"""Product authority inputs for the integrated Oracle callable (Debug test hooks only).

The integrated executable checks saved pairs, provider model catalogs and Conclave
seats against stored authority: in Release the app's preferences and bundled seat
catalog; in Debug, when set, a test-only defaults suite and a seat-catalog file.
This module seeds the dedicated test suite AUTHORITY_SUITE (never the app's own
preferences) with the run's synthetic HydraPair records and provider catalogs equal
to the frozen-guard-supported model@effort set, and pins seats to the frozen copy of
the product's bundled conclave-seat-catalog-v1.json.
"""
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile

from .common import AUTHORITY_SUITE, FROZEN_INPUTS, read_json

HELPER_NAMES = {
    # helper provider -> {model id as stored in the app catalog: canonical routing.json model}
    "codex": {"gpt-6-astra": "gpt-6-astra", "gpt-6.1-sol": "gpt-6.1-sol", "gpt-6-sol": "gpt-6-sol",
              "gpt-6-luna": "gpt-6-luna"},
    "claude": {"opus": "opus", "fable": "fable", "claude-opus-5-5": "opus", "claude-fable-5-1": "fable"},
    "antigravity": {"gemini-3.8-flash": None, "gemini-3.1-pro": None},
}


def product_snapshot(frozen=FROZEN_INPUTS):
    """The integrated adapter's snapshot.py, loaded from the frozen copy."""
    spec = importlib.util.spec_from_file_location("oracle_snapshot_frozen", Path(frozen) / "oracle_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seat_pin(frozen=FROZEN_INPUTS):
    return read_json(Path(frozen) / "conclave-seat-catalog-v1.json")


def provider_catalogs(guard):
    """Stored model catalogs equal to the frozen guard's supported model@effort set."""
    out = {}
    for provider, models in HELPER_NAMES.items():
        for model in models:
            efforts = [e for e in ("low", "medium", "high", "xhigh", "max", "ultra")
                       if guard.check_slot(provider, model, e)[0]]
            if efforts:
                out.setdefault(provider, {})[model] = efforts
    return out


def saved_pairs(cases):
    pairs = {}
    for case in cases:
        for pair in case["helper"].get("savedPairs", []):
            key = pair["id"].upper()
            if key in pairs and pairs[key] != pair:
                raise ValueError(f"saved pair {pair['id']} differs between cases")
            pairs[key] = pair
    return list(pairs.values())


def seed(cases, guard, frozen=FROZEN_INPUTS, suite=AUTHORITY_SUITE):
    """Write the test-only defaults suite and return the environment for the helper."""
    catalogs = provider_catalogs(guard)
    options = {provider: [{"id": model, "name": model, "efforts": efforts, "isDefault": False}
                          for model, efforts in models.items()] for provider, models in catalogs.items()}
    with tempfile.NamedTemporaryFile(suffix=".plist", delete=False) as handle:
        plistlib.dump({"hydraPairs": json.dumps(saved_pairs(cases)).encode(),
                       "providerModelCatalogs": json.dumps(options).encode()}, handle)
    try:
        subprocess.run(["defaults", "import", suite, handle.name], check=True, timeout=30)
    finally:
        os.unlink(handle.name)
    return {"DROPPY_ORACLE_ROUTE_DEFAULTS_SUITE": suite,
            "DROPPY_ORACLE_ROUTE_SEAT_CATALOG": str(Path(frozen) / "conclave-seat-catalog-v1.json"),
            "catalogs": catalogs}
