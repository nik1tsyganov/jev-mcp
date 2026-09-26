#!/usr/bin/env python3
"""Score decision-eval results against the cases' expected labels. Python 3.9, stdlib only.

python3 score.py results-jev.jsonl results-laya.jsonl --cases 'cases-*.jsonl' [--json out.json]
"""
import argparse
import glob
import json
import math
import os
import random
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
SEED = 20260926
THRESHOLDS = [round(0.30 + 0.05 * i, 2) for i in range(14)]  # 0.30 .. 0.95
TARGET_ACC, TARGET_COV = 0.90, 0.30


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def predict(q, a):
    """Return (predicted value comparable to expected, selected-label probability) or None."""
    if not isinstance(a, dict):
        return None
    probs = a.get("probabilities") if isinstance(a.get("probabilities"), dict) else {}
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    if q["type"] == "choice":
        c = a.get("choice")
        if not isinstance(c, str):
            return None
        return c, probs.get(c) if num(probs.get(c)) else None
    if q["type"] == "noul":
        p = a.get("noul")
        if not num(p):
            return None
        return p >= 0.5, max(p, 1 - p)
    if q["type"] == "score":
        s = a.get("score")
        if not num(s):
            return None
        vals = [v for v in probs.values() if num(v)]
        return int(round(s)), max(vals) if vals else None
    return None


def load_items(cases, results):
    """One item per (case, question) for one provider."""
    by_id = {r["id"]: r for r in results}
    items = []
    for c in cases:
        r = by_id.get(c["id"])
        answers = (r or {}).get("answers") or {}
        for qid, q in c["questions"].items():
            pred = predict(q, answers.get(qid)) if r and r.get("ok") else None
            items.append({
                "case": c["id"], "qid": qid, "source": c.get("source"), "category": c.get("category"),
                "difficulty": c.get("difficulty"), "code_computable": bool(c.get("code_computable")),
                "answered": pred is not None,
                "pred": pred[0] if pred else None,
                "prob": pred[1] if pred else None,
                "correct": (pred[0] == c["expected"].get(qid)) if pred else None,
            })
    return items


def acc(items):
    ans = [i for i in items if i["answered"]]
    return sum(i["correct"] for i in ans) / len(ans) if ans else None


def bootstrap_ci(items, n=1000, seed=SEED):
    """95% CI of accuracy over answered questions, resampling whole cases."""
    groups = defaultdict(list)
    for i in items:
        groups[i["case"]].append(i)
    keys = list(groups)
    if not keys:
        return None
    rng = random.Random(seed)
    stats = []
    for _ in range(n):
        sample = [x for k in rng.choices(keys, k=len(keys)) for x in groups[k]]
        a = acc(sample)
        if a is not None:
            stats.append(a)
    if not stats:
        return None
    stats.sort()
    return [stats[int(0.025 * len(stats))], stats[min(len(stats) - 1, int(0.975 * len(stats)))]]


def summary(items, results_by_case):
    cases = {i["case"] for i in items}
    return {
        "cases": len(cases), "questions": len(items),
        "answered": sum(i["answered"] for i in items),
        "coverage": sum(i["answered"] for i in items) / len(items) if items else None,
        "errors": sum(1 for c in cases if c in results_by_case and not results_by_case[c].get("ok")),
        "missing": sum(1 for c in cases if c not in results_by_case),
        "accuracy": acc(items), "ci95": bootstrap_ci(items),
    }


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def calibration(items):
    scored = [i for i in items if i["answered"] and i["prob"] is not None]
    bins = []
    ece = 0.0
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        inb = [i for i in scored if lo <= i["prob"] < hi or (b == 9 and i["prob"] == 1.0)]
        row = {"bin": f"{lo:.1f}-{hi:.1f}", "count": len(inb),
               "mean_prob": mean([i["prob"] for i in inb]), "accuracy": acc(inb)}
        if inb:
            ece += len(inb) / len(scored) * abs(row["accuracy"] - row["mean_prob"])
        bins.append(row)
    return {
        "bins": bins, "ece": ece if scored else None,
        "mean_prob_correct": mean([i["prob"] for i in scored if i["correct"]]),
        "mean_prob_wrong": mean([i["prob"] for i in scored if not i["correct"]]),
        "mean_prob_clear": mean([i["prob"] for i in scored if i["difficulty"] == "clear"]),
        "mean_prob_ambiguous": mean([i["prob"] for i in scored if i["difficulty"] == "ambiguous"]),
    }


def sweep(items):
    total = len(items)
    rows = []
    for t in THRESHOLDS:
        kept = [i for i in items if i["answered"] and i["prob"] is not None and i["prob"] >= t - 1e-9]
        rows.append({"threshold": t, "coverage": len(kept) / total if total else None, "accuracy": acc(kept)})
    return rows


def pick(rows):
    for r in rows:
        if r["accuracy"] is not None and r["accuracy"] >= TARGET_ACC and r["coverage"] >= TARGET_COV:
            return r["threshold"]
    return None


def threshold_report(items):
    rows = sweep(items)
    chosen = pick(rows)
    cases = sorted({i["case"] for i in items})
    rng = random.Random(SEED + 1)
    halves = []
    for _ in range(5):
        half = set(rng.sample(cases, max(1, len(cases) // 2))) if cases else set()
        sub = [i for i in items if i["case"] in half]
        sub_rows = sweep(sub)
        at = next((r for r in sub_rows if r["threshold"] == chosen), None)
        halves.append({
            "lowest_threshold": pick(sub_rows),
            "chosen_accuracy": at["accuracy"] if at else None,
            "chosen_coverage": at["coverage"] if at else None,
            "holds": bool(at and at["accuracy"] is not None and at["accuracy"] >= TARGET_ACC
                          and at["coverage"] >= TARGET_COV),
        })
    return {"sweep": rows, "lowest_threshold": chosen, "halves": halves,
            "stable": chosen is not None and all(h["holds"] for h in halves)}


def percentile(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[max(0, math.ceil(p * len(xs)) - 1)]  # nearest rank


def provider_report(items, results):
    by_case = {r["id"]: r for r in results}
    lat = [r["latency_ms"] for r in results if r.get("ok") and isinstance(r.get("latency_ms"), (int, float))]
    tokens = {"input_tokens": 0, "output_tokens": 0}
    for r in results:
        for k in tokens:
            tokens[k] += ((r.get("usage") or {}).get(k) or 0)
    out = {"overall": summary(items, by_case), "by": {}}
    for key in ("source", "category", "difficulty"):
        groups = defaultdict(list)
        for i in items:
            groups[str(i[key])].append(i)
        out["by"][key] = {g: summary(v, by_case) for g, v in sorted(groups.items())}
    out["calibration"] = calibration(items)
    out["threshold"] = threshold_report(items)
    out["latency_ms"] = {"p50": percentile(lat, 0.5), "p90": percentile(lat, 0.9), "max": max(lat) if lat else None}
    out["tokens"] = tokens
    return out


def agreement(a_items, b_items):
    b = {(i["case"], i["qid"]): i for i in b_items}
    both = [(i, b[(i["case"], i["qid"])]) for i in a_items
            if i["answered"] and (i["case"], i["qid"]) in b and b[(i["case"], i["qid"])]["answered"]]
    dis = [(x, y) for x, y in both if x["pred"] != y["pred"]]
    return {
        "both_answered": len(both),
        "agreement": (len(both) - len(dis)) / len(both) if both else None,
        "disagreements": len(dis),
        "accuracy_on_disagreement": [mean([x["correct"] for x, _ in dis]), mean([y["correct"] for _, y in dis])],
    }


def fmt(v, pct=False):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v * 100:.1f}%" if pct else f"{v:.3f}"
    return str(v)


def print_summary_row(label, s):
    ci = s["ci95"]
    ci_txt = f"[{ci[0] * 100:.1f},{ci[1] * 100:.1f}]" if ci else "-"
    print(f"  {label:<28} cases={s['cases']:<4} q={s['questions']:<4} acc={fmt(s['accuracy'], True):>6} "
          f"ci95={ci_txt:<13} cov={fmt(s['coverage'], True):>6} err={s['errors']} missing={s['missing']}")


def print_report(name, rep):
    print(f"\n=== {name} ===")
    print_summary_row("overall", rep["overall"])
    for key, groups in rep["by"].items():
        print(f" by {key}:")
        for g, s in groups.items():
            print_summary_row(g, s)
    cal = rep["calibration"]
    print(f" calibration (ECE={fmt(cal['ece'])}):")
    for b in cal["bins"]:
        if b["count"]:
            print(f"  {b['bin']}  n={b['count']:<4} mean_p={fmt(b['mean_prob'])} acc={fmt(b['accuracy'], True)}")
    print(f"  mean selected p: correct={fmt(cal['mean_prob_correct'])} wrong={fmt(cal['mean_prob_wrong'])} "
          f"clear={fmt(cal['mean_prob_clear'])} ambiguous={fmt(cal['mean_prob_ambiguous'])}")
    th = rep["threshold"]
    print(" threshold sweep (answers with selected p >= t):")
    for r in th["sweep"]:
        print(f"  t={r['threshold']:.2f} cov={fmt(r['coverage'], True):>6} acc={fmt(r['accuracy'], True):>6}")
    held = sum(h["holds"] for h in th["halves"])
    print(f"  lowest t with acc>={TARGET_ACC:.0%} and cov>={TARGET_COV:.0%}: {fmt(th['lowest_threshold'])} "
          f"(holds in {held}/5 bootstrap halves; stable={th['stable']})")
    lat = rep["latency_ms"]
    print(f" latency ms: p50={fmt(lat['p50'])} p90={fmt(lat['p90'])} max={fmt(lat['max'])}")
    if rep["tokens"]["input_tokens"] or rep["tokens"]["output_tokens"]:
        print(f" tokens: input={rep['tokens']['input_tokens']} output={rep['tokens']['output_tokens']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="+")
    ap.add_argument("--cases", default="cases-*.jsonl")
    ap.add_argument("--json")
    args = ap.parse_args()

    pattern = args.cases if os.path.isabs(args.cases) else os.path.join(HERE, args.cases)
    files = sorted(glob.glob(pattern)) or sorted(glob.glob(args.cases))
    if not files:
        raise SystemExit(f"no case files match {args.cases}")
    cases = [c for f in files for c in read_jsonl(f)]

    providers = {}
    for path in args.results:
        rows = read_jsonl(path)
        name = rows[0].get("provider") if rows else os.path.basename(path)
        providers[name] = rows

    report = {"case_files": [os.path.relpath(os.path.abspath(f), REPO_ROOT) for f in files], "providers": {}, "code_computable": {}, "agreement": {}}
    split = {False: [c for c in cases if not c.get("code_computable")], True: [c for c in cases if c.get("code_computable")]}
    items = {}
    for name, rows in providers.items():
        items[name] = load_items(split[False], rows)
        report["providers"][name] = provider_report(items[name], rows)
        cc = load_items(split[True], rows)
        report["code_computable"][name] = summary(cc, {r["id"]: r for r in rows}) if cc else None

    print(f"{len(cases)} cases from {len(files)} file(s); "
          f"{len(split[True])} code_computable cases reported separately.")
    for name, rep in report["providers"].items():
        print_report(name, rep)
    if split[True]:
        print("\n=== code_computable cases ===")
        for name, s in report["code_computable"].items():
            print_summary_row(name, s)

    names = list(items)
    for x in range(len(names)):
        for y in range(x + 1, len(names)):
            a, b = names[x], names[y]
            ag = agreement(items[a], items[b])
            report["agreement"][f"{a}~{b}"] = ag
            print(f"\n=== agreement {a} vs {b} ===")
            print(f"  both answered={ag['both_answered']} agreement={fmt(ag['agreement'], True)} "
                  f"disagreements={ag['disagreements']} acc on disagreement: "
                  f"{a}={fmt(ag['accuracy_on_disagreement'][0], True)} {b}={fmt(ag['accuracy_on_disagreement'][1], True)}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
