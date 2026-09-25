#!/usr/bin/env python3
"""Calibrate pack gates using a stratified fit/holdout split.

Measures thresholds, tie widths, holdout accuracies, and Wilson score
confidence bounds on hand-labelled datasets.
"""
import argparse, hashlib, json, math, os, random, re, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spend_log import record as _record_spend

ENDPOINT = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai") + "/v1/systemone"

def api_key():
    k = os.environ.get("TYPESAFE_API_KEY")
    if k:
        return k
    path = os.path.expanduser("~/.config/typesafe/env.sh")
    try:
        m = re.search(r'^\s*export\s+TYPESAFE_API_KEY=["\']?([^"\'\s]+)', open(path).read(), re.M)
    except OSError:
        return None
    return m.group(1) if m else None

def wilson_lower_bound(k, n, z=1.96):
    """Wilson score interval lower bound for k successes in n trials at z (default 95%)."""
    if n == 0:
        return 0.0
    p = k / n
    denom = 1 + (z * z) / n
    center = p + (z * z) / (2 * n)
    spread = z * math.sqrt((p * (1 - p) + (z * z) / (4 * n)) / n)
    return max(0.0, (center - spread) / denom)

def questions_fingerprint(questions):
    """A stable hash of the question text, so a reworded question invalidates its cache.

    A score is an answer to a specific wording. Reusing a cached score after the
    question changed would silently calibrate the new gate on the old question.
    """
    canon = json.dumps(questions, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()[:16]

def load_cache(path, fingerprint):
    """Cached judgments for this dataset, or an empty dict if absent or stale."""
    try:
        blob = json.load(open(path))
    except (OSError, ValueError):
        return {}
    if blob.get("fingerprint") != fingerprint:
        return {}
    return blob.get("items", {})

def save_cache(path, fingerprint, model, items):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"fingerprint": fingerprint, "model": model, "items": items}, fh, indent=1)

def stratified_split(rows, seed=0):
    """Split rows into fit and holdout halves preserving the true/false label ratio."""
    rng = random.Random(seed)
    true_items = [r for r in rows if r["label"]]
    false_items = [r for r in rows if not r["label"]]
    rng.shuffle(true_items)
    rng.shuffle(false_items)

    n_true_fit = len(true_items) // 2
    n_false_fit = len(false_items) // 2

    fit = true_items[:n_true_fit] + false_items[:n_false_fit]
    holdout = true_items[n_true_fit:] + false_items[n_false_fit:]
    return fit, holdout

def judge_item(key, item, questions):
    """Submit one item to Jev systemone API with spend logging."""
    state = item["state"]
    body = json.dumps({"state": state, "model": "jev-latest", "questions": questions}).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                res = json.load(r)
                _record_spend("calibrate", res.get("model"), len(questions), res.get("usage"))
                return {"id": item["id"], "answers": res, "error": None}
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            return {"id": item["id"], "answers": None, "error": f"HTTP {e.code}"}
        except Exception as e:
            if attempt < 2:
                time.sleep(1)
                continue
            return {"id": item["id"], "answers": None, "error": type(e).__name__}
    return {"id": item["id"], "answers": None, "error": "unreachable"}

def extract_metric(answers, qname, qdef):
    """Extract numeric score or noul float from Jev response."""
    if not answers or "answers" not in answers:
        return None
    ans = answers["answers"].get(qname)
    if not ans or not isinstance(ans, dict):
        return None
    qtype = qdef.get("type")
    if qtype == "score":
        return ans.get("score")
    elif qtype == "noul":
        return ans.get("noul")
    return None

def sweep_threshold(items, extract_fn):
    """Sweep candidate thresholds in 0.01 steps over observed score range on items.

    Returns: (midpoint_threshold, tie_width, max_accuracy).
    """
    valid = []
    for item in items:
        val = extract_fn(item)
        if val is not None:
            valid.append((val, item["label"], item))
    if not valid:
        return None, 0.0, 0.0

    scores = [s for s, _, _ in valid]
    min_s = min(scores)
    max_s = max(scores)
    start = round(math.floor(min_s * 100) / 100, 2) - 0.05
    end = round(math.ceil(max_s * 100) / 100, 2) + 0.05
    steps = int(round((end - start) / 0.01))

    candidates = [round(start + i * 0.01, 2) for i in range(steps + 1)]
    accs = []
    n = len(valid)
    for t in candidates:
        correct = sum(1 for s, l, _ in valid if (s > t) == l)
        accs.append((t, correct / n))

    max_acc = max(a for _, a in accs)
    runs = []
    current_run = []
    for t, a in accs:
        if abs(a - max_acc) < 1e-9:
            current_run.append(t)
        else:
            if current_run:
                runs.append(current_run)
                current_run = []
    if current_run:
        runs.append(current_run)

    widest = max(runs, key=lambda r: (round(r[-1] - r[0], 4), len(r)))
    width = round(widest[-1] - widest[0], 4)
    midpoint = round((widest[0] + widest[-1]) / 2.0, 2)
    return midpoint, width, max_acc

def evaluate_threshold(items, threshold, extract_fn):
    """Evaluate a threshold on items and compute accuracy, Wilson bound, and disagreements."""
    disagreements = []
    correct = 0
    total = 0
    for item in items:
        val = extract_fn(item)
        if val is None:
            continue
        pred = (val > threshold)
        lbl = item["label"]
        total += 1
        if pred == lbl:
            correct += 1
        else:
            disagreements.append({
                "id": item["id"],
                "score": val,
                "predicted": pred,
                "label": lbl,
                "reason": item.get("label_reason", "")
            })
    acc = (correct / total) if total > 0 else 0.0
    w_lower = wilson_lower_bound(correct, total)
    return {
        "total": total,
        "correct": correct,
        "accuracy": acc,
        "wilson_lower": w_lower,
        "disagreements": disagreements
    }

def main():
    ap = argparse.ArgumentParser(description="Calibrate gates using stratified fit/holdout split.")
    ap.add_argument("dataset", nargs="?", default="data/merge-risk.jsonl", help="path to JSONL dataset")
    ap.add_argument("pack", nargs="?", default="packs/merge-risk.json", help="path to pack JSON")
    ap.add_argument("--seed", type=int, default=0, help="random seed for stratified split (default: 0)")
    ap.add_argument("--json", nargs="?", const="-", default=None, help="emit JSON output to stdout or file")
    ap.add_argument("--cache", default=None,
                    help="score cache path (default: the dataset path with .scores.json). "
                         "A cached judgment is reused, so re-splitting and re-fitting cost nothing.")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache and re-query every item")
    ap.add_argument("--max-workers", type=int, default=6, help="concurrent API workers")
    args = ap.parse_args()

    key = api_key()
    if not key:
        print("calibrate: no TYPESAFE_API_KEY found", file=sys.stderr)
        return 1

    if not os.path.exists(args.dataset):
        print(f"calibrate: dataset {args.dataset} not found", file=sys.stderr)
        return 1
    if not os.path.exists(args.pack):
        print(f"calibrate: pack {args.pack} not found", file=sys.stderr)
        return 1

    pack_data = json.load(open(args.pack))
    questions = pack_data.get("questions", {})

    rows = []
    with open(args.dataset) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    if len(rows) < 4:
        print(f"calibrate: dataset too small ({len(rows)} rows)", file=sys.stderr)
        return 1

    fit_rows, holdout_rows = stratified_split(rows, seed=args.seed)

    print(f"calibrate: {len(rows)} items loaded (fit: {len(fit_rows)}, holdout: {len(holdout_rows)})")
    print(f"calibrate: querying Jev API with {len(questions)} questions per item...")

    # Query Jev, but only for items whose judgment is not already cached. The dataset
    # is the expensive artifact; the scores are bought once and re-split for free.
    all_items = rows
    fingerprint = questions_fingerprint(questions)
    cache_path = args.cache or re.sub(r"\.jsonl$", "", args.dataset) + ".scores.json"
    cached = {} if args.refresh else load_cache(cache_path, fingerprint)
    results_by_id = {i: {"id": i, "answers": a, "error": None} for i, a in cached.items()}

    todo = [it for it in all_items if it["id"] not in results_by_id]
    print(f"calibrate: {len(all_items) - len(todo)} cached, {len(todo)} to query")
    if todo:
        with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
            futures = [pool.submit(judge_item, key, item, questions) for item in todo]
            for f in futures:
                res = f.result()
                results_by_id[res["id"]] = res
        fresh = {i: r["answers"] for i, r in results_by_id.items() if r.get("answers")}
        save_cache(cache_path, fingerprint, "jev-latest", fresh)
        print(f"calibrate: cached {len(fresh)} judgments to {cache_path}")

    # Check query errors
    errors = [res for res in results_by_id.values() if res["error"]]
    if errors:
        print(f"calibrate: {len(errors)} API calls failed! First error: {errors[0]['error']}", file=sys.stderr)
        if len(errors) == len(all_items):
            return 1

    # Attach responses
    for r in fit_rows:
        r["api_result"] = results_by_id.get(r["id"], {}).get("answers")
    for r in holdout_rows:
        r["api_result"] = results_by_id.get(r["id"], {}).get("answers")

    out_metrics = {}

    # Measure questions
    for qname, qdef in questions.items():
        if qname == "route":
            continue
        if qname == "irreversible_path":
            out_metrics[qname] = {
                "measured": False,
                "reason": "Corpus contains no irreversible operations (revert fully undoes all changes; no data deletion, migrations, credentials, or billing touched)."
            }
            continue

        extract_fn = lambda it, qn=qname, qd=qdef: extract_metric(it.get("api_result"), qn, qd)

        # Fit
        midpoint, width, fit_acc = sweep_threshold(fit_rows, extract_fn)
        if midpoint is None:
            out_metrics[qname] = {"measured": False, "reason": "No valid scores extracted from responses."}
            continue

        fit_eval = evaluate_threshold(fit_rows, midpoint, extract_fn)
        holdout_eval = evaluate_threshold(holdout_rows, midpoint, extract_fn)

        out_metrics[qname] = {
            "measured": True,
            "fit_threshold": midpoint,
            "tie_width": width,
            "fit_accuracy": fit_acc,
            "fit_counts": {
                "total": len(fit_rows),
                "true": sum(1 for r in fit_rows if r["label"]),
                "false": sum(1 for r in fit_rows if not r["label"])
            },
            "holdout_accuracy": holdout_eval["accuracy"],
            "holdout_wilson_lower": holdout_eval["wilson_lower"],
            "holdout_counts": {
                "total": len(holdout_rows),
                "true": sum(1 for r in holdout_rows if r["label"]),
                "false": sum(1 for r in holdout_rows if not r["label"])
            },
            "holdout_disagreements": holdout_eval["disagreements"],
            "fit_disagreements": fit_eval["disagreements"]
        }

    # Format human-readable output
    report_lines = []
    report_lines.append("\n================ CALIBRATION RESULTS ================")
    report_lines.append(f"Dataset: {args.dataset} ({len(rows)} items)")
    report_lines.append(f"Split: Fit={len(fit_rows)} (True={sum(1 for r in fit_rows if r['label'])}, False={sum(1 for r in fit_rows if not r['label'])}), Holdout={len(holdout_rows)} (True={sum(1 for r in holdout_rows if r['label'])}, False={sum(1 for r in holdout_rows if not r['label'])}), Seed={args.seed}")
    report_lines.append("-----------------------------------------------------")

    for qname, m in out_metrics.items():
        report_lines.append(f"Question: {qname}")
        if not m["measured"]:
            report_lines.append(f"  Status: UNMEASURED ({m['reason']})")
        else:
            report_lines.append(f"  Fit Threshold: {m['fit_threshold']:.2f} (tie width: {m['tie_width']:.2f}, fit accuracy: {m['fit_accuracy']*100:.1f}%)")
            report_lines.append(f"  Holdout Accuracy: {m['holdout_accuracy']*100:.1f}% ({m['holdout_counts']['total'] - len(m['holdout_disagreements'])}/{m['holdout_counts']['total']})")
            report_lines.append(f"  Holdout Wilson Lower (95%): {m['holdout_wilson_lower']:.4f} ({m['holdout_wilson_lower']*100:.1f}%)")
            if m["holdout_disagreements"]:
                report_lines.append(f"  Holdout Disagreements ({len(m['holdout_disagreements'])}):")
                for d in m["holdout_disagreements"]:
                    report_lines.append(f"    - {d['id']} (score: {d['score']:.2f}, pred: {d['predicted']}, label: {d['label']}): {d['reason']}")
            else:
                report_lines.append("  Holdout Disagreements: None (100% agreement)")
        report_lines.append("-----------------------------------------------------")

    readable_text = "\n".join(report_lines)
    print(readable_text)

    output_payload = {
        "dataset": args.dataset,
        "pack": args.pack,
        "seed": args.seed,
        "total_items": len(rows),
        "fit_count": len(fit_rows),
        "holdout_count": len(holdout_rows),
        "metrics": out_metrics
    }

    if args.json:
        json_str = json.dumps(output_payload, indent=2)
        if args.json == "-":
            print(json_str)
        else:
            with open(args.json, "w") as jf:
                jf.write(json_str + "\n")

    return 0

if __name__ == "__main__":
    sys.exit(main())
