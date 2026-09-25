import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
// Fixed paths prevent callers from supplying their own question definition file.
const BOOKMARK_TOPIC_PROFILES = {
  "technical-bookmark-topic-v1": join(here, "..", "config", "technical-bookmark-topic-v1.json"),
  "technical-bookmark-topic-v2": join(here, "..", "config", "technical-bookmark-topic-v2.json"),
};
export const BOOKMARK_PROFILE_IDS = Object.freeze(Object.keys(BOOKMARK_TOPIC_PROFILES));

export function loadBookmarkQuestions(profileId = "technical-bookmark-topic-v2") {
  if (typeof profileId !== "string" || !Object.hasOwn(BOOKMARK_TOPIC_PROFILES, profileId)) {
    throw new Error(`Unknown bookmark topic profile \`${profileId}\`; expected ${BOOKMARK_PROFILE_IDS.join(" or ")}.`);
  }
  return JSON.parse(readFileSync(BOOKMARK_TOPIC_PROFILES[profileId], "utf8")).questions;
}
