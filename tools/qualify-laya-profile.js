#!/usr/bin/env node
/**
 * Offline qualification for one local Laya decision profile.
 *
 * This tool turns saved comparison results from tools/laya_compare.py into a
 * frozen calibration artifact and, only when every gate passes, the evidence
 * file src/provider-policy.js pins. It loads no model, makes no network call,
 * and never writes config/decision-profiles.json.
 *
 *   calibrate  definition + development corpus + saved local development predictions
 *   evaluate   frozen calibration + definition + holdout corpus + saved local and Jev predictions
 *
 * A prediction source is a laya_compare.py run.json, the directory holding it,
 * or the predictions.jsonl from that directory. The run.json carries the model
 * pins and the per-case records; predictions.jsonl alone carries no revision
 * pin, so the sibling run.json is used when present and calibration/evaluation
 * fails closed when a pin cannot be verified.
 *
 * The accepted probability is the probability of the chosen label
 * (`answers[qid].probabilities[prediction]`), never the entropy confidence.
 *
 * Method, gates and commands: docs/laya-profile-qualification.md.
 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { questionsFingerprint } from "../src/provider-policy.js";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
// Written output paths are repo-relative so reports never carry a home directory.
const repoRelative = (p) => relative(projectRoot, resolve(p));

/** Label names and critical groups. The row's group must equal its label. */
export const CRITICAL_GROUPS = ["software_development", "machine_learning", "computer_hardware", "other"];

const DEFAULT_DEFINITION = join(projectRoot, "config", "technical-bookmark-topic-v1.json");
const DEFAULT_DEV_CORPUS = join(projectRoot, "data", "technical-bookmark-topic-dev.jsonl");
const DEFAULT_HOLDOUT_CORPUS = join(projectRoot, "data", "technical-bookmark-topic-holdout.jsonl");

export const MIN_ACCEPTED_DEV = 20;
export const MIN_ACCEPTED_ACCURACY = 0.95;
export const MIN_ACCEPTED_PER_GROUP = 30;
export const MIN_COVERAGE = 0.25;
export const OVERALL_CI_LOWER = -0.02;
export const GROUP_CI_LOWER = -0.05;
export const CONFIDENCE_LEVEL = 0.95;
export const BOOTSTRAP_REPS = 2000;
export const EVIDENCE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

// ------------------------------------------------------------------ utilities

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sha256Hex(data) {
  return createHash("sha256").update(data).digest("hex");
}

function fileSha256(path) {
  return sha256Hex(readFileSync(path));
}

/**
 * Mirror of tools/laya_compare.py `canonical`: JSON with sorted object keys,
 * no separator whitespace and literal non-ASCII, so `caseInputHash` matches the
 * `input_hash` the comparison harness records.
 */
function canonical(value) {
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

export function caseInputHash(state, questions) {
  return sha256Hex(canonical({ state, questions }));
}

function median(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Deterministic paired bootstrap of the mean per-case difference. Mirrors the
 * percentile convention in tools/laya_compare.py `paired_bootstrap`.
 */
export function bootstrapCI(diffs, seed = 0, reps = BOOTSTRAP_REPS, alpha = 0.05) {
  const n = diffs.length;
  if (!n) return null;
  const rng = mulberry32(seed);
  const means = [];
  for (let r = 0; r < reps; r++) {
    let s = 0;
    for (let i = 0; i < n; i++) s += diffs[Math.floor(rng() * n)];
    means.push(s / n);
  }
  means.sort((a, b) => a - b);
  return {
    n,
    meanDiff: diffs.reduce((a, b) => a + b, 0) / n,
    ci95: [
      means[Math.max(0, Math.floor((alpha / 2) * reps))],
      means[Math.min(reps - 1, Math.floor((1 - alpha / 2) * reps) - 1)],
    ],
  };
}

// -------------------------------------------------------------------- loading

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

function readJsonl(path) {
  const rows = [];
  for (const line of readFileSync(path, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (trimmed) rows.push(JSON.parse(trimmed));
  }
  return rows;
}

export function loadCorpus(path) {
  return { path, sha256: fileSha256(path), rows: readJsonl(path) };
}

function loadRunJson(file, provider) {
  const doc = readJson(file);
  const run = isPlainObject(doc.run) ? doc.run : {};
  const params = isPlainObject(run.parameters) ? run.parameters : {};
  const providers = isPlainObject(doc.providers) ? doc.providers : {};
  let name = provider;
  if (!name) {
    const runnable = Object.keys(providers).filter(
      (n) => isPlainObject(providers[n]) && providers[n].status === "RUN" && Array.isArray(providers[n].cases)
    );
    if (runnable.length !== 1) {
      throw new Error(`${file}: expected one completed RUN provider, found ${runnable.length}; pass --provider`);
    }
    name = runnable[0];
  }
  const p = providers[name];
  if (!isPlainObject(p) || p.status !== "RUN" || !Array.isArray(p.cases)) {
    throw new Error(`${file}: provider ${name} is not a completed RUN`);
  }
  return {
    path: file,
    sha256: fileSha256(file),
    provider: name,
    checkpoint: p.requested_checkpoint ?? params.checkpoint ?? null,
    revision: params.revision ?? null,
    resolvedModel: typeof p.resolved_model === "string" && p.resolved_model ? p.resolved_model : null,
    rows: p.cases,
  };
}

function loadPredictionsJsonl(file, provider) {
  const rows = readJsonl(file);
  if (!rows.length) throw new Error(`${file}: no prediction records`);
  const name = provider ?? rows[0].provider ?? null;
  let checkpoint = rows[0].checkpoint ?? null;
  let revision = rows[0].revision ?? null;
  let resolvedModel = rows[0].raw_answer?.model ?? rows[0].model ?? null;
  const sibling = join(dirname(file), "run.json");
  if (existsSync(sibling)) {
    const run = loadRunJson(sibling, name ?? undefined);
    checkpoint ??= run.checkpoint;
    revision ??= run.revision;
    resolvedModel ??= run.resolvedModel;
  }
  return { path: file, sha256: fileSha256(file), provider: name, checkpoint, revision, resolvedModel, rows };
}

export function loadResult(input, { provider } = {}) {
  let file = input;
  let stat;
  try {
    stat = statSync(file);
  } catch {
    throw new Error(`result path not found: ${file}`);
  }
  if (stat.isDirectory()) file = join(file, "run.json");
  return file.endsWith(".jsonl") ? loadPredictionsJsonl(file, provider) : loadRunJson(file, provider);
}

export function validateDefinition(definition) {
  if (!isPlainObject(definition)) throw new Error("definition must be an object");
  for (const key of ["profileId", "purpose", "questions", "checkpoint", "revision", "thresholdCandidates"]) {
    if (!(key in definition)) throw new Error(`definition is missing ${key}`);
  }
  if (typeof definition.profileId !== "string" || !definition.profileId) throw new Error("definition.profileId is required");
  if (typeof definition.checkpoint !== "string" || !definition.checkpoint) throw new Error("definition.checkpoint is required");
  if (typeof definition.revision !== "string" || !definition.revision) throw new Error("definition.revision is required");
  if (!isPlainObject(definition.questions) || !Object.keys(definition.questions).length) {
    throw new Error("definition.questions must be a non-empty questions object");
  }
  normalizeCandidates(definition.thresholdCandidates);
  return definition;
}

export function normalizeCandidates(list) {
  if (!Array.isArray(list) || !list.length) throw new Error("thresholdCandidates must be a non-empty array");
  const out = list.map((x) => {
    if (typeof x !== "number" || !Number.isFinite(x) || x < 0 || x > 1) {
      throw new Error(`threshold candidate ${x} is not a finite probability`);
    }
    return x;
  });
  return [...new Set(out)].sort((a, b) => a - b);
}

// ----------------------------------------------------------------- validation

function validateCorpus(rows, source, definition, split) {
  if (!Array.isArray(rows) || !rows.length) throw new Error(`${source}: corpus is empty`);
  const byId = new Map();
  for (const row of rows) {
    if (!isPlainObject(row)) throw new Error(`${source}: corpus row is not an object`);
    for (const key of ["id", "group", "split", "state", "questions", "expected"]) {
      if (!(key in row)) throw new Error(`${source}: case ${row.id ?? "?"} is missing ${key}`);
    }
    if (byId.has(row.id)) throw new Error(`${source}: duplicate case id ${row.id}`);
    const qids = Object.keys(row.questions || {});
    if (qids.length !== 1) throw new Error(`${source}: case ${row.id} must carry exactly one question`);
    const qid = qids[0];
    const question = row.questions[qid];
    if (!isPlainObject(question) || question.type !== "choice") {
      throw new Error(`${source}: case ${row.id} question ${qid} must be type choice`);
    }
    if (row.split !== split) throw new Error(`${source}: incorrect split`);
    if (questionsFingerprint(row.questions) !== questionsFingerprint(definition.questions)) throw new Error(`${source}: questions differ from the definition`);
    const expected = row.expected?.[qid];
    const labels = Object.keys(question.criteria || {});
    if (!labels.length) throw new Error(`${source}: case ${row.id} choice has no criteria`);
    if (!labels.includes(expected)) throw new Error(`${source}: case ${row.id} label ${row.expected} is not a criteria label`);
    if (!CRITICAL_GROUPS.includes(expected)) throw new Error(`${source}: case ${row.id} label ${row.expected} is not a critical group`);
    if (row.group !== expected) throw new Error(`${source}: case ${row.id} group ${row.group} must equal its label ${row.expected}`);
    byId.set(row.id, {
      id: row.id,
      group: expected,
      split: row.split,
      expected,
      questionId: qid,
      labels,
      inputHash: caseInputHash(row.state, row.questions),
    });
  }
  return { byId, splits: [...new Set(rows.map((r) => r.split))] };
}

function alignRecords(rows, corpus, source) {
  if (!Array.isArray(rows) || !rows.length) throw new Error(`${source}: no prediction records`);
  const byId = new Map();
  for (const record of rows) {
    if (!isPlainObject(record)) throw new Error(`${source}: record is not an object`);
    if (typeof record.case_id !== "string" || !record.case_id) throw new Error(`${source}: record without case_id`);
    if (byId.has(record.case_id)) throw new Error(`${source}: duplicate record for ${record.case_id}`);
    const c = corpus.byId.get(record.case_id);
    if (!c) throw new Error(`${source}: record ${record.case_id} is not in the corpus`);
    if (record.input_hash !== c.inputHash) {
      throw new Error(`${source}: ${record.case_id} state/questions differ from the corpus (input_hash mismatch)`);
    }
    if (record.expected !== c.expected) {
      throw new Error(`${source}: ${record.case_id} label mismatch (record ${record.expected} vs corpus ${c.expected})`);
    }
    if (record.question_id !== c.questionId) throw new Error(`${source}: ${record.case_id} question id mismatch`);
    if (record.primitive !== "choice") throw new Error(`${source}: ${record.case_id} primitive ${record.primitive} is not choice`);
    byId.set(record.case_id, record);
  }
  for (const id of corpus.byId.keys()) if (!byId.has(id)) throw new Error(`${source}: corpus case ${id} has no prediction record`);
  return byId;
}

function assertPaired(localById, jevById, source) {
  const local = [...localById.keys()].sort();
  const jev = [...jevById.keys()].sort();
  if (local.length !== jev.length || local.some((id, i) => id !== jev[i])) {
    throw new Error(`${source}: local and Jev case ids differ`);
  }
  for (const id of local) {
    const a = localById.get(id);
    const b = jevById.get(id);
    if (a.input_hash !== b.input_hash) throw new Error(`${source}: ${id} local and Jev inputs differ`);
    if (a.expected !== b.expected) throw new Error(`${source}: ${id} local and Jev labels differ`);
    if (a.question_id !== b.question_id) throw new Error(`${source}: ${id} local and Jev question ids differ`);
  }
}

/**
 * Probability of the chosen label from the recorded distribution. Entropy
 * confidence is deliberately ignored; a bad distribution is a schema error.
 */
export function selectedProbability(record, labels) {
  const answers = isPlainObject(record.raw_answer) ? record.raw_answer.answers : null;
  const answer = isPlainObject(answers) ? answers[record.question_id] : null;
  if (!isPlainObject(answer) || answer.type !== "choice") return { ok: false, reason: "answer missing or not choice" };
  const probs = answer.probabilities;
  if (!isPlainObject(probs)) return { ok: false, reason: "probabilities missing" };
  const expected = [...labels].sort();
  const keys = Object.keys(probs).sort();
  if (keys.length !== expected.length || keys.some((k, i) => k !== expected[i])) {
    return { ok: false, reason: "probability labels differ from criteria" };
  }
  let sum = 0;
  for (const value of Object.values(probs)) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
      return { ok: false, reason: "probability is not a finite number in [0,1]" };
    }
    sum += value;
  }
  if (Math.abs(sum - 1) > Math.max(0.001, labels.length * 0.000051)) {
    return { ok: false, reason: "probabilities do not sum to 1" };
  }
  if (answer.choice !== record.prediction) return { ok: false, reason: "recorded prediction differs from the answer" };
  if (!labels.includes(record.prediction)) return { ok: false, reason: "prediction is not a criteria label" };
  return { ok: true, value: probs[record.prediction], prediction: record.prediction };
}

function countErrors(byId, corpus, source) {
  let errorCount = 0;
  let schemaErrorCount = 0;
  const errorIds = [];
  const schemaErrorIds = [];
  for (const [id, record] of byId) {
    if (record.ok !== true) {
      errorCount++;
      errorIds.push(id);
      continue;
    }
    const c = corpus.byId.get(id);
    if (record.schema_ok !== true || !selectedProbability(record, c.labels).ok) {
      schemaErrorCount++;
      schemaErrorIds.push(id);
    }
  }
  return { source, errorCount, schemaErrorCount, errorIds, schemaErrorIds };
}

function caseLatency(record) {
  if (typeof record.warm_p50 === "number" && Number.isFinite(record.warm_p50) && record.warm_p50 > 0) {
    return record.warm_p50;
  }
  if (Array.isArray(record.latency_samples)) {
    const xs = record.latency_samples.filter((x) => typeof x === "number" && Number.isFinite(x) && x > 0);
    if (xs.length) return median(xs);
  }
  return null;
}

// ---------------------------------------------------------------- calibration

function developmentCases(corpus, byId) {
  const cases = [];
  for (const [id, c] of corpus.byId) {
    const selected = selectedProbability(byId.get(id), c.labels);
    if (!selected.ok) return { error: `${id}: ${selected.reason}` };
    cases.push({
      id,
      group: c.group,
      expected: c.expected,
      selectedProbability: selected.value,
      correct: selected.prediction === c.expected,
    });
  }
  return { cases };
}

export function calibrate({
  definition,
  definitionSha256,
  questionsHash,
  corpus,
  predictions,
  generatedAt,
  minAccepted = MIN_ACCEPTED_DEV,
  minAcceptedAccuracy = MIN_ACCEPTED_ACCURACY,
}) {
  assertLocalPins(definition, predictions);
  if (questionsHash !== questionsFingerprint(definition.questions)) throw new Error("questions hash mismatch");
  const dev = validateCorpus(corpus.rows, "development corpus", definition, "dev");
  const byId = alignRecords(predictions.rows, dev, "local development predictions");
  const errors = countErrors(byId, dev, "local development predictions");
  if (errors.errorCount || errors.schemaErrorCount) {
    return {
      status: "INCONCLUSIVE",
      reason: "development predictions contain errors or schema errors; calibrate on a clean run",
      errorCount: errors.errorCount,
      schemaErrorCount: errors.schemaErrorCount,
      errorIds: errors.errorIds,
      schemaErrorIds: errors.schemaErrorIds,
    };
  }
  const built = developmentCases(dev, byId);
  if (built.error) return { status: "INCONCLUSIVE", reason: `development predictions unusable: ${built.error}` };

  const thresholds = normalizeCandidates(definition.thresholdCandidates);
  const attempts = [];
  let selected = null;
  for (const threshold of thresholds) {
    const accepted = built.cases.filter((c) => c.selectedProbability >= threshold);
    const correct = accepted.filter((c) => c.correct).length;
    const accuracy = accepted.length ? correct / accepted.length : null;
    const attempt = { threshold, acceptedCount: accepted.length, acceptedCorrect: correct, acceptedAccuracy: accuracy };
    attempts.push(attempt);
    if (!selected && accepted.length >= minAccepted && accuracy >= minAcceptedAccuracy) selected = attempt;
  }
  if (!selected) {
    return {
      status: "INCONCLUSIVE",
      reason: `no candidate threshold reached ${minAccepted} accepted examples at observed accuracy >= ${minAcceptedAccuracy}`,
      attempts,
    };
  }

  const artifact = {
    schemaVersion: 1,
    kind: "laya-profile-calibration",
    profileId: definition.profileId,
    questionsHash,
    checkpoint: definition.checkpoint,
    revision: definition.revision,
    definitionSha256: definitionSha256 ?? null,
    thresholdCandidates: thresholds,
    selectedThreshold: selected.threshold,
    minSelectedProbability: selected.threshold,
    selectionRule:
      `lowest candidate threshold with >= ${minAccepted} accepted examples and observed accepted accuracy >= ` +
      `${minAcceptedAccuracy}; accepted probability is the probability of the chosen label`,
    minAccepted,
    minAcceptedAccuracy,
    development: {
      corpusPath: corpus.path ?? null,
      corpusSha256: corpus.sha256 ?? null,
      caseCount: built.cases.length,
      predictionsPath: predictions.path ?? null,
      predictionsSha256: predictions.sha256 ?? null,
      acceptedCount: selected.acceptedCount,
      acceptedCorrect: selected.acceptedCorrect,
      acceptedAccuracy: selected.acceptedAccuracy,
      errorCount: 0,
      schemaErrorCount: 0,
      caseIds: built.cases.map((c) => c.id).sort(),
      inputHashes: [...new Set(dev.byId.values())].map((c) => c.inputHash).sort(),
    },
    attempts,
    generatedAt: generatedAt ?? new Date().toISOString(),
  };
  return { status: "CALIBRATED", artifact };
}

// ----------------------------------------------------------------- evaluation

function verifyArtifact(definition, questionsHash, artifact) {
  if (!isPlainObject(artifact) || artifact.schemaVersion !== 1 || artifact.kind !== "laya-profile-calibration") {
    throw new Error("calibration artifact is not a frozen laya-profile-calibration");
  }
  if (artifact.profileId !== definition.profileId) throw new Error("calibration profile mismatch");
  if (artifact.minSelectedProbability !== artifact.selectedThreshold) throw new Error("calibration threshold mismatch");
  const selected = artifact.attempts?.find(a => a.acceptedCount >= MIN_ACCEPTED_DEV && a.acceptedAccuracy >= MIN_ACCEPTED_ACCURACY);
  if (!selected || selected.threshold !== artifact.selectedThreshold) throw new Error("calibration selection changed");
  if (artifact.questionsHash !== questionsHash) throw new Error("calibration questions hash does not match the definition");
  if (artifact.checkpoint !== definition.checkpoint) throw new Error("calibration checkpoint does not match the definition");
  if (artifact.revision !== definition.revision) throw new Error("calibration revision does not match the definition");
  const candidates = normalizeCandidates(artifact.thresholdCandidates);
  if (!candidates.includes(artifact.selectedThreshold)) throw new Error("frozen threshold is not one of the frozen candidates");
  if (!normalizeCandidates(definition.thresholdCandidates).includes(artifact.selectedThreshold)) {
    throw new Error("frozen threshold is not a definition threshold candidate");
  }
  if (!Array.isArray(artifact.development?.caseIds) || !Array.isArray(artifact.development?.inputHashes)) {
    throw new Error("calibration artifact lacks the development case fingerprints");
  }
  return { threshold: artifact.selectedThreshold };
}

function assertLocalPins(definition, local) {
  if (local.checkpoint !== definition.checkpoint) {
    throw new Error(`local checkpoint ${local.checkpoint ?? "unrecorded"} does not match definition ${definition.checkpoint}`);
  }
  if (local.revision !== definition.revision) {
    throw new Error(`local revision ${local.revision ?? "unrecorded"} does not match definition ${definition.revision}`);
  }
}

function gate(name, pass, severity, detail) {
  return { name, pass, severity, detail: pass ? "requirement satisfied" : detail };
}

export function evaluate({
  definition,
  definitionSha256,
  questionsHash,
  artifact,
  artifactSha256,
  corpus,
  local,
  jev,
  now = Date.now(),
  seed = 0,
  reps = BOOTSTRAP_REPS,
}) {
  if (definitionSha256 !== artifact.definitionSha256) throw new Error("definition changed after calibration");
  if (!Number.isInteger(reps) || reps < 200 || !Number.isInteger(seed)) throw new Error("invalid bootstrap parameters");
  const frozen = verifyArtifact(definition, questionsHash, artifact);
  assertLocalPins(definition, local);
  if (typeof jev.resolvedModel !== "string" || !jev.resolvedModel) {
    throw new Error("Jev predictions do not record a resolved model");
  }

  const holdout = validateCorpus(corpus.rows, "holdout corpus", definition, "holdout");
  const devIds = new Set(artifact.development.caseIds);
  const devHashes = new Set(artifact.development.inputHashes);
  for (const [id, c] of holdout.byId) {
    if (devIds.has(id)) throw new Error(`holdout case ${id} also appears in the calibration set`);
    if (devHashes.has(c.inputHash)) throw new Error(`holdout content for ${id} also appears in the calibration set`);
  }

  for (const row of jev.rows) {
    if (row.ok && row.raw_answer?.model !== jev.resolvedModel) throw new Error("mixed or missing resolved Jev model");
  }
  const localById = alignRecords(local.rows, holdout, "local holdout predictions");
  const jevById = alignRecords(jev.rows, holdout, "Jev holdout predictions");
  assertPaired(localById, jevById, "holdout pairing");

  const localErrors = countErrors(localById, holdout, "local holdout predictions");
  const jevErrors = countErrors(jevById, holdout, "Jev holdout predictions");
  const errorCount = localErrors.errorCount + jevErrors.errorCount;
  const schemaErrorCount = localErrors.schemaErrorCount + jevErrors.schemaErrorCount;

  const cases = [];
  for (const [id, c] of holdout.byId) {
    const l = localById.get(id);
    const j = jevById.get(id);
    const selected = selectedProbability(l, c.labels);
    cases.push({
      id,
      group: c.group,
      expected: c.expected,
      selectedProbability: selected.value,
      correct: l.prediction === c.expected,
      jevCorrect: j.prediction === c.expected,
      localLatency: caseLatency(l),
      jevLatency: caseLatency(j),
    });
  }

  const accepted = cases.filter((c) => c.selectedProbability >= frozen.threshold);
  const acceptedCorrect = accepted.filter((c) => c.correct).length;
  const acceptedAccuracy = accepted.length ? acceptedCorrect / accepted.length : null;
  const coverage = cases.length ? accepted.length / cases.length : 0;
  const accuracyDeltaCI = bootstrapCI(accepted.map((c) => (c.correct ? 1 : 0) - (c.jevCorrect ? 1 : 0)), seed, reps);

  const groupSampleCounts = {};
  const groupAccuracyDeltaCI = {};
  const groupAcceptedAccuracy = {};
  for (const group of CRITICAL_GROUPS) {
    const rows = accepted.filter((c) => c.group === group);
    groupSampleCounts[group] = rows.length;
    groupAccuracyDeltaCI[group] = bootstrapCI(rows.map((c) => (c.correct ? 1 : 0) - (c.jevCorrect ? 1 : 0)), seed, reps);
    groupAcceptedAccuracy[group] = rows.length ? rows.filter((c) => c.correct).length / rows.length : null;
  }

  const latencyReady =
    accepted.length > 0 && accepted.every((c) => c.localLatency != null && c.jevLatency != null);
  const latencyRatio = latencyReady
    ? median(accepted.map((c) => c.localLatency)) / median(accepted.map((c) => c.jevLatency))
    : null;

  const localFullAccuracy = cases.filter((c) => c.correct).length / cases.length;
  const jevFullAccuracy = cases.filter((c) => c.jevCorrect).length / cases.length;
  const cascadeCorrect = cases.filter((c) =>
    c.selectedProbability >= frozen.threshold ? c.correct : c.jevCorrect
  ).length;
  const cascadeAccuracy = cascadeCorrect / cases.length;

  const gates = [
    gate("errors", errorCount === 0, "fail", `${errorCount} error record(s)`),
    gate("schema-errors", schemaErrorCount === 0, "fail", `${schemaErrorCount} schema-error record(s)`),
    gate(
      "coverage",
      coverage >= MIN_COVERAGE,
      "inconclusive",
      `${(coverage * 100).toFixed(1)}% coverage < ${(MIN_COVERAGE * 100).toFixed(0)}%`
    ),
    gate(
      "accepted-accuracy",
      acceptedAccuracy != null && acceptedAccuracy >= MIN_ACCEPTED_ACCURACY,
      acceptedAccuracy == null ? "inconclusive" : "fail",
      `observed accepted accuracy ${acceptedAccuracy == null ? "n/a" : acceptedAccuracy.toFixed(4)} < ${MIN_ACCEPTED_ACCURACY}`
    ),
    gate(
      "overall-ci-lower",
      accuracyDeltaCI != null && accuracyDeltaCI.ci95[0] >= OVERALL_CI_LOWER,
      accuracyDeltaCI == null ? "inconclusive" : "fail",
      `overall CI lower ${accuracyDeltaCI ? accuracyDeltaCI.ci95[0].toFixed(4) : "n/a"} < ${OVERALL_CI_LOWER}`
    ),
    gate(
      "latency-ratio",
      latencyRatio != null && latencyRatio > 0 && latencyRatio < 1,
      latencyRatio == null ? "inconclusive" : "fail",
      `latency ratio ${latencyRatio == null ? "n/a" : latencyRatio.toFixed(4)} is not strictly between 0 and 1`
    ),
  ];
  for (const group of CRITICAL_GROUPS) {
    gates.push(
      gate(
        `group-count:${group}`,
        groupSampleCounts[group] >= MIN_ACCEPTED_PER_GROUP,
        "inconclusive",
        `${groupSampleCounts[group]} accepted < ${MIN_ACCEPTED_PER_GROUP}`
      )
    );
    const interval = groupAccuracyDeltaCI[group];
    gates.push(
      gate(
        `group-ci-lower:${group}`,
        interval != null && interval.ci95[0] >= GROUP_CI_LOWER,
        interval == null ? "inconclusive" : "fail",
        `${group} CI lower ${interval ? interval.ci95[0].toFixed(4) : "n/a"} < ${GROUP_CI_LOWER}`
      )
    );
  }

  const failed = gates.filter((g) => !g.pass && g.severity === "fail");
  const inconclusive = gates.filter((g) => !g.pass && g.severity === "inconclusive");
  const status = !failed.length && !inconclusive.length ? "PASS" : failed.length ? "FAILED" : "INCONCLUSIVE";

  const result = {
    status,
    profileId: definition.profileId,
    selectedThreshold: frozen.threshold,
    totalHoldoutCount: cases.length,
    metrics: {
      sampleCount: accepted.length,
      acceptedAccuracy,
      coverage,
      accuracyDeltaCI,
      groupAccuracyDeltaCI,
      groupSampleCounts,
      groupAcceptedAccuracy,
      localFullAccuracy,
      jevFullAccuracy,
      cascadeAccuracy,
      latencyRatio,
      errorCount,
      schemaErrorCount,
      localCheckpoint: local.checkpoint,
      localRevision: local.revision,
      localResolvedModel: local.resolvedModel,
      resolvedJevModel: jev.resolvedModel,
    },
    gates,
  };

  if (status !== "PASS") {
    result.note = "diagnostic only; no approval evidence was emitted";
    return result;
  }

  const evaluatedAt = new Date(now).toISOString();
  const evidence = {
    schemaVersion: 1,
    profileId: definition.profileId,
    questionsHash,
    checkpoint: definition.checkpoint,
    revision: definition.revision,
    heldOut: true,
    sampleCount: accepted.length,
    confidenceLevel: CONFIDENCE_LEVEL,
    accuracyDeltaCI: accuracyDeltaCI.ci95,
    groupAccuracyDeltaCI: Object.fromEntries(
      CRITICAL_GROUPS.map((g) => [g, groupAccuracyDeltaCI[g].ci95])
    ),
    groupSampleCounts,
    errorCount: 0,
    schemaErrorCount: 0,
    latencyRatio,
    minSelectedProbability: frozen.threshold,
    evaluatedAt,
    expiresAt: new Date(now + EVIDENCE_TTL_MS).toISOString(),
    provenance: {
      definitionPath: definition.path ?? null,
      definitionSha256: definitionSha256 ?? null,
      calibrationPath: artifact.path ?? null,
      calibrationSha256: artifactSha256 ?? null,
      holdoutCorpusPath: corpus.path ?? null,
      holdoutCorpusSha256: corpus.sha256 ?? null,
      localPredictionsPath: local.path,
      localPredictionsSha256: local.sha256,
      localResolvedModel: local.resolvedModel,
      jevPredictionsPath: jev.path,
      jevPredictionsSha256: jev.sha256,
      resolvedJevModel: jev.resolvedModel,
      bootstrapSeed: seed,
      bootstrapReps: reps,
    },
    totalHoldoutCount: cases.length,
    coverage,
    acceptedAccuracy,
    localFullAccuracy,
    jevFullAccuracy,
    cascadeAccuracy,
    resolvedJevModel: jev.resolvedModel,
    qualificationScope: {
      labelSource: "generated-author-labeled",
      synthetic: true,
      statement:
        "Narrow synthetic qualification of one local choice profile on generated author-labeled data; " +
        "not a general model ranking and not representative of production traffic.",
    },
  };
  result.evidence = evidence;
  return result;
}

// ------------------------------------------------------------------------ CLI

function parseArgs(argv) {
  const [command, ...rest] = argv;
  const opts = {};
  for (let i = 0; i < rest.length; i++) {
    const arg = rest[i];
    if (!arg.startsWith("--")) throw new Error(`unexpected argument ${arg}`);
    const key = arg.slice(2);
    const value = rest[i + 1];
    if (value === undefined || value.startsWith("--")) opts[key] = true;
    else {
      opts[key] = value;
      i++;
    }
  }
  return { command, opts };
}

function writeJson(path, value) {
  writeFileSync(path, JSON.stringify(value, null, 2));
}

function emit(value, out) {
  if (out) writeJson(out, value);
  else process.stdout.write(JSON.stringify(value, null, 2) + "\n");
}

function evidencePathForProposal(outPath) {
  const rel = relative(projectRoot, resolve(outPath));
  return rel && !rel.startsWith("..") ? rel : resolve(outPath);
}

function cmdCalibrate(opts) {
  if (!opts.predictions) throw new Error("calibrate requires --predictions <run.json|predictions.jsonl|directory>");
  const definitionPath = opts.definition ?? DEFAULT_DEFINITION;
  const corpusPath = opts.corpus ?? DEFAULT_DEV_CORPUS;
  const definition = validateDefinition(readJson(definitionPath));
  definition.path = repoRelative(definitionPath);
  const result = calibrate({
    definition,
    definitionSha256: fileSha256(definitionPath),
    questionsHash: questionsFingerprint(definition.questions),
    corpus: { ...loadCorpus(corpusPath), path: repoRelative(corpusPath) },
    predictions: loadResult(opts.predictions, { provider: opts.provider }),
    generatedAt: opts["generated-at"] ?? new Date().toISOString(),
  });
  emit(result, opts.out);
  return result.status === "CALIBRATED" ? 0 : 1;
}

function cmdEvaluate(opts) {
  if (!opts.calibration) throw new Error("evaluate requires --calibration <calibration.json>");
  if (!opts.local || !opts.jev) throw new Error("evaluate requires --local and --jev");
  const definitionPath = opts.definition ?? DEFAULT_DEFINITION;
  const corpusPath = opts.corpus ?? DEFAULT_HOLDOUT_CORPUS;
  const calibrationPath = opts.calibration;
  const definition = validateDefinition(readJson(definitionPath));
  definition.path = repoRelative(definitionPath);
  const document = readJson(calibrationPath);
  const artifact = document.status === "CALIBRATED" ? document.artifact : document;
  for (const [pathKey, hashKey] of [["corpusPath", "corpusSha256"], ["predictionsPath", "predictionsSha256"]]) {
    // corpusPath is written repo-relative; resolve() keeps older absolute values unchanged.
    const file = pathKey === "corpusPath" ? resolve(projectRoot, artifact.development[pathKey]) : artifact.development[pathKey];
    if (fileSha256(file) !== artifact.development[hashKey]) throw new Error("development input changed after calibration");
  }
  artifact.path = calibrationPath;
  const now = opts.now ? Date.parse(opts.now) : Date.now();
  if (!Number.isFinite(now)) throw new Error("--now is not a date");
  const result = evaluate({
    definition,
    definitionSha256: fileSha256(definitionPath),
    questionsHash: questionsFingerprint(definition.questions),
    artifact,
    artifactSha256: fileSha256(calibrationPath),
    corpus: { ...loadCorpus(corpusPath), path: repoRelative(corpusPath) },
    local: loadResult(opts.local, { provider: opts["local-provider"] }),
    jev: loadResult(opts.jev, { provider: opts["jev-provider"] }),
    now,
    seed: opts.seed === undefined ? 0 : Number(opts.seed),
    reps: opts.reps === undefined ? BOOTSTRAP_REPS : Number(opts.reps),
  });

  if (result.status !== "PASS") {
    emit(result, opts.out);
    return 1;
  }

  const evidenceText = JSON.stringify(result.evidence, null, 2);
  const evidenceSha256 = sha256Hex(evidenceText);

  const proposal = {
    profileId: result.profileId,
    profile: {
      enabled: true,
      purpose: definition.purpose,
      questionsHash: result.evidence.questionsHash,
      checkpoint: definition.checkpoint,
      revision: definition.revision,
      maxStateChars: definition.maxStateChars,
      maxQuestions: definition.maxQuestions,
      maxOptions: definition.maxOptions,
      minSelectedProbability: result.selectedThreshold,
      evidence: { path: evidencePathForProposal(opts.out ?? "evidence.json"), sha256: evidenceSha256 },
    },
    evidenceSha256,
    note: "Proposed only. This tool never mutates config/decision-profiles.json; the lead adds the profile by hand.",
  };
  if (opts.out) {
    writeFileSync(opts.out, evidenceText);
    writeJson(`${opts.out}.proposed-profile.json`, proposal);
    process.stderr.write(`qualify-laya-profile: PASS; evidence sha256 ${evidenceSha256}\n`);
  } else {
    emit({ evidence: result.evidence, evidenceSha256, proposal }, undefined);
  }
  return 0;
}

function main(argv) {
  const { command, opts } = parseArgs(argv);
  if (command === "calibrate") return cmdCalibrate(opts);
  if (command === "evaluate") return cmdEvaluate(opts);
  process.stderr.write(
    "usage:\n" +
      "  qualify-laya-profile.js calibrate --definition <json> --corpus <dev.jsonl> --predictions <run.json|dir> [--out <calibration.json>]\n" +
      "  qualify-laya-profile.js evaluate  --calibration <json> --local <run.json|dir> --jev <run.json|dir> [--definition <json>] [--corpus <holdout.jsonl>] [--out <evidence.json>]\n"
  );
  return 2;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    process.exit(main(process.argv.slice(2)));
  } catch (error) {
    process.stderr.write(`qualify-laya-profile: INVALID: ${error.message}\n`);
    process.exit(2);
  }
}
