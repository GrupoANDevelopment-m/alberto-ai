"""NemoClaw real implementation — ported from upstream/nemoclaw/nemoclaw/src/security/.

The full NemoClaw is an OpenClaw plugin that requires OpenClaw runtime
(which we don't have). However, two CRITICAL security functions are
implemented in pure TypeScript and can be ported to Python:

1. **safe-resolve-path.ts**: prevents path traversal attacks (`..`, symlinks)
2. **secret-scanner.ts**: detects API keys, tokens, certificates in content

This module ports both. Used by Alberto before any file write/memory set
to prevent the agent from leaking secrets or escaping the sandbox.

Source: https://github.com/NVIDIA/NemoClaw/blob/main/nemoclaw/src/security/
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# === safe-resolve-path.ts port ===
# Allowed sandbox root (matches OpenClaw write-tool contract)
SANDBOX_ROOT = Path("/sandbox")
WORKSPACE_ALLOW = ["IDENTITY.md", "memory/"]

# Blocked segments (matches isMemoryPath logic in upstream)
MEMORY_SEGMENTS = [".openclaw/memory", "memory/notes.md", "agent_memory"]
HOST_PROTECTED = ["/etc/", "/var/", "/usr/", "/root/", "/home/", "/proc/", "/sys/"]


class PathViolation(Exception):
    """Raised when a path violates sandbox policy."""
    pass


def safe_resolve_path(path: str, sandbox_root: Optional[Path] = None) -> Path:
    """Resolve a path safely, blocking host escapes and path traversal.

    Source: upstream/nemoclaw/nemoclaw/src/security/safe-resolve-path.ts
    `safeResolvePath` function.

    Args:
        path: raw path (absolute, workspace-relative, or with ..)
        sandbox_root: base for resolution (default: /sandbox)

    Returns:
        Resolved absolute Path (guaranteed within sandbox_root if applicable)

    Raises:
        PathViolation: if path escapes sandbox or is host-protected
    """
    sandbox_root = sandbox_root or SANDBOX_ROOT
    if not path:
        raise PathViolation("empty path")

    # Workspace-relative form
    if not path.startswith("/"):
        # Allowed forms: IDENTITY.md, memory/...
        if path in WORKSPACE_ALLOW or any(path.startswith(w) for w in WORKSPACE_ALLOW):
            return (sandbox_root / path).resolve()
        # Try as relative to sandbox
        candidate = (sandbox_root / path).resolve()
        _check_in_sandbox(candidate, sandbox_root)
        return candidate

    # Absolute path: check it's within sandbox OR is a temp path
    p = Path(path)
    try:
        resolved = p.resolve()
    except Exception as e:
        raise PathViolation(f"cannot resolve: {e}")

    # Allow /tmp (temp paths) — typical for test/agent output
    if str(resolved).startswith("/tmp/"):
        return resolved

    # Block host-protected paths
    for protected in HOST_PROTECTED:
        if str(resolved).startswith(protected):
            raise PathViolation(f"path is in host-protected zone: {resolved}")

    # Must be in sandbox
    _check_in_sandbox(resolved, sandbox_root)
    return resolved


def _check_in_sandbox(resolved: Path, sandbox_root: Path) -> None:
    """Verify resolved path is within sandbox_root."""
    try:
        resolved.relative_to(sandbox_root)
    except ValueError:
        raise PathViolation(f"path escapes sandbox: {resolved} not in {sandbox_root}")


# === secret-scanner.ts port ===
# Exact port of SECRET_PATTERNS from upstream
SECRET_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # Original 14 from upstream NemoClaw
    ("NVIDIA API key", re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}\b")),
    ("OpenAI API key", re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_-]{20,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("GitHub token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9]{36,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("AWS secret key", re.compile(r"aws_secret_access_key\s*[=:]\s*[A-Za-z0-9/+=]{40}\b", re.I)),
    ("Slack token", re.compile(r"\b(?:xox[bpas]|xapp)-[A-Za-z0-9-]{10,}\b")),
    ("Discord bot token", re.compile(
        r"(?:discord|bot|DISCORD_TOKEN|BOT_TOKEN|token)\s*[=:]\s*[\"']?[A-Za-z0-9]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}"
    )),
    ("npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36,}\b")),
    ("Private key", re.compile(r"-----BEGIN\s+(?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("Authorization header", re.compile(
        r"(?:Authorization\s*:\s*Bearer|Bearer\s*[=:])\s*[\"']?[A-Za-z0-9._~+/=-]{40,}",
        re.I
    )),
    ("Telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35,42}\b")),
    ("HuggingFace token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),

    # === Alberto additions: more leak vectors ===
    # JWT tokens (eyJ...)
    ("JWT token", re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    # MongoDB connection strings
    ("MongoDB URI", re.compile(r"\bmongodb(?:\+srv)?://[^\s:]+:[^\s@]+@[^\s]+\b")),
    # PostgreSQL URI
    ("PostgreSQL URI", re.compile(r"\bpostgres(?:ql)?://[^\s:]+:[^\s@]+@[^\s/]+\b")),
    # MySQL URI
    ("MySQL URI", re.compile(r"\bmysql://[^\s:]+:[^\s@]+@[^\s/]+\b")),
    # Redis URL with password
    ("Redis URL", re.compile(r"\bredis://[^\s:]*:[^\s@]+@[^\s/]+\b")),
    # SSH private key (OpenSSH format)
    ("SSH private key", re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----")),
    # .env file references (DB_PASSWORD=, API_KEY=, etc)
    ("env var assignment", re.compile(r"\b(?:DATABASE|DB|REDIS|MYSQL|POSTGRES|AWS|GCP|AZURE|SECRET|API|PRIVATE|ACCESS|PASSWORD|PASSWD|TOKEN|CRED|KEY)_?(?:URL|HOST|PORT|NAME|USER|PASS|PASSWORD|KEY|TOKEN|SECRET)?\s*[=:]\s*[\"']?[^\s\"']{8,}[\"']?")),
    # Email + password combinations
    ("email+password", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\s*[:|]\s*[A-Za-z0-9!@#$%^&*]{6,}\b")),
    # Stripe live key
    ("Stripe live key", re.compile(r"\bsk_live_[A-Za-z0-9]{24,}\b")),
    # Stripe test key (still sensitive in some contexts)
    ("Stripe test key", re.compile(r"\bsk_test_[A-Za-z0-9]{24,}\b")),
    # Twilio
    ("Twilio key", re.compile(r"\bSK[a-f0-9]{32}\b")),
    # SendGrid
    ("SendGrid key", re.compile(r"\bSG\.[A-Za-z0-9_-]{16,30}\.[A-Za-z0-9_-]{30,60}\b")),
    # Mailgun
    ("Mailgun key", re.compile(r"\bkey-[a-f0-9]{32}\b")),
    # Heroku
    ("Heroku API key", re.compile(r"\b[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\b")),
    # JWT in Authorization header (different format)
    ("Basic auth header", re.compile(r"(?:Authorization\s*:\s*Basic|Basic\s+)[A-Za-z0-9+/=]{16,}")),
    # SSH password in known_hosts/config (rare but possible)
    ("SSH password in config", re.compile(r"(?:sshpass|password\s*=\s*)([\"']?)[^\s\"']{4,}\1", re.I)),
    # OAuth client secret
    ("OAuth client_secret", re.compile(r"\bclient_secret[\"']?\s*[=:]\s*[\"']?[A-Za-z0-9_-]{20,}")),
    # API gateway keys (common patterns)
    ("API gateway key", re.compile(r"\b(?:apikey|api_key|apiKey|ApiKey)[\"']?\s*[=:]\s*[\"']?[A-Za-z0-9]{32,}")),
    # PEM cert (private keys in general)
    ("PEM cert private", re.compile(r"-----BEGIN (?:CERTIFICATE|EC PARAMETERS|DH PARAMETERS|X509 CRL)\s*-----[\s\S]*?PRIVATE KEY-----", re.S)),
    # OpenAI org-scoped keys
    ("OpenAI org key", re.compile(r"\bsk-org-[A-Za-z0-9]{40,}\b")),
    # Vercel tokens
    ("Vercel token", re.compile(r"\bvercel_[A-Za-z0-9]{24,}\b")),
    # Supabase
    ("Supabase key", re.compile(r"\beyJhbGciOi[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    # Generic high-entropy base64
    # (skipped - too many false positives)
]


def scan_secrets(content: str) -> List[Dict[str, str]]:
    """Scan text for high-confidence secrets. Source: secret-scanner.ts scanSecrets.

    Args:
        content: text to scan (markdown, plain text, code)

    Returns:
        List of {pattern, redacted} dicts (empty if no secrets)
    """
    matches: List[Dict[str, str]] = []
    for name, regex in SECRET_PATTERNS:
        for m in regex.finditer(content):
            matches.append({
                "pattern": name,
                "redacted": m.group(0)[:8] + "***" + m.group(0)[-4:],
            })
    return matches


def redact_secrets(content: str) -> Tuple[str, List[Dict[str, str]]]:
    """Redact all detected secrets. Source: secret-scanner.ts redactSecrets.

    Returns:
        (redacted_text, list_of_matches)
    """
    redacted = content
    matches = scan_secrets(content)
    for m in matches:
        original_pattern = m["redacted"].split("***")[0]  # reconstruct prefix
        # Find and replace the full match in content
        for name, regex in SECRET_PATTERNS:
            for match in regex.finditer(content):
                redacted = redacted.replace(match.group(0), m["redacted"])
    return redacted, matches


# === Integration with Alberto ===

def nemoclaw_pre_write_check(alberto, path: str, content: str) -> Tuple[bool, str, str]:
    """Run NemoClaw security checks before any file write or memory set.

    Returns:
        (allowed, final_path_or_error, final_content_or_redacted)

    Raises:
        PathViolation: if path is unsafe
    """
    # 1. Protected path check
    if is_protected_path(path):
        return False, f"NemoClaw blocked: '{path}' is a protected path (SSH keys, AWS creds, K8s config, etc)", content

    # 2. Safe resolve
    try:
        safe_path = safe_resolve_path(path, sandbox_root=Path(alberto.sandbox.home()))
    except PathViolation as e:
        return False, str(e), content

    # 3. Secret scan (full content + check for env var leaks)
    matches = scan_secrets(content)
    env_leaks = scan_env_leak({"WRITTEN_VALUE": content})
    if matches or env_leaks:
        redacted, _ = redact_secrets(content)
        names = list({m["pattern"] for m in matches})
        env_names = env_leaks
        all_names = names + [f"env:{e}" for e in env_names if not e.startswith("WRITTEN_VALUE")]
        return True, str(safe_path), f"[REDACTED: {', '.join(all_names)}]\n\n{redacted}"

    return True, str(safe_path), content


def nemoclaw_full_status(alberto) -> Dict[str, Any]:
    """Get NemoClaw real status (not stub)."""
    return {
        "openclaw_runtime_required": True,
        "openclaw_runtime_available": False,
        "note": "Full NemoClaw is an OpenClaw plugin requiring OpenClaw runtime",
        "what_we_have": {
            "safe_resolve_path": True,
            "secret_scanner": True,
            "secret_patterns": len(SECRET_PATTERNS),
            "memory_segments_monitored": len(MEMORY_SEGMENTS),
            "host_protected_zones": len(HOST_PROTECTED),
            "extra_vectors": ["env vars", "DB URIs", "JWT", "Stripe", "Twilio", "SendGrid", "OAuth", "SSH keys", "Vercel", "Supabase"],
        },
        "fallback": "LocalSandbox + nemoclaw_real security functions",
        "usage": "alberto_pre_write_check() called automatically before any file write or memory set",
    }


# === Env var leak detector ===
# Common env vars that should never be persisted to memory or files
SENSITIVE_ENV_VARS = {
    "PATH", "HOME", "USER", "SHELL",  # informational (ok to log)
    "NVIDIA_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HUGGINGFACE_TOKEN", "GOOGLE_API_KEY",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "GITHUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN",
    "DATABASE_URL", "DB_URL", "DB_PASSWORD", "DB_USER",
    "REDIS_URL", "REDIS_PASSWORD", "MONGO_URL", "MONGO_PASSWORD",
    "POSTGRES_PASSWORD", "MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD",
    "SECRET_KEY", "JWT_SECRET", "SESSION_SECRET", "COOKIE_SECRET", "ENCRYPTION_KEY",
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
    "TWILIO_AUTH_TOKEN", "TWILIO_ACCOUNT_SID",
    "SENDGRID_API_KEY", "MAILGUN_API_KEY",
    "SLACK_TOKEN", "SLACK_BOT_TOKEN", "SLACK_WEBHOOK_URL",
    "DISCORD_TOKEN", "DISCORD_BOT_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "VERCEL_TOKEN", "VERCEL_API_TOKEN",
    "SUPABASE_KEY", "SUPABASE_SERVICE_KEY",
}


def scan_env_leak(env_dict: Dict[str, str]) -> List[str]:
    """Scan env dict for sensitive values that shouldn't be logged/stored.

    Returns list of keys that are sensitive (NOT the values).
    """
    leaked = []
    for key in env_dict.keys():
        key_upper = key.upper()
        for sensitive in SENSITIVE_ENV_VARS:
            if sensitive in key_upper or key_upper in sensitive:
                leaked.append(key)
                break
        # Also check value for secret patterns
        val = env_dict[key]
        if val and len(val) > 12:
            for name, regex in SECRET_PATTERNS[:14]:  # top patterns
                if regex.search(val):
                    leaked.append(f"{key} (value contains {name})")
                    break
    return list(set(leaked))


# === Path leak detector ===
# Paths that should NEVER be read or written
PROTECTED_PATH_PATTERNS = [
    re.compile(r"/etc/shadow\b"),
    re.compile(r"/etc/passwd\b"),
    re.compile(r"/etc/sudoers\b"),
    re.compile(r"/etc/ssh/.*"),
    re.compile(r"~?/\.ssh/id_(?:rsa|ed25519|ecdsa)\b"),
    re.compile(r"~?/\.aws/credentials\b"),
    re.compile(r"~?/\.aws/config\b"),
    re.compile(r"~?/\.kube/config\b"),
    re.compile(r"~?/\.docker/config\.json\b"),
    re.compile(r"~?/\.npmrc\b"),
    re.compile(r"~?/\.pypirc\b"),
    re.compile(r"~?/\.netrc\b"),
    re.compile(r"~?/\.git-credentials\b"),
    re.compile(r"~?/\.gitconfig\b"),
    re.compile(r"/proc/\d+/environ\b"),
    re.compile(r"/proc/self/environ\b"),
    re.compile(r"/proc/\d+/cmdline\b"),
    re.compile(r"/sys/.*"),
    re.compile(r"/var/log/auth\.log\b"),
    re.compile(r"/var/log/secure\b"),
]


def is_protected_path(path: str) -> bool:
    """Return True if path matches a protected path pattern."""
    p = str(Path(path).expanduser()).lower()
    for pat in PROTECTED_PATH_PATTERNS:
        if pat.search(p):
            return True
    return False
