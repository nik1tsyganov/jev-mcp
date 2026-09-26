#!/usr/bin/env node
// Checks that the `jev` and `laya` MCP servers are registered correctly in every
// client on this Mac and, with --live, that each registration starts and answers.
//
//   node tools/doctor.mjs                  # static: registrations, paths, links
//   node tools/doctor.mjs --live           # + start every distinct registration
//   node tools/doctor.mjs --live --after-restart   # + Droppy's launch exports
//
// Exit 0 only when every check passes. --live spends one Jev judgment (jev_noul) per distinct `jev`
// registration and two local Laya inferences per distinct `laya` registration; both are logged to temp files, not the real logs.
import { execFileSync } from "node:child_process";
import { accessSync, constants, existsSync, lstatSync, mkdtempSync, readFileSync, readlinkSync, statSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..");
const HOME = homedir();
const args = new Set(process.argv.slice(2));
const LIVE = args.has("--live");
const AFTER_RESTART = args.has("--after-restart");

const JEV_ARGS = [join(REPO, "src", "server.js")];
const LAYA_ARGS = [join(REPO, "src", "laya-server.js")];
const JEV_TOOLS = ["decision_browser_action", "jev_ask", "jev_choice", "jev_models", "jev_noul", "jev_score"];
const LAYA_TOOLS = ["laya_ask", "laya_bookmark_topic", "laya_status"];
const LAYA_KEYS = ["LAYA_CHECKPOINT", "LAYA_MAX_QUEUE", "LAYA_MODEL_DIR", "LAYA_MODEL_REVISION", "LAYA_PYTHON", "LAYA_TIMEOUT_MS"];
const DROPPY = join(HOME, "Library", "Application Support", "Droppy Code");

let failures = 0;
function report(ok, name, detail = "") {
  if (!ok) failures++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
}
function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}
function sameList(a, b) {
  return JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());
}

// The expected Laya env is the default profile's pinned runtime, so the generic
// worker and bookmark tagging load one model.
const registry = readJson(join(REPO, "config", "decision-profiles.json"));
const profile = registry.profiles[registry.defaultProfile];
const EXPECTED_LAYA_ENV = {
  LAYA_PYTHON: profile.runtime.python,
  LAYA_MODEL_DIR: profile.runtime.modelPath,
  LAYA_CHECKPOINT: profile.checkpoint,
  LAYA_MODEL_REVISION: profile.revision,
  LAYA_TIMEOUT_MS: String(profile.runtime.timeoutMs),
  LAYA_MAX_QUEUE: String(profile.runtime.maxQueue),
};

function resolveCommand(command) {
  if (command.includes("/")) return existsSync(command) ? command : null;
  try {
    return execFileSync("/bin/sh", ["-c", `command -v ${command}`], { encoding: "utf8" }).trim() || null;
  } catch {
    return null;
  }
}

function nodeMajor(command) {
  try {
    return Number(execFileSync(command, ["-p", "process.versions.node.split('.')[0]"], { encoding: "utf8" }).trim());
  } catch {
    return 0;
  }
}

const registrations = [];
function checkEntry(client, name, entry) {
  const where = `${client} ${name}`;
  if (!entry) return report(false, `${where} registered`, "missing");
  const command = entry.command;
  const argv = entry.args ?? [];
  const env = entry.env ?? {};
  const resolved = command ? resolveCommand(command) : null;
  // Apps opened from the Dock get launchd's PATH, so only an absolute command is portable.
  report(typeof command === "string" && command.startsWith("/") && Boolean(resolved) && nodeMajor(resolved) >= 20,
    `${where} command is an absolute Node >= 20`, `${command} -> ${resolved ?? "not found"}`);
  const wantArgs = name === "jev" ? JEV_ARGS : LAYA_ARGS;
  report(JSON.stringify(argv) === JSON.stringify(wantArgs), `${where} args`, argv.join(" "));
  if (name === "jev") {
    report(Object.keys(env).length === 0, `${where} has no env`, Object.keys(env).join(",") || "none");
  } else {
    const wrong = LAYA_KEYS.filter((k) => String(env[k] ?? "") !== EXPECTED_LAYA_ENV[k]);
    const extra = Object.keys(env).filter((k) => !LAYA_KEYS.includes(k));
    report(!wrong.length && !extra.length, `${where} env matches the default profile runtime`,
      [wrong.length && `differs: ${wrong.join(",")}`, extra.length && `extra: ${extra.join(",")}`].filter(Boolean).join("; ") || profile.checkpoint);
  }
  registrations.push({ client, name, command: resolved ?? command, args: argv, env });
}

// Shared paths.
report(existsSync(JEV_ARGS[0]) && existsSync(LAYA_ARGS[0]), "server entry points exist");
try {
  accessSync(EXPECTED_LAYA_ENV.LAYA_PYTHON, constants.X_OK);
  report(true, "LAYA_PYTHON is executable");
} catch {
  report(false, "LAYA_PYTHON is executable", EXPECTED_LAYA_ENV.LAYA_PYTHON);
}
report(existsSync(join(EXPECTED_LAYA_ENV.LAYA_MODEL_DIR, "model.safetensors")), "LAYA_MODEL_DIR holds model weights");
report(existsSync(join(REPO, "node_modules", "@modelcontextprotocol", "sdk")) && existsSync(join(REPO, "node_modules", "@typesafe-ai", "sdk")), "npm dependencies installed");
report(existsSync(join(HOME, ".config", "typesafe", "env.sh")), "TypeSafe key file present", "value not read");

// Claude, Cursor, Antigravity: JSON configs.
for (const [client, path] of [
  ["claude", join(HOME, ".claude.json")],
  ["cursor", join(HOME, ".cursor", "mcp.json")],
  ["antigravity", join(HOME, ".gemini", "config", "mcp_config.json")],
]) {
  let servers = {};
  try {
    servers = readJson(path).mcpServers ?? {};
  } catch (err) {
    report(false, `${client} config readable`, err.message);
    continue;
  }
  for (const name of ["jev", "laya"]) checkEntry(client, name, servers[name]);
  if (client === "claude") {
    const projects = readJson(path).projects ?? {};
    const shadows = Object.entries(projects).filter(([, p]) => p?.mcpServers?.jev || p?.mcpServers?.laya).map(([k]) => k);
    report(!shadows.length, "claude has no project-scope jev/laya shadowing the user entry", shadows.join(", ") || "none");
  }
}

// Codex: read through its own CLI rather than parsing TOML.
const codex = resolveCommand("codex");
if (!codex) {
  report(false, "codex CLI resolves");
} else {
  for (const name of ["jev", "laya"]) {
    try {
      const got = JSON.parse(execFileSync(codex, ["mcp", "get", name, "--json"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }));
      report(got.enabled === true, `codex ${name} enabled`);
      checkEntry("codex", name, { command: got.transport?.command, args: got.transport?.args, env: got.transport?.env ?? {} });
    } catch {
      report(false, `codex ${name} registered`, "codex mcp get failed");
    }
  }
}

// Droppy Code: custom definitions plus connection state.
try {
  const customs = readJson(join(DROPPY, "custom-mcp.json"));
  const conns = readJson(join(DROPPY, "mcp.json"));
  report(!customs.some((c) => c.id === "custom-jev-laya") && !conns.some((c) => c.catalogID === "custom-jev-laya"), "droppy has no old combined entry");
  for (const [id, name] of [["custom-jev", "jev"], ["custom-laya", "laya"]]) {
    const def = customs.find((c) => c.id === id);
    const conn = conns.find((c) => c.catalogID === id);
    report(Boolean(def), `droppy ${id} defined`);
    report(conn?.isEnabled === true && Boolean(conn?.connectedAt), `droppy ${id} enabled and connected`);
    if (!def || !conn) continue;
    const declared = (def.env ?? []).map((v) => v.key);
    const want = name === "jev" ? [] : LAYA_KEYS;
    report(sameList(declared, want), `droppy ${id} declares the right env keys`, declared.join(",") || "none");
    const env = Object.fromEntries(declared.map((k) => [k, conn.values?.[k] ?? ""]));
    checkEntry("droppy", name, { command: def.command, args: def.args, env });
    const wantTools = name === "jev" ? JEV_TOOLS : LAYA_TOOLS;
    report(sameList((conn.tools ?? []).map((t) => t.name), wantTools), `droppy ${id} cached tool list is current`);
  }
  if (AFTER_RESTART) {
    // Droppy rewrites its exports at launch; exports older than the running app
    // mean this instance has not loaded the current configuration.
    let started = null;
    try {
      // pgrep -x cannot match a name with a space, so read ps and match the app binary.
      const line = execFileSync("/bin/ps", ["-axo", "lstart=,command="], { encoding: "utf8" })
        .split("\n").find((l) => /\/Droppy Code\.app\/Contents\/MacOS\/Droppy Code$/.test(l.trim()));
      if (line) started = new Date(line.trim().split(/\s+/).slice(0, 5).join(" "));
    } catch { /* not running */ }
    report(Boolean(started), "droppy is running", started ? started.toISOString() : "not running");
    for (const file of ["claude.json", "codex.json", "copilot.json", "gemini-settings.json"]) {
      const exportedAt = statSync(join(DROPPY, "mcp", file)).mtime;
      report(Boolean(started) && exportedAt >= new Date(started.getTime() - 1000), `droppy export ${file} written by the running app`, exportedAt.toISOString());
      const exported = readJson(join(DROPPY, "mcp", file));
      const servers = exported.mcpServers ?? exported.mcp_servers ?? {};
      // The export is what providers launch, so it gets the same checks and a live start.
      for (const [id, name] of [["custom-jev", "jev"], ["custom-laya", "laya"]]) {
        checkEntry(`droppy-export ${file}`, name, servers[id]);
      }
    }
  }
} catch (err) {
  report(false, "droppy config readable", err.message);
}

// Rules reach Codex and Gemini through links to the one host file.
for (const link of [join(HOME, ".codex", "AGENTS.md"), join(HOME, ".gemini", "GEMINI.md")]) {
  let ok = false;
  try {
    ok = lstatSync(link).isSymbolicLink() && readlinkSync(link).endsWith(join(".claude", "AGENTS.md"));
  } catch { /* missing */ }
  report(ok, `${link.replace(HOME, "~")} links to ~/.claude/AGENTS.md`);
}

if (LIVE) await liveChecks();

console.log(`\n${failures === 0 ? "ALL CHECKS PASSED" : `${failures} CHECK(S) FAILED`}`);
process.exit(failures === 0 ? 0 : 1);

async function liveChecks() {
  const { Client } = await import("@modelcontextprotocol/sdk/client/index.js");
  const { StdioClientTransport } = await import("@modelcontextprotocol/sdk/client/stdio.js");
  const scratch = mkdtempSync(join(tmpdir(), "jev-doctor-"));
  const logs = { TYPESAFE_SPEND_LOG: join(scratch, "spend.jsonl"), LAYA_DECISION_LOG: join(scratch, "laya.jsonl") };

  // One start per distinct registration; one paid Jev call and one inference in total.
  const distinct = new Map();
  for (const r of registrations) distinct.set(JSON.stringify([r.name, r.command, r.args, r.env]), r);
  // launchd's default PATH, which is what an app opened from the Dock sees.
  const guiEnv = { HOME, USER: process.env.USER ?? "", LOGNAME: process.env.LOGNAME ?? "", SHELL: process.env.SHELL ?? "/bin/zsh", TMPDIR: tmpdir(), PATH: "/usr/bin:/bin:/usr/sbin:/sbin" };
  for (const r of distinct.values()) {
    const label = `live ${r.name} as registered by ${registrations.filter((x) => JSON.stringify([x.name, x.command, x.args, x.env]) === JSON.stringify([r.name, r.command, r.args, r.env])).map((x) => x.client).join("+")}`;
    const client = new Client({ name: "jev-doctor", version: "1" });
    const transport = new StdioClientTransport({ command: r.command, args: r.args, env: { ...guiEnv, ...r.env, ...logs }, stderr: "ignore" });
    try {
      await client.connect(transport);
      const tools = (await client.listTools()).tools.map((t) => t.name);
      report(sameList(tools, r.name === "jev" ? JEV_TOOLS : LAYA_TOOLS), `${label}: tools/list`, tools.join(","));
      if (r.name === "jev") {
        const models = await call(client, "jev_models", {});
        report(Array.isArray(models?.models) || Array.isArray(models?.models?.data), `${label}: jev_models answers`);
        {
          const res = await call(client, "jev_noul", { state: "The build has been red since Monday and the release is tomorrow.", instructions: "Does this message express urgency?", purpose: "doctor" });
          report(typeof res?.answers?.answer?.noul === "number" && Boolean(res?.model) && Boolean(res?.usage), `${label}: jev_noul judgment`, `${res?.model} noul=${res?.answers?.answer?.noul}`);
          const row = readFileSync(logs.TYPESAFE_SPEND_LOG, "utf8").trim().split("\n").map((l) => JSON.parse(l)).pop();
          report(row?.schema === 2 && row?.purpose === "doctor" && row?.tool === "jev_noul" && typeof row?.latency_ms === "number", `${label}: spend log schema 2 row`, `latency ${row?.latency_ms} ms`);
          const bad = await client.callTool({ name: "jev_noul", arguments: { state: "x", instructions: "y", purpse: "typo" } });
          report(bad.isError === true && /Unknown argument/.test(bad.content?.[0]?.text ?? ""), `${label}: misspelled argument refused`);
        }
      } else {
        const status = await call(client, "laya_status", {});
        report(status?.profiles?.[registry.defaultProfile]?.enabled === true && status?.local?.available === true,
          `${label}: laya_status lists the default profile and a configured env worker`, status?.local?.reason ?? "ok");
        {
          const tag = await call(client, "laya_bookmark_topic", { state: { title: "Zustand vs Redux", description: "Choosing a React state store." } });
          report(tag?.provider === "laya" && tag?.checkpoint === profile.checkpoint && typeof tag?.answers?.topic?.choice === "string", `${label}: laya_bookmark_topic inference`, `${tag?.answers?.topic?.choice} accepted=${tag?.accepted}`);
          const generic = await call(client, "laya_ask", { state: "The build has been red since Monday and the release is tomorrow.", questions: { urgent: { type: "noul", instructions: "Does this message express urgency?" } } });
          report(generic?.provider === "laya" && generic?.qualification === "UNQUALIFIED" && typeof generic?.answers?.urgent?.noul === "number", `${label}: generic laya_ask inference`, `noul=${generic?.answers?.urgent?.noul}`);
          const after = await call(client, "laya_status", {});
          report(!after?.local?.lastError && after?.counters?.errors === 0, `${label}: worker healthy after inference`, after?.local?.lastError ?? `errors=${after?.counters?.errors}`);
        }
      }
    } catch (err) {
      report(false, `${label}: starts and answers`, String(err?.message ?? err).slice(0, 200));
    } finally {
      await client.close().catch(() => {});
    }
  }
}

async function call(client, name, argumentsObject) {
  // A cold Laya model load can exceed the SDK's 60 s default.
  const res = await client.callTool({ name, arguments: argumentsObject }, undefined, { timeout: 180000 });
  const text = res.content?.[0]?.text ?? "";
  if (res.isError) throw new Error(`${name}: ${text.slice(0, 200)}`);
  return JSON.parse(text);
}
