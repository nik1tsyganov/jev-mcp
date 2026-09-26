"""One line per judgment request, shared by every tool here.

The MCP server logs its own calls from src/client.js. These Python tools post
directly, so without this they are invisible - and they are the ones that run a
corpus pass. Never raises: telemetry must not be able to fail a judgment.
"""
import json, os, time

LOG = os.environ.get("TYPESAFE_SPEND_LOG",
                     os.path.expanduser("~/.claude/docs/telemetry/jev-spend.jsonl"))

def record(tool, model, questions, usage, latency_ms=None):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as fh:
            fh.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "schema": 2,
                "source": "python",
                "tool": tool,
                "client": None,
                "purpose": tool,
                "cwd": os.getcwd(),
                "pid": os.getpid(),
                "ok": usage is not None,
                "latency_ms": latency_ms,
                "model": model,
                "questions": questions,
                "input_tokens": (usage or {}).get("input_tokens"),
                "output_tokens": (usage or {}).get("output_tokens"),
            }) + "\n")
    except OSError:
        pass
