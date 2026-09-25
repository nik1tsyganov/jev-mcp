#!/usr/bin/env python3
"""Isolated Jev Ultrafast browser trial — experiment only, no production code.

Drives the pinned upstream browser-use/jev-ultrafast agent against three
loopback HTML fixtures. Each fixture owns a deterministic completion state
(window.__trial) that is independent of the agent's DONE/BLOCKED claims and
records incorrect actions (wrong item, bad value, premature submit, disabled
or covered control interactions).

Seams (all patched in-process, upstream source never modified):
  browser transport : jev_ultrafast.browser.cdp + ensure_daemon -> direct CDP
                      websocket to the --cdp-url endpoint (never the
                      browser-harness daemon, never the user's Chrome).
  decision HTTP     : jev_ultrafast.model.post_json -> injected --decider
                      callable. Replacing the whole function also removes
                      upstream's internal 429/5xx retry loop: no hidden
                      retries. The decider contract is one systemOne request
                      per call, returning the parsed JSON body.
  TYPE_TEXT helper  : jev_ultrafast.agent.field_text -> exact string from the
                      task definition. Every result is labelled
                      "fixed-text-helper"; this is NOT a full upstream
                      reproduction.

Bounds (hard): 3 tasks x 3 repetitions, <=8 decisions per run, <=72 Jev
requests total. Dry run (no --live) makes no API or browser calls.
"""

import argparse
import base64
import functools
import importlib
import hashlib
import json
import os
import socket
import struct
import sys
import threading
import time
import types
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PIN = "1231850a0bf1a0c0341fe408ef1668dbbfdfac46"
UPSTREAM_REPO = "browser-use/jev-ultrafast"
HELPER_LABEL = "fixed-text-helper"

REPS = 3
MAX_DECISIONS_PER_RUN = 8
MAX_JEV_REQUESTS = 72  # == 3 tasks * 3 reps * 8 decisions; no retries permitted

FIXTURES = Path(__file__).with_name("fixtures")

TASKS = [
    {
        "id": "pick-item",
        "page": "pick-item.html",
        "goal": 'On the supply depot page, select the item "Kestrel".',
        "expect": {"selected": "kestrel"},
        # Runner-driven deterministic stale-node probe: after the first
        # node-targeting decision, the chosen DOM node is clone-replaced
        # between predict and act; the executor must refuse (StalePage).
        "stale_probe": True,
    },
    {
        "id": "fill-text",
        "page": "fill-text.html",
        "goal": 'Enter the access code "delta-5930-quill" into the access code field and save it.',
        "fill_text": "delta-5930-quill",
        "expect": {"saved": True, "value": "delta-5930-quill"},
    },
    {
        "id": "select-submit",
        "page": "select-submit.html",
        "goal": 'Set the shipping speed to "Courier" and submit the order preferences.',
        "expect": {"submitted": True, "value": "courier"},
    },
]

# Page-target URLs tolerated on the supplied Chrome at connect time. Anything
# else means the endpoint is a used profile (e.g. the user's daily browser).
def _fresh_url(url):
    return url == "about:blank" or url.startswith("about:") or url.startswith("chrome://new")


# --------------------------------------------------------------------------
# CDP transport: websockets library if installed, else minimal stdlib client.
# --------------------------------------------------------------------------

class _MiniWS:
    """Smallest sufficient RFC 6455 client for a loopback CDP endpoint."""

    def __init__(self, url, timeout=30):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{u.port or 80}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("CDP websocket handshake closed")
            buf += chunk
        head, _, self._buf = buf.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0]
        if b" 101" not in status:
            raise RuntimeError("CDP websocket upgrade refused: " + status.decode(errors="replace"))

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("CDP websocket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        header = bytearray([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def send(self, text):
        self._send_frame(0x1, text.encode())

    def recv(self):
        parts = []
        while True:
            b1, b2 = self._read(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            if b2 & 0x80:
                self._read(4)  # masked server frame: consume the key
            payload = self._read(length) if length else b""
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0x8:
                raise RuntimeError("CDP websocket closed by peer")
            if opcode == 0xA:
                continue
            parts.append(payload)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        self.sock.close()


class _LibWS:
    """Adapter over an installed websockets.sync.client connection."""

    def __init__(self, ws):
        self.ws = ws

    def send(self, text):
        self.ws.send(text)

    def recv(self):
        msg = self.ws.recv()
        return msg.decode() if isinstance(msg, (bytes, bytearray)) else msg

    def close(self):
        self.ws.close()


def _connect_ws(url):
    try:
        from websockets.sync.client import connect
        return _LibWS(connect(url, open_timeout=30, max_size=None))
    except ImportError:
        return _MiniWS(url)


class Cdp:
    """One CDP websocket: browser-level and flattened session commands."""

    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0

    def command(self, method, params=None, session_id=None):
        self.next_id += 1
        msg = {"id": self.next_id, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        self.ws.send(json.dumps(msg))
        while True:
            data = json.loads(self.ws.recv())
            if data.get("id") != self.next_id:
                continue  # CDP events carry no id; this trial subscribes to none
            if "error" in data:
                raise RuntimeError(f"CDP {method}: {data['error'].get('message')}")
            return data.get("result", {})

    def close(self):
        self.ws.close()


def _loopback_only(host):
    if host in {"127.0.0.1", "::1", "[::1]"}:
        return
    if host == "localhost":
        infos = socket.getaddrinfo("localhost", None)
        if infos and all(i[4][0] in ("127.0.0.1", "::1") for i in infos):
            return
    raise RuntimeError(f"--cdp-url host {host!r} is not loopback; refusing non-isolated endpoint")


def connect_isolated(cdp_url):
    """Resolve --cdp-url to a browser websocket and prove it is isolated."""
    u = urllib.parse.urlparse(cdp_url)
    if u.scheme in ("http", "https"):
        _loopback_only(u.hostname)
        with urllib.request.urlopen(cdp_url.rstrip("/") + "/json/version", timeout=10) as r:
            ws_url = json.load(r)["webSocketDebuggerUrl"]
    elif u.scheme == "ws":
        ws_url = cdp_url
    else:
        raise RuntimeError("--cdp-url must be http://127.0.0.1:PORT or a ws:// devtools URL")
    _loopback_only(urllib.parse.urlparse(ws_url).hostname)

    conn = Cdp(_connect_ws(ws_url))
    version = conn.command("Browser.getVersion")
    product = version.get("product", "")
    if "Chrom" not in product:
        conn.close()
        raise RuntimeError(f"CDP endpoint is not Chrome-family (product={product!r}); refusing")
    targets = conn.command("Target.getTargets").get("targetInfos", [])
    used = [t["url"] for t in targets if t.get("type") == "page" and not _fresh_url(t.get("url", ""))]
    if used:
        conn.close()
        raise RuntimeError(
            "CDP endpoint serves a used profile, not an isolated fresh Chrome. "
            f"Existing page targets: {used}. Launch Chrome with a fresh --user-data-dir."
        )
    pages = [t["url"] for t in targets if t.get("type") == "page"]
    return conn, {"product": product, "page_targets_at_connect": pages}


# --------------------------------------------------------------------------
# Upstream import: stub only the modules that are absent and that we replace
# anyway, so a bare interpreter can run the pinned source unmodified.
# --------------------------------------------------------------------------

def _stub_module(name, attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


def _ensure_importable():
    try:
        import httpx  # noqa: F401
    except ImportError:
        class _HTTPError(Exception):
            pass

        class _Client:
            def __init__(self, **kw):
                pass

        _stub_module("httpx", {"Client": _Client, "HTTPError": _HTTPError})
    try:
        import browser_harness.admin  # noqa: F401
        import browser_harness.helpers  # noqa: F401
    except ImportError:
        pkg = _stub_module("browser_harness", {"__path__": []})
        pkg.admin = _stub_module("browser_harness.admin", {"ensure_daemon": lambda: None})
        pkg.helpers = _stub_module("browser_harness.helpers", {"cdp": None})


def load_upstream(source):
    source = Path(source).resolve()
    if not (source / "jev_ultrafast" / "agent.py").is_file():
        raise RuntimeError(f"--source {source} has no jev_ultrafast/agent.py; expected the pinned checkout")
    _ensure_importable()
    sys.path.insert(0, str(source))
    up = types.SimpleNamespace(
        agent=importlib.import_module("jev_ultrafast.agent"),
        model=importlib.import_module("jev_ultrafast.model"),
        browser=importlib.import_module("jev_ultrafast.browser"),
    )
    import subprocess

    try:
        commit = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
    except Exception:
        commit = None
    if not commit:
        manifest_path = source / "trial-source.json"
        if not manifest_path.is_file():
            raise RuntimeError("Pinned source requires git HEAD or trial-source.json hashes")
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("pin") != PIN:
            raise RuntimeError("Source manifest pin mismatch")
        for rel, expected in manifest["sha256"].items():
            if hashlib.sha256((source / rel).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Source hash mismatch: {rel}")
        commit = manifest["pin"]
    if commit and commit != PIN:
        raise RuntimeError(f"--source resolves to {commit}, not the pinned {PIN}; refusing")
    return up, commit


# --------------------------------------------------------------------------
# Decision capture + request cap
# --------------------------------------------------------------------------

class Capture:
    """Wraps the injected decider: counts, caps, and serializes every real
    decision payload to JSONL (exact objects, never re-keyed)."""

    def __init__(self, fh, ctx, decide, cap):
        self.fh = fh
        self.ctx = ctx
        self.decide = decide
        self.cap = cap
        self.count = 0
        self.seq = 0
        self.cap_reached = False

    def post_json(self, url, key, body):
        if self.count >= self.cap:
            self.cap_reached = True
            raise RuntimeError(f"Jev request cap {self.cap} reached; refusing request {self.count + 1}")
        self.count += 1
        started = time.perf_counter()
        resp, failure = None, None
        try:
            resp = self.decide(body)
        except Exception as exc:
            failure = exc
        latency = round((time.perf_counter() - started) * 1000)
        self.seq += 1
        self.fh.write(
            json.dumps(
                {
                    "id": self.seq,
                    "run_id": self.ctx.get("run_id"),
                    "task_id": self.ctx.get("task_id"),
                    "rep": self.ctx.get("rep"),
                    "endpoint": url,
                    "state": body.get("state"),
                    "questions": body.get("questions"),
                    "request": body,
                    "requested_model": body.get("model"),
                    "response": resp,
                    "error": str(failure) if failure else None,
                    "model": resp.get("model") if isinstance(resp, dict) else None,
                    "latency_ms": latency,
                },
                default=str,
            )
            + "\n"
        )
        self.fh.flush()
        if failure is not None:
            raise failure
        return resp


# --------------------------------------------------------------------------
# Fixture server + run loop
# --------------------------------------------------------------------------

class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve_fixtures():
    handler = functools.partial(_Quiet, directory=str(FIXTURES))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


STALE_REPLACE_JS = (
    "(n=>{const c=window.__jevFast;const e=c&&c.nodes.get(n);"
    "if(!e||!e.isConnected)return false;e.replaceWith(e.cloneNode(true));return true;})(%d)"
)


def _verify(agent, task):
    """Deterministic final verifier: page-owned state, ignores DONE/BLOCKED."""
    raw = agent.browser.evaluate("window.__trial ? JSON.stringify(window.__trial) : null")
    trial = json.loads(raw) if raw else None
    out = {"trial": trial}
    if trial is None:
        out["verdict"] = "invalid"  # instrument did not populate; not a real result
    else:
        checks = {k: trial.get(k) == v for k, v in task["expect"].items()}
        out["checks"] = checks
        out["fixture_errors"] = trial.get("errors", [])
        out["completed"] = trial.get("complete") is True and all(checks.values())
        out["verdict"] = "pass" if out["completed"] and not out["fixture_errors"] else "fail"
    return out


def run_one(up, capture, ctx, task, rep, origin, max_decisions):
    run_id = f"{task['id']}-r{rep}-{uuid.uuid4().hex[:8]}"
    ctx.update(task_id=task["id"], rep=rep, run_id=run_id, fill_text=task.get("fill_text"))
    rec = {
        "run_id": run_id,
        "task_id": task["id"],
        "rep": rep,
        "helper_mode": HELPER_LABEL,
        "goal": task["goal"],
        "expect": task["expect"],
        "stop_reason": None,
        "agent_status": None,
        "verdict": "invalid",
        "requests_used": 0,
    }
    start_count = capture.count
    agent = None
    st = None
    try:
        agent = up.agent.Agent(origin + "/" + task["page"], task["goal"])
        st = agent.state
        probe_pending = bool(task.get("stale_probe"))
        while st["status"] not in ("done", "blocked"):
            if len(st["decisions"]) >= max_decisions:
                rec["stop_reason"] = "decision_cap"
                break
            if capture.cap_reached:
                rec["stop_reason"] = "request_cap"
                break
            try:
                agent.command("predict", {})
            except up.browser.StalePage:
                st["decision"] = None
                st["status"] = "ready"
                st["page"] = st["browser"].observe(screenshot=False)
                continue
            decision = st["decision"]
            probe_ran = False
            if probe_pending and decision and decision["choice"] not in ("DONE", "BLOCKED"):
                action = next((a for a in st["page"]["actions"] if a["id"] == decision["choice"]), None)
                if action and action["kind"] in ("click", "fill", "select") and type(action.get("node")) is int:
                    probe_pending = False
                    probe_ran = True
                    mutated = agent.browser.evaluate(STALE_REPLACE_JS % action["node"])
                    probe = {"node": action["node"], "kind": action["kind"], "mutated": mutated}
                    try:
                        agent.command("act", {"fingerprint": st["page"]["fingerprint"]})
                        probe["outcome"] = "acted_on_stale_node"  # executor failed its guard
                    except up.browser.StalePage:
                        probe["outcome"] = "refused_stale"
                    except Exception as e:
                        probe["outcome"] = f"error:{type(e).__name__}:{e}"
                    rec["stale_probe"] = probe
            if not probe_ran:
                try:
                    agent.command("act", {"fingerprint": st["page"]["fingerprint"]})
                except up.browser.StalePage as e:
                    rec.setdefault("stale_events", []).append(str(e))
                    st["decision"] = None
                    st["status"] = "ready"
                    st["page"] = st["browser"].observe(screenshot=False)
                    continue
            if st["status"] not in ("done", "blocked"):
                if probe_ran and rec["stale_probe"]["outcome"] != "acted_on_stale_node":
                    # Refused mid-act: decision was consumed before the guard
                    # fired, so re-observe exactly like upstream tick's branch.
                    st["page"] = st["browser"].observe(screenshot=False)
                st["decision"] = None
                st["status"] = "ready"
            if urllib.parse.urlparse(st["page"]["url"]).netloc != urllib.parse.urlparse(origin).netloc:
                rec["stop_reason"] = "off_origin"
                break
        rec["stop_reason"] = rec["stop_reason"] or st["status"]
        rec.update(_verify(agent, task))
    except Exception as e:
        rec["stop_reason"] = rec["stop_reason"] or f"error:{type(e).__name__}"
        rec["error"] = f"{type(e).__name__}: {e}"
        if agent is not None:
            try:
                rec.update(_verify(agent, task))  # evidence up to the failure still counts
            except Exception as ve:
                rec["verify_error"] = f"{type(ve).__name__}: {ve}"
    finally:
        if st is not None:
            rec["agent_status"] = st["status"]
            rec["decisions"] = [
                {k: d.get(k) for k in ("operation", "target", "choice", "confidence",
                                       "latency_ms", "model", "probabilities")}
                for d in st["decisions"]
            ]
            rec["history"] = st["history"]
            rec["text_calls"] = st["text_calls"]
        if agent is not None:
            try:
                agent.close()  # Target.closeTarget on the tab we created; nothing else
            except Exception as e:
                rec["close_error"] = str(e)
        rec["requests_used"] = capture.count - start_count
        rec["elapsed_ms"] = st.get("elapsed_ms") if st else None
        if rec.get("error") or rec.get("stale_probe", {}).get("outcome", "refused_stale") != "refused_stale":
            rec["verdict"] = "fail"
    return rec


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

DRY_RUN = """DRY RUN — no API calls, no browser connection.

Plan : {tasks} tasks x {reps} repetitions = {runs} runs
Caps : <= {max_decisions} decisions per run, <= {max_requests} Jev requests total, no retries
Tasks: pick-item (distractors + disabled + covered + stale-node probe)
       fill-text (exact fixed text + save confirm + readonly/disabled/covered decoys)
       select-submit (select value incl. disabled options + submit + decoys)
Text : TYPE_TEXT uses a fixed task-defined string; all results labelled "{helper}"
       — this is not a full upstream reproduction.

Required for --live:
  --source PATH    checkout of {repo} @ {pin}
  --cdp-url URL    http://127.0.0.1:PORT or ws://... of an ISOLATED Chrome
                   launched with a fresh --user-data-dir and
                   --remote-debugging-port. Never your daily browser and
                   never the browser-harness daemon endpoint.
  --decider MOD:F  callable(body) -> dict returning the raw systemOne JSON;
                   exactly one request per call, no retries, no secrets here
  --out PATH       results.json + decisions.jsonl are written there
"""


def main():
    p = argparse.ArgumentParser(description="Isolated Jev Ultrafast browser trial (dry run by default)")
    p.add_argument("--source", help="Path to pinned upstream jev-ultrafast checkout")
    p.add_argument("--out", help="Output directory for results.json + decisions.jsonl")
    p.add_argument("--cdp-url", help="Loopback CDP endpoint of an explicitly isolated Chrome")
    p.add_argument("--decider", help="module:callable supplying the Jev systemOne client")
    p.add_argument("--live", action="store_true", help="Actually run; without it only the plan is printed")
    p.add_argument("--reps", type=int, default=REPS, choices=range(1, REPS + 1))
    p.add_argument("--max-decisions", type=int, default=MAX_DECISIONS_PER_RUN,
                   choices=range(1, MAX_DECISIONS_PER_RUN + 1))
    args = p.parse_args()

    if not args.live:
        print(DRY_RUN.format(
            tasks=len(TASKS), reps=args.reps, runs=len(TASKS) * args.reps,
            max_decisions=args.max_decisions, max_requests=MAX_JEV_REQUESTS,
            helper=HELPER_LABEL, repo=UPSTREAM_REPO, pin=PIN))
        if args.source:
            try:
                _, commit = load_upstream(args.source)
                print(f"--source OK, resolved commit {commit or '(unresolved: not a git checkout)'}")
            except Exception as e:
                print(f"--source INVALID: {e}")
        return 0

    missing = [n for n, v in (("--source", args.source), ("--cdp-url", args.cdp_url),
                              ("--decider", args.decider), ("--out", args.out)) if not v]
    if missing:
        p.error("--live requires " + ", ".join(missing))

    mod_name, _, func_name = args.decider.partition(":")
    if not func_name:
        p.error("--decider must be module:callable")
    sys.path.insert(0, os.getcwd())
    decide = getattr(importlib.import_module(mod_name), func_name)

    conn, isolation = connect_isolated(args.cdp_url)
    up, commit = load_upstream(args.source)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ctx = {}
    server, origin = serve_fixtures()
    results = {
        "experiment": "jev-ultrafast-browser-trial",
        "helper_mode": HELPER_LABEL,
        "note": "TYPE_TEXT used fixed task-defined strings; not a full upstream reproduction.",
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6],
        "source": {"repo": UPSTREAM_REPO, "pin": PIN, "resolved_commit": commit},
        "bounds": {"reps_per_task": args.reps, "max_decisions_per_run": args.max_decisions,
                   "max_jev_requests": MAX_JEV_REQUESTS, "retries": "none"},
        "isolation": {"cdp_url": args.cdp_url, **isolation, "fixture_origin": origin},
        "runs": [],
    }
    try:
        with open(out / "decisions.jsonl", "w") as fh:
            capture = Capture(fh, ctx, decide, MAX_JEV_REQUESTS)
            # Upstream choose() evaluates os.environ["TYPESAFE_API_KEY"] before
            # post_json runs. The patched seam ignores the key — the decider
            # owns credentials — so a placeholder prevents a KeyError without
            # reading or overriding a real credential.
            os.environ.setdefault("TYPESAFE_API_KEY", "unused-injected-decider")
            # Patch the three seams on the imported upstream modules.
            up.browser.ensure_daemon = lambda: None
            up.browser.cdp = lambda method, session_id=None, **params: conn.command(
                method, params, session_id)
            up.model.post_json = capture.post_json
            up.agent.field_text = lambda context: (
                ctx["fill_text"] or "", {"model": HELPER_LABEL, "latency_ms": 0, "usage": {}})

            for task in TASKS:
                for rep in range(1, args.reps + 1):
                    if capture.cap_reached:
                        break
                    rec = run_one(up, capture, ctx, task, rep, origin, args.max_decisions)
                    results["runs"].append(rec)
                    print(f"{task['id']} rep {rep}: verdict={rec['verdict']} "
                          f"stop={rec['stop_reason']} requests={rec['requests_used']}")
        results["requests_total"] = capture.count
        results["request_cap_reached"] = capture.cap_reached
    finally:
        server.shutdown()
        server.server_close()
        conn.close()  # websocket only; the Chrome process belongs to the caller

    with open(out / "results.json", "w") as f:
        json.dump(results, f, indent=1, default=str)
    print(f"wrote {out / 'results.json'} and {out / 'decisions.jsonl'} "
          f"({results['requests_total']} Jev requests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
