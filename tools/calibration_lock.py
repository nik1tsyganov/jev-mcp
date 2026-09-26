#!/usr/bin/env python3
"""Lock calibration to the model version seen in telemetry.

A threshold measured against one model version is not evidence about another,
and this is the only thing that notices.
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS_DIR = os.path.join(HERE, "packs")
LOG = os.environ.get("TYPESAFE_SPEND_LOG", os.path.expanduser("~/.claude/docs/telemetry/jev-spend.jsonl"))


def get_pack_model(pack):
    if isinstance(pack.get("calibrated_on_model"), str) and pack["calibrated_on_model"].strip():
        return pack["calibrated_on_model"].strip()
    for t in (pack.get("thresholds") or {}).values():
        if isinstance(t, dict) and isinstance(t.get("calibrated_on_model"), str) and t["calibrated_on_model"].strip():
            return t["calibrated_on_model"].strip()
    return None


def read_packs(packs_dir):
    pins = {}
    pattern = os.path.join(packs_dir, "*.json")
    for path in sorted(glob.glob(pattern)):
        if os.path.basename(path) == "README.md":
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        name = data.get("name") or os.path.splitext(os.path.basename(path))[0]
        model = get_pack_model(data)
        pins[name] = model
    return pins


def read_spend_log(log_path):
    if not os.path.exists(log_path):
        return []
    records = []
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if isinstance(r, dict) and r.get("model") and r.get("ok") is not False:
                        records.append(r)
                except ValueError:
                    continue
    except OSError:
        return []
    return records


def main():
    ap = argparse.ArgumentParser(description="Check pack calibrations against model telemetry.")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    ap.add_argument("-q", "--quiet", action="store_true", help="suppress output, exit code only")
    args = ap.parse_args()

    pins = read_packs(PACKS_DIR)
    records = read_spend_log(LOG)

    if not records:
        if not args.quiet:
            if args.json:
                print(json.dumps({
                    "status": "empty_log",
                    "log": LOG,
                    "message": "spend log is empty or missing; no drift detected",
                    "pinned_models": pins,
                    "observed_models": {},
                    "drifts": [],
                }, indent=2))
            else:
                print(f"calibration-lock: spend log at {LOG} is empty or missing; no drift detected")
        return 0

    observed = {}
    latest_record = None
    for r in records:
        m = r["model"]
        ts = r.get("ts", "")
        if m not in observed:
            observed[m] = {
                "first_seen": ts,
                "last_seen": ts,
                "count": 1,
            }
        else:
            entry = observed[m]
            entry["count"] += 1
            if ts and (not entry["first_seen"] or ts < entry["first_seen"]):
                entry["first_seen"] = ts
            if ts and (not entry["last_seen"] or ts > entry["last_seen"]):
                entry["last_seen"] = ts
        if latest_record is None or (ts and ts >= latest_record.get("ts", "")):
            latest_record = r

    latest_model = latest_record.get("model") if latest_record else None

    drifts = []
    for pack_name, pinned in sorted(pins.items()):
        if pinned and latest_model and pinned != latest_model:
            first_seen_ts = observed.get(latest_model, {}).get("first_seen", "")
            first_seen_date = first_seen_ts[:10] if first_seen_ts else "unknown"
            drifts.append({
                "pack": pack_name,
                "pinned": pinned,
                "observed": latest_model,
                "first_seen": first_seen_date,
            })

    if drifts:
        if not args.quiet:
            if args.json:
                print(json.dumps({
                    "status": "drift",
                    "log": LOG,
                    "latest_model": latest_model,
                    "pinned_models": pins,
                    "observed_models": observed,
                    "drifts": drifts,
                    "instruction": "the gate must be re-measured before it is trusted",
                }, indent=2))
            else:
                for d in drifts:
                    print(f"calibration-lock: {d['pack']} pinned to {d['pinned']}, observed {d['observed']} (first seen {d['first_seen']})")
                print("calibration-lock: calibration drift detected; the gate must be re-measured before it is trusted")
        return 1

    # All match
    distinct_pins = sorted(set(p for p in pins.values() if p))
    pinned_display = distinct_pins[0] if len(distinct_pins) == 1 else ", ".join(distinct_pins)
    if not args.quiet:
        if args.json:
            print(json.dumps({
                "status": "ok",
                "log": LOG,
                "latest_model": latest_model,
                "pinned_models": pins,
                "observed_models": observed,
                "drifts": [],
            }, indent=2))
        else:
            print(f"calibration-lock: OK, all packs match observed model {pinned_display}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
