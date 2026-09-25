#!/usr/bin/env python3
"""Where Jev is used: by tool, client, project, day and session, plus Laya.

Reads the spend log (schema 2 rows only) and the Laya decision log. Feeds the
one-week evaluation in docs/usage-evaluation.md.

    python3 tools/usage_report.py [--since YYYY-MM-DD] [--json]
"""
import argparse, json, math, os, sys
from collections import Counter, defaultdict

DEFAULT_SINCE = "2026-09-25"
BATCH_BINS = (("1", 1, 1), ("2-4", 2, 4), ("5-16", 5, 16), ("17+", 17, None))


def spend_log():
    return os.environ.get("TYPESAFE_SPEND_LOG",
                          os.path.expanduser("~/.claude/docs/telemetry/jev-spend.jsonl"))


def laya_log():
    return os.environ.get("LAYA_DECISION_LOG",
                          os.path.expanduser("~/.claude/docs/telemetry/laya-decisions.jsonl"))


def read_rows(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a torn line from a crashed write is skipped
            if isinstance(row, dict):
                rows.append(row)
    return rows


def pct(values, p):
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(p / 100.0 * len(s)) - 1)]


def project(row):
    return os.path.basename((row.get("cwd") or "").rstrip("/")) or "(unknown)"


def qcount(row):
    return row.get("questions") or 0


def group_stats(rows, key):
    groups = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    out = []
    for name, rs in groups.items():
        lat = [r["latency_ms"] for r in rs
               if r.get("ok") is not False and isinstance(r.get("latency_ms"), (int, float))]
        out.append({
            "name": name,
            "requests": len(rs),
            "share_pct": round(100.0 * len(rs) / len(rows), 1),
            "mean_questions": round(sum(qcount(r) for r in rs) / len(rs), 2),
            "single_question_pct": round(100.0 * sum(1 for r in rs if qcount(r) == 1) / len(rs), 1),
            "latency_p50": pct(lat, 50), "latency_p90": pct(lat, 90),
            "latency_max": max(lat) if lat else None,
            "errors": sum(1 for r in rs if r.get("ok") is False),
        })
    return sorted(out, key=lambda g: (-g["requests"], str(g["name"])))


def build(since):
    all_rows = [r for r in read_rows(spend_log()) if str(r.get("ts", ""))[:10] >= since]
    rows = [r for r in all_rows if r.get("schema") == 2]
    laya = [r for r in read_rows(laya_log()) if str(r.get("ts", ""))[:10] >= since]
    ok = [r for r in rows if r.get("ok") is not False]
    report = {
        "since": since, "spend_log": spend_log(), "laya_log": laya_log(),
        "skipped_old_rows": len(all_rows) - len(rows),
        "totals": {
            "requests": len(rows),
            "ok_rate_pct": round(100.0 * len(ok) / len(rows), 1) if rows else None,
            "questions": sum(qcount(r) for r in rows),
            "input_tokens": sum(r.get("input_tokens") or 0 for r in rows),
            "output_tokens": sum(r.get("output_tokens") or 0 for r in rows),
            "sessions": len({r.get("pid") for r in rows if r.get("pid") is not None}),
            "projects": len({r.get("cwd") for r in rows if r.get("cwd")}),
        },
        "by_tool": group_stats(rows, lambda r: r.get("tool") or "(unknown)"),
        "by_client": group_stats(rows, lambda r: r.get("client") or "(none)"),
        "by_project": group_stats(rows, project),
    }
    days = defaultdict(lambda: {"requests": 0, "questions": 0})
    for r in rows:
        d = days[str(r.get("ts", ""))[:10]]
        d["requests"] += 1
        d["questions"] += qcount(r)
    report["by_day"] = [dict(day=k, **days[k]) for k in sorted(days)]
    report["batching"] = {label: sum(1 for r in rows if qcount(r) >= lo and (hi is None or qcount(r) <= hi))
                          for label, lo, hi in BATCH_BINS}

    sessions = defaultdict(list)
    for r in rows:
        sessions[r.get("pid")].append(r)
    top = sorted(sessions.items(), key=lambda kv: -len(kv[1]))[:10]
    report["top_sessions"] = [{
        "pid": pid, "client": rs[0].get("client"), "project": project(rs[0]), "requests": len(rs),
        "first_ts": min(str(r.get("ts", "")) for r in rs), "last_ts": max(str(r.get("ts", "")) for r in rs),
    } for pid, rs in top]

    durations = [r["durationMs"] for r in laya if isinstance(r.get("durationMs"), (int, float))]
    profiles = defaultdict(lambda: {"requests": 0, "accepted": 0})
    for r in laya:
        p = profiles[r.get("profile") or "(none)"]
        p["requests"] += 1
        p["accepted"] += 1 if r.get("accepted") is True else 0
    report["laya"] = {
        "requests": len(laya),
        "accepted_rate_pct": round(100.0 * sum(1 for r in laya if r.get("accepted") is True) / len(laya), 1) if laya else None,
        "reasons": dict(Counter(r.get("reason") or "(none)" for r in laya).most_common()),
        "duration_p50": pct(durations, 50), "duration_p90": pct(durations, 90),
        "by_profile": [dict(profile=k, **profiles[k]) for k in sorted(profiles)],
    }

    sites = defaultdict(list)
    for r in rows:
        sites[(r.get("tool") or "(unknown)", project(r))].append(r)
    report["candidate_sites"] = [{
        "tool": tool, "project": proj, "requests": len(rs),
        "with_answers": sum(1 for r in rs if r.get("answers")),
    } for (tool, proj), rs in sorted(sites.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:5]]
    return report


def table(title, headers, rows):
    print(f"\n{title}")
    cells = [[("-" if v is None else str(v)) for v in row] for row in rows]
    widths = [max([len(h)] + [len(c[i]) for c in cells]) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for c in cells:
        print("  ".join(v.ljust(w) for v, w in zip(c, widths)))
    if not rows:
        print("(none)")


def print_text(rep):
    t = rep["totals"]
    print(f"Jev usage since {rep['since']} ({rep['spend_log']})")
    print(f"skipped {rep['skipped_old_rows']} older rows without schema 2")
    table("Totals", ["requests", "ok %", "questions", "input", "output", "sessions", "projects"],
          [[t["requests"], t["ok_rate_pct"], t["questions"], t["input_tokens"], t["output_tokens"],
            t["sessions"], t["projects"]]])
    heads = ["name", "requests", "share %", "mean q", "1-q %", "p50 ms", "p90 ms", "max ms", "errors"]
    for key, title in (("by_tool", "By tool"), ("by_client", "By client"), ("by_project", "By project")):
        table(title, heads, [[g["name"], g["requests"], g["share_pct"], g["mean_questions"],
                              g["single_question_pct"], g["latency_p50"], g["latency_p90"],
                              g["latency_max"], g["errors"]] for g in rep[key]])
    table("By day", ["day", "requests", "questions"],
          [[d["day"], d["requests"], d["questions"]] for d in rep["by_day"]])
    table("Batching (questions per request)", ["bin", "requests"], list(rep["batching"].items()))
    table("Top sessions", ["pid", "client", "project", "requests", "first", "last"],
          [[s["pid"], s["client"], s["project"], s["requests"], s["first_ts"], s["last_ts"]]
           for s in rep["top_sessions"]])
    la = rep["laya"]
    print(f"\nLaya ({rep['laya_log']})")
    print(f"requests {la['requests']}, accepted {la['accepted_rate_pct'] if la['accepted_rate_pct'] is not None else '-'} %, "
          f"durationMs p50 {la['duration_p50'] if la['duration_p50'] is not None else '-'}, "
          f"p90 {la['duration_p90'] if la['duration_p90'] is not None else '-'}")
    table("Laya reasons", ["reason", "count"], list(la["reasons"].items()))
    table("Laya by profile", ["profile", "requests", "accepted"],
          [[p["profile"], p["requests"], p["accepted"]] for p in la["by_profile"]])
    table("Candidate call sites (score these by hand)", ["tool", "project", "requests", "with answers"],
          [[s["tool"], s["project"], s["requests"], s["with_answers"]] for s in rep["candidate_sites"]])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default=DEFAULT_SINCE, help="first day to include, YYYY-MM-DD")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    args = ap.parse_args(argv)
    rep = build(args.since)
    if args.json:
        print(json.dumps(rep, indent=2))
        return 0
    if not rep["totals"]["requests"] and not rep["laya"]["requests"]:
        print(f"no schema 2 Jev rows or Laya rows since {args.since} "
              f"(spend log {rep['spend_log']}, Laya log {rep['laya_log']}; "
              f"{rep['skipped_old_rows']} older rows skipped)")
        return 0
    print_text(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
