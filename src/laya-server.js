#!/usr/bin/env node
import { readFileSync, realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

import { BOOKMARK_PROFILE_IDS, loadBookmarkQuestions } from "./bookmark-questions.js";
import { createLayaService } from "./laya-service.js";
import { sanitizeLayaError } from "./laya-client.js";

const { version } = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const LOCAL_NOTE = "Runs a local offline model and never calls Jev. accepted:false means the caller should decide whether to ask Jev with jev_ask.";
const STATE_SCHEMA = { type: ["string", "object", "array"], description: "The situation to judge." };
const TOOLS = [
  {
    name: "laya_ask",
    description: `Ask typed questions locally. Unmatched questions return qualification UNQUALIFIED. ${LOCAL_NOTE}`,
    inputSchema: {
      type: "object",
      properties: {
        state: STATE_SCHEMA,
        questions: {
          type: "object",
          description: "Map of question ids to typed questions.",
          additionalProperties: {
            type: "object",
            properties: {
              type: { type: "string", enum: ["noul", "choice", "score"] },
              instructions: { type: "string" },
              criteria: { description: "noul: optional true/false object; choice: option descriptions; score: ordered level labels." },
            },
            required: ["type", "instructions"],
          },
        },
        profile: { type: "string", description: "Registered profile id. Must match the questions exactly." },
      },
      required: ["state", "questions"],
      additionalProperties: false,
    },
  },
  {
    name: "laya_bookmark_topic",
    description: `Classify a bookmark with the frozen topic questions. Defaults to the v2 profile. ${LOCAL_NOTE}`,
    inputSchema: {
      type: "object",
      properties: {
        state: STATE_SCHEMA,
        profile: { type: "string", enum: BOOKMARK_PROFILE_IDS, default: "technical-bookmark-topic-v2" },
      },
      required: ["state"],
      additionalProperties: false,
    },
  },
  {
    name: "laya_status",
    description: `Read local worker, profile and request status without inference. ${LOCAL_NOTE}`,
    inputSchema: { type: "object", properties: {}, additionalProperties: false },
  },
];

export function createLayaToolRunner(service) {
  async function runTool(name, args = {}) {
    const tool = TOOLS.find((candidate) => candidate.name === name);
    if (!tool) throw new Error(`Unknown tool \`${name}\`.`);
    if (!args || typeof args !== "object" || Array.isArray(args)) throw new Error("Tool arguments must be an object.");
    if (Object.keys(args).some((key) => !Object.hasOwn(tool.inputSchema.properties, key))) {
      throw new Error("Unsupported tool argument.");
    }
    switch (name) {
      case "laya_ask":
        return service.ask({ state: args.state, questions: args.questions, profile: args.profile });
      case "laya_bookmark_topic": {
        const profile = args.profile === undefined ? "technical-bookmark-topic-v2" : args.profile;
        return service.ask({ state: args.state, questions: loadBookmarkQuestions(profile), profile });
      }
      case "laya_status":
        return service.status();
    }
  }
  return { runTool, tools: TOOLS };
}

function isMainModule() {
  if (!process.argv[1]) return false;
  try {
    return realpathSync(process.argv[1]) === fileURLToPath(import.meta.url);
  } catch {
    return false;
  }
}

if (isMainModule()) {
  const service = createLayaService();
  const runner = createLayaToolRunner(service);
  const server = new Server({ name: "laya", version }, { capabilities: { tools: {} } });
  let closing;
  function shutdown() {
    closing ??= service.close().finally(() => server.close()).catch(() => {});
    return closing;
  }
  server.onclose = () => { void service.close().catch(() => {}); };
  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);
  process.stdin.once("end", shutdown);
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: runner.tools }));
  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    try {
      const result = await runner.runTool(request.params.name, request.params.arguments ?? {});
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    } catch (error) {
      return { content: [{ type: "text", text: sanitizeLayaError(error?.message ?? String(error)) }], isError: true };
    }
  });
  await server.connect(new StdioServerTransport());
}
