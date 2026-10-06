"""Classify once, replay any rule from stored answers, all through the product callable.

`classify` prepares each case's native request with `droppy route`, obtains one raw
reply per repeat from the chosen backend and stores request hashes and replies.
`replay` rebuilds each case input with a rule's threshold, re-prepares it (the
classifier request must be byte-identical) and replays the stored replies; it makes
no classifier call. Held-out splits require a verified freeze covering the case file
and never take gold. Paid runs stop on the first admission refusal or failed call.
"""
import json
import math
from pathlib import Path
import time

from . import replies as R
from .common import (CAMPAIGN_DIR, FROZEN_INPUTS, JEV_REQUEST_TOKEN_CEILING, OWNER_THRESHOLD, ROOT, read_json,
                     read_jsonl, rel, sha256, sha256_bytes, utc_now, write_json)
from .context import Context
from .frozen import verify

PAID = ("jev",)
LOCAL = ("laya",)


def backend_identity(backend):
    """Helper backend enum and model a reply is replayed under. Controls use the Jev
    identity only so the helper parses them; they are never classifier evidence."""
    return ("laya", R.LAYA_MODEL) if backend == "laya" else ("jev", R.JEV_MODEL)


def step_maximum_usd(n_calls, price):
    """Conservative step reservation: the documented per-request ceiling, rounded UP to a cent."""
    exact = n_calls * JEV_REQUEST_TOKEN_CEILING * float(price["usdPerInputToken"])
    return exact, math.ceil(exact * 100 - 1e-9) / 100


def budget_gate(n_calls, price, ledger=CAMPAIGN_DIR / "ledger.jsonl", module=CAMPAIGN_DIR / "jev_campaign_ledger.py"):
    """Aggregate gate, read in the same process that starts paid calls."""
    from .jev_native import _campaign
    campaign = _campaign(module)
    with campaign.locked(ledger):
        state = campaign.fold(campaign.read_rows(ledger))
    exact, need = step_maximum_usd(n_calls, price)
    problems = []
    if state["campaign"] is None:
        problems.append("no campaign row")
    if state["paused"]:
        problems.append("ledger paused")
    if state["unresolved"]:
        problems.append("unresolved history")
    if state["remainingUSD"] is None or state["remainingUSD"] < need:
        problems.append(f"remainingUSD {state['remainingUSD']} < step maximum {need:.2f}")
    return {"ok": not problems, "problems": problems, "step_max_usd_exact": exact, "step_max_usd": need,
            "state": {k: state[k] for k in ("committedUSD", "remainingUSD", "paused", "unresolved")}}


def admission_gate(admission_id, planned, ledger=CAMPAIGN_DIR / "ledger.jsonl",
                   module=CAMPAIGN_DIR / "jev_campaign_ledger.py"):
    """Owner single-batch admission state, read in the process that starts paid calls."""
    from .jev_native import _campaign
    campaign = _campaign(module)
    with campaign.locked(ledger):
        state = campaign.fold(campaign.read_rows(ledger))
    admission = state["_admissions"].get(admission_id)
    problems = []
    if admission is None:
        problems.append("admission unknown")
    else:
        frozen = admission["_entry"]["freeze"]
        if not admission["open"] or admission["reconciled"]:
            problems.append("admission closed")
        if admission["pausedAfter"]:
            problems.append("a pause follows the admission")
        if frozen is None:
            problems.append("admission not frozen by the batch party")
        elif frozen["maxAttempts"] - admission["attempts"] < planned:
            problems.append(f"planned {planned} > remaining {frozen['maxAttempts'] - admission['attempts']} attempts")
    return {"ok": not problems, "problems": problems,
            "admission": None if admission is None else {k: v for k, v in admission.items() if not k.startswith("_")}}


def _reply_for(backend, request_json, gold, case_id, repeat, options):
    if backend == "oracle":
        return R.oracle(request_json, gold)
    if backend == "anti":
        return R.anti(request_json, gold)
    if backend == "shuffled":
        return R.shuffled_oracle(request_json, gold, options.get("seed", 20261002))
    if backend == "random":
        return R.random_reply(request_json, f"{options.get('seed', 20261002)}:{case_id}:{repeat}")
    if backend == "matrix":
        return R.matrix(request_json)
    if backend == "manual":
        return R.manual(request_json)
    if backend.startswith("constant:"):
        _, family, task_class = backend.split(":")
        return R.constant(request_json, family, task_class)
    if backend.startswith("malformed:"):
        return R.malformed(request_json, backend.split(":", 1)[1])
    raise ValueError(f"unknown control backend {backend}")


def classify(cases_path, backend, repeats, out, gold_path=None, freeze_name=None, frozen=FROZEN_INPUTS,
             options=None, transport=None, freeze_root=ROOT, app=None):
    options = options or {}
    cases_path, out = Path(cases_path), Path(out)
    cases = read_jsonl(cases_path)
    split = cases[0]["split"]
    if split == "heldout":
        if gold_path:
            raise ValueError("gold never enters a held-out classification run")
        if not freeze_name:
            raise ValueError("held-out runs require --freeze")
        record = verify(freeze_name, freeze_root)
        if rel(cases_path) not in record["hashes"]:
            raise ValueError("freeze does not cover the held-out case file")
    if backend in ("oracle", "anti", "shuffled") and not gold_path:
        raise ValueError(f"{backend} control requires gold (non-held-out splits only)")
    if backend in PAID + LOCAL and transport is None:
        raise ValueError(f"{backend} needs a transport")
    known = PAID + LOCAL + ("keep-current", "oracle", "anti", "shuffled", "random", "matrix", "manual")
    if backend not in known and not backend.startswith(("constant:", "malformed:")):
        raise ValueError(f"unknown backend {backend}")
    gold = {g["id"]: g for g in read_jsonl(gold_path)} if gold_path else {}
    ctx = Context(cases, frozen, app=app)
    helper_backend, model = backend_identity(backend)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "manifest.json").exists():
        raise ValueError("output directory already holds a run")
    evidence = sha256(cases_path)[:16]
    manifest = {"backend": backend, "helper_backend": helper_backend, "model": model, "split": split,
                "cases": rel(cases_path), "cases_sha256": sha256(cases_path), "repeats": repeats,
                "helper": ctx.helper.identity, "catalogs": ctx.catalogs, "matrix_version": ctx.matrix_version,
                "freeze": freeze_name, "started_at": utc_now(), "status": "running", "options": options}
    write_json(out / "manifest.json", manifest)
    records, requests = [], {}
    try:
        for case in cases:
            native, removed = ctx.input(case, helper_backend, model, OWNER_THRESHOLD, evidence)
            try:
                prepared = ctx.helper.prepare(native)
            except Exception as exc:
                records.append({"case_id": case["id"], "repeat": None, "error": "prepare-rejected",
                                "detail": str(exc)[:400], "guard_removed": removed})
                continue
            request_json = prepared["requestJSON"]
            requests[case["id"]] = {"request_sha256": sha256_bytes(request_json.encode()),
                                    "serialized_bytes": prepared.get("serializedBytes"),
                                    "request_json": request_json, "guard_removed": removed}
            for repeat in range(repeats):
                row = {"case_id": case["id"], "repeat": repeat, "raw": None, "error": None,
                       "request_sha256": requests[case["id"]]["request_sha256"]}
                started = time.perf_counter()
                if backend in PAID + LOCAL:
                    sent = transport.send(request_json, f"{case['id']}#{repeat}")
                    row.update(raw=sent.get("raw"), error=None if sent.get("ok") else sent.get("error"),
                               detail=sent.get("detail"), usage=sent.get("usage"), reserve_id=sent.get("reserve_id"),
                               returned_model=sent.get("returned_model"), response_meta=sent.get("response_meta"),
                               attempt=sent.get("attempt"), peak_rss_bytes=sent.get("peak_rss_bytes"))
                    if backend in PAID and row["error"]:
                        records.append(row)
                        raise RuntimeError(f"paid stop rule: {row['error']}")
                elif backend != "keep-current":
                    row["raw"] = _reply_for(backend, request_json, gold.get(case["id"]), case["id"], repeat, options)
                row["latency_ms"] = (time.perf_counter() - started) * 1000
                records.append(row)
        manifest["status"] = "complete"
    except RuntimeError as exc:
        manifest["status"] = "stopped"
        manifest["stop_reason"] = str(exc)
    finally:
        with (out / "records.jsonl").open("w", encoding="utf-8") as stream:
            for row in records:
                stream.write(json.dumps(row, allow_nan=True) + "\n")
        write_json(out / "requests.json", requests)
        manifest["ended_at"] = utc_now()
        write_json(out / "manifest.json", manifest)
    return manifest


def replay(run_dir, threshold, rule_name, frozen=FROZEN_INPUTS, app=None):
    run_dir = Path(run_dir)
    manifest = read_json(run_dir / "manifest.json")
    case_path = Path(manifest["cases"]) if Path(manifest["cases"]).is_absolute() else ROOT / manifest["cases"]
    case_rows = read_jsonl(case_path)
    ctx = Context(case_rows, frozen, app=app or manifest["helper"].get("app"))
    for part in ("executable_sha256", "debug_dylib_sha256", "route_cli_sha256"):
        # The Debug executable is a stub; the load-bearing code is in the .debug.dylib.
        if ctx.helper.identity.get(part) != manifest["helper"].get(part):
            raise ValueError(f"product callable changed between classify and replay: {part}")
    cases = {c["id"]: c for c in case_rows}
    requests = read_json(run_dir / "requests.json")
    evidence = manifest["cases_sha256"][:16]
    target = run_dir / f"routes-{rule_name}.jsonl"
    if target.exists():
        raise ValueError("routes for this rule already exist")
    rows = []
    for record in read_jsonl(run_dir / "records.jsonl"):
        case = cases[record["case_id"]]
        row = {"case_id": record["case_id"], "repeat": record["repeat"], "rule": rule_name, "threshold": threshold}
        if record.get("repeat") is None:
            row.update(result=None, error=record["error"])
        elif manifest["backend"] == "keep-current":
            row.update(result=_keep_current(case), error=None)
        else:
            native, _ = ctx.input(case, manifest["helper_backend"], manifest["model"], threshold, evidence)
            prepared = ctx.helper.prepare(native)
            if sha256_bytes(prepared["requestJSON"].encode()) != requests[record["case_id"]]["request_sha256"]:
                raise ValueError(f"classifier request changed between classify and replay: {record['case_id']}")
            if record.get("raw") is None:
                row.update(result=None, error=record.get("error") or "backend-unavailable")
            else:
                row.update(result=ctx.helper.replay(native, prepared["requestFingerprint"], [record["raw"]]), error=None)
        rows.append(row)
    with target.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    return target


def _keep_current(case):
    native = case["_native"]
    current = native.get("currentCandidateID")
    candidate = next((c for c in native["candidates"] if c["id"] == current), None)
    if candidate is None:
        return {"outcome": "abstain", "reasons": ["no-current"], "dispatchAuthorized": False}
    return {"outcome": "keep-current", "recommendation": candidate, "resolvedConfiguration": candidate["variant"],
            "reasons": ["baseline-keep-current"], "dispatchAuthorized": False}
