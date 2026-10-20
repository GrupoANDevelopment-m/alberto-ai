"""Regression tests for fail-closed sandbox configuration."""
import pytest

from alberto.agent import resolve_sandbox_kind


def test_default_sandbox_remains_local_for_compatibility():
    assert resolve_sandbox_kind({}) == "local"


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
def test_require_docker_defaults_to_nemoclaw(value):
    assert resolve_sandbox_kind({"ALBERTO_REQUIRE_DOCKER": value}) == "nemoclaw"


def test_explicit_nemoclaw_is_accepted_when_required():
    assert resolve_sandbox_kind({
        "ALBERTO_REQUIRE_DOCKER": "1",
        "ALBERTO_SANDBOX_KIND": "nemoclaw",
    }) == "nemoclaw"


@pytest.mark.parametrize("kind", ["local", "LOCAL", ""])
def test_require_docker_rejects_conflicting_sandbox_configuration(kind):
    env = {"ALBERTO_REQUIRE_DOCKER": "1", "ALBERTO_SANDBOX_KIND": kind}
    if kind == "":
        assert resolve_sandbox_kind(env) == "nemoclaw"
    else:
        with pytest.raises(RuntimeError, match="Refusing to run without the required isolation"):
            resolve_sandbox_kind(env)
