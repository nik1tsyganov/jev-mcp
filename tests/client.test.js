import test from "node:test";
import assert from "node:assert/strict";
import {
  systemOne, listModels, redact, _resetClient,
  resolveApiKey, credentialAvailable, credentialScope,
} from "../src/client.js";

const FAKE_KEY = "sk-test-NOTAREALKEY";

test("offline test: error whose message contains a fake api key comes back redacted", async () => {
  const originalFetch = globalThis.fetch;
  const originalKey = process.env.TYPESAFE_API_KEY;
  const originalScope = process.env.DROPPY_CREDENTIAL_SCOPE;
  delete process.env.DROPPY_CREDENTIAL_SCOPE;
  process.env.TYPESAFE_API_KEY = FAKE_KEY;
  _resetClient();

  try {
    // Mock global fetch to simulate an upstream proxy or server echoing the key in the response body
    globalThis.fetch = async () => {
      return new Response(JSON.stringify({ error: `Upstream error: invalid key ${FAKE_KEY}` }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    };

    await assert.rejects(
      async () => {
        await systemOne({
          state: "test state",
          questions: {
            q1: { type: "noul", instructions: "Is this valid?" },
          },
        });
      },
      (err) => {
        assert.strictEqual(
          err.message.includes(FAKE_KEY),
          false,
          `Expected error message not to contain fake key, got: ${err.message}`
        );
        assert.match(err.message, /\[redacted\]/);
        assert.strictEqual(err.name, "AuthenticationError");
        assert.strictEqual(err.status, 401);
        return true;
      }
    );

    await assert.rejects(
      async () => {
        await listModels();
      },
      (err) => {
        assert.strictEqual(
          err.message.includes(FAKE_KEY),
          false,
          `Expected error message not to contain fake key, got: ${err.message}`
        );
        assert.match(err.message, /\[redacted\]/);
        assert.strictEqual(err.name, "AuthenticationError");
        assert.strictEqual(err.status, 401);
        return true;
      }
    );

    const direct = redact(`Error with ${FAKE_KEY} and Bearer secret-token`);
    assert.strictEqual(direct.includes(FAKE_KEY), false);
    assert.match(direct, /\[redacted\]/);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalScope === undefined) delete process.env.DROPPY_CREDENTIAL_SCOPE;
    else process.env.DROPPY_CREDENTIAL_SCOPE = originalScope;
    if (originalKey !== undefined) {
      process.env.TYPESAFE_API_KEY = originalKey;
    } else {
      delete process.env.TYPESAFE_API_KEY;
    }
    _resetClient();
  }
});

/* ---- credential scope and keyless contract (fake keys only) ---- */

function withEnv(vars, fn) {
  const saved = {};
  for (const key of Object.keys(vars)) {
    saved[key] = process.env[key];
    if (vars[key] === undefined) delete process.env[key];
    else process.env[key] = vars[key];
  }
  _resetClient();
  try {
    return fn();
  } finally {
    for (const key of Object.keys(vars)) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    }
    _resetClient();
  }
}

test("app scope ignores an inherited legacy key when the app key is blank", () => {
  withEnv({
    DROPPY_CREDENTIAL_SCOPE: "app",
    DROPPY_JEV_API_KEY: "   ",
    TYPESAFE_API_KEY: "sk-legacy-INHERITED",
  }, () => {
    assert.equal(credentialScope(), "app");
    assert.equal(credentialAvailable(), false);
    assert.throws(() => resolveApiKey(), /DROPPY_JEV_API_KEY/);
  });
});

test("app scope uses only the trimmed app key and never touches the legacy key", () => {
  withEnv({
    DROPPY_CREDENTIAL_SCOPE: "app",
    DROPPY_JEV_API_KEY: "  sk-app-ONLY  ",
    TYPESAFE_API_KEY: "sk-legacy-INHERITED",
  }, () => {
    assert.equal(credentialAvailable(), true);
    assert.equal(resolveApiKey(), "sk-app-ONLY");
    const out = redact(`failed with sk-app-ONLY and sk-legacy-INHERITED`);
    assert.equal(out.includes("sk-app-ONLY"), false);
    assert.equal(out.includes("sk-legacy-INHERITED"), false);
  });
});

test("outside app scope the legacy env key still resolves", () => {
  withEnv({
    DROPPY_CREDENTIAL_SCOPE: undefined,
    DROPPY_JEV_API_KEY: undefined,
    TYPESAFE_API_KEY: "sk-legacy-INHERITED",
  }, () => {
    assert.equal(credentialScope(), "default");
    assert.equal(resolveApiKey(), "sk-legacy-INHERITED");
    assert.equal(credentialAvailable(), true);
  });
});

test("a scope or key change cannot reuse a cached credential", () => {
  const vars = { DROPPY_CREDENTIAL_SCOPE: "app", DROPPY_JEV_API_KEY: "sk-app-FIRST", TYPESAFE_API_KEY: "sk-legacy-INHERITED" };
  const saved = {};
  for (const key of Object.keys(vars)) { saved[key] = process.env[key]; process.env[key] = vars[key]; }
  _resetClient();
  try {
    assert.equal(resolveApiKey(), "sk-app-FIRST");
    process.env.DROPPY_JEV_API_KEY = "sk-app-SECOND";
    assert.equal(resolveApiKey(), "sk-app-SECOND");
    delete process.env.DROPPY_CREDENTIAL_SCOPE;
    assert.equal(resolveApiKey(), "sk-legacy-INHERITED");
  } finally {
    for (const key of Object.keys(vars)) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    }
    _resetClient();
  }
});

test("SDK requests refresh credentials and cannot reuse a removed app key", async () => {
  const names = ["DROPPY_CREDENTIAL_SCOPE", "DROPPY_JEV_API_KEY", "DROPPY_DECISION_MODE", "TYPESAFE_API_KEY"];
  const saved = Object.fromEntries(names.map(name => [name, process.env[name]]));
  const originalFetch = globalThis.fetch;
  const headers = [];
  try {
    delete process.env.DROPPY_CREDENTIAL_SCOPE;
    delete process.env.DROPPY_DECISION_MODE;
    process.env.TYPESAFE_API_KEY = "test-legacy-only";
    _resetClient();
    globalThis.fetch = async (input, init) => {
      headers.push(new Headers(init?.headers ?? input.headers).get("authorization"));
      return new Response(JSON.stringify({error:"invalid test key"}), {status:401, headers:{"Content-Type":"application/json"}});
    };
    await assert.rejects(listModels);
    process.env.DROPPY_CREDENTIAL_SCOPE = "app";
    process.env.DROPPY_JEV_API_KEY = "test-app-only";
    await assert.rejects(listModels);
    assert.deepEqual(headers, ["Bearer test-legacy-only", "Bearer test-app-only"]);
    process.env.DROPPY_JEV_API_KEY = "";
    await assert.rejects(listModels, /DROPPY_JEV_API_KEY/);
    process.env.DROPPY_JEV_API_KEY = "test-app-only";
    process.env.DROPPY_DECISION_MODE = "local";
    await assert.rejects(listModels, /prohibits Jev/);
    assert.equal(headers.length, 2);
  } finally {
    globalThis.fetch = originalFetch;
    for (const name of names) {
      if (saved[name] === undefined) delete process.env[name]; else process.env[name] = saved[name];
    }
    _resetClient();
  }
});

test("schema 2 spend rows record the caller, latency and failures", { skip: !process.env.TYPESAFE_SPEND_LOG && "run through npm test so the spend log is a temp file" }, async () => {
  const { readFileSync, rmSync } = await import("node:fs");
  const log = process.env.TYPESAFE_SPEND_LOG;
  const originalFetch = globalThis.fetch;
  const originalKey = process.env.TYPESAFE_API_KEY;
  const originalScope = process.env.DROPPY_CREDENTIAL_SCOPE;
  delete process.env.DROPPY_CREDENTIAL_SCOPE;
  process.env.TYPESAFE_API_KEY = FAKE_KEY;
  _resetClient();
  rmSync(log, { force: true });
  const questions = { q1: { type: "noul", instructions: "Is this valid?" } };
  const caller = { tool: "jev_noul", client: "test-client@1", purpose: "unit-test" };
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({
      model: "jev-test", answers: { q1: { type: "noul", noul: 0.9 } }, usage: { input_tokens: 5, output_tokens: 2 },
    }), { status: 200, headers: { "Content-Type": "application/json" } });
    await systemOne({ state: "s", questions, caller });
    globalThis.fetch = async () => new Response(JSON.stringify({ error: "bad request" }), {
      status: 400, headers: { "Content-Type": "application/json" },
    });
    await assert.rejects(systemOne({ state: "s", questions, caller }));
    const rows = readFileSync(log, "utf8").trim().split("\n").map((line) => JSON.parse(line));
    assert.equal(rows.length, 2);
    for (const row of rows) {
      assert.equal(row.schema, 2);
      assert.equal(row.source, "mcp");
      assert.equal(row.tool, "jev_noul");
      assert.equal(row.client, "test-client@1");
      assert.equal(row.purpose, "unit-test");
      assert.equal(row.cwd, process.cwd());
      assert.equal(typeof row.latency_ms, "number");
    }
    assert.equal(rows[0].ok, true);
    assert.equal(rows[0].input_tokens, 5);
    assert.equal(rows[1].ok, false);
    assert.equal(rows[1].input_tokens, null);
    assert.equal(JSON.stringify(rows[1]).includes(FAKE_KEY), false);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalKey === undefined) delete process.env.TYPESAFE_API_KEY; else process.env.TYPESAFE_API_KEY = originalKey;
    if (originalScope === undefined) delete process.env.DROPPY_CREDENTIAL_SCOPE; else process.env.DROPPY_CREDENTIAL_SCOPE = originalScope;
    _resetClient();
  }
});

test("a call that fails before reaching Jev is still logged as a failure", { skip: !process.env.TYPESAFE_SPEND_LOG && "run through npm test so the spend log is a temp file" }, async () => {
  const { readFileSync, rmSync } = await import("node:fs");
  const log = process.env.TYPESAFE_SPEND_LOG;
  const names = ["DROPPY_CREDENTIAL_SCOPE", "DROPPY_JEV_API_KEY"];
  const saved = Object.fromEntries(names.map((n) => [n, process.env[n]]));
  rmSync(log, { force: true });
  try {
    process.env.DROPPY_CREDENTIAL_SCOPE = "app";
    process.env.DROPPY_JEV_API_KEY = "";
    _resetClient();
    await assert.rejects(systemOne({
      state: "s", questions: { q1: { type: "noul", instructions: "Is this valid?" } }, caller: { tool: "jev_noul" },
    }), /DROPPY_JEV_API_KEY/);
    const rows = readFileSync(log, "utf8").trim().split("\n").map((line) => JSON.parse(line));
    assert.equal(rows.length, 1);
    assert.equal(rows[0].ok, false);
    assert.equal(rows[0].tool, "jev_noul");
  } finally {
    for (const n of names) { if (saved[n] === undefined) delete process.env[n]; else process.env[n] = saved[n]; }
    _resetClient();
  }
});
