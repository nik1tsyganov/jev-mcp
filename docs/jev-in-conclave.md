# Where Jev sits in CONCLAVE, and in the day

Written 2026-09-19, after measuring eight packs. Every claim here is either shipped
code or a measured number; anything unproven says so.

## Already shipped in the runtime

| Decision | Tool | Status |
| --- | --- | --- |
| Task class per unit | `~/src/conclave/tools/jev-plan-classify.js` | live, bound into `plan-seal.json` |
| Convene and net-benefit | arbiter policy | live |
| Panel tally | `~/src/conclave/tools/panel-tally-jev.js` | live |
| Tie-break and the final verdict | `~/src/conclave/tools/jev-arbiter.js` | live; xAI retired as arbiter 2026-09-16 |

Deterministic code gates every one of those. That is the rule, not a preference: a
judgment ranks and routes, a check decides.

## Fits worth adding, in order

1. **Merge risk on a unit's returned diff.** The strongest measured gate this machine
   has: `blast_radius` 0.86, zero errors on 20 hand-read diffs, and `irreversible_path`
   0.40 with 2 errors on 22. A panel that approves nine units still hands back a diff
   nobody ranked. This is ready.
2. **Seat evidence verification.** A seat cites a file and claims it supports its
   verdict. `research-claim-verification` scored 0.64-0.98 on true claims and 0.01-0.06
   on false, with ONE constraint: the claim must be atomic. A compound sentence scores
   near zero whatever the truth. Split a seat's claim into parts first.
3. **Seat routing.** `decisionMatrix2026-09-16` picks seats from a table today. A table
   that works is not a problem to solve; the case for Jev here is only strong if the
   table starts needing exceptions.

## Fits to avoid, measured

- **Brief quality before a seat dispatch.** Measured non-predictive: 2.49 against 2.53
  on 15 real briefs labelled by outcome. The failures were wrong or missing facts, not
  vague prose, and no judgment over a brief can see what the brief omits.
- **Review-finding triage.** Measured inverted: 0.79 on real defects against 0.83 on
  false ones, across 35 findings. Adding the documented intent did not fix it.

## Which skills suit a Jev pass

A skill is a candidate when it repeats one bounded decision over many items.

| Skill | The repeated decision | Pack | Measured |
| --- | --- | --- | --- |
| `skill-store-maintenance` | is this reference stale, and does it matter | `skill-store-stale-ref` | gate 0.5, 15% disagreement |
| `research-verification` | does the source support the claim | `research-claim-verification` | gate 0.35, atomic claims only |
| `task-retrospective` | duplicate, extends, or new lesson | `lesson-dedupe` | good on near-duplicates; rest unmeasured |
| `documentation` | does this section still match the code | `docs-staleness` | gross drift only |
| `skill-curation` | intake, note, read later, or drop | `bookmark-triage` | use the route answer, not the score |
| `git-workflow` | which changed file needs a human read | `merge-risk` | gate 0.86, 0 errors on 20 |
| `code-review` | is this finding real | `code-review-triage` | **does not work** |

## How it lands in the day

- **A corpus decision over more than a handful of items** goes through `jev-audit`:
  state the request count, batch the questions, apply the gate in code, report the
  numbers. One command runs the store pass.
- **Before a push** from `jev-mcp` or `conclave`, the pre-push hook ranks the changed
  files. Advisory, never blocks.
- **Inside a CONCLAVE run**, the arbiter already decides class, convening and the
  tally. The next addition is merge risk on the returned diff.
- **Nothing else fires by itself.** The five MCP tools are available in every session on
  four vendors, and an agent calls them when a decision is bounded enough to deserve it.

## The rule that governs all of it

Classify the decision first: deterministic code, Jev, a generative model, or a human.
A gate belongs to the model it was measured on, and every pack records that model.
