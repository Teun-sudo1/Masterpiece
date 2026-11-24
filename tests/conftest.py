import pytest

from masterpiece import cache


@pytest.fixture(autouse=True)
def no_github(monkeypatch):
    """Tests never ask GitHub for updates (it allows ~60 checks an hour per connection)."""
    import urllib.request
    real = urllib.request.urlopen

    def guarded(req, *a, **k):
        url = getattr(req, "full_url", req)
        if "github.com" in str(url) or "githubusercontent.com" in str(url):
            raise OSError("no GitHub in tests")
        return real(req, *a, **k)
    monkeypatch.setattr(urllib.request, "urlopen", guarded)    # a test may still fake GitHub itself


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Never touch the user's real cache during tests."""
    monkeypatch.setenv("MASTERPIECE_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))       # settings.json
    cache.reset()
    yield
    cache.reset()
