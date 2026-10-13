"""Production-mode HTTP security regressions for the Alberto API."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from alberto.server.app import create_app


TOKEN = "test-only-token-with-at-least-32-characters"


def make_app(monkeypatch, tmp_path, *, production=False, token=None, alberto=None):
    monkeypatch.setenv("ALBERTO_ENV", "production" if production else "development")
    if token is None:
        monkeypatch.delenv("ALBERTO_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("ALBERTO_API_TOKEN", token)
    frontend = tmp_path / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / "index.html").write_text("<html>ok</html>")
    return create_app(alberto=alberto or SimpleNamespace(), frontend_dir=frontend)


def test_production_refuses_missing_or_short_api_token(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="ALBERTO_API_TOKEN"):
        make_app(monkeypatch, tmp_path, production=True)
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        make_app(monkeypatch, tmp_path, production=True, token="short")


def test_production_api_requires_bearer_token(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path, production=True, token=TOKEN)
    client = TestClient(app)
    response = client.get("/api/banner")
    assert response.status_code == 401
    assert response.json() == {"error": "authentication required"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_production_api_accepts_correct_bearer_token(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path, production=True, token=TOKEN)
    response = TestClient(app).get(
        "/api/banner", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 200
    assert "text" in response.json()


def test_production_disables_openapi_docs(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path, production=True, token=TOKEN)
    client = TestClient(app)
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/__docs").status_code == 404


def test_configured_token_protects_api_even_outside_production(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path, token=TOKEN)
    client = TestClient(app)
    assert client.get("/api/banner").status_code == 401
    assert client.get(
        "/api/banner", headers={"Authorization": f"Bearer {TOKEN}"}
    ).status_code == 200


def test_development_without_token_keeps_local_api_usable(monkeypatch, tmp_path):
    app = make_app(monkeypatch, tmp_path)
    assert TestClient(app).get("/api/banner").status_code == 200


def test_production_error_response_and_logs_do_not_disclose_exception(monkeypatch, tmp_path, caplog):
    broken = SimpleNamespace(status=lambda: (_ for _ in ()).throw(RuntimeError("secret-path /root/private")))
    app = make_app(monkeypatch, tmp_path, production=True, token=TOKEN, alberto=broken)
    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/status", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert response.status_code == 500
    assert response.json() == {"error": "internal server error"}
    assert "secret-path" not in response.text
    assert "secret-path" not in caplog.text
