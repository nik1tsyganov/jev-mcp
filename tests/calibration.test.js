import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const packsDir = join(here, "..", "packs");
const packFileNames = readdirSync(packsDir)
  .filter((file) => file.endsWith(".json"))
  .sort();

function getPackCalibratedModel(pack) {
  if (typeof pack.calibrated_on_model === "string" && pack.calibrated_on_model.trim()) {
    return pack.calibrated_on_model.trim();
  }
  for (const t of Object.values(pack.thresholds || {})) {
    if (typeof t.calibrated_on_model === "string" && t.calibrated_on_model.trim()) {
      return t.calibrated_on_model.trim();
    }
  }
  return undefined;
}

function hasNumericGate(pack) {
  return Object.values(pack.thresholds || {}).some(
    (t) => typeof t.gate === "number"
  );
}

function getPackValidation(pack) {
  if (typeof pack.validation === "string" && pack.validation.trim()) {
    return pack.validation.trim();
  }
  for (const t of Object.values(pack.thresholds || {})) {
    if (typeof t.validation === "string" && t.validation.trim()) {
      return t.validation.trim();
    }
  }
  return undefined;
}

test("pack files exist in packs directory", () => {
  assert.ok(packFileNames.length > 0, "Expected at least one pack JSON file.");
});

test("every pack carries a non-empty calibrated_on_model", () => {
  for (const file of packFileNames) {
    const pack = JSON.parse(readFileSync(join(packsDir, file), "utf8"));
    const model = getPackCalibratedModel(pack);
    assert.ok(
      typeof model === "string" && model.length > 0,
      `${file}: missing or empty calibrated_on_model`
    );
  }
});

test("every pack with a numeric gate also carries a validation string", () => {
  for (const file of packFileNames) {
    const pack = JSON.parse(readFileSync(join(packsDir, file), "utf8"));
    if (hasNumericGate(pack)) {
      const validation = getPackValidation(pack);
      assert.ok(
        typeof validation === "string" && validation.length > 0,
        `${file}: pack has a numeric gate but is missing a validation string`
      );
    }
  }
});

test("the set of calibrated_on_model values across all packs has exactly one distinct member", () => {
  const models = new Set();
  for (const file of packFileNames) {
    const pack = JSON.parse(readFileSync(join(packsDir, file), "utf8"));
    const model = getPackCalibratedModel(pack);
    assert.ok(model, `${file}: missing calibrated_on_model`);
    models.add(model);
  }
  assert.strictEqual(
    models.size,
    1,
    `Expected exactly 1 distinct calibrated_on_model across all packs, found ${models.size}: ${Array.from(models).join(", ")}`
  );
});
