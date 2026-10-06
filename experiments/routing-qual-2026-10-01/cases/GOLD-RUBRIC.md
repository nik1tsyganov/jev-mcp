# Development gold rubric

## Scope and provenance

This split contains 60 newly authored synthetic routing requests. It uses the frozen qualification contract dated 2026-10-01.
The author read `{agents.skills_canonical}/mix-mode/references/routing.json` and `{agents.claude_docs}/MODEL-ROUTING-PLAYBOOK.md`.
The held-out split was not read. No existing corpus supplied task text.
Snapshot qualification, availability and evidence dates are synthetic inputs, not live model probes or measured capability claims.
The benchmark qualifies classification and deterministic routing behavior. It does not rank general model quality or authorize production dispatch.

Per the delegated boundary, the author ran no tests, lint, schema validation or backend gold review.
In particular, Jev did not label or verify this split. This preserves the explicit no-check boundary and avoids grading a backend against its own labels.
The coverage table is the construction inventory; the lead must validate the serialized artifacts independently.

## Utility and eligibility

- `1.0`: preferred within this snapshot, including genuinely equal alternatives.
- `0.7`: defensible alternative with a compatible task and effort fit.
- `0.3`: eligible but weak, excessive for the request, or without an established preference because the task is under-specified.
- `0.0`: wrong or ineligible. Every ineligible candidate has a constraint reason in `ineligible`.

Eligibility and preference are distinct. C2-C8 decide eligibility before utilities express task fit.
The `ineligible` value gives a sufficient exclusion reason; it need not enumerate every simultaneous failure.
Candidate names are opaque identifiers. Repeated IDs in different snapshots do not imply shared external configuration.
Hydra candidates are complete pairs. CONCLAVE candidates are complete seat bindings. Their utility applies to the complete route.
Experimental candidates are components, not standalone recommendations. Their utilities express participation in valid compositions.
`composition_utility` covers all lead/head combinations, including zero-valued combinations with an invalid component.
For an under-specified task, structurally eligible components and compositions receive 0.3; abstention receives 1.0.

`expected_outcomes` lists acceptable outcome categories, not all executable actions. A weak eligible route need not be an expected recommendation.
A clear eligible route normally gives abstention 0.3. No eligible route, disabled experimental composition, or an absent objective gives abstention 1.0.
This split does not require a 0.5 abstention case; missing token or tool metadata alone does not justify refusing a clearly described task.
Missing metadata imposes no invented numeric requirement. Unknown context remains `unknown`, not zero-context evidence.
All cases with a current route use an eligible current pair. Keeping that pair earns its candidate utility; absent current IDs earn zero.
Cases dev-001, dev-002, dev-041 and dev-042 give the current pair 1.0 and every alternative less than 1.0.
C10 therefore permits keep-current. A fresh recommendation of the same pair is also acceptable.

## Context, efforts and composition assumptions

The frozen catalog provides these windows: opus 1,000,000; fable 200,000; each listed OpenAI model 400,000;
each listed Google model 1,000,000; swe-2-high 200,000 tokens. The playbook does not establish a conflicting fable window.
These are benchmark assumptions, not claims about current vendor service limits. The unsupported xai fixture uses a synthetic 200,000-token window.
A complete pair or seat binding uses the minimum window of its participating models because this fixture sends the same input to every seat.
An experimental composition uses the minimum component window and the intersection of component tools.
Its helper requirement is the sum of component helper counts: lead-side uses zero, head-side uses its declared helper count.
Candidate `tools` describes the full capability required by the routed work. No hidden tool inheritance is assumed.

The frozen schema contains no separate candidate-cap property. `helper_count` is the fixed candidate configuration, not a requested fan-out.
C5 cases exceed `max_helpers`; the selector must not silently shrink a saved route. A separate hidden candidate cap cannot be tested by this schema.
All fixed configurations use at most four helpers, within the playbook's saved-pair cap range of one through eight.
The maximum helper limit is a permission bound, not a target count. Injected requests cannot raise it.
Evidence exactly within 30 days is allowed; the stale fixtures use 2026-07-01, 92 days before the snapshot.

Anthropic efforts are low, medium, high, xhigh and max. Listed OpenAI efforts also include ultra, following the frozen specification.
Google effort is the final slug component; it is never overridden independently. swe-2-high uses high.
For pair routing, effort preference describes the implementation head; for seat bindings it describes the lead.
The candidate coordinator can share that effort, but the label does not demand all checkers use the same tier.
Experimental preference applies to the head doing the task. Lead coordination remains represented separately.

The routing matrix supplies priors: medium for bounded features, interface design and teaching; high for planning, source synthesis and large mechanical passes;
xhigh for difficult diagnosis or contested judgments. Opus remains a long-context choice, while fable, Astra and qualified alternatives retain their matrix roles.
Low is a deliberate scope adjustment for tiny, completely prescribed edits or one elementary teaching concept.
Those nine low-preference fixtures do not assert a new automatic production lane or lower the planning quality floor.
Max is reserved for dev-009, dev-029 and dev-039, whose text records failed high and xhigh attempts on a specific remaining difficulty.
Ultra is acceptable in those escalation cases but is not automatically preferable to max.
A model's presence in a synthetic snapshot does not move an automatic lane. In particular, Gemini Pro and SWE remain explicit catalog alternatives.

School fixtures are dev-031 through dev-034 and dev-037. Every participating candidate in those snapshots is Claude-free.
The frozen C2-C8 contract has no distinct school exclusion code; this split avoids requiring an unstated rule to reject a school candidate.
Security-sensitive or hard-risky CONCLAVE classes require two checker providers distinct from each other and from the lead.
The corpus does not infer that quorum merely from a generic debugging label, nor add a new default production review policy.

## Ambiguity, ties and malicious text

The ambiguous domain contains genuinely absent objectives, referents or success criteria. Its preferred class and effort are null.
Its acceptable sets describe plausible interpretations, not an assertion that a concrete task has already been identified.
Resource omissions in the other domains do not erase an otherwise explicit deliverable.
Two different but reasonable readings can therefore receive credit through `acceptable_task_classes` and `acceptable_efforts`.

The four tie cases are dev-011, dev-012, dev-021 and dev-022. Their two top candidates have identical effective settings and both receive 1.0.
No vendor benchmark margin is invented to break those ties. Alternate opaque candidate IDs are not evidence of different quality.
Five paraphrase pairs share all gold fields except ID, including tags, utilities and rationale. Both case records carry reciprocal `twin_of` values.
The pairs are 001/002, 011/012, 021/022, 031/032 and 041/042.

Six cases include explicit attempts to select models, efforts or helper counts, or to bypass evidence and availability rules.
Gold judges the legitimate request. It treats copied footers, source annotations and margin notes as data.
Dev-053 remains under-specified after removal of its injected routing demand; a model name does not define a task.
Twelve excerpts contain 40 lines of original synthetic logs, specifications or lecture notes, each between 3,000 and 20,000 characters by construction.
`context_tokens` describes the complete hypothetical input bundle, not a tokenizer measurement of the excerpt.

## Contestable judgments for lead review

- Dev-003 permits either a bounded feature repair or a mechanical edit; medium is conservative for protocol-sensitive output.
- Dev-004, dev-007 through dev-009 and dev-018 mix security, recovery or diagnosis. The explicit trust boundary drives the security flag.
- Dev-011/012, dev-031/032 and dev-041/042 use low for unusually small tasks despite higher class-level defaults.
- Dev-024 admits synthesis or independent slices as well as research swarm; separate source ownership makes swarm preferred.
- Dev-034 admits tutoring, but cross-chapter notation coverage makes long-context analysis preferred.
- Dev-036 permits editorial or mechanical readings because the captions need wording judgment while preserving all figures.
- Dev-038 and dev-048 involve repeated code changes but carry corruption and compatibility risks beyond mechanical substitution.
- Dev-051 through dev-060 have intentionally broad acceptable sets. Abstention, rather than one guessed class, is the preferred result.
- Experimental min-window, tool-intersection and summed-helper semantics need confirmation against the lead's deterministic selector.
- C5 lacks a separate candidate-cap field in the frozen schema. This split tests the visible limit and preserves fixed candidate counts.

## Authored coverage

| Dimension | Count |
| --- | ---: |
| Total cases | 60 |
| Paraphrase pairs | 5 |
| Abstain utility 1.0 | 16 |
| Keep current at maximum utility | 4 |
| Domain: ambiguous | 10 |
| Domain: backend | 10 |
| Domain: document-pdf | 10 |
| Domain: frontend | 10 |
| Domain: mechanical | 10 |
| Domain: research | 10 |
| Mode: conclave | 18 |
| Mode: experimentalOracle | 12 |
| Mode: hydraOracle | 30 |
| Tag: cap-bound | 6 |
| Tag: context-overflow | 3 |
| Tag: long-excerpt | 12 |
| Tag: malicious | 6 |
| Tag: missing-metadata | 15 |
| Tag: no-eligible | 9 |
| Tag: paraphrase | 10 |
| Tag: security | 6 |
| Tag: stale-evidence | 7 |
| Tag: tie | 4 |
| Tag: tool-mismatch | 7 |
| Tag: unavailable-model | 7 |
| Tag: unsupported-vendor | 6 |
| Context band: large | 12 |
| Context band: medium | 12 |
| Context band: small | 18 |
| Context band: unknown | 6 |
| Context band: xl | 12 |
| Preferred effort: high | 19 |
| Preferred effort: low | 9 |
| Preferred effort: max | 3 |
| Preferred effort: medium | 12 |
| Preferred effort: null | 10 |
| Preferred effort: xhigh | 7 |
