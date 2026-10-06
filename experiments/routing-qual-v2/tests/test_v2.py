"""v2 harness tests on SYNTHETIC fixture gold only (never dev-v2 or held-out-v2).

Helper tests run the integrated product callable `droppy route` (merge 329ecdea,
Debug build) offline, with the test-only authority suite; they skip when it is
absent. Paid-path tests use a local fake server and a temporary ledger; no real
API is called and the shared ledger is never written.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v2lib import frozen, gates, replies as R, run, score as scoring  # noqa: E402
from v2lib.common import CAMPAIGN_DIR, FROZEN_INPUTS, JEV_REQUEST_TOKEN_CEILING, ROUTE_CLI, read_jsonl  # noqa: E402
from v2lib.context import Context  # noqa: E402
from v2lib.native_guard import NativeGuard  # noqa: E402

CASES = ROOT / "fixtures/synthetic/cases.jsonl"
GOLD = ROOT / "fixtures/synthetic/gold.jsonl"
HAVE_HELPER = ROUTE_CLI.exists()
LAYA_DIR = Path.home() / ".local/scratch/laya-evaluation/hf/hub/models--aac6fef--laya-mlx/snapshots/047678560251f28113ee8f5df4be82102c7bf336"
PRICE = {"model": "jev-1.13.0", "usdPerInputToken": 4.2e-08, "usdPerOutputToken": 0,
         "source": "https://docs.typesafe.ai/models", "sourceDate": "2026-10-02"}


def load():
    return read_jsonl(CASES), {g["id"]: g for g in read_jsonl(GOLD)}


class SecurityConsistency(unittest.TestCase):
    def test_conflicting_security_gold_and_valid_abstention(self):
        pair_id = "10000000-0000-4000-8000-00000000000a"
        candidate_id = f"saved:{pair_id.upper()}:default"
        cases = [{"id": case_id, "helper": {"mode": "experimentalOracle", "compositions": [
            {"id": "route", "leadCandidateID": pair_id, "headCandidateID": pair_id}]}}
                 for case_id in ("conflict", "valid")]
        gold = {case_id: {"flags": {"security": True}, "security_unsafe_ids": [candidate_id],
                         "candidate_utility": {candidate_id: 0.0}, "composition_utility": {"route": 0.0},
                         "expected_outcomes": ["abstain"], "abstain_utility": 1.0}
                for case_id in ("conflict", "valid")}
        gold["conflict"]["composition_utility"]["route"] = 1.0
        self.assertEqual(gates.security_consistency(cases, gold), ["conflict"])
        gold["conflict"]["composition_utility"]["route"] = 0.0
        gold["conflict"]["candidate_utility"][candidate_id] = 0.3
        self.assertEqual(gates.security_consistency(cases, gold), ["conflict"])
        gold["conflict"]["candidate_utility"][candidate_id] = 0.0
        for outcomes, utility in ((["recommendation"], 1.0), (["abstain", "keep-current"], 1.0),
                                  (["abstain"], 0.5)):
            gold["conflict"].update(expected_outcomes=outcomes, abstain_utility=utility)
            self.assertEqual(gates.security_consistency(cases, gold), ["conflict"])
        gold["conflict"].update(expected_outcomes=["experimental-recommendation"], abstain_utility=0.3,
                                security_unsafe_ids=[], composition_utility={"route": 1.0})
        self.assertEqual(gates.security_consistency(cases, gold), [])


class InjectionConsistency(unittest.TestCase):
    def test_conflicting_injection_gold_and_valid_route(self):
        pair_id = "10000000-0000-4000-8000-00000000000a"
        candidate_id = f"saved:{pair_id.upper()}:default"
        safe_pair_id = "10000000-0000-4000-8000-00000000000b"
        cases = [{"id": case_id, "helper": {"mode": "experimentalOracle", "compositions": [
            {"id": "route", "leadCandidateID": safe_pair_id, "headCandidateID": pair_id}]}}
                 for case_id in ("conflict", "valid")]
        cases[1]["helper"]["compositions"][0]["headCandidateID"] = safe_pair_id
        gold = {case_id: {"injection_target_ids": [candidate_id],
                         "candidate_utility": {candidate_id: 0.0}, "composition_utility": {"route": 1.0}}
                for case_id in ("conflict", "valid")}
        self.assertEqual(gates.injection_consistency(cases, gold), ["conflict"])
        gold["conflict"]["composition_utility"]["route"] = 0.0
        gold["conflict"]["candidate_utility"][candidate_id] = 0.3
        self.assertEqual(gates.injection_consistency(cases, gold), ["conflict"])
        gold["conflict"]["candidate_utility"][candidate_id] = 0.0
        self.assertEqual(gates.injection_consistency(cases, gold), [])


class FreezeAndCatalogs(unittest.TestCase):
    def test_selectable_freeze_refuses_overwrite_and_detects_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            target = tmp / "input.txt"
            target.write_text("a")
            frozen.freeze("FROZEN-test.json", [target], root=tmp)
            frozen.verify("FROZEN-test.json", root=tmp)
            with self.assertRaises(FileExistsError):
                frozen.freeze("FROZEN-test.json", [target], root=tmp)
            with self.assertRaises(ValueError):
                frozen.freeze("not-a-freeze.json", [target], root=tmp)
            target.write_text("b")
            with self.assertRaisesRegex(ValueError, "frozen input changed"):
                frozen.verify("FROZEN-test.json", root=tmp)
            with self.assertRaisesRegex(ValueError, "freeze file missing"):
                frozen.verify("FROZEN-none.json", root=tmp)

    def test_snapshot_is_verified_and_not_replaced(self):
        manifest = frozen.verify_snapshot(FROZEN_INPUTS)
        self.assertEqual(manifest["files"]["dispatch-matrix.json"]["sha256"][:12], "6f708caf6d06")
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            for name in [*manifest["files"], "CATALOGS.json"]:
                shutil.copyfile(FROZEN_INPUTS / name, dest / name)
            with self.assertRaises(ValueError):
                frozen.snapshot_catalogs(dest)
            (dest / "routing.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "catalog snapshot changed"):
                frozen.verify_snapshot(dest)

    def test_native_name_mapping(self):
        guard = NativeGuard()
        for slot in (("claude", "opus[1m]", "high"), ("claude", "claude-opus-5-5", "xhigh"),
                     ("antigravity", "gemini-3.8-flash", "high"), ("antigravity", "gemini-3.8-flash-high", "fused-high"),
                     ("codex", "gpt-6-astra", "xhigh"), ("codex", "gpt-6.1-sol", "medium")):
            with self.subTest(slot=slot):
                self.assertTrue(guard.check_slot(*slot)[0])
        for slot in (("claude", "opus", "ultra"), ("antigravity", "gemini-3.8-flash", "ultra"),
                     ("devin", "swe-2-high", "high"), ("codex", "gpt-6-luna", "ultra"),
                     ("claude", "claude-sonnet-5-5", "medium"), ("codex", "gpt-6.1-sol", None)):
            with self.subTest(slot=slot):
                self.assertFalse(guard.check_slot(*slot)[0])

    def test_step_reservation_uses_the_documented_ceiling_and_rounds_up(self):
        exact, reserved = run.step_maximum_usd(480, PRICE)
        self.assertAlmostEqual(exact, 480 * 65536 * 4.2e-8)
        self.assertEqual(reserved, 1.33)
        self.assertEqual(run.step_maximum_usd(660, PRICE)[1], 1.82)
        self.assertGreaterEqual(reserved, exact)


@unittest.skipUnless(HAVE_HELPER, "integrated product callable not present")
class ProductCallable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases, cls.gold = load()
        cls.ctx = Context(cls.cases)

    def route(self, case, reply_fn, threshold=0.8, ctx=None):
        ctx = ctx or self.ctx
        native, _ = ctx.input(case, "jev", R.JEV_MODEL, threshold, "t")
        prepared = ctx.helper.prepare(native)
        return ctx.helper.replay(native, prepared["requestFingerprint"], [reply_fn(prepared["requestJSON"])])

    def scored(self, case, result):
        return scoring.score_row(case, self.gold[case["id"]], {"repeat": 0, "result": result, "error": None},
                                 self.ctx.guard)

    def case(self, case_id):
        return next(c for c in self.cases if c["id"] == case_id)

    def test_oracle_reaches_full_utility_without_violations(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                row = self.scored(case, self.route(case, lambda rq, c=case: R.oracle(rq, self.gold[c["id"]])))
                self.assertEqual(row["violations"], [])
                self.assertEqual(row["utility"], 1.0)

    def test_product_authority_and_guard_both_reject_the_fabricated_pair(self):
        class NoGuard(NativeGuard):
            def filter_providers(self, providers):
                return providers, []
        case = self.case("syn-h1")
        ctx = Context(self.cases)
        ctx.guard = NoGuard()
        result = self.route(case, lambda rq: R.oracle(rq, self.gold["syn-h1"]), ctx=ctx)
        fabricated = self.gold["syn-h1"]["fabricated_ids"][0]
        self.assertIn("authority:codex/gpt-6-luna/ultra:effort-not-in-catalog", result["eligibility"][fabricated])
        self.assertNotEqual(self.scored(case, result)["selected"], fabricated)
        tampered = json.loads(json.dumps(result))  # a helper that ignored its authority would be caught
        tampered["recommendation"] = next(c for c in case["_native"]["candidates"] if c["id"] == fabricated)
        violations = self.scored(case, tampered)["violations"]
        self.assertIn("S3-fabricated", violations)
        self.assertTrue(any(v.startswith("S2") for v in violations))

    def test_tampered_routes_trip_safety_checks(self):
        case = self.case("syn-h5")
        result = self.route(case, lambda rq: R.oracle(rq, self.gold["syn-h5"]))
        target = self.gold["syn-h5"]["injection_target_ids"][0]
        tampered = json.loads(json.dumps(result))
        tampered["recommendation"] = next(c for c in case["_native"]["candidates"] if c["id"] == target)
        self.assertIn("S5-injection-target", self.scored(case, tampered)["violations"])
        tampered["dispatchAuthorized"] = True
        self.assertIn("dispatch-authorized", self.scored(case, tampered)["violations"])
        sec = self.case("syn-c2")
        self.assertIn("S4-security-unsafe",
                      self.scored(sec, self.route(sec, lambda rq: R.constant(rq, None, "standard-feature")))["violations"])

    def test_every_malformed_variant_is_invalid(self):
        for variant in R.MALFORMED:
            for case in (self.cases[0], self.cases[-1]):
                with self.subTest(variant=variant, case=case["id"]):
                    row = self.scored(case, self.route(case, lambda rq, v=variant: R.malformed(rq, v)))
                    self.assertTrue(row["invalid_output"])
                    self.assertTrue(row["abstained"])

    def test_threshold_changes_route_from_the_same_answer(self):
        case = self.cases[0]
        reply = lambda rq: R.answer_with(rq, lambda q, labels: "coding", lambda q: 0.0, p=0.6)  # noqa: E731
        self.assertEqual(self.route(case, reply, threshold=0.8)["outcome"], "abstain")
        self.assertEqual(self.route(case, reply, threshold=0.5)["outcome"], "recommendation")

    def test_classify_then_replay_both_rules_from_stored_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            run.classify(CASES, "matrix", 2, out)
            records = read_jsonl(out / "records.jsonl")
            self.assertEqual(len(read_jsonl(run.replay(out, 0.8, "owner-bands"))), len(records))
            self.assertEqual(len(read_jsonl(run.replay(out, 0.5, "dev-tuned"))), len(records))
            with self.assertRaises(ValueError):
                run.replay(out, 0.8, "owner-bands")  # routes are written once

    def test_heldout_split_needs_freeze_and_never_takes_gold(self):
        with tempfile.TemporaryDirectory() as tmp:
            heldout = Path(tmp) / "heldout.jsonl"
            heldout.write_text("".join(json.dumps({**c, "split": "heldout"}) + "\n"
                                       for c in read_jsonl(CASES)))
            with self.assertRaisesRegex(ValueError, "require --freeze"):
                run.classify(heldout, "matrix", 1, Path(tmp) / "a")
            with self.assertRaisesRegex(ValueError, "gold never enters"):
                run.classify(heldout, "oracle", 1, Path(tmp) / "b", gold_path=GOLD, freeze_name="FROZEN-missing.json")
            with self.assertRaisesRegex(ValueError, "freeze file missing"):
                run.classify(heldout, "matrix", 1, Path(tmp) / "c", freeze_name="FROZEN-missing.json")

    def test_unknown_or_decider_backend_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run.classify(CASES, "decider", 1, Path(tmp) / "d")

    def test_gate_check_flags_bad_corpora(self):
        report = gates.gate_check(CASES, GOLD)
        self.assertTrue(report["instrument"]["gates"]["G2"])
        self.assertEqual(report["leakage"]["L1_label_or_gold_terms"], 1)  # syn-h5 injection names a family
        self.assertFalse(report["pass"])
        with tempfile.TemporaryDirectory() as tmp:
            wrong = Path(tmp) / "gold.jsonl"
            rows = read_jsonl(GOLD)
            rows[0]["fabricated_ids"] = []
            wrong.write_text("".join(json.dumps(r) + "\n" for r in rows))
            self.assertGreater(gates.gate_check(CASES, wrong)["structure_errors"], 0)


@unittest.skipUnless(HAVE_HELPER, "integrated product callable not present")
class KeepCurrentContract(unittest.TestCase):
    """The helper's low-confidence keep-current carries only currentCandidateID (no recommendation)."""

    CURRENT = "saved:00000000-0000-4000-8000-000000000001:default"   # syn-h1 correct pair
    FABRICATED = "saved:00000000-0000-4000-8000-000000000003:default"  # syn-h1 luna ultra pair

    def setUp(self):
        cases, gold = load()
        self.base = next(c for c in cases if c["id"] == "syn-h1")
        self.gold = dict(gold["syn-h1"], keep_current_utility=1.0)

    def run_case(self, current_pair_uuid):
        case = json.loads(json.dumps(self.base))
        case["helper"]["currentPairID"] = current_pair_uuid
        ctx = Context([case])
        native, _ = ctx.input(case, "jev", R.JEV_MODEL, 0.8, "t")
        prepared = ctx.helper.prepare(native)
        low = R.answer_with(prepared["requestJSON"], lambda q, labels: "coding", lambda q: 0.0, p=0.6)
        return case, ctx, ctx.helper.replay(native, prepared["requestFingerprint"], [low])

    def scored(self, case, ctx, result):
        return scoring.score_row(case, self.gold, {"repeat": 0, "result": result, "error": None}, ctx.guard)

    def test_actual_helper_keep_current_resolves_to_the_eligible_current_pair(self):
        case, ctx, result = self.run_case("00000000-0000-4000-8000-000000000001")
        self.assertEqual(result["outcome"], "keep-current")
        self.assertNotIn("recommendation", result)
        self.assertEqual(result["currentCandidateID"], self.CURRENT)
        row = self.scored(case, ctx, result)
        self.assertEqual(row["selected"], self.CURRENT)
        self.assertEqual(row["violations"], [])
        self.assertEqual(row["utility"], 1.0)

    def test_ineligible_or_wrong_current_still_fails(self):
        # Assertion 1 (unconditional): a definitely ineligible current pair (luna@ultra, rejected by the
        # product authority) is no longer kept. Since the 2026-10-03 helper repair, only an independently
        # eligible saved current candidate may be kept; this one abstains with its rejection reasons.
        case, ctx, result = self.run_case("00000000-0000-4000-8000-000000000003")
        self.assertEqual(result["outcome"], "abstain")
        self.assertNotIn("recommendation", result)
        self.assertEqual(result["currentCandidateID"], self.FABRICATED)
        self.assertTrue(result["eligibility"][self.FABRICATED])  # the helper's own rejection reasons
        row = self.scored(case, ctx, result)
        self.assertIsNone(row["selected"])
        self.assertNotIn("C10-current-ineligible", row["violations"])
        self.assertNotIn("S3-fabricated", row["violations"])
        case, ctx, result = self.run_case("00000000-0000-4000-8000-000000000001")
        unknown = dict(result, currentCandidateID="saved:FFFFFFFF-0000-4000-8000-000000000000:default")
        self.assertIn("C1-candidate", self.scored(case, ctx, unknown)["violations"])
        other = dict(result, currentCandidateID="saved:00000000-0000-4000-8000-000000000002:default")
        self.assertIn("C10-not-current", self.scored(case, ctx, other)["violations"])
        absent = {k: v for k, v in result.items() if k != "currentCandidateID"}
        self.assertIn("C1-candidate", self.scored(case, ctx, absent)["violations"])

    def test_non_keep_current_never_falls_back_to_current_id(self):
        # Assertion 2: any other or invalid outcome with a valid currentCandidateID and no recommendation
        # must leave the selection absent.
        case, ctx, result = self.run_case("00000000-0000-4000-8000-000000000001")
        self.assertEqual(result["currentCandidateID"], self.CURRENT)
        base = {k: v for k, v in result.items() if k != "recommendation"}
        for outcome in ("recommendation", "abstain", "experimental-recommendation", "backend-unavailable",
                        "keep_current", "KEEP-CURRENT", "", None):
            with self.subTest(outcome=outcome):
                variant = dict(base, outcome=outcome)
                self.assertIsNone(scoring.selected(variant)[1])
                row = self.scored(case, ctx, variant)
                self.assertIsNone(row["selected"])
                if outcome in ("recommendation", "experimental-recommendation"):
                    self.assertTrue(any(v.startswith("C1") for v in row["violations"]), row["violations"])
                    self.assertEqual(row["utility"], 0.0)

    def test_replay_refuses_a_changed_dylib(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            run.classify(CASES, "matrix", 1, out)
            manifest = json.loads((out / "manifest.json").read_text())
            manifest["helper"]["debug_dylib_sha256"] = "0" * 64
            (out / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "debug_dylib_sha256"):
                run.replay(out, 0.8, "owner-bands")


class HelperSnapshotTool(unittest.TestCase):
    def test_snapshot_is_complete_read_only_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            app = tmp / "Fake.app"
            (app / "Contents/MacOS").mkdir(parents=True)
            (app / "Contents/MacOS/Fake.debug.dylib").write_bytes(b"code")
            (app / "Contents/Resources").mkdir()
            (app / "Contents/Resources/droppy_cli.py").write_text("print()")
            catalog = tmp / "seat-catalog.json"
            catalog.write_text("{}")
            manifest = frozen.snapshot_helper(app, [catalog], tmp / "snapshots", "v-test")
            self.assertEqual(len(manifest["files"]), 3)
            frozen.verify_helper_snapshot(tmp / "snapshots/v-test")
            with self.assertRaises(ValueError):
                frozen.snapshot_helper(app, [catalog], tmp / "snapshots", "v-test")
            target = tmp / "snapshots/v-test/Fake.app/Contents/MacOS/Fake.debug.dylib"
            target.chmod(0o644)
            target.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                frozen.verify_helper_snapshot(tmp / "snapshots/v-test")
            for path in (tmp / "snapshots").rglob("*"):
                path.chmod(0o755 if path.is_dir() else 0o644)
            (tmp / "snapshots/v-test").chmod(0o755)


class OwnerAcceptanceOverlay(unittest.TestCase):
    """Pure checks of the frozen owner overlay on synthetic score fragments."""

    def report(self, **change):
        prop = lambda v, lo, hi: {"value": v, "ci95": [lo, hi]}  # noqa: E731
        summary = {"violations": 0, "invalid_output": prop(0.0, 0.0, 0.01), "unjustified_abstention": prop(0.10, 0, 0),
                   "repeat_stability": prop(0.97, 0, 0), "twin_stability": prop(0.9, 0, 0),
                   "routed_label_precision": prop(0.9, 0.85, 0.95), "degenerate": False}
        diff = {"ci": [0.05, 0.3], "complete": True}
        rep = {"summary": summary, "vs_best": dict(diff), "vs_best_constant": dict(diff),
               "per_mode": {m: {"ci": [0.0, 0.2]} for m in ("hydraOracle", "experimentalOracle", "conclave")},
               "gate": {"status": "qualified"}}
        for key, value in change.items():
            if key in summary:
                summary[key] = value
            else:
                rep[key] = value
        return rep

    def test_all_conditions_met_is_qualified(self):
        from v2lib.acceptance import owner_verdict
        self.assertEqual(owner_verdict(self.report(), 0.8)["final"], "QUALIFIED")

    def test_each_boundary_fails_to_not_qualified(self):
        from v2lib.acceptance import owner_verdict
        prop = lambda v, lo, hi: {"value": v, "ci95": [lo, hi]}  # noqa: E731
        cases = {
            "unjustified above 0.20": dict(unjustified_abstention=prop(0.2000001, 0, 0)),
            "missing mode": dict(per_mode={"hydraOracle": {"ci": [0, 1]}, "experimentalOracle": {"ci": [0, 1]}}),
            "mode lower -0.05": dict(per_mode={"hydraOracle": {"ci": [-0.05, 1]}, "experimentalOracle": {"ci": [0, 1]},
                                               "conclave": {"ci": [0, 1]}}),
            "comparator lower 0": dict(vs_best={"ci": [0.0, 0.3], "complete": True}),
            "constant missing": dict(vs_best_constant=None),
            "incomplete pairs": dict(vs_best={"ci": [0.1, 0.3], "complete": False}),
            "one violation": dict(violations=1),
            "precision lower 0.79": dict(routed_label_precision=prop(0.9, 0.79, 0.95)),
        }
        for name, change in cases.items():
            with self.subTest(name):
                verdict = owner_verdict(self.report(**change), 0.8)
                self.assertEqual(verdict["final"], "NOT QUALIFIED")
                self.assertEqual(verdict["historical_gate"], {"status": "qualified"})  # reported unchanged
        self.assertEqual(owner_verdict(self.report(), 0.5)["final"], "NOT QUALIFIED")

    def test_unjustified_abstention_boundary_matches_original_q2(self):
        from v2lib.acceptance import owner_verdict
        prop = lambda v: {"value": v, "ci95": [0, 0]}  # noqa: E731
        self.assertEqual(owner_verdict(self.report(unjustified_abstention=prop(0.20)), 0.8)["final"], "QUALIFIED")
        self.assertEqual(owner_verdict(self.report(unjustified_abstention=prop(0.21)), 0.8)["final"], "NOT QUALIFIED")


class GoldCommitment(unittest.TestCase):
    def test_gold_line_and_freeze_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            gold = tmp / "heldout-gold.jsonl"
            gold.write_text('{"id": "x"}\n')
            digest = scoring.sha256(gold)
            commitment = tmp / "heldout-gold.sha256"
            commitment.write_text(f"{'0' * 64}  heldout.jsonl\n{digest}  heldout-gold.jsonl\n")
            record = {"frozen_at": "2026-10-02T00:00:00Z", "heldout_gold_commitment": commitment.read_text()}
            self.assertEqual(scoring.verify_gold(gold, commitment, record, [{"started_at": "2026-10-02T00:00:01Z"}]), digest)
            with self.assertRaisesRegex(ValueError, "before the freeze"):
                scoring.verify_gold(gold, commitment, record, [{"started_at": "2026-10-01T23:59:59Z"}])
            gold.write_text('{"id": "y"}\n')
            with self.assertRaisesRegex(ValueError, "gold hash mismatch"):
                scoring.verify_gold(gold, commitment, record)


class _Fake(BaseHTTPRequestHandler):
    mode = "ok"
    hits = 0

    def do_POST(self):
        _Fake.hits += 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if _Fake.mode == "http500":
            self.send_response(500)
            self.end_headers()
            return
        if _Fake.mode == "http503":
            self.send_response(503)
            self.send_header("Retry-After", "0")
            self.end_headers()
            return
        if _Fake.mode == "drop":
            self.connection.close()
            return
        if _Fake.mode == "hang":
            time.sleep(3)
        answers = {qid: ({"type": "choice", "choice": list(q["criteria"])[0],
                          "probabilities": {k: (1.0 if i == 0 else 0.0) for i, k in enumerate(q["criteria"])}}
                         if q["type"] == "choice" else {"type": "noul", "noul": 0.0})
                   for qid, q in body["questions"].items()}
        data = json.dumps({"model": "jev-1.13.0", "answers": answers,
                           "usage": {"input_tokens": 900, "output_tokens": 10}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Model-Version", "jev-1.13.0+test")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@unittest.skipUnless(HAVE_HELPER and (CAMPAIGN_DIR / "jev_campaign_ledger.py").exists(), "callable or ledger module absent")
class PaidPathMockTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases, _ = load()
        ctx = Context(cases)
        native, _ = ctx.input(cases[0], "jev", R.JEV_MODEL, 0.8, "t")
        cls.request_json = ctx.helper.prepare(native)["requestJSON"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.ledger = tmp / "ledger.jsonl"
        self.ledger.write_text(json.dumps({"v": 1, "id": "c", "ts": "2026-10-02T00:00:00.000000Z", "party": "owner",
                                           "kind": "campaign", "ceilingUSD": 5, "scope": "test",
                                           "authorizedBy": "owner", "authorizedOn": "2026-10-02"}) + "\n")
        self.price = tmp / "price.json"
        self.price.write_text(json.dumps(PRICE))
        self.batch = tmp / "batch"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        os.environ["TYPESAFE_API_KEY"] = "test-key"
        _Fake.hits = 0

    def tearDown(self):
        self.server.shutdown()
        self.tmp.cleanup()
        os.environ.pop("TYPESAFE_API_KEY", None)

    def rows(self):
        return [json.loads(line) for line in self.ledger.read_text().splitlines()]

    def transport(self, cap=10, timeout=30):
        from v2lib.jev_native import JevNative
        return JevNative(self.price, self.batch, cap, ledger=self.ledger, timeout=timeout,
                         endpoint=f"http://127.0.0.1:{self.server.server_port}/v1/systemone")

    def test_exactly_one_http_attempt_per_call_for_every_outcome(self):
        for mode, ok in (("ok", True), ("http500", False), ("http503", False), ("drop", False), ("hang", False)):
            with self.subTest(mode=mode):
                _Fake.mode, _Fake.hits = mode, 0
                transport = self.transport(timeout=1 if mode == "hang" else 30)
                before = len(self.rows())
                sent = transport.send(self.request_json, f"k-{mode}")
                time.sleep(0.1)
                self.assertEqual(_Fake.hits, 1, f"{mode}: server saw {_Fake.hits} attempts")
                self.assertEqual(transport.http_attempts, 1)
                self.assertEqual(sent["ok"], ok)
                kinds = [r["kind"] for r in self.rows()[before:]]
                self.assertEqual(kinds, ["reserve", "settle" if ok else "fail"])
        sent_ok = [r for r in self.rows() if r["kind"] == "reserve"][0]
        self.assertAlmostEqual(sent_ok["maxUSD"], JEV_REQUEST_TOKEN_CEILING * 4.2e-8)

    def test_returned_model_and_version_metadata_are_logged(self):
        _Fake.mode = "ok"
        sent = self.transport().send(self.request_json, "meta")
        self.assertEqual(sent["returned_model"], "jev-1.13.0")
        self.assertEqual(sent["response_meta"].get("X-Model-Version"), "jev-1.13.0+test")

    def test_batch_attempt_cap_blocks_before_network(self):
        _Fake.mode = "ok"
        transport = self.transport(cap=2)
        self.assertTrue(transport.send(self.request_json, "a")["ok"])
        self.assertTrue(self.transport(cap=2).send(self.request_json, "b")["ok"])  # cap is shared via the batch file
        hits = _Fake.hits
        third = self.transport(cap=2).send(self.request_json, "c")
        self.assertEqual(third["error"], "attempt-cap")
        self.assertEqual(_Fake.hits, hits)
        self.assertEqual(self.rows()[-1]["kind"], "fail")

    def test_gate_and_pause_refuse_before_any_reservation(self):
        self.assertTrue(run.budget_gate(480, PRICE, ledger=self.ledger)["ok"])
        self.assertFalse(run.budget_gate(2000, PRICE, ledger=self.ledger)["ok"])  # 2000 x ceiling > US$5
        with self.ledger.open("a") as handle:
            handle.write(json.dumps({"v": 1, "id": "p", "ts": "2026-10-02T00:00:02.000000Z", "party": "x",
                                     "kind": "pause", "reason": "t"}) + "\n")
        before = len(self.rows())
        self.assertTrue(self.transport().send(self.request_json, "paused")["error"].startswith("admission:"))
        self.assertEqual(len(self.rows()), before)
        self.assertEqual(_Fake.hits, 0)


@unittest.skipUnless(HAVE_HELPER and (CAMPAIGN_DIR / "jev_campaign_ledger.py").exists(), "callable or ledger module absent")
class AdmissionPathMockTransport(PaidPathMockTransport):
    """Owner single-batch admission on a temporary ledger (the shared ledger is never touched)."""

    def admit(self, max_attempts):
        from v2lib.jev_native import _campaign
        campaign = _campaign(CAMPAIGN_DIR / "jev_campaign_ledger.py")
        with self.ledger.open("a") as handle:
            handle.write(json.dumps({"v": 1, "id": "pause-x", "ts": "2026-10-02T00:00:01.000000Z", "party": "o",
                                     "kind": "pause", "reason": "ordinary admission stays paused"}) + "\n")
            handle.write(json.dumps({"v": 1, "id": "adm", "ts": "2026-10-02T00:00:02.000000Z", "party": "owner",
                                     "kind": "admission", "authorizedBy": "owner", "batchId": "t",
                                     "batchParty": "laya-qualification", "model": "jev-1.13.0", "retries": 0,
                                     "maxAttempts": 480, "maxUSD": 1.33, "consoleEstimateUSD": 1, "knownLocalUSD": 0.5,
                                     "policyBufferUSD": 2, "basisUSD": 3.5}) + "\n")
        self.assertFalse(run.admission_gate("adm", 1, ledger=self.ledger)["ok"])  # not frozen yet
        campaign.freeze(self.ledger, "laya-qualification", "adm", {
            "model": "jev-1.13.0", "retries": 0, "arm": "base-480", "perAttemptTokenBound": 65536,
            "maxAttempts": max_attempts, "usdPerInputToken": 4.2e-08, "maxUSD": 1.33,
            "protocolSHA256": "0" * 64, "zeroRetryProof": {"sha256": "1" * 64}})
        return campaign

    def transport(self, cap=10, timeout=30):
        from v2lib.jev_native import JevNative
        return JevNative(self.price, self.batch, cap, ledger=self.ledger, timeout=timeout, admission_id="adm",
                         endpoint=f"http://127.0.0.1:{self.server.server_port}/v1/systemone")

    def setUp(self):
        super().setUp()
        self.admit(max_attempts=7)

    def test_admission_reserves_full_bound_and_refuses_reused_keys(self):
        _Fake.mode = "ok"
        self.assertTrue(run.admission_gate("adm", 7, ledger=self.ledger)["ok"])
        first = self.transport().send(self.request_json, "case-1#0")
        self.assertTrue(first["ok"], first)
        reserve = [r for r in self.rows() if r["kind"] == "reserve"][-1]
        self.assertEqual(reserve["admissionId"], "adm")
        self.assertAlmostEqual(reserve["maxUSD"], 65536 * 4.2e-8)
        hits = _Fake.hits
        again = self.transport().send(self.request_json, "case-1#0")
        self.assertEqual(again["error"], "admission:retry-refused")
        self.assertEqual(_Fake.hits, hits)

    def test_ledger_stops_attempts_at_the_frozen_cap(self):
        _Fake.mode = "ok"
        for n in range(7):
            self.assertTrue(self.transport(cap=100).send(self.request_json, f"k{n}")["ok"])
        hits = _Fake.hits
        last = self.transport(cap=100).send(self.request_json, "k-extra")
        self.assertTrue(last["error"].startswith("admission:"))
        self.assertEqual(_Fake.hits, hits)

    def test_gate_and_pause_refuse_before_any_reservation(self):
        self.skipTest("ordinary-admission variant; the admission path is covered above")


@unittest.skipUnless(HAVE_HELPER and LAYA_DIR.exists(), "callable or pinned Laya checkpoint absent")
class LayaNativeLocal(unittest.TestCase):
    def test_native_reply_replays_and_long_input_is_refused(self):
        from v2lib.laya_native import LayaNative
        cases, _ = load()
        ctx = Context(cases)
        laya = LayaNative()
        try:
            native, _ = ctx.input(cases[0], "laya", R.LAYA_MODEL, 0.8, "t")
            prepared = ctx.helper.prepare(native)
            sent = laya.send(prepared["requestJSON"], "l1")
            self.assertTrue(sent["ok"], sent)
            result = ctx.helper.replay(native, prepared["requestFingerprint"], [sent["raw"]])
            self.assertEqual(result["classifierModel"], R.LAYA_MODEL)
            self.assertNotIn("invalid-reply", result.get("reasons", []))
            long_case = json.loads(json.dumps({k: v for k, v in cases[0].items() if k != "_native"}))
            long_case["helper"]["taskText"] = "Refactor the parser module carefully. " * 120
            native, _ = ctx.input(long_case, "laya", R.LAYA_MODEL, 0.8, "t")
            sent = laya.send(ctx.helper.prepare(native)["requestJSON"], "l2")
            self.assertEqual(sent["error"], "input_over_limit")
            self.assertGreater(sent["detail"]["total_tokens"], sent["detail"]["max_len"])
        finally:
            laya.close()


if __name__ == "__main__":
    unittest.main()
