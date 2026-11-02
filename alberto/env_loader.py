"""env_loader.py — load credentials from .env into os.environ.

Search order (first hit wins per variable):
  1. $ALBERTO_ENV_FILE if set
  2. ./alberto-ai/.env relative to CWD
  3. package-root/.env (repo checkout)
  4. ~/.alberto/.env

Existing environment variables always win — .env only fills gaps.
Values already present in os.environ are never overwritten.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional

_LOADED = False


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []

    explicit = os.environ.get("ALBERTO_ENV_FILE")
    if explicit:
        paths.append(Path(explicit).expanduser())

    # Package root (repo checkout): alberto/env_loader.py -> parent.parent
    try:
        pkg_root = Path(__file__).resolve().parent.parent
        paths.append(pkg_root / ".env")
    except Exception:
        pass

    paths.append(Path.cwd() / ".env")
    paths.append(Path.home() / ".alberto" / ".env")
    return paths


def _parse_env_file(path: Path) -> dict:
    values: dict = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return values
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            values[key] = val
    return values


def load_env(force: bool = False) -> dict:
    """Load .env into os.environ. Existing env vars are preserved."""
    global _LOADED
    if _LOADED and not force:
        return {}

    loaded: dict = {}
    for path in _candidate_paths():
        if not path.exists() or not path.is_file():
            continue
        for key, val in _parse_env_file(path).items():
            if key not in os.environ:
                os.environ[key] = val
                loaded[key] = val
        break  # first existing file wins

    _LOADED = True
    return loaded


def env_file_path() -> Optional[Path]:
    """Return the .env path that would be used (first existing candidate)."""
    for path in _candidate_paths():
        if path.exists() and path.is_file():
            return path
    return None
