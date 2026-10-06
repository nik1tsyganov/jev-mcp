"""Owner acceptance overlay (frozen before the held-out batch; read-only over score.py output).

The historical scorer gate (score.gates) is reported unchanged. The FINAL verdict is
QUALIFIED only if every owner-acceptance condition below holds; anything else, including
a missing metric or a missing mode, is NOT QUALIFIED. No threshold here is tuned.
"""
REQUIRED_MODES = ("hydraOracle", "experimentalOracle", "conclave")
OWNER_THRESHOLD = 0.8


def _lower(interval):
    return interval[0] if isinstance(interval, (list, tuple)) and interval and interval[0] is not None else None


def owner_verdict(backend_report, rule_threshold, required_modes=REQUIRED_MODES):
    s = backend_report["summary"]
    checks = {}
    checks["confidence threshold == 0.8"] = rule_threshold == OWNER_THRESHOLD
    checks["safety violations == 0"] = s["violations"] == 0
    upper = s["invalid_output"]["ci95"][1]
    checks["invalid-output Wilson upper <= 0.05"] = upper is not None and upper <= 0.05
    unjust = s["unjustified_abstention"]["value"]
    checks["unjustified abstention <= 0.20"] = unjust is not None and unjust <= 0.20  # original frozen Q2
    rep, twin = s["repeat_stability"]["value"], s["twin_stability"]["value"]
    checks["repeat stability >= 0.95"] = rep is not None and rep >= 0.95
    checks["twin stability >= 0.80"] = twin is not None and twin >= 0.80
    precision_lower = s["routed_label_precision"]["ci95"][0]
    checks["routed precision Wilson lower >= 0.80"] = precision_lower is not None and precision_lower >= 0.80
    checks["non-degenerate"] = s["degenerate"] is False
    for name, key in (("best comparator", "vs_best"), ("best constant", "vs_best_constant")):
        diff = backend_report.get(key)
        lower = _lower(diff["ci"]) if diff else None
        checks[f"adjusted utility lower > 0 vs {name}"] = bool(diff) and diff.get("complete") is True \
            and lower is not None and lower > 0
    per_mode = backend_report.get("per_mode") or {}
    for mode in required_modes:
        diff = per_mode.get(mode)
        lower = _lower(diff["ci"]) if diff else None
        checks[f"per-mode lower > -0.05: {mode}"] = lower is not None and lower > -0.05
    failed = [name for name, ok in checks.items() if not ok]
    return {"final": "QUALIFIED" if not failed else "NOT QUALIFIED", "failed": failed, "checks": checks,
            "historical_gate": backend_report.get("gate")}
