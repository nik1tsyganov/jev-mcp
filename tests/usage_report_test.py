import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import usage_report as report


def row(**kw):
    base = {'ts': '2026-09-26T10:00:00Z', 'schema': 2, 'source': 'mcp', 'tool': 'jev_ask',
            'client': 'claude-code@1', 'cwd': '/x/proj', 'pid': 1, 'ok': True, 'error': None,
            'latency_ms': 100, 'model': 'm', 'questions': 1, 'input_tokens': 10, 'output_tokens': 1}
    base.update(kw)
    return base


class UsageReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        spend = os.path.join(self.tmp.name, 'spend.jsonl')
        laya = os.path.join(self.tmp.name, 'laya.jsonl')
        lines = [
            {'ts': '2026-09-19T10:00:00Z', 'model': 'm', 'questions': 1},  # old, before --since
            {'ts': '2026-09-25T10:00:00Z', 'model': 'm', 'questions': 2},  # old, in range: skipped
            row(answers={'answer': {'noul': 0.9}}),
            row(tool='jev_choice', questions=3, latency_ms=300, input_tokens=20),
            row(tool='jev_noul', questions=20, latency_ms=200, input_tokens=30,
                cwd='/x/other', pid=2, client='codex-mcp-client@1'),
            row(ok=False, error='TimeoutError', latency_ms=999, input_tokens=None,
                output_tokens=None, pid=2, cwd='/x/other'),
        ]
        with open(spend, 'w') as fh:
            fh.write('\n'.join(json.dumps(r) for r in lines) + '\n{"torn": \n')
        with open(laya, 'w') as fh:
            for accepted, ms in ((True, 1000), (False, 2000)):
                fh.write(json.dumps({'ts': '2026-09-26T10:00:00Z', 'provider': 'laya',
                                     'profile': 'p', 'accepted': accepted,
                                     'reason': 'ok' if accepted else 'below_threshold',
                                     'durationMs': ms, 'qualificationStatus': 'FAILED'}) + '\n')
        self.env = {k: os.environ.get(k) for k in ('TYPESAFE_SPEND_LOG', 'LAYA_DECISION_LOG')}
        os.environ['TYPESAFE_SPEND_LOG'] = spend
        os.environ['LAYA_DECISION_LOG'] = laya

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_totals_and_skipped_old_rows(self):
        rep = report.build('2026-09-25')
        self.assertEqual(rep['skipped_old_rows'], 1)
        t = rep['totals']
        self.assertEqual((t['requests'], t['questions'], t['input_tokens']), (4, 25, 60))
        self.assertEqual((t['ok_rate_pct'], t['sessions'], t['projects']), (75.0, 2, 2))

    def test_latency_percentiles_use_ok_rows_only(self):
        rep = report.build('2026-09-25')
        proj = {g['name']: g for g in rep['by_project']}
        self.assertEqual((proj['proj']['latency_p50'], proj['proj']['latency_p90']), (100, 300))
        ask = {g['name']: g for g in rep['by_tool']}['jev_ask']
        self.assertEqual((ask['latency_max'], ask['errors']), (100, 1))

    def test_batching_histogram(self):
        self.assertEqual(report.build('2026-09-25')['batching'],
                         {'1': 2, '2-4': 1, '5-16': 0, '17+': 1})

    def test_laya_and_candidate_sites(self):
        rep = report.build('2026-09-25')
        self.assertEqual((rep['laya']['requests'], rep['laya']['accepted_rate_pct']), (2, 50.0))
        self.assertEqual(rep['laya']['duration_p50'], 1000)
        sites = {(s['tool'], s['project']): s for s in rep['candidate_sites']}
        self.assertEqual(len(sites), 4)
        self.assertEqual(sites[('jev_ask', 'proj')]['with_answers'], 1)
        self.assertEqual(sites[('jev_ask', 'other')]['with_answers'], 0)

    def test_missing_logs_exit_zero_with_message(self):
        os.environ['TYPESAFE_SPEND_LOG'] = os.path.join(self.tmp.name, 'none.jsonl')
        os.environ['LAYA_DECISION_LOG'] = os.path.join(self.tmp.name, 'none2.jsonl')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(report.main([]), 0)
        self.assertIn('no schema 2 Jev rows', out.getvalue())


if __name__ == '__main__':
    unittest.main()
