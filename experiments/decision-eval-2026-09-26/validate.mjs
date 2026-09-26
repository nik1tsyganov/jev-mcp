// Checks every case file: question shapes pass the server's validator and each expected value is one of the question's own options.
import { readdirSync, readFileSync } from "node:fs";
import { validateQuestions } from "../../src/questions.js";
for (const f of readdirSync(".").filter((f) => /^cases-.*\.jsonl$/.test(f))) {
  let n = 0; const bad = [];
  for (const l of readFileSync(f, "utf8").split("\n").filter(Boolean)) {
    n++; const c = JSON.parse(l);
    try {
      const q = validateQuestions(c.questions);
      for (const [id, x] of Object.entries(q)) {
        const e = c.expected[id];
        if (e === undefined) throw new Error("no expected for " + id);
        if (x.type === "choice" && !Object.hasOwn(x.criteria, e)) throw new Error("expected not a label: " + e);
        if (x.type === "noul" && typeof e !== "boolean") throw new Error("noul expected not boolean");
        if (x.type === "score" && !(Number.isInteger(e) && e >= 0 && e < x.criteria.length)) throw new Error("score expected out of range");
      }
    } catch (err) { bad.push(`${c.id}: ${err.message}`); }
  }
  console.log(f, n, "cases,", bad.length, "bad", bad.slice(0, 5));
}
