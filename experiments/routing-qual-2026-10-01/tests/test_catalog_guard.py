"""Positive and negative parity checks for catalog_guard (offline, no API calls)."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import catalog_guard  # noqa: E402
import policy  # noqa: E402
from controls import point_answers  # noqa: E402

ROUTING = catalog_guard.DEFAULT_ROUTING
CONCLAVE_SEATS = ROUTING.parents[2] / "conclave/references/conclave-seats.json"
CODEX_CACHE = catalog_guard.DEFAULT_CODEX_CACHE
RULE = dict(policy.RULES["owner-bands"])

# Dispatch rows that name models outside the canonical vendor model lists (2026-10-02).
# A change here means the catalog drifted and needs a reviewed update, not a test edit.
KNOWN_ROW_INCONSISTENCIES = {("gpt-5.6-sol", "high"), ("sonnet", "medium"), ("haiku", "medium"), ("haiku", "high")}


def dispatch_pairs():
    """Every {model, effort} member in routing.json class/fallback rows and Conclave seats."""
    pairs = set()

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("model"), str):
                pairs.add((value.get("vendor"), value["model"], value.get("effort")))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    routing = json.loads(ROUTING.read_text())
    for key in ("classes", "fallbacks", "vendorImplementSeats", "escalation"):
        walk(routing.get(key))
    if CONCLAVE_SEATS.exists():
        walk(json.loads(CONCLAVE_SEATS.read_text()))
    return pairs


def member(model, provider, effort):
    return {"model": model, "provider": provider, "effort": effort}


@unittest.skipUnless(ROUTING.exists() and CODEX_CACHE.exists(), "canonical catalogs not present")
class LiveCatalogParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.support = catalog_guard.Support()

    def provider_for(self, vendor, model):
        if vendor in catalog_guard.VENDOR_PROVIDER:
            return catalog_guard.VENDOR_PROVIDER[vendor]
        entry = self.support.models.get(model)
        return entry[0] if entry else None

    def test_every_dispatch_row_is_supported_or_a_known_inconsistency(self):
        unsupported = set()
        for vendor, model, effort in dispatch_pairs():
            ok, reason, _ = self.support.check(member(model, self.provider_for(vendor, model), effort))
            if not ok:
                unsupported.add((model, effort if isinstance(effort, str) else None))
        self.assertEqual(unsupported, KNOWN_ROW_INCONSISTENCIES)

    def test_required_positive_rows(self):
        for model, effort in (("gpt-6-astra", "high"), ("gpt-6-astra", "xhigh"), ("gpt-6-astra", "medium"),
                              ("gpt-6.1-sol", "medium"), ("gpt-6.1-sol", "high"), ("gpt-6.1-sol", "xhigh"),
                              ("gpt-6.1-sol", "max"), ("gpt-6.1-sol", "ultra"), ("gpt-6-luna", "max"),
                              ("codex-auto-review", "high")):
            with self.subTest(model=model, effort=effort):
                self.assertTrue(self.support.check(member(model, "openai", effort))[0])
        for model, effort in (("opus", "xhigh"), ("fable", "max"), ("opus", "low")):
            with self.subTest(model=model, effort=effort):
                self.assertTrue(self.support.check(member(model, "anthropic", effort))[0])
        for slug, effort in (("gemini-3.8-flash-high", "fused-high"), ("gemini-3.8-flash-high", None),
                             ("gemini-3.1-pro-low", "low")):
            with self.subTest(model=slug, effort=effort):
                self.assertTrue(self.support.check(member(slug, "google", effort))[0])

    def test_fabricated_or_unsupported_combinations(self):
        cases = [
            member("gpt-6-luna", "openai", "ultra"),           # cache lists low..max only
            member("gpt-6.1-sol", "openai", "minimal"),        # not a supported level
            member("gpt-6.1-sol", "openai", None),             # missing effort
            member("gpt-5.6-sol", "openai", "high"),           # cache-only model, not in canonical list
            member("gpt-7", "openai", "high"),                 # unknown model
            member("opus", "anthropic", "ultra"),              # Claude efforts stop at max
            member("opus", "openai", "high"),                  # provider mismatch
            member("sonnet", "anthropic", "medium"),           # alias only, not a listed model
            member("gemini-3.8-flash-low", "google", "high"),  # effort contradicts slug
            member("gemini-3.8-flash-low", "google", "fused-high"),
            member("swe-2-high", "cognition", "high"),         # provider absent from canonical catalog
            member("claude-sonnet-4-6", "google", "high"),     # agy third-party slug, no effort source
            None,
        ]
        for item in cases:
            with self.subTest(member=item):
                self.assertFalse(self.support.check(item)[0])


class GuardBehaviour(unittest.TestCase):
    """Deterministic checks with a synthetic catalog pair."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self.routing = tmp / "routing.json"
        self.routing.write_text(json.dumps({
            "_meta": {"updated": "test"}, "claudeModels": ["opus"], "codexModels": ["gpt-6-astra", "gpt-6-luna"],
            "codexReviewModel": None, "geminiModels": ["gemini-3.8-flash-high"],
            "efforts": {"claude": ["low", "medium", "high", "xhigh", "max"],
                        "codexByModel": {"gpt-6-astra": ["low", "medium", "high", "xhigh"]}}}))
        self.cache = tmp / "models_cache.json"
        self.cache.write_text(json.dumps({"fetched_at": "test", "models": [
            {"slug": "gpt-6-astra", "supported_reasoning_levels": [{"effort": e} for e in ("low", "medium", "high", "xhigh", "max", "ultra")]},
            {"slug": "gpt-6-luna", "supported_reasoning_levels": [{"effort": e} for e in ("low", "medium", "high")]}]}))

    def tearDown(self):
        self.tmp.cleanup()

    def case(self, candidates, current=None):
        snapshot = {"as_of": "2026-10-01", "candidates": candidates, "max_helpers": 4,
                    "unsupported_providers": [], "evidence_max_age_days": 30, "experimental_opt_in": False}
        if current:
            snapshot["current_candidate_id"] = current
        return {"id": "g-1", "mode": "hydraOracle", "task_text": "x", "metadata": {}, "snapshot": snapshot}

    def pair(self, cid, lead, head):
        return {"id": cid, "kind": "saved-pair", "lead": lead, "head": {**head, "profile": None}, "checkers": [],
                "helper_count": 2, "task_classes": ["standard-feature"], "context_window_tokens": 400000,
                "tools": ["shell"], "evidence_date": "2026-09-30", "qualified": True, "available": True}

    def test_intersection_and_missing_cache(self):
        support = catalog_guard.Support(self.routing, self.cache)
        self.assertFalse(support.check(member("gpt-6-astra", "openai", "ultra"))[0])  # routing list stops at xhigh
        self.assertTrue(support.check(member("gpt-6-luna", "openai", "high"))[0])     # cache only
        missing = catalog_guard.Support(self.routing, Path(self.tmp.name) / "absent.json")
        self.assertIsNone(missing.sources["codex_cache"])
        self.assertTrue(missing.check(member("gpt-6-astra", "openai", "high"))[0])    # routing list only
        self.assertFalse(missing.check(member("gpt-6-luna", "openai", "high"))[0])    # no effort source

    def test_fabricated_snapshot_support_abstains(self):
        support = catalog_guard.Support(self.routing, self.cache)
        fake = self.pair("fake", member("opus", "anthropic", "high"), member("gpt-6-luna", "openai", "max"))
        case = self.case([fake], current="fake")
        answers = point_answers("standard-feature", "medium")
        unguarded = policy.route(case, answers, RULE, {})
        self.assertEqual(unguarded["candidate_id"], "fake")  # v1 trusts the snapshot
        guarded = catalog_guard.guarded_route(case, answers, RULE, {}, support)
        self.assertEqual(guarded["outcome"], "abstain")
        self.assertIn("no-eligible", guarded["reasons"])
        self.assertIn("effort-unsupported:gpt-6-luna@max", guarded["provenance"]["catalog_guard"]["removed"]["fake"])

    def test_supported_candidate_routes_like_v1(self):
        support = catalog_guard.Support(self.routing, self.cache)
        good = self.pair("good", member("opus", "anthropic", "high"), member("gpt-6-astra", "openai", "xhigh"))
        fake = self.pair("fake", member("opus", "anthropic", "medium"), member("gpt-6-astra", "openai", "ultra"))
        case = self.case([good, fake])
        answers = point_answers("standard-feature", "medium")
        guarded = catalog_guard.guarded_route(case, answers, RULE, {}, support)
        self.assertEqual(guarded["candidate_id"], "good")
        self.assertEqual(guarded["heads"]["effort"], "xhigh")
        self.assertEqual(policy.route(case, answers, RULE, {})["candidate_id"], "fake")  # cheaper fabricated row wins in v1


if __name__ == "__main__":
    unittest.main()
