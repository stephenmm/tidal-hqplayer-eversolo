"""Integration tests for HTTP routes using the FastAPI TestClient."""
from unittest.mock import MagicMock, patch

import pytest


# ── /status ──────────────────────────────────────────────────────────────────

def test_status_shape(client, mock_hqp_send, logged_in_session):
    resp = client.get("/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "tidal_logged_in" in body
    assert "hqplayer" in body


def test_status_hqplayer_unreachable(client, monkeypatch, logged_in_session):
    from fastapi import HTTPException
    import tidal_hqp.hqplayer.client as hc
    monkeypatch.setattr(hc, "hqp_send", MagicMock(side_effect=HTTPException(502, "unreachable")))

    resp = client.get("/status")
    assert resp.status_code == 200
    assert resp.json()["hqplayer"]["error"] == "HQPlayer not reachable"


# ── /auth ─────────────────────────────────────────────────────────────────────

def test_auth_status_not_logged_in(client):
    import tidal_hqp.tidal.session as ts
    ts.session.check_login.return_value = False

    resp = client.get("/auth/status")
    assert resp.status_code == 200
    assert resp.json()["logged_in"] is False
    assert resp.json()["user"] is None


def test_auth_login_returns_url_and_expiry(client, monkeypatch):
    import tidal_hqp.tidal.session as ts

    fake_login = MagicMock()
    fake_login.verification_uri_complete = "link.tidal.com/ABCD"
    fake_login.expires_in = 300
    ts.session.login_oauth = MagicMock(return_value=(fake_login, MagicMock()))

    resp = client.post("/auth/login")
    assert resp.status_code == 200
    body = resp.json()
    assert body["login_url"].startswith("https://")
    assert body["expires_in"] == 300


def test_auth_logout_removes_token_file(client, tmp_path, monkeypatch):
    token = tmp_path / "token.json"
    token.write_text("{}")
    monkeypatch.setattr("tidal_hqp.tidal.routes.TOKEN_FILE", token)

    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    assert not token.exists()


# ── /play ─────────────────────────────────────────────────────────────────────

def test_play_requires_login(client):
    import tidal_hqp.tidal.session as ts
    ts.session.check_login.return_value = False

    resp = client.post("/play", json={"track_id": 42})
    assert resp.status_code == 401


def test_play_returns_ok_and_sets_active(client, logged_in_session, monkeypatch):
    import time
    import tidal_hqp.hqplayer.client as hc
    import tidal_hqp.streaming.state as st

    monkeypatch.setattr(hc, "hqp_send", MagicMock(return_value="<Stop />"))
    # Patch on player.py — that's where the names are imported at module level
    import tidal_hqp.playback.player as pp
    mock_play_url = MagicMock()
    monkeypatch.setattr(pp, "hqp_play_url", mock_play_url)
    monkeypatch.setattr(pp, "track_stream_url", MagicMock(return_value="https://cdn.tidal.com/fake"))

    # Fake download: write 8 MB immediately so prebuffer is satisfied
    def fake_download(url, path):
        with open(path, "wb") as f:
            f.write(b"\x00" * (8 * 1024 * 1024 + 1))
        with st._active_lock:
            st._active["content_length"] = 8 * 1024 * 1024 + 1

    monkeypatch.setattr(pp, "download", fake_download)

    resp = client.post("/play", json={"track_id": 42})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # /play dispatches a background thread; wait for it to complete
    time.sleep(0.5)
    mock_play_url.assert_called_once()
    call_url = mock_play_url.call_args[0][0]
    assert "/stream/42" in call_url


# ── /stop ─────────────────────────────────────────────────────────────────────

def test_stop_calls_hqp(client, mock_hqp_send):
    resp = client.post("/stop")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_hqp_send.assert_called()


# ── /hqplayer/configure ───────────────────────────────────────────────────────

def test_hqplayer_configure_patches_xml(client, tmp_path, monkeypatch):
    settings = tmp_path / "settings.xml"
    settings.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<hqplayer>"
        '<engine adaptive_rate="0">'
        '<defaults samplerate="44100" />'
        '<network period_time="250" />'
        "</engine>"
        "</hqplayer>"
    )

    import tidal_hqp.hqplayer_routes as hr
    import tidal_hqp.hqplayer.configure as cfg

    monkeypatch.setattr(hr, "HQP_SETTINGS_XML", settings)
    monkeypatch.setattr(cfg, "HQP_SETTINGS_XML", settings)
    # hqplayer_routes imports these by name, so patch them there — patching
    # them on `configure` leaves the route calling the real implementations.
    monkeypatch.setattr(hr, "close_and_wait", MagicMock(return_value=True))
    monkeypatch.setattr(hr, "launch", MagicMock())

    resp = client.post("/hqplayer/configure", json={"samplerate": 192000, "period_time": 50000})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["samplerate"] == "192000"
    assert body["period_time"] == "50000"

    import xml.etree.ElementTree as ET
    root = ET.parse(settings).getroot()
    assert root.find("engine/defaults").get("samplerate") == "192000"
    assert root.find("engine/network").get("period_time") == "50000"


# ── Auth flow details ─────────────────────────────────────────────────────────

def test_auth_login_leaves_an_absolute_url_alone(client, tidal_session):
    fake_login = MagicMock()
    fake_login.verification_uri_complete = "https://link.tidal.com/ABCD"
    fake_login.expires_in = 300
    tidal_session.login_oauth = MagicMock(return_value=(fake_login, MagicMock()))

    body = client.post("/auth/login").json()

    assert body["login_url"] == "https://link.tidal.com/ABCD"


def test_auth_login_records_a_pending_login(client, tidal_session):
    import tidal_hqp.tidal.session as ts

    fake_login = MagicMock()
    fake_login.verification_uri_complete = "link.tidal.com/ABCD"
    fake_login.expires_in = 300
    tidal_session.login_oauth = MagicMock(return_value=(fake_login, MagicMock()))

    client.post("/auth/login")

    assert ts.pending_login is not None


def test_auth_status_saves_the_token_after_a_successful_login(client, tmp_path, monkeypatch, tidal_session):
    """The pending login must be persisted and cleared exactly once."""
    import tidal_hqp.tidal.session as ts

    token = tmp_path / "token.json"
    monkeypatch.setattr(ts, "TOKEN_FILE", token)
    monkeypatch.setattr(ts, "pending_login", {"future": MagicMock(), "started": 0})
    tidal_session.check_login.return_value = True
    tidal_session.token_type = "Bearer"
    tidal_session.access_token = "acc"
    tidal_session.refresh_token = "ref"
    tidal_session.expiry_time = None

    body = client.get("/auth/status").json()

    assert body == {"logged_in": True, "user": "test@example.com"}
    assert token.exists(), "a completed login must be written to disk"
    assert ts.pending_login is None, "the pending login must be cleared"


def test_auth_status_does_not_rewrite_the_token_without_a_pending_login(client, tmp_path, monkeypatch, tidal_session):
    import tidal_hqp.tidal.session as ts

    token = tmp_path / "token.json"
    monkeypatch.setattr(ts, "TOKEN_FILE", token)
    monkeypatch.setattr(ts, "pending_login", None)
    tidal_session.check_login.return_value = True

    client.get("/auth/status")

    assert not token.exists()


def test_auth_logout_is_safe_when_no_token_exists(client, tmp_path, monkeypatch):
    monkeypatch.setattr("tidal_hqp.tidal.routes.TOKEN_FILE", tmp_path / "absent.json")
    assert client.post("/auth/logout").json() == {"ok": True}


# ── Queue route error tolerance ───────────────────────────────────────────────

def test_remove_current_track_tolerates_an_unreachable_hqplayer(client, monkeypatch, queued):
    """Removing the playing track must still succeed if HQPlayer is down."""
    import tidal_hqp.hqplayer.client as hc
    queued([{"id": 1}, {"id": 2}], current_index=0)
    monkeypatch.setattr(hc, "hqp_send", MagicMock(side_effect=OSError("down")))

    resp = client.delete("/queue/0")

    assert resp.status_code == 200
    assert resp.json()["playback_stopped"] is True


def test_remove_track_out_of_range_reports_not_stopped(client, queued):
    queued([{"id": 1}], current_index=0)
    assert client.delete("/queue/99").json()["playback_stopped"] is False


# ── Lifespan ──────────────────────────────────────────────────────────────────

def test_lifespan_reports_a_restored_session(monkeypatch, capsys):
    """The startup log must name the restored user."""
    import importlib
    from fastapi.testclient import TestClient

    app_module = importlib.import_module("tidal_hqp.app")
    monkeypatch.setattr(app_module, "load_token", lambda: True)
    monkeypatch.setattr(app_module, "start_monitor", lambda: None)

    with TestClient(app_module.app):
        pass

    assert "Restored session for test@example.com" in capsys.readouterr().out


def test_lifespan_starts_the_queue_monitor(monkeypatch):
    """The monitor must be started by the app, since import no longer does it."""
    import importlib
    from fastapi.testclient import TestClient

    app_module = importlib.import_module("tidal_hqp.app")
    started = []
    monkeypatch.setattr(app_module, "load_token", lambda: False)
    monkeypatch.setattr(app_module, "start_monitor", lambda: started.append(1))

    with TestClient(app_module.app):
        pass

    assert started == [1]
