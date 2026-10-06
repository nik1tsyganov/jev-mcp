"""Frozen, deterministic baselines; no case files or gold labels inform rules.

Sources: Skills/mix-mode/references/routing.json classes.*.title and
classes.*.roles.implement; Context/MODEL-ROUTING-PLAYBOOK.md sections 3 and 4.
Keyword matching is case-insensitive substring matching. First match wins:

security-sensitive: auth, login, session, token, secret, password, payment,
                    oauth, permission
tie-break: tie-break, tie break, second opinion, disputed, contested
debug-mystery: mystery, unexplained, root cause, root-cause, bisect, debug
research-swarm: research swarm, parallel research, independent research,
                orchestrated research
parallel-slices: independent slices, parallel slices, independent units,
                 split work, parallel implementation
hard-risky: risky, hard change, end-to-end, end to end, trust boundary
bulk-mechanical: mechanical, rename, migration, formatting, repetitive
ui-design: ui design, interface design, visual interface, redesign, layout
tutoring-dispatch: tutor, teach, explain, homework, exercise, exam, proof
prose-writing: prose, creative writing, essay, story, writing
planning: planning, architecture, plan, trade-off, tradeoff, dependencies
long-context-analysis: long-context, long context, large corpus, many files,
                       codebase analysis
research-synthesis: research, synthesis, sources, literature, conclusion
standard-feature: feature, implement, build, fix, add, update

If none matches, context_tokens > 64000 selects long-context-analysis;
otherwise select standard-feature. This threshold operationalizes the
playbook's large-corpus description using the benchmark context bands.

Effort table (highest applicable floor wins): class implement effort is the
floor, using the highest declared lead effort for dual-lead classes. Thus
planning/high; standard-feature/medium; hard-risky/high; security-sensitive/high;
bulk-mechanical/high; parallel-slices/xhigh; debug-mystery/xhigh; tie-break/xhigh;
long-context-analysis/high; research-synthesis/high; prose-writing/high;
ui-design/medium; tutoring-dispatch/medium; research-swarm/high.
files_touched > 3 or context_tokens > 64000 => at least high.
'risky', 'root cause', 'root-cause', 'security' => at least high.
'contested', 'tie-break', 'tie break', 'second opinion' => at least xhigh.
The numeric file threshold operationalizes the playbook's 'one to a few files';
these are declared baseline heuristics, not claimed vendor recommendations.
No ungrounded max-effort or low-effort assignment is added.

Security yes: auth, login, session, token, secret, password, payment, OAuth,
permission. Injection yes: ignore previous, use model, set effort, helpers,
override. These detection lists come from the benchmark contract.
Ambiguous yes: task_text has fewer than six words, or no verb from this fixed
list: add, analyze, analyse, assess, audit, bisect, build, change, check, compare,
create, debug, design, document, edit, evaluate, explain, find, fix, format,
implement, integrate, investigate, migrate, plan, read, refactor, rename,
research, resolve, review, rewrite, summarize, summarise, synthesize, teach,
test, update, verify, write. Verb matching uses whole words.

Manual default: standard-feature, medium, no security, no injection, no ambiguity.
Keep-current: use the first declared task class of the current complete
candidate and enforce C10, including that class's C8 checker requirements.
A current experimental side alone is not a complete route and must abstain.
"""

import re

from policy import (
    ANSWER_LABELS, EFFORT_ORDER, RULES, _assign, _effort, _empty_route,
    constraint_failures,
)

BASELINE_VERSION = "routing-baselines-v1"
SECURITY_KEYWORDS = (
    "auth", "login", "session", "token", "secret", "password", "payment",
    "oauth", "permission",
)
INJECTION_KEYWORDS = ("ignore previous", "use model", "set effort", "helpers", "override")
CLASS_KEYWORDS = (
    ("security-sensitive", SECURITY_KEYWORDS),
    ("tie-break", ("tie-break", "tie break", "second opinion", "disputed", "contested")),
    ("debug-mystery", ("mystery", "unexplained", "root cause", "root-cause", "bisect", "debug")),
    ("research-swarm", ("research swarm", "parallel research", "independent research", "orchestrated research")),
    ("parallel-slices", ("independent slices", "parallel slices", "independent units", "split work", "parallel implementation")),
    ("hard-risky", ("risky", "hard change", "end-to-end", "end to end", "trust boundary")),
    ("bulk-mechanical", ("mechanical", "rename", "migration", "formatting", "repetitive")),
    ("ui-design", ("ui design", "interface design", "visual interface", "redesign", "layout")),
    ("tutoring-dispatch", ("tutor", "teach", "explain", "homework", "exercise", "exam", "proof")),
    ("prose-writing", ("prose", "creative writing", "essay", "story", "writing")),
    ("planning", ("planning", "architecture", "plan", "trade-off", "tradeoff", "dependencies")),
    ("long-context-analysis", ("long-context", "long context", "large corpus", "many files", "codebase analysis")),
    ("research-synthesis", ("research", "synthesis", "sources", "literature", "conclusion")),
    ("standard-feature", ("feature", "implement", "build", "fix", "add", "update")),
)
CLASS_EFFORT = {
    "planning": "high", "standard-feature": "medium", "hard-risky": "high",
    "security-sensitive": "high", "bulk-mechanical": "high", "parallel-slices": "xhigh",
    "debug-mystery": "xhigh", "tie-break": "xhigh", "long-context-analysis": "high",
    "research-synthesis": "high", "prose-writing": "high", "ui-design": "medium",
    "tutoring-dispatch": "medium", "research-swarm": "high",
}
VERBS = frozenset((
    "add analyze analyse assess audit bisect build change check compare create debug "
    "design document edit evaluate explain find fix format implement integrate "
    "investigate migrate plan read refactor rename research resolve review rewrite "
    "summarize summarise synthesize teach test update verify write"
).split())


def _answers(task_class, effort, security="no", injection="no", ambiguous="no"):
    chosen = {"task_class": task_class, "effort": effort, "security_sensitive": security,
              "injection": injection, "ambiguous": ambiguous}
    return {qid: {"probs": {label: float(label == chosen[qid]) for label in labels}}
            for qid, labels in ANSWER_LABELS.items()}


def matrix_lookup_answers(case):
    text = case["task_text"].lower()
    metadata = case.get("metadata", {})
    context_tokens = metadata.get("context_tokens", 0)
    task_class = next((name for name, keywords in CLASS_KEYWORDS
                       if any(keyword in text for keyword in keywords)),
                      "long-context-analysis" if context_tokens > 64000 else "standard-feature")
    floors = [CLASS_EFFORT[task_class]]
    if (metadata.get("files_touched", 0) > 3 or context_tokens > 64000
            or any(word in text for word in ("risky", "root cause", "root-cause", "security"))):
        floors.append("high")
    if any(word in text for word in ("contested", "tie-break", "tie break", "second opinion")):
        floors.append("xhigh")
    effort = max(floors, key=EFFORT_ORDER.index)
    words = re.findall(r"\b[\w'-]+\b", text)
    return _answers(
        task_class, effort,
        "yes" if any(word in text for word in SECURITY_KEYWORDS) else "no",
        "yes" if any(word in text for word in INJECTION_KEYWORDS) else "no",
        "yes" if len(words) < 6 or not VERBS.intersection(words) else "no",
    )


def manual_default_answers(case):
    return _answers("standard-feature", "medium")


def keep_current_route(case, backend_info):
    result = _empty_route(case, RULES["owner-bands"], backend_info)
    result["provenance"]["baseline_version"] = BASELINE_VERSION
    current_id = case["snapshot"].get("current_candidate_id")
    candidate = next((candidate for candidate in case["snapshot"]["candidates"]
                      if candidate["id"] == current_id), None)
    task_class = (candidate.get("task_classes") or [None])[0] if candidate else None
    if (candidate is None or task_class is None or case["mode"] == "experimentalOracle"
            or constraint_failures(case, candidate, task_class)):
        result["reasons"] = ["no-current"]
        return result
    result["routed_task_class"] = task_class
    result["routed_effort"] = _effort(candidate["lead"])
    return _assign(result, case, candidate, outcome="keep-current")
