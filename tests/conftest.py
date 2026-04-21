import pathlib
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    """TestClient with real lifespan skipped (no token file needed)."""
    from tidal_hqp.app import app
    # Prevent load_token() from hitting disk during test session
    import tidal_hqp.tidal.session as ts
    ts.session = _make_fake_session(logged_in=False)
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture()
def logged_in_session(monkeypatch):
    """Patch the Tidal session to appear authenticated."""
    import tidal_hqp.tidal.session as ts
    fake = _make_fake_session(logged_in=True)
    monkeypatch.setattr(ts, "session", fake)
    return fake


@pytest.fixture()
def mock_hqp_send(monkeypatch):
    """Prevent any real TCP connections to HQPlayer."""
    import tidal_hqp.hqplayer.client as hc
    fake = MagicMock(return_value='<?xml version="1.0"?><Status state="2" input_fill="0.5" output_fill="0.0" />')
    monkeypatch.setattr(hc, "hqp_send", fake)
    return fake


@pytest.fixture(autouse=True)
def reset_active_state():
    """Isolate streaming state between tests."""
    from tidal_hqp.streaming.state import _active
    _active.clear()
    yield
    _active.clear()


@pytest.fixture()
def fake_flac(tmp_path) -> str:
    """100 KB placeholder file standing in for a FLAC download."""
    f = tmp_path / "test.flac"
    f.write_bytes(b"\x00" * 100_000)
    return str(f)


@pytest.fixture()
def active_stream(fake_flac):
    """Populate _active as if a download finished for track 42."""
    from tidal_hqp.streaming.state import _active, _active_lock
    with _active_lock:
        _active["tmp_path"]       = fake_flac
        _active["content_length"] = 100_000
        _active["dl_thread"]      = None
    return fake_flac


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_fake_session(*, logged_in: bool) -> MagicMock:
    fake = MagicMock()
    fake.check_login.return_value = logged_in
    fake.user.email = "test@example.com"
    return fake
