import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export const DEFAULT_MODEL = process.env.TYPESAFE_DEFAULT_MODEL || "jev-latest";
export const KEY_FILE = join(homedir(), ".config", "typesafe", "env.sh");

export function baseUrl() {
  return (process.env.TYPESAFE_BASE_URL || "https://api.typesafe.ai").replace(/\/+$/, "");
}

let cachedKey = null;

/** Resolves the API key. Never returns it in an error message or log line. */
export function resolveApiKey() {
  if (cachedKey) return cachedKey;
  if (process.env.TYPESAFE_API_KEY) {
    cachedKey = process.env.TYPESAFE_API_KEY;
    return cachedKey;
  }
  let contents;
  try {
    contents = readFileSync(KEY_FILE, "utf8");
  } catch {
    throw new Error(`TYPESAFE_API_KEY is not set and ${KEY_FILE} could not be read.`);
  }
  const match = contents.match(/^\s*export\s+TYPESAFE_API_KEY=["']?([^"'\s]+)["']?\s*$/m);
  if (!match) throw new Error(`No TYPESAFE_API_KEY export line found in ${KEY_FILE}.`);
  cachedKey = match[1];
  return cachedKey;
}

/** Strips the key from any text before it can reach a log, a tool result or a user.
 *  Measured 2026-09-19: an invalid header value made undici echo the whole
 *  `Bearer <key>` back in err.message, and that message was interpolated into the
 *  thrown Error. A credential must never be able to ride out on an error path. */
function redact(text) {
  const key = cachedKey || process.env.TYPESAFE_API_KEY;
  let out = String(text);
  if (key && key.length > 4) out = out.split(key).join("[redacted]");
  return out.replace(/Bearer\s+\S+/g, "Bearer [redacted]");
}

/* Spend visibility, not a budget. Jev is cheap and the owner has said cost is not the
   constraint; the standing rule is different - never loop a corpus silently, and state
   the request count. So this counts, logs and warns, and only refuses at a number no
   honest pass reaches. Raise or disable with TYPESAFE_MAX_REQUESTS.
   `listModels` is not counted: it spends no judgment tokens. */
const MAX_REQUESTS = Number(process.env.TYPESAFE_MAX_REQUESTS || 5000);
const WARN_EVERY = Number(process.env.TYPESAFE_WARN_EVERY || 50);
const SPEND_LOG = process.env.TYPESAFE_SPEND_LOG
  || join(homedir(), ".claude", "docs", "telemetry", "jev-spend.jsonl");
let spent = 0;
let inputTokens = 0;
let outputTokens = 0;

export function spendSoFar() {
  return { requests: spent, inputTokens, outputTokens, cap: MAX_REQUESTS };
}

function chargeOne() {
  if (spent >= MAX_REQUESTS) {
    throw new Error(
      `Runaway guard: ${spent} judgment requests in one process, limit ${MAX_REQUESTS}. ` +
      `This is not a budget - it is a loop that nobody is reading. Stop and report the ` +
      `count, or raise TYPESAFE_MAX_REQUESTS deliberately.`
    );
  }
  spent += 1;
  if (WARN_EVERY > 0 && spent % WARN_EVERY === 0) {
    process.stderr.write(`jev: ${spent} requests so far this process, ${inputTokens} input tokens.\n`);
  }
}

/** One line per judgment, so a session can answer "what did that cost?" afterwards.
    Never throws: telemetry must not be able to fail a call. */
function summarise(answers) {
  /* The gate has to be retunable later, so record what came back, not only the bill:
     probabilities and confidence are what a false positive is reviewed against. */
  const out = {};
  for (const [id, a] of Object.entries(answers || {})) {
    if (!a || typeof a !== "object") continue;
    out[id] = a.type === "noul" ? { noul: a.noul }
      : a.type === "choice" ? { choice: a.choice, confidence: a.confidence }
      : a.type === "score" ? { score: a.score, confidence: a.confidence }
      : { type: a.type };
  }
  return out;
}

function recordSpend(model, questionCount, usage, answers) {
  const used = usage || {};
  inputTokens += used.input_tokens || 0;
  outputTokens += used.output_tokens || 0;
  try {
    mkdirSync(dirname(SPEND_LOG), { recursive: true });
    appendFileSync(SPEND_LOG, JSON.stringify({
      ts: new Date().toISOString(),
      model,
      questions: questionCount,
      input_tokens: used.input_tokens ?? null,
      output_tokens: used.output_tokens ?? null,
      request_in_process: spent,
      answers: summarise(answers),
    }) + "\n");
  } catch {
    /* a read-only or missing telemetry dir must not break a judgment */
  }
}

const RETRYABLE = new Set([429, 529]);
const MAX_ATTEMPTS = 3;
const BACKOFF_BASE_MS = 500;
const TIMEOUT_MS = 30_000;

async function request(path, { method = "GET", body } = {}) {
  const key = resolveApiKey();
  let lastError;
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    if (attempt > 0) {
      const wait = BACKOFF_BASE_MS * 2 ** (attempt - 1) + Math.floor(Math.random() * 250);
      await new Promise((r) => setTimeout(r, wait));
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    let res;
    try {
      res = await fetch(`${baseUrl()}${path}`, {
        method,
        headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (err) {
      // Network fault or the 30s abort: worth one more attempt.
      lastError = new Error(redact(`Request to ${path} failed: ${err.message}`));
      continue;
    } finally {
      clearTimeout(timer);
    }
    if (res.ok) return await res.json();
    const text = (await res.text()).slice(0, 500);
    const httpError = new Error(redact(`HTTP ${res.status}: ${text}`));
    if (!RETRYABLE.has(res.status)) throw httpError;
    lastError = httpError;
  }
  throw lastError ?? new Error(`Request to ${path} failed with no error recorded.`);
}

export async function systemOne({ state, questions, model }) {
  chargeOne();
  const result = await request("/v1/systemone", {
    method: "POST",
    body: { state, model: model || DEFAULT_MODEL, questions },
  });
  recordSpend(result?.model ?? (model || DEFAULT_MODEL), Object.keys(questions || {}).length, result?.usage, result?.answers);
  return result;
}

export async function listModels() {
  return request("/v1/models");
}
