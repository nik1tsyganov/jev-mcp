import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

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

/* Spend cap. The five tools sit in every session on four CLIs, and nothing on the agent
   side limits how many times an agent calls them: one call is capped at 32 questions,
   but a loop over a corpus is unbounded. This counts judgment requests for the life of
   the process and refuses past the cap with an instruction, not a silent stop.
   Raise it deliberately with TYPESAFE_MAX_REQUESTS. `listModels` is not counted: it
   spends no judgment tokens. */
const MAX_REQUESTS = Number(process.env.TYPESAFE_MAX_REQUESTS || 200);
let spent = 0;

export function spendSoFar() {
  return { requests: spent, cap: MAX_REQUESTS };
}

function chargeOne() {
  if (spent >= MAX_REQUESTS) {
    throw new Error(
      `Spend cap reached: ${spent} judgment requests in this process, cap ${MAX_REQUESTS}. ` +
      `Stop and report the count, or raise TYPESAFE_MAX_REQUESTS deliberately. ` +
      `A corpus pass should state its request count before it starts.`
    );
  }
  spent += 1;
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
  return request("/v1/systemone", {
    method: "POST",
    body: { state, model: model || DEFAULT_MODEL, questions },
  });
}

export async function listModels() {
  return request("/v1/models");
}
