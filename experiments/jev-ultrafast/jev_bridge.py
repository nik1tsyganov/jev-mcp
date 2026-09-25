"""Persistent, logged Node client for the isolated browser trial."""
import atexit
import json
import os
from pathlib import Path
import subprocess

_child = None


def close():
    global _child
    if _child is not None:
        _child.stdin.close()
        try:
            _child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _child.terminate()
            _child.wait(timeout=5)
        _child = None


atexit.register(close)


def decide(body):
    global _child
    if _child is None:
        env = os.environ.copy()
        # browser_trial's placeholder is solely for upstream's env lookup.
        if env.get('TYPESAFE_API_KEY') == 'unused-injected-decider':
            env.pop('TYPESAFE_API_KEY')
        _child = subprocess.Popen(
            ['node', str(Path(__file__).with_name('logged-client.mjs'))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, env=env, bufsize=1,
        )
    _child.stdin.write(json.dumps(body) + '\n')
    _child.stdin.flush()
    line = _child.stdout.readline()
    if not line:
        raise RuntimeError('Logged Jev bridge exited without a response')
    response = json.loads(line)
    if 'error' in response:
        raise RuntimeError(response['error'])
    return response['result']
