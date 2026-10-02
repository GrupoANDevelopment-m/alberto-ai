"""Stub: minimal utils for upstream tools."""
import os
from pathlib import Path

def atomic_replace(path: Path, content: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)

def safe_path(p: str) -> str:
    """Expand ~ and resolve."""
    return str(Path(p).expanduser().resolve())

def env_var_enabled(name: str, default: bool = False) -> bool:
    val = os.environ.get(name, "").lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default

def is_truthy_value(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("1", "true", "yes", "on")
    return bool(val)

def display_path(path) -> str:
    return str(Path(path).expanduser())

def truncate_text(text: str, max_len: int = 1000) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"... (truncated {len(text) - max_len} chars)"

def env_int(name: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default

def env_float(name: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default

def file_signature(path):
    import hashlib
    from pathlib import Path as _P
    p = _P(path)
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()

def base_url_hostname(url):
    from urllib.parse import urlparse
    return urlparse(url).hostname or ""
