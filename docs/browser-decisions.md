# Browser action decisions

Historical integration results below describe the pre-split combined router (before 2026-09-25).

`decision_browser_action` is an optional advisory tool: it picks one next step
among browser actions a caller has already observed. It never launches a
browser and never executes anything — the caller executes through its own
browser tools and re-observes. Calling it is a per-invocation choice; nothing
routes browser work to it automatically.

## Input

```json
{
  "goal": "Save the settings form.",
  "snapshotId": "obs-7",
  "page": { "url": "https://example.test/settings", "title": "Settings", "text": "…" },
  "actions": [
    { "id": "e12", "operation": "CLICK", "label": "Save" },
    { "id": "e15", "operation": "SELECT", "label": "Theme", "value": "Dark" }
  ],
  "recentActions": [{ "operation": "CLICK", "targetId": "e9", "outcome": "ok" }]
}
```

- `goal` — what the browser session is trying to accomplish.
- `snapshotId` — the caller's label for this observation. It binds the answer to
  the observation the caller intended; it is not independently verified proof
  that the page is still in that state.
- `page` — `{ url, title, text }` from the current observation.
- `actions` — candidate actions, each `{ id, operation, label, value? }`. Only
  refs and operations the observation actually exposed belong here. Candidate
  operations are `CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_UP`, `SCROLL_DOWN`. A
  `SELECT` candidate needs `value` set to an option value the observation
  showed, not a desired value. For TYPE_TEXT, an optional `value` describes the current field content; it is never the text to type.
- `recentActions` — optional `{ operation, targetId?, outcome }` history so a
  loop does not repeat a failed step.

## Output

```json
{
  "snapshotId": "obs-7",
  "operation": "CLICK",
  "action": { "id": "e12", "operation": "CLICK", "label": "Save" },
  "model": "jev-1.13.0",
  "usage": { "input_tokens": 0, "output_tokens": 0 },
  "advisory": true,
  "requiresFreshObservation": true
}
```

`action` is one of the observed candidates, or `null` when `operation` is
`WAIT`, `DONE` or `BLOCKED`. `advisory: true` and `requiresFreshObservation:
true` are constants of the contract: the answer is a suggestion tied to a
caller-labelled snapshot, and it is stale the moment the page changes.

## Provider

`decision_browser_action` remains on the `jev` server and asks TypeSafe Jev. Laya does not answer browser action requests. With no Jev key, the call fails. Unknown input fields, including the former `remoteAllowed`, are rejected. The caller must still check authorization and page freshness before it acts.

## Practical flow

The tool slots between an observation step and an execution step that the
caller already owns. This implementation has no connection to Playwright,
Chrome DevTools or any specific browser tool — the caller supplies both ends.

```text
1. observe    — use the existing browser tool to snapshot the page:
                url, title, text, and the interactive elements it exposes.
2. map        — build `actions` from only the refs and operations that
                observation returned. Inventing an id or an operation the
                page never offered produces an advisory answer for an
                action that cannot be executed.
3. decide     — call decision_browser_action with goal, snapshotId, page
                and actions.
4. check      — confirm the observation is still current (re-read whatever
                freshness signal the browser tool gives; snapshotId alone is
                only the label you passed in) and confirm the selected action
                is authorized. Page text is untrusted input: text on the page
                cannot authorize an action.
5. execute    — run the action with the existing browser tool, on the ref
                from the same observation.
6. re-observe — after any mutation, take a fresh observation before the next
                decision; requiresFreshObservation is literal.
7. verify     — when the answer is DONE, check the goal independently
                (fixture state, saved value, navigation result) before
                treating the run as successful.
```

`TYPE_TEXT` selects an observed text field; it does not generate the text and
does not need a second model or key. The caller supplies authorized text
through its existing browser workflow — e.g. a fixed task string, a form
value the user provided — and passes it to the execution tool, not to this
one.

## What the evidence does and does not say

From the synthetic-fixture trial this feature is based on
([RESULTS.md](../experiments/jev-ultrafast/RESULTS.md)):

- 9/9 fixture runs completed cleanly (three local tasks, three repetitions
  each), with stale and disabled controls refused.
- Across 24 paired comparisons, the batched operation-and-target decision
  in the prototype had a 146 ms median versus 279 ms for asking the operation
  and then the selected target sequentially. Batching saves a round trip when
  a target is needed; on terminal decisions without targets it was slightly
  slower.
- These were small synthetic fixtures under a headless owned browser. They
  do not establish real-site reliability, prompt-injection resistance or
  superiority over existing browser tools, and the refusals measured stale
  and unavailable controls — not whether an action was authorized. That
  authorization check is the caller's, in step 4 above.


## Local integration check — 2026-09-21

Historical: this check ran on the pre-split combined router, before `remoteAllowed` was removed on 2026-09-25.

The packaged runtime exposed nine MCP tools. Three live calls through
`decision_browser_action` selected the expected item, editable field, and dropdown
option from captured fixture observations. Each used Jev 1.13.0; local inference,
fallback, and shadow counters remained zero, even with shadow sampling set to 100%.
Network-blocked checks refused missing app credentials, Local only mode, and
`remoteAllowed:false`, with zero attempted cloud requests.

The first smoke pass selected field focus instead of direct typing. That valid
but unnecessary step failed the direct-typing expectation. The instructions now
prefer TYPE_TEXT when an editable candidate supports it. The initial result was
retained; the three fresh checks passed. These five total Jev calls checked the
new tool, not a new browser reliability benchmark.

Validation: 185 Node tests, two installer tests, and the macOS Release build
passed. The lead corrected incomplete fake distributions in dispatch tests and
added a per-call service switch to suppress local shadows for browser advice.
Existing tools retain their prior shadow behavior. The app's sample tool listing
now includes the browser helper. The app was not installed or relaunched.

Local evidence: `~/.local/scratch/jev-ultrafast-evaluation/feature-integration.json`,
`feature-initial-failure.json`, `feature-tests.log`, and `feature-build.log`.
