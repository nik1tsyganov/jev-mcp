from pathlib import Path
from .local_sandbox import LocalAdapter

MODEL = 'Mapika/decider-2b'
REVISION = '533964dae8be954c5b5e19fa4948e48408094c1e'


def make_adapter(config: dict):
    root = Path.home() / '.local/scratch/local-classifier-pilot-20261001'
    defaults = {'python': str(root / 'venv/bin/python'), 'model_dir': str(root / 'models/decider'),
                'device': 'mps', 'max_input_tokens': 4096}
    defaults.update(config)
    defaults.update(model=MODEL, revision=REVISION, backend='decider')
    return LocalAdapter('decider', MODEL, REVISION, 'decider_worker.py', defaults)
