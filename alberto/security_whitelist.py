"""security_whitelist.py - Alberto AI Security Whitelist (v1.7).

Provides validation for commands emitted by LLM via "Comando:" interceptor
and limits which alberto subcommands can be executed.
"""
from __future__ import annotations
import re
from typing import Tuple


ALBERTO_SAFE_SUBCOMMANDS = {
    "banner", "status", "tools", "tool", "skill", "skills",
    "model", "models", "router", "fallback",
    "memory-list", "memory-get", "memory-search",
    "auto-invoke", "skill-show",
    "security", "security-scan", "security-path", "security-patterns",
    "vision",
    "squad", "squad-list", "squad-describe",
    "hermes", "hermes-list",
    "meta", "meta-status",
    "s", "s-list",
    "strategy",
    "--help", "-h",
}

ALBERTO_REQUIRE_CONFIRMATION = {
    "squad-activate", "squad-hibernate", "squad-run",
    "s-add", "s-remove",
    "memory-set", "memory-delete",
    "model-set", "model-test",
    "install",
    "app",
    "test",
    "heal",
    "learn",
    "research",
    "loop",
}

ALBERTO_NEVER_AUTORUN = {
    "serve", "serve-stop",
    "system",
}

BLOCKED_CMD_PATTERNS = [
    (r"\$\s*\(", "shell variable expansion $()"),
    (r"`", "backtick command substitution"),
    (r"\brm\s+-rf\s+/", "destructive rm -rf /"),
    (r"\brm\s+-rf\s+~", "destructive rm -rf home"),
    (r"\bmkfs\b", "mkfs (filesystem format)"),
    (r"\bdd\s+if=/dev/(zero|urandom|random)", "dd write to device"),
    (r"\bcurl\s+[^|]+\|\s*(sh|bash)\b", "curl piped to shell"),
    (r"\bwget\s+[^|]+\|\s*(sh|bash)\b", "wget piped to shell"),
    (r"\bchmod\s+777\s+/", "chmod 777 root"),
    (r"\bchown\s+-R\s+.*\s+/(\s|$)", "chown -R /"),
    (r">\s*/dev/sd[a-z]", "write to disk device"),
    (r"\bshutdown\b", "shutdown command"),
    (r"\breboot\b", "reboot command"),
    (r"\bsystemctl\s+disable", "systemctl disable"),
    (r"\buserdel\b", "userdel"),
    (r"\bpasswd\b", "passwd command"),
    (r"/etc/", "write to /etc/"),
    (r"~?/\.ssh/", "access .ssh/"),
    (r"~?/\.aws/", "access .aws/credentials"),
]


def validate_alberto_subcommand(cmd_str: str) -> Tuple[bool, str]:
    """Validate that a 'Comando: alberto X Y Z' string is safe to auto-execute."""
    cmd_str = cmd_str.strip()
    if not cmd_str:
        return False, "Empty command"
    tokens = cmd_str.split(None, 1)
    if not tokens:
        return False, "Empty"
    subcommand = tokens[0]
    for pattern, desc in BLOCKED_CMD_PATTERNS:
        if re.search(pattern, cmd_str, re.IGNORECASE):
            return False, f"Blocked pattern: {desc}"
    if subcommand in ALBERTO_NEVER_AUTORUN:
        return False, f"Subcommand '{subcommand}' is never auto-executable (security)"
    if subcommand in ALBERTO_REQUIRE_CONFIRMATION:
        return False, (
            f"Subcommand '{subcommand}' requires explicit user confirmation. "
            f"Ask: 'Type yes to run {cmd_str[:50]}'"
        )
    if subcommand in ALBERTO_SAFE_SUBCOMMANDS:
        return True, ""
    return False, (
        f"Unknown subcommand '{subcommand}'. "
        f"Run `alberto {subcommand}` manually to see if it exists."
    )


def list_safe_subcommands() -> list:
    return sorted(ALBERTO_SAFE_SUBCOMMANDS)


def list_confirmation_subcommands() -> list:
    return sorted(ALBERTO_REQUIRE_CONFIRMATION)


def list_blocked_subcommands() -> list:
    return sorted(ALBERTO_NEVER_AUTORUN)
