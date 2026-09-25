import test from 'node:test';
import assert from 'node:assert/strict';

test('experiment uses one transport attempt on retryable HTTP failure', async () => {
  process.env.DROPPY_CREDENTIAL_SCOPE = 'app';
  process.env.DROPPY_JEV_API_KEY = 'experiment-test-key';
  process.env.DROPPY_DECISION_MODE = 'auto';
  let attempts = 0;
  globalThis.fetch = async () => {
    attempts++;
    return new Response(JSON.stringify({error: 'fixture unavailable'}),
      {status: 503, headers: {'content-type': 'application/json'}});
  };
  const {systemOne} = await import('./logged-client.mjs');
  await assert.rejects(systemOne({state: 'fixture', questions: {
    q: {type: 'choice', instructions: 'Pick one', criteria: {a: 'A', b: 'B'}}
  }}));
  assert.equal(attempts, 1);
});
