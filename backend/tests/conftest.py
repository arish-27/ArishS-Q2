import pytest
import threading
import time
import urllib.request
import uvicorn
import os
from app.main import app
from app.core.database import Base, engine

@pytest.fixture(scope="session")
def server():
    port = 8011
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server_obj = uvicorn.Server(config)
    thread = threading.Thread(target=server_obj.run, daemon=True)
    thread.start()

    # Wait for server to respond to health check
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=1) as response:
                if response.status == 200:
                    break
        except Exception:
            time.sleep(0.2)

    yield f"http://127.0.0.1:{port}"
    server_obj.should_exit = True
