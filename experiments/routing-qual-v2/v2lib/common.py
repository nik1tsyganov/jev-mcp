"""Shared paths and small helpers for routing-qual v2 (stdlib only)."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT.parent / "routing-qual-2026-10-01"
FROZEN_INPUTS = Path.home() / ".local/scratch/routing-qual-v2/frozen-inputs-r3"  # outside the repo: raw catalog copies carry account-derived and host notes
SEALED = Path.home() / ".local/scratch/routing-qual-v2/sealed"
RUNS = Path.home() / ".local/scratch/routing-qual-v2/runs"
# Integrated Oracle CLI, merge 329ecdea6b1fd17e4cd1ce391c0967a425cb45a4 (Debug build; test-only authority hooks).
INTEGRATION = Path.home() / ".local/scratch/droppy-oracle-cli-integration"
DEBUG_APP = INTEGRATION / "build.noindex/integration/Build/Products/Debug/Droppy Code Dev.app"
ROUTE_CLI = DEBUG_APP / "Contents/Resources/droppy_cli.py"
DEFAULT_WRAPPER = INTEGRATION / "build.noindex/integration-oracle/droppy-oracle-route"
AUTHORITY_SUITE = "iordv.droppycode.routing-qual-v2-tests"  # test-only defaults domain, never app settings
JEV_REQUEST_TOKEN_CEILING = 65536  # docs.typesafe.ai/models: "64k tokens per request"
CAMPAIGN_DIR = Path.home() / ".local/scratch/jev-testing-campaign-2026-10"
CALLER = "routing-qual-v2"
CAPABILITY = "oracle-classification-policy-v1"
OWNER_THRESHOLD = 0.8
GRID = (0.35, 0.4, 0.5, 0.6, 0.7, 0.8)

if str(V1) not in sys.path:
    sys.path.insert(0, str(V1))  # v1 catalog_guard and sandbox are reused, never edited


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256(path):
    return sha256_bytes(Path(path).read_bytes())


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False, sort_keys=True) + "\n", encoding="utf-8")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def rel(path, root=ROOT):
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return "~/" + str(Path(path).resolve().relative_to(Path.home())) if str(Path(path).resolve()).startswith(str(Path.home())) else str(path)
