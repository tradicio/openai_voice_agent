import pytest
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

def test_set_timeout_valid():
    """Test POST /api/session/timeout with valid timeout"""
    response = client.post("/api/session/timeout", json={"timeout": 120})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["timeout"] == 120

def test_set_timeout_invalid_low():
    """Test POST /api/session/timeout with timeout too low"""
    response = client.post("/api/session/timeout", json={"timeout": 30})
    assert response.status_code == 400

def test_set_timeout_invalid_high():
    """Test POST /api/session/timeout with timeout too high"""
    response = client.post("/api/session/timeout", json={"timeout": 500})
    assert response.status_code == 400

def test_timeout_boundary_low():
    """Test POST /api/session/timeout at minimum boundary"""
    response = client.post("/api/session/timeout", json={"timeout": 60})
    assert response.status_code == 200
    assert response.json()["timeout"] == 60

def test_timeout_boundary_high():
    """Test POST /api/session/timeout at maximum boundary"""
    response = client.post("/api/session/timeout", json={"timeout": 300})
    assert response.status_code == 200
    assert response.json()["timeout"] == 300

def test_timeout_just_below_min():
    """Test POST /api/session/timeout just below minimum"""
    response = client.post("/api/session/timeout", json={"timeout": 59})
    assert response.status_code == 400

def test_timeout_just_above_max():
    """Test POST /api/session/timeout just above maximum"""
    response = client.post("/api/session/timeout", json={"timeout": 301})
    assert response.status_code == 400
