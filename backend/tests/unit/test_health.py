"""`GET /api/v1/health` contract test (D15).

See `docs/specs/d1-a-platform-data-v0.md` §"Test list". Fakes only, no
containers and no lifespan: the probes are overridden via
`app.dependency_overrides`.
"""

from fastapi.testclient import TestClient

from app.core.db import ping_db
from app.core.redis import ping_redis
from app.main import app


def test_health_up_and_down() -> None:
    """200 + both up with healthy fakes; 503 + `db: down` when the DB probe fails."""
    app.dependency_overrides[ping_db] = lambda: True
    app.dependency_overrides[ping_redis] = lambda: True
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "db": "up", "redis": "up"}

        app.dependency_overrides[ping_db] = lambda: False
        with TestClient(app) as client:
            response = client.get("/api/v1/health")
        assert response.status_code == 503
        assert response.json() == {"status": "degraded", "db": "down", "redis": "up"}
    finally:
        app.dependency_overrides.clear()
