/** Local shape checks, so a malformed question fails before it costs a request. */

function assertInstructions(instructions) {
  if (typeof instructions !== "string" || instructions.trim() === "") {
    throw new Error("`instructions` must be a non-empty string.");
  }
}

function isPlainObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function noul(instructions, criteria) {
  assertInstructions(instructions);
  if (criteria !== undefined) {
    if (!isPlainObject(criteria)) {
      throw new Error("noul `criteria` must be an object with the keys `true` and `false`.");
    }
    const extra = Object.keys(criteria).filter((k) => k !== "true" && k !== "false");
    if (extra.length) {
      throw new Error(`noul \`criteria\` allows only \`true\` and \`false\`; got: ${extra.join(", ")}.`);
    }
  }
  return criteria === undefined
    ? { type: "noul", instructions }
    : { type: "noul", instructions, criteria };
}

export function choice(instructions, criteria) {
  assertInstructions(instructions);
  if (!isPlainObject(criteria) || Object.keys(criteria).length === 0) {
    throw new Error(
      "choice `criteria` must be a non-empty object mapping each option name to a description or null."
    );
  }
  return { type: "choice", instructions, criteria };
}

export function score(instructions, criteria) {
  assertInstructions(instructions);
  if (!Array.isArray(criteria) || criteria.length < 2) {
    throw new Error("score `criteria` must be an array of at least two ordered level labels.");
  }
  return { type: "score", instructions, criteria };
}

const BUILDERS = { noul, choice, score };

/** Validates a whole questions map and returns a normalised copy. */
export function validateQuestions(questions) {
  if (!isPlainObject(questions) || Object.keys(questions).length === 0) {
    throw new Error("`questions` must be a non-empty object keyed by your own question ids.");
  }
  const out = {};
  for (const [id, q] of Object.entries(questions)) {
    if (!isPlainObject(q)) throw new Error(`Question \`${id}\` must be an object.`);
    const build = BUILDERS[q.type];
    if (!build) {
      throw new Error(`Question \`${id}\` has type \`${q.type}\`; expected noul, choice or score.`);
    }
    try {
      out[id] = build(q.instructions, q.criteria);
    } catch (err) {
      throw new Error(`Question \`${id}\`: ${err.message}`);
    }
  }
  return out;
}
