# Jev integration for Droppy Code

Droppy Code decides things constantly and has no way to be unsure: a head is dispatched
or it is not, a merge runs or it does not, six heads spawn because the lead said six.
Jev turns those into numbers the app can threshold, at a fraction of the cost of asking
another agent.

Written against `upstream/main` (the tree Droppy Code 1.6.1 was built from), so the
anchors below use its layout. This document lives here rather than in the Droppy Code
checkout so it can go upstream as its own MR, separate from the `agy` flag fix.

## Why a typed judgment and not another agent

An extra head costs a session, tokens and wall-clock, and returns prose that the app
has to parse and cannot threshold. Jev returns a probability or a score in one call, so
the app can set a bar at 0.6 and change it later from measurement. And there is no
conversation to manage: no retries for format, no "as an AI" preamble, no partial JSON.

## Two integration paths

**Path A — the `jev` MCP server.** Droppy Code already has a complete MCP surface:
`MCPProviderConfig` in `DroppyCode/Services/MCP/MCPProviderConfig.swift` generates one
config file per provider (`claude`, `codex`, `copilot`, `gemini`) from the connected
servers, and `ProviderRegistry.swift:274` hands the Antigravity CLI its file through
`GEMINI_CLI_SYSTEM_SETTINGS_PATH`. Adding `jev` to the catalog costs nothing new: the
server is a stdio process at `~/src/jev-mcp/src/server.js`, and every agent
inside Droppy Code gains six tools (`jev_ask`, `jev_noul`, `jev_choice`, `jev_score`, `jev_models`,
`decision_browser_action`). What it does **not** give you is any judgment
inside the app itself — the agent has to choose to ask.

**Path B — native Swift.** `AppModel` calls the endpoint directly and uses the numbers
in its own control flow and UI. One small client, one questions file, no agent in the
loop. This is the only path that can gate a dispatch or rank a merge, because those
decisions happen in the app and never reach an agent.

They compose: Path A for the agents, Path B for the app. Path A is an afternoon.
Path B is a day plus whatever UI you want around the numbers.

## Where the numbers change a decision

### 1. Brief quality before a Hydra block goes out

`HydraDelegationStream.delegation(fromEntry:)`
(`DroppyCode/Core/Models/HydraDelegationStream.swift:110`) already turns each entry into
a `HydraDelegation` carrying `task`, `prompt`, `name` and `project`. That is the state.

State: the prompt, the task title, the files the prompt names, and the file lists of the
sibling entries in the same block.

Questions (`packs/head-brief-quality.json`): `self_contained` as a `score` over
`["needs a conversation first", "needs to guess one or two things", "needs a few
lookups", "can start immediately"]`; `names_exact_files`, `has_acceptance`, `ambiguous`
and `file_overlap` as `noul`; `sizing` as a `choice` over `one_agent` / `split` /
`keep_inline`.

Threshold: `self_contained` under 2.5, or `ambiguous` over 0.5 → the head still
launches, but the panel marks the brief amber with the reason. Never block the lead's
dispatch on a network call.

### 2. Overlapping heads

Same request as above; `file_overlap` over 0.4 means two entries in one block will edit
the same file. Today that is discovered at merge. `HydraPanel.swift` can show it before
the heads start, which is the only moment it is cheap to fix.

### 3. Fan-out sizing

State: the lead's own request text plus the repository's changed-file count.
Question: a `choice` over `one_head`, `two_to_three`, `full_team`, with the descriptions
naming what each is for. `HydraPair.clampedCap` (`Hydra.swift:109`) already clamps the
cap; this gives it a reason rather than a constant. Advisory only — the lead may
override, and the number is a suggestion in the panel.

### 4. Merge risk, per file

`mergeHydraProject(of:lead:project:checkout:work:runtime:several:)`
(`AppModel+HydraMerge.swift:204`) walks each project's work before it lands, and
`hydraWork(of:runtime:...)` (`:450`) already collects the changed paths.

State per changed file: path, the diff summary, lines added and removed, and one
sentence on what the file does. Questions (`packs/merge-risk.json`): `blast_radius` as
a `score`, `irreversible_path` and `behaviour_change` as `noul`, `route` as a `choice`.

Threshold: `irreversible_path` over 0.4, or `blast_radius` over 2.0, sorts that file to
the top of the merge popover with a marker. It does **not** block the merge. The one
exception is the stray-path branch (`strayBody(_:)`, `:123`) — if the app ever deletes
or overwrites outside the checkout on a judgment, a missing judgment must refuse.

### 5. Routing a new chat to the right project pair

`AppModel.hydraProject(named:for:)` (`AppModel+Hydra.swift:278`) resolves a head's
`project` reference by name today, and `HydraPair.projectPair(_:hydraOn:in:)`
(`Hydra.swift:117`) picks the pair. For a fresh chat with no reference, a `choice` over
the sidebar project names, with each project's one-line description as the criteria
value, routes it from the first message. Under 0.5 top probability, or under 0.1 clear
of the second, leave the current default and say nothing.

### 6. Merge-request description quality

`hydraCreateMergeRequest(git:title:body:source:target:)`
(`AppModel+HydraMerge.swift:353`) composes and opens the MR. Score the body before it is
sent: does it say what changed, why, and what was checked. Under the bar, the popover
offers "add what you checked" rather than opening a thin MR. A `score`, one request, at
the moment the user is already waiting on the network.

### 7. Head report triage

`hydraTeam(of:)` and `workingHydraHeadNames(of:excluding:)` (`AppModel+Hydra.swift:256`,
`:263`) know which heads reported. Each report can be scored for whether it actually did
the work or only described it — the single most common failure of a fast head model.
`noul`: "Does this report name files it changed, rather than describing what it would
change?" Under 0.5, the panel flags the head as a probable no-op before the lead reads
six reports.

## Failure and cost posture

One request per decision, never one per question: every pack above fits in a single
call. Cache on a hash of the state — a re-rendered panel must not re-ask.

When the call fails, the key is missing, or the user has no TypeSafe account, every
feature above falls back to exactly today's behaviour. A number that does not arrive
changes nothing on screen except the absence of a badge.

The exception is any judgment placed in front of a destructive action. There, absence
must refuse loudly rather than allow silently. A missing safety record is not a pass.

## Recommendation

Build **Path B, the brief gate (§1 and §2), first.** It sits at the one moment in
Droppy Code where a bad decision costs the most — six agents running in parallel on a
vague brief, with the cost paid in vendor turns and in a merge nobody can untangle.
The state is already assembled by `HydraDelegationStream`, the output is one badge per
head in a panel that already exists, and nothing blocks if the call fails. It also
produces the labelled data needed to calibrate everything else: after fifty dispatches
you know what a 2.5 actually means here. Ship `jev_ask` through the MCP catalog at the
same time, since the catalog work is trivial and agents inside the app can start using
it immediately.

## Not proposed

- **Jev deciding whether to merge.** A judgment must never gate an irreversible action;
  the tests and the build do that.
- **Jev picking the provider or model for a pair.** The routing is deterministic and
  auditable today. Replacing it with a probability removes the audit trail and adds a
  bill.
- **Jev summarising head reports.** Prose out, wrong tool.
- **A judgment on every tool call.** A network round trip in front of each tool makes
  the session feel broken, and the state at that point is too thin to judge well.
- **Asking an agent to write the questions at runtime.** Agents write weak questions.
  Ship the packs as data and let them be reviewed.
