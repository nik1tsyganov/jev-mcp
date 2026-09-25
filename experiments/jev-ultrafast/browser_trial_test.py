import io
import json
import unittest
import browser_trial as trial


class TrialTests(unittest.TestCase):
    def test_failed_requests_are_captured(self):
        output = io.StringIO()
        def fail(body):
            raise RuntimeError('provider unavailable')
        capture = trial.Capture(output, {}, fail, 1)
        with self.assertRaises(RuntimeError):
            capture.post_json('endpoint', 'unused', {'state': {}, 'questions': {}})
        row = json.loads(output.getvalue())
        self.assertEqual(capture.count, 1)
        self.assertEqual(row['error'], 'provider unavailable')
        self.assertIsNone(row['response'])
        with self.assertRaisesRegex(RuntimeError, 'cap'):
            capture.post_json('endpoint', 'unused', {})
        self.assertEqual(capture.count, 1)

    def test_completion_does_not_erase_incorrect_actions(self):
        class Browser:
            def evaluate(self, expression):
                return json.dumps({'complete': True, 'selected': 'kestrel',
                                   'errors': [{'type': 'wrong_item'}]})
        class Agent:
            browser = Browser()
        result = trial._verify(Agent(), {'expect': {'selected': 'kestrel'}})
        self.assertTrue(result['completed'])
        self.assertEqual(result['verdict'], 'fail')


if __name__ == '__main__':
    unittest.main()
