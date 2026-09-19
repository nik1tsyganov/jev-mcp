#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

import { DEFAULT_MODEL, listModels, systemOne } from "./client.js";
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

const TOOLS = [
  {
    name: "jev_ask",
    description:
      "Ask Jev several typed questions about one state in a single request. Prefer this tool: one request answers many questions, and batching is what keeps a decision pass cheap. Returns the answers, the resolved model and the token usage.",
    inputSchema: {
      type: "object",
      properties: {
        state: STATE_SCHEMA,
        questions: {
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
        },
        model: { type: "string", description: `Model id. Defaults to ${DEFAULT_MODEL}.` },
      },
      required: ["state", "questions"],
    },
  },
  {
    name: "jev_noul",
    description:
      "One yes/no judgment about a state, returned as a probability between 0 and 1. Use when code will threshold the number. There is no confidence field on a noul answer: the probability is the answer.",
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
        model: { type: "string" },
      },
      required: ["state", "instructions"],
    },
  },
  {
    name: "jev_choice",
    description:
      "Route a state to one of several named options. Returns the chosen option, a probability per option and a confidence. Use for routing, classification and triage.",
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
        model: { type: "string" },
      },
      required: ["state", "instructions", "criteria"],
    },
  },
  {
    name: "jev_score",
    description:
      "Grade a state on an ordered scale. Returns a probability-weighted score that may land between levels, the legend, a probability per level and a confidence. Use for quality, severity and risk grading.",
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
        model: { type: "string" },
      },
      required: ["state", "instructions", "criteria"],
    },
  },
  {
    name: "jev_models",
    description: "List the models the TypeSafe account can use. Costs no judgment tokens.",
    inputSchema: { type: "object", properties: {} },
  },
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

async function ask({ state, questions, model }) {
  const validated = validateQuestions(questions);
  guard(state, validated);
  const result = await systemOne({ state, questions: validated, model });
  return { model: result.model, answers: result.answers, usage: result.usage };
}

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
      return listModels();
    default:
      throw new Error(`Unknown tool \`${name}\`.`);
  }
}

const server = new Server({ name: "jev", version }, { capabilities: { tools: {} } });

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  try {
    const result = await runTool(request.params.name, request.params.arguments ?? {});
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  } catch (err) {
    return { content: [{ type: "text", text: err.message }], isError: true };
  }
});

await server.connect(new StdioServerTransport());
