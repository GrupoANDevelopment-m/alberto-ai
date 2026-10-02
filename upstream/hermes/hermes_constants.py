"""Stub: minimal hermes_constants for upstream tools that need it."""
import os
from pathlib import Path

def get_hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

def get_hermes_dir() -> Path:
    return get_hermes_home()

def get_default_hermes_root() -> Path:
    return get_hermes_home()

def display_hermes_home() -> str:
    return str(get_hermes_home())

def is_termux() -> bool:
    return False

def apply_subprocess_home_env(env=None):
    """Stub: apply Hermes env vars to subprocess."""
    import os
    if env is None:
        env = os.environ.copy()
    return env

def agent_browser_runnable():
    return False
