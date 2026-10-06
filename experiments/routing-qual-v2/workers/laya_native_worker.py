"""Sandboxed Laya worker for the helper's native request, exact state only.

Loads the helper-pinned checkpoint (aac6fef/laya-mlx @ 047678560251f2...). For each
question it builds the complete prefix and state token sequence without limits
and refuses the request when it exceeds the checkpoint's max_len or head_max_len.
Only then does it call the library, whose own build is identical when nothing is
cut. Protocol: one JSON request per stdin line -> one JSON line on stdout.
"""
import json
import os
from pathlib import Path
import platform
import sys
import time
import importlib.metadata

PINNED_MODEL = "laya-mlx-0476785"
REVISION = "047678560251f28113ee8f5df4be82102c7bf336"


def main():
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    config = json.loads(sys.argv[1])

    def emit(value):
        protocol.write(json.dumps(value, ensure_ascii=False) + "\n")
        protocol.flush()

    model_dir = Path(config["model_dir"]).expanduser().resolve()
    info = {"model": PINNED_MODEL, "revision": REVISION, "model_dir": str(model_dir),
            "python": platform.python_version(),
            "versions": {p: importlib.metadata.version(p) for p in ("mlx", "laya-mlx")}}
    try:
        if model_dir.name != REVISION or model_dir.parent.name != "snapshots":
            raise ValueError("model_dir must be the pinned snapshot directory")
        import laya_mlx
        from laya_mlx.common import build_prefix, serialize_state
        agent = laya_mlx.load(str(model_dir), device="gpu", dtype="float16")
        max_len, head_max = agent.cfg.get("max_len", 512), agent.cfg.get("head_max_len", 192)
        info.update(max_len=max_len, head_max_len=head_max)
        emit({"type": "ready", "info": info})
    except Exception as exc:  # report and stop; the adapter turns this into backend-unavailable
        emit({"type": "fatal", "error": "transport", "message": str(exc), "info": info})
        return
    tok = agent.tok
    for line in sys.stdin:
        started = time.perf_counter()
        result = {"type": "result", "request_id": None, "ok": False, "raw": None, "error": None}
        try:
            request = json.loads(line)
            result["request_id"] = request["request_id"]
            body = json.loads(request["request_json"])
            if body.get("model") != PINNED_MODEL:
                raise ValueError("request model is not the pinned Laya model")
            state, questions = body["state"], body["questions"]
            counts = {}
            for qid, definition in questions.items():
                internal = agent._to_internal(definition)
                prefix, markers = build_prefix(tok, internal, 10 ** 9)
                state_ids = tok(serialize_state(state).replace(tok.mask_token, " "), add_special_tokens=False)["input_ids"]
                total = len(prefix) + len(state_ids) + 1
                counts[qid] = {"prefix": len(prefix), "total": total}
                if len(prefix) > head_max or total > max_len:
                    result.update(error="input_over_limit",
                                  raw={"qid": qid, "prefix_tokens": len(prefix), "total_tokens": total,
                                       "max_len": max_len, "head_max_len": head_max})
                    raise StopIteration
            reply = agent.system_one(state, questions)
            reply["model"] = PINNED_MODEL
            for answer in reply["answers"].values():
                answer.pop("action", None)
            result.update(ok=True, raw=json.dumps(reply), token_counts=counts)
        except StopIteration:
            pass
        except Exception as exc:
            result.update(error="malformed", raw={"message": str(exc)})
        result["latency_ms"] = (time.perf_counter() - started) * 1000
        emit(result)


if __name__ == "__main__":
    main()
