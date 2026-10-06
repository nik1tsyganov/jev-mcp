"""Independent routing checks and offline qualification reports (stdlib only).

results.json groups metrics and 95% intervals by backend, rule, and split,
with domain/effort breakdowns, failed constraints, and held-out gate reasons.
RESULTS.md includes the same complete metric tables as formatted JSON.
Proportions use records; repeat stability uses cases with multiple records;
twin stability uses matched case pairs and repeat indices. Degeneracy uses
one top class per case. Paired comparisons average repeats within each case.
Flag suggestion accuracy is suggested-class acceptance. Missing repeat,
twin, or complete baseline evidence cannot qualify a held-out backend.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

ROOT = Path(__file__).resolve().parent
SEALED = Path.home() / '.local/scratch/routing-qual-20261001/sealed/heldout-gold.jsonl'
SEED = 20261001
BASELINES = ('matrix', 'keep-current', 'manual')
OUTCOMES = {'recommendation', 'experimental-recommendation', 'keep-current',
            'abstain', 'backend-unavailable'}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def check_route(case, route):
    """Return C1-C10 violations without importing the routing policy."""
    errors = []

    def fail(code, message):
        errors.append(f'{code}: {message}')

    required = {'outcome', 'candidate_id', 'lead', 'heads', 'checkers', 'helper_count',
                'mode', 'routed_task_class', 'routed_effort', 'flag_suggestion',
                'reasons', 'uncertainty', 'provenance', 'dispatch_authorized'}
    if not isinstance(route, dict) or not required <= route.keys():
        return ['shape: missing route fields']
    if (not isinstance(route['outcome'], str) or route['outcome'] not in OUTCOMES or
            (route['heads'] is not None and not isinstance(route['heads'], dict)) or not isinstance(route['checkers'], list) or
            type(route['helper_count']) is not int or route['helper_count'] < 0 or
            not isinstance(route['reasons'], list) or
            not isinstance(route['uncertainty'], dict) or not isinstance(route['provenance'], dict)):
        return ['shape: invalid route field types']
    if route['dispatch_authorized'] is not False:
        fail('C9', 'dispatch must remain unauthorized')
    if route['mode'] != case['mode']:
        fail('shape', 'mode differs from case')
    if route['outcome'] in {'abstain', 'backend-unavailable'}:
        if (route['candidate_id'] is not None or route['lead'] is not None or
                route['heads'] or route['checkers'] or route['helper_count']):
            fail('shape', 'abstention contains a dispatch selection')
        return errors
    if not isinstance(route['candidate_id'], str):
        return errors + ['C1: candidate id is not a string']
    snapshot = case['snapshot']
    candidates = {candidate['id']: candidate for candidate in snapshot['candidates']}
    ids = route['candidate_id'].split('+')
    experimental = case['mode'] == 'experimentalOracle'
    if (any(cid not in candidates for cid in ids) or
            (len(ids) != 2 if experimental else len(ids) != 1)):
        return errors + ['C1: selection is not in the snapshot']
    used = [candidates[cid] for cid in ids]
    if any(candidate.get('available') is not True for candidate in used):
        fail('C2', 'candidate unavailable')
    actors = [actor for candidate in used for actor in
              [candidate.get('lead'), candidate.get('head'), *candidate.get('checkers', [])]
              if actor is not None]
    route_actors = [actor for actor in [route['lead'], route['heads'], *route['checkers']]
                    if actor is not None]
    if any(not isinstance(actor, dict) or not isinstance(actor.get('provider'), str)
           for actor in actors + route_actors):
        fail('shape', 'actor must identify its provider')
    elif any(actor['provider'] in snapshot['unsupported_providers'] for actor in actors + route_actors):
        fail('C3', 'unsupported provider')
    leads = [candidate['lead'] for candidate in used if candidate.get('lead') is not None]
    heads = [candidate['head'] for candidate in used if candidate.get('head') is not None]
    checkers = [actor for candidate in used for actor in candidate.get('checkers', [])]
    # Check model/provider identities independently of policy-assigned effort.
    def identities(items):
        return sorted((str(item.get('model')), str(item.get('provider')), str(item.get('profile')))
                      for item in items if isinstance(item, dict))
    if (identities([route['lead']] if route['lead'] else []) != identities(leads) or
            identities([route['heads']] if route['heads'] else []) != identities(heads) or
            identities(route['checkers']) != identities(checkers)):
        fail('shape', 'routed actors differ from snapshot selection')
    for candidate in used:
        try:
            age = (timestamp(snapshot['as_of']) - timestamp(candidate['evidence_date'])).total_seconds() / 86400
            if age > snapshot['evidence_max_age_days']:
                fail('C4', 'candidate evidence is stale')
        except (KeyError, TypeError, ValueError):
            fail('C4', 'candidate evidence date is invalid')
        if candidate['helper_count'] > snapshot['max_helpers']:
            fail('C5', 'candidate helper count exceeds the cap')
        metadata = case.get('metadata', {})
        if metadata.get('context_tokens', 0) > candidate['context_window_tokens']:
            fail('C6', 'context exceeds candidate window')
        if not set(metadata.get('tools_needed', [])) <= set(candidate['tools']):
            fail('C7', 'required tools unavailable')
    if route['helper_count'] != sum(candidate['helper_count'] for candidate in used):
        fail('C5', 'route changes the configured helper count')
    if route['helper_count'] > snapshot['max_helpers']:
        fail('C5', 'helper limit exceeded')
    mode = case['mode']
    if mode == 'hydraOracle' and any(c['kind'] != 'saved-pair' or not c['qualified'] for c in used):
        fail('C8', 'Hydra requires a qualified saved pair')
    if experimental:
        if (not snapshot['experimental_opt_in'] or
                [c['kind'] for c in used] != ['lead-side', 'head-side'] or
                route['outcome'] != 'experimental-recommendation'):
            fail('C8', 'experimental composition is not authorized')
    elif route['outcome'] == 'experimental-recommendation':
        fail('C8', 'experimental outcome outside experimental mode')
    if mode == 'conclave':
        if any(c['kind'] != 'seat-binding' or not c['qualified'] or
               route['routed_task_class'] not in c['task_classes'] for c in used):
            fail('C8', 'Conclave requires a qualified class binding')
        security_p = route['uncertainty'].get('security_p', 0)
        sensitive = route['routed_task_class'] in {'security-sensitive', 'hard-risky'}
        sensitive = sensitive or (isinstance(security_p, (int, float)) and security_p >= 0.8)
        if sensitive:
            providers = [checker.get('provider') for checker in route['checkers']
                         if isinstance(checker, dict)]
            lead_provider = route['lead'].get('provider') if isinstance(route['lead'], dict) else None
            if len(providers) < 2 or len(set(providers)) != len(providers) or lead_provider in providers:
                fail('C8', 'sensitive Conclave needs distinct checker providers')
    if route['outcome'] == 'keep-current':
        if not snapshot.get('current_candidate_id') or route['candidate_id'] != snapshot['current_candidate_id']:
            fail('C10', 'keep-current does not select the current candidate')
        if any(error.startswith(tuple(f'C{i}:' for i in range(2, 9))) for error in errors):
            fail('C10', 'current candidate is ineligible')
    return list(dict.fromkeys(errors))


def wilson(successes, count):
    if not count:
        return [None, None]
    z = 1.959963984540054
    p = successes / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap(values, resamples=2000, seed=SEED):
    if not values:
        return [None, None]
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choices(values, k=len(values))) for _ in range(resamples)]
    return [percentile(means, 0.025), percentile(means, 0.975)]


def proportion(values):
    count = len(values)
    successes = sum(bool(value) for value in values)
    return {'value': successes / count if count else None, 'n': count,
            'count': successes, 'ci95': wilson(successes, count)}


def mean_metric(values):
    return {'value': statistics.fmean(values) if values else None,
            'n': len(values), 'ci95': bootstrap(values)}


def achieved_utility(gold, route, violations):
    if violations:
        return 0.0
    outcome = route['outcome']
    if outcome in {'abstain', 'backend-unavailable'}:
        return float(gold['abstain_utility'])
    if outcome == 'keep-current':
        return float(gold['keep_current_utility'])
    field = 'composition_utility' if outcome == 'experimental-recommendation' else 'candidate_utility'
    return float(gold.get(field, {}).get(route['candidate_id'], 0))


def score_record(case, gold, record):
    route = record.get('route')
    violations = check_route(case, route)
    route = route if isinstance(route, dict) else {}
    outcome = route.get('outcome')
    utility = achieved_utility(gold, route, violations)
    possible = [*gold.get('candidate_utility', {}).values(),
                *gold.get('composition_utility', {}).values(),
                gold['abstain_utility'], gold['keep_current_utility']]
    eligible = any(cid not in gold.get('ineligible', {}) for cid in gold.get('candidate_utility', {}))
    eligible = eligible or any(all(cid not in gold.get('ineligible', {}) for cid in composition.split('+'))
                               for composition in gold.get('composition_utility', {}))
    raw = record.get('raw_result', {})
    raw = raw if isinstance(raw, dict) else {}
    errors = record.get('validation_errors', [])
    acceptance = route.get('routed_task_class') in gold['acceptable_task_classes']
    suggestion = route.get('flag_suggestion')
    suggested_class = suggestion.get('task_class', suggestion.get('routed_task_class')) if isinstance(suggestion, dict) else suggestion
    uncertainty = route.get('uncertainty')
    confidence = uncertainty.get('class_top_p') if isinstance(uncertainty, dict) else None
    usage = raw.get('usage') if isinstance(raw.get('usage'), dict) else {}
    latency = record.get('timing', {}).get('latency_ms', raw.get('latency_ms', 0))
    latency = latency if type(latency) in (int, float) and math.isfinite(latency) else 0
    tokens = usage.get('input_tokens', 0)
    tokens = tokens if type(tokens) in (int, float) and math.isfinite(tokens) else 0
    cost = raw.get('cost_usd')
    cost = cost if type(cost) in (int, float) and math.isfinite(cost) else None
    network = raw.get('network_attempts_blocked', 0)
    network = network if type(network) in (int, float) and math.isfinite(network) else 0
    confidence = confidence if type(confidence) in (int, float) and math.isfinite(confidence) and 0 <= confidence <= 1 else None
    return {'id': case['id'], 'repeat': record['repeat'], 'case': case, 'gold': gold,
            'record': record, 'violations': violations, 'utility': utility,
            'regret': max(possible) - utility if eligible else None,
            'invalid_output': bool(errors) or bool(record.get('adapter_malformed')),
            'invalid_route': any(v.startswith(('C1:', 'shape:')) for v in violations),
            'abstention': outcome in {'abstain', 'backend-unavailable'},
            'justified': outcome in {'abstain', 'backend-unavailable'} and 'abstain' in gold['expected_outcomes'],
            'unjustified': outcome in {'abstain', 'backend-unavailable'} and 'abstain' not in gold['expected_outcomes'],
            'class_acceptance': acceptance, 'effort_acceptance': route.get('routed_effort') in gold['acceptable_efforts'],
            'confidence': confidence, 'top_class': record.get('top_class', route.get('routed_task_class')),
            'suggestion_correct': suggested_class in gold['acceptable_task_classes'] if suggestion is not None else None,
            'latency_ms': latency, 'input_tokens': tokens, 'cost_usd': cost,
            'network_attempts': network,
            'over_limit_misrouted': raw.get('error') == 'input_over_limit'
            and outcome != 'backend-unavailable'}


def summary(rows):
    metrics = {}
    for name in ('invalid_output', 'invalid_route', 'justified', 'unjustified', 'class_acceptance', 'effort_acceptance'):
        metrics[name] = proportion([row[name] for row in rows])
    metrics['constraint_violation'] = proportion([bool(row['violations']) for row in rows])
    metrics['achieved_utility'] = mean_metric([row['utility'] for row in rows])
    metrics['regret'] = mean_metric([row['regret'] for row in rows if row['regret'] is not None])
    metrics['flag_band_suggestion_accuracy'] = proportion([row['suggestion_correct'] for row in rows if row['suggestion_correct'] is not None])
    groups = defaultdict(list)
    for row in rows:
        groups[row['id']].append(row)
    def selection(row):
        route = row['record'].get('route')
        return (route.get('candidate_id'), route.get('outcome')) if isinstance(route, dict) else (None, None)

    stable = []
    for repeats in groups.values():
        if len(repeats) > 1:
            stable.append(len({selection(row) for row in repeats}) == 1)
    metrics['repeat_stability'] = proportion(stable)
    twin_stability = []
    seen = set()
    for row in rows:
        twin_id = row['case'].get('twin_of')
        if twin_id not in groups:
            continue
        key = (tuple(sorted((row['id'], twin_id))), row['repeat'])
        if key in seen:
            continue
        match = next((other for other in groups[twin_id] if other['repeat'] == row['repeat']), None)
        if match:
            seen.add(key)
            twin_stability.append(selection(row) == selection(match))
    metrics['twin_stability'] = proportion(twin_stability)
    top_classes = Counter(repeats[0]['top_class'] for repeats in groups.values() if repeats[0]['top_class'] is not None)
    metrics['degenerate'] = bool(groups) and max(top_classes.values(), default=0) / len(groups) >= 0.9
    metrics['top_classes'] = dict(top_classes)
    latency = [row['latency_ms'] for row in rows]
    metrics['latency_ms'] = {'p50': percentile(latency, 0.5), 'p95': percentile(latency, 0.95)}
    metrics['input_tokens'] = sum(row['input_tokens'] for row in rows)
    known_costs = [row['cost_usd'] for row in rows if row['cost_usd'] is not None]
    metrics['usd'] = {'total_known': sum(known_costs), 'unknown_records': len(rows) - len(known_costs)}
    metrics['network_attempts_blocked'] = sum(row['network_attempts'] for row in rows)
    metrics['over_limit_misrouted'] = sum(row['over_limit_misrouted'] for row in rows)
    confidences = [(row['confidence'], int(row['class_acceptance'])) for row in rows if row['confidence'] is not None]
    bins = []
    for index in range(10):
        items = [(p, y) for p, y in confidences if min(int(p * 10), 9) == index]
        bins.append({'lower': index / 10, 'upper': (index + 1) / 10, 'n': len(items),
                     'confidence': statistics.fmean(p for p, _ in items) if items else None,
                     'accuracy': statistics.fmean(y for _, y in items) if items else None})
    metrics['confidence_descriptive_uncalibrated'] = {
        'brier': mean_metric([(p - y) ** 2 for p, y in confidences]),
        'ece_10_bins': sum(item['n'] * abs(item['confidence'] - item['accuracy'])
                           for item in bins if item['n']) / len(confidences) if confidences else None,
        'bins': bins}
    return metrics


def verify_gold_access(gold_path, manifests, root=ROOT, sealed_path=SEALED):
    """Apply the sealed-gold gate before opening the gold file."""
    gold_path, root = Path(gold_path), Path(root)
    heldout = [manifest for manifest in manifests if manifest.get('split') == 'heldout']
    if gold_path.resolve() != Path(sealed_path).resolve() and not heldout:
        return
    frozen_path = root / 'FROZEN.json'
    if not frozen_path.exists():
        raise ValueError('sealed/held-out scoring requires FROZEN.json')
    frozen = json.loads(frozen_path.read_text())
    freeze_time = timestamp(frozen['frozen_at'])
    for manifest in heldout:
        if freeze_time >= timestamp(manifest['started_at']):
            raise ValueError('freeze must precede every held-out run')
    expected = (root / 'cases/heldout-gold.sha256').read_text().strip().split()[0]
    if sha256(gold_path) != expected:
        raise ValueError('held-out gold hash mismatch')
    commitment = frozen.get('heldout_gold_sha256', '').strip().split()
    if not commitment or commitment[0] != expected:
        raise ValueError('gold hash differs from the frozen commitment')
    for manifest in heldout:
        if manifest.get('frozen_sha256') != sha256(frozen_path):
            raise ValueError('run does not identify the current freeze commitment')


def gate_status(metrics, difference, manifests, backend):
    if not manifests or any(m.get('split') != 'heldout' for m in manifests):
        return {'status': 'not-run', 'reasons': ['held-out qualification not run']}
    failures = []
    checks = [('constraint violations', metrics['constraint_violation']['count'] == 0),
              ('invalid-output Wilson upper exceeds 0.05', metrics['invalid_output']['ci95'][1] is not None and metrics['invalid_output']['ci95'][1] <= 0.05),
              ('unjustified abstention exceeds 0.20', metrics['unjustified']['value'] is not None and metrics['unjustified']['value'] <= 0.20),
              ('repeat stability below 0.95 or missing', metrics['repeat_stability']['value'] is not None and metrics['repeat_stability']['value'] >= 0.95),
              ('twin stability below 0.80 or missing', metrics['twin_stability']['value'] is not None and metrics['twin_stability']['value'] >= 0.80)]
    failures.extend(reason for reason, passed in checks if not passed)
    if backend in {'laya', 'qwen_reranker', 'decider'} and metrics['network_attempts_blocked']:
        failures.append('local backend attempted network access')
    if backend in {'laya', 'qwen_reranker', 'decider'} and metrics['over_limit_misrouted']:
        failures.append('over-limit input did not produce backend-unavailable')
    if any(m.get('status') != 'complete' for m in manifests):
        failures.append('run incomplete or sandbox failed')
    if any(m.get('policy', 'standard') != 'standard' for m in manifests):
        failures.append('deliberately defective policy cannot qualify')
    if difference is None or difference.get('complete_pairs') is not True:
        failures.append('all three paired baselines are required')
    if failures:
        return {'status': 'unqualified', 'reasons': failures}
    lower, upper = difference['ci95']
    if lower > 0:
        return {'status': 'qualified', 'reasons': []}
    if lower <= 0 <= upper:
        return {'status': 'inconclusive', 'reasons': ['paired utility interval includes zero']}
    return {'status': 'unqualified', 'reasons': ['utility does not beat the best baseline']}


def score_runs(run_dirs, gold_path, out, root=ROOT):
    manifests = [json.loads((Path(directory) / 'manifest.json').read_text()) for directory in run_dirs]
    verify_gold_access(gold_path, manifests, root)
    gold = {row['id']: row for row in read_jsonl(gold_path)}
    groups, group_manifests = defaultdict(list), defaultdict(list)
    case_cache = {}
    for directory, manifest in zip(run_dirs, manifests):
        split = manifest['split']
        case_path = Path(root) / 'cases' / f'{split}.jsonl'
        if split not in case_cache:
            case_cache[split] = {case['id']: case for case in read_jsonl(case_path)}
        recorded_hash = manifest.get('input_hashes', {}).get(f'cases/{split}.jsonl')
        if recorded_hash != sha256(case_path):
            raise ValueError('cases differ from the run input hash')
        key = (manifest['backend'], manifest['rule'], split)
        if group_manifests[key]:
            previous = group_manifests[key][0]
            if previous.get('thresholds') != manifest.get('thresholds') or previous.get('policy') != manifest.get('policy'):
                raise ValueError('cannot pool different thresholds or policy implementations')
        records = read_jsonl(Path(directory) / 'records.jsonl')
        for record in records:
            cid = record['case_id']
            groups[key].append(score_record(case_cache[split][cid], gold[cid], record))
        group_manifests[key].append(manifest)
    per_case = {}
    for key, rows in groups.items():
        values = defaultdict(list)
        for row in rows:
            values[row['id']].append(row['utility'])
        per_case[key] = {cid: statistics.fmean(items) for cid, items in values.items()}
    results = {'seed': SEED, 'bootstrap_resamples': 2000, 'groups': []}
    for key, rows in groups.items():
        backend, rule, split = key
        metrics = summary(rows)
        # Baseline answers carry probability 1.0, so their routes do not depend on the rule.
        baseline_keys = [(name, 'owner-bands', split) for name in BASELINES]
        difference = None
        if all(bkey in per_case and per_case[bkey] for bkey in baseline_keys):
            best = max(baseline_keys, key=lambda bkey: statistics.fmean(per_case[bkey].values()))
            shared = sorted(set(per_case[key]) & set(per_case[best]))
            differences = [per_case[key][cid] - per_case[best][cid] for cid in shared]
            difference = mean_metric(differences)
            difference.update({'best_baseline': best[0], 'complete_pairs': bool(shared) and
                               all(set(per_case[bkey]) == set(per_case[key]) for bkey in baseline_keys)})
        metrics['paired_difference_vs_best_baseline'] = difference
        rss = [m.get('totals', {}).get('peak_rss_bytes') for m in group_manifests[key]]
        metrics['peak_rss_bytes'] = max((value for value in rss if value is not None), default=None)
        breakdowns = {}
        for field in ('domain', 'preferred_effort'):
            buckets = defaultdict(list)
            for row in rows:
                buckets[row['gold'][field] or 'none'].append(row)
            breakdowns[field] = {label: summary(bucket) for label, bucket in sorted(buckets.items())}
        results['groups'].append({'backend': backend, 'rule': rule, 'split': split,
                                  'records': len(rows), 'metrics': metrics, 'breakdowns': breakdowns,
                                  'gate': gate_status(metrics, difference, group_manifests[key], backend),
                                  'violations': [{'case_id': row['id'], 'repeat': row['repeat'], 'errors': row['violations']}
                                                 for row in rows if row['violations']]})
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'results.json').write_text(json.dumps(results, indent=2, allow_nan=False) + '\n')
    lines = ['# Routing qualification results', '',
             'Confidence scores are uncalibrated. Brier and ECE values are descriptive.', '',
             'Proportion intervals: Wilson 95%. Mean intervals: 2,000 percentile bootstrap resamples.',
             'Paired comparisons resample case-level utility differences with seed 20261001.', '',
             '| Backend | Rule | Split | Gate | Mean utility |', '|---|---|---|---|---:|']
    for group in results['groups']:
        lines.append(f"| {group['backend']} | {group['rule']} | {group['split']} | {group['gate']['status']} | {group['metrics']['achieved_utility']['value']} |")
    for group in results['groups']:
        lines.extend(['', f"## {group['backend']} / {group['rule']} / {group['split']}", '',
                      '```json', json.dumps({'metrics': group['metrics'], 'gate': group['gate'],
                                            'breakdowns': group['breakdowns'], 'violations': group['violations']}, indent=2), '```'])
    (out / 'RESULTS.md').write_text('\n'.join(lines) + '\n')
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('score')
    command.add_argument('--runs', nargs='+', required=True, type=Path)
    command.add_argument('--gold', required=True, type=Path)
    command.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        score_runs(args.runs, args.gold, args.out)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
