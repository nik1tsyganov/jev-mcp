import contextlib
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import laya_compare as bench


def case(kind='choice'):
    criteria = {'yes': 'yes', 'no': 'no'} if kind == 'choice' else ['none', 'all']
    return {'id': 'one', 'group': 'g', 'split': 'smoke', 'state': 'yes',
            'questions': {'q': {'type': kind, 'instructions': 'Is it yes?', 'criteria': criteria}},
            'expected': {'q': 'yes' if kind == 'choice' else 1}}


def record():
    return {'case_id': 'one', 'group': 'g', 'primitive': 'choice', 'question_id': 'q',
            'input_hash': 'same', 'ok': True, 'schema_ok': True, 'prediction': 'yes',
            'expected': 'yes', 'latency_samples': [0.1],
            'raw_answer': {'answers': {'q': {'choice': 'yes', 'confidence': 0.03,
                'probabilities': {'yes': 0.6, 'no': 0.4}}}}}


class ComparisonTests(unittest.TestCase):
    def test_error_redaction_handles_a_present_key_without_crashing(self):
        self.assertEqual(bench.redact_error('failed fixture-secret twice fixture-secret', 'fixture-secret'),
                         'failed [redacted] twice [redacted]')

    def test_local_only_does_not_add_paid_reference(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(bench.main(['--provider', 'laya-mlx']), 0)
        self.assertNotIn('planned Jev requests:', out.getvalue())

    def test_choice_ece_uses_selected_probability_not_entropy(self):
        metrics = bench.primitive_metrics([record()])['choice']
        self.assertAlmostEqual(metrics['ece']['ece'], 0.4)

    def test_failed_cases_remain_in_accuracy_denominator(self):
        failed = dict(record(), case_id='two', ok=False, schema_ok=False, prediction=None)
        self.assertEqual(bench.primitive_metrics([record(), failed])['choice']['accuracy'], 0.5)

    def test_invalid_probabilities_rejected(self):
        def response(answer):
            return {'model': 'fixture', 'usage': {'input_tokens': 1, 'output_tokens': 0},
                    'answers': {'q': answer}}
        for value in [float('nan'), float('inf'), -0.1, 1.1, True]:
            self.assertFalse(bench.extract(case('noul'), response({'type': 'noul', 'noul': value}))[1])
        self.assertTrue(bench.extract(case('noul'), response({'type': 'noul', 'noul': 0.6}))[1])
        self.assertFalse(bench.extract(case(), response({'type': 'choice', 'confidence': 0,
            'choice': 'other', 'probabilities': {'yes': 0.5, 'no': 0.5}}))[1])

    def test_multiple_questions_cannot_be_silently_dropped(self):
        c = case()
        c['questions']['second'] = c['questions']['q']
        c['expected']['second'] = 'yes'
        with self.assertRaises(ValueError):
            bench.validate_cases([c])

    def test_different_inputs_cannot_be_paired(self):
        with self.assertRaises(ValueError):
            bench.paired_compare([record()], [dict(record(), input_hash='different')], 0)

    def test_adapter_requires_semantic_label_match(self):
        root = Path(__file__).resolve().parents[1]
        with self.assertRaises(ValueError):
            bench.adapt_dataset(root / 'data/merge-risk.jsonl', root / 'packs/merge-risk.json',
                                'irreversible_path')

    def test_invalid_repetitions_rejected(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            bench.parse_args(['--repetitions', '0'])

    def test_request_errors_block_adoption(self):
        r = record()
        broken = dict(r, ok=False, schema_ok=False, prediction=None)
        result = bench.verdict(bench.compute_metrics([r]), bench.compute_metrics([broken]),
                               [r], [broken], [], 0, 30, True)
        self.assertEqual(result['status'], 'FAIL')

    def test_score_ece_uses_modal_level_not_fractional_mean(self):
        r = dict(record(), primitive='score', expected=1, prediction=0.8,
                 raw_answer={'answers': {'q': {'score': 0.8, 'confidence': 0.2,
                    'probabilities': {'0': 0.2, '1': 0.8}}}})
        self.assertAlmostEqual(bench.primitive_metrics([r])['score']['ece']['ece'], 0.2)

    def test_reference_override_cannot_be_applied_to_all_providers(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            bench.parse_args(['--checkpoint', 'aac6fef/laya-mlx'])


if __name__ == '__main__':
    unittest.main()
