#!/usr/bin/env python3
"""Persistent, offline Laya-MLX worker.

The parent process spawns this once and keeps one loaded model for the life of
the child. Configuration arrives only through argv, never through a prediction
payload, so a caller cannot redirect the worker at a different checkpoint or a
remote download. stdout carries newline-delimited protocol JSON and nothing
else; model and library logs go to stderr.

Protocol (one JSON object per line):
  parent -> worker  {"id": <n>, "op": "predict", "state": ..., "questions": {...}}
  worker -> parent  {"type": "ready", "checkpoint": ..., "revision": ..., ...}
                    {"type": "result", "id": <n>, "result": {...}}
                    {"type": "error", "id": <n>, "error": {"code": ..., "message": ...}}
                    {"type": "fatal", "error": {"code": ..., "message": ...}}
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path

# Generous budgets used only to build the untruncated comparison sequence.
HUGE = 1 << 30
# build_prefix caps each option at 48 tokens; a longer option is truncated silently.
OPTION_TOKEN_CAP = 48
# Per-label rounding tolerance: probabilities are rounded to 4 decimals upstream.
ROUNDING_PER_LABEL = 0.000051
MAX_LINE_BYTES = 4 * 1024 * 1024

CHECKPOINT_FILES = (
    "model.safetensors",
    "rl_agent_config.json",
    "encoder/config.json",
    "tokenizer/tokenizer.json",
)
CREDENTIAL_KEYS = (
    "TYPESAFE_API_KEY",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)

# Set by load_runtime(); kept module-level so tests can inject fakes without
# importing the MLX package.
build_sequence = None
render_options = None
analyse_state = None

PROTOCOL = None


class WorkerError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def redact(text):
    """Strip credential-shaped text and cap length before any message is stored."""
    out = str(text)
    out = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", out)
    out = re.sub(r"\b(hf_|sk-)[A-Za-z0-9_\-]{8,}", "[redacted]", out)
    out = re.sub(r"(?i)(api[_-]?key|token|authorization)\s*[=:]\s*\S+", r"\1=[redacted]", out)
    return out[:500]


def emit(obj):
    if PROTOCOL is None:
        raise RuntimeError("protocol stream is not open")
    PROTOCOL.write(json.dumps(obj, ensure_ascii=False) + "\n")
    PROTOCOL.flush()


# ------------------------------------------------------------------- configuration

def resolve_model_dir(model_dir, revision):
    """Validate a complete local checkpoint whose identity matches the pin.

    A remote id, an incomplete directory, or a directory that is not the pinned
    revision is refused. Nothing here downloads or substitutes a checkpoint.
    """
    path = Path(model_dir).expanduser()
    if not path.is_dir():
        raise WorkerError("checkpoint_missing", f"local model directory not found: {path}")
    missing = [name for name in CHECKPOINT_FILES if not (path / name).is_file()]
    if missing:
        raise WorkerError(
            "checkpoint_incomplete", f"not a complete Laya checkpoint: missing {', '.join(missing)}"
        )
    if revision and not _identity_matches(path, revision):
        raise WorkerError(
            "revision_mismatch",
            f"local checkpoint identity does not match the pinned revision {revision}",
        )
    return path


def _identity_matches(path, revision):
    if path.name == revision:
        return True
    manifest = path / "laya-identity.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return data.get("revision") == revision
    return False


def scrub_credentials():
    """Remove credential keys from this process's environment before any import."""
    for key in CREDENTIAL_KEYS:
        os.environ.pop(key, None)


def enforce_offline():
    """Refuse any implicit Hugging Face fetch, even if the parent did not set these."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


# ----------------------------------------------------------------------- runtime

class Runtime:
    """Thin wrapper over a loaded laya_mlx Agent."""

    def __init__(self, agent, checkpoint, revision, language):
        self.agent = agent
        self.tok = agent.tok
        self.cfg = agent.cfg
        self.max_len = int(self.cfg.get("max_len", 512))
        self.head_max_len = int(self.cfg.get("head_max_len", 192))
        self.model_dir = str(agent.model_dir)
        self.checkpoint = checkpoint
        self.revision = revision
        self.language = language
        self.device_label = str(agent.device)
        self.dtype_label = "float16"

    def to_internal(self, definition):
        return self.agent._to_internal(definition)

    def predict(self, state, questions):
        return self.agent.system_one(state, questions)

    def synchronize(self):
        import mlx.core as mx

        mx.synchronize()

    def analyse(self, state):
        return analyse_state(state)


def load_runtime(model_dir, checkpoint, revision, language):
    global build_sequence, render_options, analyse_state
    try:
        import laya_mlx
        from laya_mlx.common import build_sequence as _build_sequence
        from laya_mlx.common import render_options as _render_options
        from laya_mlx.lang import analyse as _analyse
    except ImportError as exc:
        raise WorkerError("runtime_missing", f"laya_mlx is not importable: {redact(exc)}")
    build_sequence, render_options, analyse_state = _build_sequence, _render_options, _analyse
    try:
        agent = laya_mlx.load(str(model_dir), device="gpu", dtype="float16")
        return Runtime(agent, checkpoint, revision, language)
    except Exception as exc:  # noqa: BLE001 - every load failure is reported explicitly
        raise WorkerError("load_failed", f"could not load {model_dir}: {redact(exc)}")


# -------------------------------------------------------------------- validation

def check_no_truncation(tok, q, state, max_len, head_max_len):
    """Return a reason string when the real sequence is shorter than an untruncated one.

    The comparison is token-based: the same builder runs with the model budget and
    with a budget large enough that nothing is cut, so a difference means the
    question text, options, or state would lose tokens.
    """
    if build_sequence is None or render_options is None:
        raise WorkerError("runtime_missing", "token-budget validation is unavailable")
    ids, _ = build_sequence(tok, state, q, max_len, head_max_len)
    full, _ = build_sequence(tok, state, q, HUGE, HUGE)
    if len(ids) != len(full) or ids != full:
        return f"input would be truncated to the {max_len}-token model budget"
    for option in render_options(q):
        text = " " + option.replace(tok.mask_token, " ")
        if len(tok(text, add_special_tokens=False)["input_ids"]) > OPTION_TOKEN_CAP:
            return f"an option exceeds the {OPTION_TOKEN_CAP}-token option budget"
    return None


def _number(value, low=0.0, high=1.0):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and low <= value <= high
    )


def _tolerance(labels):
    return max(0.001, labels * ROUNDING_PER_LABEL)


def validate_answer(qid, definition, answer):
    kind = definition.get("type")
    if not isinstance(answer, dict) or answer.get("type") != kind:
        raise WorkerError("invalid_output", f"question {qid!r}: answer type does not match")
    if not _number(answer.get("confidence")):
        raise WorkerError("invalid_output", f"question {qid!r}: confidence is missing or out of range")
    probabilities = answer.get("probabilities")
    if kind == "choice":
        labels = list(definition["criteria"])
        if not isinstance(probabilities, dict) or set(probabilities) != set(labels):
            raise WorkerError("invalid_output", f"question {qid!r}: probabilities do not cover the labels")
        if not all(_number(p) for p in probabilities.values()):
            raise WorkerError("invalid_output", f"question {qid!r}: a probability is not finite in [0,1]")
        if abs(sum(probabilities.values()) - 1) > _tolerance(len(labels)):
            raise WorkerError("invalid_output", f"question {qid!r}: probabilities do not sum to one")
        if answer.get("choice") not in labels:
            raise WorkerError("invalid_output", f"question {qid!r}: selected label is not a valid option")
    elif kind == "score":
        count = len(definition["criteria"])
        labels = {str(i) for i in range(count)}
        if not isinstance(probabilities, dict) or set(probabilities) != labels:
            raise WorkerError("invalid_output", f"question {qid!r}: probabilities do not cover the levels")
        if not all(_number(p) for p in probabilities.values()):
            raise WorkerError("invalid_output", f"question {qid!r}: a probability is not finite in [0,1]")
        if abs(sum(probabilities.values()) - 1) > _tolerance(count):
            raise WorkerError("invalid_output", f"question {qid!r}: probabilities do not sum to one")
        if not _number(answer.get("score"), high=count - 1):
            raise WorkerError("invalid_output", f"question {qid!r}: score is out of range")
        legend = answer.get("legend")
        if not isinstance(legend, dict) or set(legend) != labels:
            raise WorkerError("invalid_output", f"question {qid!r}: legend does not cover the levels")
    else:  # noul
        if not _number(answer.get("noul")):
            raise WorkerError("invalid_output", f"question {qid!r}: noul is missing or out of range")


def validate_result(raw, questions, runtime):
    if not isinstance(raw, dict):
        raise WorkerError("invalid_output", "the model returned a non-object result")
    if not isinstance(raw.get("model"), str) or not raw["model"]:
        raise WorkerError("invalid_output", "the model identity is missing")
    usage = raw.get("usage")
    if not isinstance(usage, dict) or any(
        not isinstance(usage.get(key), int) or isinstance(usage.get(key), bool) or usage[key] < 0
        for key in ("input_tokens", "output_tokens")
    ):
        raise WorkerError("invalid_output", "usage is missing or invalid")
    answers = raw.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise WorkerError("invalid_output", "answers do not cover exactly the requested question ids")
    for qid, definition in questions.items():
        validate_answer(qid, definition, answers[qid])
    return {
        "model": f"{runtime.checkpoint}@{runtime.revision}",
        "answers": answers,
        "usage": {"input_tokens": int(usage["input_tokens"]), "output_tokens": int(usage["output_tokens"])},
        "backend": "laya-mlx",
        "checkpoint": runtime.checkpoint,
        "revision": runtime.revision,
        "device": runtime.device_label,
        "dtype": runtime.dtype_label,
        "model_dir": runtime.model_dir,
    }


def handle_predict(runtime, state, questions):
    if not isinstance(questions, dict) or not questions:
        raise WorkerError("invalid_request", "questions must be a non-empty object")
    for qid in questions:
        if qid in ("__proto__", "constructor", "prototype"):
            raise WorkerError("invalid_request", f"question id {qid!r} is reserved")

    analysis = runtime.analyse(state)
    if runtime.language == "en" and analysis.get("script") not in ("latin", "unknown"):
        raise WorkerError(
            "unsupported_language",
            f"the pinned English checkpoint cannot read {analysis.get('script')} script",
        )

    for qid, definition in questions.items():
        try:
            q = runtime.to_internal(definition)
        except Exception as exc:  # noqa: BLE001 - report the shape error verbatim
            raise WorkerError("invalid_request", f"question {qid!r}: {redact(exc)}")
        reason = check_no_truncation(runtime.tok, q, state, runtime.max_len, runtime.head_max_len)
        if reason:
            raise WorkerError("input_truncated", f"question {qid!r}: {reason}")

    started = time.perf_counter()
    try:
        raw = runtime.predict(state, questions)
    except WorkerError:
        raise
    except Exception as exc:  # noqa: BLE001 - a model failure is reported, not swallowed
        raise WorkerError("inference_failed", redact(exc))
    runtime.synchronize()
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    result = validate_result(raw, questions, runtime)
    result["elapsed_ms"] = round(elapsed_ms, 3)
    return result


# --------------------------------------------------------------------------- loop

def parse_args(argv):
    ap = argparse.ArgumentParser(description="persistent offline Laya-MLX worker")
    ap.add_argument("--model-dir", required=True, help="local checkpoint directory")
    ap.add_argument("--checkpoint", required=True, help="checkpoint identity for the result envelope")
    ap.add_argument("--revision", required=True, help="expected pinned revision")
    ap.add_argument("--language", default="en", help="checkpoint language; 'en' rejects non-Latin script")
    return ap.parse_args(argv)


def _open_protocol():
    global PROTOCOL
    PROTOCOL = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)  # every later write to fd 1 (print, warnings) goes to stderr


def _read_line(stream):
    line = stream.readline(MAX_LINE_BYTES + 1)
    if not line:
        return None
    if len(line) > MAX_LINE_BYTES:
        raise WorkerError("invalid_request", "request line exceeds the size limit")
    return line


def run(argv=None):
    _open_protocol()
    scrub_credentials()
    enforce_offline()
    try:
        args = parse_args(argv)
        model_dir = resolve_model_dir(args.model_dir, args.revision)
        runtime = load_runtime(model_dir, args.checkpoint, args.revision, args.language)
    except WorkerError as exc:
        emit({"type": "fatal", "error": {"code": exc.code, "message": exc.message}})
        return 1
    except SystemExit:
        return 2

    emit(
        {
            "type": "ready",
            "checkpoint": args.checkpoint,
            "revision": args.revision,
            "model": f"{args.checkpoint}@{args.revision}",
            "backend": "laya-mlx",
            "device": runtime.device_label,
            "dtype": runtime.dtype_label,
            "model_dir": runtime.model_dir,
        }
    )

    stdin = sys.stdin.buffer
    while True:
        try:
            line = _read_line(stdin)
        except WorkerError as exc:
            emit({"type": "fatal", "error": {"code": exc.code, "message": exc.message}})
            return 1
        if line is None:
            return 0
        text = line.strip()
        if not text:
            continue
        try:
            request = json.loads(text)
        except ValueError:
            emit({"type": "error", "id": None, "error": {"code": "invalid_request", "message": "request is not valid JSON"}})
            continue
        if not isinstance(request, dict):
            emit({"type": "fatal", "error": {"code": "invalid_request", "message": "request must be an object"}})
            return 1
        request_id = request.get("id")
        if request.get("op") != "predict":
            emit({"type": "error", "id": request_id, "error": {"code": "invalid_request", "message": "unknown op"}})
            continue
        try:
            result = handle_predict(runtime, request.get("state"), request.get("questions"))
        except WorkerError as exc:
            emit({"type": "error", "id": request_id, "error": {"code": exc.code, "message": exc.message}})
        except Exception as exc:  # noqa: BLE001 - a worker must answer, not crash the parent
            emit({"type": "error", "id": request_id, "error": {"code": "internal_error", "message": redact(exc)}})
        else:
            emit({"type": "result", "id": request_id, "result": result})


if __name__ == "__main__":
    sys.exit(run())
