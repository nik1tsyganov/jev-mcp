#!/usr/bin/env node
/**
 * Experiment-only replay of jev-ultrafast decision captures.
 *
 * Input: JSONL captures from browser_trial.py, one record per line:
 *   {id, task_id, state, questions, response, model, latency_ms}
 * `state` and `questions` are the upstream request body pieces produced by
 * jev_ultrafast/model.py `choose`. Upstream sends `instructions` objects; our
 * string-only validator cannot take those, so object instructions are replaced
 * by a deterministic JSON serialization (sorted keys, no whitespace). Original
 * and normalized request hashes are both recorded. Nothing here claims
 * byte-identical upstream behavior.
 *
 * provider=jev (default): for each selected state, 3 alternating paired
 * repetitions of one batched systemOne call (all questions) vs the same
 * questions submitted sequentially. No retries; failures stay in the report.
 * provider=laya: one local predict per selected state through createLayaClient
 * with trusted env configuration only. There is no Jev fallback in this mode.
 *
 * Dry run (no --live) parses and reports planned calls only. Inference never
 * happens without --live, and the exact call count is printed before a pass.
 *
 * Upstream pin: browser-use/jev-ultrafast@1231850a0bf1a0c0341fe408ef1668dbbfdfac46
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

export const UPSTREAM_PIN = "browser-use/jev-ultrafast@1231850a0bf1a0c0341fe408ef1668dbbfdfac46";
export const DEFAULT_LIMIT = 12;
export const REPETITIONS = 3;
const PROVIDERS = new Set(["jev", "laya"]);

// ------------------------------------------------------------------ utilities

/** Deterministic JSON: sorted object keys, no whitespace, array order kept. */
export function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  return (
    "{" +
    Object.keys(value)
      .sort()
      .map((k) => JSON.stringify(k) + ":" + canonical(value[k]))
      .join(",") +
    "}"
  );
}

export function hashOf(value) {
  return createHash("sha256").update(canonical(value)).digest("hex");
}

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Replace only non-string `instructions` with their canonical serialization.
 * Captured question objects are not mutated; the normalized copy is returned.
 */
export function normalizeInstructions(questions) {
  const normalized = JSON.parse(JSON.stringify(questions));
  let changed = 0;
  for (const q of Object.values(normalized)) {
    if (isPlainObject(q) && q.instructions !== undefined && typeof q.instructions !== "string") {
      q.instructions = canonical(q.instructions);
      changed += 1;
    }
  }
  return { questions: normalized, changed };
}

// --------------------------------------------------------------------- input

/** Parse JSONL captures. Malformed JSON aborts the run; structurally invalid
 *  records are kept as rows marked invalid and never reach selection. */
export function parseCaptures(text) {
  const records = [];
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    let record;
    try {
      record = JSON.parse(line);
    } catch (err) {
      throw new Error(`Line ${i + 1}: invalid JSON (${err.message})`);
    }
    const invalid =
      !isPlainObject(record) ? "record is not an object"
      : record.state === undefined || record.state === null ? "missing state"
      : !isPlainObject(record.questions) || Object.keys(record.questions).length === 0 ? "missing questions"
      : null;
    records.push({ line: i + 1, record, invalid });
  }
  return records;
}

/** First `limit` distinct state/questions hashes, in capture order. The
 *  original captured objects are preserved untouched. */
export function selectStates(parsed, limit = DEFAULT_LIMIT) {
  const seen = new Set();
  const selected = [];
  for (const { line, record, invalid } of parsed) {
    if (invalid) continue;
    const originalHash = hashOf({ state: record.state, questions: record.questions });
    if (seen.has(originalHash)) continue;
    seen.add(originalHash);
    const { questions: normalizedQuestions, changed } = normalizeInstructions(record.questions);
    selected.push({
      id: record.id ?? `line-${line}`,
      task_id: record.task_id ?? null,
      line,
      state: record.state,
      questions: record.questions,
      normalizedQuestions,
      normalizedInstructionsChanged: changed,
      originalHash,
      normalizedHash: hashOf({ state: record.state, questions: normalizedQuestions }),
      questionIds: Object.keys(normalizedQuestions),
      captured: { model: record.model ?? null, latency_ms: record.latency_ms ?? null },
      capturedResponse: record.response ?? null,
    });
    if (selected.length >= limit) break;
  }
  return selected;
}

// ---------------------------------------------------- upstream head semantics

/** Port of upstream model.py validate_choice: choice in ids, probabilities
 *  covering exactly ids, all values and confidence finite in [0,1], sum within
 *  0.02 of 1, and the chosen label at the argmax (1e-6 slack). */
export function validateChoiceAnswer(answer, ids) {
  try {
    const probabilities = answer.probabilities;
    const values = Object.values(probabilities);
    const numbers = [...values, answer.confidence];
    return (
      ids.includes(answer.choice) &&
      Object.keys(probabilities).length === ids.length &&
      ids.every((id) => Object.hasOwn(probabilities, id)) &&
      numbers.every((n) => typeof n === "number" && Number.isFinite(n) && 0 <= n && n <= 1) &&
      Math.abs(values.reduce((a, b) => a + b, 0) - 1) < 0.02 &&
      probabilities[answer.choice] >= Math.max(...values) - 1e-6
    );
  } catch {
    return false;
  }
}

/**
 * Upstream choose() semantics on a questions map and its answers:
 * read `operation`, then validate only the `<operation>_target` head the
 * operation selects. Unused speculative heads are never graded — upstream
 * does not act on them. An invalid answer raises upstream, so an invalid
 * operation or head leaves operation/target null here.
 */
export function analyzeUpstream(questions, answers) {
  const out = { operation: null, operationValid: null, selectedHeadId: null, selectedHeadValid: null, selectedTarget: null };
  const opQuestion = questions?.operation;
  if (!opQuestion || opQuestion.type !== "choice") return out;
  const opAnswer = answers?.operation;
  out.operationValid = validateChoiceAnswer(opAnswer, Object.keys(opQuestion.criteria ?? {}));
  out.operation = out.operationValid ? opAnswer.choice : null;
  if (!out.operation) return out;
  const headId = `${String(out.operation).toLowerCase()}_target`;
  const headQuestion = questions[headId];
  // DONE, BLOCKED and observed controls carry no target head upstream.
  if (!headQuestion || headQuestion.type !== "choice") return out;
  out.selectedHeadId = headId;
  const headAnswer = answers?.[headId];
  out.selectedHeadValid = validateChoiceAnswer(headAnswer, Object.keys(headQuestion.criteria ?? {}));
  out.selectedTarget = out.selectedHeadValid ? headAnswer.choice : null;
  return out;
}

// -------------------------------------------------------------------- planning

export function planCalls(states, provider, sequentialMode = "all") {
  const questionCounts = states.map((s) => s.questionIds.length);
  const sequential = questionCounts.reduce((a, n) => a + (sequentialMode === "selected" ? Math.min(n, 2) : n), 0);
  return {
    provider,
    states: states.length,
    repetitions: provider === "jev" ? REPETITIONS : 1,
    jevCalls: provider === "jev" ? REPETITIONS * (states.length + sequential) : 0,
    layaCalls: provider === "laya" ? states.length : 0,
    perStateQuestions: questionCounts,
    sequentialMode,
    callCountKind: sequentialMode === "selected" ? "upper-bound" : "exact",
  };
}

// ------------------------------------------------------------------ jev arms

async function timed(fn, now) {
  const started = now();
  try {
    const result = await fn();
    return { ok: true, durationMs: round1(now() - started), result };
  } catch (err) {
    return { ok: false, durationMs: round1(now() - started), error: String(err?.message ?? err), errorCode: err?.code ?? null, result: null };
  }
}

function round1(ms) {
  return Math.round(ms * 10) / 10;
}

/**
 * 3 alternating paired repetitions per state: odd reps batch-then-sequential,
 * even reps sequential-then-batch, so drift does not favor one arm. A failed
 * call is recorded and the pass continues; nothing is retried.
 */
export async function runJevComparison({ states, systemOne, now = () => performance.now(), sequentialMode = "all" }) {
  if (!["all", "selected"].includes(sequentialMode)) throw new Error("Invalid sequential mode");
  const pairs = [];
  for (const rec of states) {
    for (let rep = 0; rep < REPETITIONS; rep++) {
      const order = rep % 2 === 0 ? ["batch", "sequential"] : ["sequential", "batch"];
      const pair = { recordId: rec.id, rep: rep + 1, order, sequentialMode, batch: null, sequential: null };
      for (const arm of order) {
        if (arm === "batch") {
          const call = await timed(
            () => systemOne({ state: rec.state, questions: rec.normalizedQuestions }),
            now
          );
          const answers = call.result?.answers ?? null;
          pair.batch = {
            wallMs: call.durationMs,
            calls: [callRecord(call)],
            answers,
            analysis: analyzeUpstream(rec.normalizedQuestions, answers),
          };
        } else {
          const calls = [];
          const answers = {};
          const started = now();
          const qids = sequentialMode === "selected" ? ["operation"] : [...rec.questionIds];
          for (const qid of qids) {
            const call = await timed(
              () => systemOne({ state: rec.state, questions: { [qid]: rec.normalizedQuestions[qid] } }),
              now
            );
            calls.push(callRecord(call, qid));
            if (call.result?.answers) Object.assign(answers, call.result.answers);
            if (sequentialMode === "selected" && qid === "operation") {
              const analysis = analyzeUpstream(rec.normalizedQuestions, answers);
              if (analysis.selectedHeadId) qids.push(analysis.selectedHeadId);
            }
          }
          pair.sequential = {
            wallMs: round1(now() - started),
            calls,
            answers,
            analysis: analyzeUpstream(rec.normalizedQuestions, answers),
          };
        }
      }
      const b = pair.batch.analysis;
      const s = pair.sequential.analysis;
      // A failed arm's wall time is not a comparable sample; it stays in the
      // call denominators but never enters latency stats.
      const batchOk = pair.batch.calls.every((c) => c.ok);
      const seqOk = pair.sequential.calls.every((c) => c.ok);
      pair.latencyDeltaMs = batchOk && seqOk ? round1(pair.sequential.wallMs - pair.batch.wallMs) : null;
      pair.agreement = {
        operation: b.operation !== null && b.operation === s.operation,
        selectedTarget:
          b.selectedHeadId && s.selectedHeadId
            ? b.operation === s.operation && b.selectedTarget !== null && b.selectedTarget === s.selectedTarget
            : null,
      };
      pairs.push(pair);
    }
  }
  return pairs;
}

function callRecord(call, questionId = null) {
  return {
    questionId,
    ok: call.ok,
    durationMs: call.durationMs,
    model: call.result?.model ?? null,
    usage: call.result?.usage ?? null,
    error: call.ok ? null : call.error,
  };
}

export function summarizeJev(pairs) {
  const deltas = pairs.map((p) => p.latencyDeltaMs).filter((d) => d !== null).sort((a, b) => a - b);
  const calls = pairs.flatMap((p) => [...p.batch.calls, ...p.sequential.calls]);
  const failed = calls.filter((c) => !c.ok);
  const targetPairs = pairs.filter((p) => p.agreement.selectedTarget !== null);
  return {
    pairs: pairs.length,
    callsAttempted: calls.length,
    callsFailed: failed.length,
    failures: failed.map((c) => ({ questionId: c.questionId, error: c.error })),
    pairedLatencyDeltaMs: deltas,
    medianDeltaMs: deltas.length ? median(deltas) : null,
    minDeltaMs: deltas.length ? deltas[0] : null,
    maxDeltaMs: deltas.length ? deltas[deltas.length - 1] : null,
    operationAgreementRate: rate(pairs.filter((p) => p.agreement.operation).length, pairs.length),
    selectedTargetAgreementRate: targetPairs.length
      ? rate(targetPairs.filter((p) => p.agreement.selectedTarget).length, targetPairs.length)
      : null,
    selectedTargetPairs: targetPairs.length,
  };
}

function median(sorted) {
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : round1((sorted[mid - 1] + sorted[mid]) / 2);
}

function rate(part, whole) {
  return whole ? Math.round((part / whole) * 1000) / 1000 : null;
}

// ------------------------------------------------------------------ laya arm

/** Trusted env configuration only — mirrors envLayaConfig in
 *  src/decision-service.js. Absent LAYA_MODEL_DIR means not configured. */
export function layaEnvConfig(env) {
  const modelPath = env.LAYA_MODEL_DIR;
  if (!modelPath) return null;
  return {
    python: env.LAYA_PYTHON,
    modelPath,
    checkpoint: env.LAYA_CHECKPOINT,
    revision: env.LAYA_MODEL_REVISION,
    timeoutMs: env.LAYA_TIMEOUT_MS ? Number(env.LAYA_TIMEOUT_MS) : undefined,
    maxQueue: env.LAYA_MAX_QUEUE ? Number(env.LAYA_MAX_QUEUE) : undefined,
  };
}

/**
 * One predict per selected state on identical normalized payloads. The first
 * call carries worker spawn and model load; later calls are warm. Errors —
 * including input_truncated and option-budget rejections — stay in the rows.
 */
export async function runLayaReplay({ states, client, now = () => performance.now() }) {
  const status = safeStatus(client);
  const rows = [];
  for (const [index, rec] of states.entries()) {
    const call = await timed(() => client.predict({ state: rec.state, questions: rec.normalizedQuestions }), now);
    const row = {
      recordId: rec.id,
      first: index === 0,
      ok: call.ok,
      durationMs: call.durationMs,
      workerMs: call.result?.elapsed_ms ?? null,
      model: call.result?.model ?? null,
      checkpoint: call.result?.checkpoint ?? null,
      revision: call.result?.revision ?? null,
      checkpointMatch: null,
      schemaCompatible: null,
      heads: {},
      error: call.ok ? null : call.error,
      errorCode: call.ok ? null : (call.errorCode ?? null),
    };
    if (call.ok) {
      const pred = call.result;
      row.checkpointMatch =
        (status?.checkpoint == null || pred.checkpoint === status.checkpoint) &&
        (status?.revision == null || pred.revision === status.revision);
      row.schemaCompatible = schemaCompatible(rec.normalizedQuestions, pred.answers);
      for (const [qid, q] of Object.entries(rec.normalizedQuestions)) {
        if (q.type !== "choice") continue;
        const ids = Object.keys(q.criteria ?? {});
        const answer = pred.answers?.[qid];
        row.heads[qid] = {
          choice: answer?.choice ?? null,
          argmaxAligned: argmaxAligned(answer),
          upstreamValid: validateChoiceAnswer(answer, ids),
        };
      }
    }
    rows.push(row);
  }
  return { status, rows };
}

function safeStatus(client) {
  try {
    return typeof client.status === "function" ? client.status() : null;
  } catch {
    return null;
  }
}

function schemaCompatible(questions, answers) {
  if (!answers || typeof answers !== "object") return false;
  for (const [qid, q] of Object.entries(questions)) {
    const a = answers[qid];
    if (!a || typeof a !== "object" || a.type !== q.type) return false;
  }
  return true;
}

function argmaxAligned(answer) {
  const probs = answer?.probabilities;
  if (!probs || typeof probs !== "object" || typeof answer.choice !== "string") return null;
  const values = Object.values(probs).filter((n) => typeof n === "number" && Number.isFinite(n));
  if (!values.length || !Object.hasOwn(probs, answer.choice)) return false;
  return probs[answer.choice] >= Math.max(...values) - 1e-6;
}

export function summarizeLaya({ rows }) {
  const warm = rows.filter((r) => !r.first && r.ok).map((r) => r.durationMs).sort((a, b) => a - b);
  return {
    attempted: rows.length,
    succeeded: rows.filter((r) => r.ok).length,
    firstCallMs: rows[0]?.durationMs ?? null,
    warmMs: warm,
    medianWarmMs: warm.length ? median(warm) : null,
    truncationRejections: rows.filter((r) => r.errorCode === "input_truncated").length,
    checkpointMismatches: rows.filter((r) => r.checkpointMatch === false).length,
    schemaIncompatible: rows.filter((r) => r.schemaCompatible === false).length,
    upstreamInvalidHeads: rows.flatMap((r) =>
      Object.entries(r.heads).filter(([, h]) => h.upstreamValid === false).map(([qid]) => ({ recordId: r.recordId, qid }))
    ),
  };
}

// ------------------------------------------------------------------------ CLI

const USAGE = `Usage: node experiments/jev-ultrafast/replay.mjs --input PATH [--provider jev|laya] [--limit N] [--selected-only] [--live]

  --input PATH      JSONL captures from browser_trial.py (required)
  --provider        jev (default) or laya. laya never falls back to Jev.
  --limit N         first N distinct state/questions hashes (default ${DEFAULT_LIMIT})
  --selected-only   sequential arm asks operation, then only its selected target
  --live            required for any inference; dry run only parses and plans
`;

export function parseArgs(argv) {
  const args = { input: null, provider: "jev", limit: DEFAULT_LIMIT, live: false, help: false, selectedOnly: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--input") args.input = argv[++i];
    else if (a === "--provider") args.provider = argv[++i];
    else if (a === "--limit") args.limit = Number(argv[++i]);
    else if (a === "--live") args.live = true;
    else if (a === "--selected-only") args.selectedOnly = true;
    else if (a === "--help" || a === "-h") args.help = true;
    else throw new Error(`Unknown argument: ${a}`);
  }
  if (args.help) return args;
  if (!args.input) throw new Error("--input PATH is required.");
  if (!PROVIDERS.has(args.provider)) throw new Error(`Unknown provider \`${args.provider}\`; expected jev or laya.`);
  if (!Number.isInteger(args.limit) || args.limit < 1) throw new Error("--limit must be a positive integer.");
  return args;
}

function recordRows(states) {
  return states.map((s) => ({
    id: s.id,
    task_id: s.task_id,
    line: s.line,
    questionIds: s.questionIds,
    // The exact payload sent on every call for this record; call rows
    // reference it by recordId (+ questionId for sequential calls).
    normalizedRequest: { state: s.state, questions: s.normalizedQuestions },
    originalHash: s.originalHash,
    normalizedHash: s.normalizedHash,
    normalizedInstructionsChanged: s.normalizedInstructionsChanged,
    capturedModel: s.captured.model,
    capturedLatencyMs: s.captured.latency_ms,
    capturedAnalysis: s.capturedResponse?.answers || s.capturedResponse?.raw_answers
      ? analyzeUpstream(s.normalizedQuestions, s.capturedResponse.answers ?? s.capturedResponse.raw_answers)
      : null,
  }));
}

export async function main(argv, env = process.env, stderr = (s) => process.stderr.write(s + "\n")) {
  const args = parseArgs(argv);
  if (args.help) {
    stderr(USAGE.trim());
    return 0;
  }
  const parsed = parseCaptures(readFileSync(args.input, "utf8"));
  const states = selectStates(parsed, args.limit);
  const invalidRows = parsed.filter((p) => p.invalid).map((p) => ({ line: p.line, invalid: p.invalid }));
  const sequentialMode = args.selectedOnly ? "selected" : "all";
  const plan = planCalls(states, args.provider, sequentialMode);
  if (args.provider === "laya") {
    const cfg = layaEnvConfig(env);
    plan.layaConfigured = Boolean(cfg && env.LAYA_PYTHON && env.LAYA_CHECKPOINT && env.LAYA_MODEL_REVISION);
    plan.layaConfigSource = "env: LAYA_MODEL_DIR/LAYA_CHECKPOINT/LAYA_MODEL_REVISION (+ LAYA_PYTHON)";
  }

  const report = {
    experiment: "jev-ultrafast paired batching replay",
    upstream: UPSTREAM_PIN,
    live: args.live,
    provider: args.provider,
    generatedAt: new Date().toISOString(),
    plan,
    invalidRecords: invalidRows,
    records: recordRows(states),
    note: "Object instructions were normalized to canonical JSON strings for the local validator; original and normalized hashes are recorded. Upstream behavior is not claimed byte-identical.",
  };

  if (!args.live) {
    stderr(`dry run: ${parsed.length} records parsed, ${states.length} distinct states selected (limit ${args.limit}).`);
    stderr(
      args.provider === "jev"
        ? `planned jev calls (${plan.callCountKind}): ${plan.jevCalls}; ${sequentialMode} sequential heads.`
        : `planned laya predict calls: ${plan.layaCalls}. laya configured: ${plan.layaConfigured}.`
    );
    process.stdout.write(JSON.stringify({ status: "dry-run", ...report }, null, 2) + "\n");
    return 0;
  }

  if (args.provider === "laya") {
    const cfg = layaEnvConfig(env);
    const missingEnv = [
      !cfg && "LAYA_MODEL_DIR",
      !env.LAYA_PYTHON && "LAYA_PYTHON",
      !env.LAYA_CHECKPOINT && "LAYA_CHECKPOINT",
      !env.LAYA_MODEL_REVISION && "LAYA_MODEL_REVISION",
    ].filter(Boolean);
    if (missingEnv.length) {
      stderr(`provider=laya is not configured: missing ${missingEnv.join(", ")}. No Jev fallback exists in this mode.`);
      process.stdout.write(
        JSON.stringify({ status: "not-run", reason: "laya-not-configured", missingEnv, ...report }, null, 2) + "\n"
      );
      return 2;
    }
    stderr(`planned laya predict calls: ${plan.layaCalls} (one per selected state; no Jev calls).`);
    const { createLayaClient } = await import("../../src/laya-client.js");
    const client = createLayaClient(cfg);
    try {
      const laya = await runLayaReplay({ states, client });
      stderr(`laya pass complete: ${laya.rows.filter((r) => r.ok).length}/${laya.rows.length} calls succeeded.`);
      process.stdout.write(
        JSON.stringify({ status: "complete", ...report, laya: { status: laya.status, rows: laya.rows, summary: summarizeLaya(laya) } }, null, 2) + "\n"
      );
    } finally {
      try {
        client.close();
      } catch {
        /* best effort */
      }
    }
    return 0;
  }

  stderr(`planned jev calls (${plan.callCountKind}): ${plan.jevCalls} across ${plan.states} states x ${plan.repetitions} paired reps.`);
  const { systemOne } = await import("./logged-client.mjs");
  const pairs = await runJevComparison({ states, systemOne, sequentialMode });
  const summary = summarizeJev(pairs);
  stderr(`jev pass complete: ${summary.callsAttempted} calls, ${summary.callsFailed} failed.`);
  process.stdout.write(JSON.stringify({ status: "complete", ...report, pairs, summary }, null, 2) + "\n");
  return 0;
}

const invoked = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invoked) {
  main(process.argv.slice(2))
    .then((code) => {
      process.exitCode = code;
    })
    .catch((err) => {
      process.stderr.write(`replay failed: ${err?.message ?? err}\n`);
      process.exitCode = 1;
    });
}
