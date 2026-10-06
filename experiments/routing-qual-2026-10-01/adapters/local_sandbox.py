"""Persistent JSON workers with an OS-enforced network boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import threading
import time

SANDBOX_PROFILE = '(version 1)(allow default)(deny network*)'


class WorkerFailure(Exception):
    def __init__(self, code, raw):
        super().__init__(str(raw))
        self.code, self.raw = code, raw


class Worker:
    def __init__(self, argv, env_extra, cwd):
        env = {key: value for key, value in os.environ.items()
               if key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT')}
        env.update({str(k): str(v) for k, v in (env_extra or {}).items()})
        for key in list(env):
            if 'proxy' in key.lower():
                del env[key]
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1',
                   HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                   PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1',
                   PYTORCH_ENABLE_MPS_FALLBACK='0', TOKENIZERS_PARALLELISM='false')
        self.process = subprocess.Popen(
            ['/usr/bin/sandbox-exec', '-p', SANDBOX_PROFILE, *map(str, argv)],
            cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0)
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)
        self.buffer = b''
        self.stderr = bytearray()
        self.peak_rss_bytes = 0
        self.rss_samples = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._rss_thread = threading.Thread(target=self._sample_rss, daemon=True)
        self._stderr_thread.start()
        self._rss_thread.start()

    @property
    def pid(self):
        return self.process.pid

    def _drain_stderr(self):
        while True:
            chunk = self.process.stderr.read(65536)
            if not chunk:
                return
            self.stderr.extend(chunk)

    def _sample_rss(self):
        while not self._stop.is_set():
            try:
                output = subprocess.check_output(
                    ['/bin/ps', '-o', 'rss=', '-p', str(self.pid)],
                    text=True, stderr=subprocess.DEVNULL, timeout=1)
                self.peak_rss_bytes = max(self.peak_rss_bytes, int(output.strip()) * 1024)
                self.rss_samples += 1
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            if self.process.poll() is not None:
                return
            self._stop.wait(0.2)

    def _remaining(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WorkerFailure('timeout', {'message': 'worker deadline exceeded'})
        return remaining

    def _read(self, deadline):
        while b'\n' not in self.buffer:
            ready, _, _ = select.select([self.process.stdout], [], [], self._remaining(deadline))
            if not ready:
                raise WorkerFailure('timeout', {'message': 'worker response timed out'})
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise WorkerFailure('transport', {'message': 'worker exited',
                                                  'partial_stdout': self.buffer.decode('utf-8', 'replace')})
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b'\n', 1)
        try:
            value = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise WorkerFailure('malformed', {'stdout': line.decode('utf-8', 'replace')}) from exc
        if not isinstance(value, dict):
            raise WorkerFailure('malformed', {'stdout': value})
        return value

    def receive(self, timeout):
        with self._lock:
            try:
                return self._read(time.monotonic() + timeout)
            except WorkerFailure:
                self.close()
                raise

    def call(self, request, timeout=30):
        with self._lock:
            deadline = time.monotonic() + timeout
            try:
                data = memoryview((json.dumps(request, ensure_ascii=False, allow_nan=False) + '\n').encode())
                while data:
                    _, ready, _ = select.select([], [self.process.stdin], [], self._remaining(deadline))
                    if not ready:
                        raise WorkerFailure('timeout', {'message': 'worker write timed out'})
                    data = data[os.write(self.process.stdin.fileno(), data):]
                return self._read(deadline)
            except WorkerFailure:
                self.close()
                raise
            except (OSError, ValueError) as exc:
                self.close()
                raise WorkerFailure('transport', {'message': str(exc)}) from exc

    def close(self):
        self._stop.set()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self._stderr_thread.join(timeout=2)
        self._rss_thread.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream and not stream.closed:
                stream.close()


def start_worker(argv, env_extra=None, cwd=None):
    return Worker(argv, env_extra, cwd)


class LocalAdapter:
    def __init__(self, backend, model, revision, worker_file, config):
        self.backend, self.model, self.revision = backend, model, revision
        self.config = dict(config)
        self.worker_file = Path(__file__).with_name(worker_file)
        self.worker = None
        self.failure = None
        self.closed = False
        self._info = dict(backend=backend, model=model, revision=revision, local=True,
                          versions={}, sandbox_profile=SANDBOX_PROFILE)

    def _start(self):
        if self.closed:
            raise WorkerFailure('transport', {'message': 'adapter is closed'})
        if self.failure:
            raise self.failure
        if self.worker:
            return
        try:
            self.worker = start_worker(
                [self.config['python'], '-u', str(self.worker_file), json.dumps(self.config)],
                self.config.get('env_extra'), self.config.get('cwd', str(self.worker_file.parent)))
            ready = self.worker.receive(float(self.config.get('startup_timeout_ms', 180000)) / 1000)
            self._info.update(ready.get('info', {}))
            if ready.get('type') != 'ready':
                raise WorkerFailure(ready.get('error', 'transport'), ready)
        except (OSError, WorkerFailure) as exc:
            self.failure = exc if isinstance(exc, WorkerFailure) else WorkerFailure('transport', {'message': str(exc)})
            if self.worker:
                self.worker.close()
            raise self.failure

    def info(self):
        try:
            self._start()
        except WorkerFailure as exc:
            self._info['startup_error'] = {'error': exc.code, 'raw': exc.raw}
        return {**self._info, 'peak_rss_bytes': self.worker.peak_rss_bytes if self.worker else 0,
                'rss_samples': self.worker.rss_samples if self.worker else 0}

    def classify(self, request):
        started = time.perf_counter()
        result = dict(ok=False, answers=None, error=None, model=self.model, revision=self.revision,
                      usage={'input_tokens': 0, 'output_tokens': 0}, latency_ms=0,
                      cost_usd=0.0, raw=None, network_attempts_blocked=0)
        try:
            self._start()
            raw = self.worker.call(request, float(self.config.get('timeout_ms', 30000)) / 1000)
            result['raw'] = raw
            if raw.get('request_id') != request.get('request_id') or raw.get('type') != 'result':
                raise WorkerFailure('malformed', raw)
            for key in ('ok', 'answers', 'error', 'usage', 'network_attempts_blocked'):
                result[key] = raw[key]
            if raw.get('raw') == 'NETWORK-REACHED':
                result['raw'] = 'NETWORK-REACHED'
        except WorkerFailure as exc:
            result.update(error=exc.code, raw=exc.raw)
            self.failure = exc
        except (KeyError, TypeError, ValueError) as exc:
            result.update(ok=False, answers=None, error='malformed',
                          raw={'worker_output': result['raw'], 'message': str(exc)})
        if self.worker:
            result['peak_rss_bytes'] = self.worker.peak_rss_bytes
            if isinstance(result['raw'], dict):
                result['raw']['worker_stderr'] = self.worker.stderr.decode('utf-8', 'replace')
        result['latency_ms'] = (time.perf_counter() - started) * 1000
        return result

    def close(self):
        self.closed = True
        if self.worker:
            self.worker.close()
