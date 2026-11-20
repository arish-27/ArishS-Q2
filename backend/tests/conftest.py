import pytest
import threading
import time
import uvicorn
import os
from app.main import app
from app.core.database import Base, engine

@pytest.fixture(scope="session")
def server():
    port = 8011
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    time.sleep(1.2)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
