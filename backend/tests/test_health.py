import pytest
import urllib.request
import json

def test_health_check(server):
    with urllib.request.urlopen(f"{server}/api/v1/health") as response:
        assert response.status == 200
        data = json.loads(response.read().decode())
        assert data["status"] == "healthy"
        assert data["service"] == "AI Voice Agent Backend"
        assert "uptime_seconds" in data

def test_root_endpoint(server):
    with urllib.request.urlopen(f"{server}/") as response:
        assert response.status == 200
        data = json.loads(response.read().decode())
        assert data["status"] == "online"
        assert "AI Voice Agent" in data["message"]
