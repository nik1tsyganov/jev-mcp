import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { TypeSafeClient } from "@typesafe-ai/sdk";
import { validateQuestions } from "./questions.js";

export const DEFAULT_MODEL = process.env.TYPESAFE_DEFAULT_MODEL || "jev-latest";
export const KEY_FILE = join(homedir(), ".config", "typesafe", "env.sh");

export function baseUrl() {
  return (process.env.TYPESAFE_BASE_URL || "https://api.typesafe.ai").replace(/\/+$/, "");
}

let cachedKey = null;
let cachedIdentity = null;

/** "app" trusts the Droppy-provided key only; anything else keeps the legacy
 *  resolution. Unrecognized values fall back to "default" rather than widening scope. */
export function credentialScope() {
  return process.env.DROPPY_CREDENTIAL_SCOPE === "app" ? "app" : "default";
}

/** Resolves the API key. Never returns it in an error message or log line.
 *  Scope "app" reads DROPPY_JEV_API_KEY alone: never TYPESAFE_API_KEY, never a
 *  previously cached legacy credential, never ~/.config/typesafe/env.sh. The
 *  cache key records the scope and the env value it came from, so a scope or
 *  key change cannot inherit a stale credential. */
export function resolveApiKey() {
  const scope = credentialScope();
  const envValue = scope === "app" ? process.env.DROPPY_JEV_API_KEY : process.env.TYPESAFE_API_KEY;
  const identity = `${scope}${envValue ?? ""}`;
  if (cachedKey && cachedIdentity === identity) return cachedKey;
  const trimmed = typeof envValue === "string" ? envValue.trim() : "";
  if (!trimmed) {
    if (scope === "app") {
      throw new Error("DROPPY_JEV_API_KEY is not set; credential scope 'app' uses no other credential source.");
    }
    let contents;
    try {
      contents = readFileSync(KEY_FILE, "utf8");
    } catch {
      throw new Error(`TYPESAFE_API_KEY is not set and ${KEY_FILE} could not be read.`);
    }
    const match = contents.match(/^\s*export\s+TYPESAFE_API_KEY=["']?([^"'\s]+)["']?\s*$/m);
    if (!match || !match[1].trim()) throw new Error(`No TYPESAFE_API_KEY export line found in ${KEY_FILE}.`);
    cachedKey = match[1].trim();
  } else {
    cachedKey = trimmed;
  }
  cachedIdentity = identity;
  return cachedKey;
}

/** Whether a usable key resolves in the current scope. Boolean only; the key
 *  itself is never returned or logged. */
export function credentialAvailable() {
  try {
    return Boolean(resolveApiKey());
  } catch {
    return false;
  }
}

/** Strips the key from any text before it can reach a log, a tool result or a user.
 *  Measured 2026-09-19: an invalid header value made undici echo the whole
 *  `Bearer <key>` back in err.message, and that message was interpolated into the
 *  thrown Error. A credential must never be able to ride out on an error path. */
export function redact(text) {
  let out = String(text);
  for (const key of [cachedKey, process.env.DROPPY_JEV_API_KEY, process.env.TYPESAFE_API_KEY]) {
    const trimmed = typeof key === "string" ? key.trim() : "";
    if (trimmed && trimmed.length > 4) out = out.split(trimmed).join("[redacted]");
  }
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

/* Schema 2 (2026-09-25) adds who called and how long it took, so a week of normal
   use can be scored per call site: source, tool, client, purpose, cwd, pid, latency_ms, ok.
   `purpose` is the caller's own tag; it is logged here and never sent to Jev.
   A failed call is logged too (ok:false, no tokens) so error rates are visible. */
function recordSpend(model, questionCount, usage, answers, { caller = {}, latencyMs = null, error = null } = {}) {
  const used = usage || {};
  inputTokens += used.input_tokens || 0;
  outputTokens += used.output_tokens || 0;
  try {
    mkdirSync(dirname(SPEND_LOG), { recursive: true });
    appendFileSync(SPEND_LOG, JSON.stringify({
      ts: new Date().toISOString(),
      schema: 2,
      source: "mcp",
      tool: caller.tool ?? null,
      client: caller.client ?? null,
      purpose: caller.purpose ?? null,
      cwd: process.cwd(),
      pid: process.pid,
      ok: error === null,
      error,
      latency_ms: latencyMs,
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

// The SDK handles fetch, timeouts, and retries natively.
// As defined in @typesafe-ai/sdk (src/retry.ts), the SDK retries HTTP status codes:
// 408 (Request Timeout), 429 (Too Many Requests), and 500-599 (all 5xx server errors).
// It also retries connection errors (APIConnectionError) and request timeouts (APITimeoutError).

let clientInstance = null;
let clientIdentity = null;

function getClient() {
  if (process.env.DROPPY_DECISION_MODE === "local") {
    throw new Error("DROPPY_DECISION_MODE=local prohibits Jev calls.");
  }
  const apiKey = resolveApiKey();
  const identity = JSON.stringify([credentialScope(), apiKey, baseUrl()]);
  if (!clientInstance || clientIdentity !== identity) {
    clientInstance = new TypeSafeClient({
      apiKey,
      baseURL: baseUrl(),
      timeout: 30000,
    });
    clientIdentity = identity;
  }
  return clientInstance;
}

export function _resetClient() {
  clientInstance = null;
  clientIdentity = null;
  cachedKey = null;
  cachedIdentity = null;
}

function redactError(err) {
  const redacted = redact(err?.message ?? String(err));
  if (err && typeof err === "object") {
    try {
      err.message = redacted;
      if (typeof err.stack === "string") {
        err.stack = redact(err.stack);
      }
      return err;
    } catch {
      // In case err.message is read-only
    }
    const custom = new Error(redacted);
    custom.name = err.name || err.constructor?.name || "Error";
    if (err.status !== undefined) custom.status = err.status;
    if (err.stack) custom.stack = redact(err.stack);
    Object.setPrototypeOf(custom, Object.getPrototypeOf(err));
    return custom;
  }
  return new Error(redacted);
}

export async function systemOne({ state, questions, model, caller }) {
  const validated = validateQuestions(questions);
  chargeOne();
  const client = getClient();
  const count = Object.keys(validated || {}).length;
  const started = performance.now();
  let result;
  try {
    result = await client.systemOne({
      state,
      questions: validated,
      model: model || DEFAULT_MODEL,
    });
  } catch (err) {
    // Only the error class is logged: a message can carry request text or a credential.
    recordSpend(model || DEFAULT_MODEL, count, null, null, {
      caller, latencyMs: Math.round(performance.now() - started), error: err?.constructor?.name || "Error",
    });
    throw redactError(err);
  }
  recordSpend(
    result?.model ?? (model || DEFAULT_MODEL),
    count,
    result?.usage,
    result?.answers,
    { caller, latencyMs: Math.round(performance.now() - started) }
  );
  return result;
}

export async function listModels() {
  const client = getClient();
  let models;
  try {
    models = await client.models.list();
  } catch (err) {
    throw redactError(err);
  }
  return { models };
}
