# Oracle helper and Conclave schema map

Source inspection, 2026-10-01. No helper, classifier, API, validator, or provider was run. This document records interfaces and mapping gaps; it grants no dispatch authority.

`OW` means `~/.local/scratch/droppy-code-oracle-wt`. `C` means `~/src/conclave`. `H` means `OW/DroppyCode/Core/Models/OracleRoutingHelper.swift`; `M` means `OW/DroppyCode/Core/Models/OracleRoutingModes.swift`; `O` means `OW/DroppyCode/Core/Models/HydraOracle.swift`. These prefixes expand every file:line citation below.

## Input snapshot

`OracleRoutingInput: Codable, Sendable` has these exact Swift fields. A `?` denotes optional. Sets encode as arrays. Helper JSON dates use ISO 8601 UTC. [H:45-67; OW/docs/hydra-oracle/ROUTING-HELPER.md:53-71]

| Field | Type |
| --- | --- |
| mode | OracleRoutingMode |
| requestID | String |
| caller | String |
| backend | OracleRoutingBackend |
| taskText | String |
| scope | OracleScope |
| roleHints | Set<OracleRoleNeed> |
| currentCandidateID | String? |
| candidates | [OracleCandidate] |
| bindings | [OracleRoutingBinding] |
| matrixVersion | String |
| providers | [OracleProviderFacts] |
| readinessVersion | String |
| readinessValidUntil | Date |
| qualification | OracleRoutingQualification? |
| helperCap | Int |
| experimentalOptIn | Bool? |
| compositions | [OracleRoutingComposition]? |
| conclaveClasses | [String: String]? |
| repoFacts | String? |
| unitCount | Int? |

Enums are `OracleRoutingBackend { jev, laya }`, `OracleRoutingMode { hydraOracle, experimentalOracle, conclave }`, and `OracleScope { personal, school }`. `OracleRoleNeed` values are `independentCheck`, `parallelResearch`, `bulkImplementation`, `deepPlanning`. [H:5-14; O:5-9]

The GUI's separate `OracleSnapshot: Hashable, Sendable` carries:

```swift
generation: UUID
threadID: UUID
threadRevision: Int
draftDigest: String
attachmentDigest: String
mode: OracleMode // manual | auto
scope: OracleScope
pinnedPairID: UUID?
leadEffort: String?
fastMode: Bool
candidateIDs: [String]
candidatesDigest: String
catalogVersion: Int
connectionVersion: Int
sessionIdentity: String?
capturedAt: Date
dependencyKey: String // computed
```

`dependencyKey` joins snapshot dependencies, excluding generation and capturedAt. The app builds candidate digest from ordered ID/revision pairs. This GUI snapshot is not the Codable helper input. [O:278-299; OW/DroppyCode/App/AppModel+HydraRouter.swift:186-198]

## Candidate, configuration, readiness, and permission records

| Record | Exact fields and types | Source |
| --- | --- | --- |
| OracleCandidate | `id: String`, `source: OracleCandidateSource`, `displayName: String`, `variant: OracleVariant`, `evidenceDate: String?`, `revision: String` | O:101-107 |
| OracleCandidateSource | `saved(pairID: UUID)` or `example(recipeID: String, evidenceVersion: String)` | O:96-99 |
| OracleVariant | `variantID: String`, `leadProvider: ProviderKind`, `leadModel: String?`, `leadEffort: String?`, `defaultHead: OracleHeadSlot`, `profiles: [OracleHeadSlot]`, `maxHeads: Int?`, `families: Set<OracleTaskLabel>`, `roles: Set<OracleRoleNeed>`, `purpose: String` | O:33-43 |
| OracleHeadSlot | `profileName: String?`, `provider: ProviderKind`, `model: String?`, `effort: String?`, `required: Bool` | O:25-30 |
| OracleProviderFacts | `provider: ProviderKind`, `enabled: Bool`, `installed: OracleFact`, `authenticated: OracleFact`, `capacity: OracleFact`, `catalogFresh: Bool`, `models: [String: OracleModelFacts]` | O:139-148 |
| OracleModelFacts | `efforts: [String]`, `supportsFast: OracleFact` | O:139 |
| OracleFact | `yes`, `no`, `unknown` | O:9 |
| OracleRoutingBinding | `kind: Kind`, `candidateID: String`, `revision: String`, `configuration: OracleVariant`, `families: Set<OracleTaskLabel>`, `requiredRoles: Set<OracleRoleNeed>`, `priority: Int`, `evidenceVersion: String`, `validUntil: Date`, `qualified: Bool`, `conclave: OracleRoutingConclaveContract?` | H:17-30 |
| Binding.Kind | `savedPair`, `qualifiedSeat` | H:18 |

Saved IDs use `saved:UUID:variantID`. A saved source's JSON is `{"saved":{"pairID":"UUID"}}`. Qualified seats use the existing `example` shape plus a qualifiedSeat binding. No named profile automatically becomes a checking role. [O:109-110; OW/docs/hydra-oracle/ROUTING-HELPER.md:73-79]

The helper rejects unknown readiness, missing models/caps, unsupported efforts, expired evidence, changed configurations, and duplicate bindings. Lower integer priority wins; tied best rows abstain. `maxHeads` is a cap for saved configurations, not observed helper execution. [H:108-126,228-269,293-308]

## Qualification and returned classification

`OracleRoutingQualification: Codable, Sendable` contains exactly:

```swift
caller: String
backend: OracleRoutingBackend
model: String
capability: String
evidenceVersion: String
validUntil: Date
threshold: Double
qualified: Bool
preservesExactState: Bool
mode: OracleRoutingMode
```

There is **no `classifierModel`, `historicalThreshold`, or `appliedThreshold` field inside qualification**. Those are result fields. Capability must equal `oracle-classification-policy-v1`. Caller, backend, model, and mode must match. The helper requires fresh evidence, exact-state preservation, and a finite threshold in [0,1]. [H:32-43,106,275-285]

`OracleRoutingClassification: Codable, Sendable, Equatable` has `taskClass: String?`, `family: OracleTaskLabel?`, `familyProbability: Double?`, `roleProbabilities: [String: Double]`, `schoolProbability: Double?`, `errors: [String]`. In Conclave mode, the selected task-class probability is stored in `familyProbability`; its name does not mean a family was returned. [H:69-76; M:59-82]

`OracleRoutingResult: Codable, Sendable` contains:

```swift
mode: OracleRoutingMode
requestID: String
caller: String
backend: OracleRoutingBackend
classifierModel: String
outcome: String
currentCandidateID: String?
recommendation: OracleCandidate?
binding: OracleRoutingBinding?
classification: OracleRoutingClassification?
confidence: Double?
confidenceProvenance: String
historicalThreshold: Double
appliedThreshold: Double?
qualificationEvidence: String?
matrixVersion: String
readinessVersion: String
eligibility: [String: [String]]
reasons: [String]
resolvedConfiguration: OracleVariant?
composition: OracleRoutingComposition?
experimental: Bool // default false
ephemeral: Bool // default false
dispatchAuthorized: Bool // private(set), default false
```

Historical pair thresholds are Jev=.55 and Laya=.50. `appliedThreshold` comes only from the matching qualification record. `confidence` is response-reported probability, not measured routing accuracy. No explicit model-revision, question-set-version, policy-version, or calibration field exists in this result. `matrixVersion`, `readinessVersion`, `qualificationEvidence`, and binding/composition evidence versions have distinct meanings. [H:8-9,78-103,209-218,275-285]

The GUI chooses its threshold from `OracleQualification.record(for: source).threshold`, with provisional fallback. That GUI record is separate from `OracleRoutingQualification`. Do not transfer a GUI permission bit into helper qualification. [OW/DroppyCode/App/AppModel+HydraRouter.swift:116-145; OW/docs/hydra-oracle/VALIDATION.md:285-290]

## Outcomes and source adapter

The helper's result `outcome` is a **String**, not a Swift enum. Its documented vocabulary is `recommendation`, `experimental-recommendation`, `keep-current`, `abstain`, `backend-unavailable`. Other failures go into `reasons`, retaining keep-current/abstain. [H:84,209-223,304; M:129,175; OW/docs/hydra-oracle/ROUTING-HELPER.md:102-104]

The older decoder has an enum:

```swift
enum OracleOutcome: Hashable, Sendable {
    case commit(OracleChoice), hold(OracleHoldReason)
}
```

`OracleHoldReason` contains `noCandidates`, `disconnected`, `abstained`, `lowScore`, `invalidReply`, `timeout`, `unauthorized`, `rateLimited`, `serverError`, `offline`, `stale`, `cancelled`, `boundExceeded`, `versionChanged`, `schoolRestricted`, `schoolCheck`. [O:387-397]

The transport signatures are exact:

```swift
protocol OracleClassifying: Sendable {
    func classify(body: Data) async throws -> Data
}
struct OracleRoutingSourceAdapter: Sendable {
    var backend: OracleRoutingBackend
    var preservesExactState: Bool
    var classifier: (any OracleClassifying)?
}
static func route(_ input: OracleRoutingInput,
                  source: OracleRoutingSourceAdapter,
                  requestBudget: Int) async -> OracleRoutingResult
```

[O:596; OW/DroppyCode/Services/Oracle/OracleRoutingService.swift:3-12]

The service permits at most one injected classifier call, with cancellation and a ten-second deadline. It never falls back to another backend. Existing Laya shortening paths cannot assert exact-state preservation without separate qualification. [OW/DroppyCode/Services/Oracle/OracleRoutingService.swift:13-40; OW/docs/hydra-oracle/ROUTING-HELPER.md:26-28]

## Exact classifier requests

### Hydra and experimental modes

State fields are `task: String`, `scope: String`, `role_hints: [String]`, and `candidates: [[String: Any]]`. Candidate state fields are `label`, `name`, `lead`, `heads`, `profiles`, `families`, `roles`, `purpose`. The helper removes the older `pair` question. Code, rather than the classifier, selects the permitted binding. [O:329-340; H:129-139]

`family` is Choice with instructions: `Classify state.task using state.scope and state.role_hints.` Exact criteria:

| Label | Wording |
| --- | --- |
| coding | Writing, changing, or debugging software. |
| analysis | Examining facts or code to reach a conclusion. |
| research | Finding and checking information from sources. |
| mechanical | Repeating a well-defined change across items. |
| study | Learning or practicing a subject. |
| general | A task outside the other named families. |
| unclear | The task lacks enough context to classify. |

[O:343-355]

Other question IDs are `school_task`, `role_independentCheck`, `role_parallelResearch`, `role_bulkImplementation`, and `role_deepPlanning`, all Noul. Their instructions are respectively:

- `Is state.task school or coursework: an assignment, exam practice, a class project or studying?`
- `Does state.task require a separate check of completed work? Use state.role_hints and state.candidates roles.`
- `Does state.task require independent research in parallel? Use state.role_hints and state.candidates roles.`
- `Does state.task require repeated implementation across many items? Use state.role_hints and state.candidates roles.`
- `Does state.task require detailed planning before execution? Use state.role_hints and state.candidates roles.`

[O:355-364]

### Conclave classifyTask

JavaScript signature:

```javascript
async function classifyTask({ briefText, repoFacts = '', unitCount = null }, routing, opts = {})
```

State is exactly `{ brief: briefText, repoFacts, unitCount }`. Question ID is `taskClass`; type is `choice`. Instructions are exactly:

> Which routing class best describes the task in `brief`, given `repoFacts` and the number of independent work units in `unitCount`? Judge the work the brief asks for, not vocabulary it happens to use.

Criteria are `Object.fromEntries(Object.entries(routing.classes).map(([id, c]) => [id, c.title]))`. The helper receives that dictionary through `conclaveClasses`; it does not hardcode 14 labels. It uses `taskText` as `brief`, absent repoFacts as `""`, and absent unitCount as JSON null. [C/tools/jev-arbiter.js:90-99; M:44-56]

Conclave returns `ok`, `classId`, `p`, `confidence`, `distribution`, `gate`, `usage`. Failure returns `ok: false`, `notRun`, `classId: null`, `gate: 'owner'`. The Swift decoder discards the full distribution after validation; only the selected probability survives. [C/tools/jev-arbiter.js:100-112; M:59-82]

The current Conclave matrix supplies these exact IDs and titles:

| Label | Exact title | Source |
| --- | --- | --- |
| architecture-planning | Architecture or system design planning: decide structure, interfaces, trade-offs before code | C/contracts/dispatch-matrix.json:208 |
| standard-feature | Standard feature or bounded bug fix in a known codebase, one to a few files, existing tests | C/contracts/dispatch-matrix.json:240 |
| bulk-mechanical | Bulk mechanical edits: renames, migrations, formatting, repetitive changes with low judgment | C/contracts/dispatch-matrix.json:328 |
| debug-mystery | Debugging an unexplained failure: reproduce, hypothesise, bisect, root-cause | C/contracts/dispatch-matrix.json:416 |
| long-context-analysis | Reading and analysing a large corpus or codebase; answer from many files | C/contracts/dispatch-matrix.json:503 |
| agentic-long-run | Long-horizon autonomous work across many steps and tools with self-verification | C/contracts/dispatch-matrix.json:534 |
| security-sensitive | Security-sensitive code: auth, secrets, permissions, crypto, input trust boundaries | C/contracts/dispatch-matrix.json:622 |
| review-adversarial | Adversarial review of existing changes to find latent defects | C/contracts/dispatch-matrix.json:718 |
| test-verification | Verify a change against its tests and evidence; run or inspect tests, no product edits | C/contracts/dispatch-matrix.json:749 |
| research-synthesis | Research and synthesis from sources into a written conclusion | C/contracts/dispatch-matrix.json:781 |
| extreme-end-to-end | Extreme end-to-end delivery: build, verify and ship a whole capability with a panel | C/contracts/dispatch-matrix.json:812 |
| study-coding | Coding learning and exercises: worked examples, homework-style tasks, explanations | C/contracts/dispatch-matrix.json:900 |
| school-general | School work: mathematics and proofs, exams and timed practice problems, school writing and drafting, school research and long documents | C/contracts/dispatch-matrix.json:994 |

## Experimental composition and Conclave binding

`OracleRoutingComposition: Codable, Sendable` fields are `id: String`, `leadCandidateID: String`, `headCandidateID: String`, `helperCount: Int`, `families: Set<OracleTaskLabel>`, `requiredRoles: Set<OracleRoleNeed>`, `purpose: String`, `priority: Int`, `evidenceVersion: String`, `validUntil: Date`. [M:4-15]

Composition takes the lead candidate's lead fields and the head candidate's `defaultHead` and `profiles`. It sets `maxHeads` to `helperCount`. The count must fit the caller and both candidate caps. Exact saved reuse compares every variant field except `variantID`. A composed result can have no `recommendation` candidate and still have `resolvedConfiguration`. `ephemeral` remains true. [M:85-130]

`OracleRoutingConclaveContract: Codable, Sendable` fields are:

| Field | Type |
| --- | --- |
| taskClass | String |
| configuration | OracleVariant |
| roles | [String] |
| canonicalModels | [String] |
| vendors | [String] |
| authorModel | String |
| authorVendor | String |
| independence | String |
| requiresPanel | Bool |
| maxConcurrent | Int |
| contractVersion | String |
| nativeEvidenceVersion | String |
| validUntil | Date |
| validated | Bool |

[M:18-33]

Array order is lead, default helper, then named profiles. Each length equals helper count plus one. Accepted roles are `implement`, `plan`, `research`, `review`, `verify`. `independence` accepts `vendor` or `model`. Review/verify identities must differ from author, lead, and each other. Required panels need at least two checkers. This is a proposal check against caller assertions, not native evidence validation. [M:134-176; OW/docs/hydra-oracle/ROUTING-HELPER.md:91-98]

### Conclave export and native seat formats

**Exact helper-compatible export: NOT FOUND in the inspected Conclave checkout.** Searches for `contractVersion`, `nativeEvidenceVersion`, `nativeEvidence`, rules-contract, seat-binding, and binding found no constructor exporting the helper object above. The helper documentation requires a caller-supplied export, but does not identify a producing API. Do not invent one or mark a synthetic fixture validated. The existing formats below are related inputs, not an interchangeable export.

| Existing surface | Fields / contract | Source |
| --- | --- | --- |
| Rules-only tools | `conclave_hosts`, `conclave_validate_row`, `conclave_tally`, `conclave_route`, `conclave_read_block`, `conclave_read_reply` | C/mcp/server.js:53-58 |
| conclave_route input | `units: object[]` with `id`, `brief`, optional `files`, `class`; `seats: object[]` with `slot`, `vendor`, `name`; `readyVendors: string[]`; optional `criticalTwoReviews: boolean` | C/mcp/server.js:205-221 |
| Seat profile validation result | `ok: boolean`, `vendor: string`, `role: string`, `class: string`, `skills: string[]`, `permissionProfile: string`, `proofFields: string[]` | C/tools/seat-policy.js:30-58 |
| Sealed plan binding | `{ planId, planHash, entry }`; entry is the exact dispatch row | C/tools/dispatch-run.js:488; C/tools/run-finalize.js:189 |
| Dispatch identity equality | `dispatchId`, `unitId`, `class`, `role`, `vendor`, `model`, `effort`, `authorVendor`, `authorModel`; plus supplied `escalation`, `escalationReason`; resolved `cwd`, `brief`, and `briefSha256` must match | C/tools/dispatch-matrix.js:273-287 |
| Dispatch row requirements | Strings `dispatchId`, `unitId`, `cwd`, `briefSha256`; `writeScope: string[]`; optional `dependsOn: string[]`, `evidenceReadDirs`, `checkerProof`, `escalation: boolean`, `escalationReason: string`; checking rows require `authorVendor` | C/tools/dispatch-matrix.js:143-175 |
| Plan context | `hostMode`, `seatPolicy`, `arbiter`, `dispatches`; `arbiter.host` optional slug | C/tools/dispatch-matrix.js:104-131 |
| Generated SEAT-CONTRACT.md | Dispatch, Unit, Vendor, Role, Class, Model, Effort, Plan ID/hash, optional model-independent seating policy, Escalation/reason, Permission profile, write scope and leaf-seat rules | C/tools/dispatch-run.js:80-113 |
| Counted receipt | `slot`, `vendor`, `role`, `position`, `evidence`, `status`, `sessionId`, `tokens`, `modelObserved`, `treeBefore`, `treeAfter`; nonempty `voidReason` disqualifies | C/mcp/server.js:193-200; C/tools/panel-rules.js:148-159 |
| Instruction transcript binding | `protocol`, `vendor`, `sessionId`, `sourcePath`, `sha256` | C/tools/dispatch-run.js:555-561; C/tools/run-finalize.js:219-229 |

Conclave's `seatPolicy` uses absent/null for vendor separation or `model-independent` for canonical vendor/model separation. The helper instead uses `independence: "vendor" | "model"`. Provider names also differ: Droppy uses `codex`, `claude`, `antigravity`; Conclave uses `openai`, `anthropic`, `google`. Effort changes do not create independent identities. Conclave resolves canonical aliases through its model catalog; the helper expects them already resolved. [C/tools/seat-policy.js:70-110; M:155-163; OW/docs/hydra-pairs-2026-09-29.json:21-39]

The older panel routing API accepts nine routable classes and explicitly rejects four matrix classes without implementation/verification lanes. Thus valid classification labels need not be seatable through `conclave_route`. [C/tools/panel-routing.js:25-48,103-115]

## Persisted results and historical catalog

`OracleRoutingRunStore.Record` has `schemaVersion: Int = 1`, `runID: UUID`, `requestFingerprint: String`, `selectionFingerprint: String`, `selection: OracleRoutingResult`, `createdAt: Date`. `State` has `record: Record`, `status: String`, `observations: [Observation]`, and computed `outcome: Observation.Outcome`. [OW/DroppyCode/Services/Oracle/OracleRoutingRunStore.swift:8-43]

Observation outcome is another enum: `unknown`, `succeeded`, `failed`, `cancelled`. Tests use `unknown`, `passed`, `failed`, `notRun`. Provenance uses `unknown`, `parentReported`, `providerObserved`, `testRunner`. Observation fields are `eventID: UUID`, `observedAt: Date?`, `provenance: Provenance`, `executed: Execution?`, `outcome: Outcome`, `tests: Tests`, `correctionOf: UUID?`, `usage: [TokenSpend]?`, `elapsedMilliseconds: Int?`. Execution has `lead: OracleHeadSlot?`, `helpers: [OracleHeadSlot]?`, `helperCount: Int?`. Recommended configuration is not evidence of actual execution. [OW/DroppyCode/Services/Oracle/OracleRoutingRunStore.swift:47-66; OW/docs/hydra-oracle/ROUTING-HELPER.md:128-136]

`requalify-v1.json` contains `version`, `catalogs`, `rows`, and `rules`. Rules contain `lossTable`, `noiseFloor`, `referenceRegret`, `sourceSha256s`, `targets`, and `threshold`. Threshold=.55, referenceRegret=.1812, noiseFloor=.075; this is the older 80-row pair recheck artifact. Rows carry `acceptable`, `catalog`, `committedSession`, `fastMode`, `id`, `leadEffort`, `scope`, `task`. [OW/DroppyCode/Resources/Oracle/requalify-v1.json:1539-1555,2597-2615]

The newer pair document has `artifact`, `created`, `status`, `supersedes`, `changes_from_2026_09_22`, `limits`, `proposed_pairs`. Each proposed pair has `name`, `provider`, `orchestratorModel`, `orchestratorEffort`, `workerProvider`, `workerModel`, `workerEffort`, `maxHeads`, `headProfiles`, `rationale`, `evidence`. Profiles use `name`, `provider`, `model`, `effort`. This document has no candidate IDs, revision-bound permissions, class qualification, or native execution receipts. Its limits explicitly disclaim full-pair comparative benchmarks. [OW/docs/hydra-pairs-2026-09-29.json:1-67]

## All task-label mismatches

The benchmark's requested 14 classes are the comparison authority here. The helper does not ship its own fixed `taskClass` criteria: callers supply `conclaveClasses`. Using the current Conclave matrix produces 13 labels, with six exact matches.

| Benchmark class | Current Conclave matrix | Hydra/experimental family interface |
| --- | --- | --- |
| planning | Missing; `architecture-planning` differs in name and scope | No exact label; `analysis`/`general` and deepPlanning role are coarser |
| standard-feature | Exact ID present | No exact label; coding is coarser |
| hard-risky | Missing; agentic-long-run/extreme-end-to-end are not equivalent | No exact label |
| security-sensitive | Exact ID present | No exact label; no security Noul |
| bulk-mechanical | Exact ID present | No exact label; mechanical is coarser |
| parallel-slices | Missing | No exact label; bulkImplementation role is not a class |
| debug-mystery | Exact ID present | No exact label; coding/analysis are coarser |
| tie-break | Missing; review-adversarial is not equivalent | No exact label; independentCheck is not a class |
| long-context-analysis | Exact ID present; older panel API rejects it | No exact label; analysis is coarser |
| research-synthesis | Exact ID present; older panel API rejects it | No exact label; research/analysis are coarser |
| prose-writing | Missing | No exact label; general is coarser |
| ui-design | Missing | No exact label; coding/general are coarser |
| tutoring-dispatch | Missing; study-coding/school-general differ in scope | No exact label; study is coarser |
| research-swarm | Missing | No exact label; parallelResearch is not a class |

Conclave-only labels are **architecture-planning, agentic-long-run, review-adversarial, test-verification, extreme-end-to-end, study-coding, school-general**. Benchmark-only labels are **planning, hard-risky, parallel-slices, tie-break, prose-writing, ui-design, tutoring-dispatch, research-swarm**. No silent alias mapping is justified. Hydra-family labels **coding, analysis, research, mechanical, study, general, unclear** all differ from the benchmark class IDs. `unclear` is a family fallback, not an `ambiguous_p` probability. [O:7,343-346; current matrix criteria table above; C/tools/panel-routing.js:25-48]

Other field mismatches: backend enum lacks Qwen and Decider; full class distributions are discarded by Swift; no effort question exists; no security or ambiguity probability exists; qualification does not carry calibrated probability evidence; profile names and role-needs are not seat roles; caps are not executed counts; native contract export is absent. These need explicit benchmark adapters and evidence, not renamed fields alone.

Document validation: NOT RUN; assigned to the lead.

## Mapping to the benchmark route object

| Benchmark field | Source field / mapping | Gap or constraint |
| --- | --- | --- |
| outcome | OracleRoutingResult.outcome | String vocabulary above; do not map observed run success or legacy commit directly |
| candidate_id | recommendation.id / binding.candidateID | Optional for ephemeral compositions; currentCandidateID is retained state, not a fresh recommendation |
| lead.model | resolvedConfiguration.leadModel | Optional in source; eligibility requires resolution |
| lead.provider | resolvedConfiguration.leadProvider | Explicit codex→openai, claude→anthropic, antigravity→google mapping if benchmark uses vendor names |
| lead.effort | resolvedConfiguration.leadEffort | Catalog-supported string; preserve missing values |
| lead.role | binding.conclave.roles[0] | Absent for ordinary Hydra; derive only from explicit benchmark policy |
| heads[].model | defaultHead.model then profiles[].model | Profiles are available configurations, not necessarily all dispatched helpers |
| heads[].provider | defaultHead.provider / profiles[].provider | Same provider normalization requirement |
| heads[].effort | defaultHead.effort / profiles[].effort | No predicted effort field; these are fixed configuration values |
| heads[].profile | OracleHeadSlot.profileName | Default head can have null profile; pair JSON uses headProfiles[].name |
| heads[].role | aligned binding.conclave.roles[1...] | Hydra OracleRoleNeed values are aggregate needs, not per-head roles |
| checkers | aligned Conclave roles review/verify plus corresponding slots | No standalone checker list; a profile named crosscheck is insufficient |
| helper_count | composition.helperCount; exact Conclave configuration.maxHeads | Saved Hydra maxHeads is a cap. Observed executed.helperCount is separate evidence |
| mode | OracleRoutingMode | Exact values hydraOracle, experimentalOracle, conclave |
| routed_task_class | classification.taskClass | Only Conclave mode; family requires a separately qualified 7→14-class policy, not an alias |
| routed_effort | No direct field | lead/head efforts are configuration fields; no route-level effort classifier |
| reasons | result.reasons; retain eligibility separately | Flattening candidate eligibility would lose which candidate each reason concerns |
| uncertainty.class_top_p | classification.familyProbability / result.confidence | Conclave stores class p here; ordinary Hydra stores family p |
| uncertainty.class_margin | Conclave JS distribution top minus second | Swift result loses distribution; cannot reconstruct from selected p |
| uncertainty.effort_quantile_p | None | Requires a new benchmark question and calibration |
| uncertainty.security_p | None | No security probability; selected security-sensitive class p is not a general security Noul |
| uncertainty.ambiguous_p | None | No ambiguity Noul; unclear family and reasons are not interchangeable |
| uncertainty.calibrated | None | qualified and confidenceProvenance do not prove calibration; preserve unknown/false according to benchmark schema |
| provenance.backend | result.backend | Existing enum permits only jev/laya; extend benchmark adapter for Qwen/Decider |
| provenance.classifier_model | result.classifierModel / qualification.model | Model tag differs from selected lead/head model; Oracle Laya pin differs from Jev-MCP typed pin |
| provenance.revision | Classifier artifact manifest; not candidate.revision | candidate/binding revision identifies configuration; requires separate classifier revision provenance |
| provenance.question_set_version | None explicit; capability is oracle-classification-policy-v1 | Capability is not a question-set hash/version; record exact exported questions separately |
| provenance.policy_version | None explicit; matrixVersion and contractVersion identify different inputs | Freeze the actual benchmark policy version; do not substitute readiness version |
| provenance.catalog_version | input.matrixVersion; GUI snapshot.catalogVersion is Int | Permission matrix version and provider catalog version differ; carry explicit catalog snapshot identity |
| provenance.rule_name | composition.id, or explicit selected binding/policy identity | Binding has no rule-name field; reasons are not stable rule IDs |
| provenance.thresholds | historicalThreshold, appliedThreshold, qualification.threshold; role gate .5 | Preserve historical vs applied distinction; no class-margin or effort threshold fields currently exist |
| dispatch_authorized | result.dispatchAuthorized | Always false; qualification, persistence, and a recommendation never grant dispatch permission |
