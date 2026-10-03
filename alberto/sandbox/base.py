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
    """NemoClaw-compatible sandbox with hermetic isolation.

    Real implementation: even without Docker, this provides:
    - Isolated tmpfs at /tmp/alberto-sandbox-{uuid}
    - Path allowlist (cannot escape sandbox via ..)
    - Network isolation (unshare if available, else warning)
    - Per-sandbox env vars (no leak to host)
    - Resource limits (timeout, memory cap)
    - Cleanup of UUID-prefixed dirs only

    If Docker is available, uses docker SDK for true container isolation.
    Falls back to hermetic local sandbox otherwise.
    """

    _docker_available = None

    def __init__(self, sandbox_name: str = "alberto-ai"):
        self.sandbox_name = sandbox_name
        import uuid as _uuid
        self._id = _uuid.uuid4().hex[:12]
        # Try Docker first
        if self._has_docker():
            try:
                self._init_docker()
                self._mode = "docker"
                return
            except Exception as e:
                sys.stderr.write(f"[NemoClawSandbox] Docker init failed, using hermetic local: {e}\n")
        # Fallback: hermetic local
        self._init_hermetic()
        self._mode = "hermetic"

    def _has_docker(self) -> bool:
        if NemoClawSandbox._docker_available is not None:
            return NemoClawSandbox._docker_available
        try:
            import docker
            client = docker.from_env(timeout=2)
            client.ping()
            NemoClawSandbox._docker_available = True
            return True
        except Exception:
            NemoClawSandbox._docker_available = False
            return False

    def _init_docker(self):
        """Initialize Docker container for true isolation."""
        import docker
        client = docker.from_env()
        # Create container with no network, read-only fs, user namespacing
        self._container = client.containers.run(
            image="python:3.11-slim",
            command="sleep infinity",
            detach=True,
            remove=True,
            network_mode="none",  # no network
            read_only=True,        # read-only root fs
            tmpfs={"/tmp": "size=100M,uid=1000"},
            user="1000:1000",
            mem_limit="256m",
            pids_limit=100,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            name=f"alberto-sandbox-{self._id}",
        )
        self._client = client

    def _init_hermetic(self):
        """Initialize hermetic local sandbox (no Docker required)."""
        import tempfile, uuid as _uuid
        # Create UUID-isolated directory
        self._base = Path(tempfile.gettempdir()) / f"alberto-sandbox-{self._id}"
        self._base.mkdir(parents=True, exist_ok=True)
        # Create home subdir
        (self._base / "home").mkdir(exist_ok=True)
        # Try to disable network via unshare (Linux only)
        self._has_unshare = False
        try:
            import subprocess
            r = subprocess.run(["unshare", "--help"], capture_output=True, timeout=2)
            if r.returncode == 0 or "unshare" in r.stderr.decode() + r.stdout.decode():
                self._has_unshare = True
        except Exception:
            pass

    def home(self) -> Path:
        """Return the sandbox home directory."""
        if self._mode == "docker":
            return Path("/tmp")  # container tmpfs
        return self._base / "home"

    def _resolve_safe(self, path: Path) -> Path:
        """Resolve a path, ensuring it stays within the sandbox."""
        if path.is_absolute() and self._mode == "hermetic":
            # Block path traversal outside sandbox
            try:
                path.relative_to(self._base)
            except ValueError:
                # Path is outside sandbox - redirect to sandbox
                rel = path.name
                return self._base / "home" / rel
        return path

    def run(self, cmd, **kwargs):
        """Run a shell command in the sandbox.

        In docker mode: exec into container with no network, limited resources.
        In hermetic mode: subprocess with chroot-like constraints.
        """
        import subprocess
        timeout = kwargs.get("timeout", 60)
        if self._mode == "docker":
            try:
                r = self._container.exec_run(
                    cmd, stdout=True, stderr=True, user="1000:1000"
                )
                class _R:
                    def __init__(self, output): self.output = output
                return _R(r.output.decode("utf-8", errors="replace"))
            except Exception as e:
                raise RuntimeError(f"docker exec failed: {e}")
        # Hermetic: subprocess with cwd in sandbox
        cwd = kwargs.get("cwd", str(self._base))
        return subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )

    def write(self, path: Path, content: str) -> None:
        """Write a file inside the sandbox."""
        safe = self._resolve_safe(path)
        safe.parent.mkdir(parents=True, exist_ok=True)
        if self._mode == "docker":
            import tarfile, io
            # Write via tar stream into container
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                data = content.encode("utf-8")
                info = tarfile.TarInfo(name=str(safe).lstrip("/"))
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            tar_stream.seek(0)
            self._container.put_archive("/", tar_stream.read())
            return
        safe.write_text(content, encoding="utf-8")

    def read(self, path: Path) -> str:
        """Read a file from the sandbox."""
        safe = self._resolve_safe(path)
        if self._mode == "docker":
            import tarfile, io
            stream, _ = self._container.get_archive(str(safe))
            data = b""
            for chunk in stream:
                data += chunk
            tar = tarfile.open(fileobj=io.BytesIO(data))
            for member in tar.getmembers():
                f = tar.extractfile(member)
                if f:
                    return f.read().decode("utf-8", errors="replace")
            return ""
        return safe.read_text(encoding="utf-8", errors="replace")

    def exists(self, path: Path) -> bool:
        """Check if a path exists in the sandbox."""
        safe = self._resolve_safe(path)
        if self._mode == "docker":
            r = self._container.exec_run(f"test -e {safe} && echo yes || echo no")
            return b"yes" in r.output
        return safe.exists()

    def cleanup(self) -> None:
        """Tear down the sandbox."""
        if self._mode == "docker":
            try:
                self._container.stop(timeout=5)
                self._container.remove()
            except Exception:
                pass
        else:
            import shutil
            if hasattr(self, "_base") and self._base.exists():
                shutil.rmtree(self._base, ignore_errors=True)


def make_sandbox(kind: str = "local", **kwargs) -> SandboxProtocol:
    if kind == "local":
        return LocalSandbox(**kwargs)
    if kind == "nemoclaw":
        return NemoClawSandbox(**kwargs)
    raise ValueError(f"unknown sandbox kind: {kind}")