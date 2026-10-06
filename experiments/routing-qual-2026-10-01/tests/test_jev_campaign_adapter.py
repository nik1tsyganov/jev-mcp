"""Offline checks of adapters/jev.py against the shared campaign ledger.

A local HTTP server stands in for Jev; the ledger, price file and spend log are
temporary. No real API call and no write to the shared campaign ledger.
"""
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as HTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CAMPAIGN_MODULE = Path.home() / ".local/scratch/jev-testing-campaign-2026-10/jev_campaign_ledger.py"

from questions import LABELS, build_request  # noqa: E402

CASE = {"id": "t-1", "mode": "hydraOracle", "task_text": "Rename one label.", "metadata": {}, "snapshot": {}}
PRICE = {"model": "jev-1.13.0", "usdPerInputToken": 4.2e-08, "usdPerOutputToken": 0,
         "source": "https://docs.typesafe.ai/models", "sourceDate": "2026-10-02"}


def good_body(model="jev-1.13.0", usage=True):
    answers = {}
    for qid, labels in LABELS.items():
        probs = {label: 0.0 for label in labels}
        probs[labels[0]] = 1.0
        answers[qid] = {"type": "choice", "choice": labels[0], "confidence": 1.0, "probabilities": probs}
    body = {"model": model, "answers": answers}
    if usage:
        body["usage"] = {"input_tokens": 1000, "output_tokens": 300}
    return json.dumps(body).encode()


class Handler(BaseHTTPRequestHandler):
    mode = "ok"
    hits = 0

    def do_POST(self):
        Handler.hits += 1
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if Handler.mode == "slow":
            # Hold the reply so every racing reservation is still open.
            import time
            time.sleep(3)
        if Handler.mode == "drop":
            self.connection.close()
            return
        status, body = {"ok": (200, good_body()), "http500": (500, b'{"error":"x"}'),
                        "nousage": (200, good_body(usage=False)),
                        "wrongmodel": (200, good_body(model="jev-9.9.9")),
                        "slow": (200, good_body())}[Handler.mode]
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _race_worker(args):
    ledger, price_path, base, spend = args
    os.environ["TYPESAFE_API_KEY"] = "test-key"
    os.environ["TYPESAFE_SPEND_LOG"] = spend
    from adapters import jev
    adapter = jev.make_adapter({"campaign_ledger": ledger, "price_file": price_path, "api_base": base,
                                "campaign_module": str(CAMPAIGN_MODULE), "timeout_s": 5})
    return adapter.classify(build_request(CASE))["error"]


@unittest.skipUnless(CAMPAIGN_MODULE.exists(), "shared campaign module not present")
class CampaignAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.ledger = tmp / "ledger.jsonl"
        self.price = tmp / "price.json"
        self.spend = tmp / "spend.jsonl"
        self.price.write_text(json.dumps(PRICE))
        os.environ["TYPESAFE_API_KEY"] = "test-key"
        os.environ["TYPESAFE_SPEND_LOG"] = str(self.spend)
        self.campaign_row(50)
        Handler.hits = 0

    def tearDown(self):
        self.tmp.cleanup()

    def campaign_row(self, ceiling):
        row = {"v": 1, "id": "c-1", "ts": "2026-10-02T00:00:00.000000Z", "party": "owner", "kind": "campaign",
               "ceilingUSD": ceiling, "scope": "test", "authorizedBy": "owner", "authorizedOn": "2026-10-02"}
        self.ledger.write_text(json.dumps(row) + "\n")

    def adapter(self):
        from adapters import jev
        return jev.make_adapter({"campaign_ledger": str(self.ledger), "price_file": str(self.price),
                                 "api_base": self.base, "campaign_module": str(CAMPAIGN_MODULE), "timeout_s": 5})

    def rows(self):
        return [json.loads(line) for line in self.ledger.read_text().splitlines() if line.strip()]

    def kinds(self):
        return [row["kind"] for row in self.rows()]

    def test_valid_reply_settles_and_tags_spend_log(self):
        Handler.mode = "ok"
        result = self.adapter().classify(build_request(CASE))
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(self.kinds(), ["campaign", "reserve", "settle"])
        settle = self.rows()[2]
        self.assertEqual(settle["inputTokens"], 1000)
        self.assertAlmostEqual(settle["usd"], 1000 * 4.2e-08)
        spend = json.loads(self.spend.read_text().splitlines()[-1])
        self.assertEqual(spend["campaignReserveId"], self.rows()[1]["id"])

    def test_failures_record_fail_and_keep_reservation(self):
        for mode, expected in (("http500", "transport"), ("nousage", "usage-missing"),
                               ("wrongmodel", "resolved-model-mismatch"), ("drop", None)):
            with self.subTest(mode=mode):
                self.campaign_row(50)
                Handler.mode = mode
                result = self.adapter().classify(build_request(CASE))
                self.assertFalse(result["ok"])
                self.assertEqual(self.kinds(), ["campaign", "reserve", "fail"])
                if expected:
                    self.assertEqual(self.rows()[2]["reason"], expected)

    def test_pause_or_unresolved_blocks_before_network(self):
        for row in ({"kind": "pause", "reason": "t"}, {"kind": "unresolved", "source": "t", "reason": "t", "calls": None}):
            with self.subTest(kind=row["kind"]):
                self.campaign_row(50)
                with self.ledger.open("a") as handle:
                    handle.write(json.dumps({"v": 1, "id": "x-" + row["kind"], "ts": "2026-10-02T00:00:01.000000Z",
                                             "party": "owner", **row}) + "\n")
                Handler.hits = 0
                result = self.adapter().classify(build_request(CASE))
                self.assertEqual(result["error"], "budget_exceeded")
                self.assertEqual(Handler.hits, 0)
                self.assertNotIn("reserve", self.kinds())

    def test_six_process_admission_race_respects_ceiling(self):
        Handler.mode = "slow"
        request_bytes = len(json.dumps({"state": build_request(CASE)["state"], "model": "jev-1.13.0",
                                        "questions": build_request(CASE)["questions"]},
                                       ensure_ascii=False, separators=(",", ":")).encode())
        per_call = (request_bytes + 2048) * 4.2e-08
        self.campaign_row(per_call * 2.5)  # room for exactly two open reservations
        context = multiprocessing.get_context("spawn")
        with context.Pool(6) as pool:
            errors = pool.map(_race_worker, [(str(self.ledger), str(self.price), self.base, str(self.spend))] * 6)
        self.assertEqual(self.kinds().count("reserve"), sum(error is None for error in errors))
        self.assertLessEqual(self.kinds().count("reserve"), 2)
        self.assertGreaterEqual(errors.count("budget_exceeded"), 4)

    def test_crash_mid_call_leaves_reservation_counted(self):
        Handler.mode = "slow"
        context = multiprocessing.get_context("spawn")
        worker = context.Process(target=_race_worker,
                                 args=((str(self.ledger), str(self.price), self.base, str(self.spend)),))
        worker.start()
        import time
        deadline = time.monotonic() + 20
        while "reserve" not in self.kinds() and time.monotonic() < deadline:
            time.sleep(0.05)
        worker.kill()  # SIGKILL: no finally block, no settle or fail
        worker.join()
        self.assertEqual(self.kinds(), ["campaign", "reserve"])
        import importlib.util
        spec = importlib.util.spec_from_file_location("campaign_ledger_check", CAMPAIGN_MODULE)
        ledger = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ledger)
        state = ledger.fold(ledger.read_rows(self.ledger))
        reserve = self.rows()[1]
        self.assertEqual(state["openReservations"], [reserve["id"]])
        self.assertAlmostEqual(state["committedUSD"], reserve["maxUSD"])


if __name__ == "__main__":
    unittest.main()
