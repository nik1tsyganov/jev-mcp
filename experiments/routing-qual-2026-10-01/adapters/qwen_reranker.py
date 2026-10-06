from pathlib import Path
from .local_sandbox import LocalAdapter

MODEL = 'Qwen/Qwen3-Reranker-0.6B'
REVISION = 'e61197ed45024b0ed8a2d74b80b4d909f1255473'


def make_adapter(config: dict):
    root = Path.home() / '.local/scratch/local-classifier-pilot-20261001'
    defaults = {'python': str(root / 'venv/bin/python'), 'model_dir': str(root / 'models/qwen'),
                'device': 'mps', 'max_input_tokens': 4096}
    defaults.update(config)
    defaults.update(model=MODEL, revision=REVISION, backend='qwen_reranker')
    return LocalAdapter('qwen_reranker', MODEL, REVISION, 'qwen_reranker_worker.py', defaults)
