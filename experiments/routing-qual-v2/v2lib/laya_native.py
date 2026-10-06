"""Explicitly selected local Laya backend for the helper's native request.

Runs workers/laya_native_worker.py under the v1 deny-network sandbox
(adapters/local_sandbox.py, unchanged). Errors become backend-unavailable;
there is never a remote call or a fallback to Jev.
"""
from pathlib import Path

from .common import ROOT
from .replies import LAYA_MODEL

from adapters.local_sandbox import SANDBOX_PROFILE, WorkerFailure, start_worker  # v1, unchanged

DEFAULT_PYTHON = Path.home() / ".local/scratch/laya-evaluation/venv/bin/python"
DEFAULT_MODEL_DIR = (Path.home() / ".local/scratch/laya-evaluation/hf/hub/models--aac6fef--laya-mlx/snapshots"
                     / "047678560251f28113ee8f5df4be82102c7bf336")


class LayaNative:
    model = LAYA_MODEL

    def __init__(self, python=DEFAULT_PYTHON, model_dir=DEFAULT_MODEL_DIR, timeout=60, startup_timeout=180):
        import json
        self.timeout = timeout
        self.worker = start_worker([str(python), "-u", str(ROOT / "workers/laya_native_worker.py"),
                                    json.dumps({"model_dir": str(model_dir)})], None, str(ROOT / "workers"))
        ready = self.worker.receive(startup_timeout)
        if ready.get("type") != "ready":
            self.worker.close()
            raise WorkerFailure("transport", ready)
        self.info = {**ready["info"], "sandbox_profile": SANDBOX_PROFILE}

    def send(self, request_json, request_key):
        try:
            result = self.worker.call({"request_id": request_key, "request_json": request_json}, self.timeout)
        except WorkerFailure as exc:
            return {"ok": False, "raw": None, "error": exc.code, "detail": exc.raw}
        return {"ok": bool(result.get("ok")), "raw": result.get("raw") if result.get("ok") else None,
                "error": result.get("error"), "detail": None if result.get("ok") else result.get("raw"),
                "latency_ms": result.get("latency_ms"), "token_counts": result.get("token_counts"),
                "peak_rss_bytes": self.worker.peak_rss_bytes}

    def close(self):
        self.worker.close()
