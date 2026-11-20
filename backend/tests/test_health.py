import pytest
import urllib.request
import json
import threading
import time
import uvicorn
from app.main import app

@pytest.fixture(scope="session")
def server():
    port = 8009
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(1.2)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True

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
