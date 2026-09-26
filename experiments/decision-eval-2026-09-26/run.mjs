#!/usr/bin/env node
// Runs every case in cases-*.jsonl against one provider, one request per case,
// and appends one result line per case. See README.md.
import { appendFileSync, existsSync, globSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";
import { validateQuestions } from "../../src/questions.js";
import { questionsFingerprint } from "../../src/provider-policy.js";

const here = dirname(fileURLToPath(import.meta.url));
const V2 = "technical-bookmark-topic-v2";

const { values: args } = parseArgs({
  options: {
    provider: { type: "string" },
    cases: { type: "string", default: "cases-*.jsonl" },
    out: { type: "string" },
    limit: { type: "string" },
    concurrency: { type: "string" },
    yes: { type: "boolean", default: false },
    "laya-service": { type: "boolean", default: false },
  },
});
if (!["jev", "laya"].includes(args.provider)) {
  console.error("usage: node run.mjs --provider jev|laya [--cases GLOB] [--out FILE] [--limit N] [--concurrency N] --yes");
  process.exit(2);
}
const provider = args.provider;
const outPath = resolve(args.out ?? join(here, `results-${provider}.jsonl`));
// Laya runs one local worker; parallel asks would only queue behind it.
const concurrency = provider === "laya" ? 1 : Math.max(1, Number(args.concurrency ?? 4));

const readJsonl = (path) => readFileSync(path, "utf8").split("\n").filter((l) => l.trim()).map((l) => JSON.parse(l));

const caseFiles = globSync(args.cases, { cwd: here }).sort().map((f) => resolve(here, f));
if (!caseFiles.length) {
  console.error(`No case files match ${args.cases} (relative to ${here}).`);
  process.exit(2);
}
let cases = caseFiles.flatMap(readJsonl);
const done = new Set(existsSync(outPath) ? readJsonl(outPath).map((r) => r.id) : []);
cases = cases.filter((c) => !done.has(c.id));
if (args.limit) cases = cases.slice(0, Number(args.limit));

const write = (row) => appendFileSync(outPath, JSON.stringify({ provider, ...row }) + "\n");

// Invalid cases are recorded and never sent.
const toSend = [];
const invalid = [];
for (const c of cases) {
  try {
    c.questions = validateQuestions(c.questions);
    toSend.push(c);
  } catch {
    invalid.push(c);
  }
}

console.log(`provider=${provider} files=${caseFiles.length} skipped(already in ${outPath})=${done.size} ` +
  `invalid=${invalid.length} requests=${toSend.length} concurrency=${concurrency}`);
if (!args.yes) {
  console.log("Dry count only. Re-run with --yes to send these requests.");
  process.exit(0);
}
for (const c of invalid) write({ id: c.id, ok: false, error: "invalid-case", latency_ms: null, answers: null, usage: null });

let askOne;
let shutdown = async () => {};
if (provider === "jev") {
  const { systemOne } = await import("../../src/client.js");
  const caller = { tool: "eval-runner", client: "decision-eval", purpose: "decision-eval-2026-09-26" };
  askOne = async (c) => {
    const r = await systemOne({ state: c.state, questions: c.questions, caller });
    return { model: r?.model ?? null, answers: r?.answers ?? null, usage: r?.usage ?? null };
  };
} else if (!args["laya-service"]) {
  // Default: ask the Laya model directly. The service's pack-overlap guard is a
  // routing policy, not a capability limit, and would refuse every pack question.
  const { createLayaClient } = await import("../../src/laya-client.js");
  const policy = JSON.parse(readFileSync(join(here, "../../config/decision-profiles.json"), "utf8"));
  const def = policy.profiles[policy.defaultProfile];
  const client = createLayaClient({ ...def.runtime, checkpoint: def.checkpoint, revision: def.revision });
  shutdown = () => client.close();
  askOne = async (c) => {
    const r = await client.predict({ state: c.state, questions: c.questions });
    return { checkpoint: r.checkpoint, revision: r.revision, answers: r.answers, usage: r.usage ?? null };
  };
} else {
  const { createLayaService } = await import("../../src/laya-service.js");
  const policy = JSON.parse(readFileSync(join(here, "../../config/decision-profiles.json"), "utf8"));
  const def = policy.profiles[policy.defaultProfile];
  const service = createLayaService({
    laya: { ...def.runtime, checkpoint: def.checkpoint, revision: def.revision },
    logPath: join(here, "laya-decisions.eval.jsonl"),
  });
  const v2Hash = policy.profiles[V2]?.questionsHash;
  shutdown = () => service.close();
  askOne = async (c) => {
    // Only the frozen v2 questions may name the profile; everything else takes the generic path.
    const frozen = c.category === "bookmark-topic" && v2Hash && questionsFingerprint(c.questions) === v2Hash;
    const r = await service.ask({ state: c.state, questions: c.questions, ...(frozen ? { profile: V2 } : {}) });
    return {
      checkpoint: r.checkpoint, revision: r.revision, profile: r.profile,
      accepted: r.accepted, reason: r.reason, qualification: r.qualification,
      answers: r.answers, usage: null,
    };
  };
}

// Messages are already redacted/sanitized by client.js and laya-service.js; keep them short.
const errorText = (err) => `${err?.constructor?.name || "Error"}: ${String(err?.message ?? err).slice(0, 200)}`;

let next = 0;
let finished = 0;
async function worker() {
  while (next < toSend.length) {
    const c = toSend[next++];
    const started = performance.now();
    try {
      const r = await askOne(c);
      write({ id: c.id, ok: true, error: null, latency_ms: Math.round(performance.now() - started), ...r });
    } catch (err) {
      write({ id: c.id, ok: false, error: errorText(err), latency_ms: Math.round(performance.now() - started), answers: null, usage: null });
    }
    if (++finished % 25 === 0) console.log(`${finished}/${toSend.length}`);
  }
}
try {
  await Promise.all(Array.from({ length: concurrency }, worker));
} finally {
  await shutdown();
}
console.log(`done: ${finished} requests, results in ${outPath}`);
