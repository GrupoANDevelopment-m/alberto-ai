"""Stub: file safety checks."""
from pathlib import Path

PROTECTED_PATHS = ["/etc", "/root/.ssh", "/proc", "/sys", "/var/log"]

def is_protected(path: str) -> bool:
    p = Path(path).expanduser().resolve()
    for prot in PROTECTED_PATHS:
        prot_p = Path(prot).resolve()
        try:
            p.relative_to(prot_p)
            return True
        except ValueError:
            continue
    return False

def get_read_block_error(path: str) -> str:
    return f"blocked: {path} is protected"

def build_write_denied_paths() -> list:
    return ["/etc", "/var", "/boot", "/proc", "/sys"]
