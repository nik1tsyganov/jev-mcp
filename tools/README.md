# Tools

Two working passes built on the packs. Both do the deterministic half in code and send
Jev only what a script cannot settle.

## `skill_refs.py` — extract and resolve references in a skill store

    python3 tools/skill_refs.py ~/.claude/skills

Prints the reference census and writes `/tmp/skill-refs3.json`. Each reference carries
the document-level context a judgment needs: `file_declares_archived`,
`surrounding_text_says_absent`, `inside_code_block`, plus a resolution status of
`exists`, `missing`, `placeholder`, `truncated` or `windows-path`.

Those fields are not decoration. On 53 references, sending them cut the flagged set
from 43 to 7 with the same model and the same gate — the false positives were archived
files that already disclose the absence, and placeholders inside examples.

`deterministic_findings()` handles the class a model gets wrong even with full context:
a line asserting paths ARE present, checked with `os.path.exists`. Those score 0.32-0.39
on the stale question because the file around them is archived, so they never go to the
model at all.

## `brief_gate.py` — score delegation briefs before dispatch

    python3 tools/brief_gate.py briefs.json          # advisory, exits 0
    python3 tools/brief_gate.py briefs.json --strict # exits 1 when a brief is held
    cat block.json | python3 tools/brief_gate.py --json

Input is a JSON array of `{task, prompt, name?, project?}`. One request per brief.
Holds a brief when it is not self-contained, is ambiguous, names no exact files, states
no acceptance criteria, or should not have been one agent's job.

File overlap between briefs is computed in code, not asked: it is a set intersection.
`write_targets()` counts only files a brief tells the agent to create or edit, skipping
any filename preceded by a prohibition.

Measured on 11 real briefs from 2026-09-19: 2 passed, 9 were held, every hold with a
specific reason. Both probe briefs were correctly held for naming no files and stating
no acceptance criteria, and one was correctly flagged as work that should have stayed
with the lead.

## `audit_store.py` — the whole store pass in one command

    python3 tools/audit_store.py                 # census + deterministic findings + the request count
    python3 tools/audit_store.py --run           # spend them
    python3 tools/audit_store.py --run --json /tmp/out.json

Prints the plan and stops. Nothing is spent until `--run`, and the request count is
always stated first, because a corpus pass is the easiest way to spend a balance by
accident. The deterministic half — Windows paths, present-assertions, resolution — is
reported with no requests at all.

## `merge_risk.py` and `hooks/pre-push` — rank what to read before a push

    python3 tools/merge_risk.py origin/main..HEAD --repo ~/src/conclave
    tools/install_hook.sh ~/src/conclave          # install the advisory hook
    tools/install_hook.sh --remove ~/src/conclave

One request per changed file, capped at 25 (a 35-file range refuses rather than
spending silently). The hook never blocks: a missing key, a missing tool, a timeout or
a failed call all exit 0, and `JEV_MERGE_RISK=0 git push` silences it for one push. A
judgment ranks what a human reads; the tests gate the push.

The state carries what the diff cannot show: what kind of file it is, how many other
files in the repository name it, whether the change is deletion-only, and which
irreversible patterns the diff matches (file deletion, history rewriting, credentials,
schema, billing, outbound calls, permissions). Measured 2026-09-19 on a 19-file commit:
without those fields every file scored 0.30-0.62 blast radius and the gate never fired;
with them the spread ran 0.37-1.96 and the two provider files carrying an irreversible
pattern surfaced at 0.74 and 0.66.

## What the brief gate is measured to do, and not do

Calibrated 2026-09-19 against 15 real briefs labelled by outcome — did the head's work
need a correction traceable to the brief. It does not predict that: `self_contained`
averaged 2.49 on the seven failures and 2.53 on the eight successes.

It reliably catches two things, both seen in the same session: a brief that names no
files and states no acceptance criteria, and work that should have stayed with the lead.

It cannot catch a brief that is confidently wrong (a command that fails on the installed
runtime, a heuristic that over-fires) or one missing context only the lead holds (a
rename landing in another file at the same moment). Nothing in the brief text reveals
those, so no judgment over that text can find them. Before dispatch, the lead checks
both by hand: run any command the brief prescribes, and write down what has changed
since the brief was drafted.

## `bookmark_triage.py` — route a week of saved posts

    python3 tools/bookmark_triage.py posts.json          # prints the request count, spends nothing
    python3 tools/bookmark_triage.py posts.json --run

Input is a JSON array of `{author, text, posted_at, links, engagement}`. The browser
step is deliberately manual: the signed-in session lives in a real Chrome profile, and
an unattended scrape of a logged-in account is not something a tool should start by
itself.

It acts on the pack's `route` answer and prints `durable_technique` only as context,
because route measured better on this corpus. It flags a tie — top option under 0.5, or
under 0.10 clear of the second — and sends those to you. On the owner's 22 real posts:
8 skill-intake, 4 vault-note, 6 read-later, 4 drop, 10 ties.

It warns when a post still contains "Show more", because the judgement is then about
the preview rather than the post.

## Spending

`src/client.js` counts judgment requests for the life of the process and refuses past
200. Raise it deliberately with `TYPESAFE_MAX_REQUESTS`. `jev_models` is not counted.
The cap covers everything that goes through the MCP server. The Python tools in this
directory call the API directly and are NOT covered; each states its request count
before spending and requires `--run`.
