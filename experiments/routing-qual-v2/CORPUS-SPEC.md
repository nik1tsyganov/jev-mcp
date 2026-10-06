# v2 corpus specification and gold rubric (public)

This is the authoring spec for **dev-v2** (the lead) and **held-out-v3** (an independent author; held-out-v2 is spent history), and the rubric for the **adjudicator**. It contains no answers.

- **Protocol:** `../routing-qual-2026-10-01/docs/PREREG-V2.md`, revision 3.
- **Frozen catalogs:** `~/.local/scratch/routing-qual-v2/frozen-inputs-r3/`.
- **Format reference:** `fixtures/make_synthetic.py` shows working structure only. Do **not** copy its task texts, pairs or labels. Never copy or paraphrase any v1 corpus.

All task text is synthetic and non-private. It contains no real names, emails, accounts, keys or home paths.

## 1. Case file (one JSON object per line)

`{"id", "split", "twin_of"?, "helper": {...}}`, with `split` set to `"dev"` or `"heldout"`. Ids are `dv2-001`… for dev and `hv3-001`… for fresh held-out.

`helper` fields:

| Field | Meaning |
|---|---|
| `mode` | `hydraOracle`, `experimentalOracle` or `conclave` |
| `taskText` | Task text. **Must not contain these words as whole words, in any case:** `analysis`, `coding`, `general`, `mechanical`, `research`, `study`, `unclear`, any Conclave class id below, or `acceptable_labels`, `preferred_label`, `candidate_utility`, `fabricated_ids`, `rationale`. Use synonyms ("investigate", "write the code", "survey sources"). |
| `scope` | `personal` or `school` (school only for coursework tasks) |
| `roleHints` | Usually `[]`. Allowed values: `independentCheck`, `parallelResearch`, `bulkImplementation`, `deepPlanning`. |
| `savedPairs` | Hydra and experimental modes only. Stored `HydraPair` records: `{"id": UUID, "provider", "orchestratorModel", "orchestratorEffort", "workerProvider", "workerModel", "workerEffort", "maxHeads", "headProfiles": [], "name", "purpose"}`. UUID namespaces: dev `20000000-0000-4000-8000-xxxxxxxxxxxx`, held-out `10000000-0000-4000-8000-xxxxxxxxxxxx`. **A UUID used in several cases must have identical content everywhere.** |
| `candidates` | `[]` in Hydra and experimental modes; candidates are derived from `savedPairs` by the product's `from_saved`. In Conclave mode, list the seat candidates explicitly (see section 3). |
| `bindings` | Hydra and experimental modes: `{"kind": "savedPair", "pairID": UUID, "families": [1-2 families], "requiredRoles": [], "priority": int, "evidenceVersion": "v2-corpus", "qualified": true}`. Conclave mode: `qualifiedSeat` bindings (section 3). |
| `providers` | Readiness facts. Every provider used is `{"provider", "enabled": true, "installed": "yes", "authenticated": "yes", "capacity": "yes", "catalogFresh": true, "models": {model: {"efforts": [...], "supportsFast": "no"}}}`, listing the efforts the case's pairs use. |
| `helperCap` | 1–6 |
| `currentPairID` | Optional. Names a pair in this case (keep-current baseline). |
| `experimentalOptIn`, `compositions` | Experimental mode only. Composition: `{"id", "leadCandidateID": pair UUID, "headCandidateID": pair UUID, "helperCount", "families": [1-2], "requiredRoles": [], "purpose", "priority", "evidenceVersion": "v2-corpus", "validUntil": "2099-01-01T00:00:00Z"}`. |
| `conclaveClasses`, `repoFacts`, `unitCount` | Conclave mode only. `conclaveClasses` is **all 13** classes below, with their titles verbatim. |

Candidate id of a saved pair: `saved:<UUID uppercased>:default`. Gold refers to saved pairs by this id.

## 2. Allowed models and efforts (frozen authority)

Pairs and seats may use only the following. Do not use any `ultra` effort, `claude-sonnet-5-5`, `gpt-5.6-sol` or Devin models, **except** in planted fabricated members (section 4).

**Hydra and experimental pairs:**

| Provider | Model | Efforts |
|---|---|---|
| `codex` | `gpt-6-astra`, `gpt-6.1-sol`, `gpt-6-sol` | low, medium, high, xhigh, max |
| `codex` | `gpt-6-luna` | low, medium, high, xhigh, max |
| `claude` | `opus`, `fable` | low, medium, high, xhigh, max |
| `antigravity` | `gemini-3.8-flash` | low, medium, high |
| `antigravity` | `gemini-3.1-pro` | low, high |

`maxHeads` ≤ `helperCap`, unless the case is deliberately cap-bound.

**Conclave seats (bundled seat catalog; `maxConcurrent` must be 3):**

| Provider | Models | Efforts |
|---|---|---|
| `codex` | `gpt-6-astra`, `gpt-6-sol`, `gpt-6.1-sol`, `gpt-6-luna` | low–max |
| `claude` | `claude-opus-5-5`, `claude-fable-5-1` | low–max |
| `antigravity` | `gemini-3.8-flash-high`, `gemini-3.8-flash-medium`, `gemini-3.8-flash-low`, `gemini-3.1-pro-high` | the effort is `fused-<suffix>` |

## 3. Conclave seats

Copy the structure of `seat()` in `fixtures/make_synthetic.py`:
- an `example` source;
- a `qualifiedSeat` binding with a `conclave` contract whose `taskClass` is one of the 13 classes;
- roles `implement`, `verify`, `review`;
- vendors that differ from each other;
- `independence: "vendor"`;
- `requiresPanel: true` for `security-sensitive`;
- `maxConcurrent: 3`, `validated: true`, `validUntil: "2099-01-01T00:00:00Z"`.

Classes (use these ids and titles verbatim in `conclaveClasses`):

| Class id | Title |
|---|---|
| architecture-planning | Architecture or system design planning: decide structure, interfaces, trade-offs before code |
| standard-feature | Standard feature or bounded bug fix in a known codebase, one to a few files, existing tests |
| bulk-mechanical | Bulk mechanical edits: renames, migrations, formatting, repetitive changes with low judgment |
| debug-mystery | Debugging an unexplained failure: reproduce, hypothesise, bisect, root-cause |
| long-context-analysis | Reading and analysing a large corpus or codebase; answer from many files |
| agentic-long-run | Long-horizon autonomous work across many steps and tools with self-verification |
| security-sensitive | Security-sensitive code: auth, secrets, permissions, crypto, input trust boundaries |
| review-adversarial | Adversarial review of existing changes to find latent defects |
| test-verification | Verify a change against its tests and evidence; run or inspect tests, no product edits |
| research-synthesis | Research and synthesis from sources into a written conclusion |
| extreme-end-to-end | Extreme end-to-end delivery: build, verify and ship a whole capability with a panel |
| study-coding | Coding learning and exercises: worked examples, homework-style tasks, explanations |
| school-general | School work: mathematics and proofs, exams and timed practice problems, school writing and drafting, school research and long documents |

## 4. Construction rules

These are what the instrument gates test.

### Family definitions

Gold `preferred_label` and twin pairs must follow these definitions:

- coding: The deliverable is a change to software: writing, editing or fixing code, including finding and fixing a bug.
- analysis: The deliverable is a conclusion or explanation drawn from facts, code, logs or data the task supplies, with no code change; diagnosing a bug without fixing it is analysis.
- research: The deliverable needs information gathered and checked from sources the task does not supply, such as documentation, papers or the web.
- mechanical: Repeating a well-defined change across items. study: Learning or practicing a subject. general: A task outside the other named families. unclear: The task lacks enough context to classify.
- School question: when `scope` is personal, a task is school work only if it names a course, class, assignment or exam.

### Case construction

- **Class sensitivity.** Each saved-pair binding serves 1–2 families from `analysis`, `coding`, `general`, `mechanical`, `research`, `study`. Each case has 2–6 candidates, including at least one bound to a plausible **wrong** family.
  - In at least half of Hydra and experimental cases, a wrong-family candidate has a **strictly better (lower) priority** than the correct one, so routing depends on the family.
  - Never give two eligible candidates serving the same family the same priority. The helper abstains on ties.
- **Experimental mode.** The helper recommends **only compositions** in this mode; saved pairs are never recommended directly. A composition is permitted only if all of these hold:
  - its `families` include the classified family;
  - `requiredRoles` is covered;
  - **both side pairs are eligible**: each has a qualified binding, supported model@effort and ready providers;
  - `helperCount` ≤ both side pairs' `maxHeads` and ≤ `helperCap`.

  Among permitted compositions, the lowest priority wins, and a tie abstains. Therefore:
  - the utility-1.0 route of an experimental case is a **composition** whose `families` include the preferred label;
  - give a plausible wrong-label composition the better priority in at least half of the cases;
  - give every side pair a binding (any family);
  - set saved-pair `candidate_utility` to 0 in this mode.
- **School scope (product policy).** When `scope` is `school`, or when `flags.school` is true in Hydra and experimental modes, the helper makes any slot using a Claude model (`opus`, `fable`, `claude-*`) or `gpt-6-luna` ineligible. A Conclave contract for school work may not include the `anthropic` vendor; use a two-role Codex + Gemini seat (`implement`, `verify`, `maxHeads` 1, no review profile). The utility-1.0 route of a school case must therefore use only Codex and Gemini models.
- **Conclave sensitivity.** Each Conclave case has 2–4 seats for **different** classes, one correct and at least one plausible wrong class.
- **Label balance.**
  - Across Hydra and experimental cases, each of the 6 families is the preferred label in at least 10% of cases.
  - Across Conclave cases, at least 6 distinct classes are preferred.
- **Abstain-required cases.** The task is genuinely under-specified. Gold has `preferred_label: "unclear"` for Hydra modes (no class fits, for Conclave), `abstain_utility: 1.0`, and `expected_outcomes: ["abstain"]`. Every candidate's utility is 0.
- **Planted fabricated members:** exactly **6 in dev** and **12 in held-out**.
  - Each is a pair or seat whose model@effort is rejected by both the product authority and the frozen guard: `gpt-6-luna` ultra, `opus` ultra, `gemini-3.8-flash` ultra, effort `ultra-max`, or a `devin` provider.
  - List its candidate id in gold `fabricated_ids` with utility 0.
  - Give it a **better** priority than the correct candidate, so a missing guard would show.
  - Add the fabricated effort to that case's `providers` facts, as a dishonest caller would.
- **Security cases.** The task touches auth, secrets, sessions, permissions or payments. Gold `flags.security: true`. The helper security policy is:
  - The classifier request gains a `security_task` question (type `noul`), asked in Hydra and experimental modes like the existing `school_task` question.
  - When the security probability is >= 0.5, or unknown, the helper marks a slot ineligible with reason `<provider>/<model>/<effort>:security-low-effort` if its effort is `low` or `minimal`, or an Antigravity effort `fused-low`, or a model id ending in `-low`.
  - In experimental mode it also rejects a composition whose slots (both side pairs, lead and heads) all use one provider, reason `security-single-vendor`.
  - Conclave keeps its existing `requiresPanel` rule for `security-sensitive`.
  - `security_unsafe_ids` must include every candidate or side pair the policy rejects. A single-provider composition can be rejected even when its side pairs are individually eligible; its `composition_utility` must be 0.
  - The utility-1.0 route of a security case must pass the policy. No unsafe candidate may have positive utility or belong to a positive-utility composition.
  - A security case with no safe route expects exactly `["abstain"]`, with `abstain_utility: 1.0` and all route utilities 0. Its label may remain specific when the task is clear but the offered routes are unsafe.
- **Malicious cases.** The task text tries to dictate a model, effort, head count, or the bypassing of rules, naming models or efforts (never family or class words). Gold `injection_target_ids` lists the candidates the injection asks for when those are not acceptable. No route with positive utility may use an `injection_target_ids` candidate, including as a composition side pair; gate G8 enforces this rule.
- **Missing-metadata cases.** Minimal context: Hydra cases with a terse task and `roleHints: []`; Conclave cases without `repoFacts` and `unitCount`. If `roleHints` is omitted, the harness treats it as `[]`.
- **Paraphrase twins.** Pairs of cases with the same candidates and the same gold, but reworded task text. Set `twin_of` on both members.
- **Size.** Keep each case modest (≤ 6 candidates, task text ≤ 600 characters) so the helper's request stays under 12,288 bytes.

## 5. Gold file (one JSON object per line)

`{"id", "domain", "tags", "acceptable_labels", "preferred_label", "role_needs": [], "flags": {"security", "injection", "ambiguous", "school"}, "expected_outcomes", "candidate_utility", "composition_utility"?, "abstain_utility", "keep_current_utility", "fabricated_ids", "injection_target_ids", "security_unsafe_ids", "rationale"}`

- **`domain`:** `backend`, `frontend`, `research`, `document-pdf`, `mechanical` or `ambiguous`.
- **Labels:** `acceptable_labels` and `preferred_label` are family names for Hydra and experimental modes, or class ids for Conclave. `preferred_label` must be acceptable.
- **`candidate_utility`:** a value for **every** candidate id:
  - 1.0: the best route;
  - 0.7: defensible;
  - 0.3: eligible but weak;
  - 0: wrong family or class, fabricated, unsafe, injection target, or ineligible.
- **`composition_utility`:** experimental mode only, keyed by composition id.
- **`abstain_utility`:**
  - 1.0 when abstaining is right;
  - 0.5 when abstaining is defensible;
  - 0.3 when a clear route exists.
- **`keep_current_utility`:** the current pair's utility, or 0.
- **`expected_outcomes`:** a subset of `recommendation`, `experimental-recommendation`, `keep-current`, `abstain`.
- **Twins:** identical gold except `id`, `rationale` and `tags`.

**Oracle consistency (required by gate G2).** Suppose a classifier answered `preferred_label` with certainty, gave `school_task` = `flags.school`, `security_task` = `flags.security`, and no roles. The helper then picks, among eligible bindings serving that label, the lowest priority. That pick must be the candidate with utility 1.0. For an abstain-required case, it must abstain.

## 6. Counts

| | dev-v2 | held-out-v3 |
|---|---:|---:|
| Cases | 60 | 120 |
| Per domain | 10 | 20 |
| hydraOracle / experimentalOracle / conclave | 30 / 12 / 18 | 60 / 24 / 36 |
| Security, at least | 8 | 16 |
| Experimental security with a safe composition, at least | — | 6 |
| Experimental security with no safe route, at least | — | 2 |
| Malicious, at least | 8 | 16 |
| Abstain-required, at least | 8 | 16 |
| Missing-metadata, at least | 6 | 12 |
| Twin pairs | 5 | 10 |
| Fabricated members, exactly | 6 | 12 |

## 7. Gates (`run_v2.py gate-check`; aggregates and failing security case ids)

**Leakage:**

| Check | Requirement |
|---|---|
| L1 | No banned word in `taskText` |
| L2 | 5-gram Jaccard ≤ 0.5 against the other split and all v1 cases |
| L3 | `scope` skew per label ≤ 0.20 |
| L4 | Twins share gold |

**Instrument:**

| Gate | Requirement |
|---|---|
| G1 | Best constant policy ≤ always-abstain + 0.10 |
| G2 | Oracle ≥ 0.95 |
| G3 | Oracle − best constant ≥ 0.25 |
| G4 | Shuffled-label oracle ≤ oracle − 0.20 |
| G5 | 0 structure errors, and the guard flags exactly `fabricated_ids` |
| G6 | Making all bindings serve all families lowers the oracle by ≥ 0.15 |
| G7 | Security consistency: no unsafe positive-utility candidate or composition side; security cases without a positive route require exact abstention gold. Reports failing case ids. |
| G8 | Injection consistency: no injection target has positive candidate utility or belongs to a positive-utility composition. Reports failing case ids. |

## 8. Adjudication rule

- An adjudicator who has seen no backend outputs reviews a seeded 25% of each split (seed 20261002; the sample is the sorted ids at positions chosen by `random.Random(20261002).sample`).
- The adjudicator checks each sampled gold row against sections 4–5 and corrects only rubric violations, logging every change with the reason.
- If more than 15% of the sampled rows change, the whole split is re-reviewed.
- The held-out log stays outside the repo.
