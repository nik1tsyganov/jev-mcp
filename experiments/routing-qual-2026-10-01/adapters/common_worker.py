"""Worker protocol, request validation, and local checkpoint identity."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import sys
import time

QIDS = {'task_class', 'effort', 'security_sensitive', 'injection', 'ambiguous'}


class Rejected(Exception):
    def __init__(self, code, raw, input_tokens=0):
        super().__init__(str(raw))
        self.code, self.raw, self.input_tokens = code, raw, input_tokens


def serialize(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def questions(request):
    supplied = request['questions']
    rows = list(supplied.values()) if isinstance(supplied, dict) else supplied
    if not isinstance(rows, list) or len(rows) != len(QIDS):
        raise Rejected('malformed', {'message': 'exactly five questions required'})
    mapped = {}
    for index, row in enumerate(rows):
        qid = row.get('id', list(supplied)[index] if isinstance(supplied, dict) else None)
        criteria = row.get('criteria', row.get('labels'))
        if isinstance(criteria, list):
            pairs = [(v.get('label', v.get('id')), v.get('criteria', v.get('criterion')))
                     for v in criteria if isinstance(v, dict)]
            if len(pairs) != len(criteria) or len(dict(pairs)) != len(pairs):
                raise Rejected('malformed', {'message': 'labels must include unique names and criteria'})
            criteria = dict(pairs)
        if (qid in mapped or not isinstance(criteria, dict) or not criteria
                or not all(isinstance(k, str) and isinstance(v, str) for k, v in criteria.items())
                or not isinstance(row.get('instructions'), str)):
            raise Rejected('malformed', {'message': 'invalid question or label criteria'})
        mapped[qid] = {'type': 'choice', 'instructions': row['instructions'], 'criteria': criteria}
    if set(mapped) != QIDS:
        raise Rejected('malformed', {'message': 'question ids do not match routing-q-v1'})
    if not isinstance(request.get('state'), dict):
        raise Rejected('malformed', {'message': 'state must be an object'})
    return mapped


def normalize(answers, qs):
    if not isinstance(answers, dict) or set(answers) != set(qs):
        raise Rejected('malformed', {'message': 'model omitted a question', 'answers': answers})
    out = {}
    for qid, definition in qs.items():
        answer = answers[qid]
        probs = answer.get('probs', answer.get('probabilities')) if isinstance(answer, dict) else None
        if (not isinstance(probs, dict) or set(probs) != set(definition['criteria'])
                or not all(isinstance(p, (int, float)) and not isinstance(p, bool)
                           and math.isfinite(p) and 0 <= p <= 1 for p in probs.values())
                or abs(sum(probs.values()) - 1) > 1e-3):
            raise Rejected('malformed', {'message': 'invalid full distribution', 'qid': qid, 'answer': answer})
        out[qid] = {'probs': {label: float(p) for label, p in probs.items()}}
    return out


def limit(count, maximum, source, **extra):
    if count > maximum:
        raise Rejected('input_over_limit', {'input_tokens': count, 'limit': maximum,
                                            'limit_source': source, **extra}, count)


def versions(config):
    result = {'python': platform.python_version(), 'model_directory': config.get('model_dir'),
              'resolved_snapshot_revision': None}
    for package in ('mlx', 'mlx-lm', 'laya-mlx', 'torch', 'transformers', 'decider-ai', 'tokenizers'):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    return result


def model_directory(config):
    path = Path(config['model_dir']).expanduser().resolve()
    if not path.is_dir():
        raise Rejected('transport', {'message': 'local model directory missing', 'model_dir': str(path)})
    revision = config['revision']
    if config['backend'] == 'laya':
        if path.name != revision or path.parent.name != 'snapshots':
            raise Rejected('transport', {'message': 'Laya must use the pinned local snapshot directory'})
        for name in ('model.safetensors', 'rl_agent_config.json', 'encoder/config.json', 'tokenizer/tokenizer.json'):
            if not (path / name).is_file():
                raise Rejected('transport', {'message': 'incomplete Laya snapshot', 'missing': name})
        return path
    # The pilot uses flat directories. Its download manifest binds their bytes to the revision.
    manifest = Path(config.get('download_plan', path.parent.parent / 'download-plan.json'))
    plan = json.loads(manifest.read_text())
    entries = [entry for entry in plan['files'] if entry.get('kind') == 'model'
               and Path(entry['path']).parent.name == path.name]
    if not entries or not any(Path(e['path']).name == 'model.safetensors' for e in entries):
        raise Rejected('transport', {'message': 'no checkpoint identity in download plan'})
    for entry in entries:
        if f"/{config['model']}/resolve/{revision}/" not in entry['url']:
            raise Rejected('transport', {'message': 'download plan revision mismatch'})
        file = path / Path(entry['path']).name
        if file.stat().st_size != entry['size']:
            raise Rejected('transport', {'message': 'checkpoint size mismatch', 'file': file.name})
        sha256 = entry.get('sha256')
        digest = hashlib.sha256() if sha256 else hashlib.sha1()
        if not sha256:
            digest.update(f'blob {file.stat().st_size}\0'.encode())
        with file.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != (sha256 or entry['git_blob_sha1']):
            raise Rejected('transport', {'message': 'checkpoint digest mismatch', 'file': file.name})
    return path


def main(runtime_type):
    protocol = os.fdopen(os.dup(1), 'w', encoding='utf-8')
    os.dup2(2, 1)
    # Adapter decider.py must not shadow the installed decider package.
    here = Path(__file__).resolve().parent
    sys.path[:] = [p for p in sys.path if Path(p or os.getcwd()).resolve() != here]
    config = json.loads(sys.argv[1])
    info = {'backend': config['backend'], 'model': config['model'], 'revision': config['revision'],
            'local': True, 'versions': versions(config)}

    def emit(value):
        protocol.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
        protocol.flush()

    try:
        runtime = runtime_type(config)
        info['versions'].update(model_directory=str(runtime.model_dir) if runtime.model_dir else None,
                                resolved_snapshot_revision=config['revision'])
        info.update(runtime.info)
        emit({'type': 'ready', 'info': info})
    except Exception as exc:
        emit({'type': 'fatal', 'error': exc.code if isinstance(exc, Rejected) else 'transport',
              'raw': exc.raw if isinstance(exc, Rejected) else {'message': str(exc)}, 'info': info})
        return
    for line in sys.stdin:
        started = time.perf_counter()
        request = None
        result = {'type': 'result', 'request_id': None, 'ok': False, 'answers': None, 'error': None,
                  'model': config['model'], 'revision': config['revision'],
                  'usage': {'input_tokens': 0, 'output_tokens': 0}, 'cost_usd': 0.0,
                  'network_attempts_blocked': 0}
        try:
            request = json.loads(line)
            result['request_id'] = request['request_id']
            answers, raw, usage = runtime.classify(request)
            result.update(ok=True, answers=answers, raw=raw, usage=usage)
        except Rejected as exc:
            result.update(error=exc.code, raw=exc.raw)
            result['usage']['input_tokens'] = exc.input_tokens
            if exc.code == 'network_blocked':
                result['network_attempts_blocked'] = 1
        except (ValueError, KeyError, TypeError) as exc:
            result.update(error='malformed', raw={'message': str(exc)})
        except Exception as exc:
            result.update(error='transport', raw={'message': str(exc)})
        result['latency_ms'] = (time.perf_counter() - started) * 1000
        emit(result)
