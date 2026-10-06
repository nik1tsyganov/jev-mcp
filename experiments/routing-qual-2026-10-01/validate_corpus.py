"""Structural checks for case and gold files before any classifier run.

Usage: python validate_corpus.py CASES.jsonl GOLD.jsonl
Prints counts and every inconsistency; exits 1 when an error is found.
Gold eligibility is compared with policy.constraint_failures (C2-C7 plus the
mode part of C8 without class membership), so a gold label that marks an
eligible candidate ineligible, or gives positive utility to an ineligible one,
is reported.
"""
import json
import sys
from collections import Counter

import policy
from questions import LABELS

CASE_KEYS = {"id", "split", "mode", "task_text", "metadata", "snapshot"}
GOLD_KEYS = {"id", "domain", "tags", "context_band", "acceptable_task_classes",
             "preferred_task_class", "acceptable_efforts", "preferred_effort", "flags",
             "expected_outcomes", "candidate_utility", "ineligible", "abstain_utility",
             "keep_current_utility", "rationale"}
FORBIDDEN_IN_CASE = {"domain", "tags", "gold", "rationale", "expected_outcomes", "candidate_utility"}


def read(path):
    with open(path) as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main(case_path, gold_path):
    cases, gold = read(case_path), {row["id"]: row for row in read(gold_path)}
    errors, warnings = [], []
    counts = Counter()
    for case in cases:
        cid = case["id"]
        g = gold.get(cid)
        if g is None:
            errors.append(f"{cid}: no gold")
            continue
        if missing := CASE_KEYS - case.keys():
            errors.append(f"{cid}: case missing {sorted(missing)}")
        if leaked := FORBIDDEN_IN_CASE & case.keys():
            errors.append(f"{cid}: case carries gold-only keys {sorted(leaked)}")
        if missing := GOLD_KEYS - g.keys():
            errors.append(f"{cid}: gold missing {sorted(missing)}")
            continue
        for label in g["acceptable_task_classes"]:
            if label not in LABELS["task_class"]:
                errors.append(f"{cid}: unknown class {label}")
        for label in g["acceptable_efforts"]:
            if label not in (*LABELS["effort"], "ultra"):
                errors.append(f"{cid}: unknown effort {label}")
        if g["preferred_task_class"] and g["preferred_task_class"] not in g["acceptable_task_classes"]:
            errors.append(f"{cid}: preferred class not acceptable")
        if g["preferred_effort"] and g["preferred_effort"] not in g["acceptable_efforts"]:
            errors.append(f"{cid}: preferred effort not acceptable")
        ids = {c["id"] for c in case["snapshot"]["candidates"]}
        if set(g["candidate_utility"]) != ids:
            errors.append(f"{cid}: candidate_utility ids differ from snapshot")
        current = case["snapshot"].get("current_candidate_id")
        if current is not None and current not in ids:
            errors.append(f"{cid}: current_candidate_id not in snapshot")
        for cand in case["snapshot"]["candidates"]:
            fails = policy.constraint_failures(case, cand, None)
            marked = cand["id"] in g["ineligible"]
            util = g["candidate_utility"].get(cand["id"], 0)
            if fails and util > 0:
                errors.append(f"{cid}/{cand['id']}: utility {util} but fails {fails}")
            if fails and not marked:
                warnings.append(f"{cid}/{cand['id']}: fails {fails} but not marked ineligible")
            if marked and not fails:
                warnings.append(f"{cid}/{cand['id']}: marked ineligible ({g['ineligible'][cand['id']]}) but passes C2-C8 mode checks")
        if current is not None and g["keep_current_utility"] > 0:
            cur = next(c for c in case["snapshot"]["candidates"] if c["id"] == current)
            if policy.constraint_failures(case, cur, None):
                errors.append(f"{cid}: keep_current_utility > 0 but current candidate is ineligible")
        if case["mode"] == "experimentalOracle":
            for key, util in g.get("composition_utility", {}).items():
                parts = key.split("+")
                if len(parts) != 2 or any(p not in ids for p in parts):
                    errors.append(f"{cid}: bad composition key {key}")
        if case.get("twin_of"):
            twin = case["twin_of"]
            tg = gold.get(twin)
            if tg is None:
                errors.append(f"{cid}: twin {twin} missing")
            else:
                same = {k: g[k] for k in GOLD_KEYS - {"id", "rationale", "tags"}} == \
                       {k: tg[k] for k in GOLD_KEYS - {"id", "rationale", "tags"}}
                if not same:
                    warnings.append(f"{cid}: twin gold differs from {twin}")
        counts[f"domain:{g['domain']}"] += 1
        counts[f"mode:{case['mode']}"] += 1
        counts[f"band:{g['context_band']}"] += 1
        counts[f"effort:{g['preferred_effort']}"] += 1
        for tag in g["tags"]:
            counts[f"tag:{tag}"] += 1
        counts["abstain_required"] += g["abstain_utility"] >= 1.0
        counts["excerpt"] += "context_excerpt" in case.get("metadata", {})
    extra = set(gold) - {c["id"] for c in cases}
    if extra:
        errors.append(f"gold without case: {sorted(extra)}")
    for key in sorted(counts):
        print(f"{key}\t{counts[key]}")
    print(f"warnings {len(warnings)}")
    for item in warnings:
        print("WARN", item)
    print(f"errors {len(errors)}")
    for item in errors:
        print("ERROR", item)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
