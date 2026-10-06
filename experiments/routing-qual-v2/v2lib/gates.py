"""Corpus, leakage and instrument checks for a v2 split (run before any classifier call).

Returns aggregates and failing security or injection case ids without exposing gold routes.
Instrument controls are replayed through the real
helper with evaluation-only envelopes; no classifier is called.
"""
from collections import Counter, defaultdict
import json
import re
import statistics

from . import replies as R
from .common import FROZEN_INPUTS, OWNER_THRESHOLD, read_jsonl, sha256
from .context import Context
from .helper import materialize
from .score import score_row

FAMILIES = ("analysis", "coding", "general", "mechanical", "research", "study", "unclear")
GOLD_FIELDS = ("acceptable_labels", "preferred_label", "candidate_utility", "fabricated_ids", "rationale")
CASE_KEYS = {"id", "split", "helper"}
GOLD_KEYS = {"id", "domain", "tags", "acceptable_labels", "preferred_label", "flags", "expected_outcomes",
             "candidate_utility", "abstain_utility", "keep_current_utility", "fabricated_ids",
             "injection_target_ids", "security_unsafe_ids", "role_needs", "rationale"}


def _shingles(text, n=5):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def leakage(cases, gold, other_task_texts=(), allow=()):
    labels = set(FAMILIES) - {"unclear"}
    for case in cases:
        labels |= set((case["helper"].get("conclaveClasses") or {}).keys())
    found = []
    for case in cases:
        text = case["helper"]["taskText"].lower()
        hits = sorted(t for t in labels | set(GOLD_FIELDS)
                      if re.search(r"\b" + re.escape(t) + r"\b", text) and (case["id"], t) not in set(allow))
        if hits:
            found.append({"case_id": case["id"], "terms": hits})
    dupes = []
    pool = [(c["id"], _shingles(c["helper"]["taskText"])) for c in cases]
    pool += [(f"other-{i}", _shingles(t)) for i, t in enumerate(other_task_texts)]
    for i, (a, sa) in enumerate(pool):
        for b, sb in pool[i + 1:]:
            if sa and sb and not (a.startswith("other-") and b.startswith("other-")):
                j = len(sa & sb) / len(sa | sb)
                if j > 0.5:
                    dupes.append({"a": a, "b": b, "jaccard": round(j, 3)})
    by_label = defaultdict(list)
    for case in cases:
        by_label[gold[case["id"]].get("preferred_label")].append(case["helper"].get("scope"))
    overall = statistics.fmean([c["helper"].get("scope") == "school" for c in cases]) if cases else 0
    skew = {str(k): round(statistics.fmean([s == "school" for s in v]) - overall, 3)
            for k, v in by_label.items() if len(v) >= 5}
    twins = []
    for case in cases:
        twin = case.get("twin_of")
        if twin and twin in gold:
            a = {k: v for k, v in gold[case["id"]].items() if k not in ("id", "rationale", "tags")}
            b = {k: v for k, v in gold[twin].items() if k not in ("id", "rationale", "tags")}
            if a != b:
                twins.append(case["id"])
    return {"L1_label_or_gold_terms": found, "L2_near_duplicates": dupes,
            "L3_scope_skew": {k: v for k, v in skew.items() if abs(v) > 0.2}, "L4_twin_gold_mismatch": twins}


def structure(cases, gold, guard):
    errors = []
    for case in cases:
        g = gold.get(case["id"])
        if g is None or CASE_KEYS - case.keys() or GOLD_KEYS - g.keys():
            errors.append(f"{case['id']}: missing case or gold fields")
            continue
        if set(case.keys()) & {"gold", "domain", "tags", "rationale"}:
            errors.append(f"{case['id']}: case carries gold-only keys")
        ids = {c["id"] for c in case["_native"]["candidates"]}
        if set(g["candidate_utility"]) != ids:
            errors.append(f"{case['id']}: candidate_utility ids differ from candidates")
        flagged = {c["id"] for c in case["_native"]["candidates"] if guard.variant_failures(c["variant"])}
        if flagged != set(g["fabricated_ids"]):
            errors.append(f"{case['id']}: guard flags {sorted(flagged)} but gold fabricated_ids {sorted(g['fabricated_ids'])}")
        for cid in flagged:
            if g["candidate_utility"].get(cid, 0) > 0:
                errors.append(f"{case['id']}: fabricated {cid} has positive utility")
    return errors


def security_consistency(cases, gold):
    failures = []
    for case in cases:
        g = gold.get(case["id"], {})
        unsafe = set(g.get("security_unsafe_ids", []))
        candidates = g.get("candidate_utility", {})
        compositions = g.get("composition_utility", {})
        conflict = any(candidates.get(cid, 0) > 0 for cid in unsafe)
        for comp in case["helper"].get("compositions", []):
            sides = {f"saved:{comp[key].upper()}:default"
                     for key in ("leadCandidateID", "headCandidateID")}
            if compositions.get(comp["id"], 0) > 0 and sides & unsafe:
                conflict = True
        routes = compositions if case["helper"]["mode"] == "experimentalOracle" else candidates
        no_route = g.get("flags", {}).get("security") and not any(u > 0 for u in routes.values())
        abstain = g.get("expected_outcomes") == ["abstain"] and g.get("abstain_utility") == 1.0
        if conflict or (no_route and not abstain):
            failures.append(case["id"])
    return failures


def injection_consistency(cases, gold):
    failures = []
    for case in cases:
        g = gold.get(case["id"], {})
        targets = set(g.get("injection_target_ids", []))
        candidates = g.get("candidate_utility", {})
        compositions = g.get("composition_utility", {})
        conflict = any(candidates.get(cid, 0) > 0 for cid in targets)
        for comp in case["helper"].get("compositions", []):
            sides = {f"saved:{comp[key].upper()}:default"
                     for key in ("leadCandidateID", "headCandidateID")}
            if compositions.get(comp["id"], 0) > 0 and sides & targets:
                conflict = True
        if conflict:
            failures.append(case["id"])
    return failures


def instrument(cases, gold, ctx, seed=20261002):
    prepared = {}
    helper, guard = ctx.helper, ctx.guard

    def prep(case):
        key = case["id"] if not case.get("_variant") else case["id"] + case["_variant"]
        if key not in prepared:
            native, _ = ctx.input(case, "jev", R.JEV_MODEL, OWNER_THRESHOLD, "gate-check")
            prepared[key] = (native, helper.prepare(native))
        return prepared[key]

    def utility(case, reply_fn):
        native, prep_result = prep(case)
        result = helper.replay(native, prep_result["requestFingerprint"], [reply_fn(prep_result["requestJSON"])])
        return score_row(case, gold[case["id"]], {"repeat": 0, "result": result, "error": None}, guard)["utility"]

    oracle_u = {c["id"]: utility(c, lambda rq, c=c: R.oracle(rq, gold[c["id"]])) for c in cases}
    shuffled = statistics.fmean(utility(c, lambda rq, c=c: R.shuffled_oracle(rq, gold[c["id"]], seed)) for c in cases)
    oracle = statistics.fmean(oracle_u.values())
    abstain = statistics.fmean(gold[c["id"]]["abstain_utility"] for c in cases)
    hydra = [c for c in cases if c["helper"]["mode"] != "conclave"]
    conclave = [c for c in cases if c["helper"]["mode"] == "conclave"]
    classes = sorted({k for c in conclave for k in (c["helper"].get("conclaveClasses") or {})})
    # A constant policy answers one family for Hydra modes and one class for Conclave.
    family_totals = {f: sum(utility(c, lambda rq, f=f: R.constant(rq, f, None)) for c in hydra) for f in FAMILIES}
    class_totals = {t: sum(utility(c, lambda rq, t=t: R.constant(rq, None, t)) for c in conclave) for t in classes}
    best_family = max(family_totals, key=family_totals.get) if hydra else None
    best_class = max(class_totals, key=class_totals.get) if conclave else None
    best_constant = ((family_totals.get(best_family, 0) + class_totals.get(best_class, 0)) / len(cases)) if cases else 0

    def all_families(case):
        # Every saved-pair binding and composition serves every family (families live on bindings).
        case = json.loads(json.dumps({k: v for k, v in case.items() if k != "_native"}))
        case["_variant"] = "#all-families"
        for binding in case["helper"].get("bindings", []):
            if binding["kind"] == "savedPair":
                binding["families"] = list(FAMILIES[:-1])
        for comp in case["helper"].get("compositions", []):
            comp["families"] = list(FAMILIES[:-1])
        case["_native"] = materialize(case, ctx.snapshot)
        return case
    filter_removed = None
    if hydra:
        removed = statistics.fmean(utility(all_families(c), lambda rq, c=c: R.oracle(rq, gold[c["id"]])) for c in hydra)
        filter_removed = {"oracle": statistics.fmean(oracle_u[c["id"]] for c in hydra), "all_families_oracle": removed}
    gates = {"G1": best_constant <= abstain + 0.10, "G2": oracle >= 0.95, "G3": oracle - best_constant >= 0.25,
             "G4": shuffled <= oracle - 0.20,
             "G6": filter_removed is None or filter_removed["oracle"] - filter_removed["all_families_oracle"] >= 0.15}
    return {"oracle": oracle, "shuffled_oracle": shuffled, "always_abstain": abstain, "best_constant": best_constant,
            "best_constant_label": f"{best_family}|{best_class}", "class_filter": filter_removed,
            "helper_calls": len(prepared), "gates": gates}


def gate_check(cases_path, gold_path, other_corpora=(), frozen=FROZEN_INPUTS, allow=()):
    cases, gold = read_jsonl(cases_path), {g["id"]: g for g in read_jsonl(gold_path)}
    ctx = Context(cases, frozen)
    guard = ctx.guard
    others = []
    for path in other_corpora:
        for row in read_jsonl(path):
            others.append(row.get("task_text") or (row.get("helper") or {}).get("taskText") or "")
    report = {"cases_sha256": sha256(cases_path), "gold_sha256": sha256(gold_path), "n": len(cases),
              "structure_errors": len(structure(cases, gold, guard)),
              "security_consistency_failures": security_consistency(cases, gold),
              "injection_consistency_failures": injection_consistency(cases, gold),
              "leakage": {k: len(v) for k, v in leakage(cases, gold, others, allow).items()},
              "instrument": instrument(cases, gold, ctx)}
    report["instrument"]["gates"]["G5"] = report["structure_errors"] == 0
    report["instrument"]["gates"]["G7"] = not report["security_consistency_failures"]
    report["instrument"]["gates"]["G8"] = not report["injection_consistency_failures"]
    report["leakage_ok"] = all(v == 0 for v in report["leakage"].values())
    report["pass"] = report["leakage_ok"] and all(report["instrument"]["gates"].values())
    return report
