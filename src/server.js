#!/usr/bin/env node
import { readFileSync, realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

import { DEFAULT_MODEL, listModels, systemOne } from "./client.js";
import { browserActionTool, createBrowserDecision } from "./browser-decision.js";
import { choice, noul, score, validateQuestions } from "./questions.js";

// Every call spends a real balance, so a runaway agent is capped here rather than at the API.
const MAX_QUESTIONS_PER_CALL = 32;
const MAX_STATE_CHARS = 200_000;

const here = dirname(fileURLToPath(import.meta.url));
const { version } = JSON.parse(readFileSync(join(here, "..", "package.json"), "utf8"));

const STATE_SCHEMA = {
  description:
    "The situation to judge: a string, or an object with named fields you can reference from instructions with backticked paths such as `ticket.messages[0].text`.",
  type: ["string", "object", "array"],
};

const QUESTIONS_SCHEMA = {
  type: "object",
  description:
    "Map of your own ids to question objects. Each has type (noul|choice|score), instructions, and criteria as required by the type. Ids are for your code and are not sent to the model.",
  additionalProperties: {
    type: "object",
    properties: {
      type: { type: "string", enum: ["noul", "choice", "score"] },
      instructions: { type: "string" },
      criteria: {
        description:
          "noul: optional object with keys true/false. choice: required object of option name to description. score: required array of at least two ordered level labels.",
      },
    },
    required: ["type", "instructions"],
  },
};

const MODEL_SCHEMA = {
  type: "string",
  description: `Jev model id. Defaults to ${DEFAULT_MODEL}.`,
};

export const TOOLS = [
  {
    name: "jev_ask",
    description:
      "Ask several typed questions in one TypeSafe Jev request. Batch questions that read the same state. Returns answers, the resolved model and token usage.",
    inputSchema: {
      type: "object",
      properties: {
        state: STATE_SCHEMA,
        questions: QUESTIONS_SCHEMA,
        model: MODEL_SCHEMA,
      },
      required: ["state", "questions"],
    },
  },
  {
    name: "jev_noul",
    description:
      "Ask TypeSafe Jev for one yes/no judgment, returned as a probability between 0 and 1. Use when code will threshold the number. There is no confidence field on a noul answer: the probability is the answer. Use jev_ask to batch several questions.",
    inputSchema: {
      type: "object",
      properties: {
        state: STATE_SCHEMA,
        instructions: { type: "string", description: "The yes/no question, phrased as one question." },
        criteria: {
          type: "object",
          description: "Optional. Only the keys `true` and `false`, each describing that side.",
          properties: { true: { type: "string" }, false: { type: "string" } },
          additionalProperties: false,
        },
        model: MODEL_SCHEMA,
      },
      required: ["state", "instructions"],
    },
  },
  {
    name: "jev_choice",
    description:
      "Ask TypeSafe Jev to choose one of several named options. Returns the chosen option, a probability per option and a confidence. Use jev_ask to batch several questions.",
    inputSchema: {
      type: "object",
      properties: {
        state: STATE_SCHEMA,
        instructions: { type: "string" },
        criteria: {
          type: "object",
          description: "Required. Each option name mapped to a description (or null).",
          minProperties: 1,
          additionalProperties: { type: ["string", "null"] },
        },
        model: MODEL_SCHEMA,
      },
      required: ["state", "instructions", "criteria"],
    },
  },
  {
    name: "jev_score",
    description:
      "Ask TypeSafe Jev to grade a state on an ordered scale. Returns a probability-weighted score that may land between levels, the legend, a probability per level and a confidence. Use jev_ask to batch several questions.",
    inputSchema: {
      type: "object",
      properties: {
        state: STATE_SCHEMA,
        instructions: { type: "string" },
        criteria: {
          type: "array",
          description: "Required. At least two level labels, in order from lowest to highest.",
          items: { type: "string" },
          minItems: 2,
        },
        model: MODEL_SCHEMA,
      },
      required: ["state", "instructions", "criteria"],
    },
  },
  {
    name: "jev_models",
    description: "List the TypeSafe Jev models the account can use. Costs no judgment tokens.",
    inputSchema: { type: "object", properties: {} },
  },
  browserActionTool,
];

function guard(state, questions) {
  if (state === undefined || state === null || (typeof state !== "string" && typeof state !== "object")) {
    throw new Error("The state is required and must be a string, object or array.");
  }
  const count = Object.keys(questions).length;
  if (count > MAX_QUESTIONS_PER_CALL) {
    throw new Error(
      `${count} questions in one call exceeds the ${MAX_QUESTIONS_PER_CALL} cap. Split the pass, or drop questions that do not change an action.`
    );
  }
  const size = typeof state === "string" ? state.length : JSON.stringify(state).length;
  if (size > MAX_STATE_CHARS) {
    throw new Error(`State is ${size} characters, over the ${MAX_STATE_CHARS} cap. Send only the fields the questions read.`);
  }
}

export function createToolRunner({ client = { systemOne, listModels } } = {}) {

  async function ask({ state, questions, model }) {
    const validated = validateQuestions(questions);
    guard(state, validated);
    return client.systemOne({ state, questions: validated, model });
  }

  const browserDecision = createBrowserDecision({ ask });

  async function runTool(name, args = {}) {
    switch (name) {
      case "jev_ask":
        return ask(args);
      case "jev_noul":
        return ask({ ...args, questions: { answer: noul(args.instructions, args.criteria) } });
      case "jev_choice":
        return ask({ ...args, questions: { answer: choice(args.instructions, args.criteria) } });
      case "jev_score":
        return ask({ ...args, questions: { answer: score(args.instructions, args.criteria) } });
      case "jev_models":
        return client.listModels();
      case "decision_browser_action":
        return browserDecision(args);
      default:
        throw new Error(`Unknown tool \`${name}\`.`);
    }
  }

  return { runTool };
}

const runner = createToolRunner();

const server = new Server({ name: "jev", version }, { capabilities: { tools: {} } });

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  try {
    const result = await runner.runTool(request.params.name, request.params.arguments ?? {});
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  } catch (err) {
    return { content: [{ type: "text", text: err.message }], isError: true };
  }
});

// Only a direct `node src/server.js` run opens the stdio transport; importing
// this module (tests) must not take over stdin.
function isMainModule() {
  if (!process.argv[1]) return false;
  try {
    return realpathSync(process.argv[1]) === fileURLToPath(import.meta.url);
  } catch {
    return false;
  }
}

if (isMainModule()) {
  await server.connect(new StdioServerTransport());
}
