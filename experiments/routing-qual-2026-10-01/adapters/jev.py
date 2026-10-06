"""Single-attempt Jev transport accounted in the shared campaign ledger.

Every network call is preceded by a durable `reserve` row and followed by
exactly one `settle` (reply with measured input usage for the requested model)
or `fail` (anything else; the reservation's maxUSD stays counted until the
ledger owner reconciles it). Admission, pause, unresolved-history and ceiling
rules belong to the shared module (jev-testing-campaign CONTRACT.md v1).
The pre-campaign adapter (frozen v1) is kept outside the repo; see REPORT.md.
"""

import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import socket
import sys
import time
import urllib.error
import urllib.request

from questions import METADATA_KEYS, QUESTIONS, validate_answers

# CONTRACT.md, MUST AGREE 3, pins Jev; config/ only defines Laya profiles.
DEFAULT_MODEL = "jev-1.13.0"
# src/client.js baseUrl() and CONTRACT.md, MUST AGREE 1.
DEFAULT_API_BASE = "https://api.typesafe.ai"
CAMPAIGN_DIR = Path.home() / ".local/scratch/jev-testing-campaign-2026-10"
PARTY = "laya-qualification"


def _repo_helpers():
    directory = Path(__file__).resolve().parents[3] / "tools"
    sys.path.insert(0, str(directory))
    try:
        spec = importlib.util.spec_from_file_location("routing_qual_spend_log", directory / "spend_log.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from machine_paths import path_of
        return module.record, path_of
    finally:
        sys.path.pop(0)


def _campaign_module(path):
    spec = importlib.util.spec_from_file_location("jev_campaign_ledger", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _key(path_of):
    value = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if value:
        return value
    contents = Path(path_of("config.typesafe_env", ".config/typesafe/env.sh")).read_text(encoding="utf-8")
    match = re.search(r"^\s*export\s+TYPESAFE_API_KEY=[\"']?([^\"'\s]+)[\"']?\s*$", contents, re.MULTILINE)
    if not match:
        raise ValueError("credential unavailable")
    return match.group(1)


def _redact(raw, key):
    if key:
        raw = raw.replace(key, "[redacted]")
    return re.sub(r"Bearer\s+\S+", "Bearer [redacted]", raw)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class JevAdapter:
    def __init__(self, config):
        self.model = config.get("model", DEFAULT_MODEL)
        self.api_base = config.get("api_base", DEFAULT_API_BASE).rstrip("/")
        self.timeout = float(config.get("timeout_s", 30))
        if not self.timeout > 0:
            raise ValueError("invalid timeout")
        self.purpose = config.get("purpose", "routing-qual")
        self.party = config.get("party", PARTY)
        self.ledger = Path(config.get("campaign_ledger", CAMPAIGN_DIR / "ledger.jsonl"))
        self.campaign = _campaign_module(config.get("campaign_module", CAMPAIGN_DIR / "jev_campaign_ledger.py"))
        price_path = config.get("price_file")
        if not price_path:
            raise ValueError("a verified price file is required")
        self.price = json.loads(Path(price_path).read_text(encoding="utf-8"))
        self.campaign.verified_rate(self.price, self.model)  # raises price-unverified
        self.record_spend, self.path_of = _repo_helpers()
        self.opener = urllib.request.build_opener(_NoRedirect())
        self.closed = False

    def info(self):
        return {
            "backend": "jev", "model": self.model, "revision": self.model, "local": False,
            "versions": {"api": "v1", "python": platform.python_version(),
                         "accounting": "jev-testing-campaign CONTRACT v1", "party": self.party},
        }

    def classify(self, request):
        started = time.monotonic()
        result = {
            "ok": False, "answers": None, "error": None,
            "model": self.model, "revision": self.model,
            "usage": {"input_tokens": None, "output_tokens": None},
            "latency_ms": 0.0, "cost_usd": None, "raw": "",
            "network_attempts_blocked": 0,
        }

        def finish(error):
            result["error"] = error
            result["ok"] = error is None
            result["latency_ms"] = (time.monotonic() - started) * 1000
            return result

        if self.closed:
            return finish("transport")
        if os.environ.get("DROPPY_DECISION_MODE") == "local":
            result["network_attempts_blocked"] = 1
            return finish("network_blocked")
        try:
            state = request["state"]
            if (request["questions"] != QUESTIONS or not isinstance(state, dict)
                    or set(state) - {"task_text", "mode", "metadata"}
                    or not {"task_text", "mode"} <= set(state)
                    or not isinstance(state["task_text"], str)
                    or not isinstance(state["mode"], str)
                    or not isinstance(state.get("metadata", {}), dict)
                    or set(state.get("metadata", {})) - set(METADATA_KEYS)):
                return finish("malformed")
            request_id = request["request_id"]
            serialized = json.dumps({"state": state, "model": self.model, "questions": request["questions"]},
                                    ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (KeyError, TypeError, ValueError):
            return finish("malformed")
        body = serialized.encode("utf-8")
        try:
            reservation = self.campaign.reserve(self.ledger, self.party, request_id, self.model, len(body), self.price)
        except self.campaign.LedgerError as error:
            # No reservation, no network call.
            result["raw"] = json.dumps({"admission": error.reason})
            return finish("budget_exceeded")
        result["campaign_reserve_id"] = reservation["id"]
        return self._call(request_id, body, reservation, result, finish)

    def _call(self, request_id, body, reservation, result, finish):
        key, error, payload, closed = "", None, None, False
        try:
            try:
                key = _key(self.path_of)
                endpoint = self.api_base
                if not endpoint.endswith("/v1/systemone"):
                    endpoint += "/systemone" if endpoint.endswith("/v1") else "/v1/systemone"
                wire = urllib.request.Request(endpoint, data=body, method="POST",
                                              headers={"Authorization": "Bearer " + key,
                                                       "Content-Type": "application/json"})
                with self.opener.open(wire, timeout=self.timeout) as response:
                    result["raw"] = _redact(response.read().decode("utf-8", errors="replace"), key)
            except urllib.error.HTTPError as exc:
                result["raw"] = _redact(exc.read().decode("utf-8", errors="replace"), key)
                error = "input_over_limit" if exc.code == 413 else "timeout" if exc.code in (408, 504) else "transport"
            except (TimeoutError, socket.timeout):
                error = "timeout"
            except urllib.error.URLError as exc:
                error = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "transport"
            except (OSError, ValueError):
                error = "transport"
            try:
                payload = json.loads(result["raw"])
            except (ValueError, TypeError):
                error = error or "malformed"
            usage = payload.get("usage") if isinstance(payload, dict) else None
            input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else None
            output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
            valid_input = type(input_tokens) is int and input_tokens >= 0
            valid_output = type(output_tokens) is int and output_tokens >= 0
            resolved = payload.get("model") if isinstance(payload, dict) else None
            if isinstance(resolved, str):
                result["model"] = result["revision"] = resolved
            if valid_input and resolved == self.model:
                result["usage"] = {"input_tokens": input_tokens,
                                   "output_tokens": output_tokens if valid_output else None}
                settled = self.campaign.settle(self.ledger, reservation, input_tokens,
                                               output_tokens if valid_output else 0, self.price,
                                               evidence="response-usage" if valid_output else "response-input-usage")
                result["cost_usd"] = settled["usd"]
                closed = True
            else:
                # Unknown usage or a resolved model without a verified price: keep maxUSD counted.
                reason = ("resolved-model-mismatch" if valid_input and resolved != self.model
                          else error or "usage-missing")
                self.campaign.fail(self.ledger, reservation, reason)
                result["cost_usd"] = None
                closed = True
                if valid_input:
                    result["usage"] = {"input_tokens": input_tokens,
                                       "output_tokens": output_tokens if valid_output else None}
                error = error or "malformed"
            if error is None:
                wire_answers = payload.get("answers")
                if not isinstance(wire_answers, dict) or set(wire_answers) != set(QUESTIONS):
                    error = "malformed"
                else:
                    normalized = {}
                    for qid, answer in wire_answers.items():
                        if not isinstance(answer, dict) or answer.get("type") != "choice" or "probabilities" not in answer:
                            error = "malformed"
                            break
                        normalized[qid] = {"probs": answer["probabilities"]}
                    if error is None:
                        answers, errors = validate_answers(normalized)
                        if errors:
                            error = "malformed"
                        else:
                            result["answers"] = answers
        finally:
            if not closed:
                # An exception escaped before settlement; the call may have been billed.
                self.campaign.fail(self.ledger, reservation, "adapter-exception")
        finish(error)
        self.record_spend(self.purpose, result["model"], len(QUESTIONS),
                          result["usage"] if result["usage"]["input_tokens"] is not None else None,
                          latency_ms=result["latency_ms"], answers=result["answers"],
                          context={"request_id": request_id}, campaign_reserve_id=reservation["id"])
        return result

    def close(self):
        self.closed = True


def make_adapter(config):
    return JevAdapter(config)
