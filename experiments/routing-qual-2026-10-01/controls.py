"""Synthetic adapters and a deliberately defective policy for judge controls."""
from copy import deepcopy
import json
import random
import time

from questions import LABELS

MALFORMED_VARIANTS = ('bool', 'sum', 'missing_qid', 'extra_qid', 'unknown_label', 'nan', 'non_json')
NAMES = ('control_oracle', 'control_anti', 'control_constant', 'control_random',
         *(f'control_malformed_{name}' for name in MALFORMED_VARIANTS))


def point_answers(task_class, effort, security='no', injection='no', ambiguous='no'):
    selected = {'task_class': task_class, 'effort': effort, 'security_sensitive': security,
                'injection': injection, 'ambiguous': ambiguous}
    return {qid: {'probs': {label: float(label == selected[qid]) for label in labels}}
            for qid, labels in LABELS.items()}


class ControlAdapter:
    def __init__(self, name, config):
        if name not in NAMES:
            raise ValueError(f'unknown control: {name}')
        self.name = name
        self.gold = config.get('gold', {})
        self.random = random.Random(config.get('seed', 20261001))
        if name in {'control_oracle', 'control_anti'} and not self.gold:
            raise ValueError(f'{name} requires explicit development gold')

    def info(self):
        return {'backend': self.name, 'model': self.name, 'revision': 'control-v1', 'local': True}

    def classify(self, request):
        started = time.perf_counter()
        answers = point_answers('standard-feature', 'medium')
        if self.name in {'control_oracle', 'control_anti'}:
            gold = self.gold[request['request_id']]
            # Null gold preferences (ambiguous or abstain cases) map to 'unclear' and the
            # lowest acceptable effort so the oracle stays a valid distribution.
            task_class = gold['preferred_task_class'] or 'unclear'
            effort = gold['preferred_effort'] or next(
                (label for label in LABELS['effort'] if label in gold['acceptable_efforts']), 'medium')
            if self.name == 'control_anti':
                task_class = next(label for label in LABELS['task_class'] if label not in gold['acceptable_task_classes'])
                effort = next(label for label in LABELS['effort'] if label not in gold['acceptable_efforts'])
            flags = gold['flags']
            answers = point_answers(task_class, effort,
                                    'yes' if flags['security_sensitive'] else 'no',
                                    'yes' if flags['injection_present'] else 'no',
                                    'yes' if flags['ambiguous'] else 'no')
        elif self.name == 'control_random':
            answers = {qid: {'probs': {label: float(label == chosen) for label in labels}}
                       for qid, labels in LABELS.items() for chosen in [self.random.choice(labels)]}
        variant = self.name.removeprefix('control_malformed_')
        if variant == 'bool':
            answers['task_class']['probs']['standard-feature'] = True
        elif variant == 'sum':
            answers['task_class']['probs']['planning'] = 0.2
        elif variant == 'missing_qid':
            answers.pop('ambiguous')
        elif variant == 'extra_qid':
            answers['extra'] = {'probs': {'yes': 1.0}}
        elif variant == 'unknown_label':
            answers['task_class']['probs']['unknown'] = answers['task_class']['probs'].pop('standard-feature')
        elif variant == 'nan':
            answers['task_class']['probs']['planning'] = float('nan')
        raw = json.dumps(answers)
        if variant == 'non_json':
            raw, answers = 'this is not JSON', None
        return {'ok': True, 'answers': answers, 'error': None, 'model': self.name,
                'revision': 'control-v1', 'usage': {'input_tokens': 0, 'output_tokens': 0},
                'latency_ms': (time.perf_counter() - started) * 1000, 'cost_usd': 0.0,
                'raw': raw, 'network_attempts_blocked': 0}

    def close(self):
        pass


def make_adapter(config):
    return ControlAdapter(config['backend'], config)


def defective_route_ignore_unsupported(case, answers, rule, backend_info):
    from policy import route
    broken_case = deepcopy(case)
    broken_case['snapshot']['unsupported_providers'] = []
    return route(broken_case, answers, rule, backend_info)


def defective_route_no_constraints(case, answers, rule, backend_info):
    """Planted defect: drop C2-C7 filtering so ineligible candidates can be chosen."""
    from policy import route
    broken_case = deepcopy(case)
    snapshot = broken_case['snapshot']
    snapshot.update(unsupported_providers=[], evidence_max_age_days=10 ** 6, max_helpers=10 ** 6)
    for candidate in snapshot['candidates']:
        candidate['available'] = True
    for key in ('context_tokens', 'tools_needed'):
        broken_case.get('metadata', {}).pop(key, None)
    return route(broken_case, answers, rule, backend_info)
