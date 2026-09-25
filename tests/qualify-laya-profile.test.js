import test from "node:test";
import assert from "node:assert/strict";
import {
  BOOTSTRAP_REPS,
  CRITICAL_GROUPS,
  MIN_ACCEPTED_PER_GROUP,
  bootstrapCI,
  calibrate,
  caseInputHash,
  evaluate,
  selectedProbability,
} from "../tools/qualify-laya-profile.js";
import { questionsFingerprint } from "../src/provider-policy.js";

// Focused regression tests for the offline qualification tool. They build
// synthetic laya_compare-shaped fixtures only: no model is run and no file
// outside this module's in-memory fixtures is read.

const checkpoint = "acme/bookmark-topic";
const revision = "rev-1";
const questions = {
  topic: {
    type: "choice",
    instructions: "Which technical topic does this bookmark belong to?",
    criteria: {
      software_development: "code, tooling, languages",
      machine_learning: "models, training, inference",
      computer_hardware: "chips, devices, peripherals",
      other: "none of the above",
    },
  },
};
const questionsHash = questionsFingerprint(questions);

function definition(overrides = {}) {
  return {
    profileId: "technical-bookmark-topic-v1",
    purpose: "low_risk_classification",
    questions,
    checkpoint,
    revision,
    maxQuestions: 1,
    maxOptions: 4,
    maxStateChars: 2000,
    thresholdCandidates: [0.7, 0.8, 0.9, 0.95],
    ...overrides,
  };
}

function row(id, label, split = "holdout") {
  return {
    id,
    group: label,
    split,
    origin: "generated",
    label_source: "author-generated",
    state: { title: `${id} title`, url: `https://example.test/${id}` },
    questions,
    expected: {topic:label},
  };
}

function distribution(labels, prediction, probability) {
  const others = labels.filter((l) => l !== prediction);
  const rest = (1 - probability) / others.length;
  return Object.fromEntries(labels.map((l) => [l, l === prediction ? probability : rest]));
}

function recordFor(
  rowObject,
  {
    correct = true,
    probability = 0.9,
    ok = true,
    schemaOk = true,
    latency = 0.1,
    model = "local-model",
    provider = "laya-mlx",
    checkpoint: ck = checkpoint,
    revision: rev = revision,
  } = {}
) {
  const qid = Object.keys(rowObject.questions)[0];
  const labels = Object.keys(rowObject.questions[qid].criteria);
  const prediction = correct ? rowObject.expected[qid] : labels.find((l) => l !== rowObject.expected[qid]);
  return {
    case_id: rowObject.id,
    group: rowObject.group,
    split: rowObject.split,
    primitive: "choice",
    question_id: qid,
    input_hash: caseInputHash(rowObject.state, rowObject.questions),
    ok,
    error: ok ? null : "boom",
    schema_ok: schemaOk,
    prediction,
    expected: rowObject.expected[qid],
    raw_answer: {
      model,
      answers: {
        [qid]: {
          type: "choice",
          choice: prediction,
          confidence: 0.001,
          probabilities: distribution(labels, prediction, probability),
        },
      },
      usage: { input_tokens: 1, output_tokens: 1 },
    },
    warm_p50: latency,
    latency_samples: [latency],
    provider,
    checkpoint: ck,
    revision: rev,
  };
}

function corpusSource(rows, label) {
  return { path: `<fixture:${label}>`, sha256: "0".repeat(64), rows };
}

function predictionSource(rows, overrides = {}) {
  return {
    path: "<fixture:predictions>",
    sha256: "0".repeat(64),
    provider: "laya-mlx",
    checkpoint,
    revision,
    resolvedModel: "local-model",
    rows,
    ...overrides,
  };
}

/** 25 development cases: 20 reach 0.70, so the lowest candidate is selected. */
function developmentFixture() {
  const probabilities = [
    ...Array(5).fill(0.65),
    ...Array(5).fill(0.72),
    ...Array(15).fill(0.99),
  ];
  const rows = [];
  const records = [];
  probabilities.forEach((probability, i) => {
    const rowObject = row(`dev-${i}`, CRITICAL_GROUPS[i % CRITICAL_GROUPS.length], "dev");
    rows.push(rowObject);
    records.push(recordFor(rowObject, { probability }));
  });
  return { rows, records };
}

function frozenArtifact() {
  const dev = developmentFixture();
  const result = calibrate({
    definition: definition(),
    definitionSha256: "1".repeat(64),
    questionsHash,
    corpus: corpusSource(dev.rows, "dev"),
    predictions: predictionSource(dev.records),
    generatedAt: "2026-09-21T00:00:00.000Z",
  });
  assert.equal(result.status, "CALIBRATED");
  assert.equal(result.artifact.selectedThreshold, 0.7);
  return result.artifact;
}

function holdoutFixture({
  perGroup = 60,
  probability = 0.9,
  probabilityByGroup = {},
  localCorrectByGroup = {},
  jevCorrect = true,
  latency = { local: 0.1, jev: 0.5 },
} = {}) {
  const rows = [];
  const local = [];
  const jev = [];
  for (const label of CRITICAL_GROUPS) {
    for (let i = 0; i < perGroup; i++) {
      const rowObject = row(`hold-${label}-${i}`, label);
      rows.push(rowObject);
      local.push(
        recordFor(rowObject, {
          correct: localCorrectByGroup[label] ?? true,
          probability: probabilityByGroup[label] ?? probability,
          latency: latency.local,
        })
      );
      jev.push(
        recordFor(rowObject, {
          correct: jevCorrect,
          probability: 0.8,
          latency: latency.jev,
          model: "jev-1.13.0",
          provider: "jev",
          checkpoint: "jev-latest",
          revision: null,
        })
      );
    }
  }
  return { rows, local, jev };
}

function runEvaluation({ artifact = frozenArtifact(), fixture = holdoutFixture(), localOverrides = {}, jevOverrides = {}, definitionOverrides = {} } = {}) {
  return evaluate({
    definition: definition(definitionOverrides),
    definitionSha256: "1".repeat(64),
    questionsHash,
    artifact,
    artifactSha256: "2".repeat(64),
    corpus: corpusSource(fixture.rows, "holdout"),
    local: predictionSource(fixture.local, localOverrides),
    jev: predictionSource(fixture.jev, { provider: "jev", checkpoint: "jev-latest", revision: null, resolvedModel: "jev-1.13.0", ...jevOverrides }),
    now: Date.parse("2026-09-21T00:00:00Z"),
    seed: 0,
    reps: 200,
  });
}

test("selected probability is the chosen label's probability, never entropy confidence", () => {
  const labels = Object.keys(questions.topic.criteria);
  const record = recordFor(row("x", "other"), { probability: 0.9 });
  record.raw_answer.answers.topic.confidence = 0.999;
  const selected = selectedProbability(record, labels);
  assert.equal(selected.ok, true);
  assert.equal(selected.value, 0.9);

  const low = recordFor(row("y", "other"), { probability: 0.4 });
  low.raw_answer.answers.topic.confidence = 0.999;
  assert.equal(selectedProbability(low, labels).value, 0.4);
});

test("a non-finite or unlabelled distribution is a schema error", () => {
  const labels = Object.keys(questions.topic.criteria);
  const record = recordFor(row("x", "other"), { probability: 0.9 });
  record.raw_answer.answers.topic.probabilities = { other: 1 };
  assert.equal(selectedProbability(record, labels).ok, false);

  const bad = recordFor(row("y", "other"), { probability: 0.9 });
  bad.raw_answer.answers.topic.probabilities.other = Infinity;
  assert.equal(selectedProbability(bad, labels).ok, false);
});

test("calibration selects the lowest qualifying threshold and freezes the label probability", () => {
  const artifact = frozenArtifact();
  assert.equal(artifact.schemaVersion, 1);
  assert.equal(artifact.kind, "laya-profile-calibration");
  assert.equal(artifact.questionsHash, questionsHash);
  assert.equal(artifact.checkpoint, checkpoint);
  assert.equal(artifact.revision, revision);
  assert.equal(artifact.minSelectedProbability, artifact.selectedThreshold);
  assert.deepEqual(artifact.thresholdCandidates, [0.7, 0.8, 0.9, 0.95]);
  assert.equal(artifact.development.acceptedCount, 20);
  assert.equal(artifact.development.acceptedAccuracy, 1);
  assert.deepEqual(artifact.attempts.map((a) => a.threshold), [0.7, 0.8, 0.9, 0.95]);
  assert.deepEqual(artifact.development.caseIds, artifact.development.caseIds.slice().sort());
});

test("calibration is inconclusive when no threshold reaches the accuracy floor", () => {
  const rows = [];
  const records = [];
  for (let i = 0; i < 25; i++) {
    const rowObject = row(`dev-${i}`, CRITICAL_GROUPS[i % 4], "dev");
    rows.push(rowObject);
    records.push(recordFor(rowObject, { correct: i % 5 !== 0, probability: 0.7 }));
  }
  const result = calibrate({
    definition: definition(),
    questionsHash,
    corpus: corpusSource(rows, "dev"),
    predictions: predictionSource(records),
  });
  assert.equal(result.status, "INCONCLUSIVE");
  assert.equal(result.artifact, undefined);
});

test("calibration fails closed on an errored development prediction", () => {
  const dev = developmentFixture();
  dev.records[0].ok = false;
  const result = calibrate({
    definition: definition(),
    questionsHash,
    corpus: corpusSource(dev.rows, "dev"),
    predictions: predictionSource(dev.records),
  });
  assert.equal(result.status, "INCONCLUSIVE");
  assert.equal(result.errorCount, 1);
});

test("a missing holdout record fails closed rather than being discarded", () => {
  const fixture = holdoutFixture({ perGroup: 30 });
  fixture.local.pop();
  assert.throws(() => runEvaluation({ fixture }), /has no prediction record/);
});

test("a local error record produces a diagnostic, never evidence", () => {
  const fixture = holdoutFixture();
  fixture.local[0].ok = false;
  const result = runEvaluation({ fixture });
  assert.equal(result.status, "FAILED");
  assert.equal(result.evidence, undefined);
  assert.equal(result.metrics.errorCount, 1);
  assert.match(result.note, /no approval evidence/);
});

test("mismatched local pins fail closed", () => {
  assert.throws(
    () => runEvaluation({ localOverrides: { checkpoint: "other/model" } }),
    /local checkpoint/
  );
  assert.throws(
    () => runEvaluation({ localOverrides: { revision: "other-rev" } }),
    /local revision/
  );
  assert.throws(() => runEvaluation({ jevOverrides: { resolvedModel: null } }), /resolved model/);
});

test("mismatched inputs and labels fail closed", () => {
  const fixture = holdoutFixture();
  fixture.local[0].input_hash = "f".repeat(64);
  assert.throws(() => runEvaluation({ fixture }), /input_hash mismatch/);

  const other = holdoutFixture();
  other.local[0].expected = "other";
  assert.throws(() => runEvaluation({ fixture: other }), /label mismatch/);
});

test("holdout ids and content must be independent of the calibration set", () => {
  const artifact = frozenArtifact();
  const shared = row(artifact.development.caseIds[0], "other");
  const fixture = holdoutFixture({ perGroup: 30 });
  fixture.rows[0] = shared;
  fixture.local[0] = recordFor(shared, { probability: 0.9 });
  fixture.jev[0] = recordFor(shared, { model: "jev-1.13.0", provider: "jev", checkpoint: "jev-latest", revision: null });
  assert.throws(() => runEvaluation({ artifact, fixture }), /also appears in the calibration set/);

  const dev = developmentFixture();
  const devRow = dev.rows[0];
  const overlapping = holdoutFixture({ perGroup: 30 });
  const clone = { ...row("fresh-id", "other"), state: devRow.state, questions: devRow.questions };
  overlapping.rows[1] = clone;
  overlapping.local[1] = recordFor(clone, { probability: 0.9 });
  overlapping.jev[1] = recordFor(clone, { model: "jev-1.13.0", provider: "jev", checkpoint: "jev-latest", revision: null });
  assert.throws(() => runEvaluation({ artifact, fixture: overlapping }), /content for/);
});

test("the frozen threshold governs the accepted subset", () => {
  const artifact = frozenArtifact();
  const fixture = holdoutFixture({ probability: 0.65 });
  const result = runEvaluation({ artifact, fixture });
  assert.equal(result.metrics.sampleCount, 0);
  assert.notEqual(result.status, "PASS");
  assert.equal(result.evidence, undefined);
});

test("a threshold outside the frozen candidates is rejected", () => {
  const artifact = { ...frozenArtifact(), selectedThreshold: 0.6, minSelectedProbability: 0.6 };
  assert.throws(() => runEvaluation({ artifact }), /calibration selection changed|frozen threshold/);
});

test("fewer than 30 accepted cases in a group never passes", () => {
  const fixture = holdoutFixture({ probabilityByGroup: { other: 0.5 } });
  const result = runEvaluation({ fixture });
  assert.equal(result.status, "INCONCLUSIVE");
  assert.equal(result.evidence, undefined);
  assert.ok(result.metrics.groupSampleCounts.other < MIN_ACCEPTED_PER_GROUP);
});

test("a worse-than-Jev accepted subset fails the CI gate", () => {
  const fixture = holdoutFixture({ localCorrectByGroup: { machine_learning: false } });
  const result = runEvaluation({ fixture });
  assert.equal(result.status, "FAILED");
  assert.equal(result.evidence, undefined);
  assert.ok(result.metrics.groupAccuracyDeltaCI.machine_learning.ci95[0] < -0.05);
});

test("a passing evaluation emits policy-shaped evidence with provenance", () => {
  const fixture = holdoutFixture();
  const result = runEvaluation({ fixture });
  assert.equal(result.status, "PASS");
  const evidence = result.evidence;
  assert.equal(evidence.schemaVersion, 1);
  assert.equal(evidence.profileId, "technical-bookmark-topic-v1");
  assert.equal(evidence.questionsHash, questionsHash);
  assert.equal(evidence.checkpoint, checkpoint);
  assert.equal(evidence.revision, revision);
  assert.equal(evidence.heldOut, true);
  assert.equal(evidence.sampleCount, 240);
  assert.equal(evidence.confidenceLevel, 0.95);
  assert.equal(evidence.errorCount, 0);
  assert.equal(evidence.schemaErrorCount, 0);
  assert.equal(evidence.minSelectedProbability, 0.7);
  assert.ok(evidence.accuracyDeltaCI[0] >= -0.02);
  assert.deepEqual(Object.keys(evidence.groupAccuracyDeltaCI).sort(), [...CRITICAL_GROUPS].sort());
  for (const group of CRITICAL_GROUPS) {
    assert.ok(evidence.groupSampleCounts[group] >= 30);
    assert.ok(evidence.groupAccuracyDeltaCI[group][0] >= -0.05);
  }
  assert.equal(
    Object.values(evidence.groupSampleCounts).reduce((a, b) => a + b, 0),
    evidence.sampleCount
  );
  assert.ok(evidence.latencyRatio > 0 && evidence.latencyRatio < 1);
  assert.equal(evidence.totalHoldoutCount, 240);
  assert.equal(evidence.coverage, 1);
  assert.equal(evidence.resolvedJevModel, "jev-1.13.0");
  assert.equal(evidence.qualificationScope.synthetic, true);
  assert.equal(evidence.qualificationScope.labelSource, "generated-author-labeled");
  assert.equal(evidence.provenance.holdoutCorpusSha256, "0".repeat(64));
  assert.equal(Date.parse(evidence.expiresAt) - Date.parse(evidence.evaluatedAt), 7 * 24 * 60 * 60 * 1000);
  assert.equal(result.metrics.cascadeAccuracy, 1);
});

test("bootstrap intervals are deterministic for a seed and empty-safe", () => {
  const diffs = [0, 1, 1, 0, 1, 1, 1, 0];
  assert.deepEqual(bootstrapCI(diffs, 7, 200), bootstrapCI(diffs, 7, 200));
  assert.equal(bootstrapCI([], 0, 200), null);
  assert.equal(bootstrapCI(diffs, 0, 200).n, diffs.length);
  assert.equal(BOOTSTRAP_REPS, 2000);
});


test("calibration rejects a different runtime revision", () => {
 const dev=developmentFixture();
 assert.throws(()=>calibrate({definition:definition(),questionsHash,corpus:corpusSource(dev.rows,"dev"),predictions:predictionSource(dev.records,{revision:"wrong"})}),/revision/);
});
test("corpus questions must match the profile being approved", () => {
 const fixture=holdoutFixture();
 fixture.rows[0]={...fixture.rows[0],questions:{topic:{...questions.topic,instructions:"Different task"}}};
 assert.throws(()=>runEvaluation({fixture}),/questions differ/);
});
test("a saved prediction cannot disagree with the raw answer", () => {
 const fixture=holdoutFixture(); fixture.local[0].raw_answer.answers.topic.choice="other";
 assert.equal(runEvaluation({fixture}).status,"FAILED");
});
test("a threshold cannot be edited after calibration", () => {
 assert.throws(()=>runEvaluation({artifact:{...frozenArtifact(),selectedThreshold:.9,minSelectedProbability:.9}}),/selection changed/);
});
