/**
 * Local, offline Laya-MLX client.
 *
 * One persistent worker process holds one loaded model. `predict` speaks
 * newline-delimited JSON over the worker's stdio; it never calls Jev and never
 * touches the network. Configuration comes from this process only, so a
 * prediction payload cannot choose a checkpoint or a remote download.
 */
import { spawn as defaultSpawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { validateQuestions } from "./questions.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const WORKER_PATH = join(HERE, "..", "tools", "laya_worker.py");

/** Child environment allowlist: OS/runtime/cache only. Credentials never cross. */
const ENV_ALLOWLIST = [
  "PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "LC_CTYPE",
  "USER", "LOGNAME", "SHELL", "XDG_CACHE_HOME", "XDG_DATA_HOME",
  "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV",
  "HF_HOME", "HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE",
  "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE",
  "HF_HUB_DISABLE_TELEMETRY", "USE_TF", "USE_TORCH", "TOKENIZERS_PARALLELISM",
];

const MAX_RESPONSE_BYTES = 4 * 1024 * 1024;

/** Strips credential-shaped text and caps length before any message is surfaced. */
export function sanitizeLayaError(text) {
  let out = String(text ?? "");
  out = out.replace(/Bearer\s+\S+/g, "Bearer [redacted]");
  out = out.replace(/\b(hf_|sk-)[A-Za-z0-9_\-]{8,}/g, "[redacted]");
  out = out.replace(/(api[_-]?key|token|authorization)\s*[=:]\s*\S+/gi, "$1=[redacted]");
  return out.slice(0, 500);
}

function pick(opts, key, envKey) {
  if (opts[key] !== undefined) return opts[key];
  return process.env[envKey];
}

export function createLayaClient(opts = {}) {
  const python = pick(opts, "python", "LAYA_PYTHON") ?? null;
  const modelPath = pick(opts, "modelPath", "LAYA_MODEL_DIR") ?? null;
  const checkpoint = pick(opts, "checkpoint", "LAYA_CHECKPOINT") ?? null;
  const revision = pick(opts, "revision", "LAYA_MODEL_REVISION") ?? null;
  const timeoutMs = opts.timeoutMs ?? 30000;
  const maxQueue = opts.maxQueue ?? 8;
  if (!Number.isInteger(timeoutMs) || timeoutMs <= 0 || timeoutMs > 2147483647 ||
      !Number.isInteger(maxQueue) || maxQueue < 1) {
    throw new Error("Invalid local timeout or queue limit.");
  }
  const spawnImpl = opts.spawn ?? defaultSpawn;
  const workerPath = opts.workerPath ?? WORKER_PATH;

  let child = null;
  let readyPromise = null;
  let readyResolve = null;
  let readyReject = null;
  let deadReason = null;
  let closed = false;
  let stdoutBuf = "";
  let stderrTail = "";
  let nextId = 1;
  const pending = [];
  let inFlight = null;

  function missingConfig() {
    const missing = [];
    if (!python) missing.push("python");
    if (!modelPath) missing.push("modelPath");
    if (!checkpoint) missing.push("checkpoint");
    if (!revision) missing.push("revision");
    return missing;
  }

  function status() {
    const missing = missingConfig();
    if (missing.length) {
      return {
        available: false,
        checkpoint,
        revision,
        reason: `not configured: missing ${missing.join(", ")}`,
      };
    }
    if (closed) return { available: false, checkpoint, revision, reason: "client is closed" };
    if (deadReason) return { available: false, checkpoint, revision, reason: deadReason };
    return { available: true, checkpoint, revision, reason: null };
  }

  function childEnv() {
    const env = {};
    for (const key of ENV_ALLOWLIST) {
      if (process.env[key] !== undefined) env[key] = process.env[key];
    }
    env.HF_HUB_OFFLINE = "1";
    env.TRANSFORMERS_OFFLINE = "1";
    env.HF_DATASETS_OFFLINE = "1";
    env.HF_HUB_DISABLE_TELEMETRY = "1";
    env.USE_TF = "0";
    env.PYTHONUNBUFFERED = "1";
    return env;
  }

  function errorFor(message, code) {
    const err = new Error(sanitizeLayaError(message));
    if (code) err.code = code;
    return err;
  }

  function settle(request, err, value) {
    if (!request || request.settled) return;
    request.settled = true;
    if (request.timer) clearTimeout(request.timer);
    if (request === inFlight) inFlight = null;
    if (err) request.reject(err);
    else request.resolve(value);
  }

  function failAll(error) {
    if (inFlight) settle(inFlight, error);
    while (pending.length) settle(pending.shift(), error);
  }

  function markDead(message, error) {
    if (deadReason && !child) return;
    deadReason = sanitizeLayaError(message);
    child = null;
    const err = error ?? errorFor(deadReason);
    const reject = readyReject;
    readyPromise = null;
    readyResolve = readyReject = null;
    if (reject) reject(err);
    failAll(err);
  }

  function killWorker(message, error) {
    const dying = child;
    markDead(message, error);
    if (dying) {
      try {
        dying.kill("SIGKILL");
      } catch {
        /* already gone */
      }
    }
  }

  function spawnWorker() {
    const args = [
      workerPath,
      "--model-dir", modelPath,
      "--checkpoint", checkpoint,
      "--revision", revision,
    ];
    readyPromise = new Promise((resolve, reject) => {
      readyResolve = resolve;
      readyReject = reject;
    });
    const startup = readyPromise;
    let proc;
    try {
      proc = spawnImpl(python, args, { env: childEnv(), stdio: ["pipe", "pipe", "pipe"], shell: false });
    } catch (err) {
      markDead(`worker spawn failed: ${err?.message ?? err}`);
      return startup;
    }
    child = proc;
    proc.stdout.setEncoding("utf8");
    proc.stdout.on("data", (chunk) => { if (child === proc) onStdout(chunk); });
    proc.stdin.on("error", () => { if (child === proc) killWorker("worker write failed"); });
    proc.stderr.setEncoding("utf8");
    proc.stderr.on("data", (chunk) => {
      stderrTail = (stderrTail + chunk).slice(-2000);
    });
    proc.on("error", () => { if (child === proc) killWorker("worker spawn failed"); });
    proc.on("exit", (code, signal) => {
      if (child !== proc) return;
      const tail = stderrTail.trim().split("\n").slice(-3).join(" | ");
      markDead(deadReason || `worker exited (code=${code} signal=${signal})${tail ? `: ${tail}` : ""}`);
    });
    return startup;
  }

  function onStdout(chunk) {
    stdoutBuf += chunk;
    if (Buffer.byteLength(stdoutBuf) > MAX_RESPONSE_BYTES) {
      killWorker("protocol error: worker response exceeded the size limit");
      return;
    }
    let index;
    while ((index = stdoutBuf.indexOf("\n")) !== -1) {
      const line = stdoutBuf.slice(0, index);
      stdoutBuf = stdoutBuf.slice(index + 1);
      if (line.trim()) handleLine(line);
      if (!child) return;
    }
  }

  function handleLine(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      killWorker("protocol error: worker wrote a non-JSON line");
      return;
    }
    if (!message || typeof message !== "object") {
      killWorker("protocol error: invalid message");
      return;
    }
    if (message.type === "ready") {
      if (message.checkpoint !== checkpoint || message.revision !== revision) {
        killWorker("protocol error: worker identity mismatch");
        return;
      }
      if (readyResolve) {
        const resolve = readyResolve;
        readyResolve = readyReject = null;
        resolve(message);
      }
      return;
    }
    if (message.type === "fatal") {
      killWorker(message.error?.message || "worker reported a fatal error");
      return;
    }
    if (message.type === "result" || message.type === "error") {
      if (!inFlight || message.id !== inFlight.id) {
        killWorker("protocol error: response id does not match the in-flight request");
        return;
      }
      const request = inFlight;
      if (message.type === "error") {
        settle(request, errorFor(message.error?.message || "worker error", message.error?.code));
        pump();
      } else {
        try {
          validateEnvelope(message.result, request.questions);
          settle(request, null, message.result);
        } catch (err) {
          settle(request, err);
        }
        pump();
      }
      return;
    }
    killWorker("protocol error: unknown worker message");
  }

  function validateEnvelope(result, questions) {
    if (!result || typeof result !== "object") {
      throw errorFor("worker result is not an object", "invalid_output");
    }
    if (typeof result.model !== "string" || !result.model) {
      throw errorFor("worker result has no model identity", "invalid_output");
    }
    if (result.checkpoint !== checkpoint || result.revision !== revision || result.model !== `${checkpoint}@${revision}`) {
      throw errorFor("worker result identity does not match the configured checkpoint", "invalid_output");
    }
    if (!result.usage || typeof result.usage !== "object") {
      throw errorFor("worker result has no usage", "invalid_output");
    }
    const answers = result.answers;
    const wanted = Object.keys(questions);
    if (!answers || typeof answers !== "object" || Object.keys(answers).length !== wanted.length) {
      throw errorFor("worker result answers do not cover the requested questions", "invalid_output");
    }
    for (const qid of wanted) {
      if (!Object.prototype.hasOwnProperty.call(answers, qid)) {
        throw errorFor(`worker result is missing an answer for ${qid}`, "invalid_output");
      }
    }
  }

  function writeRequest(request) {
    try {
      child.stdin.write(request.line + "\n");
    } catch (err) {
      killWorker("worker write failed", errorFor("worker write failed", "transport"));
    }
  }

  async function ensureWorker() {
    if (closed) throw errorFor("client is closed", "closed");
    if (child && !deadReason) return readyPromise;
    if (!readyPromise) {
      deadReason = null;
      stdoutBuf = stderrTail = "";
      return spawnWorker();
    }
    await readyPromise;
  }

  function pump() {
    if (inFlight || closed || !pending.length) return;
    const request = pending.shift();
    inFlight = request;
    request.timer = setTimeout(() => {
      killWorker(`laya worker timed out after ${timeoutMs} ms`, errorFor(
        `laya worker timed out after ${timeoutMs} ms`, "timeout"));
    }, timeoutMs);
    ensureWorker().then(
      () => {
        if (!request.settled) writeRequest(request);
      },
      (err) => {
        settle(request, err);
        pump();
      }
    );
  }

  function predict({ state, questions } = {}) {
    return new Promise((resolve, reject) => {
      if (closed) return reject(errorFor("client is closed", "closed"));
      const missing = missingConfig();
      if (missing.length) {
        return reject(errorFor(`laya client is not configured: missing ${missing.join(", ")}`, "unconfigured"));
      }
      let validated, line;
      try {
        validated = validateQuestions(questions);
        if (state === undefined || state === null || !["string", "object"].includes(typeof state)) {
          throw new Error("state must be a string, object or array");
        }
        line = JSON.stringify({ id: nextId, op: "predict", state, questions: validated });
        if (Buffer.byteLength(line) >= MAX_RESPONSE_BYTES) throw new Error("request exceeds size limit");
      } catch (err) {
        return reject(errorFor(err.message, "invalid_request"));
      }
      if (pending.length >= maxQueue) {
        return reject(errorFor(`laya client queue is full (${maxQueue})`, "queue_full"));
      }
      pending.push({ id: nextId++, line, questions: JSON.parse(line).questions, resolve, reject, settled: false, timer: null });
      pump();
    });
  }

  function close() {
    if (closed) return;
    closed = true;
    killWorker("client is closed", errorFor("client is closed", "closed"));
  }

  return { predict, status, close };
}
