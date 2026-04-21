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
    import tidal_hqp.tidal.session as ts
    import tidal_hqp.hqplayer.client as hc
    import tidal_hqp.streaming.state as st

    monkeypatch.setattr(ts, "track_stream_url", MagicMock(return_value="https://cdn.tidal.com/fake"))
    monkeypatch.setattr(hc, "hqp_send", MagicMock(return_value="<Stop />"))
    # Patch where it's used (imported name in routes), not where it's defined
    import tidal_hqp.playback.routes as pr
    monkeypatch.setattr(pr, "hqp_play_url", MagicMock())

    # Fake download: write 8 MB immediately so prebuffer is satisfied
    def fake_download(url, path):
        with open(path, "wb") as f:
            f.write(b"\x00" * (8 * 1024 * 1024 + 1))
        with st._active_lock:
            st._active["content_length"] = 8 * 1024 * 1024 + 1

    monkeypatch.setattr("tidal_hqp.playback.routes.download", fake_download)

    resp = client.post("/play", json={"track_id": 42})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    pr.hqp_play_url.assert_called_once()
    call_url = pr.hqp_play_url.call_args[0][0]
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
    monkeypatch.setattr(cfg, "close_and_wait", MagicMock(return_value=True))
    monkeypatch.setattr(cfg, "launch", MagicMock())

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
