import pytest

from masterpiece import cache


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Never touch the user's real cache during tests."""
    monkeypatch.setenv("MASTERPIECE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))       # settings.json
    cache.reset()
    yield
    cache.reset()
