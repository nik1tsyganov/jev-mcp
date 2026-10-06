"""Small synthetic checks. No corpus, model, subprocess, or network is used."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import controls
import harness
import policy
from questions import build_request, validate_answers
import score


def fixture():
    candidate = {
        'id': 'pair-a', 'kind': 'saved-pair',
        'lead': {'model': 'lead-model', 'provider': 'provider-a', 'effort': 'medium'},
        'head': {'model': 'head-model', 'provider': 'provider-b', 'effort': 'medium', 'profile': 'review'},
        'checkers': [], 'helper_count': 2, 'task_classes': ['standard-feature'],
        'context_window_tokens': 32000, 'tools': ['read', 'edit'],
        'evidence_date': '2026-09-30', 'qualified': True, 'available': True,
    }
    case = {
        'id': 'fixture-1', 'split': 'dev', 'twin_of': None, 'mode': 'hydraOracle',
        'task_text': 'Implement a small routine feature with existing components.',
        'metadata': {'context_tokens': 1000, 'tools_needed': ['read']},
        'snapshot': {'as_of': '2026-10-01', 'candidates': [candidate],
                     'current_candidate_id': 'pair-a', 'max_helpers': 2,
                     'unsupported_providers': [], 'evidence_max_age_days': 30,
                     'experimental_opt_in': False},
    }
    gold = {
        'id': case['id'], 'domain': 'fixture', 'tags': [], 'context_band': 'small',
        'acceptable_task_classes': ['standard-feature'], 'preferred_task_class': 'standard-feature',
        'acceptable_efforts': ['medium'], 'preferred_effort': 'medium',
        'flags': {'security_sensitive': False, 'injection_present': False, 'ambiguous': False},
        'expected_outcomes': ['recommendation'], 'candidate_utility': {'pair-a': 1.0},
        'ineligible': {}, 'composition_utility': {}, 'abstain_utility': 0.0,
        'keep_current_utility': 0.5, 'rationale': 'One eligible exact-match pair.',
    }
    return case, gold


def record_for(case, adapter, repeat=0):
    result = adapter.classify(build_request(case))
    answers, errors, malformed = harness.validate_result(result)
    route = (policy.route(case, answers, policy.RULES['owner-bands'], adapter.info()) if answers
             else policy.route_from_error(case, 'malformed', policy.RULES['owner-bands'], adapter.info()))
    return {'case_id': case['id'], 'repeat': repeat, 'request_hash': 'fixture',
            'raw_result': result, 'answers': answers, 'validation_errors': errors,
            'adapter_malformed': malformed, 'route': route,
            'top_class': max(answers['task_class']['probs'], key=answers['task_class']['probs'].get) if answers else None,
            'timing': {'latency_ms': result['latency_ms']}}


class ControlsTests(unittest.TestCase):
    def test_oracle_has_zero_regret(self):
        case, gold = fixture()
        oracle = controls.make_adapter({'backend': 'control_oracle', 'gold': {case['id']: gold}})
        row = score.score_record(case, gold, record_for(case, oracle))
        self.assertEqual(row['violations'], [])
        self.assertEqual(row['utility'], 1.0)
        self.assertEqual(row['regret'], 0.0)

    def test_each_malformed_variant_is_rejected(self):
        case, _ = fixture()
        for variant in controls.MALFORMED_VARIANTS:
            with self.subTest(variant=variant):
                adapter = controls.make_adapter({'backend': f'control_malformed_{variant}'})
                result = adapter.classify(build_request(case))
                answers, errors = validate_answers(result['answers'])
                self.assertIsNone(answers)
                self.assertTrue(errors)
                answers, errors, _ = harness.validate_result(result)
                self.assertIsNone(answers)
                self.assertTrue(errors)

    def test_anti_uses_unacceptable_labels(self):
        case, gold = fixture()
        adapter = controls.make_adapter({'backend': 'control_anti', 'gold': {case['id']: gold}})
        answers = adapter.classify(build_request(case))['answers']
        for qid, acceptable in [('task_class', gold['acceptable_task_classes']), ('effort', gold['acceptable_efforts'])]:
            chosen = max(answers[qid]['probs'], key=answers[qid]['probs'].get)
            self.assertNotIn(chosen, acceptable)
            self.assertEqual(answers[qid]['probs'][chosen], 1.0)

    def test_constant_is_degenerate(self):
        case, gold = fixture()
        adapter = controls.make_adapter({'backend': 'control_constant'})
        rows = []
        for index in range(12):
            current = deepcopy(case)
            current['id'] = f'constant-{index}'
            rows.append(score.score_record(current, gold, record_for(current, adapter)))
        self.assertTrue(score.summary(rows)['degenerate'])

    def test_random_is_seeded(self):
        case, _ = fixture()
        first = controls.make_adapter({'backend': 'control_random', 'seed': 19})
        second = controls.make_adapter({'backend': 'control_random', 'seed': 19})
        request = build_request(case)
        self.assertEqual([first.classify(request)['answers'] for _ in range(5)],
                         [second.classify(request)['answers'] for _ in range(5)])

    def test_adapter_shape_is_rejected(self):
        for result in (None, [], {'ok': True}):
            with self.subTest(result=result):
                answers, errors, malformed = harness.validate_result(result)
                self.assertIsNone(answers)
                self.assertTrue(errors)
                self.assertTrue(malformed)


class ConstraintTests(unittest.TestCase):
    def setUp(self):
        self.case, self.gold = fixture()
        self.adapter = controls.make_adapter({'backend': 'control_constant'})
        self.route = record_for(self.case, self.adapter)['route']

    def test_independent_checker_catches_defective_policy(self):
        self.case['snapshot']['unsupported_providers'] = ['provider-a']
        answers = self.adapter.classify(build_request(self.case))['answers']
        normal = policy.route(self.case, answers, policy.RULES['owner-bands'], self.adapter.info())
        defective = controls.defective_route_ignore_unsupported(
            self.case, answers, policy.RULES['owner-bands'], self.adapter.info())
        self.assertEqual(normal['outcome'], 'abstain')
        self.assertEqual(defective['outcome'], 'recommendation')
        violations = score.check_route(self.case, defective)
        self.assertTrue(any(error.startswith('C3:') for error in violations))
        self.assertEqual(score.achieved_utility(self.gold, defective, violations), 0.0)
        self.assertEqual(self.case['snapshot']['unsupported_providers'], ['provider-a'])

    def test_c1_unknown_candidate(self):
        self.route['candidate_id'] = 'missing'
        self.assertTrue(any(error.startswith('C1:') for error in score.check_route(self.case, self.route)))

    def test_c2_unavailable(self):
        self.case['snapshot']['candidates'][0]['available'] = False
        self.assertTrue(any(error.startswith('C2:') for error in score.check_route(self.case, self.route)))

    def test_c4_stale_evidence(self):
        self.case['snapshot']['candidates'][0]['evidence_date'] = '2025-01-01'
        self.assertTrue(any(error.startswith('C4:') for error in score.check_route(self.case, self.route)))

    def test_c5_helper_cap(self):
        self.route['helper_count'] = 3
        self.assertTrue(any(error.startswith('C5:') for error in score.check_route(self.case, self.route)))

    def test_c6_context_window(self):
        self.case['metadata']['context_tokens'] = 32001
        self.assertTrue(any(error.startswith('C6:') for error in score.check_route(self.case, self.route)))

    def test_c7_required_tools(self):
        self.case['metadata']['tools_needed'] = ['unavailable']
        self.assertTrue(any(error.startswith('C7:') for error in score.check_route(self.case, self.route)))

    def test_c8_qualified_pair(self):
        self.case['snapshot']['candidates'][0]['qualified'] = False
        self.assertTrue(any(error.startswith('C8:') for error in score.check_route(self.case, self.route)))

    def test_c9_dispatch_is_always_false(self):
        self.route['dispatch_authorized'] = True
        self.assertTrue(any(error.startswith('C9:') for error in score.check_route(self.case, self.route)))

    def test_c10_keep_current(self):
        self.route['outcome'] = 'keep-current'
        self.case['snapshot']['current_candidate_id'] = None
        self.assertTrue(any(error.startswith('C10:') for error in score.check_route(self.case, self.route)))


class GuardTests(unittest.TestCase):
    def test_heldout_guard_refuses_without_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'FROZEN'):
                harness.verify_frozen(Path(directory))

    def test_sealed_gold_refuses_without_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sealed = root / 'sealed.jsonl'
            with self.assertRaisesRegex(ValueError, 'FROZEN'):
                score.verify_gold_access(sealed, [], root, sealed)

    def test_sealed_gold_refuses_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'cases').mkdir()
            sealed = root / 'sealed.jsonl'
            sealed.write_text('{}\n')
            commitment = '0' * 64 + '\n'
            (root / 'cases/heldout-gold.sha256').write_text(commitment)
            (root / 'FROZEN.json').write_text(json.dumps({
                'frozen_at': '2026-10-01T12:00:00+00:00', 'heldout_gold_sha256': commitment}))
            manifests = [{'split': 'heldout', 'started_at': '2026-10-01T13:00:00+00:00'}]
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                score.verify_gold_access(sealed, manifests, root, sealed)

    def test_sealed_gold_refuses_run_before_freeze(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'FROZEN.json').write_text(json.dumps({'frozen_at': '2026-10-01T12:00:00+00:00'}))
            sealed = root / 'sealed.jsonl'
            manifests = [{'split': 'heldout', 'started_at': '2026-10-01T11:59:59+00:00'}]
            with self.assertRaisesRegex(ValueError, 'precede'):
                score.verify_gold_access(sealed, manifests, root, sealed)


class StatisticsTests(unittest.TestCase):
    def test_wilson_known_values(self):
        lower, upper = score.wilson(5, 10)
        self.assertAlmostEqual(lower, 0.2365930905, places=9)
        self.assertAlmostEqual(upper, 0.7634069095, places=9)
        lower, upper = score.wilson(0, 100)
        self.assertAlmostEqual(lower, 0.0, places=12)
        self.assertAlmostEqual(upper, 0.0369934982, places=9)
        self.assertEqual(score.wilson(0, 0), [None, None])

    def test_bootstrap_is_deterministic(self):
        values = [0.0, 0.2, 0.5, 0.8, 1.0]
        first = score.bootstrap(values)
        self.assertEqual(first, score.bootstrap(values, seed=20261001))
        self.assertLessEqual(first[0], first[1])
        self.assertEqual(score.bootstrap([0.5]), [0.5, 0.5])

    def test_repeat_and_twin_stability(self):
        case, gold = fixture()
        twin = deepcopy(case)
        twin.update(id='fixture-twin', twin_of=case['id'])
        adapter = controls.make_adapter({'backend': 'control_constant'})
        rows = [score.score_record(current, gold, record_for(current, adapter, repeat))
                for current in (case, twin) for repeat in range(2)]
        metrics = score.summary(rows)
        self.assertEqual(metrics['repeat_stability']['value'], 1.0)
        self.assertEqual(metrics['twin_stability']['value'], 1.0)


if __name__ == '__main__':
    unittest.main()
