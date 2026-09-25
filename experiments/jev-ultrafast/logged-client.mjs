import { TypeSafeClient } from '@typesafe-ai/sdk';
import { systemOne as loggedSystemOne, redact } from '../../src/client.js';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
import { normalizeInstructions } from './replay.mjs';

// The production wrapper does not expose SDK request options. This process-only
// experiment adapter preserves its logging while disabling transport retries.
const original = TypeSafeClient.prototype.systemOne;
TypeSafeClient.prototype.systemOne = function(body, options = {}) {
  return original.call(this, body, {...options, retry: {maxRetries: 0}});
};
export const systemOne = loggedSystemOne;

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({input: process.stdin})) {
    try {
      const body = JSON.parse(line);
      const questions = normalizeInstructions(body.questions).questions;
      const result = await systemOne({...body, questions});
      process.stdout.write(JSON.stringify({result}) + '\n');
    } catch (error) {
      process.stdout.write(JSON.stringify({error: redact(error.message)}) + '\n');
    }
  }
}
