#!/usr/bin/env python3
"""Jev client contract checker for jev-mcp.

Checks that the jev-mcp client and question validator adhere to the shared
Jev Client Contract (CONTRACT.md). Inspects local source files offline without
requiring conclave or network access.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(HERE, "src")
PACKS_DIR = os.path.join(HERE, "packs")
CLIENT_JS = os.path.join(SRC_DIR, "client.js")
QUESTIONS_JS = os.path.join(SRC_DIR, "questions.js")

# Re-use calibration_lock's read_packs if available, else standalone fallback
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from calibration_lock import read_packs
except Exception:
    import glob

    def get_pack_model(pack):
        if isinstance(pack.get("calibrated_on_model"), str) and pack["calibrated_on_model"].strip():
            return pack["calibrated_on_model"].strip()
        for t in (pack.get("thresholds") or {}).values():
            if isinstance(t, dict) and isinstance(t.get("calibrated_on_model"), str) and t["calibrated_on_model"].strip():
                return t["calibrated_on_model"].strip()
        return None

    def read_packs(packs_dir):
        pins = {}
        for path in sorted(glob.glob(os.path.join(packs_dir, "*.json"))):
            if os.path.basename(path) == "README.md":
                continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            name = data.get("name") or os.path.splitext(os.path.basename(path))[0]
            pins[name] = get_pack_model(data)
        return pins


CONTRACT_DEFAULTS = {
    "endpoint": "https://api.typesafe.ai/v1/systemone",
    "default_model": "jev-latest",
    "calibrated_model": "jev-1.13.0",
}


def check_endpoint(client_code, expected_endpoint):
    """(a) Assert endpoint composed by baseUrl() plus SDK path equals contract value."""
    # Look for the default fallback in baseUrl()
    match = re.search(
        r'function\s+baseUrl\s*\(\)\s*\{[\s\S]*?TYPESAFE_BASE_URL\s*\|\|\s*["\']([^"\']+)["\']',
        client_code,
    )
    if not match:
        return {
            "name": "endpoint",
            "status": "FAIL",
            "expected": expected_endpoint,
            "observed": "could not extract fallback from baseUrl()",
        }
    raw_base = match.group(1).rstrip("/")
    sdk_path = "/v1/systemone"
    composed = f"{raw_base}{sdk_path}"
    status = "PASS" if composed == expected_endpoint else "FAIL"
    return {
        "name": "endpoint",
        "status": status,
        "expected": expected_endpoint,
        "observed": composed,
    }


def check_default_model(client_code, expected_model):
    """(b) Assert DEFAULT_MODEL is the contract alias."""
    match = re.search(
        r'export\s+const\s+DEFAULT_MODEL\s*=\s*(?:process\.env\.\w+\s*\|\|\s*)?["\']([^"\']+)["\']',
        client_code,
    )
    if not match:
        return {
            "name": "default_model",
            "status": "FAIL",
            "expected": expected_model,
            "observed": "could not extract DEFAULT_MODEL from client.js",
        }
    observed = match.group(1)
    status = "PASS" if observed == expected_model else "FAIL"
    return {
        "name": "default_model",
        "status": status,
        "expected": expected_model,
        "observed": observed,
    }


def check_pack_calibrations(packs_dir, expected_version):
    """(c) Assert every pack under packs/ carries calibrated_on_model equal to contract pin."""
    pins = read_packs(packs_dir)
    if not pins:
        return {
            "name": "calibrated_model",
            "status": "FAIL",
            "expected": expected_version,
            "observed": f"no packs found in {packs_dir}",
        }
    mismatches = {name: model for name, model in pins.items() if model != expected_version}
    if mismatches:
        mismatch_desc = ", ".join(f"{k}={v}" for k, v in sorted(mismatches.items()))
        return {
            "name": "calibrated_model",
            "status": "FAIL",
            "expected": expected_version,
            "observed": f"mismatches in {len(mismatches)}/{len(pins)} packs: {mismatch_desc}",
        }
    return {
        "name": "calibrated_model",
        "status": "PASS",
        "expected": expected_version,
        "observed": f"all {len(pins)} packs pinned to {expected_version}",
    }


def check_error_redaction(client_code):
    """(d) Assert client.js defines a redaction function AND catch block routes through it."""
    has_redact_def = bool(re.search(r'export\s+function\s+redact\s*\(', client_code))
    has_redact_error = bool(re.search(r'function\s+redactError\s*\(', client_code))
    redact_error_calls_redact = bool(
        re.search(r'function\s+redactError\s*\([^)]*\)\s*\{[\s\S]*?redact\(', client_code)
    )
    # Check that systemOne's catch block routes through redactError
    catch_routes_redact = bool(
        re.search(
            r'export\s+async\s+function\s+systemOne\b[\s\S]*?\}\s*catch\s*\((?:\w+)\)\s*\{[\s\S]*?(?:throw\s+redactError|redact)',
            client_code,
        )
    )

    if not has_redact_def:
        observed = "redact() function not defined in client.js"
        status = "FAIL"
    elif not (has_redact_error and redact_error_calls_redact):
        observed = "redactError() helper missing or does not invoke redact()"
        status = "FAIL"
    elif not catch_routes_redact:
        observed = "catch block in systemOne does not route through redactError/redact"
        status = "FAIL"
    else:
        observed = "redact() defined and systemOne catch block routes through redactError"
        status = "PASS"

    return {
        "name": "error_redaction",
        "status": status,
        "expected": "redact() defined and applied in error catch paths",
        "observed": observed,
    }


def check_question_guards(questions_code):
    """(e) Assert questions.js rejects reserved ids and enforces choice/score criteria shapes.

    Note: This is a source-level check; the behavioural proof is tests/questions.test.js.
    """
    # Reserved IDs guard: __proto__, constructor, prototype
    has_proto = "__proto__" in questions_code
    has_constructor = "constructor" in questions_code
    has_prototype = "prototype" in questions_code
    reserved_guarded = has_proto and has_constructor and has_prototype

    # Choice criteria shape check (non-empty object)
    has_choice_shape = bool(
        re.search(
            r'export\s+function\s+choice\b[\s\S]*?isPlainObject\(criteria\)[\s\S]*?Object\.keys\(criteria\)\.length\s*===\s*0',
            questions_code,
        )
    )

    # Score criteria shape check (array of at least two levels)
    has_score_shape = bool(
        re.search(
            r'export\s+function\s+score\b[\s\S]*?Array\.isArray\(criteria\)[\s\S]*?criteria\.length\s*<\s*2',
            questions_code,
        )
    )

    missing = []
    if not reserved_guarded:
        missing.append("reserved id guards (__proto__, constructor, prototype)")
    if not has_choice_shape:
        missing.append("choice non-empty object criteria check")
    if not has_score_shape:
        missing.append("score >= 2 levels array criteria check")

    if missing:
        status = "FAIL"
        observed = f"missing guards in questions.js: {', '.join(missing)}"
    else:
        status = "PASS"
        observed = "reserved ids (__proto__, constructor, prototype) and choice/score shapes guarded"

    return {
        "name": "question_guards",
        "status": status,
        "expected": "reserved ids rejected and choice/score shapes enforced",
        "observed": observed,
    }



# The gap self-checks cannot close: each repository checks itself against its OWN copy
# of the contract values, so both can stay green while disagreeing with each other.
# This reads the peer client's source directly - never imports it, so the
# dependency-free rule holds - and compares the three shared constants. If the peer is
# not on this machine the check is SKIPPED, because absence is not disagreement.
PEER_CLIENT = os.path.expanduser("~/src/conclave/tools/jev-client.js")

def check_peer_agreement(expected):
    if not os.path.exists(PEER_CLIENT):
        return {"name": "peer_agreement", "status": "SKIP",
                "expected": "conclave client agrees",
                "observed": f"peer not present at {PEER_CLIENT}; absence is not disagreement"}
    code = open(PEER_CLIENT, encoding="utf-8").read()
    wanted = {"ENDPOINT": expected["endpoint"],
              "DEFAULT_MODEL": expected["default_model"],
              "PINNED_MODEL": expected["calibrated_model"]}
    bad = []
    for name, want in wanted.items():
        m = re.search(rf"\b{name}\s*=\s*['\"]([^'\"]+)['\"]", code)
        if not m:
            bad.append(f"{name} not declared in peer")
        elif m.group(1) != want:
            bad.append(f"{name}: peer={m.group(1)!r} contract={want!r}")
    return {"name": "peer_agreement",
            "status": "FAIL" if bad else "PASS",
            "expected": "endpoint, alias and pinned model match the contract",
            "observed": "; ".join(bad) if bad else "conclave client agrees on all three"}


def run_checks(expected=None):
    if expected is None:
        expected = CONTRACT_DEFAULTS

    with open(CLIENT_JS, "r", encoding="utf-8") as fh:
        client_code = fh.read()

    with open(QUESTIONS_JS, "r", encoding="utf-8") as fh:
        questions_code = fh.read()

    results = [
        check_endpoint(client_code, expected["endpoint"]),
        check_default_model(client_code, expected["default_model"]),
        check_pack_calibrations(PACKS_DIR, expected["calibrated_model"]),
        check_error_redaction(client_code),
        check_question_guards(questions_code),
        check_peer_agreement(expected),
    ]
    return results


def run_selftest(args):
    """Deliberately check a wrong expected value and confirm checker reports FAIL."""
    # Test with an intentionally wrong model alias
    wrong_expected = dict(CONTRACT_DEFAULTS)
    wrong_expected["default_model"] = "jev-deliberate-mismatch-alias"

    results = run_checks(wrong_expected)
    mismatched_assertion = next((r for r in results if r["name"] == "default_model"), None)

    failed_as_expected = mismatched_assertion and mismatched_assertion["status"] == "FAIL"

    if args.json:
        print(
            json.dumps(
                {
                    "selftest": "PASS" if failed_as_expected else "FAIL",
                    "injected_mismatch": {
                        "name": "default_model",
                        "expected": wrong_expected["default_model"],
                        "observed": mismatched_assertion["observed"] if mismatched_assertion else None,
                        "status": mismatched_assertion["status"] if mismatched_assertion else None,
                    },
                    "confirmed_can_fail": failed_as_expected,
                },
                indent=2,
            )
        )
    else:
        print("jev_contract_check selftest:")
        print(
            f"  injected deliberate mismatch: default_model expected='{wrong_expected['default_model']}'"
        )
        if failed_as_expected:
            print(
                f"  result: FAIL reported as expected (observed='{mismatched_assertion['observed']}')"
            )
            print("  selftest: PASS (checker correctly detects contract divergence)")
        else:
            print("  selftest: FAIL (checker did not report FAIL on mismatched value)")

    return 0 if failed_as_expected else 1


def main():
    ap = argparse.ArgumentParser(description="Check jev-mcp against the Jev Client Contract.")
    ap.add_argument("--json", action="store_true", help="output results in JSON format")
    ap.add_argument(
        "--selftest",
        action="store_true",
        help="verify checker detects failure against wrong expected value",
    )
    args = ap.parse_args()

    if args.selftest:
        return run_selftest(args)

    results = run_checks()
    all_pass = all(r["status"] in ("PASS", "SKIP") for r in results)

    if args.json:
        print(
            json.dumps(
                {
                    "status": "PASS" if all_pass else "FAIL",
                    "assertions": results,
                },
                indent=2,
            )
        )
    else:
        for r in results:
            print(f"{r['status']} [{r['name']}]: {r['observed']}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
