import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { createLayaClient, sanitizeLayaError } from "../src/laya-client.js";

const WORKER = "/tools/laya_worker.py";

/** A fake worker process: EventEmitter + PassThrough streams, no real subprocess. */
function fakeWorker({ ready = true, onRequest, onSpawn } = {}) {
  const calls = [];
  const spawn = (cmd, args, options) => {
    const child = new EventEmitter();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    child.stdin = new PassThrough();
    child.killed = false;
    child.kill = (signal) => {
      if (child.killed) return;
      child.killed = true;
      setImmediate(() => child.emit("exit", null, signal));
    };
    let buf = "";
    child.stdin.on("data", (chunk) => {
      buf += chunk.toString();
      let index;
      while ((index = buf.indexOf("\n")) !== -1) {
        const line = buf.slice(0, index).trim();
        buf = buf.slice(index + 1);
        if (line && onRequest) onRequest(JSON.parse(line), child);
      }
    });
    calls.push({ cmd, args, options, child });
    if (onSpawn) onSpawn(child);
    if (ready) {
      setImmediate(() =>
        child.stdout.write(JSON.stringify({ type: "ready", checkpoint: "c", revision: "r" }) + "\n")
      );
    }
    return child;
  };
  return { spawn, calls };
}

function configured(overrides = {}) {
  return { python: "/venv/bin/python", modelPath: "/model", checkpoint: "c", revision: "r", workerPath: WORKER, ...overrides };
}

function resultLine(req, extra = {}) {
  return JSON.stringify({
    type: "result",
    id: req.id,
    result: {
      model: "c@r",
      checkpoint: "c",
      revision: "r",
      answers: { q: { type: "noul", noul: 0.7, confidence: 0.7 } },
      usage: { input_tokens: 3, output_tokens: 0 },
      backend: "laya-mlx",
      elapsed_ms: 1.5,
      ...extra,
    },
  }) + "\n";
}

test("status is unavailable with a reason when unconfigured", () => {
  const { spawn } = fakeWorker({ ready: false });
  const client = createLayaClient({ spawn, python: null, modelPath: null, checkpoint: null, revision: null });
  assert.deepEqual(client.status(), {
    available: false,
    checkpoint: null,
    revision: null,
    reason: "not configured: missing python, modelPath, checkpoint, revision",
  });
});

test("status is available when fully configured", () => {
  const { spawn } = fakeWorker({ ready: false });
  const client = createLayaClient(configured({ spawn }));
  assert.deepEqual(client.status(), { available: true, checkpoint: "c", revision: "r", reason: null });
});

test("predict spawns without a shell, passes config by argv, and strips credentials", async () => {
  const previousKey = process.env.TYPESAFE_API_KEY;
  const previousToken = process.env.HF_TOKEN;
  process.env.TYPESAFE_API_KEY = "sk-live-SECRET";
  process.env.HF_TOKEN = "hf_live_SECRET";
  const seen = [];
  const { spawn, calls } = fakeWorker({
    onRequest: (req, child) => {
      seen.push(req);
      child.stdout.write(resultLine(req));
    },
  });
  try {
    const client = createLayaClient(configured({ spawn }));
    const result = await client.predict({ state: "hello", questions: { q: { type: "noul", instructions: "Is it?" } } });
    assert.equal(result.model, "c@r");
    assert.equal(result.answers.q.noul, 0.7);
    assert.deepEqual(calls[0].args, [WORKER, "--model-dir", "/model", "--checkpoint", "c", "--revision", "r"]);
    assert.equal(calls[0].options.shell, false);
    assert.equal(calls[0].options.env.HF_HUB_OFFLINE, "1");
    assert.equal(calls[0].options.env.TRANSFORMERS_OFFLINE, "1");
    assert.equal(calls[0].options.env.TYPESAFE_API_KEY, undefined);
    assert.equal(calls[0].options.env.HF_TOKEN, undefined);
    assert.equal(seen[0].op, "predict");
    assert.equal(Object.prototype.hasOwnProperty.call(seen[0], "modelPath"), false);
    assert.equal(Object.prototype.hasOwnProperty.call(seen[0], "checkpoint"), false);
    client.close();
  } finally {
    if (previousKey === undefined) delete process.env.TYPESAFE_API_KEY;
    else process.env.TYPESAFE_API_KEY = previousKey;
    if (previousToken === undefined) delete process.env.HF_TOKEN;
    else process.env.HF_TOKEN = previousToken;
  }
});

test("predict rejects a malformed worker result", async () => {
  const { spawn } = fakeWorker({
    onRequest: (req, child) => {
      child.stdout.write(JSON.stringify({ type: "result", id: req.id, result: { model: "c@r", checkpoint: "c", revision: "r", usage: {} } }) + "\n");
    },
  });
  const client = createLayaClient(configured({ spawn }));
  await assert.rejects(
    client.predict({ state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } }),
    /answers/
  );
  client.close();
});

test("predict sanitizes a worker error message", async () => {
  const { spawn } = fakeWorker({
    onRequest: (req, child) => {
      child.stdout.write(
        JSON.stringify({ type: "error", id: req.id, error: { code: "load_failed", message: "failed hf_abcdefghijklmnop" } }) + "\n"
      );
    },
  });
  const client = createLayaClient(configured({ spawn }));
  await assert.rejects(
    client.predict({ state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } }),
    (err) => {
      assert.equal(err.message.includes("hf_abcdefghijklmnop"), false);
      assert.match(err.message, /\[redacted\]/);
      assert.equal(err.code, "load_failed");
      return true;
    }
  );
  client.close();
});

test("a timeout kills the worker and rejects every pending request deterministically", async () => {
  const { spawn, calls } = fakeWorker({ onRequest: () => {} });
  const client = createLayaClient(configured({ spawn, timeoutMs: 20 }));
  const first = client.predict({ state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } });
  const second = client.predict({ state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } });
  const errors = await Promise.all([first.catch((e) => e), second.catch((e) => e)]);
  assert.match(errors[0].message, /timed out/);
  assert.equal(errors[1].message, errors[0].message);
  assert.equal(calls[0].child.killed, true);
  client.close();
});

test("worker death rejects in-flight and pending requests with one message", async () => {
  const { spawn } = fakeWorker({ onRequest: (req, child) => child.emit("exit", 1, null) });
  const client = createLayaClient(configured({ spawn }));
  const first = client.predict({ state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } });
  const second = client.predict({ state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } });
  const errors = await Promise.all([first.catch((e) => e), second.catch((e) => e)]);
  assert.match(errors[0].message, /worker exited/);
  assert.equal(errors[1].message, errors[0].message);
  client.close();
});

test("the bounded queue rejects once it is full", async () => {
  const { spawn } = fakeWorker({ onRequest: () => {} });
  const client = createLayaClient(configured({ spawn, maxQueue: 1, timeoutMs: 5000 }));
  const inFlight = client.predict({ state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } });
  const queued = client.predict({ state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } });
  await assert.rejects(
    client.predict({ state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } }),
    (err) => err.code === "queue_full"
  );
  inFlight.catch(() => {});
  queued.catch(() => {});
  client.close();
});

test("predict rejects when the client is unconfigured", async () => {
  const { spawn } = fakeWorker({ ready: false });
  const client = createLayaClient({ spawn, python: null, modelPath: null, checkpoint: null, revision: null });
  await assert.rejects(
    client.predict({ state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } }),
    (err) => err.code === "unconfigured"
  );
});

test("predict validates questions locally before spawning", async () => {
  const { spawn, calls } = fakeWorker({ onRequest: () => {} });
  const client = createLayaClient(configured({ spawn }));
  await assert.rejects(client.predict({ state: "s", questions: {} }), /non-empty/);
  assert.equal(calls.length, 0);
});

test("close is idempotent and marks the client unavailable", async () => {
  const { spawn, calls } = fakeWorker({ onRequest: () => {} });
  const client = createLayaClient(configured({ spawn }));
  client.close();
  client.close();
  assert.equal(client.status().available, false);
  await assert.rejects(
    client.predict({ state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } }),
    (err) => err.code === "closed"
  );
  assert.equal(calls.length <= 1, true);
});

test("sanitizeLayaError redacts tokens and caps length", () => {
  const out = sanitizeLayaError(`Bearer abc.def and hf_abcdefghijklmnop ${"x".repeat(1000)}`);
  assert.equal(out.includes("hf_abcdefghijklmnop"), false);
  assert.match(out, /\[redacted\]/);
  assert.equal(out.length <= 500, true);
});

const smallRequest = { state: "s", questions: { q: { type: "noul", instructions: "Is it?" } } };

test("synchronous spawn failure rejects without an unhandled rejection", async () => {
  const client = createLayaClient(configured({ spawn: () => { throw new Error("spawn unavailable"); } }));
  await assert.rejects(client.predict(smallRequest), /spawn failed/);
  client.close();
});

test("a fatal protocol message kills the worker", async () => {
  const { spawn, calls } = fakeWorker({ onRequest: (_, child) => child.stdout.write(JSON.stringify({type:"fatal",error:{message:"fatal"}}) + "\n") });
  const client = createLayaClient(configured({ spawn }));
  await assert.rejects(client.predict(smallRequest), /fatal/);
  assert.equal(calls[0].child.killed, true);
  client.close();
});

test("a broken input pipe rejects the request without crashing", async () => {
  const { spawn } = fakeWorker({ onRequest: (_, child) => child.stdin.emit("error", new Error("EPIPE")) });
  const client = createLayaClient(configured({ spawn }));
  await assert.rejects(client.predict(smallRequest), /write failed/);
  client.close();
});

test("circular input fails before spawning", async () => {
  const { spawn, calls } = fakeWorker();
  const client = createLayaClient(configured({ spawn }));
  const state = {}; state.self = state;
  await assert.rejects(client.predict({...smallRequest,state}), /circular/i);
  assert.equal(calls.length, 0);
  client.close();
});

test("a dying worker cannot invalidate its replacement", async () => {
  const fake = fakeWorker({ onRequest: (req, child) => {
    if (fake.calls.length === 1) child.stdout.write(JSON.stringify({type:"fatal",error:{message:"first died"}}) + "\n");
    else child.stdout.write(resultLine(req));
  }});
  const client = createLayaClient(configured({ spawn: fake.spawn }));
  await assert.rejects(client.predict(smallRequest), /first died/);
  assert.equal((await client.predict(smallRequest)).model, "c@r");
  client.close();
});

test("a dead worker still reports available and respawns on the next predict", async () => {
  const fake = fakeWorker({ onRequest: (req, child) => {
    if (fake.calls.length === 1) child.emit("exit", 1, null);
    else child.stdout.write(resultLine(req));
  }});
  const client = createLayaClient(configured({ spawn: fake.spawn }));
  await assert.rejects(client.predict(smallRequest), /worker exited/);
  const status = client.status();
  assert.equal(status.available, true);
  assert.match(status.lastError, /worker exited/);
  assert.equal((await client.predict(smallRequest)).model, "c@r");
  assert.equal(fake.calls.length, 2);
  client.close();
});

test("a slow worker startup does not count against the request timeout", async () => {
  const fake = fakeWorker({ ready: false, onRequest: (req, child) => child.stdout.write(resultLine(req)) });
  const client = createLayaClient(configured({ spawn: fake.spawn, timeoutMs: 20, startupTimeoutMs: 5000 }));
  const pending = client.predict(smallRequest);
  await new Promise((resolve) => setTimeout(resolve, 60));
  fake.calls[0].child.stdout.write(JSON.stringify({ type: "ready", checkpoint: "c", revision: "r" }) + "\n");
  assert.equal((await pending).model, "c@r");
  client.close();
});

test("a worker that never becomes ready fails with startup-timeout and is killed", async () => {
  const fake = fakeWorker({ ready: false });
  const client = createLayaClient(configured({ spawn: fake.spawn, timeoutMs: 5000, startupTimeoutMs: 20 }));
  await assert.rejects(client.predict(smallRequest), (err) => err.code === "startup-timeout" && /startup timed out/.test(err.message));
  assert.equal(fake.calls[0].child.killed, true);
  client.close();
});
