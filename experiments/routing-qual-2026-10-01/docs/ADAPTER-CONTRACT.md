# Routing classifier adapter contract

Status: draft contract, 2026-10-02. This document defines **schema compatibility** only. It shows that fields can be mapped. It is not empirical qualification, and no backend is qualified (see `REPORT.md` section 7). It defines how a routing-benchmark result may reach the Oracle routing helper (`--oracle-route`) and Conclave. It does not activate a backend, edit saved pairs, change Conclave seats or accounts, or grant dispatch. Field sources are in `ORACLE-HELPER-SCHEMA.md`.

## 1. Backend boundary

- One backend per request: `jev`, `laya`, `qwen_reranker` or `decider`. One attempt. There is no retry and no fallback to another backend. Jev is the owner's backend. Laya is an optional local backend for people without Jev. It is never an automatic substitute for Jev, and Jev is never a substitute for Laya.
- A local selection (`laya`, `qwen_reranker`, `decider`) runs under the deny-network sandbox (`adapters/local_sandbox.py`) with Hugging Face offline flags. A local request must never cause a remote call. Evidence: `control_network` returns `network_blocked` (EPERM) in the sandbox, and the same connection succeeds outside it.
- Input is never truncated or shortened. Over-limit input returns `input_over_limit` with the token count and the limit. Laya's limits are 1,024 sequence tokens, 256 head tokens and 48 option tokens; Qwen and Decider use 4,096.
- Every error becomes the route outcome `backend-unavailable`. The caller then keeps the current configuration or abstains. That is the only fallback.

## 2. Classifier request and answer

- State: `task_text`, `mode`, `metadata` (`questions.build_state`). Questions: `routing-q-v1`, five choice questions, batched in one request.
- Answer: full probability distributions for all five questions. They are validated unchanged (`questions.validate_answers`): the sum must be within max(1e-3, 0.005 x label count), and nothing is renormalized or filled in. Selected-label-only answers are `malformed`.

## 3. Route object (policy output)

`policy.route` returns: `outcome`, `candidate_id`, `lead`, `heads`, `checkers`, `helper_count`, `mode`, `routed_task_class`, `routed_effort`, `flag_suggestion`, `reasons`, `uncertainty`, `provenance`, and `dispatch_authorized: false`. The `uncertainty` object always has `calibrated: false`. `provenance` carries backend, classifier model, revision, question-set, policy and catalog versions, rule name and thresholds.

- `helper_count` is the configured count of a saved pair or seat binding; it is never reduced.
- An experimental composition sums its two sides' counts and is task-scoped.
- The policy never reads task text.

## 4. Mapping to the Oracle helper

| Helper field | Benchmark source | Rule |
|---|---|---|
| `OracleRoutingResult.outcome` | `outcome` | Same five strings |
| `recommendation.id` / `binding.candidateID` | `candidate_id` | Saved pair or seat binding only; a composition goes to `composition` |
| `resolvedConfiguration.lead*` | `lead.model/provider/effort` | Provider names: anthropic, openai, google, cognition. Helper vendor names need an explicit mapping table |
| `defaultHead` / `profiles` | `heads` | Configuration values, not executed helpers |
| `composition.helperCount` | `helper_count` | Must equal the configured sum |
| `classification.taskClass` | `routed_task_class` | Conclave mode only, and only for labels in both vocabularies (see section 6) |
| `confidence` + `confidenceProvenance` | `uncertainty.class_top_p` + `"response-reported, uncalibrated"` | Never described as routing accuracy |
| `reasons` | `reasons` | Candidate eligibility stays per candidate |
| `dispatchAuthorized` | `dispatch_authorized` | Always false |

### Qualification record

The helper's `OracleRoutingQualification` requires `capability = "oracle-classification-policy-v1"`. That capability names the helper's own classification question. This benchmark measures a different formulation: `routing-q-v1` questions plus `routing-policy-v1.1`.

A benchmark result therefore **must not be exported as `oracle-classification-policy-v1` evidence**. The export uses `capability = "routing-q-v1+routing-policy-v1.1"`. The current helper rejects that capability, so it gets no qualified rows from this benchmark.

There are two ways to connect them, and both need owner approval:

- (a) Add the benchmark capability to the helper.
- (b) Run this benchmark through the helper's own question.

Export fields when a gate passes:

- `caller`
- `backend`: `jev` or `laya` (the helper enum has no Qwen or Decider)
- `model`: exact model id and revision
- `capability`
- `evidenceVersion`: the `FROZEN.json` SHA-256 plus `results.json` SHA-256
- `validUntil`: evidence date + 30 days
- `threshold`: the frozen `act` for the rule that qualified
- `qualified`: true only when the held-out gate status is `qualified`
- `preservesExactState`: true for this benchmark's adapters, which reject rather than shorten input
- `mode`

An `unqualified`, `inconclusive` or `not-run` status exports nothing. That status is not a provisional or fallback record either.

## 5. Mode rules

- `hydraOracle`: select only an existing qualified saved pair and return it unchanged, or keep-current, or abstain.
- `experimentalOracle`: only with `experimental_opt_in`; the result is `experimental: true` and `ephemeral: true` and is never saved.
- `conclave`: the route is a proposal only. It may name a caller-supplied qualified seat binding. Security-sensitive and hard-risky classes need two checkers whose providers differ from each other and from the lead. The benchmark does not run the Conclave validator, read accounts, or change seats.

## 6. Known gaps

- The two class vocabularies overlap on only six labels: standard-feature, security-sensitive, bulk-mechanical, debug-mystery, long-context-analysis and research-synthesis. Other labels need a separately qualified mapping; there is no silent alias.
- The helper has no effort, security or ambiguity probability fields. They stay in benchmark provenance.
- No helper-compatible Conclave rules-contract export exists yet.
- Confidence is uncalibrated. Brier and ECE in the results are descriptive only.
