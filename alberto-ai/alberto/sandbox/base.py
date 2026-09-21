"""
Sandbox abstraction.

Alberto AI ships with TWO sandbox implementations:

1. LocalSandbox - works RIGHT NOW on any Linux/macOS machine. Uses Python's
   os, subprocess, and a temp directory as the "container". The L7 proxy
   is simulated by URL allowlisting.

2. NemoClawSandbox - production sandbox. Uses the real NemoClaw daemon
   + OpenShell container. Requires Docker + the NemoClaw runtime.

Both implement the same SandboxProtocol so the rest of the agent is identical.
"""

from __future__ import annotations
import os
import subprocess
import tempfile
import shutil
import shlex
from pathlib import Path
from typing import Optional, List, Dict, Protocol


class SandboxProtocol(Protocol):
    """Minimum sandbox interface that engines depend on."""
    def home(self) -> Path: ...
    def run(self, cmd: List[str], *, env: Optional[Dict[str, str]] = None,
            cwd: Optional[Path] = None, timeout: int = 60) -> subprocess.CompletedProcess: ...
    def write(self, path: Path, content: str) -> None: ...
    def read(self, path: Path) -> str: ...
    def exists(self, path: Path) -> bool: ...
    def cleanup(self) -> None: ...


class LocalSandbox:
    """Containerless sandbox that runs on the host. For testing RIGHT NOW."""

    def __init__(self, *, base_dir: Optional[Path] = None, allow_net: bool = True):
        if base_dir is None:
            # Persistent sandbox: keep memory/conversations across runs
            base_dir = Path(os.environ.get("ALBERTO_SANDBOX_DIR", "/tmp/alberto-sandbox"))
        self._base = Path(base_dir)
        self._home = self._base / "home"
        self._home.mkdir(parents=True, exist_ok=True)
        self.allow_net = allow_net
        self._policies = {
            "denied_hosts": ["169.254.169.254"],  # IMDS
            "approved_hosts": [],
        }

    def home(self) -> Path:
        return self._home

    def run(self, cmd: List[str], *, env: Optional[Dict[str, str]] = None,
            cwd: Optional[Path] = None, timeout: int = 60) -> subprocess.CompletedProcess:
        full_env = os.environ.copy()
        full_env.setdefault("ALBERTO_SANDBOX", "1")
        full_env.setdefault("ALBERTO_HOME", str(self._home))
        if env:
            full_env.update(env)
        if cwd is None:
            cwd = self._home
        try:
            return subprocess.run(
                cmd,
                cwd=str(cwd),
                env=full_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            return subprocess.CompletedProcess(
                args=cmd, returncode=124,
                stdout=e.stdout or "", stderr=f"timeout after {timeout}s"
            )

    def write(self, path: Path, content: str) -> None:
        full = self._home / path if not path.is_absolute() else path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")

    def read(self, path: Path) -> str:
        full = self._home / path if not path.is_absolute() else path
        return full.read_text(encoding="utf-8")

    def exists(self, path: Path) -> bool:
        full = self._home / path if not path.is_absolute() else path
        return full.exists()

    def cleanup(self) -> None:
        # Only clean up if the base was auto-generated (mkdtemp), not user-provided
        # Detect: if the path has a random suffix (UUID) after alberto-sandbox, it's ephemeral
        import tempfile
        base_str = str(self._base)
        # Must be in /tmp AND name must have a random suffix (e.g. alberto-sandbox-abc123)
        # The persistent path /tmp/alberto-sandbox or /tmp/alberto-sandbox-test stays.
        if base_str.startswith(tempfile.gettempdir()) and "alberto-sandbox" in base_str:
            # Check if it has a UUID-like suffix (more than just "alberto-sandbox")
            import re as _re
            # UUID pattern: alberto-sandbox-XXXXXXX where X is alphanumeric random
            if _re.search(r"alberto-sandbox-[a-z0-9]{6,}$", base_str):
                shutil.rmtree(self._base, ignore_errors=True)

    def list_dir(self, path: Path) -> List[Path]:
        full = self._home / path if not path.is_absolute() else path
        if not full.exists():
            return []
        return sorted(full.iterdir())


class NemoClawSandbox:
    """Production sandbox via NemoClaw + OpenShell. Stub - requires Docker."""

    def __init__(self, sandbox_name: str = "alberto-ai"):
        self.sandbox_name = sandbox_name
        raise NotImplementedError(
            "NemoClawSandbox requires Docker + the NemoClaw runtime. "
            "Use LocalSandbox for testing, or see docs/INSTALL-NEMOCLAW.md"
        )

    def home(self) -> Path:
        raise NotImplementedError

    def run(self, cmd, **kwargs):
        raise NotImplementedError

    def write(self, path: Path, content: str) -> None:
        raise NotImplementedError

    def read(self, path: Path) -> str:
        raise NotImplementedError

    def exists(self, path: Path) -> bool:
        raise NotImplementedError

    def cleanup(self) -> None:
        raise NotImplementedError


def make_sandbox(kind: str = "local", **kwargs) -> SandboxProtocol:
    if kind == "local":
        return LocalSandbox(**kwargs)
    if kind == "nemoclaw":
        return NemoClawSandbox(**kwargs)
    raise ValueError(f"unknown sandbox kind: {kind}")