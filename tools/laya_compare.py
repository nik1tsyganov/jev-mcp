#!/usr/bin/env python3
"""Compare Jev, upstream Laya, and laya-mlx on one shared corpus.

This harness prepares an executable comparison and makes no network or model
call unless `--live` is given. A missing local runtime produces an explicit
NOT RUN result for that provider; a provider or checkpoint is never silently
substituted.

Providers:
  jev              TypeSafe System One HTTP API (the existing credential path)
  upstream-laya    `import laya`, a fixed checkpoint via laya.load(...)
  upstream-router  `from laya import Router`, a distinct routed configuration
  laya-mlx         `import laya_mlx`, a fixed checkpoint on Apple silicon

Real signatures (read from upstream source 2026-09-21):
  laya.load(model_id_or_path="convaiinnovations/laya", device=None, token=None,
            subfolder=None) -> Agent
  laya.Agent.system_one(state, questions)  # alias predict
  laya.Router(models=None, device=None, ..., preload=False)
  laya.Router.predict(state, questions, model=None, task=None, lang=None)
  laya_mlx.load(model_id_or_path, device=None, token=None, subfolder=None,
                revision=None, dtype=None, batch_size=None, ...)
  laya_mlx.Agent.system_one(state, questions)  # alias predict
Both Laya runtimes return {"model", "answers", "usage"}; the Router payload
adds "routing". Jev returns {"model", "answers", "usage"}.

The method, the adoption rule and the run commands are in
docs/laya-comparison-protocol.md.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spend_log import record as record_spend  # noqa: E402

try:
    from calibrate import api_key as _resolve_api_key  # reuse the existing credential path
except Exception:  # pragma: no cover - fallback keeps the harness runnable
    def _resolve_api_key():
        import re
        k = os.environ.get("TYPESAFE_API_KEY")
        if k:
            return k
        path = os.path.expanduser("~/.config/typesafe/env.sh")
        try:
            m = re.search(r'^\s*export\s+TYPESAFE_API_KEY=["\']?([^"\'\s]+)', open(path).read(), re.M)
        except OSError:
            return None
        return m.group(1) if m else None

ENDPOINT = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/") + "/v1/systemone"

PROVIDERS = {
    "jev": {"kind": "jev", "module": None, "mode": "http"},
    "upstream-laya": {"kind": "laya", "module": "laya", "mode": "direct",
                      "subfolder": True},
    "upstream-router": {"kind": "laya", "module": "laya", "mode": "router"},
    "laya-mlx": {"kind": "laya_mlx", "module": "laya_mlx", "mode": "direct",
                 "subfolder": True, "revision": True, "dtype": True, "batch_size": True},
}
DEFAULT_CHECKPOINT = {
    "jev": "jev-latest",
    "upstream-laya": "convaiinnovations/laya",
    "upstream-router": "english",
    "laya-mlx": "aac6fef/laya-mlx",
}
PRIMITIVES = ("choice", "noul", "score")

# Preregistered adoption margins. See docs/laya-comparison-protocol.md.
ACC_MARGIN = 0.02          # overall noninferiority margin
GROUP_ACC_MARGIN = 0.05    # per critical group
BRIER_MARGIN = 0.02        # no material Brier regression
MAE_MARGIN = 0.10          # no material score-MAE regression
DEFAULT_MIN_N = 30         # below this a primitive is INCONCLUSIVE


# --------------------------------------------------------------------------- util

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact_error(text, key):
    """Strip the credential and any bearer token before a failure is stored.

    An error path is the classic leak: a proxy or HTTP client can echo the
    request header into the message. Nothing stored may carry the key.
    """
    out = str(text)
    if key and len(key) > 4:
        out = "[redacted]".join(out.split(key))
    return re.sub(r"Bearer\s+\S+", "Bearer [redacted]", out)


def percentile(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] * (hi - k) + s[hi] * (k - lo)


def ece(pairs, bins=10):
    """Expected calibration error over (probability, correct) pairs.

    Binning is explicit and equal-width; every bin reports its sample count so
    a thin tail cannot hide behind the summary number.
    """
    n = len(pairs)
    if n == 0:
        return {"n": 0, "bins": bins, "ece": None, "bin_detail": []}
    detail = []
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        members = [(p, c) for p, c in pairs if min(int(p * bins), bins - 1) == b]
        if not members:
            detail.append({"bin": b, "lo": lo, "hi": hi, "n": 0})
            continue
        acc = sum(1 for _, c in members if c) / len(members)
        conf = sum(p for p, _ in members) / len(members)
        detail.append({"bin": b, "lo": lo, "hi": hi, "n": len(members),
                       "accuracy": acc, "confidence": conf, "gap": abs(acc - conf)})
        total += (len(members) / n) * abs(acc - conf)
    return {"n": n, "bins": bins, "ece": total, "bin_detail": detail}


def paired_bootstrap(ref_vals, cand_vals, seed, reps=2000, alpha=0.05):
    """Deterministic paired bootstrap CI for the mean per-case difference."""
    n = len(ref_vals)
    if n == 0:
        return None
    diffs = [c - r for r, c in zip(ref_vals, cand_vals)]
    rng = random.Random(seed)
    means = []
    for _ in range(reps):
        s = 0.0
        for _ in range(n):
            s += diffs[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[max(0, int((alpha / 2) * reps))]
    hi = means[min(reps - 1, int((1 - alpha / 2) * reps) - 1)]
    return {"n": n, "mean_diff": sum(diffs) / n, "ci95": [lo, hi]}


# ----------------------------------------------------------------------- runtime

def sync_accelerator(kind):
    """Block until queued accelerator work finishes, so timing measures work."""
    if kind == "laya":
        import torch
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        elif torch.backends.mps.is_available():
            torch.mps.synchronize()
    elif kind == "laya_mlx":
        import mlx.core as mx
        mx.synchronize()


class JevProvider:
    kind = "jev"

    def __init__(self, args):
        self.key = _resolve_api_key()
        if not self.key:
            raise RuntimeError("no TYPESAFE_API_KEY found (env or ~/.config/typesafe/env.sh)")
        self.model = args.checkpoint
        self.resolved_model = None
        self.requests = 0

    def predict(self, state, questions):
        body = json.dumps({"state": state, "model": self.model, "questions": questions}).encode()
        req = urllib.request.Request(
            ENDPOINT, data=body,
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        # One attempt only: a retry here would make the printed request count a lie.
        self.requests += 1
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.load(r)
        except Exception:
            record_spend("laya-compare", self.model, len(questions), None)
            raise
        self.resolved_model = res.get("model") or self.resolved_model
        record_spend("laya-compare", res.get("model"), len(questions), res.get("usage"))
        return res


class LocalProvider:
    def __init__(self, provider, args):
        spec = PROVIDERS[provider]
        self.kind = spec["kind"]
        self.mode = spec["mode"]
        mod = __import__(spec["module"])
        self.mod = mod
        self.resolved_model = args.checkpoint
        if self.mode == "router":
            if args.revision:
                raise ValueError("Router revision pinning requires explicit local model paths")
            self.router = mod.Router(device=args.device) if args.device else mod.Router()
            self.router_model = args.router_model
        else:
            kwargs = {}
            checkpoint = args.checkpoint
            if provider == "upstream-laya" and args.revision:
                from huggingface_hub import snapshot_download
                prefix = args.subfolder.rstrip('/') + '/' if args.subfolder else ''
                checkpoint = snapshot_download(args.checkpoint, revision=args.revision,
                    allow_patterns=[prefix + p for p in ('model.safetensors',
                        'rl_agent_config.json', 'encoder/*', 'tokenizer/*')])
            if args.device:
                kwargs["device"] = args.device
            if spec.get("subfolder") and args.subfolder:
                kwargs["subfolder"] = args.subfolder
            if spec.get("revision") and args.revision:
                kwargs["revision"] = args.revision
            if spec.get("dtype") and args.dtype:
                kwargs["dtype"] = args.dtype
            if spec.get("batch_size") and args.batch_size:
                kwargs["batch_size"] = args.batch_size
            self.agent = mod.load(checkpoint, **kwargs)
            self.resolved_model = str(getattr(self.agent, 'model_dir', checkpoint))
            self.actual_device = str(getattr(self.agent, 'device', 'unknown'))
            self.actual_dtype = str(getattr(self.agent, 'dtype', 'unknown'))
            if args.device and args.device not in self.actual_device:
                raise RuntimeError(f'Requested {args.device}, runtime selected {self.actual_device}')

    def predict(self, state, questions):
        if self.mode == "router":
            return self.router.predict(state, questions, model=self.router_model)
        return self.agent.predict(state, questions)


def build_provider(provider, args):
    if provider == "jev":
        return JevProvider(args)
    return LocalProvider(provider, args)


# -------------------------------------------------------------------------- cases

def load_cases(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    validate_cases(rows)
    return rows


def validate_cases(rows):
    seen = set()
    for r in rows:
        for key in ("id", "group", "split", "state", "questions", "expected"):
            if key not in r:
                raise ValueError(f"case {r.get('id')!r} missing required key {key!r}")
        if r["id"] in seen:
            raise ValueError(f"duplicate case id {r['id']!r}")
        seen.add(r["id"])
        if not isinstance(r["questions"], dict) or not r["questions"]:
            raise ValueError(f"case {r['id']!r} needs a non-empty questions object")
        if len(r['questions']) != 1:
            raise ValueError('The accuracy corpus requires one scored question per case')
        for qid, q in r["questions"].items():
            if q.get("type") not in PRIMITIVES:
                raise ValueError(f"case {r['id']!r} question {qid!r} has unknown type {q.get('type')!r}")
            if qid not in r["expected"]:
                raise ValueError(f"case {r['id']!r} has no expected answer for {qid!r}")


def adapt_dataset(dataset_path, pack_path, question_id=None):
    """Adapter for an existing hand-labelled local dataset.

    Only `noul` questions are compatible: their label is a boolean, so the
    hand label maps directly to the expected answer. Other primitives need a
    label in their own output space and are skipped. Provenance from the row
    (labelled_by, date, label_reason) is preserved; these cases carry
    origin='adapter' and must stay separate from the synthetic corpus.
    """
    with open(pack_path, encoding="utf-8") as f:
        pack = json.load(f)
    questions = pack.get("questions", {})
    # A boolean label describes one proposition, not every noul in a pack.
    if Path(dataset_path).name != 'merge-risk.jsonl' or question_id != 'behaviour_change':
        raise ValueError('Only merge-risk.jsonl -> behaviour_change has an established label mapping')
    noul_ids = [qid for qid, q in questions.items() if q.get("type") == "noul"]
    if question_id:
        if question_id not in noul_ids:
            raise ValueError(f"{question_id!r} is not a noul question in {pack_path}")
        noul_ids = [question_id]
    cases = []
    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row.get("label"), bool):
                continue
            for qid in noul_ids:
                cases.append({
                    "id": f"{row['id']}::{qid}",
                    "group": f"adapter:{pack.get('name', os.path.basename(pack_path))}",
                    "split": "adapter",
                    "origin": "adapter",
                    "state": row["state"],
                    "questions": {qid: questions[qid]},
                    "expected": {qid: row["label"]},
                    "label_source": row.get("labelled_by", "hand"),
                    "label_reason": row.get("label_reason"),
                    "label_date": row.get("date"),
                    "dataset": str(dataset_path),
                })
    return cases


# ---------------------------------------------------------------------- run one

def extract(case, answer):
    """Return (prediction, schema_ok) for the case's single primitive."""
    qid = next(iter(case["questions"]))
    prim = case["questions"][qid]["type"]
    if not isinstance(answer, dict) or not isinstance(answer.get("answers"), dict):
        return None, False
    if not isinstance(answer.get('model'), str) or not isinstance(answer.get('usage'), dict):
        return None, False
    if any(not isinstance(answer['usage'].get(k), int) or isinstance(answer['usage'].get(k), bool)
           or answer['usage'][k] < 0 for k in ('input_tokens', 'output_tokens')):
        return None, False
    a = answer["answers"].get(qid)
    if not isinstance(a, dict) or a.get('type') != prim:
        return None, False
    def number(x, low=0, high=1):
        return (isinstance(x, (int, float)) and not isinstance(x, bool)
                and math.isfinite(x) and low <= x <= high)
    if prim in ('choice', 'score'):
        criteria = case['questions'][qid]['criteria']
        labels = set(criteria) if prim == 'choice' else {str(i) for i in range(len(criteria))}
        probs = a.get('probabilities')
        if (not number(a.get('confidence')) or not isinstance(probs, dict) or set(probs) != labels
                or not all(number(p) for p in probs.values())
                or abs(sum(probs.values()) - 1) > max(0.001, len(labels) * 0.000051)):
            return None, False
    if prim == "choice":
        ok = a.get('choice') in labels
        return a.get("choice"), ok
    if prim == "noul":
        p = a.get("noul")
        ok = number(p)
        return (float(p) if ok else None), ok
    if prim == "score":
        s = a.get("score")
        ok = number(s, high=len(criteria) - 1) and isinstance(a.get('legend'), dict)
        return (float(s) if ok else None), ok
    return None, False


def run_case(prov, case, args):
    qid = next(iter(case["questions"]))
    prim = case["questions"][qid]["type"]
    state, questions = case["state"], case["questions"]
    input_hash = sha256_hex(canonical({"state": state, "questions": questions}))
    latencies = []
    answer = None
    error = None
    samples = []
    first_call = None
    for i in range(args.warmup + args.repetitions):
        t0 = time.perf_counter()
        try:
            sync_accelerator(prov.kind)
            res = prov.predict(state, questions)
            sync_accelerator(prov.kind)
        except Exception as e:  # noqa: BLE001 - every failure is recorded, never dropped
            error = redact_error(f"{type(e).__name__}: {e}", getattr(prov, "key", None))
            break
        dt = time.perf_counter() - t0
        if i == 0:
            answer = res
            first_call = dt
        samples.append({'warmup': i < args.warmup, 'seconds': dt, 'answer': res,
                        'schema_ok': extract(case, res)[1]})
        if i >= args.warmup:
            latencies.append(dt)
    prediction, schema_ok = extract(case, answer)
    usage = answer.get("usage") if isinstance(answer, dict) else None
    return {
        "case_id": case["id"],
        "group": case["group"],
        "origin": case.get("origin", "synthetic"),
        "split": case['split'],
        "primitive": prim,
        "question_id": qid,
        "input_hash": input_hash,
        "ok": error is None,
        "error": error,
        "schema_ok": schema_ok and all(s['schema_ok'] for s in samples) if error is None else False,
        "prediction": prediction,
        "expected": case["expected"][qid],
        "latency_samples": latencies,
        "warm_p50": percentile(latencies, 0.5),
        "warm_p95": percentile(latencies, 0.95),
        "usage": usage,
        "raw_answer": answer,
        "first_call_seconds": first_call,
        "samples": samples,
    }


# ---------------------------------------------------------------------- metrics

def primitive_metrics(recs, bins=10):
    out = {}
    for prim in PRIMITIVES:
        rs = [r for r in recs if r["primitive"] == prim]
        valid = [r for r in rs if r["ok"] and r["schema_ok"] and r["prediction"] is not None]
        m = {"n": len(valid), "attempted": len(rs)}
        if prim == "choice":
            correct = sum(1 for r in valid if r["prediction"] == r["expected"])
            m.update(correct=correct, accuracy=(correct / len(rs)) if rs else None)
            pairs = [(float(r["raw_answer"]["answers"][r["question_id"]]['probabilities'][r['prediction']]),
                      1 if r["prediction"] == r["expected"] else 0) for r in valid]
            m["ece"] = ece(pairs, bins)
        elif prim == "noul":
            correct = sum(1 for r in valid if (r["prediction"] > 0.5) == bool(r["expected"]))
            brier = sum((r["prediction"] - (1.0 if r["expected"] else 0.0)) ** 2 for r in valid)
            m.update(correct=correct, accuracy=(correct / len(rs)) if rs else None,
                     brier=(brier / len(valid)) if valid else None)
            m["ece"] = ece([(r["prediction"], 1 if r["expected"] else 0) for r in valid], bins)
        elif prim == "score":
            mae = sum(abs(r["prediction"] - float(r["expected"])) for r in valid)
            m["mae"] = (mae / len(valid)) if valid else None
            pairs = []
            for r in valid:
                probs = r['raw_answer']['answers'][r['question_id']]['probabilities']
                selected = max(probs, key=probs.get)
                pairs.append((probs[selected], int(selected) == r['expected']))
            m["ece"] = ece(pairs, bins)
        out[prim] = m
    return out


def compute_metrics(recs, bins=10):
    metrics = {"primitives": primitive_metrics(recs, bins)}
    errors = [r for r in recs if not r["ok"]]
    schema_bad = [r for r in recs if r["ok"] and not r["schema_ok"]]
    metrics["error_rate"] = (len(errors) / len(recs)) if recs else None
    metrics["errors"] = len(errors)
    metrics["schema_incompatibilities"] = len(schema_bad)
    metrics["schema_incompatible_ids"] = [r["case_id"] for r in schema_bad]
    lat = [x for r in recs for x in r["latency_samples"]]
    metrics["latency"] = {"samples": len(lat),
                          "p50": percentile(lat, 0.5),
                          "p95": percentile(lat, 0.95)}
    groups = {}
    for g in sorted({r["group"] for r in recs}):
        groups[g] = primitive_metrics([r for r in recs if r["group"] == g], bins)
    metrics["per_group"] = groups
    return metrics


def per_case_values(recs, prim, metric):
    """Per-case value for a paired comparison. Accuracy=1/0, brier/mae lower-better."""
    vals = {}
    for r in recs:
        if r["primitive"] != prim or not r["ok"] or not r["schema_ok"] or r["prediction"] is None:
            continue
        if metric == "accuracy":
            if prim == "choice":
                vals[r["case_id"]] = 1.0 if r["prediction"] == r["expected"] else 0.0
            elif prim == "noul":
                vals[r["case_id"]] = 1.0 if (r["prediction"] > 0.5) == bool(r["expected"]) else 0.0
        elif metric == "brier" and prim == "noul":
            vals[r["case_id"]] = (r["prediction"] - (1.0 if r["expected"] else 0.0)) ** 2
        elif metric == "mae" and prim == "score":
            vals[r["case_id"]] = abs(r["prediction"] - float(r["expected"]))
    return vals


def paired_compare(ref_recs, cand_recs, seed):
    ref_by_id = {r['case_id']: r for r in ref_recs}
    if len(ref_by_id) != len(ref_recs) or len({r['case_id'] for r in cand_recs}) != len(cand_recs):
        raise ValueError('Duplicate comparison case IDs')
    if set(ref_by_id) != {r['case_id'] for r in cand_recs}:
        raise ValueError('Comparison requires identical case sets')
    for r in cand_recs:
        ref = ref_by_id[r['case_id']]
        if any(ref.get(k) != r.get(k) for k in ('input_hash', 'expected', 'primitive')):
            raise ValueError(f"Comparison input or label mismatch: {r['case_id']}")
    out = {}
    for prim, metric in (("choice", "accuracy"), ("noul", "accuracy"),
                         ("noul", "brier"), ("score", "mae")):
        rv = per_case_values(ref_recs, prim, metric)
        cv = per_case_values(cand_recs, prim, metric)
        shared = sorted(set(rv) & set(cv))
        if not shared:
            out[f"{prim}_{metric}"] = None
            continue
        out[f"{prim}_{metric}"] = paired_bootstrap(
            [rv[c] for c in shared], [cv[c] for c in shared], seed)
    return out


def verdict(ref_metrics, cand_metrics, ref_recs, cand_recs, critical_groups,
            seed, min_n, local):
    """Apply the preregistered adoption rule.

    PASS requires every clause. Any missing sample, any CI that crosses a
    margin, or any primitive below min_n yields INCONCLUSIVE, never PASS.
    """
    reasons = []
    failed = False
    inconclusive = False
    comparisons = paired_compare(ref_recs, cand_recs, seed)
    if any(r.get('split') != 'evaluation' for r in cand_recs):
        inconclusive = True
        reasons.append('INCONCLUSIVE: smoke or previously calibrated data cannot authorize adoption')
    for label, metrics in (('reference', ref_metrics), ('candidate', cand_metrics)):
        if metrics['errors'] or metrics['schema_incompatibilities']:
            failed = True
            reasons.append(f"FAIL: {label} has errors or schema incompatibilities")
    checks = [('choice_accuracy', ACC_MARGIN, True), ('noul_accuracy', ACC_MARGIN, True),
              ('noul_brier', BRIER_MARGIN, False), ('score_mae', MAE_MARGIN, False)]
    scopes = [('overall', comparisons)]
    for group in critical_groups:
        if not any(r['group'] == group for r in cand_recs):
            inconclusive = True
            reasons.append(f'INCONCLUSIVE: missing critical group {group}')
        scopes.append((group, paired_compare(
            [r for r in ref_recs if r['group'] == group],
            [r for r in cand_recs if r['group'] == group], seed)))
    for scope, comparisons in scopes:
        for metric, margin, higher_better in checks:
            c = comparisons[metric]
            if scope != 'overall' and c is None:
                continue
            if scope != 'overall' and higher_better:
                margin = GROUP_ACC_MARGIN
            if c is None or c['n'] < min_n:
                inconclusive = True
                reasons.append(f'INCONCLUSIVE: {scope} {metric} has fewer than {min_n} paired cases')
                continue
            lo, hi = c['ci95']
            bad = hi < -margin if higher_better else lo > margin
            good = lo >= -margin if higher_better else hi <= margin
            if bad:
                failed = True
                status = 'FAIL'
            elif not good:
                inconclusive = True
                status = 'INCONCLUSIVE'
            else:
                status = 'PASS'
            reasons.append(f'{status}: {scope} {metric}, difference {c["mean_diff"]:+.4f}, '
                           f'CI95 [{lo:+.4f}, {hi:+.4f}], margin {margin}')
    ref_p50 = ref_metrics['latency']['p50']
    cand_p50 = cand_metrics['latency']['p50']
    if ref_p50 is not None and cand_p50 is not None and cand_p50 < ref_p50:
        reasons.append(f'PASS: measured latency benefit {cand_p50:.4f}s vs {ref_p50:.4f}s')
    else:
        inconclusive = True
        reasons.append('INCONCLUSIVE: latency benefit not measured; local execution alone does not prove no egress')
    status = 'FAIL' if failed else ('INCONCLUSIVE' if inconclusive else 'PASS')
    return {'status': status, 'reasons': reasons,
            'margins': {'accuracy': ACC_MARGIN, 'group_accuracy': GROUP_ACC_MARGIN,
                        'brier': BRIER_MARGIN, 'score_mae': MAE_MARGIN, 'min_n': min_n},
            'critical_groups': critical_groups}


# --------------------------------------------------------------------- metadata

def hardware_metadata():
    meta = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
    }
    for name in ("torch", "mlx", "numpy", "transformers", "laya", "laya_mlx"):
        try:
            meta[f"{name}_version"] = importlib.metadata.version(name.replace('_', '-'))
        except importlib.metadata.PackageNotFoundError:
            meta[f"{name}_version"] = None
    return meta


# -------------------------------------------------------------------------- main

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Compare Jev, upstream Laya, and laya-mlx.")
    ap.add_argument("--provider", action="append", choices=list(PROVIDERS) + ["all"],
                    help="provider to run (repeatable); default all")
    ap.add_argument("--checkpoint", default=None, help="model id / repo / router alias")
    ap.add_argument("--revision", default=None, help="Hub revision pin (laya-mlx)")
    ap.add_argument("--subfolder", default=None, help="checkpoint subfolder (laya, laya-mlx)")
    ap.add_argument("--dtype", default=None, help="laya-mlx dtype, e.g. float16 or float32")
    ap.add_argument("--batch-size", type=int, default=None, help="laya-mlx questions per forward pass")
    ap.add_argument("--device", default=None, help="device override for local runtimes")
    ap.add_argument("--router-model", default=None, help="explicit Router model override")
    ap.add_argument("--cases", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "laya-comparison-cases.jsonl"),
        help="path to the cases JSONL")
    ap.add_argument("--adapter", default=None, help="existing labelled dataset to adapt (JSONL)")
    ap.add_argument("--adapter-pack", default=None, help="pack JSON for the adapter")
    ap.add_argument("--adapter-question", default=None, help="noul question id to adapt")
    ap.add_argument("--out", default=None, help="scratch output directory (never the repo)")
    ap.add_argument("--seed", type=int, default=0, help="seed for the paired bootstrap")
    ap.add_argument("--warmup", type=int, default=1, help="unmeasured runs per case")
    ap.add_argument("--repetitions", type=int, default=3, help="measured runs per case")
    ap.add_argument("--limit", type=int, default=None, help="use only the first N cases")
    ap.add_argument("--bins", type=int, default=10, help="ECE bins")
    ap.add_argument("--min-n", type=int, default=DEFAULT_MIN_N, help="minimum cases per primitive")
    ap.add_argument("--critical-groups", default="explicit_negation,absent_evidence,multilingual",
                    help="comma-separated groups with a 5-point margin")
    ap.add_argument("--reference", default="jev", choices=list(PROVIDERS),
                    help="provider the adoption rule compares against")
    ap.add_argument('--reference-run', help='Reuse the reference from a prior run.json; no additional calls')
    ap.add_argument("--live", action="store_true", help="actually execute providers")
    args = ap.parse_args(argv)
    if args.warmup < 0 or args.repetitions < 1 or args.bins < 1 or args.min_n < 30:
        ap.error('warmup must be >=0, repetitions/bins >=1, and min-n >=30')
    if args.limit is not None and args.limit < 1:
        ap.error('limit must be positive')
    if any((args.checkpoint, args.revision, args.device)) and len(select_providers(args.provider)) != 1:
        ap.error('--checkpoint, --revision, and --device require exactly one explicit provider')
    return args


def select_providers(requested):
    if not requested or "all" in requested:
        return list(PROVIDERS)
    seen = []
    for p in requested:
        if p not in seen:
            seen.append(p)
    return seen


def default_out_dir():
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return os.path.expanduser(f"~/.local/scratch/laya-compare-{stamp}")


def main(argv=None):
    args = parse_args(argv)
    args.critical_groups = [g for g in args.critical_groups.split(",") if g]

    if args.adapter:
        if not args.adapter_pack:
            print("laya_compare: --adapter requires --adapter-pack", file=sys.stderr)
            return 2
        cases = adapt_dataset(args.adapter, args.adapter_pack, args.adapter_question)
        print(f"laya_compare: adapted {len(cases)} cases from {args.adapter} "
              f"(origin=adapter; keep separate from the synthetic corpus)")
    else:
        if not os.path.exists(args.cases):
            print(f"laya_compare: cases file not found: {args.cases}", file=sys.stderr)
            return 2
        cases = load_cases(args.cases)
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        print("laya_compare: no cases to run", file=sys.stderr)
        return 2

    providers = select_providers(args.provider)
    runs = args.warmup + args.repetitions

    print(f"laya_compare: {len(cases)} cases, providers={providers}, "
          f"warmup={args.warmup}, repetitions={args.repetitions}")

    if "jev" in providers:
        planned = len(cases) * runs
        print(f"laya_compare: planned Jev requests: {planned} "
              f"({len(cases)} cases x ({args.warmup} warmup + {args.repetitions} measured)); "
              f"no retries are hidden in this count")

    if not args.live:
        print("laya_compare: dry run. Pass --live to execute. "
              "Local runtimes that are absent will report NOT RUN.")
        return 0

    out_dir = args.out or default_out_dir()
    os.makedirs(out_dir, exist_ok=True)
    if any(os.path.exists(os.path.join(out_dir, f)) for f in ('run.json', 'predictions.jsonl')):
        raise ValueError('Output already contains a run; use a fresh --out directory')
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    run_meta = {
        "started_at": started,
        "cases_path": None if args.adapter else os.path.abspath(args.cases),
        "adapter": {"dataset": args.adapter, "pack": args.adapter_pack,
                    "question": args.adapter_question} if args.adapter else None,
        "case_count": len(cases),
        "case_ids_sha256": sha256_hex(canonical([c["id"] for c in cases])),
        "providers": providers,
        "reference": args.reference,
        "seed": args.seed,
        "warmup": args.warmup,
        "repetitions": args.repetitions,
        "parameters": {
            "checkpoint": args.checkpoint, "revision": args.revision,
            "subfolder": args.subfolder, "dtype": args.dtype,
            "batch_size": args.batch_size, "device": args.device,
            "router_model": args.router_model, "limit": args.limit,
            "bins": args.bins, "min_n": args.min_n,
            "critical_groups": args.critical_groups,
        },
        "hardware": hardware_metadata(),
    }

    results = {}
    if args.reference_run:
        if args.reference in providers:
            raise ValueError('Cannot reuse and execute the same reference in one run')
        with open(args.reference_run, encoding='utf-8') as f:
            previous = json.load(f)
        results[args.reference] = previous['providers'][args.reference]
        run_meta['reference_run'] = os.path.abspath(args.reference_run)
        run_meta['reference_sha256'] = sha256_hex(canonical(previous))
    pred_path = os.path.join(out_dir, "predictions.jsonl")
    checkpoint_override = args.checkpoint
    with open(pred_path, "w", encoding="utf-8") as predf:
        for provider in providers:
            ckpt = checkpoint_override or DEFAULT_CHECKPOINT[provider]
            args.checkpoint = ckpt  # build_provider reads it; never substituted
            print(f"laya_compare: loading {provider} (checkpoint={ckpt}) ...")
            t0 = time.perf_counter()
            try:
                prov = build_provider(provider, args)
            except ImportError as e:
                results[provider] = {"status": "NOT RUN", "requested_checkpoint": ckpt,
                                     "reason": f"runtime not importable: {e}"}
                print(f"laya_compare: {provider} NOT RUN ({e})")
                continue
            except Exception as e:  # noqa: BLE001
                results[provider] = {"status": "NOT RUN", "requested_checkpoint": ckpt,
                                     "reason": f"{type(e).__name__}: {e}"}
                print(f"laya_compare: {provider} NOT RUN ({type(e).__name__}: {e})")
                continue
            cold = time.perf_counter() - t0
            recs = []
            halted = False
            for case in cases:
                if halted:
                    qid = next(iter(case['questions']))
                    rec = dict(case_id=case['id'], group=case['group'], split=case['split'],
                        primitive=case['questions'][qid]['type'], question_id=qid,
                        input_hash=sha256_hex(canonical({'state': case['state'], 'questions': case['questions']})),
                        ok=False, schema_ok=False, error='NOT RUN after authentication failure',
                        prediction=None, expected=case['expected'][qid], latency_samples=[], raw_answer=None)
                else:
                    rec = run_case(prov, case, args)
                if rec['error'] and any(s in rec['error'] for s in ('HTTP Error 401', 'HTTP Error 403')):
                    halted = True
                rec['provider'] = provider
                rec['checkpoint'] = ckpt
                recs.append(rec)
                predf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                predf.flush()
            metrics = compute_metrics(recs, args.bins)
            results[provider] = {
                "status": "RUN",
                "requested_checkpoint": ckpt,
                "resolved_model": getattr(prov, "resolved_model", None),
                "actual_device": getattr(prov, 'actual_device', None),
                "actual_dtype": getattr(prov, 'actual_dtype', None),
                "cold_load_seconds": cold,
                "requests": getattr(prov, "requests", None),
                "cases": recs,
                "metrics": metrics,
            }
            print(f"laya_compare: {provider} done "
                  f"(resolved={getattr(prov, 'resolved_model', None)}, cold={cold:.3f}s)")

    # Paired comparisons against the reference.
    ref = results.get(args.reference)
    if ref and ref.get("status") == "RUN":
        ref_recs = ref["cases"]
        for provider, res in results.items():
            if provider == args.reference or res.get("status") != "RUN":
                continue
            res["paired_vs_reference"] = paired_compare(ref_recs, res["cases"], args.seed)
            res["verdict"] = verdict(ref["metrics"], res["metrics"], ref_recs, res["cases"],
                                     args.critical_groups, args.seed, args.min_n,
                                     local=PROVIDERS[provider]["kind"] != "jev")

    run_meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    run_meta["provider_summary"] = {
        p: {"status": r.get("status"),
            "resolved_model": r.get("resolved_model"),
            "cold_load_seconds": r.get("cold_load_seconds"),
            "reason": r.get("reason")}
        for p, r in results.items()}

    with open(os.path.join(out_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump({"run": run_meta, "providers": results}, f, indent=2, ensure_ascii=False)

    print(f"laya_compare: wrote {os.path.join(out_dir, 'run.json')} and {pred_path}")
    print("laya_compare: this is a smoke evaluation on a small synthetic corpus; "
          "it is not sufficient evidence for a global default switch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
