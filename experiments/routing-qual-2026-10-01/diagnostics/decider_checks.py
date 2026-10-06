"""Dev-only checks on the Decider dev-tuned jump (never reads held-out files).

Usage: python diagnostics/decider_checks.py RUN_DIR THRESHOLDS.json OUT.json [--permutation-calls N]

1. Leakage: class keys, effort labels or gold-only words appearing in the classifier state.
2. Parser/defaults: errors, exact-uniform distributions, repeated identical vectors.
3. Negative controls re-routed from stored answers under the frozen dev-tuned rule:
   shuffled class labels (per-case permutation), shuffled cases (answers from another
   case), class-blind (class probabilities replaced by the top class of a fixed label).
4. Candidate-filter shortcut: routed cases whose top class is unacceptable, and how many
   unacceptable top classes were turned into abstentions by the snapshot class filter.
5. Label mapping (optional, local calls): reverse the option order of every question and
   compare per-label probabilities with the stored answers.
"""
import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import policy  # noqa: E402
from questions import LABELS, QUESTIONS, build_request, build_state  # noqa: E402
from score import achieved_utility, check_route  # noqa: E402

SEED = 20261001


def read_jsonl(path):
    return [json.loads(line) for line in open(path) if line.strip()]


def mean(values):
    return sum(values) / len(values) if values else None


def route_utility(case, gold, answers, rule):
    route = policy.route(case, answers, rule, {"backend": "decider"})
    return route, achieved_utility(gold, route, check_route(case, route))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("thresholds", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--permutation-calls", type=int, default=0)
    args = parser.parse_args()

    cases = {c["id"]: c for c in read_jsonl(ROOT / "cases/dev.jsonl")}
    gold = {g["id"]: g for g in read_jsonl(ROOT / "cases/dev-gold.jsonl")}
    records = [r for r in read_jsonl(args.run_dir / "records.jsonl") if r["repeat"] == 0]
    t = json.loads(args.thresholds.read_text())
    rule = {"name": "dev-tuned", "act": t["act"], "flag": min(0.6, t["act"]), "effort_q": t["effort_q"]}
    report = {"run_dir": str(args.run_dir), "rule": rule, "n_cases": len(records)}

    # 1. Leakage scan of exactly what the classifier sees.
    leak_terms = set(policy.TASK_CLASSES) | {"preferred", "acceptable", "gold", "domain", "rationale"}
    leaks = []
    for cid, case in cases.items():
        text = json.dumps(build_state(case)).lower()
        found = sorted(term for term in leak_terms if term in text)
        if found:
            leaks.append({"case_id": cid, "terms": found,
                          "top_class_matches_term": None})
    report["leakage"] = {"cases_with_terms": len(leaks), "items": leaks}

    # 2. Parser failures and default-looking outputs.
    errors = [r["case_id"] for r in records if r["answers"] is None]
    uniform, vectors = [], {}
    for r in records:
        if not r["answers"]:
            continue
        for qid, answer in r["answers"].items():
            values = list(answer["probs"].values())
            if max(values) - min(values) < 1e-6:
                uniform.append([r["case_id"], qid])
        key = json.dumps(r["answers"]["task_class"]["probs"], sort_keys=True)
        vectors.setdefault(key, []).append(r["case_id"])
    report["parser"] = {"errors": errors, "uniform_distributions": uniform,
                        "repeated_class_vectors": [ids for ids in vectors.values() if len(ids) > 1]}

    usable = [r for r in records if r["answers"]]
    observed = [route_utility(cases[r["case_id"]], gold[r["case_id"]], r["answers"], rule)[1] for r in usable]

    # 3. Negative controls.
    rng = random.Random(SEED)
    shuffled_labels, shuffled_cases, class_blind = [], [], []
    others = [r["answers"] for r in usable]
    for index, r in enumerate(usable):
        case, g = cases[r["case_id"]], gold[r["case_id"]]
        answers = json.loads(json.dumps(r["answers"]))
        labels = list(answers["task_class"]["probs"])
        values = [answers["task_class"]["probs"][label] for label in labels]
        rng.shuffle(values)
        answers["task_class"]["probs"] = dict(zip(labels, values))
        shuffled_labels.append(route_utility(case, g, answers, rule)[1])
        donor = others[(index + 1 + rng.randrange(len(others) - 1)) % len(others)]
        shuffled_cases.append(route_utility(case, g, donor, rule)[1])
        blind = json.loads(json.dumps(r["answers"]))
        top = max(blind["task_class"]["probs"].values())
        rest = (1 - top) / (len(labels) - 1)
        blind["task_class"]["probs"] = {label: (top if label == "standard-feature" else rest) for label in labels}
        class_blind.append(route_utility(case, g, blind, rule)[1])
    report["controls"] = {"observed_mean_utility": mean(observed),
                          "shuffled_class_labels": mean(shuffled_labels),
                          "shuffled_cases": mean(shuffled_cases),
                          "class_blind_standard_feature": mean(class_blind),
                          "always_abstain": mean([gold[r["case_id"]]["abstain_utility"] for r in usable])}

    # 4. Candidate-filter shortcut.
    routed_wrong, filtered_wrong, top_wrong = [], [], 0
    for r in usable:
        case, g = cases[r["case_id"]], gold[r["case_id"]]
        probs = r["answers"]["task_class"]["probs"]
        top_class, top_p = max(probs.items(), key=lambda item: item[1])
        route = policy.route(case, r["answers"], rule, {})
        if top_class not in g["acceptable_task_classes"] and top_class != "unclear":
            top_wrong += 1
            if route["outcome"] in ("recommendation", "experimental-recommendation", "keep-current"):
                routed_wrong.append(r["case_id"])
            elif top_p >= rule["act"] and "no-eligible" in route["reasons"]:
                filtered_wrong.append(r["case_id"])
    report["candidate_filter"] = {"top_class_unacceptable": top_wrong,
                                  "routed_with_unacceptable_class": routed_wrong,
                                  "confident_wrong_rescued_by_class_filter": filtered_wrong}

    # 5. Label mapping under reversed option order (local Decider calls only).
    if args.permutation_calls:
        from adapters import decider
        adapter = decider.make_adapter({})
        deltas = []
        try:
            for r in usable[:args.permutation_calls]:
                request = build_request(cases[r["case_id"]])
                request["questions"] = {qid: {**q, "criteria": dict(reversed(list(q["criteria"].items())))}
                                        for qid, q in QUESTIONS.items()}
                result = adapter.classify(request)
                if not result["ok"]:
                    deltas.append({"case_id": r["case_id"], "error": result["error"]})
                    continue
                worst = max(abs(result["answers"][qid]["probs"][label] - r["answers"][qid]["probs"][label])
                            for qid in LABELS for label in LABELS[qid])
                same_top = all(max(result["answers"][qid]["probs"], key=result["answers"][qid]["probs"].get)
                               == max(r["answers"][qid]["probs"], key=r["answers"][qid]["probs"].get)
                               for qid in LABELS)
                deltas.append({"case_id": r["case_id"], "max_abs_prob_delta": worst, "same_top_labels": same_top})
        finally:
            adapter.close()
        report["label_order_reversal"] = deltas
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("leakage",)}, indent=1)[:4000])
    print("leakage cases:", report["leakage"]["cases_with_terms"])


if __name__ == "__main__":
    main()
