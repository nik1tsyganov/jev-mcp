import { createHash } from "node:crypto";
import { appendFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

import { validateQuestions } from "./questions.js";
import { loadPolicy, overlapsCalibratedQuestion, questionsFingerprint, resolveProfileId, selectProvider } from "./provider-policy.js";
import { createLayaClient, sanitizeLayaError } from "./laya-client.js";

const DEFAULT_LOG = join(homedir(), ".claude", "docs", "telemetry", "laya-decisions.jsonl");

function envLayaConfig(env) {
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

// Returns the generic worker and, when it was built here, the config it was built from.
function resolveLocalClient(laya, createClient) {
  try {
    if (laya && typeof laya.predict === "function") return { client: laya, config: null };
    const config = laya || envLayaConfig(process.env);
    return config ? { client: createClient(config), config } : { client: null, config: null };
  } catch {
    return { client: null, config: null };
  }
}

function numberOrNull(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function choiceProbability(answer) {
  const probs = answer.probabilities;
  if (!probs || typeof probs !== "object" || Array.isArray(probs)) return null;
  if (typeof answer.choice !== "string" || !Object.prototype.hasOwnProperty.call(probs, answer.choice)) {
    return null;
  }
  return numberOrNull(probs[answer.choice]);
}

function modalProbability(answer) {
  const probs = answer.probabilities;
  if (!probs || typeof probs !== "object" || Array.isArray(probs)) return null;
  const values = Object.values(probs).map(numberOrNull).filter((n) => n !== null);
  return values.length ? Math.max(...values) : null;
}

/** The selected label's probability, never an entropy-based confidence. */
function selectedProbability(answer) {
  if (!answer || typeof answer !== "object") return null;
  if (answer.type === "noul") {
    const p = numberOrNull(answer.noul);
    // A binary answer selects the side it leans to; report that side's probability.
    return p === null ? null : Math.max(p, 1 - p);
  }
  if (answer.type === "choice") return choiceProbability(answer);
  if (answer.type === "score") return modalProbability(answer);
  return null;
}

/** Returns a short failure code, or null when the local result is eligible. */
function localResultFailure(questions, pred, runtime) {
  if (!pred || typeof pred !== "object") return "empty-result";
  if (pred.truncated === true) return "truncated";
  const answers = pred.answers;
  if (!answers || typeof answers !== "object") return "missing-answers";
  if (runtime?.checkpoint != null && pred.checkpoint !== runtime.checkpoint) {
    return "checkpoint-mismatch";
  }
  if (runtime?.revision != null && pred.revision !== runtime.revision) {
    return "revision-mismatch";
  }
  if (Object.keys(answers).length !== Object.keys(questions).length) return "answer-count-mismatch";
  for (const [id, q] of Object.entries(questions)) {
    const a = answers[id];
    if (!a || typeof a !== "object") return "missing-answer";
    if (a.type !== q.type) return "type-mismatch";
    if (q.type === "noul") {
      const p = numberOrNull(a.noul);
      if (p === null || p < 0 || p > 1) return "invalid-noul";
    } else if (q.type === "choice") {
      const p = choiceProbability(a);
      const labels = Object.keys(q.criteria);
      if (p === null || !labels.includes(a.choice) || !validDistribution(a.probabilities, labels)) return "invalid-choice";
    } else {
      const labels = q.criteria.map((_, i) => String(i));
      if (!validDistribution(a.probabilities, labels) || !Number.isFinite(a.score) || a.score < 0 || a.score > labels.length - 1 ||
          !a.legend || labels.some((key) => a.legend[key] !== q.criteria[Number(key)])) return "invalid-score";
    }
  }
  if (typeof pred.model !== "string" || !pred.model || !pred.usage ||
      ["input_tokens", "output_tokens"].some((k) => !Number.isInteger(pred.usage[k]) || pred.usage[k] < 0)) return "invalid-envelope";
  return null;
}

function validDistribution(probabilities, labels) {
  if (!probabilities || Array.isArray(probabilities) || Object.keys(probabilities).length !== labels.length) return false;
  const values = labels.map((k) => Object.hasOwn(probabilities, k) ? probabilities[k] : NaN);
  return values.every((p) => Number.isFinite(p) && p >= 0 && p <= 1) &&
    Math.abs(values.reduce((a, b) => a + b, 0) - 1) <= Math.max(0.001, labels.length * 0.000051);
}

/** Minimum selected-label probability across every answer, or null if unscoreable. */
function minimumSelectedProbability(questions, answers) {
  let min = null;
  for (const id of Object.keys(questions)) {
    const p = selectedProbability(answers[id]);
    if (p === null) return null;
    min = min === null ? p : Math.min(min, p);
  }
  return min;
}

function requestHash(state, questions) {
  return createHash("sha256").update(JSON.stringify({ state, questions })).digest("hex");
}

function isTrustedPolicy(policy) {
  return Boolean(policy) && typeof policy === "object" && !Array.isArray(policy) &&
    policy.version === 1 && Boolean(policy.profiles) &&
    typeof policy.profiles === "object" && !Array.isArray(policy.profiles);
}

export function createLayaService({
  laya,
  createClient = createLayaClient,
  policy,
  logPath,
  now = Date.now,
} = {}) {
  const policyApi = policy && typeof policy.selectProvider === "function"
    ? policy
    : { loadPolicy, questionsFingerprint, resolveProfileId, selectProvider };
  let loadedPolicy = policy && typeof policy.selectProvider !== "function" ? policy : null;
  const { client: envClient, config: envConfig } = resolveLocalClient(laya, createClient);
  const decisionLog = logPath || process.env.LAYA_DECISION_LOG || DEFAULT_LOG;
  const counters = { asks: 0, accepted: 0, rejected: 0, errors: 0 };
  let lastReason = null;
  let closed = false;

  function clientStatus(client) {
    if (!client) return { available: false, reason: "not-configured" };
    try {
      const s = client.status();
      if (!s || typeof s !== "object") return { available: false, reason: "invalid-status" };
      return s;
    } catch {
      return { available: false, reason: "status-error" };
    }
  }

  // Persistent workers for the configured profile runtimes. The cache key is the
  // complete trusted identity, so a registry change to any pinned field can never
  // reuse a worker built for a different model. At most two stay resident.
  const profileClients = new Map();
  const MAX_PROFILE_CLIENTS = 2;

  function profileRuntimeConfig(profile) {
    const runtime = profile?.runtime;
    if (!runtime || typeof runtime !== "object") return null;
    return {
      python: runtime.python ?? null,
      modelPath: runtime.modelPath ?? null,
      timeoutMs: runtime.timeoutMs,
      maxQueue: runtime.maxQueue,
      checkpoint: profile.checkpoint,
      revision: profile.revision,
    };
  }

  // Unset limits resolve to the laya-client defaults (30000 ms, queue 8), so an
  // env config that omits them still matches a profile that pins those values.
  function runtimeKey(config) {
    return JSON.stringify([
      config.python ?? null,
      config.modelPath ?? null,
      config.timeoutMs ?? 30000,
      config.maxQueue ?? 8,
      config.checkpoint ?? null,
      config.revision ?? null,
    ]);
  }

  // A profile whose runtime identity equals the env config shares the env worker,
  // so the same model is never loaded twice. The env worker is never cached in
  // profileClients, so refresh and eviction cannot close it.
  const envKey = envClient && envConfig ? runtimeKey(envConfig) : null;

  // Refresh and eviction retire a worker: a request it is serving or has queued
  // still completes. Retired workers are kept until they close so shutdown can
  // close them immediately.
  const retiredClients = new Set();

  function closeClient(client, { whenIdle = false } = {}) {
    if (!client || typeof client.close !== "function") return;
    try {
      if (whenIdle && typeof client.closeWhenIdle === "function") {
        retiredClients.add(client);
        Promise.resolve(client.closeWhenIdle()).then(
          () => retiredClients.delete(client), () => retiredClients.delete(client));
        return;
      }
      const result = client.close();
      if (result && typeof result.catch === "function") result.catch(() => {});
    } catch {
      /* Shutdown is best effort. */
    }
  }

  function refreshPolicy() {
    if (policy === undefined || typeof policy?.selectProvider === "function") {
      try { loadedPolicy = policyApi.loadPolicy({}); } catch { loadedPolicy = null; }
    }
    const keys = new Set(Object.values(loadedPolicy?.profiles ?? {})
      .map(profileRuntimeConfig).filter(Boolean).map(runtimeKey));
    for (const [key, client] of profileClients) {
      if (!keys.has(key)) {
        closeClient(client, { whenIdle: true });
        profileClients.delete(key);
      }
    }
  }

  function getProfileClient(profileId) {
    const config = profileRuntimeConfig(loadedPolicy?.profiles?.[profileId]);
    if (!config) return null;
    const key = runtimeKey(config);
    if (key === envKey) return envClient;
    if (profileClients.has(key)) {
      const existing = profileClients.get(key);
      profileClients.delete(key);
      profileClients.set(key, existing);
      return existing;
    }
    let client;
    try {
      client = createClient(config);
    } catch {
      return null;
    }
    if (!client || typeof client.predict !== "function") {
      closeClient(client);
      return null;
    }
    profileClients.set(key, client);
    while (profileClients.size > MAX_PROFILE_CLIENTS) {
      const oldest = profileClients.keys().next().value;
      closeClient(profileClients.get(oldest), { whenIdle: true });
      profileClients.delete(oldest);
    }
    return client;
  }

  // Resolve the registered profile before any worker is chosen. An explicit
  // string stays explicit; an omitted profile resolves only when the policy
  // recognizes the exact question fingerprint, otherwise it stays unprofiled.
  function resolveProfile(profile, questions) {
    if (typeof policyApi.resolveProfileId === "function") {
      try {
        const id = policyApi.resolveProfileId({ profile, questions, policy: loadedPolicy });
        return typeof id === "string" && id ? id : null;
      } catch {
        return typeof profile === "string" ? profile : null;
      }
    }
    return typeof profile === "string" ? profile : null;
  }

  function appendLog(record) {
    try {
      mkdirSync(dirname(decisionLog), { recursive: true });
      appendFileSync(decisionLog, JSON.stringify(record) + "\n");
    } catch {
      /* Telemetry must never change a judgment. */
    }
  }

  async function ask({ state, questions, profile } = {}) {
    const started = now();
    const record = {
      event: "ask",
      ts: new Date(started).toISOString(),
      inputHash: null,
      fingerprint: null,
      provider: "none",
      reason: null,
      profile: null,
      adoptionMode: null,
      qualificationStatus: null,
      model: null,
      checkpoint: null,
      revision: null,
      accepted: false,
      error: null,
    };
    counters.asks++;
    try {
      if (closed) throw new Error("Laya service is closed.");
      if (profile !== undefined && (typeof profile !== "string" || !profile || profile.length > 128)) {
        throw new Error("profile must be a registered profile id.");
      }
      if (state === undefined || state === null || (typeof state !== "string" && typeof state !== "object")) {
        throw new Error("The state is required and must be a string, object or array.");
      }
      const validated = validateQuestions(questions);
      const snapshot = JSON.stringify({ state, questions: validated });
      if (Object.keys(validated).length > 32 || (typeof state === "string" ? state.length : JSON.stringify(state).length) > 200000) {
        throw new Error("Laya request exceeds the state or question limit.");
      }
      ({ state, questions } = JSON.parse(snapshot));
      record.inputHash = requestHash(state, questions);
      record.fingerprint = questionsFingerprint(questions);
      refreshPolicy();
      const profileId = resolveProfile(profile, questions);
      record.profile = profileId;
      const profileConfig = profileId ? loadedPolicy?.profiles?.[profileId] : null;
      record.adoptionMode = profileConfig?.adoptionMode ?? null;
      record.qualificationStatus = profileConfig?.qualificationStatus ?? null;
      const client = profileId ? getProfileClient(profileId) : envClient;
      const runtime = clientStatus(client);
      const decision = policyApi.selectProvider({ state, questions, profile: profileId,
        policy: loadedPolicy, runtime, now: now() });
      if (!decision || !["laya", "none"].includes(decision.provider)) {
        throw new Error("invalid-policy-decision");
      }
      const generic = profile === undefined && !profileId && decision.provider === "none" &&
        decision.reason === "profile-absent" && isTrustedPolicy(loadedPolicy);
      if (decision.provider !== "laya" && !generic) {
        record.reason = decision.reason || "no-eligible-local-profile";
        throw new Error(record.reason);
      }
      // Questions registered to a non-default profile must name it; they never run thresholdless.
      if (generic && Object.values(loadedPolicy.profiles).some((p) => p?.questionsHash === record.fingerprint)) {
        record.reason = "profile-required";
        throw new Error(record.reason);
      }
      if (generic && Object.values(questions).some(overlapsCalibratedQuestion)) {
        record.reason = "pack-overlap";
        throw new Error(record.reason);
      }
      if (generic) record.qualificationStatus = "UNQUALIFIED";
      if (!client || runtime.available !== true) {
        record.reason = "local-unavailable";
        throw new Error(record.reason);
      }
      let prediction;
      try {
        prediction = await client.predict({ state, questions });
      } catch (error) {
        record.reason = "local-error";
        throw error;
      }
      const failure = localResultFailure(questions, prediction, runtime);
      if (failure) {
        record.reason = `local-invalid:${failure}`;
        throw new Error(record.reason);
      }
      const selected = minimumSelectedProbability(questions, prediction.answers);
      if (selected === null) {
        record.reason = "local-unscored";
        throw new Error(record.reason);
      }
      const threshold = Number.isFinite(decision.minSelectedProbability) ? decision.minSelectedProbability : 0;
      const accepted = generic || selected >= threshold;
      const reason = accepted ? null : "below_threshold";
      Object.assign(record, {
        provider: "laya", reason, accepted,
        model: prediction.model,
        checkpoint: prediction.checkpoint ?? runtime.checkpoint ?? null,
        revision: prediction.revision ?? runtime.revision ?? null,
      });
      counters[accepted ? "accepted" : "rejected"]++;
      return {
        provider: "laya",
        profile: profileId,
        checkpoint: record.checkpoint,
        revision: record.revision,
        qualification: record.qualificationStatus,
        accepted,
        reason,
        answers: prediction.answers,
      };
    } catch (error) {
      counters.errors++;
      record.reason ??= "local-request-failed";
      record.error = "local-request-failed";
      throw new Error(sanitizeLayaError(error?.message ?? String(error)));
    } finally {
      lastReason = record.reason;
      appendLog({ ...record, durationMs: now() - started });
    }
  }

  function profileStatus() {
    const out = {};
    const profiles = loadedPolicy?.profiles;
    if (!profiles || typeof profiles !== "object") return out;
    for (const [id, profile] of Object.entries(profiles)) {
      if (!profile || typeof profile !== "object") continue;
      const config = profileRuntimeConfig(profile);
      const key = config ? runtimeKey(config) : null;
      const client = key === null ? null : key === envKey ? envClient : profileClients.get(key) ?? null;
      out[id] = {
        configured: Boolean(config?.python && config?.modelPath && config?.checkpoint && config?.revision),
        enabled: profile.enabled === true,
        adoptionMode: profile.adoptionMode ?? null,
        qualificationStatus: profile.qualificationStatus ?? null,
        checkpoint: profile.checkpoint ?? null,
        revision: profile.revision ?? null,
        minSelectedProbability: numberOrNull(profile.minSelectedProbability),
        runtime: config
          ? {
            python: config.python ?? null,
            modelPath: config.modelPath ?? null,
            timeoutMs: config.timeoutMs ?? null,
            maxQueue: config.maxQueue ?? null,
          }
          : null,
        resident: client !== null,
        status: client ? clientStatus(client) : { available: false, reason: "not-resident" },
      };
    }
    return out;
  }

  function status() {
    refreshPolicy();
    return {
      local: clientStatus(envClient),
      counters: { ...counters },
      lastReason,
      closed,
      profiles: profileStatus(),
    };
  }

  async function close() {
    if (closed) return;
    closed = true;
    const clients = [envClient, ...profileClients.values(), ...retiredClients];
    profileClients.clear();
    retiredClients.clear();
    await Promise.all(clients.map(async (client) => {
      if (!client || typeof client.close !== "function") return;
      try {
        await client.close();
      } catch {
        /* Shutdown is best effort. */
      }
    }));
  }

  return { ask, status, close };
}
