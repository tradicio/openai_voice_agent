from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_check():
    """Test GET /api/health endpoint"""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_prompts():
    """Test GET /api/prompts endpoint"""
    response = client.get("/api/prompts")
    assert response.status_code == 200
    data = response.json()
    assert "prompts" in data
    assert len(data["prompts"]) > 0
    assert "key" in data["prompts"][0]
    assert "label" in data["prompts"][0]


def test_get_models():
    """Test GET /api/models endpoint"""
    response = client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert len(data["models"]) > 0
    keys = {m["key"] for m in data["models"]}
    assert "gpt-realtime-2" in keys
    for m in data["models"]:
        assert "key" in m and "label" in m


def test_get_voices():
    """Test GET /api/voices endpoint"""
    response = client.get("/api/voices")
    assert response.status_code == 200
    data = response.json()
    assert "voices" in data
    assert len(data["voices"]) == 10
    keys = {v["key"] for v in data["voices"]}
    assert "alloy" in keys
    for v in data["voices"]:
        assert "key" in v and "label" in v


def test_timeout_endpoint_removed():
    """The old timeout endpoint no longer exists."""
    response = client.post("/api/session/timeout", json={"timeout": 120})
    assert response.status_code == 404
