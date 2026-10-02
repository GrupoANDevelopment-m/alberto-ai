"""File safety checks."""
from pathlib import Path

def build_write_denied_prefixes(_=None):
    return ["/etc", "/var", "/boot", "/proc", "/sys", "/dev"]

def build_write_denied_paths(_=None):
    return ["/etc", "/var", "/boot", "/proc", "/sys", "/dev"]

def is_write_denied(path):
    p = Path(path).expanduser()
    for prefix in build_write_denied_prefixes():
        try:
            p.relative_to(prefix)
            return True
        except ValueError:
            continue
    return False

def is_protected(path):
    p = Path(path).expanduser().resolve()
    for prot in ["/etc", "/root/.ssh"]:
        try:
            p.relative_to(prot)
            return True
        except ValueError:
            continue
    return False

def get_read_block_error(path):
    # Real Hermes checks: SSH keys, AWS creds, etc
    sensitive = [".ssh", ".aws", ".gnupg", "credentials.json", ".env", "id_rsa", "id_ed25519"]
    p_str = str(path)
    for s in sensitive:
        if s in p_str:
            return f"blocked: {path} contains sensitive data ({s})"
    # Also block /etc/passwd, /etc/shadow
    if "/etc/passwd" in p_str or "/etc/shadow" in p_str:
        return f"blocked: {path} is system credential file"
    return None
