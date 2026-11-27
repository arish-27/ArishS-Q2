"""
Container entrypoint for FastAPI backend:
1. Waits for PostgreSQL to become reachable (with retry loop).
2. Logs and runs `alembic upgrade head` idempotently.
3. Replaces the process with `uvicorn app.main:app` (or passed args).
"""
import os
import subprocess
import sys
import time
from urllib.parse import urlparse
import socket


def wait_for_postgres(database_url: str, max_attempts: int = 30, delay_s: float = 2.0) -> None:
    if not database_url or "sqlite" in database_url.lower():
        return
    normalized = database_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(normalized)
    host = parsed.hostname or "postgres"
    port = parsed.port or 5432

    for attempt in range(1, max_attempts + 1):
        try:
            with socket.create_connection((host, port), timeout=2.0):
                print(f"PostgreSQL reachable at {host}:{port} (attempt {attempt})", flush=True)
                return
        except OSError as exc:
            print(f"Waiting for PostgreSQL at {host}:{port} (attempt {attempt}/{max_attempts}): {exc}", flush=True)
            time.sleep(delay_s)

    raise RuntimeError(f"PostgreSQL at {host}:{port} did not become reachable after {max_attempts} attempts.")


def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "")
    wait_for_postgres(db_url)

    print("Running database migrations...", flush=True)
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    print("Database migrations complete.", flush=True)

    cmd = sys.argv[1:] if len(sys.argv) > 1 else [
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--reload",
    ]
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
