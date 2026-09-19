#!/usr/bin/env python3
"""What has Jev cost, by day and by model. Reads the spend log the client writes."""
import json, os, sys
from collections import defaultdict
LOG = os.environ.get("TYPESAFE_SPEND_LOG", os.path.expanduser("~/.claude/docs/telemetry/jev-spend.jsonl"))
if not os.path.exists(LOG):
    sys.exit(f"no spend log at {LOG} yet")
days = defaultdict(lambda: {"requests": 0, "questions": 0, "in": 0, "out": 0})
for line in open(LOG):
    line = line.strip()
    if not line:
        continue
    try:
        r = json.loads(line)
    except ValueError:
        continue          # a torn line from a crashed write is skipped, not fatal
    d = days[r.get("ts", "")[:10]]
    d["requests"] += 1
    d["questions"] += r.get("questions") or 0
    d["in"] += r.get("input_tokens") or 0
    d["out"] += r.get("output_tokens") or 0
print(f"{'day':12s} {'requests':>9s} {'questions':>10s} {'input':>10s} {'output':>9s}")
for day in sorted(days):
    v = days[day]
    print(f"{day:12s} {v['requests']:9d} {v['questions']:10d} {v['in']:10d} {v['out']:9d}")
tot = {k: sum(v[k] for v in days.values()) for k in ("requests", "questions", "in", "out")}
print(f"{'total':12s} {tot['requests']:9d} {tot['questions']:10d} {tot['in']:10d} {tot['out']:9d}")
