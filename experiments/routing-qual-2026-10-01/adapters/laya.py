from pathlib import Path
from .local_sandbox import LocalAdapter

MODEL = 'aac6fef/laya-typed-decisions-mlx'
REVISION = '28416e78cb26a239a4eabaa2e084904ec5e6cacb'


def make_adapter(config: dict):
    root = Path.home() / '.local/scratch/laya-evaluation'
    defaults = {'python': str(root / 'venv/bin/python'),
                'model_dir': str(root / 'hf/hub/models--aac6fef--laya-typed-decisions-mlx/snapshots' / REVISION),
                'device': 'gpu'}
    defaults.update(config)
    defaults.update(model=MODEL, revision=REVISION, backend='laya')
    return LocalAdapter('laya', MODEL, REVISION, 'laya_worker.py', defaults)
