from fastapi.testclient import TestClient

from app.api.server import app

client = TestClient(app)


def test_healthz_returns_status_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))

    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["app"] == "MendCode"
    assert payload["status"] == "ok"
    assert "timestamp" in payload
    assert "traces_dir" in payload

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
