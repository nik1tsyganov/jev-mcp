"""The product Oracle callable: `droppy route` (prepare/replay only, offline).

Pinned to the integrated Oracle CLI (merge 329ecdea, Debug build). `droppy route`
forwards one JSON envelope to the executable's `--oracle-route` mode; it needs no
daemon (`--no-start`, an unreachable socket) and makes no API call. The child
environment never carries TYPESAFE_API_KEY and carries the test-only authority
hooks from authority.seed().
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

from .common import CALLER, CAPABILITY, DEBUG_APP, ROUTE_CLI, sha256

FAR_FUTURE = "2099-01-01T00:00:00Z"
EXECUTABLE = DEBUG_APP / "Contents/MacOS/Droppy Code Dev"
DEBUG_DYLIB = DEBUG_APP / "Contents/MacOS/Droppy Code Dev.debug.dylib"


class HelperError(Exception):
    pass


class Helper:
    def __init__(self, authority_env=None, timeout=60, command=None, app=None):
        # `app` points at an immutable snapshot bundle (frozen.snapshot_helper) instead of the shared build.
        # ROUTING_QUAL_HELPER_APP selects an accepted immutable bundle for gates, tests and runs alike.
        app = Path(app) if app else Path(os.environ.get("ROUTING_QUAL_HELPER_APP") or DEBUG_APP)
        route_cli = app / "Contents/Resources/droppy_cli.py"
        executable = app / "Contents/MacOS/Droppy Code Dev"
        dylib = app / "Contents/MacOS/Droppy Code Dev.debug.dylib"
        self.command = command or [sys.executable, str(route_cli), "--app", str(app),
                                   "--socket", "/nonexistent/routing-qual-v2.sock", "--no-start", "route"]
        for path in (route_cli, executable):
            if command is None and not Path(path).is_file():
                raise HelperError(f"product callable missing: {path}")
        self.env = {k: v for k, v in os.environ.items() if k not in ("TYPESAFE_API_KEY", "DROPPY_APP")}
        self.env.update({k: v for k, v in (authority_env or {}).items() if k.startswith("DROPPY_ORACLE_ROUTE_")})
        self.timeout = timeout
        self.identity = {"app": str(app),
                         "route_cli_sha256": sha256(route_cli) if route_cli.is_file() else None,
                         "executable_sha256": sha256(executable) if executable.is_file() else None,
                         "debug_dylib_sha256": sha256(dylib) if dylib.is_file() else None,
                         "authority": {k: v for k, v in (authority_env or {}).items() if k.startswith("DROPPY_")}}

    def call(self, envelope):
        try:
            done = subprocess.run(self.command, input=json.dumps(envelope), capture_output=True, text=True,
                                  timeout=self.timeout, env=self.env)
        except subprocess.TimeoutExpired as exc:
            raise HelperError("helper timeout") from exc
        if done.returncode != 0 or not done.stdout.strip():
            raise HelperError(f"helper exit {done.returncode}: {done.stderr.strip()[:300]}")
        return json.loads(done.stdout)

    def prepare(self, helper_input):
        result = self.call({"operation": "prepare", "input": helper_input})
        if "requestFingerprint" not in result or "requestJSON" not in result:
            raise HelperError("prepare rejected: " + json.dumps(result)[:400])
        return result

    def replay(self, helper_input, fingerprint, replies):
        return self.call({"operation": "replay", "input": helper_input,
                          "requestFingerprint": fingerprint, "replies": list(replies)})


def evaluation_qualification(mode, backend, model, threshold, evidence_version):
    """Evaluation-only envelope so the helper applies `threshold` while the backend is
    under test. It is never exported and never counts as qualification evidence."""
    return {"caller": CALLER, "backend": backend, "mode": mode, "model": model,
            "capability": CAPABILITY, "evidenceVersion": "evaluation-under-test:" + evidence_version,
            "validUntil": FAR_FUTURE, "threshold": threshold, "qualified": True,
            "preservesExactState": True}


def materialize(case, snapshot_module):
    """Native fields with saved-pair candidates derived by the product's from_saved."""
    native = deepcopy(case["helper"])
    native.setdefault("roleHints", [])  # an absent field means no hints; the helper schema requires the array
    pairs = native.pop("savedPairs", [])
    derived = [snapshot_module.from_saved(pair) for pair in pairs]
    native["candidates"] = derived + native.get("candidates", [])
    by_pair = {c["source"]["saved"]["pairID"]: c for c in derived}
    for binding in native.get("bindings", []):
        if "pairID" in binding:
            candidate = by_pair[binding.pop("pairID").upper()]
            binding["candidateID"] = candidate["id"]
            binding["revision"] = candidate["revision"]
            binding["configuration"] = deepcopy(candidate["variant"])
    if "currentPairID" in native:
        native["currentCandidateID"] = by_pair[native.pop("currentPairID").upper()]["id"]
    for comp in native.get("compositions", []):
        for side in ("leadCandidateID", "headCandidateID"):
            if comp[side] in by_pair or comp[side].upper() in by_pair:
                comp[side] = by_pair[comp[side].upper()]["id"]
    return native


def helper_input(case, backend, model, threshold, guard, evidence_version, matrix_version, snapshot_module):
    """Native helper snapshot for one case: product-derived candidates, guard-filtered
    provider facts, harness identity and the evaluation-only qualification envelope."""
    native = materialize(case, snapshot_module)
    providers, removed = guard.filter_providers(native.get("providers", []))
    native.update(providers=providers, requestID=case["id"], caller=CALLER, backend=backend,
                  matrixVersion=matrix_version, readinessVersion="fixture:" + evidence_version,
                  readinessValidUntil=FAR_FUTURE,
                  qualification=evaluation_qualification(native["mode"], backend, model, threshold, evidence_version))
    for binding in native.get("bindings", []):
        binding.setdefault("validUntil", FAR_FUTURE)
    return native, removed
