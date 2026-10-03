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
        # Mode is either docker or hermetic
        assert sb._mode in ("docker", "hermetic")
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
        if sb1._mode == "hermetic" and sb2._mode == "hermetic":
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
