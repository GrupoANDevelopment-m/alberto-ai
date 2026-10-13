"""Regression tests for the app tester's benchmark result semantics."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from alberto.runtime.tester import AppTester


def make_tester(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    return AppTester(app)


@pytest.mark.parametrize(
    ("endpoint", "n_requests", "concurrency", "expected"),
    [
        ("/", 0, 1, "n_requests"),
        ("/", -1, 1, "n_requests"),
        ("/", 1, 0, "concurrency"),
        ("/", 1, -2, "concurrency"),
        ("https://example.invalid/", 1, 1, "endpoint"),
        ("//example.invalid/path", 1, 1, "endpoint"),
        ("relative", 1, 1, "endpoint"),
    ],
)
def test_perf_rejects_invalid_inputs_without_starting_process(
    tmp_path, monkeypatch, endpoint, n_requests, concurrency, expected
):
    t = make_tester(tmp_path)
    (t.app_dir / "backend").mkdir()
    monkeypatch.setattr(
        "alberto.runtime.tester.subprocess.Popen",
        lambda *a, **k: pytest.fail("process must not start for invalid inputs"),
    )
    result = t.perf(endpoint, n_requests=n_requests, concurrency=concurrency)
    assert result["ok"] is False
    assert expected in result["error"]


def test_smoke_fails_when_app_has_no_testable_components(tmp_path):
    result = make_tester(tmp_path).smoke()
    assert result["ok"] is False
    assert result["failed"] == 0
    assert "no backend or frontend" in result["error"]


def test_percentile_handles_empty_and_nonempty_samples(tmp_path):
    t = make_tester(tmp_path)
    assert t._percentile([], 95) == 0.0
    assert t._percentile([10, 30, 20], 50) == 20
    assert t._percentile([10, 30, 20], 95) == 30


def test_perf_reports_request_failures_as_failed_benchmark(tmp_path, monkeypatch):
    t = make_tester(tmp_path)
    (t.app_dir / "backend").mkdir()

    class Process:
        stderr = SimpleNamespace(read=lambda: b"")

        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr("alberto.runtime.tester.subprocess.Popen", lambda *a, **k: Process())
    monkeypatch.setattr("alberto.runtime.tester.time.sleep", lambda *_: None)

    def unavailable(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    result = t.perf("/", n_requests=2, concurrency=2)
    assert result["ok"] is False
    assert result["sequential"]["errors"] == 2
    assert result["concurrent"]["errors"] == 2


def test_perf_reports_successful_requests_and_percentiles(tmp_path, monkeypatch):
    t = make_tester(tmp_path)
    (t.app_dir / "backend").mkdir()

    class Process:
        stderr = SimpleNamespace(read=lambda: b"")

        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"ok"

    monkeypatch.setattr("alberto.runtime.tester.subprocess.Popen", lambda *a, **k: Process())
    monkeypatch.setattr("alberto.runtime.tester.time.sleep", lambda *_: None)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response())
    result = t.perf("/", n_requests=3, concurrency=2)
    assert result["ok"] is True
    assert result["sequential"]["n"] == 3
    assert result["concurrent"]["n"] == 3
    assert result["sequential"]["errors"] == 0
    assert result["concurrent"]["errors"] == 0
    assert result["concurrent"]["throughput_rps"] > 0
