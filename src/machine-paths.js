/**
 * Optional per-machine path registry: a flat key -> absolute path map in
 * ~/.config/machine-paths/paths.json. A machine without it (or without the key)
 * gets the home-relative fallback, so a fresh clone keeps working.
 */

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

function registry() {
  try {
    return JSON.parse(readFileSync(join(homedir(), ".config", "machine-paths", "paths.json"), "utf8"));
  } catch {
    return null;
  }
}

/** Absolute path for `key`, else `fallback` joined to the home directory. */
export function pathOf(key, fallback) {
  const value = registry()?.[key];
  return typeof value === "string" && value ? value : join(homedir(), fallback);
}
