"""Capture classifier runs, freeze inputs, and tune policy from stored dev answers.

Examples (run from this directory; output paths are caller-selected):
  python3.12 harness.py run --backend control_constant --split dev --repeats 3 \
      --rule owner-bands --out /tmp/routing-constant
  python3.12 harness.py tune --runs /tmp/routing-dev --gold cases/dev-gold.jsonl \
      --out /tmp/routing-thresholds/backend.json
  python3.12 harness.py freeze --thresholds /tmp/routing-thresholds
  python3.12 score.py score --runs /tmp/routing-constant --gold cases/dev-gold.jsonl \
      --out /tmp/routing-results

records.jsonl has one object per case/repeat: case_id, repeat (zero-based),
request_hash (canonical JSON SHA-256), raw_result, validated answers,
validation_errors, adapter_malformed, top_class, route, and timing in ms.
manifest.json records input hashes, adapter identity, rule thresholds, Git
identity, host snapshots, UTC timestamps, completion status, and run totals.
Threshold JSON contains act, effort_q, flag, a 36-row grid, and source hashes.
The grid ties break by higher act, then higher effort_q. Tuning pools runs
from one backend. Freeze also pins harness/scorer/control code. A second
freeze refuses to overwrite an existing commitment.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import adapters
import baselines
import controls
import policy
from questions import QUESTION_SET_VERSION, build_request, validate_answers

ROOT = Path(__file__).resolve().parent
GRID = (0.35, 0.4, 0.5, 0.6, 0.7, 0.8)
BASELINES = ('matrix', 'keep-current', 'manual')


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def write_json(path, value):
    Path(path).write_text(json.dumps(json_safe(value), indent=2, allow_nan=False) + '\n')


def read_jsonl(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def input_key(path, root=ROOT):
    return os.path.relpath(Path(path).resolve(), Path(root).resolve())


def command_output(argv, cwd=None):
    try:
        return subprocess.check_output(argv, cwd=cwd, text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def host_snapshot():
    loads = os.getloadavg()
    process_output = command_output(['ps', '-Ao', 'pid,pcpu,rss,comm', '-r'])
    processes = []
    for line in (process_output or '').splitlines()[1:]:
        fields = line.strip().split(None, 3)
        if len(fields) != 4:
            continue
        try:
            processes.append({'pid': int(fields[0]), 'pcpu': float(fields[1]),
                              'rss_kib': int(fields[2]), 'comm': fields[3]})
        except ValueError:
            continue
    pressure = command_output(['memory_pressure'])
    contended = loads[0] >= 2.0 or any(process['pid'] != os.getpid() and process['pcpu'] > 20 for process in processes)
    return {'uptime': command_output(['uptime']), 'load_averages': list(loads),
            'memory_pressure': pressure.splitlines()[-1] if pressure else None,
            'top_processes': processes[:5], 'load_label': 'contended' if contended else 'idle'}


def git_snapshot(root=ROOT):
    head = command_output(['git', 'rev-parse', 'HEAD'], root)
    dirty = None
    if head:
        worktree = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--'], cwd=root, capture_output=True).returncode
        untracked = command_output(['git', 'ls-files', '--others', '--exclude-standard'], root)
        dirty = bool(worktree or untracked)
    return {'head': head, 'dirty': dirty}


def frozen_inputs(root=ROOT):
    root = Path(root)
    return [root / name for name in ('catalog.json', 'questions.py', 'policy.py', 'baselines.py',
                                     'harness.py', 'score.py', 'controls.py', 'cases/heldout.jsonl')]


def verify_frozen(root=ROOT):
    root = Path(root)
    path = root / 'FROZEN.json'
    if not path.exists():
        raise ValueError('held-out runs require FROZEN.json')
    frozen = json.loads(path.read_text())
    hashes = frozen.get('hashes', {})
    required = {input_key(path, root) for path in frozen_inputs(root)}
    required.update(input_key(path, root) for path in (root / 'adapters').glob('*.py'))
    if not required <= hashes.keys():
        raise ValueError('freeze does not cover the current benchmark inputs')
    for name, expected in hashes.items():
        path = root / name
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f'frozen input changed: {name}')
    if (root / 'cases/heldout-gold.sha256').read_text() != frozen['heldout_gold_sha256']:
        raise ValueError('held-out gold commitment changed')
    return frozen


def freeze(thresholds, root=ROOT):
    root, thresholds = Path(root), Path(thresholds)
    if not thresholds.is_dir():
        raise ValueError('--thresholds must be a directory')
    paths = frozen_inputs(root) + sorted((root / 'adapters').glob('*.py'))
    threshold_paths = sorted(path for path in thresholds.rglob('*') if path.is_file())
    if not threshold_paths:
        raise ValueError('threshold directory contains no files')
    paths += threshold_paths
    result = {'frozen_at': utc_now(), 'hashes': {input_key(path, root): sha256(path) for path in paths},
              'threshold_files': [input_key(path, root) for path in threshold_paths],
              'heldout_gold_sha256': (root / 'cases/heldout-gold.sha256').read_text()}
    with (root / 'FROZEN.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    return result


def load_rule(name, thresholds=None):
    if name == 'owner-bands':
        return dict(policy.RULES[name])
    if thresholds is None:
        raise ValueError('dev-tuned requires --thresholds FILE')
    value = json.loads(Path(thresholds).read_text())
    if value.get('act') not in GRID or value.get('effort_q') not in GRID:
        raise ValueError('thresholds must be selected from the declared dev grid')
    return {'name': 'dev-tuned', 'act': value['act'], 'effort_q': value['effort_q'],
            'flag': min(0.6, value['act'])}


def failure_result(error, info, raw=None):
    return {'ok': False, 'answers': None, 'error': error, 'model': info.get('model'),
            'revision': info.get('revision'), 'usage': {}, 'latency_ms': 0,
            'cost_usd': None, 'raw': raw, 'network_attempts_blocked': 0}


def validate_result(result):
    required = {'ok', 'answers', 'error', 'model', 'revision', 'usage', 'latency_ms',
                'cost_usd', 'raw', 'network_attempts_blocked'}
    if not isinstance(result, dict) or not required <= result.keys():
        return None, ['adapter result is missing fields'], True
    if type(result['ok']) is not bool or not isinstance(result['usage'], dict):
        return None, ['adapter result has invalid field types'], True
    for field in ('latency_ms', 'network_attempts_blocked'):
        value = result[field]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return None, [f'adapter {field} must be a finite nonnegative number'], True
    cost = result['cost_usd']
    if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
        return None, ['adapter cost_usd is invalid'], True
    if (result['ok'] and result['error'] is not None) or (not result['ok'] and not isinstance(result['error'], str)):
        return None, ['adapter success and error fields disagree'], True
    for field, value in result['usage'].items():
        if field in {'input_tokens', 'output_tokens'} and value is not None and (type(value) is not int or value < 0):
            return None, [f'adapter usage {field} is invalid'], True
    if not result['ok']:
        malformed = result.get('error') in {'malformed', 'invalid_output', 'non_json'}
        return None, ['adapter reported malformed output'] if malformed else [], malformed
    answers, errors = validate_answers(result['answers'])
    return answers, errors, False


def run(args, root=ROOT):
    root = Path(root)
    if args.repeats < 1 or (args.limit is not None and args.limit < 1):
        raise ValueError('repeats and limit must be positive')
    frozen = verify_frozen(root) if args.split == 'heldout' else None
    gold_controls = ('control_oracle', 'control_anti')
    if args.control_gold and (args.split != 'dev' or args.backend not in gold_controls):
        raise ValueError('--control-gold is permitted only for control_oracle/control_anti on dev')
    if args.backend in gold_controls and (args.split != 'dev' or not args.control_gold):
        raise ValueError(f'{args.backend} requires --split dev --control-gold FILE')
    config = json.loads(args.config) if args.config else {}
    if not isinstance(config, dict):
        raise ValueError('--config must be a JSON object')
    if 'gold' in config:
        raise ValueError('gold may enter the harness only through --control-gold')
    if args.control_gold:
        config['gold'] = {row['id']: row for row in read_jsonl(args.control_gold)}
    rule = load_rule(args.rule, args.thresholds)
    if frozen and args.thresholds and input_key(args.thresholds, root) not in frozen['hashes']:
        raise ValueError('thresholds file was not frozen')
    case_path = root / 'cases' / f'{args.split}.jsonl'
    cases = read_jsonl(case_path)
    if args.limit is not None:
        cases = cases[:args.limit]
    if not cases:
        raise ValueError('case selection is empty')
    module = None
    if args.backend in BASELINES:
        module = baselines
    elif args.backend in controls.NAMES:
        module = controls
    else:
        module = adapters.load(args.backend)
    paths = [case_path, root / 'catalog.json', root / 'questions.py', root / 'policy.py',
             root / 'baselines.py', root / 'harness.py', root / 'controls.py', Path(module.__file__)]
    # Include worker and sandbox source because the backend module delegates execution.
    paths += sorted((root / 'adapters').glob('*.py'))
    if args.thresholds:
        paths.append(Path(args.thresholds))
    if args.control_gold:
        paths.append(Path(args.control_gold))
    input_hashes = {input_key(path, root): sha256(path) for path in paths}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'manifest.json').exists() or (out / 'records.jsonl').exists():
        raise ValueError('output directory already contains a run; choose a fresh directory')
    before = host_snapshot()
    started = utc_now()
    manifest = {'format_version': 1, 'backend': args.backend, 'split': args.split,
                'rule': args.rule, 'thresholds': rule, 'policy': args.policy,
                'question_set_version': QUESTION_SET_VERSION, 'policy_version': policy.POLICY_VERSION,
                'catalog_version': json.loads((root / 'catalog.json').read_text())['catalog_version'],
                'git': git_snapshot(root), 'input_hashes': input_hashes,
                'config_sha256': hashlib.sha256((args.config or '{}').encode()).hexdigest(),
                'frozen_sha256': sha256(root / 'FROZEN.json') if frozen else None,
                'started_at': started, 'ended_at': None, 'host_before': before, 'host_after': None,
                'load_label': before['load_label'], 'status': 'running',
                'repeats': args.repeats, 'limit': args.limit,
                'totals': {'cases': len(cases), 'records': 0, 'expected_records': len(cases) * args.repeats}}
    write_json(out / 'manifest.json', manifest)
    adapter = None
    info = {'backend': args.backend, 'model': args.backend, 'revision': 'baseline-v1', 'local': True}
    init_error = None
    sandbox_failed = False
    costs, tokens, unknown_costs, network_attempts = 0.0, 0, 0, 0
    run_started = time.perf_counter()
    try:
        if args.backend not in BASELINES:
            try:
                adapter = module.make_adapter({**config, 'backend': args.backend})
                info = adapter.info()
            except Exception as error:
                init_error = f'adapter-init: {type(error).__name__}'
        manifest['adapter_info'] = info
        write_json(out / 'manifest.json', manifest)
        route_fn = {'standard': policy.route,
                    'defective': controls.defective_route_ignore_unsupported,
                    'defective-all': controls.defective_route_no_constraints}[args.policy]
        with (out / 'records.jsonl').open('x') as stream:
            for case in cases:
                for repeat in range(args.repeats):
                    request = build_request(case)
                    request_hash = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
                    began = time.perf_counter()
                    raw = None
                    if args.backend in BASELINES:
                        answer_fn = baselines.matrix_lookup_answers if args.backend == 'matrix' else baselines.manual_default_answers
                        raw = {'ok': True, 'answers': answer_fn(case), 'error': None,
                               'model': args.backend, 'revision': 'baseline-v1', 'usage': {'input_tokens': 0},
                               'latency_ms': 0.0, 'cost_usd': 0.0, 'raw': None, 'network_attempts_blocked': 0}
                    elif init_error:
                        raw = failure_result(init_error, info)
                    else:
                        try:
                            raw = adapter.classify(request)
                        except Exception as error:
                            raw = failure_result(f'adapter-exception: {type(error).__name__}', info)
                    answers, errors, malformed = validate_result(raw)
                    result = raw if isinstance(raw, dict) else failure_result('malformed', info, raw)
                    backend_info = {**info, 'model': result.get('model'), 'revision': result.get('revision')}
                    if args.backend == 'keep-current':
                        routed = baselines.keep_current_route(case, backend_info)
                    elif answers is None:
                        error = 'malformed' if errors else result.get('error') or 'backend-unavailable'
                        routed = policy.route_from_error(case, error, rule, backend_info)
                    else:
                        routed = route_fn(case, answers, rule, backend_info)
                    elapsed = (time.perf_counter() - began) * 1000
                    if args.backend in BASELINES:
                        result['latency_ms'] = elapsed
                    top_class = min(answers['task_class']['probs'], key=lambda label: (-answers['task_class']['probs'][label], label)) if answers else None
                    if args.backend == 'keep-current':
                        top_class = routed.get('routed_task_class')
                    record = {'case_id': case['id'], 'repeat': repeat, 'request_hash': request_hash,
                              'raw_result': raw, 'answers': answers, 'validation_errors': errors,
                              'adapter_malformed': malformed, 'top_class': top_class, 'route': routed,
                              'timing': {'latency_ms': result.get('latency_ms', elapsed), 'total_ms': elapsed}}
                    stream.write(json.dumps(json_safe(record), allow_nan=False) + '\n')
                    stream.flush()
                    sandbox_failed |= 'NETWORK-REACHED' in json.dumps(json_safe(raw))
                    manifest['totals']['records'] += 1
                    usage = result.get('usage')
                    if isinstance(usage, dict):
                        value = usage.get('input_tokens')
                        if type(value) in (int, float) and math.isfinite(value):
                            tokens += value
                    cost = result.get('cost_usd')
                    if type(cost) in (int, float) and math.isfinite(cost):
                        costs += cost
                    else:
                        unknown_costs += 1
                    blocked = result.get('network_attempts_blocked')
                    if type(blocked) in (int, float) and math.isfinite(blocked):
                        network_attempts += blocked
        manifest['status'] = 'sandbox-failed' if sandbox_failed else 'complete'
    finally:
        if adapter is not None:
            try:
                adapter.close()
                manifest['adapter_info_after'] = adapter.info()
            except Exception as error:
                manifest['close_error'] = type(error).__name__
                manifest['status'] = 'failed'
        manifest['ended_at'] = utc_now()
        manifest['host_after'] = host_snapshot()
        if manifest['host_after']['load_label'] == 'contended':
            manifest['load_label'] = 'contended'
        if sandbox_failed:
            manifest['status'] = 'sandbox-failed'
        elif manifest['status'] == 'running':
            manifest['status'] = 'failed'
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform != 'darwin':
            rss *= 1024
        adapter_rss = manifest.get('adapter_info_after', {}).get('peak_rss_bytes', 0) or 0
        manifest['totals'].update(elapsed_s=time.perf_counter() - run_started,
                                  peak_rss_bytes=max(rss, adapter_rss), input_tokens=tokens,
                                  cost_usd_known=costs, unknown_cost_records=unknown_costs,
                                  network_attempts_blocked=network_attempts)
        write_json(out / 'manifest.json', manifest)
    return manifest


def tune(run_dirs, gold_path, out, root=ROOT):
    from score import achieved_utility, check_route
    root = Path(root)
    if Path(gold_path).resolve() != (root / 'cases/dev-gold.jsonl').resolve():
        raise ValueError('tuning accepts only cases/dev-gold.jsonl')
    gold = {row['id']: row for row in read_jsonl(gold_path)}
    cases = {case['id']: case for case in read_jsonl(root / 'cases/dev.jsonl')}
    stored = []
    backends = set()
    run_hashes = []
    for directory in run_dirs:
        directory = Path(directory)
        manifest = json.loads((directory / 'manifest.json').read_text())
        if manifest['split'] != 'dev':
            raise ValueError('tuning accepts only dev runs')
        if manifest.get('policy', 'standard') != 'standard':
            raise ValueError('defective-policy records cannot tune thresholds')
        if manifest['input_hashes'].get('cases/dev.jsonl') != sha256(root / 'cases/dev.jsonl'):
            raise ValueError('dev cases differ from captured input')
        backends.add(manifest['backend'])
        if manifest['backend'] == 'keep-current':
            raise ValueError('keep-current has no classifier thresholds to tune')
        run_hashes.append({'manifest': sha256(directory / 'manifest.json'), 'records': sha256(directory / 'records.jsonl')})
        for record in read_jsonl(directory / 'records.jsonl'):
            stored.append((record, manifest['adapter_info']))
    if len(backends) != 1 or not stored:
        raise ValueError('tune requires nonempty runs from one backend')
    grid = []
    for act in GRID:
        for effort_q in GRID:
            rule = {'name': 'dev-tuned', 'act': act, 'flag': min(0.6, act), 'effort_q': effort_q}
            utilities, violations = [], 0
            for record, info in stored:
                case = cases[record['case_id']]
                answers, errors = validate_answers(record.get('answers'))
                if answers is None:
                    raw = record.get('raw_result') or {}
                    route = policy.route_from_error(case, raw.get('error') or 'malformed', rule, info)
                else:
                    route = policy.route(case, answers, rule, info)
                failures = check_route(case, route)
                violations += bool(failures)
                utilities.append(achieved_utility(gold[case['id']], route, failures))
            grid.append({**rule, 'mean_utility': sum(utilities) / len(utilities),
                         'violations': violations, 'records': len(utilities)})
    eligible = [row for row in grid if row['violations'] == 0]
    if not eligible:
        raise ValueError('no threshold pair has zero constraint violations')
    chosen = max(eligible, key=lambda row: (row['mean_utility'], row['act'], row['effort_q']))
    result = {**chosen, 'backend': next(iter(backends)), 'tuned_at': utc_now(), 'grid': grid,
              'dev_gold_sha256': sha256(gold_path), 'source_runs': run_hashes}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    write_json(out, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run_parser = sub.add_parser('run')
    run_parser.add_argument('--backend', required=True)
    run_parser.add_argument('--split', choices=('dev', 'heldout'), required=True)
    run_parser.add_argument('--repeats', type=int, required=True)
    run_parser.add_argument('--rule', choices=('owner-bands', 'dev-tuned'), required=True)
    run_parser.add_argument('--thresholds', type=Path)
    run_parser.add_argument('--config', help='inline JSON configuration object')
    run_parser.add_argument('--limit', type=int)
    run_parser.add_argument('--out', type=Path, required=True)
    run_parser.add_argument('--control-gold', type=Path)
    run_parser.add_argument('--policy', choices=('standard', 'defective', 'defective-all'), default='standard')
    freeze_parser = sub.add_parser('freeze')
    freeze_parser.add_argument('--thresholds', type=Path, required=True)
    tune_parser = sub.add_parser('tune')
    tune_parser.add_argument('--runs', nargs='+', type=Path, required=True)
    tune_parser.add_argument('--gold', type=Path, required=True)
    tune_parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'run':
            run(args)
        elif args.command == 'freeze':
            freeze(args.thresholds)
        else:
            tune(args.runs, args.gold, args.out)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
