from pathlib import Path
from .local_sandbox import LocalAdapter


def make_adapter(config: dict):
    defaults = {'python': str(Path.home() / '.local/scratch/local-classifier-pilot-20261001/venv/bin/python'),
                'model_dir': None, 'connect_timeout': 5}
    defaults.update(config)
    defaults.update(model='network-control', revision='1', backend='control_network')
    return LocalAdapter('control_network', 'network-control', '1', 'control_network_worker.py', defaults)
