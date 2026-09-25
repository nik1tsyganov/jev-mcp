import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import laya_worker as worker


class FakeTokenizer:
    mask_token = "[MASK]"

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": list(range(len(text)))}


def fake_build_sequence(tok, state, q, max_len, head_max_len):
    """Emulate build_sequence's length truncation without the MLX package."""
    ids = list(range(len(str(state)) + 10))
    return ids[:max_len], [0]


def fake_render_options(q):
    return [q.get("ins", "")]


class FakeRuntime:
    def __init__(self, script="latin", raw=None):
        self.tok = FakeTokenizer()
        self.max_len = 512
        self.head_max_len = 192
        self.language = "en"
        self.checkpoint = "aac6fef/laya-mlx"
        self.revision = "047678560251f28113ee8f5df4be82102c7bf336"
        self.device_label = "gpu"
        self.dtype_label = "float16"
        self.model_dir = "/model"
        self.calls = 0
        self._script = script
        self._raw = raw

    def to_internal(self, definition):
        return {"t": definition["type"], "ins": definition["instructions"], "crit": definition.get("criteria")}

    def analyse(self, state):
        return {"script": self._script, "is_english": self._script in ("latin", "unknown")}

    def synchronize(self):
        pass

    def predict(self, state, questions):
        self.calls += 1
        if self._raw is not None:
            return self._raw
        answers = {}
        for qid, q in questions.items():
            if q["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": 0.6, "confidence": 0.6}
            elif q["type"] == "choice":
                answers[qid] = {"type": "choice", "choice": "yes", "confidence": 0.9,
                                "probabilities": {"yes": 0.9, "no": 0.1}}
            else:
                answers[qid] = {"type": "score", "score": 1.0, "confidence": 0.5,
                                "legend": {"0": "a", "1": "b"}, "probabilities": {"0": 0.4, "1": 0.6}}
        return {"model": "laya-rl-agent", "answers": answers,
                "usage": {"input_tokens": 1, "output_tokens": 0}}


def make_checkpoint(root, name, revision=None, manifest=False):
    directory = root / name
    (directory / "encoder").mkdir(parents=True)
    (directory / "tokenizer").mkdir()
    for relative in ("model.safetensors", "rl_agent_config.json",
                     "encoder/config.json", "tokenizer/tokenizer.json"):
        (directory / relative).write_text("{}")
    if manifest:
        (directory / "laya-identity.json").write_text(json.dumps({"revision": revision}))
    return directory


class ConfigTests(unittest.TestCase):
    def test_missing_directory_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(worker.WorkerError) as ctx:
                worker.resolve_model_dir(Path(tmp) / "absent", "rev")
        self.assertEqual(ctx.exception.code, "checkpoint_missing")

    def test_incomplete_checkpoint_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = make_checkpoint(Path(tmp), "rev")
            (directory / "model.safetensors").unlink()
            with self.assertRaises(worker.WorkerError) as ctx:
                worker.resolve_model_dir(directory, "rev")
        self.assertEqual(ctx.exception.code, "checkpoint_incomplete")

    def test_revision_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = make_checkpoint(Path(tmp), "snapshot-abc")
            with self.assertRaises(worker.WorkerError) as ctx:
                worker.resolve_model_dir(directory, "04767856")
        self.assertEqual(ctx.exception.code, "revision_mismatch")

    def test_revision_path_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = make_checkpoint(Path(tmp), "04767856")
            self.assertEqual(worker.resolve_model_dir(directory, "04767856"), directory)

    def test_identity_manifest_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = make_checkpoint(Path(tmp), "model", revision="04767856", manifest=True)
            self.assertEqual(worker.resolve_model_dir(directory, "04767856"), directory)

    def test_credentials_are_scrubbed(self):
        os.environ["HF_TOKEN"] = "hf_secret"
        os.environ["TYPESAFE_API_KEY"] = "sk-secret"
        try:
            worker.scrub_credentials()
            self.assertNotIn("HF_TOKEN", os.environ)
            self.assertNotIn("TYPESAFE_API_KEY", os.environ)
        finally:
            os.environ.pop("HF_TOKEN", None)
            os.environ.pop("TYPESAFE_API_KEY", None)

    def test_offline_settings_are_forced(self):
        previous = os.environ.get("HF_HUB_OFFLINE")
        try:
            worker.enforce_offline()
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
            self.assertEqual(os.environ["TRANSFORMERS_OFFLINE"], "1")
        finally:
            if previous is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = previous


class RedactionTests(unittest.TestCase):
    def test_redact_hides_credentials(self):
        out = worker.redact("failed with hf_abcdefghijklmnop and Bearer abc.def token=xyz")
        self.assertNotIn("hf_abcdefghijklmnop", out)
        self.assertIn("[redacted]", out)

    def test_redact_caps_length(self):
        self.assertLessEqual(len(worker.redact("x" * 1000)), 500)


class TruncationTests(unittest.TestCase):
    def setUp(self):
        worker.build_sequence = fake_build_sequence
        worker.render_options = fake_render_options

    def tearDown(self):
        worker.build_sequence = None
        worker.render_options = None

    def test_untruncated_input_is_accepted(self):
        self.assertIsNone(worker.check_no_truncation(FakeTokenizer(), {"ins": "Is it?"}, "short", 512, 192))

    def test_state_truncation_is_rejected(self):
        reason = worker.check_no_truncation(FakeTokenizer(), {"ins": "Is it?"}, "a much longer state", 5, 192)
        self.assertIsNotNone(reason)

    def test_option_over_budget_is_rejected(self):
        reason = worker.check_no_truncation(FakeTokenizer(), {"ins": "x" * 60}, "", 512, 192)
        self.assertIsNotNone(reason)


class AnswerValidationTests(unittest.TestCase):
    def test_valid_choice_answer(self):
        definition = {"type": "choice", "criteria": {"yes": "y", "no": "n"}}
        worker.validate_answer("q", definition, {"type": "choice", "choice": "yes", "confidence": 0.9,
                                                "probabilities": {"yes": 0.9, "no": 0.1}})

    def test_invalid_selected_label_is_rejected(self):
        definition = {"type": "choice", "criteria": {"yes": "y", "no": "n"}}
        with self.assertRaises(worker.WorkerError):
            worker.validate_answer("q", definition, {"type": "choice", "choice": "other", "confidence": 0.9,
                                                     "probabilities": {"yes": 0.9, "no": 0.1}})

    def test_distribution_must_cover_labels(self):
        definition = {"type": "choice", "criteria": {"yes": "y", "no": "n"}}
        with self.assertRaises(worker.WorkerError):
            worker.validate_answer("q", definition, {"type": "choice", "choice": "yes", "confidence": 0.9,
                                                     "probabilities": {"yes": 1.0}})

    def test_non_finite_probability_is_rejected(self):
        definition = {"type": "noul", "criteria": None}
        with self.assertRaises(worker.WorkerError):
            worker.validate_answer("q", definition, {"type": "noul", "noul": math.nan, "confidence": 0.5})

    def test_score_out_of_range_is_rejected(self):
        definition = {"type": "score", "criteria": ["a", "b"]}
        with self.assertRaises(worker.WorkerError):
            worker.validate_answer("q", definition, {"type": "score", "score": 2.0, "confidence": 0.5,
                                                     "legend": {"0": "a", "1": "b"},
                                                     "probabilities": {"0": 0.4, "1": 0.6}})

    def test_missing_confidence_is_rejected(self):
        definition = {"type": "noul", "criteria": None}
        with self.assertRaises(worker.WorkerError):
            worker.validate_answer("q", definition, {"type": "noul", "noul": 0.6})


class HandlePredictTests(unittest.TestCase):
    def setUp(self):
        worker.build_sequence = fake_build_sequence
        worker.render_options = fake_render_options

    def tearDown(self):
        worker.build_sequence = None
        worker.render_options = None

    def test_result_carries_truthful_identity_and_metadata(self):
        runtime = FakeRuntime()
        result = worker.handle_predict(runtime, "hello", {"q": {"type": "noul", "instructions": "Is it?"}})
        self.assertEqual(result["model"], f"{runtime.checkpoint}@{runtime.revision}")
        self.assertEqual(result["backend"], "laya-mlx")
        self.assertEqual(result["checkpoint"], runtime.checkpoint)
        self.assertEqual(result["revision"], runtime.revision)
        self.assertEqual(result["usage"], {"input_tokens": 1, "output_tokens": 0})
        self.assertIsInstance(result["elapsed_ms"], float)

    def test_non_latin_state_is_rejected_without_inference(self):
        runtime = FakeRuntime(script="han")
        with self.assertRaises(worker.WorkerError) as ctx:
            worker.handle_predict(runtime, "你好", {"q": {"type": "noul", "instructions": "Is it?"}})
        self.assertEqual(ctx.exception.code, "unsupported_language")
        self.assertEqual(runtime.calls, 0)

    def test_empty_questions_are_rejected(self):
        with self.assertRaises(worker.WorkerError) as ctx:
            worker.handle_predict(FakeRuntime(), "s", {})
        self.assertEqual(ctx.exception.code, "invalid_request")

    def test_invalid_output_is_rejected(self):
        raw = {"model": "laya-rl-agent", "answers": {"q": {"type": "noul", "noul": math.nan, "confidence": 0.5}},
               "usage": {"input_tokens": 1, "output_tokens": 0}}
        runtime = FakeRuntime(raw=raw)
        with self.assertRaises(worker.WorkerError) as ctx:
            worker.handle_predict(runtime, "s", {"q": {"type": "noul", "instructions": "Is it?"}})
        self.assertEqual(ctx.exception.code, "invalid_output")

    def test_missing_usage_is_rejected(self):
        raw = {"model": "laya-rl-agent", "answers": {"q": {"type": "noul", "noul": 0.6, "confidence": 0.6}}}
        runtime = FakeRuntime(raw=raw)
        with self.assertRaises(worker.WorkerError) as ctx:
            worker.handle_predict(runtime, "s", {"q": {"type": "noul", "instructions": "Is it?"}})
        self.assertEqual(ctx.exception.code, "invalid_output")

    def test_extra_answers_are_rejected(self):
        raw = {"model": "laya-rl-agent",
               "answers": {"q": {"type": "noul", "noul": 0.6, "confidence": 0.6},
                           "extra": {"type": "noul", "noul": 0.6, "confidence": 0.6}},
               "usage": {"input_tokens": 1, "output_tokens": 0}}
        runtime = FakeRuntime(raw=raw)
        with self.assertRaises(worker.WorkerError) as ctx:
            worker.handle_predict(runtime, "s", {"q": {"type": "noul", "instructions": "Is it?"}})
        self.assertEqual(ctx.exception.code, "invalid_output")


if __name__ == "__main__":
    unittest.main()
