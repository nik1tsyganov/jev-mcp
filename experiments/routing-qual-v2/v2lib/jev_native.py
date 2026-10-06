"""Jev transport for the product callable's exact prepared request (shared campaign ledger).

Per call, in this order, all before any network I/O:
1. size check against the documented 64k-token request ceiling (bytes >= tokens);
2. ledger `reserve` at the ceiling: maxUSD = 65,536 tokens x input rate. The ledger
   module prices (request_bytes + 2048) tokens, so request_bytes = 65,536 - 2,048;
3. a durable attempt row in the batch file under its lock, refused once the batch's
   hard attempt cap is reached.
Then exactly ONE HTTP attempt (urllib has no retry; nothing here retries), followed by
exactly one `settle` (measured input usage for the requested model) or `fail`. A
SIGKILL after reserve leaves an open reservation counted at maxUSD. The returned
model and any version metadata are logged.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import time
import urllib.error
import urllib.request

from .common import CAMPAIGN_DIR, JEV_REQUEST_TOKEN_CEILING, utc_now
from .replies import JEV_MODEL

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
PARTY = "laya-qualification"
OVERHEAD = 2048  # jev_campaign_ledger.OVERHEAD_TOKENS
META_HEADERS = re.compile(r"(model|version|request-id|x-request)", re.IGNORECASE)


def _campaign(path):
    spec = importlib.util.spec_from_file_location("jev_campaign_ledger_v2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _key():
    value = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if value:
        return value
    text = (Path.home() / ".config/typesafe/env.sh").read_text(encoding="utf-8")
    match = re.search(r"^\s*export\s+TYPESAFE_API_KEY=[\"']?([^\"'\s]+)[\"']?\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError("credential unavailable")
    return match.group(1)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class AttemptCap:
    """Durable, locked attempt counter shared by every run of one batch."""

    def __init__(self, batch_dir, max_attempts):
        self.path = Path(batch_dir) / "attempts.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max = int(max_attempts)

    def count(self):
        return sum(1 for line in self.path.read_text().splitlines() if line.strip()) if self.path.exists() else 0

    def claim(self, request_key, reserve_id):
        with open(str(self.path) + ".lock", "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            used = self.count()
            if used >= self.max:
                return None
            row = {"n": used + 1, "ts": utc_now(), "request_key": request_key, "reserve_id": reserve_id}
            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, (json.dumps(row) + "\n").encode())
                os.fsync(fd)
            finally:
                os.close(fd)
            return row["n"]


class JevNative:
    def __init__(self, price_file, batch_dir, max_attempts, ledger=CAMPAIGN_DIR / "ledger.jsonl",
                 module=CAMPAIGN_DIR / "jev_campaign_ledger.py", endpoint=ENDPOINT, timeout=30, admission_id=None):
        # With admission_id, every reserve cites the owner's single-batch admission: the ledger then
        # reserves the frozen per-attempt bound, refuses reused request keys and caps attempts and spend.
        self.admission_id = admission_id
        self.campaign = _campaign(module)
        self.ledger = Path(ledger)
        self.price = json.loads(Path(price_file).read_text(encoding="utf-8"))
        self.campaign.verified_rate(self.price, JEV_MODEL)
        self.cap = AttemptCap(batch_dir, max_attempts)
        self.endpoint, self.timeout = endpoint, timeout
        self.opener = urllib.request.build_opener(_NoRedirect())
        self.http_attempts = 0

    def send(self, request_json, request_key):
        """Return {ok, raw, error, reserve_id, usage, returned_model, response_meta, attempt, latency_ms}."""
        started = time.monotonic()
        out = {"ok": False, "raw": None, "error": None, "reserve_id": None, "usage": None,
               "returned_model": None, "response_meta": {}, "attempt": None}
        body = request_json.encode("utf-8")
        if json.loads(request_json).get("model") != JEV_MODEL:
            out["error"] = "request-model-mismatch"
            return out
        if len(body) > JEV_REQUEST_TOKEN_CEILING:
            out["error"] = "input_over_limit"
            return out
        try:
            reservation = self.campaign.reserve(self.ledger, PARTY, request_key, JEV_MODEL,
                                                JEV_REQUEST_TOKEN_CEILING - OVERHEAD, self.price, max_output_tokens=0,
                                                admission_id=self.admission_id)
        except self.campaign.LedgerError as error:
            out["error"] = "admission:" + error.reason
            return out
        out["reserve_id"] = reservation["id"]
        closed = False
        try:
            attempt = self.cap.claim(request_key, reservation["id"])
            if attempt is None:
                self.campaign.fail(self.ledger, reservation, "attempt-cap-reached-before-network")
                closed = True
                out["error"] = "attempt-cap"
                return out
            out["attempt"] = attempt
            key = _key()
            try:
                wire = urllib.request.Request(self.endpoint, data=body, method="POST",
                                              headers={"Authorization": "Bearer " + key,
                                                       "Content-Type": "application/json"})
                self.http_attempts += 1
                with self.opener.open(wire, timeout=self.timeout) as response:
                    out["response_meta"] = {k: v for k, v in response.headers.items() if META_HEADERS.search(k)}
                    out["raw"] = response.read().decode("utf-8", errors="replace").replace(key, "[redacted]")
            except urllib.error.HTTPError as exc:
                out["error"] = f"http-{exc.code}"
                out["response_meta"] = {k: v for k, v in (exc.headers or {}).items() if META_HEADERS.search(k)}
            except (TimeoutError, socket.timeout, urllib.error.URLError, OSError):
                out["error"] = "transport"
            payload = None
            try:
                payload = json.loads(out["raw"]) if out["raw"] else None
            except ValueError:
                out["error"] = out["error"] or "malformed"
            if isinstance(payload, dict):
                out["returned_model"] = payload.get("model")
                out["response_meta"].update({k: payload[k] for k in payload if "version" in k.lower()})
            usage = payload.get("usage") if isinstance(payload, dict) else None
            tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
            if type(tokens) is int and tokens >= 0 and out["returned_model"] == JEV_MODEL:
                output = usage.get("output_tokens") if type(usage.get("output_tokens")) is int else 0
                self.campaign.settle(self.ledger, reservation, tokens, output, self.price)
                out["usage"] = {"input_tokens": tokens, "output_tokens": output}
                out["ok"] = out["error"] is None
            else:
                reason = "resolved-model-mismatch" if type(tokens) is int else (out["error"] or "usage-missing")
                self.campaign.fail(self.ledger, reservation, reason)
                out["error"] = out["error"] or reason
            closed = True
        finally:
            if not closed:
                self.campaign.fail(self.ledger, reservation, "adapter-exception")
        out["latency_ms"] = (time.monotonic() - started) * 1000
        return out
