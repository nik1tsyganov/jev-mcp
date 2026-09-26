"""Optional per-machine path registry: a flat key -> absolute path map in
~/.config/machine-paths/paths.json. A machine without it (or without the key) gets the
home-relative fallback, so a fresh clone keeps working."""
import json
import os


def path_of(key, fallback):
    """Absolute path for `key`, else `fallback` joined to the home directory."""
    try:
        with open(os.path.join(os.path.expanduser("~"), ".config", "machine-paths", "paths.json"), encoding="utf-8") as f:
            value = json.load(f).get(key)
    except (OSError, ValueError, AttributeError):
        value = None
    return value if isinstance(value, str) and value else os.path.join(os.path.expanduser("~"), fallback)
