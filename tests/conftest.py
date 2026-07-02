import fakeredis
import pytest

import skills.conviction as conviction


@pytest.fixture
def fake_redis(monkeypatch):
    """Fresh in-memory Redis for tests that exercise conviction's prev-snapshot cache."""
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(conviction, "_r", fake)
    return fake
