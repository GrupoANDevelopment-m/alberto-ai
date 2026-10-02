"""Stub: hermes_cli config."""
def get_hermes_dir():
    from hermes_constants import get_hermes_dir
    return get_hermes_dir()

def cfg_get(key: str, default=None):
    import os
    return os.environ.get(key, default)

def load_config():
    return {}

def get_hermes_home():
    import os
    from pathlib import Path
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))

DEFAULT_CONFIG = {}
