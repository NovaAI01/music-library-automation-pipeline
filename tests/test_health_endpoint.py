from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_service_status():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "music-library-intelligence-platform",
    }
