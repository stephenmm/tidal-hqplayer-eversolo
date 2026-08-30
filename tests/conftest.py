import socket
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from tidal_hqp.config import HQPLAYER_PORT


# ── Socket guard ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_hqplayer_sockets(monkeypatch):
    """Fail any test that opens a real connection to HQPlayer.

    The queue monitor used to start on import and poll the HQPlayer port every
    500 ms for the whole session. This fixture makes a regression of that kind
    fail loudly instead of quietly slowing the suite down.
    """
    attempts: list = []
    real = socket.create_connection

    def guarded(address, *args, **kwargs):
        attempts.append(address)
        return real(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded)
    yield attempts

    hqp = [a for a in attempts if isinstance(a, tuple) and len(a) > 1 and a[1] == HQPLAYER_PORT]
    assert not hqp, f"test opened a real connection to HQPlayer: {hqp}"


# ── Tidal session ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def tidal_session(monkeypatch):
    """Install a fresh logged-out Tidal session mock for every test.

    Function-scoped and monkeypatched so a test that mutates the session (or a
    route that reassigns it) cannot leak into the next test.
    """
    import tidal_hqp.tidal.session as ts
    fake = _make_fake_session(logged_in=False)
    monkeypatch.setattr(ts, "session", fake)
    monkeypatch.setattr(ts, "pending_login", None)
    return fake


@pytest.fixture()
def logged_in_session(tidal_session):
    """Flip the current session mock to appear authenticated."""
    tidal_session.check_login.return_value = True
    return tidal_session


# ── App client ───────────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    """TestClient with the token load and the monitor thread stubbed out."""
    import importlib
    # tidal_hqp/__init__.py binds `app` to the FastAPI instance, which shadows
    # the tidal_hqp.app submodule — so reach for the module explicitly.
    app_module = importlib.import_module("tidal_hqp.app")

    monkeypatch.setattr(app_module, "load_token", lambda: False)
    monkeypatch.setattr(app_module, "start_monitor", lambda: None)

    with TestClient(app_module.app, raise_server_exceptions=True) as c:
        yield c


# ── HQPlayer ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_hqp_send(monkeypatch):
    """Prevent any real TCP connections to HQPlayer."""
    import tidal_hqp.hqplayer.client as hc
    fake = MagicMock(return_value='<?xml version="1.0"?><Status state="2" input_fill="0.5" output_fill="0.0" />')
    monkeypatch.setattr(hc, "hqp_send", fake)
    return fake


# ── Queue ────────────────────────────────────────────────────────────────────

_QUEUE_DEFAULTS = {
    "tracks":        [],
    "current_index": None,
    "shuffle":       False,
    "shuffle_order": [],
    "loading":       False,
    "user_stopped":  False,
}


@pytest.fixture(autouse=True)
def reset_queue():
    """Isolate the queue singleton between tests."""
    import tidal_hqp.playback.queue as Q

    def _reset():
        with Q._queue_lock:
            Q._queue.update({k: (list(v) if isinstance(v, list) else v)
                             for k, v in _QUEUE_DEFAULTS.items()})

    _reset()
    yield
    _reset()


@pytest.fixture()
def queued(request):
    """Load the queue with tracks and an optional current_index."""
    import tidal_hqp.playback.queue as Q

    def _load(tracks, current_index=None, **flags):
        with Q._queue_lock:
            Q._queue["tracks"] = list(tracks)
            Q._queue["current_index"] = current_index
            Q._queue.update(flags)
        return Q

    return _load


# ── Streaming ────────────────────────────────────────────────────────────────

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
