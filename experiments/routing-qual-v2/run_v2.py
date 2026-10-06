"""Routing qualification v2 harness CLI (offline unless --paid is given and the gate passes).

Commands
  snapshot-catalogs                 copy canonical catalogs into frozen-inputs/ (once)
  drift                             report frozen-vs-live catalog differences
  unsupported-rows                  dispatch/seat rows the frozen catalogs do not support
  gate-check --cases C --gold G     corpus, leakage and instrument gates (aggregates only)
  freeze --name FROZEN-*.json PATH...   write a freeze file once
  verify --name FROZEN-*.json       verify a freeze file
  classify --cases C --backend B --repeats N --out DIR [--gold G] [--freeze F]
           [--paid --price P --batch-dir D --max-attempts N]   (Jev only; gate read in-process)
  replay --run DIR --rule owner-bands|dev-tuned [--threshold T]
  tune --runs DIR... --gold G --out FILE    choose a dev-only analysis threshold
  score --runs DIR... --comparators name=DIR... --constant DIR --cases C --gold G --rule R --out FILE
         [--commitment FILE --freeze F]   (required for held-out gold)

Backends: jev (paid), laya (local, sandboxed), oracle|anti|shuffled|random|matrix|manual|keep-current,
constant:<family>:<conclave-class>, malformed:<variant>. Decider has no helper backend identity and is
not available here.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from v2lib import frozen, gates, run, score as scoring  # noqa: E402
from v2lib.common import FROZEN_INPUTS, GRID, OWNER_THRESHOLD, read_json, read_jsonl  # noqa: E402


def unsupported_rows():
    from v2lib.native_guard import NativeGuard
    import catalog_guard
    guard = NativeGuard()
    out = []

    def walk(value, source):
        if isinstance(value, dict):
            if isinstance(value.get("model"), str):
                vendor = value.get("vendor")
                provider = catalog_guard.VENDOR_PROVIDER.get(vendor) or (guard.support.models.get(value["model"]) or (None,))[0]
                ok, reason, _ = guard.support.check({"model": value["model"], "provider": provider,
                                                     "effort": value.get("effort")})
                if not ok:
                    out.append({"source": source, "model": value["model"], "effort": value.get("effort"), "reason": reason})
            for item in value.values():
                walk(item, source)
        elif isinstance(value, list):
            for item in value:
                walk(item, source)
    routing = read_json(FROZEN_INPUTS / "routing.json")
    for key in ("classes", "fallbacks", "vendorImplementSeats", "escalation"):
        walk(routing.get(key), "routing." + key)
    walk(read_json(FROZEN_INPUTS / "conclave-seats.json"), "conclave-seats")
    unique = {json.dumps(r, sort_keys=True) for r in out}
    return [json.loads(r) for r in sorted(unique)]


def tune(run_dirs, cases_path, gold_path, out):
    """Dev-only analysis threshold: replay stored answers on the grid (no classifier calls)."""
    rows = []
    for threshold in GRID:
        utilities, violations, precision = [], 0, []
        for directory in run_dirs:
            name = f"grid-{threshold}"
            target = Path(directory) / f"routes-{name}.jsonl"
            if not target.exists():
                run.replay(directory, threshold, name)
            manifest = read_json(Path(directory) / "manifest.json")
            if manifest["split"] == "heldout":
                raise ValueError("tuning never reads held-out runs")
            report = scoring.score([directory], cases_path, gold_path, name, Path(directory) / f"tune-{name}.json",
                                   (), {}, None)
            summary = report["backends"][manifest["backend"]]["summary"]
            utilities.append(summary["utility"]["value"])
            violations += summary["violations"]
            precision.append(summary["routed_label_precision"]["ci95"][0] or 0)
        rows.append({"threshold": threshold, "utility": sum(utilities) / len(utilities), "violations": violations,
                     "routed_precision_lower": min(precision)})
    eligible = [r for r in rows if r["violations"] == 0 and r["routed_precision_lower"] >= 0.85]
    chosen = max(eligible, key=lambda r: (r["utility"], r["threshold"])) if eligible else None
    Path(out).write_text(json.dumps({"analysis_only": True, "chosen": chosen, "grid": rows}, indent=2) + "\n")
    return chosen


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--helper-app", type=Path, help="immutable helper snapshot bundle (frozen.snapshot_helper); default: shared Debug build")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot-catalogs")
    sub.add_parser("drift")
    sub.add_parser("unsupported-rows")
    g = sub.add_parser("gate-check")
    g.add_argument("--cases", required=True, type=Path)
    g.add_argument("--gold", required=True, type=Path)
    g.add_argument("--other", nargs="*", type=Path, default=[])
    f = sub.add_parser("freeze")
    f.add_argument("--name", required=True)
    f.add_argument("--commitment", type=Path)
    f.add_argument("paths", nargs="+", type=Path)
    v = sub.add_parser("verify")
    v.add_argument("--name", required=True)
    c = sub.add_parser("classify")
    c.add_argument("--cases", required=True, type=Path)
    c.add_argument("--backend", required=True)
    c.add_argument("--repeats", type=int, default=1)
    c.add_argument("--out", required=True, type=Path)
    c.add_argument("--gold", type=Path)
    c.add_argument("--freeze")
    c.add_argument("--paid", action="store_true")
    c.add_argument("--price", type=Path)
    c.add_argument("--batch-dir", type=Path, help="shared attempt counter for the whole paid batch")
    c.add_argument("--max-attempts", type=int, help="hard HTTP attempt cap for the whole batch")
    c.add_argument("--admission", help="owner single-batch admission id (ledger); required for paid runs")
    r = sub.add_parser("replay")
    r.add_argument("--run", required=True, type=Path)
    r.add_argument("--rule", required=True, choices=["owner-bands", "dev-tuned"])
    r.add_argument("--threshold", type=float)
    t = sub.add_parser("tune")
    t.add_argument("--runs", nargs="+", required=True, type=Path)
    t.add_argument("--cases", required=True, type=Path)
    t.add_argument("--gold", required=True, type=Path)
    t.add_argument("--out", required=True, type=Path)
    s = sub.add_parser("score")
    s.add_argument("--runs", nargs="+", required=True, type=Path)
    s.add_argument("--comparators", nargs="*", default=[])
    s.add_argument("--constant", type=Path)
    s.add_argument("--cases", required=True, type=Path)
    s.add_argument("--gold", required=True, type=Path)
    s.add_argument("--rule", required=True)
    s.add_argument("--out", required=True, type=Path)
    s.add_argument("--commitment", type=Path)
    s.add_argument("--freeze")
    s.add_argument("--under-test", nargs="*", default=["jev", "laya"])
    a = p.parse_args(argv)

    if a.cmd == "snapshot-catalogs":
        result = frozen.snapshot_catalogs()
    elif a.cmd == "drift":
        result = frozen.drift()
    elif a.cmd == "unsupported-rows":
        result = unsupported_rows()
    elif a.cmd == "gate-check":
        result = gates.gate_check(a.cases, a.gold, a.other)
    elif a.cmd == "freeze":
        extra = {"heldout_gold_commitment": a.commitment.read_text()} if a.commitment else {}
        result = frozen.freeze(a.name, a.paths, extra)
    elif a.cmd == "verify":
        result = frozen.verify(a.name)
    elif a.cmd == "classify":
        transport = None
        if a.backend == "jev":
            if not (a.paid and a.price and a.batch_dir and a.max_attempts and a.admission):
                p.error("jev needs --paid --price --batch-dir --max-attempts --admission; paid calls are never implicit")
            from v2lib.jev_native import AttemptCap, JevNative
            remaining = a.max_attempts - AttemptCap(a.batch_dir, a.max_attempts).count()
            planned = len(read_jsonl(a.cases)) * a.repeats
            if planned > remaining:
                p.error(f"planned {planned} attempts exceed the batch's remaining {remaining}")
            gate = run.admission_gate(a.admission, planned)
            print(json.dumps({"admission_gate": gate}, indent=1, default=str))
            if not gate["ok"]:
                p.error("admission gate failed: " + "; ".join(gate["problems"]))
            transport = JevNative(a.price, a.batch_dir, a.max_attempts, admission_id=a.admission)
        elif a.backend == "laya":
            from v2lib.laya_native import LayaNative
            transport = LayaNative()
        try:
            result = run.classify(a.cases, a.backend, a.repeats, a.out, a.gold, a.freeze, transport=transport,
                                  app=a.helper_app)
        finally:
            if hasattr(transport, "close"):
                transport.close()
    elif a.cmd == "replay":
        if a.rule == "owner-bands":
            threshold = OWNER_THRESHOLD
        elif a.threshold is None or a.threshold not in GRID:
            p.error("dev-tuned replay needs --threshold from the dev-chosen grid value")
        else:
            threshold = a.threshold
        result = {"routes": str(run.replay(a.run, threshold, a.rule, app=a.helper_app))}
    elif a.cmd == "tune":
        result = tune(a.runs, a.cases, a.gold, a.out)
    else:
        cases = read_jsonl(a.cases)
        if cases and cases[0]["split"] == "heldout":
            if not (a.commitment and a.freeze):
                p.error("held-out scoring needs --commitment and --freeze")
            record = frozen.verify(a.freeze)
            manifests = [read_json(Path(d) / "manifest.json") for d in a.runs]
            scoring.verify_gold(a.gold, a.commitment, record, manifests)
        comparators = dict(item.split("=", 1) for item in a.comparators)
        report = scoring.score(a.runs, a.cases, a.gold, a.rule, a.out, a.under_test, comparators, a.constant)
        result = {name: {"utility": b["summary"]["utility"], "gate": b["gate"]} for name, b in report["backends"].items()}
    print(json.dumps(result, indent=1, default=str))


if __name__ == "__main__":
    main()
