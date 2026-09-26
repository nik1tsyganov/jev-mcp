# Question Wording Audit: Testing the Jaggedness Hypothesis Across Eight Packs

**Date:** 2026-09-19  
**Auditor:** Zola 2 (Droppy Code Hydra Head)  
**Target:** Question wording across all eight packs in `~/src/jev-mcp/packs/` evaluated against the Jev 1.13 static linter (`jevcal.lint`).

---

## Verdict

The hypothesis that question wording flaws caused the measured calibration failures in `code-review-triage` and `head-brief-quality` is **DISCONFIRMED**. The two failing packs trigger fewer severe rule violations than the working packs (0 errors vs 2 errors; 0.82 violations/question in failing packs vs 0.88 in working packs), while the failing question `head-brief-quality:self_contained` has zero linter violations and `code-review-triage:is_real` triggers only a single criterion negation warning present across working packs as well.

---

## Extracted Linter Rules (`jevcal.lint`)

The static linter in `~/.local/scratch/jev-calibration/jevcal/src/jevcal/lint.py` defines 14 question-level rules (across three severities: `error`, `warn`, `info`) and 3 dataset-level rules based on TypeSafe's published Jev 1.13 jaggedness characteristics:

### Trigger Patterns
```python
NEGATION = re.compile(r"\b(not|never|no longer|isn't|aren't|doesn't|don't|didn't|won't|cannot|can't|without|except|unless|neither|nor)\b", re.I)
ARITHMETIC = re.compile(r"\b(how many|count of|number of|at least \d+|at most \d+|more than \d+|fewer than \d+|less than \d+|sum of|total of|average|percent(age)?)\b", re.I)
DATETIME = re.compile(r"\b(within the (last|past|next)|older than|newer than|earlier than|later than|expired?|overdue|past due|(before|after|since|until) \d|\d+\s*(minutes?|hours?|days?|weeks?|months?|years?))\b", re.I)
NUMERIC = re.compile(r"(\b(greater than|less than|exceeds?|at least|at most|above|below|over|under)\s+[$€£]?\d|[<>]=?\s*[$€£]?\d)", re.I)
MULTI_HOP = re.compile(r"\b(whose|of the \w+ of|which of .+ that|if .+ then .+ otherwise)\b", re.I)
COMPOUND = re.compile(r"\b(and|or|as well as)\b", re.I)
VAGUE = re.compile(r"\b(good|bad|appropriate|relevant|quality|suitable|acceptable|reasonable|important|interesting)\b", re.I)
```

### Rule Catalog
1. **`J001` (warn):** Triggered when exactly one negation token is found in the question text or criteria.  
   - *Message:* `negation ('<token>')`  
   - *Rationale:* *"P(noul) and 1 - P(negated noul) are not interchangeable on Jev. Prefer the positive phrasing."*
2. **`J002` (error):** Triggered when two or more negation tokens are found in the question text or criteria.  
   - *Message:* `multiple negations (<tokens>)`  
   - *Rationale:* *"Jev reads negations literally and double negatives cut accuracy. Ask the positive version and flip the answer in code."*
3. **`J003` (warn):** Triggered by `ARITHMETIC.search(text)`.  
   - *Message:* `asks the model to count or do arithmetic`  
   - *Rationale:* *"Jev is not a calculator. Compute the number in code and put the result in the state."*
4. **`J004` (warn):** Triggered by `DATETIME.search(text)`.  
   - *Message:* `depends on a date or duration comparison`  
   - *Rationale:* *"Dates are read as text. Precompute the comparison (e.g. days_overdue: 12) and ask about that field."*
5. **`J005` (warn):** Triggered by `NUMERIC.search(text)`.  
   - *Message:* `depends on a numeric comparison`  
   - *Rationale:* *"Do the comparison in code, or describe the bands in words inside the criteria."*
6. **`J006` (info):** Triggered by `MULTI_HOP.search(text)`.  
   - *Message:* `looks like a multi-hop question`  
   - *Rationale:* *"Indirection lowers accuracy. Split into atomic questions and combine the answers in code; extra questions are nearly free."*
7. **`J007` (warn):** Triggered when `len(instructions.split()) < 4`.  
   - *Message:* `instructions are very short`  
   - *Rationale:* *"Jev answers the question as written and will not infer intent. Say exactly what should count."*
8. **`J008` (info):** Triggered by `VAGUE.search(instructions)` when criteria is absent.  
   - *Message:* `subjective wording with no criteria`  
   - *Rationale:* *"Define what the subjective word means in `criteria`, including the boundary cases."*
9. **`J009` (info):** Triggered when a `noul` has no criteria, or when >50% of options in a `choice` have no description.  
   - *Message:* `noul has no criteria` or `<n> of <m> options have no description`  
   - *Rationale:* *"Describe what a yes and a no mean, especially near the boundary."* / *"Option descriptions are where domain rules live. Describe each option."*
10. **`J010` (warn):** Triggered when a `noul` question instruction matches `COMPOUND`.  
    - *Message:* `compound yes/no question (and / or)`  
    - *Rationale:* *"Ask one thing per noul. Several nouls in one request cost almost nothing extra."*
11. **`J011` (error):** Triggered when `choice` options exceed `MAX_OPTIONS` (255).  
    - *Message:* `<n> options exceeds the 255-option limit`  
    - *Rationale:* *"Use hierarchical classification."*
12. **`J012` (warn):** Triggered when token Jaccard overlap between any two choice options exceeds 0.6.  
    - *Message:* `options <first> and <second> overlap heavily`  
    - *Rationale:* *"Overlapping options flatten the distribution and tank confidence. Merge them or sharpen the boundary."*
13. **`J013` (warn):** Triggered when `score` has >7 criteria levels.  
    - *Message:* `<n> score levels`  
    - *Rationale:* *"Fine-grained scales produce low confidence. Use 3 to 5 levels with clear descriptions."*
14. **`J014` (error):** Triggered when `noul` criteria for `true` and `false` are identical strings.  
    - *Message:* `true and false criteria are identical`  
    - *Rationale:* *"Contradictory guidance confuses the model. Make them distinct."*

*(Data rules `J020`, `J021`, `J022` govern dataset state size and label coverage).*

---

## Step 1: Pack-by-Pack Audit Tables

Every question instruction and criterion across all eight packs in `~/src/jev-mcp/packs/` was audited against the rules.

### 1. `bookmark-triage.json` (Working Pack)
*File: [bookmark-triage.json](../packs/bookmark-triage.json)*

| Question ID | Rule Triggered | Offending Text Quoted Exactly | Line Number |
| :--- | :--- | :--- | :--- |
| `expires` | `J010` (warn) | `"or"` in `"Does the value of this post depend on a version, price or lineup that will change?"` | line 23 |
| `expires` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 21–24 |
| `verifiable` | `J010` (warn) | `"or"` in `"Does it point at something checkable: a repository, a paper, a doc page, or reproducible numbers?"` | line 37 |
| `verifiable` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 35–38 |
| `route` | `J001` (warn) | `"not"` in `"worth keeping as a note, but not a skill"` | line 44 |

*Ambiguity / Semantic Note:* `durable_technique` (line 15) contains `"in six months"`. Rule `J004` checks `\d+\s*months?` and does not match spelled-out numbers like `"six"`. In line 18, `"a claim with no method"` uses `"no"`, which `NEGATION` omits (only matching `"no longer"`).

---

### 2. `code-review-triage.json` (Failing Pack)
*File: [code-review-triage.json](../packs/code-review-triage.json)*

| Question ID | Rule Triggered | Offending Text Quoted Exactly | Line Number |
| :--- | :--- | :--- | :--- |
| `is_real` | `J001` (warn) | `"not"` in `"the code is correct, or the finding describes something the excerpt does not show"` | line 19 |
| `actionable_now` | `J001` (warn) | `"without"` in `"Can this be fixed inside the same change, without new information from a human?"` | line 42 |
| `actionable_now` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 40–43 |
| `route` | `J001` (warn) | `"not"` in `"not a defect, unreachable, or pure taste"` | line 50 |

*Ambiguity / Semantic Note:* In `reachable` (line 27), criterion `false` contains `"no caller passes those inputs, or the path is unreachable"`. Neither `"no"` nor prefix `"un-"` in `"unreachable"` matches the strict `NEGATION` regex.

---

### 3. `docs-staleness.json` (Working Pack)
*File: [docs-staleness.json](../packs/docs-staleness.json)*

| Question ID | Rule Triggered | Offending Text Quoted Exactly | Line Number |
| :--- | :--- | :--- | :--- |
| `misleads` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 20–23 |
| `still_needed` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 24–27 |

*Ambiguity / Semantic Note:* No regex violations on negations, compounds, or dates.

---

### 4. `head-brief-quality.json` (Failing Pack)
*File: [head-brief-quality.json](../packs/head-brief-quality.json)*

| Question ID | Rule Triggered | Offending Text Quoted Exactly | Line Number |
| :--- | :--- | :--- | :--- |
| `names_exact_files` | `J010` (warn) | `"or"` in `"Does the brief name the exact files, symbols or line anchors to change?"` | line 24 |
| `names_exact_files` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 22–25 |
| `has_acceptance` | `J010` (warn) | `"and"` in `"Does the brief state how the agent will know the work is done and correct?"` | line 28 |
| `has_acceptance` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 26–29 |
| `ambiguous` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 30–33 |

*Ambiguity / Semantic Note:* The failing question `self_contained` (lines 12–21) contains `"needs to guess one or two things"` (spelled-out numbers) and `"who has read nothing else"` (`"nothing"` is not in `NEGATION`). It triggers **zero** static linter violations.

---

### 5. `lesson-dedupe.json` (Working Pack)
*File: [lesson-dedupe.json](../packs/lesson-dedupe.json)*

| Question ID | Rule Triggered | Offending Text Quoted Exactly | Line Number |
| :--- | :--- | :--- | :--- |
| `states_procedure` | `J001` (warn) | `"not"` in `"Does the candidate say what to DO next time, and not only what happened?"` | line 22 |
| `states_procedure` | `J010` (warn) | `"and"` in `"Does the candidate say what to DO next time, and not only what happened?"` | line 22 |
| `states_procedure` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 20–23 |
| `durable` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 24–27 |

*Ambiguity / Semantic Note:* `durable` (line 26) contains `"in six months"`, which escapes `J004` because `"six"` is spelled out.

---

### 6. `merge-risk.json` (Working Pack)
*File: [merge-risk.json](../packs/merge-risk.json)*

| Question ID | Rule Triggered | Offending Text Quoted Exactly | Line Number |
| :--- | :--- | :--- | :--- |
| `irreversible_path` | `J001` (warn) | `"cannot"` in `"Does the change touch something a revert alone cannot undo: data deletion, a migration, credentials, billing, or an outbound message?"` | line 25 |
| `irreversible_path` | `J010` (warn) | `"or"` in `"Does the change touch something a revert alone cannot undo: data deletion, a migration, credentials, billing, or an outbound message?"` | line 25 |
| `behaviour_change` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 31–34 |

---

### 7. `research-claim-verification.json` (Working Pack)
*File: [research-claim-verification.json](../packs/research-claim-verification.json)*

| Question ID | Rule Triggered | Offending Text Quoted Exactly | Line Number |
| :--- | :--- | :--- | :--- |
| `supported` | `J010` (warn) | `"or"` in `"Does \`source_excerpt\` state, or directly entail, the claim in \`claim\`?"` | line 14 |
| `overstated` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 20–23 |
| `independence` | `J001` (warn) | `"not"` in `"the excerpt does not say who measured what"` | line 31 |
| `publishable` | `J001` (warn) | `"not"` in `"do not publish"` | line 38 |

---

### 8. `skill-store-stale-ref.json` (Working Pack)
*File: [skill-store-stale-ref.json](../packs/skill-store-stale-ref.json)*

| Question ID | Rule Triggered | Offending Text Quoted Exactly | Line Number |
| :--- | :--- | :--- | :--- |
| `is_stale` | `J002` (error) | Multiple negations: `"no longer"` (line 22) and `"not"` (line 23) | lines 22, 23 |
| `is_stale` | `J010` (warn) | `"and"`, `"or"` in instructions | line 20 |
| `load_bearing` | `J009` (info) | `noul has no criteria` (criteria object omitted) | lines 26–29 |
| `route` | `J002` (error) | Multiple negations: `"cannot"` (line 45) and `"not"` (line 47) | lines 45, 47 |

*Ambiguity / Semantic Note:* `is_stale` instruction (line 20) contains multi-clause procedural dispatch (`"Answer true whenever ... Otherwise answer false when ... or when ..."`). `MULTI_HOP` does not trigger because it strictly regexes `if .+ then .+ otherwise`, but semantically this is the most heavily conditional prompt in the repository.

---

## Step 2: Test of the Hypothesis

### Rule Violation Counts by Pack

| Pack Name | Status | Total Questions | Errors (`J002`, `J011`, `J014`) | Warnings (`J001`, `J010`, etc.) | Infos (`J009`, etc.) | Total Findings | Findings / Question |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`code-review-triage`** | **Failing** | 5 | 0 | 3 | 1 | 4 | 0.80 |
| **`head-brief-quality`** | **Failing** | 6 | 0 | 2 | 3 | 5 | 0.83 |
| *Failing Subtotal* | | *11* | *0* | *5* | *4* | *9* | *0.82* |
| `bookmark-triage` | Working | 5 | 0 | 3 | 2 | 5 | 1.00 |
| `docs-staleness` | Working | 4 | 0 | 0 | 2 | 2 | 0.50 |
| `lesson-dedupe` | Working | 4 | 0 | 2 | 2 | 4 | 1.00 |
| `merge-risk` | Working | 4 | 0 | 2 | 1 | 3 | 0.75 |
| `research-claim-verification` | Working | 4 | 0 | 3 | 1 | 4 | 1.00 |
| `skill-store-stale-ref` | Working | 4 | 2 | 1 | 1 | 4 | 1.00 |
| *Working Subtotal* | | *25* | *2* | *11* | *9* | *22* | *0.88* |

### Comparative Analysis
1. **Rule Density:** Failing packs average **0.82 violations per question**, which is lower than the **0.88 violations per question** in working packs.
2. **Rule Severity:** Failing packs have **0 errors**. The only pack in the repository tripping `J002` (error: multiple negations) is `skill-store-stale-ref`, which is a working pack calibrated with 0 false positives at gate 0.5.
3. **Specific Question Performance:**
   - In `head-brief-quality`, the failing metric was `self_contained` (2.49 failure vs 2.53 success across 15 briefs). `self_contained` has **0 linter violations**.
   - In `code-review-triage`, the failing metric was `is_real` (0.79 real vs 0.83 false across 35 findings). `is_real` triggers only a single `J001` (warn) on the word `"not"` in criterion `false`. That exact pattern exists in calibrated, working questions like `lesson-dedupe:states_procedure` (trips `J001`, `J010`, `J009`), `merge-risk:irreversible_path` (trips `J001`, `J010`), and `research-claim-verification:publishable` (trips `J001`).
4. **Conclusion:** Working packs trip the exact same rules just as frequently. The wording difference is not large enough, nor directional enough, to be a plausible cause of the measured failures. **The hypothesis is DISCONFIRMED**. The failures stem from unobserved state information (e.g., missing code contract/spec in review triage; runtime Node environment and lead context in brief quality), as the pack calibration notes themselves document.

---

## Step 3: Proposed Rewrites for All Violations

> [!IMPORTANT]
> **Do NOT apply any rewrite to any pack file.** Another agent owns those files, and rewriting a question invalidates thresholds already calibrated against the old wording. Threshold recalibration is a decision for the lead agent.

All proposed rewrites remove the offending tokens (negations, conjunctions, missing criteria) while preserving domain semantics:

| Pack | Question ID & Rule | Before (Pack Text) | After (Proposed Rewrite) |
| :--- | :--- | :--- | :--- |
| `bookmark-triage` | `expires` (`J010`, `J009`) | *Instructions (line 23):* `"Does the value of this post depend on a version, price or lineup that will change?"`<br>*Criteria:* None | *Instructions:* `"Does the value of this post depend on changing details (version, price, product lineup)?"`<br>*Criteria:*<br>`true: "the value decays when listed versions, prices or lineups change"`<br>`false: "the core insight remains valid regardless of product updates"` |
| `bookmark-triage` | `verifiable` (`J010`, `J009`) | *Instructions (line 37):* `"Does it point at something checkable: a repository, a paper, a doc page, or reproducible numbers?"`<br>*Criteria:* None | *Instructions:* `"Does it point at checkable evidence (such as a repository, paper, documentation page, reproducible data)?"`<br>*Criteria:*<br>`true: "cites verifiable external sources or reproducible data"`<br>`false: "makes unanchored assertions with no inspectable reference"` |
| `bookmark-triage` | `route` (`J001`) | *Criterion `vault_note` (line 44):* `"worth keeping as a note, but not a skill"` | *Criterion `vault_note`:* `"worth keeping as a reference note rather than an actionable skill"` |
| `code-review-triage` | `is_real` (`J001`) | *Criterion `false` (line 19):* `"the code is correct, or the finding describes something the excerpt does not show"` | *Criterion `false`:* `"the code is correct, or the finding describes behavior absent from the excerpt"` |
| `code-review-triage` | `actionable_now` (`J001`, `J009`) | *Instructions (line 42):* `"Can this be fixed inside the same change, without new information from a human?"`<br>*Criteria:* None | *Instructions:* `"Can this be fixed inside the same change solely using information already present?"`<br>*Criteria:*<br>`true: "the fix is self-evident from the existing change and context"`<br>`false: "resolving this requires human clarification, external input, or broader design choices"` |
| `code-review-triage` | `route` (`J001`) | *Criterion `drop` (line 50):* `"not a defect, unreachable, or pure taste"` | *Criterion `drop`:* `"valid code, unreachable execution path, or stylistic preference"` |
| `docs-staleness` | `misleads` (`J009`) | *Instructions (line 22):* `"Would a reader following this section take a wrong action?"`<br>*Criteria:* None | *Instructions:* `"Would a reader following this section take a wrong action?"`<br>*Criteria:*<br>`true: "following these instructions leads directly to an error, broken setup, or incorrect behavior"`<br>`false: "the text is accurate, harmlessly minor, or guides the reader correctly"` |
| `docs-staleness` | `still_needed` (`J009`) | *Instructions (line 26):* `"Is this section worth keeping at all, assuming it were corrected?"`<br>*Criteria:* None | *Instructions:* `"Is this section worth keeping at all, assuming it were corrected?"`<br>*Criteria:*<br>`true: "the documented concept remains relevant to current architecture or workflows"`<br>`false: "the underlying feature, workflow, or system has been entirely retired"` |
| `head-brief-quality` | `names_exact_files` (`J010`, `J009`) | *Instructions (line 24):* `"Does the brief name the exact files, symbols or line anchors to change?"`<br>*Criteria:* None | *Instructions:* `"Does the brief name the exact modification targets (files, symbols, line anchors)?"`<br>*Criteria:*<br>`true: "explicitly identifies specific file paths, symbols, or line numbers to edit"`<br>`false: "leaves the target locations open-ended or unspecified"` |
| `head-brief-quality` | `has_acceptance` (`J010`, `J009`) | *Instructions (line 28):* `"Does the brief state how the agent will know the work is done and correct?"`<br>*Criteria:* None | *Instructions:* `"Does the brief state explicit completion criteria verifying the work is correct?"`<br>*Criteria:*<br>`true: "provides clear, testable success criteria or verification steps"`<br>`false: "lacks concrete verification steps, stopping conditions, or expected outcomes"` |
| `head-brief-quality` | `ambiguous` (`J009`) | *Instructions (line 32):* `"Does the brief contain an instruction that two competent engineers would carry out differently?"`<br>*Criteria:* None | *Instructions:* `"Does the brief contain an instruction that two competent engineers would carry out differently?"`<br>*Criteria:*<br>`true: "key directives permit conflicting interpretations by competent engineers"`<br>`false: "requirements are unambiguous with a single obvious execution path"` |
| `lesson-dedupe` | `states_procedure` (`J001`, `J010`, `J009`) | *Instructions (line 22):* `"Does the candidate say what to DO next time, and not only what happened?"`<br>*Criteria:* None | *Instructions:* `"Does the candidate provide concrete future action steps rather than solely recounting past events?"`<br>*Criteria:*<br>`true: "prescribes actionable forward-looking steps to follow"`<br>`false: "merely describes historical symptoms with zero forward-looking instructions"` |
| `lesson-dedupe` | `durable` (`J009`) | *Instructions (line 26):* `"Will this still be worth following in six months, rather than being tied to one incident?"`<br>*Criteria:* None | *Instructions:* `"Will this still be worth following in six months, rather than being tied to one incident?"`<br>*Criteria:*<br>`true: "captures general principles applicable over the next six months"`<br>`false: "records ephemeral details tied strictly to a one-off incident"` |
| `merge-risk` | `irreversible_path` (`J001`, `J010`) | *Instructions (line 25):* `"Does the change touch something a revert alone cannot undo: data deletion, a migration, credentials, billing, or an outbound message?"` | *Instructions:* `"Does the change touch permanent state operations where a revert alone leaves persistent effects (data deletion, migrations, credentials, billing, outbound messaging)?"` |
| `merge-risk` | `behaviour_change` (`J009`) | *Instructions (line 33):* `"Does this change what the software does, rather than only how it is written?"`<br>*Criteria:* None | *Instructions:* `"Does this change what the software does, rather than only how it is written?"`<br>*Criteria:*<br>`true: "alters runtime behavior, API semantics, or user-visible functionality"`<br>`false: "strictly refactors structure, types, tests, or styling with identical behavior"` |
| `research-claim-verification` | `supported` (`J010`) | *Instructions (line 14):* `"Does \`source_excerpt\` state, or directly entail, the claim in \`claim\`?"` | *Instructions:* `"Does \`source_excerpt\` directly entail the claim in \`claim\`?"` |
| `research-claim-verification` | `overstated` (`J009`) | *Instructions (line 22):* `"Does the claim generalise further than the excerpt allows?"`<br>*Criteria:* None | *Instructions:* `"Does the claim generalise further than the excerpt allows?"`<br>*Criteria:*<br>`true: "extrapolates beyond evidence presented in the excerpt"`<br>`false: "strictly bounds assertions to what the excerpt demonstrates"` |
| `research-claim-verification` | `independence` (`J001`) | *Criterion `unclear` (line 31):* `"the excerpt does not say who measured what"` | *Criterion `unclear`:* `"the excerpt omits authorship and measurement provenance"` |
| `research-claim-verification` | `publishable` (`J001`) | *Criterion `[0]` (line 38):* `"do not publish"` | *Criterion `[0]`:* `"suppress publication"` |
| `skill-store-stale-ref` | `is_stale` (`J002`, `J010`) | *Instructions (line 20):* `"Does \`target_excerpt\` contradict what \`reference_text\` claims? Answer true whenever \`line_asserts_current_state\` is true and the excerpt contradicts the line, even if the file is archived. Otherwise answer false when \`surrounding_text_says_absent\` is true, when \`file_declares_archived\` is true and the claim describes the machine that file documents, or when \`inside_code_block\` is true and the path is an example rather than a claim about this machine."`<br>*Criteria (lines 22–23):*<br>`true: "the claim no longer matches reality"`<br>`false: "the claim still matches, or the evidence does not show otherwise"` | *Instructions:* `"Does \`target_excerpt\` contradict \`reference_text\`? Positive condition: \`line_asserts_current_state\` holds with contradicting excerpt text (regardless of archival status). Negative exceptions: \`surrounding_text_says_absent\` holds; \`file_declares_archived\` documents a previous host; \`inside_code_block\` marks an illustrative example."`<br>*Criteria:*<br>`true: "the claim contradicts observed reality"`<br>`false: "the claim aligns with reality, or evidence confirms its validity"` |
| `skill-store-stale-ref` | `load_bearing` (`J009`) | *Instructions (line 28):* `"Would an agent following this skill take a different action if this reference were wrong?"`<br>*Criteria:* None | *Instructions:* `"Would an agent following this skill take a different action if this reference were wrong?"`<br>*Criteria:*<br>`true: "an incorrect reference diverts an executing agent into an error or wrong action"`<br>`false: "the reference is informational, cosmetic, or immaterial to agent execution"` |
| `skill-store-stale-ref` | `route` (`J002`) | *Criteria (lines 45, 47):*<br>`verify_live: "cannot be judged from the evidence given; open the target and re-run"`<br>`delete: "wrong and not worth replacing"` | *Criteria:*<br>`verify_live: "indeterminate from provided evidence; requires live target inspection"`<br>`delete: "erroneous with zero replacement value"` |

---

## Step 4: Linter Evaluation and Blind Spots

### 1. Worth Adopting Beyond These Eight Packs
- **Token Budgeting Checks (`J020`, `J021`):** Enforcing limits on dataset state sizes (error at >32k tokens, warning at >8k tokens) prevents distractor saturation. Example: in `bookmark-triage.json` (line 70), unexpanded preview text degraded judgment; in `head-brief-quality.json` (line 72), including every file mentioned in prohibitions inflated collisions.
- **Option Overlap Analysis (`J012`):** Token Jaccard similarity checking on choice option pairs catches taxonomy collisions before running costly manual labelling passes.
- **Identical Criteria Guard (`J014`):** Catches copy-paste errors where `true` and `false` criteria receive identical text, avoiding broken training/calibration runs.

### 2. Gaps and Blind Spots Not Checked by `jevcal`
- **Word-Form Numbers in Temporal / Arithmetic Rules:** `DATETIME` (`J004`) only matches digits (`\d+\s*months?`), missing `"in six months"` in `bookmark-triage.json` (line 15) and `lesson-dedupe.json` (line 26), and `"one or two"` in `head-brief-quality.json` (line 17). Jev 1.13 struggles with temporal boundaries regardless of digit formatting.
- **Procedural Logic Embedded in Instructions:** The linter only looks for `if .+ then .+ otherwise` (`MULTI_HOP`, `J006`). It misses arbitrary procedural dispatch scripts embedded in instruction prose, such as `skill-store-stale-ref:is_stale` (line 20: `"Answer true whenever ... Otherwise answer false when ..."`). Such branching should be computed in Python before calling Jev.
- **Exemplification vs. Compound Questions:** `COMPOUND` (`J010`) flags any `"and"` or `"or"`, conflating compound logic with exemplification in a list (e.g., `head-brief-quality:names_exact_files` line 24: `"files, symbols or line anchors"`).
- **Information Insufficiency (Ungrounded Judgment):** The fundamental failure mode across both failing packs is asking questions whose ground truth is unresolvable from the state schema:
  - In `code-review-triage:is_real` (line 16), the state supplies code excerpt and finding text, but lacks the specification/contract required to distinguish intended behavior from a defect.
  - In `head-brief-quality:self_contained` (line 14), the state supplies brief text, but cannot detect that an instruction fails on the host execution environment or lacks external lead context.
