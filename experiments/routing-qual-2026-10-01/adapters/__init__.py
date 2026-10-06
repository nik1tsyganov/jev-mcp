"""Backend modules for the routing qualification benchmark."""

import importlib

NAMES = ["jev", "laya", "qwen_reranker", "decider", "control_network"]


def load(name):
    if name not in NAMES:
        raise ValueError("unknown routing backend")
    return importlib.import_module(f"adapters.{name}")
