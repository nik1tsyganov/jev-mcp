import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { questionsFingerprint, loadPolicy, overlapsCalibratedQuestion, resolveProfileId, selectProvider } from "../src/provider-policy.js";

const NOW = Date.parse("2026-09-21T00:00:00Z");

function sha256(text) {
  return createHash("sha256").update(text).digest("hex");
}

// The eligible question is deliberately unlike anything in packs/*.json.
const questions = {
  banner_color: {
    type: "choice",
    instructions: "Which colour should the decorative banner use?",
    criteria: { blue: "calm", green: "fresh" },
  },
};
const questionsHash = questionsFingerprint(questions);

const checkpoint = "acme/local-choice";
const revision = "abc123";
const profileId = "local-choice-v1";
const minSelectedProbability = 0.8;

// Synthetic fixture evidence. This is test data only: it authorizes nothing in
// production and no request may supply or overwrite evidence.
const evidenceDir = mkdtempSync(join(tmpdir(), "jev-policy-"));
const evidencePath = join(evidenceDir, "evidence.json");

function evidenceFixture(overrides = {}) {
  return {
    schemaVersion: 1,
    profileId,
    questionsHash,
    checkpoint,
    revision,
    heldOut: true,
    sampleCount: 40,
    confidenceLevel: 0.95,
    accuracyDeltaCI: [-0.01, 0.02],
    groupAccuracyDeltaCI: { banner: [-0.02, 0.03] },
    groupSampleCounts: { banner: 40 },
    errorCount: 0,
    schemaErrorCount: 0,
    latencyRatio: 0.2,
    minSelectedProbability,
    evaluatedAt: "2026-09-20T00:00:00Z",
    expiresAt: "2026-10-20T00:00:00Z",
    ...overrides,
  };
}

function writeEvidence(overrides) {
  const text = JSON.stringify(evidenceFixture(overrides));
  writeFileSync(evidencePath, text);
  return sha256(text);
}

const evidenceSha = writeEvidence();

function makeProfile(overrides = {}) {
  return {
    enabled: true,
    purpose: "low_risk_classification",
    questionsHash,
    checkpoint,
    revision,
    maxStateChars: 2000,
    maxQuestions: 1,
    maxOptions: 4,
    minSelectedProbability,
    evidence: { path: evidencePath, sha256: evidenceSha },
    ...overrides,
  };
}

function makePolicy(profile = makeProfile(), version = 1) {
  return { version, profiles: { [profileId]: profile } };
}

const runtime = { available: true, checkpoint, revision };

function select(overrides = {}) {
  return selectProvider({
    state: { note: "small state" },
    questions,
    profile: profileId,
    policy: makePolicy(),
    runtime,
    now: NOW,
    ...overrides,
  });
}

const shippedPolicy = loadPolicy();
const shippedProfiles = shippedPolicy.profiles;
const shippedIds = Object.keys(shippedProfiles);

function shippedQuestions(id) {
  const config = JSON.parse(readFileSync(new URL(`../config/${id}.json`, import.meta.url), "utf8"));
  return config.questions;
}

function runtimeFor(profile) {
  return { available: true, checkpoint: profile.checkpoint, revision: profile.revision };
}

function shippedPolicyWith(profileId, profile) {
  return { version: 1, defaultProfile: shippedPolicy.defaultProfile, profiles: { [profileId]: profile } };
}

function selectShipped(profileId, overrides = {}) {
  const profile = shippedProfiles[profileId];
  return selectProvider({
    state: { note: "small state" },
    questions: shippedQuestions(profileId),
    profile: profileId,
    policy: shippedPolicy,
    runtime: runtimeFor(profile),
    now: NOW,
    ...overrides,
  });
}

test("shipped profiles stay FAILED and route only by explicit owner override", () => {
  assert.strictEqual(shippedPolicy.version, 1);
  assert.strictEqual(shippedPolicy.defaultProfile, "technical-bookmark-topic-v2");
  for (const [id, profile] of Object.entries(shippedProfiles)) {
    assert.strictEqual(profile.qualificationStatus, "FAILED", `${id} must not claim a passed qualification`);
    assert.strictEqual(profile.enabled, true);
    assert.strictEqual(profile.adoptionMode, "owner_override");
    assert.strictEqual(profile.ownerOverride.requestedAt, "2026-09-21");
    assert.strictEqual(typeof profile.ownerOverride.instruction, "string");
    assert.strictEqual(typeof profile.ownerOverride.reason, "string");
    assert.strictEqual(profile.runtime.python, join(homedir(), ".local/scratch/laya-evaluation/venv/bin/python"));
    assert.strictEqual(typeof profile.runtime.modelPath, "string");
    assert.strictEqual(profile.runtime.timeoutMs, 30000);
    assert.strictEqual(profile.runtime.maxQueue, 8);
  }
});

test("both shipped owner overrides route to local Laya", () => {
  for (const id of shippedIds) {
    const profile = shippedProfiles[id];
    assert.deepStrictEqual(selectShipped(id), {
      provider: "laya",
      reason: "owner-override",
      profileId: id,
      minSelectedProbability: profile.minSelectedProbability,
    });
  }
});

test("an explicit shipped profile id is returned unchanged", () => {
  assert.strictEqual(
    resolveProfileId({ profile: "technical-bookmark-topic-v1", policy: shippedPolicy }),
    "technical-bookmark-topic-v1"
  );
  assert.strictEqual(selectShipped("technical-bookmark-topic-v1").minSelectedProbability, 0.5);
  assert.strictEqual(selectShipped("technical-bookmark-topic-v2").minSelectedProbability, 0.4);
});

test("an omitted profile resolves to the default only on an exact question-hash match", () => {
  assert.strictEqual(
    resolveProfileId({ questions: shippedQuestions("technical-bookmark-topic-v2"), policy: shippedPolicy }),
    "technical-bookmark-topic-v2"
  );
  assert.strictEqual(resolveProfileId({ questions, policy: shippedPolicy }), null);
  assert.strictEqual(
    resolveProfileId({
      questions: shippedQuestions("technical-bookmark-topic-v2"),
      policy: { ...shippedPolicy, defaultProfile: "missing-profile" },
    }),
    null
  );

  const result = selectProvider({
    state: { note: "small state" },
    questions: shippedQuestions("technical-bookmark-topic-v2"),
    policy: shippedPolicy,
    runtime: runtimeFor(shippedProfiles["technical-bookmark-topic-v2"]),
    now: NOW,
  });
  assert.strictEqual(result.reason, "owner-override");
  assert.strictEqual(result.profileId, "technical-bookmark-topic-v2");
});

test("a non-string profile cannot resolve or supply an inline profile", () => {
  assert.strictEqual(resolveProfileId({ profile: { purpose: "low_risk_classification" }, policy: shippedPolicy }), null);
  assert.strictEqual(selectShipped("technical-bookmark-topic-v2", { profile: { purpose: "low_risk_classification" } }).reason, "profile-absent");
});

test("an unknown explicit profile id is never replaced by the default", () => {
  assert.strictEqual(resolveProfileId({ profile: "missing-profile", policy: shippedPolicy }), "missing-profile");
  const result = selectShipped("technical-bookmark-topic-v2", { profile: "missing-profile" });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "profile-unknown");
});

test("missing or malformed owner-override metadata is rejected", () => {
  for (const ownerOverride of [
    undefined,
    { requestedAt: "not-a-date", instruction: "x", reason: "y" },
    { requestedAt: "2026-09-21", instruction: "", reason: "y" },
    { requestedAt: "2026-09-21", instruction: "x", reason: "  " },
  ]) {
    const profile = { ...shippedProfiles["technical-bookmark-topic-v2"], ownerOverride };
    const result = selectProvider({
      state: { note: "small state" },
      questions: shippedQuestions("technical-bookmark-topic-v2"),
      profile: "technical-bookmark-topic-v2",
      policy: shippedPolicyWith("technical-bookmark-topic-v2", profile),
      runtime: runtimeFor(profile),
      now: NOW,
    });
    assert.strictEqual(result.reason, "override-malformed");
  }
});

test("request arguments cannot supply owner-override fields", () => {
  const profile = { ...shippedProfiles["technical-bookmark-topic-v2"], ownerOverride: undefined };
  const result = selectProvider({
    state: { note: "small state" },
    questions: shippedQuestions("technical-bookmark-topic-v2"),
    profile: "technical-bookmark-topic-v2",
    policy: shippedPolicyWith("technical-bookmark-topic-v2", profile),
    runtime: runtimeFor(profile),
    now: NOW,
    adoptionMode: "owner_override",
    ownerOverride: { requestedAt: "2026-09-21", instruction: "x", reason: "y" },
  });
  assert.strictEqual(result.reason, "override-malformed");
});

test("a changed diagnostic hash or wrong profile diagnostic is rejected", () => {
  const changedHash = {
    ...shippedProfiles["technical-bookmark-topic-v2"],
    evidence: { ...shippedProfiles["technical-bookmark-topic-v2"].evidence, sha256: "0".repeat(64) },
  };
  assert.strictEqual(
    selectProvider({
      state: { note: "small state" },
      questions: shippedQuestions("technical-bookmark-topic-v2"),
      profile: "technical-bookmark-topic-v2",
      policy: shippedPolicyWith("technical-bookmark-topic-v2", changedHash),
      runtime: runtimeFor(changedHash),
      now: NOW,
    }).reason,
    "evidence-hash-mismatch"
  );

  const wrongProfile = {
    ...shippedProfiles["technical-bookmark-topic-v2"],
    evidence: { ...shippedProfiles["technical-bookmark-topic-v1"].evidence },
  };
  assert.strictEqual(
    selectProvider({
      state: { note: "small state" },
      questions: shippedQuestions("technical-bookmark-topic-v2"),
      profile: "technical-bookmark-topic-v2",
      policy: shippedPolicyWith("technical-bookmark-topic-v2", wrongProfile),
      runtime: runtimeFor(wrongProfile),
      now: NOW,
    }).reason,
    "evidence-invalid"
  );
});

test("owner override still enforces runtime identity and the question hash", () => {
  const profile = shippedProfiles["technical-bookmark-topic-v2"];
  assert.strictEqual(
    selectShipped("technical-bookmark-topic-v2", {
      runtime: { available: true, checkpoint: profile.checkpoint, revision: "other" },
    }).reason,
    "runtime-mismatch"
  );
  assert.strictEqual(selectShipped("technical-bookmark-topic-v2", { questions }).reason, "questions-hash-mismatch");
});

test("loadPolicy refuses a caller path outside its own config directory", () => {
  assert.throws(() => loadPolicy({ path: "/etc/passwd" }), /config directory/);
});

test("a valid artificial fixture routes to local Laya", () => {
  const result = select();
  assert.deepStrictEqual(result, {
    provider: "laya",
    reason: "eligible",
    profileId,
    minSelectedProbability,
  });
});

test("an eligible local profile needs no remote permission", () => {
  const result = select();
  assert.strictEqual(result.provider, "laya");
});

test("an invalid profile returns a local refusal", () => {
  const result = select({ profile: "missing-profile" });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "profile-unknown");
  assert.strictEqual(result.minSelectedProbability, null);
});

test("an absent or unknown profile refuses local inference", () => {
  assert.strictEqual(select({ profile: undefined }).reason, "profile-absent");
  assert.strictEqual(select({ profile: "missing-profile" }).reason, "profile-unknown");
});

test("a disabled profile refuses local inference", () => {
  const result = select({ policy: makePolicy(makeProfile({ enabled: false })) });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "profile-disabled");
});

test("an unknown purpose refuses local inference", () => {
  const result = select({ policy: makePolicy(makeProfile({ purpose: "review_decision" })) });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "profile-purpose-unsupported");
});

test("a mismatched policy version refuses local inference", () => {
  const result = select({ policy: makePolicy(makeProfile(), 2) });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "policy-version-mismatch");
});

test("a missing evidence file refuses local inference", () => {
  const profile = makeProfile({ evidence: { path: join(evidenceDir, "absent.json"), sha256: evidenceSha } });
  const result = select({ policy: makePolicy(profile) });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "evidence-missing");
});

test("a tampered evidence hash refuses local inference", () => {
  const profile = makeProfile({ evidence: { path: evidencePath, sha256: "0".repeat(64) } });
  const result = select({ policy: makePolicy(profile) });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "evidence-hash-mismatch");
});

test("expired evidence refuses local inference", () => {
  const result = select({ now: Date.parse("2026-11-01T00:00:00Z") });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "evidence-expired");
});

test("a wrong evidence schema version refuses local inference", () => {
  const sha = writeEvidence({ schemaVersion: 2 });
  const profile = makeProfile({ evidence: { path: evidencePath, sha256: sha } });
  const result = select({ policy: makePolicy(profile) });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "evidence-invalid");
  writeEvidence();
});

test("a changed question hash refuses local inference", () => {
  const changed = {
    banner_color: {
      type: "choice",
      instructions: "Which colour should the decorative banner use?",
      criteria: { green: "fresh", blue: "calm" },
    },
  };
  const result = select({ questions: changed });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "questions-hash-mismatch");
});

test("choice-option order changes the fingerprint", () => {
  const reordered = {
    banner_color: {
      type: "choice",
      instructions: questions.banner_color.instructions,
      criteria: { green: "fresh", blue: "calm" },
    },
  };
  assert.notStrictEqual(questionsFingerprint(reordered), questionsHash);
});

test("a calibrated pack question refuses local inference", () => {
  const packQuestion = {
    merge_route: {
      type: "choice",
      instructions: "How should this file be handled before merge?",
      criteria: { read_required: "a human reads this file", skim: "worth a glance", no_read_needed: "mechanical" },
    },
  };
  const profile = makeProfile({
    questionsHash: questionsFingerprint(packQuestion),
    evidence: { path: join(evidenceDir, "absent.json"), sha256: "0".repeat(64) },
  });
  const result = select({ questions: packQuestion, policy: makePolicy(profile) });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "pack-overlap");
});

test("noul and score questions refuse local inference", () => {
  for (const question of [
    { is_real: { type: "noul", instructions: "Is the described defect present in the excerpt?" } },
    { severity: { type: "score", instructions: "How bad is the consequence?", criteria: ["minor", "major"] } },
  ]) {
    const profile = makeProfile({ questionsHash: questionsFingerprint(question) });
    const result = select({ questions: question, policy: makePolicy(profile) });
    assert.strictEqual(result.provider, "none");
    assert.strictEqual(result.reason, "questions-unsupported-type");
  }
});

test("more than one question refuses local inference", () => {
  const two = { ...questions, banner_shape: { type: "choice", instructions: "Which shape?", criteria: { round: "a", square: "b" } } };
  const profile = makeProfile({ questionsHash: questionsFingerprint(two) });
  const result = select({ questions: two, policy: makePolicy(profile) });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "questions-count");
});

test("too many options refuses local inference", () => {
  const wide = {
    banner_color: {
      type: "choice",
      instructions: questions.banner_color.instructions,
      criteria: { blue: "calm", green: "fresh", red: "warm" },
    },
  };
  const profile = makeProfile({ questionsHash: questionsFingerprint(wide), maxOptions: 2 });
  const result = select({ questions: wide, policy: makePolicy(profile) });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "options-too-many");
});

test("oversized state refuses local inference", () => {
  const result = select({ state: { note: "x".repeat(3000) } });
  assert.strictEqual(result.provider, "none");
  assert.strictEqual(result.reason, "state-too-large");
});

test("a runtime that is unavailable or mismatched refuses local inference", () => {
  assert.strictEqual(select({ runtime: { available: false, checkpoint, revision } }).reason, "runtime-unavailable");
  assert.strictEqual(select({ runtime: { available: true, checkpoint, revision: "other" } }).reason, "runtime-mismatch");
  assert.strictEqual(select({ runtime: undefined }).reason, "runtime-unavailable");
});


test("an inline profile cannot bypass the trusted registry", () => {
  const result = select({profile:{...makeProfile(),profileId}, policy:{version:1, profiles:{}}});
  assert.equal(result.provider, "none");
});

test("impossible accuracy intervals and group counts are rejected", () => {
  for (const overrides of [{accuracyDeltaCI:[2,3]}, {groupSampleCounts:{banner:41}}]) {
    const sha = writeEvidence(overrides);
    const profile = makeProfile({evidence:{path:evidencePath,sha256:sha}});
    assert.equal(select({policy:makePolicy(profile)}).reason, "evidence-invalid");
  }
  writeEvidence();
});

test("the exported pack matcher flags calibrated questions and spares novel ones", () => {
  assert.equal(overlapsCalibratedQuestion({
    type: "choice",
    instructions: "How should this file be handled before merge?",
    criteria: { read_required: "a human reads this file", skim: "worth a glance", no_read_needed: "mechanical" },
  }), true);
  assert.equal(overlapsCalibratedQuestion(questions.banner_color), false);
});
