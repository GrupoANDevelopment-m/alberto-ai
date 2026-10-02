"""Stub: skill utilities."""
def is_excluded_skill_path(path: str) -> bool:
    return False

EXCLUDED_SKILL_DIRS = [".git", "__pycache__", "node_modules"]

def is_skill_support_path(path):
    from pathlib import Path
    p = Path(path)
    return any(part in EXCLUDED_SKILL_DIRS for part in p.parts)
