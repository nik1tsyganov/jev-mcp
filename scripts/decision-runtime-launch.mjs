#!/usr/bin/env node
/**
 * Droppy Code decision-runtime launcher. Installed as launch.mjs at the
 * runtime root; starts the selected packaged server over stdio.
 *
 * Reads only runtime.json next to this file. A missing or unreadable config is
 * a setup error (exit 78). The first argument selects `jev` (default) or `laya`.
 * Laya requires python/modelPath/checkpoint/revision in config.laya and maps
 * those values to LAYA_*. Jev receives no LAYA_* variables. This
 * launcher never resolves or stores credentials, never fetches models and
 * never installs packages.
 */
import { existsSync, readFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const configPath = join(root, "runtime.json");
const provider = process.argv[2] ?? "jev";
if (provider !== "jev" && provider !== "laya") {
  fail(`unknown provider ${provider}; expected jev or laya.`);
}
const serverPath = join(root, "src", provider === "jev" ? "server.js" : "laya-server.js");

function fail(message) {
  process.stderr.write(`decision-runtime: ${message}\n`);
  process.exit(78); // EX_CONFIG
}

let raw;
try {
  raw = readFileSync(configPath, "utf8");
} catch {
  fail(`no runtime config at ${configPath}; run install-decision-runtime.py first.`);
}

let config;
try {
  config = JSON.parse(raw);
} catch (err) {
  fail(`runtime config at ${configPath} is not valid JSON: ${err.message}`);
}

if (!config || typeof config !== "object" || Array.isArray(config) || config.version !== 1) {
  fail(`runtime config at ${configPath} has an unsupported shape; expected {"version":1,...}.`);
}

const env = { ...process.env };
delete env.JEV_SHADOW_RATE;
delete env.DROPPY_DECISION_MODE;
// Worker identity comes only from this runtime's config; ambient host LAYA_*
// must not be able to point the packaged server at another machine's paths.
for (const key of Object.keys(env)) {
  if (key.startsWith("LAYA_")) delete env[key];
}
if (provider === "laya") {
  const laya = config.laya;
  if (!laya || typeof laya !== "object" || Array.isArray(laya)) {
    fail(`runtime config at ${configPath}: "laya" must be an object.`);
  }
  for (const key of ["python", "modelPath", "checkpoint", "revision"]) {
    if (typeof laya[key] !== "string" || !laya[key]) {
      fail(`runtime config at ${configPath} is missing laya.${key}; re-run the installer with --download-laya.`);
    }
  }
  if (!existsSync(laya.python)) {
    fail(`configured Python not found: ${laya.python}; re-run the installer with --download-laya.`);
  }
  if (!existsSync(laya.modelPath)) {
    fail(`configured local model not found: ${laya.modelPath}; re-run the installer with --download-laya.`);
  }
  env.LAYA_PYTHON = laya.python;
  env.LAYA_MODEL_DIR = laya.modelPath;
  env.LAYA_CHECKPOINT = laya.checkpoint;
  env.LAYA_MODEL_REVISION = laya.revision;
  for (const [key, value] of [["timeoutMs", laya.timeoutMs ?? 30000], ["maxQueue", laya.maxQueue ?? 8]]) {
    if (!Number.isInteger(value) || value <= 0) {
      fail(`runtime config at ${configPath}: laya.${key} must be a positive integer.`);
    }
    env[key === "timeoutMs" ? "LAYA_TIMEOUT_MS" : "LAYA_MAX_QUEUE"] = String(value);
  }
}

if (!existsSync(serverPath)) {
  fail(`packaged server missing at ${serverPath}; reinstall the decision runtime.`);
}

const child = spawn(process.execPath, [serverPath], { stdio: "inherit", env });
const SIGNALS = ["SIGINT", "SIGTERM", "SIGHUP"];
for (const signal of SIGNALS) {
  process.on(signal, () => {
    try {
      child.kill(signal);
    } catch {
      /* already gone */
    }
  });
}
child.on("error", (err) => fail(`could not start the server: ${err.message}`));
child.on("exit", (code, signal) => {
  if (signal) {
    // Die by the same signal so the host sees the real exit cause.
    for (const name of SIGNALS) process.removeAllListeners(name);
    try {
      process.kill(process.pid, signal);
    } catch {
      process.exit(1);
    }
    return;
  }
  process.exit(code ?? 1);
});
