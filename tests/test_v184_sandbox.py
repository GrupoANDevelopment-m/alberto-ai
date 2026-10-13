"""test_v184_sandbox.py - Real sandbox tests (Local + NemoClaw)."""
import os
import pytest
from pathlib import Path


class TestLocalSandbox:
    def test_local_sandbox_works(self):
        from alberto.sandbox.base import LocalSandbox
        sb = LocalSandbox()
        test_file = sb.home() / "test.txt"
        sb.write(test_file, "Hello LocalSandbox")
        assert sb.read(test_file) == "Hello LocalSandbox"
        assert sb.exists(test_file)
        sb.cleanup()

    def test_local_sandbox_run(self):
        from alberto.sandbox.base import LocalSandbox
        sb = LocalSandbox()
        r = sb.run(["echo", "hello-from-local"])
        assert "hello-from-local" in r.stdout
        sb.cleanup()


class TestNemoClawSandbox:
    """NemoClaw sandbox now real (was stub)."""

    def test_nemoclaw_creates_real_sandbox(self):
        from alberto.sandbox.base import NemoClawSandbox
        sb = NemoClawSandbox("test1")
        # Host fallback is explicitly not treated as an OS security boundary.
        assert sb._mode in ("docker", "host-fallback")
        assert sb.isolation_level in ("docker-container", "host-process")
        assert sb.home().exists()
        sb.cleanup()

    def test_nemoclaw_write_read(self):
        from alberto.sandbox.base import NemoClawSandbox
        sb = NemoClawSandbox("test2")
        f = sb.home() / "data.txt"
        sb.write(f, "nemoclaw-data")
        assert sb.read(f) == "nemoclaw-data"
        assert sb.exists(f)
        sb.cleanup()

    def test_nemoclaw_run_command(self):
        from alberto.sandbox.base import NemoClawSandbox
        sb = NemoClawSandbox("test3")
        r = sb.run("echo from-nemoclaw")
        assert "from-nemoclaw" in r.stdout
        sb.cleanup()

    def test_nemoclaw_path_traversal_blocked(self):
        """NemoClaw blocks path traversal outside sandbox."""
        from alberto.sandbox.base import NemoClawSandbox
        sb = NemoClawSandbox("test4")
        # Try to escape via ../
        target = Path("/etc/passwd")
        safe = sb._resolve_safe(target)
        # Should NOT be /etc/passwd - should be redirected to sandbox
        assert "/etc/passwd" not in str(safe)
        sb.cleanup()

    def test_nemoclaw_uuid_isolation(self):
        """Each NemoClaw sandbox gets a unique UUID dir."""
        from alberto.sandbox.base import NemoClawSandbox
        sb1 = NemoClawSandbox("test5a")
        sb2 = NemoClawSandbox("test5b")
        # UUIDs should differ
        assert sb1._id != sb2._id
        # Bases should differ
        if sb1._mode == "host-fallback" and sb2._mode == "host-fallback":
            assert sb1._base != sb2._base
        sb1.cleanup()
        sb2.cleanup()


class TestSandboxFactory:
    def test_make_sandbox_local(self):
        from alberto.sandbox.base import make_sandbox
        sb = make_sandbox("local")
        assert sb is not None
        sb.cleanup()

    def test_make_sandbox_nemoclaw(self):
        from alberto.sandbox.base import make_sandbox
        sb = make_sandbox("nemoclaw")
        assert sb is not None
        # Should NOT raise NotImplementedError now
        assert hasattr(sb, "home")
        assert hasattr(sb, "run")
        sb.cleanup()


def test_nemoclaw_relative_traversal_stays_inside_home():
    from alberto.sandbox.base import NemoClawSandbox
    sb = NemoClawSandbox("path-traversal-relative")
    try:
        safe = sb._resolve_safe(Path("../../../../etc/passwd"))
        assert safe != Path("/etc/passwd")
        assert safe.is_relative_to(sb.home().resolve())
    finally:
        sb.cleanup()


def test_nemoclaw_rejects_symlink_escape_in_host_fallback(tmp_path):
    from alberto.sandbox.base import NemoClawSandbox
    sb = NemoClawSandbox("path-traversal-symlink")
    try:
        if sb._mode == "docker":
            pytest.skip("host symlink test does not apply to container filesystem")
        home = sb.home()
        link = home / "escape-link"
        try:
            link.symlink_to(Path("/etc/passwd"))
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        with pytest.raises(ValueError, match="escapes sandbox home"):
            sb._resolve_safe(link)
    finally:
        sb.cleanup()


def test_docker_run_returns_completed_process_shape():
    from types import SimpleNamespace
    from alberto.sandbox.base import NemoClawSandbox

    class FakeContainer:
        def __init__(self):
            self.last_command = None

        def exec_run(self, command, **kwargs):
            self.last_command = command
            return SimpleNamespace(exit_code=0, output=(b"sandbox-output", b""))

    sb = NemoClawSandbox.__new__(NemoClawSandbox)
    sb._mode = "docker"
    sb.isolation_level = "docker-container"
    sb._container = FakeContainer()

    result = sb.run(["echo", "hello"], timeout=3)

    assert result.returncode == 0
    assert result.stdout == "sandbox-output"
    assert result.stderr == ""
    assert sb._container.last_command[:2] == ["timeout", "3s"]


def test_docker_exists_uses_argv_not_shell_string():
    from types import SimpleNamespace
    from alberto.sandbox.base import NemoClawSandbox

    class FakeContainer:
        def __init__(self):
            self.last_command = None

        def exec_run(self, command, **kwargs):
            self.last_command = command
            return SimpleNamespace(exit_code=1, output=b"")

    sb = NemoClawSandbox.__new__(NemoClawSandbox)
    sb._mode = "docker"
    sb._container = FakeContainer()

    assert sb.exists(Path("/tmp/file with spaces")) is False
    assert sb._container.last_command == ["test", "-e", "/tmp/file with spaces"]


def test_nemoclaw_run_timeout_returns_completed_process():
    from alberto.sandbox.base import NemoClawSandbox
    sb = NemoClawSandbox("timeout-contract")
    try:
        result = sb.run(["python3", "-c", "import time; time.sleep(2)"], timeout=1)
        assert result.returncode == 124
        assert "timeout after 1s" in result.stderr or result.returncode == 124
    finally:
        sb.cleanup()
