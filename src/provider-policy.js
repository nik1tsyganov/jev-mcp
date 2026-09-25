/**
 * Evidence-bound local eligibility policy.
 *
 * Routes a caller to the local Laya runtime only when a declared profile, a
 * pinned runtime identity, and a SHA256-pinned evidence file all agree. Every
 * other outcome refuses local inference. This module loads no model runtime and makes no
 * network call.
 */

import { createHash } from "node:crypto";
import { readFileSync, readdirSync, realpathSync } from "node:fs";
import { dirname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { validateQuestions } from "./questions.js";

const moduleDir = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(moduleDir, "..");
const configDir = join(projectRoot, "config");
const defaultPolicyPath = join(configDir, "decision-profiles.json");
const packsDir = join(projectRoot, "packs");

/** The only purpose this first production fast path may route locally. */
const ALLOWED_PURPOSE = "low_risk_classification";

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isHex64(value) {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function sha256Hex(text) {
  return createHash("sha256").update(text).digest("hex");
}

function normalizeText(text) {
  return String(text).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function optionSignature(keys) {
  return keys.map((k) => String(k).toLowerCase()).sort().join("\u0000");
}

/**
 * SHA256 of the validated questions, preserving choice-option order because
 * option order affects inference.
 */
export function questionsFingerprint(questions) {
  return sha256Hex(JSON.stringify(validateQuestions(questions)));
}

/**
 * Resolve the profile id a request should use.
 *
 * An explicit string is returned unchanged, so an unknown id still reaches the
 * registry lookup and is rejected there. An omitted profile resolves to the
 * policy's configured defaultProfile only when the validated questions
 * fingerprint exactly matches that registered profile. Every other input
 * resolves to null: no task is inferred from its shape, an explicit id is never
 * replaced, and a caller cannot pass an inline profile object.
 */
export function resolveProfileId({ profile, questions, policy } = {}) {
  if (typeof profile === "string") return profile;
  if (profile !== undefined && profile !== null) return null;
  if (!isPlainObject(policy) || policy.version !== 1) return null;
  const defaultId = policy.defaultProfile;
  if (typeof defaultId !== "string" || !isPlainObject(policy.profiles)) return null;
  if (!Object.prototype.hasOwnProperty.call(policy.profiles, defaultId)) return null;
  const candidate = policy.profiles[defaultId];
  if (!isPlainObject(candidate) || !isHex64(candidate.questionsHash)) return null;
  let fingerprint;
  try {
    fingerprint = questionsFingerprint(questions);
  } catch {
    return null;
  }
  return fingerprint === candidate.questionsHash ? defaultId : null;
}

/**
 * Read the trusted local decision profile file. Defaults to
 * config/decision-profiles.json in this module's project. A caller-supplied
 * path is accepted only inside that config directory; anything else throws.
 */
export function loadPolicy({ path } = {}) {
  const target = assertTrustedPolicyPath(path === undefined ? defaultPolicyPath : path);
  const parsed = JSON.parse(readFileSync(target, "utf8"));
  if (!isPlainObject(parsed) || parsed.version !== 1 || !isPlainObject(parsed.profiles)) {
    throw new Error("decision profile file must be {version:1, profiles:{...}}.");
  }
  return parsed;
}

function assertTrustedPolicyPath(path) {
  const resolved = resolve(path);
  if (resolved === defaultPolicyPath || resolved.startsWith(configDir + sep)) {
    const physical = realpathSync(resolved);
    if (physical.startsWith(realpathSync(configDir) + sep)) return physical;
  }
  throw new Error("loadPolicy reads only this module's own config directory.");
}

let packSignatures;

/**
 * Signatures of every question defined in packs/*.json. Calibrated pack
 * questions are Jev-only, so any overlap blocks the local fast path. Fail
 * closed: if the packs cannot be read, the caller cannot prove non-overlap.
 */
function loadPackSignatures() {
  if (packSignatures) return packSignatures;
  const instructions = new Set();
  const options = new Set();
  for (const file of readdirSync(packsDir)) {
    if (!file.endsWith(".json")) continue;
    const pack = JSON.parse(readFileSync(join(packsDir, file), "utf8"));
    for (const q of Object.values(pack.questions || {})) {
      if (!isPlainObject(q)) continue;
      instructions.add(normalizeText(q.instructions));
      if (q.type === "choice" && isPlainObject(q.criteria)) {
        options.add(optionSignature(Object.keys(q.criteria)));
      }
    }
  }
  packSignatures = { instructions, options };
  return packSignatures;
}

/** Exported so the generic-local path applies the same pack-overlap
 *  protection instead of inventing its own keyword matching. */
export function overlapsCalibratedQuestion(question) {
  let signatures;
  try {
    signatures = loadPackSignatures();
  } catch {
    return true;
  }
  if (signatures.instructions.has(normalizeText(question.instructions))) return true;
  if (question.type === "choice" && isPlainObject(question.criteria)) {
    if (signatures.options.has(optionSignature(Object.keys(question.criteria)))) return true;
  }
  return false;
}

function profileShapeError(profile) {
  if (!isPlainObject(profile)) return "profile-malformed";
  if (profile.enabled !== true) return "profile-disabled";
  if (profile.purpose !== ALLOWED_PURPOSE) return "profile-purpose-unsupported";
  if (profile.maxQuestions !== 1) return "profile-malformed";
  if (!Number.isInteger(profile.maxOptions) || profile.maxOptions < 1) return "profile-malformed";
  if (!Number.isInteger(profile.maxStateChars) || profile.maxStateChars < 1) return "profile-malformed";
  if (!Number.isFinite(profile.minSelectedProbability) || profile.minSelectedProbability < 0 || profile.minSelectedProbability > 1) {
    return "profile-malformed";
  }
  if (!isHex64(profile.questionsHash)) return "profile-malformed";
  if (typeof profile.checkpoint !== "string" || !profile.checkpoint) return "profile-malformed";
  if (typeof profile.revision !== "string" || !profile.revision) return "profile-malformed";
  if (!isPlainObject(profile.evidence)) return "profile-malformed";
  if (typeof profile.evidence.path !== "string" || !profile.evidence.path) return "profile-malformed";
  if (!isHex64(profile.evidence.sha256)) return "profile-malformed";
  return null;
}

function runtimeMismatch(runtime, profile) {
  if (!isPlainObject(runtime) || runtime.available !== true) return "runtime-unavailable";
  if (runtime.checkpoint !== profile.checkpoint || runtime.revision !== profile.revision) {
    return "runtime-mismatch";
  }
  return null;
}

function serializedStateChars(state) {
  try {
    const serialized = JSON.stringify(state);
    return typeof serialized === "string" ? serialized.length : Infinity;
  } catch { return Infinity; }
}

function intervalOk(interval, minLower) {
  if (!Array.isArray(interval) || interval.length !== 2) return false;
  const [lower, upper] = interval;
  if (!Number.isFinite(lower) || !Number.isFinite(upper)) return false;
  return lower >= minLower && lower <= upper && upper <= 1;
}

function groupsOk(groupIntervals, groupCounts, total) {
  if (!isPlainObject(groupIntervals) || Object.keys(groupIntervals).length === 0) return false;
  if (!isPlainObject(groupCounts)) return false;
  for (const [group, interval] of Object.entries(groupIntervals)) {
    if (!intervalOk(interval, -0.05)) return false;
    const count = groupCounts[group];
    if (!Number.isInteger(count) || count < 30 || count > total) return false;
  }
  return true;
}

function isValidDate(value) {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

/**
 * Validate the SHA256-pinned evidence file a profile references. Evidence is
 * generated outside production; a request can never supply or overwrite it.
 */
function evidenceError(profile, profileId, now) {
  let raw;
  try {
    raw = readFileSync(resolve(projectRoot, profile.evidence.path), "utf8");
  } catch {
    return "evidence-missing";
  }
  if (sha256Hex(raw) !== profile.evidence.sha256) return "evidence-hash-mismatch";

  let evidence;
  try {
    evidence = JSON.parse(raw);
  } catch {
    return "evidence-invalid";
  }
  if (!isPlainObject(evidence)) return "evidence-invalid";
  if (evidence.schemaVersion !== 1) return "evidence-invalid";
  if (evidence.profileId !== profileId) return "evidence-invalid";
  if (evidence.questionsHash !== profile.questionsHash) return "evidence-invalid";
  if (evidence.checkpoint !== profile.checkpoint) return "evidence-invalid";
  if (evidence.revision !== profile.revision) return "evidence-invalid";
  if (evidence.heldOut !== true) return "evidence-invalid";
  if (!Number.isInteger(evidence.sampleCount) || evidence.sampleCount < 30) return "evidence-invalid";
  if (evidence.confidenceLevel !== 0.95) return "evidence-invalid";
  if (!intervalOk(evidence.accuracyDeltaCI, -0.02)) return "evidence-invalid";
  if (!groupsOk(evidence.groupAccuracyDeltaCI, evidence.groupSampleCounts, evidence.sampleCount)) return "evidence-invalid";
  if (evidence.errorCount !== 0) return "evidence-invalid";
  if (evidence.schemaErrorCount !== 0) return "evidence-invalid";
  if (!Number.isFinite(evidence.latencyRatio) || evidence.latencyRatio <= 0 || evidence.latencyRatio >= 1) {
    return "evidence-invalid";
  }
  if (evidence.minSelectedProbability !== profile.minSelectedProbability) return "evidence-invalid";
  if (!isValidDate(evidence.evaluatedAt) || !isValidDate(evidence.expiresAt)) return "evidence-invalid";
  if (!(Date.parse(evidence.evaluatedAt) <= now && now < Date.parse(evidence.expiresAt))) {
    return "evidence-expired";
  }
  return null;
}

/**
 * Validate a trusted local owner override. The owner authorized local routing
 * for a profile whose statistical qualification FAILED, so the override is
 * registry metadata plus the pinned FAILED diagnostic — never a claim that
 * qualification passed, and never anything a request can supply. The normal
 * PASS evidence schema does not apply to a FAILED diagnostic.
 */
function ownerOverrideError(profile, profileId) {
  if (profile.adoptionMode !== "owner_override" || profile.qualificationStatus !== "FAILED") {
    return "override-malformed";
  }
  const meta = profile.ownerOverride;
  if (!isPlainObject(meta)) return "override-malformed";
  if (!isValidDate(meta.requestedAt)) return "override-malformed";
  if (typeof meta.instruction !== "string" || !meta.instruction.trim()) return "override-malformed";
  if (typeof meta.reason !== "string" || !meta.reason.trim()) return "override-malformed";

  let raw;
  try {
    raw = readFileSync(resolve(projectRoot, profile.evidence.path), "utf8");
  } catch {
    return "evidence-missing";
  }
  if (sha256Hex(raw) !== profile.evidence.sha256) return "evidence-hash-mismatch";

  let diagnostic;
  try {
    diagnostic = JSON.parse(raw);
  } catch {
    return "evidence-invalid";
  }
  if (!isPlainObject(diagnostic)) return "evidence-invalid";
  if (diagnostic.profileId !== profileId) return "evidence-invalid";
  if (diagnostic.status !== "FAILED") return "evidence-invalid";
  return null;
}

/**
 * Check local eligibility. Returns provider:'laya' for an allowed profile or
 * provider:'none' with a refusal reason. Runtime pins, exact questions and
 * trusted evidence apply equally to qualified profiles and owner overrides.
 */
export function selectProvider({
  state,
  questions,
  profile,
  policy,
  runtime,
  now = Date.now(),
} = {}) {
  let profileId = null;
  const deny = (reason) => ({ provider: "none", reason, profileId, minSelectedProbability: null });

  profileId = resolveProfileId({ profile, questions, policy });
  if (typeof profileId !== "string") return deny("profile-absent");
  if (policy === undefined || policy === null) return deny("policy-unavailable");
  if (!isPlainObject(policy) || policy.version !== 1) return deny("policy-version-mismatch");
  if (!isPlainObject(policy.profiles) || !Object.prototype.hasOwnProperty.call(policy.profiles, profileId)) {
    return deny("profile-unknown");
  }
  profile = policy.profiles[profileId];

  const shapeError = profileShapeError(profile);
  if (shapeError) return deny(shapeError);

  const mismatch = runtimeMismatch(runtime, profile);
  if (mismatch) return deny(mismatch);

  let validated;
  try {
    validated = validateQuestions(questions);
  } catch {
    return deny("questions-invalid");
  }
  if (questionsFingerprint(questions) !== profile.questionsHash) return deny("questions-hash-mismatch");

  const entries = Object.entries(validated);
  if (entries.length > profile.maxQuestions) return deny("questions-count");
  for (const [, question] of entries) {
    if (question.type !== "choice") return deny("questions-unsupported-type");
  }
  for (const [, question] of entries) {
    if (Object.keys(question.criteria).length > profile.maxOptions) return deny("options-too-many");
  }
  for (const [, question] of entries) {
    if (overlapsCalibratedQuestion(question)) return deny("pack-overlap");
  }

  if (serializedStateChars(state) > profile.maxStateChars) return deny("state-too-large");

  if (profile.adoptionMode === "owner_override") {
    const overrideFailure = ownerOverrideError(profile, profileId);
    if (overrideFailure) return deny(overrideFailure);
    return {
      provider: "laya",
      reason: "owner-override",
      profileId,
      minSelectedProbability: profile.minSelectedProbability,
    };
  }

  const evidenceFailure = evidenceError(profile, profileId, now);
  if (evidenceFailure) return deny(evidenceFailure);

  return {
    provider: "laya",
    reason: "eligible",
    profileId,
    minSelectedProbability: profile.minSelectedProbability,
  };
}
