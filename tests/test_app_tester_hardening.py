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
        ("/", 1001, 1, "n_requests"),
        ("/", True, 1, "n_requests"),
        ("/", 1, 0, "concurrency"),
        ("/", 1, -2, "concurrency"),
        ("/", 1, 65, "concurrency"),
        ("/", 1, True, "concurrency"),
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

    monkeypatch.setenv("ALBERTO_ALLOW_HOST_APP_TESTING", "1")
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

    monkeypatch.setenv("ALBERTO_ALLOW_HOST_APP_TESTING", "1")
    monkeypatch.setattr("alberto.runtime.tester.subprocess.Popen", lambda *a, **k: Process())
    monkeypatch.setattr("alberto.runtime.tester.time.sleep", lambda *_: None)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Response())
    result = t.perf("/", n_requests=3, concurrency=2)
    assert result["ok"] is True
    assert result["sequential"]["n"] == 3
    assert result["concurrent"]["n"] == 3
    assert result["sequential"]["errors"] == 0
    assert result["concurrent"]["errors"] == 0
    assert result["concurrent"]["duration_s"] > 0
    assert result["concurrent"]["throughput_rps"] == pytest.approx(
        result["concurrent"]["n"] / result["concurrent"]["duration_s"]
    )



def test_perf_refuses_host_execution_without_explicit_opt_in(tmp_path, monkeypatch):
    t = make_tester(tmp_path)
    (t.app_dir / "backend").mkdir()
    monkeypatch.delenv("ALBERTO_ALLOW_HOST_APP_TESTING", raising=False)
    monkeypatch.setattr(
        "alberto.runtime.tester.subprocess.Popen",
        lambda *a, **k: pytest.fail("must refuse before starting app code"),
    )
    result = t.perf("/", n_requests=1, concurrency=1)
    assert result["ok"] is False
    assert "refusing to execute app code on the host" in result["error"]


@pytest.mark.parametrize("method,phase", [
    ("test_install", "test_install"),
    ("test_frontend_e2e", "frontend_e2e"),
])
def test_install_and_e2e_refuse_host_execution_without_opt_in(tmp_path, monkeypatch, method, phase):
    t = make_tester(tmp_path)
    (t.app_dir / "backend").mkdir()
    (t.app_dir / "frontend").mkdir()
    monkeypatch.delenv("ALBERTO_ALLOW_HOST_APP_TESTING", raising=False)
    monkeypatch.setattr(
        "alberto.runtime.tester.subprocess.run",
        lambda *a, **k: pytest.fail("must refuse before subprocess.run"),
    )
    monkeypatch.setattr(
        "alberto.runtime.tester.subprocess.Popen",
        lambda *a, **k: pytest.fail("must refuse before subprocess.Popen"),
    )
    result = getattr(t, method)()
    assert result["ok"] is False
    assert result["phase"] == phase
    assert "refusing to execute app code on the host" in result["error"]


def test_backend_smoke_refuses_host_execution_without_opt_in(tmp_path, monkeypatch):
    t = make_tester(tmp_path)
    t.backend.mkdir()
    monkeypatch.delenv("ALBERTO_ALLOW_HOST_APP_TESTING", raising=False)
    monkeypatch.setattr(
        "alberto.runtime.tester.subprocess.Popen",
        lambda *a, **k: pytest.fail("must refuse before starting app code"),
    )
    result = t._test_backend()
    assert result["ok"] is False
    assert result["phase"] == "backend_smoke"

def test_perf_against_real_local_fastapi_backend(tmp_path, monkeypatch):
    """Exercise the benchmark against a real Uvicorn process and HTTP responses."""
    app_dir = tmp_path / "real-app"
    backend = app_dir / "backend"
    backend.mkdir(parents=True)
    (backend / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.get('/')\n"
        "def health():\n"
        "    return {'status': 'ok'}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ALBERTO_ALLOW_HOST_APP_TESTING", "1")

    result = AppTester(app_dir).perf("/", n_requests=5, concurrency=2)

    assert result["ok"] is True, result
    assert result["phase"] == "perf"
    assert result["sequential"]["n"] == 5
    assert result["sequential"]["errors"] == 0
    assert result["concurrent"]["n"] == 5
    assert result["concurrent"]["errors"] == 0
    assert result["concurrent"]["duration_s"] > 0
    assert result["concurrent"]["throughput_rps"] > 0
    assert result["concurrent"]["p95_ms"] >= 0
