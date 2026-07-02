import fakeredis
import pytest

import skills.conviction as conviction
import skills.watchlist as watchlist
import workers.tasks as tasks


@pytest.fixture
def fake_redis(monkeypatch):
    """Fresh in-memory Redis for tests that exercise conviction's prev-snapshot cache."""
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(conviction, "_r", fake)
    return fake


@pytest.fixture
def fake_watchlist_redis(monkeypatch):
    """Fresh in-memory Redis for tests that exercise the watchlist store."""
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(watchlist, "_r", fake)
    return fake


@pytest.fixture
def fake_tasks_redis(monkeypatch):
    """Fresh in-memory Redis for tests that exercise the job-timing tracker."""
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(tasks, "_redis", fake)
    return fake
