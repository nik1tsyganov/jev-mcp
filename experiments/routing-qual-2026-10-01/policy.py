"""Pure routing policy. Candidate snapshots, never task prose, constrain routes.

Candidate helper_count is the fixed configuration count, never shrunk: a saved
pair or seat binding above max_helpers fails C5. An experimental composition
uses the sum of its sides' counts, which must fit max_helpers. A lone current
experimental side cannot satisfy C10's complete-route rule.
"""

import json
import math
from copy import deepcopy
from datetime import date
from pathlib import Path

POLICY_VERSION = "routing-policy-v1.1"
CATALOG_VERSION = "routing-catalog-2026-10-01"
QUESTION_SET_VERSION = "routing-q-v1"
RULES = {"owner-bands": {"name": "owner-bands", "act": 0.8,
                         "flag": 0.6, "effort_q": 0.8}}
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max", "ultra")
TASK_CLASSES = (
    "planning", "standard-feature", "hard-risky", "security-sensitive",
    "bulk-mechanical", "parallel-slices", "debug-mystery", "tie-break",
    "long-context-analysis", "research-synthesis", "prose-writing", "ui-design",
    "tutoring-dispatch", "research-swarm",
)
ANSWER_LABELS = {
    "task_class": (*TASK_CLASSES, "unclear"),
    "effort": EFFORT_ORDER[:-1],
    "security_sensitive": ("yes", "no"),
    "injection": ("yes", "no"),
    "ambiguous": ("yes", "no"),
}


def load_catalog(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# v1.1 (dev phase, 2026-10-01): rank candidates by how many of the routed class's
# routing.json implement/fallback models they use, before the helper-count tie-break.
_CATALOG = load_catalog(Path(__file__).with_name("catalog.json"))


def _matrix_models(routed_class):
    entry = _CATALOG["classes"].get(routed_class, {})
    members = list(entry.get("implement") or []) + list(
        [entry["fallback"]] if isinstance(entry.get("fallback"), dict) else entry.get("fallback") or [])
    return {member.get("model") for member in members if isinstance(member, dict)}


def _matrix_matches(candidate, routed_class):
    models = _matrix_models(routed_class)
    used = [candidate.get("lead"), candidate.get("head"), *candidate.get("checkers", [])]
    return sum(1 for member in used if member and member.get("model") in models)


def _effort(member):
    value = member.get("effort")
    if member.get("provider") == "google":
        suffix = member.get("model", "").rsplit("-", 1)[-1]
        if suffix in ("low", "medium", "high"):
            return suffix
    return value.removeprefix("fused-") if isinstance(value, str) else value


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def constraint_failures(case, candidate, routed_class=None):
    """Return C1-C8 failures; C9 is fixed at construction and C10 wraps these.

    Class membership is C8 for each mode. With routed_class=None, membership
    and class-specific checker requirements are deferred to the route caller.
    """
    snapshot = case["snapshot"]
    failures = []
    if candidate not in snapshot["candidates"]:
        failures.append("C1")
    if candidate.get("available") is not True:
        failures.append("C2")
    members = [candidate.get("lead"), candidate.get("head")]
    members += candidate.get("checkers", [])
    if any(member and member.get("provider") in snapshot["unsupported_providers"]
           for member in members):
        failures.append("C3")
    try:
        age = (date.fromisoformat(snapshot["as_of"])
               - date.fromisoformat(candidate["evidence_date"])).days
        fresh = age <= snapshot["evidence_max_age_days"]
    except (ValueError, TypeError, KeyError):
        fresh = False
    if not fresh:
        failures.append("C4")
    if (not _count(snapshot["max_helpers"]) or not _count(candidate.get("helper_count"))
            or candidate["helper_count"] > snapshot["max_helpers"]):
        failures.append("C5")
    metadata = case.get("metadata", {})
    if ("context_tokens" in metadata
            and metadata["context_tokens"] > candidate.get("context_window_tokens", 0)):
        failures.append("C6")
    if not set(metadata.get("tools_needed", [])).issubset(candidate.get("tools", [])):
        failures.append("C7")
    mode = case["mode"]
    kind = candidate.get("kind")
    lead, head = candidate.get("lead"), candidate.get("head")
    checkers = candidate.get("checkers", [])
    if mode == "hydraOracle":
        valid_mode = (kind == "saved-pair" and candidate.get("qualified") is True
                      and bool(lead) and bool(head) and not checkers)
    elif mode == "experimentalOracle":
        valid_mode = (snapshot["experimental_opt_in"] is True and not checkers
                      and ((kind == "lead-side" and bool(lead) and head is None)
                           or (kind == "head-side" and lead is None and bool(head))))
    elif mode == "conclave":
        valid_mode = (kind == "seat-binding" and candidate.get("qualified") is True
                      and bool(lead))
        if routed_class in ("security-sensitive", "hard-risky"):
            other_providers = {checker.get("provider") for checker in checkers
                               if checker.get("provider") != (lead or {}).get("provider")}
            valid_mode = valid_mode and len(other_providers) >= 2
    else:
        valid_mode = False
    if routed_class is not None and routed_class not in candidate.get("task_classes", []):
        valid_mode = False
    if not valid_mode:
        failures.append("C8")
    return failures


def eligible(case, routed_class):
    ids, rejected = [], {}
    for candidate in case["snapshot"]["candidates"]:
        failures = constraint_failures(case, candidate, routed_class)
        if failures:
            rejected[candidate["id"]] = failures
        else:
            ids.append(candidate["id"])
    return ids, rejected


def _thresholds(rule):
    return {"act": rule["act"],
            "flag": min(0.6, rule["act"]) if rule["name"] == "dev-tuned" else rule["flag"],
            "effort_q": rule.get("effort_q", rule["act"])}


def _empty_route(case, rule, backend_info):
    return {
        "outcome": "abstain", "candidate_id": None, "lead": None, "heads": None,
        "checkers": [], "helper_count": 0, "mode": case["mode"],
        "routed_task_class": None, "routed_effort": None, "flag_suggestion": None,
        "reasons": [],
        "uncertainty": {"class_top_p": None, "class_margin": None,
                        "effort_quantile_p": None, "security_p": None,
                        "ambiguous_p": None, "calibrated": False},
        "provenance": {
            "backend": backend_info.get("backend"),
            "classifier_model": backend_info.get("classifier_model", backend_info.get("model")),
            "revision": backend_info.get("revision"),
            "question_set_version": QUESTION_SET_VERSION, "policy_version": POLICY_VERSION,
            "catalog_version": CATALOG_VERSION, "rule_name": rule["name"],
            "thresholds": _thresholds(rule),
        },
        "dispatch_authorized": False,
    }


def _valid_answers(answers):
    if not isinstance(answers, dict) or set(answers) != set(ANSWER_LABELS):
        return False
    for qid, labels in ANSWER_LABELS.items():
        answer = answers[qid]
        if not isinstance(answer, dict) or set(answer) != {"probs"}:
            return False
        probs = answer["probs"]
        if not isinstance(probs, dict) or set(probs) != set(labels):
            return False
        values = list(probs.values())
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            return False
        if abs(sum(values) - 1) > max(1e-3, 0.005 * len(values)):  # questions.sum_tolerance
            return False
    return True


def _member(member, role):
    if member is None:
        return None
    result = {"model": member["model"], "provider": member["provider"],
              "effort": _effort(member), "role": role}
    if role == "head":
        result["profile"] = member.get("profile")
    return result


def _assign(result, case, lead_candidate, head_candidate=None, outcome="recommendation"):
    head_source = head_candidate or lead_candidate
    result.update(
        outcome=outcome,
        candidate_id=(lead_candidate["id"] + "+" + head_candidate["id"]
                      if head_candidate else lead_candidate["id"]),
        lead=_member(lead_candidate.get("lead"), "lead"),
        heads=_member(head_source.get("head"), "head"),
        checkers=[_member(checker, checker["role"])
                  for checker in lead_candidate.get("checkers", [])],
        helper_count=(lead_candidate["helper_count"] + head_candidate["helper_count"]
                      if head_candidate else lead_candidate["helper_count"]),
    )
    return result


def _choose(candidates, needed, current_id, member_key, routed_class=None):
    ranked = [(candidate, EFFORT_ORDER.index(_effort(candidate[member_key])))
              for candidate in candidates
              if _effort(candidate.get(member_key) or {}) in EFFORT_ORDER]
    if not ranked:
        return None, False
    adequate = [(candidate, effort) for candidate, effort in ranked if effort >= needed]
    below = not adequate
    target = min(effort for _, effort in adequate) if adequate else max(effort for _, effort in ranked)
    choices = [candidate for candidate, effort in ranked if effort == target]
    return min(choices, key=lambda candidate: (candidate["id"] != current_id,
               -_matrix_matches(candidate, routed_class),
               candidate["helper_count"], candidate["id"])), below


def _has_complete_choice(case, candidates):
    if case["mode"] != "experimentalOracle":
        return bool(candidates)
    return (any(candidate["kind"] == "lead-side" for candidate in candidates)
            and any(candidate["kind"] == "head-side" for candidate in candidates))


def _recommend(case, result, security):
    routed_class = result["routed_task_class"]
    snapshot = case["snapshot"]
    if security and routed_class != "security-sensitive":
        result["reasons"].append("security-override")
        secure_ids, _ = eligible(case, "security-sensitive")
        secure = [candidate for candidate in snapshot["candidates"] if candidate["id"] in secure_ids]
        if not _has_complete_choice(case, secure):
            result["reasons"].append("security-no-candidate")
            return result
        routed_class = result["routed_task_class"] = "security-sensitive"
    ids, _ = eligible(case, routed_class)
    candidates = [candidate for candidate in snapshot["candidates"] if candidate["id"] in ids]
    needed = EFFORT_ORDER.index(result["routed_effort"])
    current_id = snapshot.get("current_candidate_id")
    if case["mode"] == "experimentalOracle":
        lead, lead_below = _choose([c for c in candidates if c["kind"] == "lead-side"],
                                  needed, current_id, "lead", routed_class)
        head, head_below = _choose([c for c in candidates if c["kind"] == "head-side"],
                                  needed, current_id, "head", routed_class)
        if (lead is not None and head is not None
                and lead["helper_count"] + head["helper_count"] <= snapshot["max_helpers"]):
            if lead_below or head_below:
                result["reasons"].append("effort-below-need")
            return _assign(result, case, lead, head, "experimental-recommendation")
    else:
        candidate, below = _choose(candidates, needed, current_id, "lead", routed_class)
        if candidate is not None:
            if below:
                result["reasons"].append("effort-below-need")
            return _assign(result, case, candidate)
        current = next((c for c in snapshot["candidates"] if c["id"] == current_id), None)
        if current is not None and not constraint_failures(case, current, routed_class):
            return _assign(result, case, current, outcome="keep-current")
    result["reasons"].append("no-eligible")
    return result


def route(case, answers, rule, backend_info):
    result = _empty_route(case, rule, backend_info)
    if not _valid_answers(answers):
        result["reasons"].append("backend-invalid")
        return result
    probs = {qid: answer["probs"] for qid, answer in answers.items()}
    thresholds = result["provenance"]["thresholds"]
    ordered = sorted(probs["task_class"].items(), key=lambda item: (-item[1], item[0]))
    top_class, top_p = ordered[0]
    result["uncertainty"].update(class_top_p=top_p, class_margin=top_p - ordered[1][1],
                                 effort_quantile_p=thresholds["effort_q"],
                                 security_p=probs["security_sensitive"]["yes"],
                                 ambiguous_p=probs["ambiguous"]["yes"])
    injection = probs["injection"]["yes"] >= 0.5
    if probs["ambiguous"]["yes"] >= thresholds["act"]:
        result["reasons"].append("ambiguous")
    elif top_class == "unclear" or top_p < thresholds["flag"]:
        result["reasons"].append("low-confidence")
    else:
        result["routed_task_class"] = top_class
        cumulative = 0.0
        result["routed_effort"] = "max"
        for effort in ANSWER_LABELS["effort"]:
            cumulative += probs["effort"][effort]
            if cumulative >= thresholds["effort_q"]:
                result["routed_effort"] = effort
                break
        if top_p < thresholds["act"]:
            suggestion = _recommend(case, deepcopy(result), probs["security_sensitive"]["yes"] >= 0.5)
            if injection:
                suggestion["reasons"].append("injection-suspected")
            result["flag_suggestion"] = suggestion
            result["reasons"].append("flag")
        else:
            result = _recommend(case, result, probs["security_sensitive"]["yes"] >= 0.5)
    if injection:
        result["reasons"].append("injection-suspected")
    return result


def route_from_error(case, error, rule, backend_info):
    result = _empty_route(case, rule, backend_info)
    result["outcome"] = "backend-unavailable"
    result["reasons"] = [error]
    return result
