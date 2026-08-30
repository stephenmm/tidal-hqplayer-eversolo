"""Tests for Tidal helpers — formatting, session guards, and stream quality."""
from unittest.mock import MagicMock, patch

import pytest
import tidalapi

from tidal_hqp.tidal.browse import fmt_album, fmt_track


def _make_track(**kwargs):
    t = MagicMock()
    t.id = kwargs.get("id", 1)
    t.name = kwargs.get("name", "Song")
    t.artist.name = kwargs.get("artist", "Artist")
    t.album.name = kwargs.get("album", "Album")
    t.duration = kwargs.get("duration", 240)
    t.audio_quality = kwargs.get("quality", "LOSSLESS")
    return t


def _make_album(**kwargs):
    a = MagicMock()
    a.id = kwargs.get("id", 10)
    a.name = kwargs.get("name", "Album")
    a.artist.name = kwargs.get("artist", "Artist")
    a.year = kwargs.get("year", 2024)
    a.image = MagicMock(return_value="https://example.com/cover.jpg")
    return a


def test_fmt_track_all_fields():
    t = _make_track(id=99, name="Track", artist="Band", album="Record", duration=180)
    result = fmt_track(t)
    assert result["id"] == 99
    assert result["title"] == "Track"
    assert result["artist"] == "Band"
    assert result["album"] == "Record"
    assert result["duration"] == 180


def test_fmt_track_missing_artist():
    t = _make_track()
    t.artist = None
    result = fmt_track(t)
    assert result["artist"] == ""


def test_fmt_track_missing_album():
    t = _make_track()
    t.album = None
    result = fmt_track(t)
    assert result["album"] == ""


def test_fmt_album_all_fields():
    a = _make_album(id=5, name="Record", artist="Band", year=2023)
    result = fmt_album(a)
    assert result["id"] == 5
    assert result["title"] == "Record"
    assert result["artist"] == "Band"
    assert result["year"] == 2023
    assert result["cover"] is not None


def test_require_login_raises_401(monkeypatch):
    import tidal_hqp.tidal.session as ts
    from fastapi import HTTPException

    monkeypatch.setattr(ts.session, "check_login", lambda: False)

    with pytest.raises(HTTPException) as exc:
        ts.require_login()

    assert exc.value.status_code == 401


# ── Stream quality ────────────────────────────────────────────────────────────

def test_session_configured_for_hi_res():
    """session.py must configure Quality.hi_res_lossless at module level.

    We inspect the source rather than the live object because conftest replaces
    ts.session with a MagicMock for other tests.
    """
    import inspect
    import tidal_hqp.tidal.session as ts
    src = inspect.getsource(ts)
    assert "hi_res_lossless" in src, (
        "session.py must create the Session with Quality.hi_res_lossless"
    )


def test_track_stream_url_uses_manifest(monkeypatch):
    """track_stream_url should use get_stream() manifest — not the legacy get_url()."""
    import tidal_hqp.tidal.session as ts

    fake_url = "https://cdn.tidal.com/hires/track.flac"
    manifest = MagicMock()
    manifest.get_urls.return_value = [fake_url]

    stream = MagicMock()
    stream.audio_quality = "HI_RES_LOSSLESS"
    stream.get_stream_manifest.return_value = manifest

    fake_track = MagicMock()
    fake_track.name = "Test Track"
    fake_track.audio_quality = "HI_RES_LOSSLESS"
    fake_track.get_stream.return_value = stream

    monkeypatch.setattr(ts.session, "track", lambda _id: fake_track)

    url = ts.track_stream_url(42)

    fake_track.get_stream.assert_called_once()
    manifest.get_urls.assert_called_once()
    fake_track.get_url.assert_not_called()
    assert url == fake_url


def test_track_stream_url_falls_back_to_get_url(monkeypatch):
    """If get_stream() raises, fall back to get_url() rather than crashing."""
    import tidal_hqp.tidal.session as ts

    fallback_url = "https://cdn.tidal.com/lossless/track.flac"

    fake_track = MagicMock()
    fake_track.name = "Test Track"
    fake_track.audio_quality = "LOSSLESS"
    fake_track.get_stream.side_effect = Exception("manifest unavailable")
    fake_track.get_url.return_value = fallback_url

    monkeypatch.setattr(ts.session, "track", lambda _id: fake_track)

    url = ts.track_stream_url(42)

    assert url == fallback_url
    fake_track.get_url.assert_called_once()


def test_track_stream_url_logs_quality(monkeypatch, capsys):
    """Quality info must be printed so it appears in server logs."""
    import tidal_hqp.tidal.session as ts

    manifest = MagicMock()
    manifest.get_urls.return_value = ["https://cdn.tidal.com/hires/track.flac"]

    stream = MagicMock()
    stream.audio_quality = "HI_RES_LOSSLESS"
    stream.get_stream_manifest.return_value = manifest

    fake_track = MagicMock()
    fake_track.name = "Hi-Res Song"
    fake_track.audio_quality = "HI_RES_LOSSLESS"
    fake_track.get_stream.return_value = stream

    monkeypatch.setattr(ts.session, "track", lambda _id: fake_track)
    ts.track_stream_url(99)

    out = capsys.readouterr().out
    assert "HI_RES_LOSSLESS" in out


# ── Token persistence ─────────────────────────────────────────────────────────

@pytest.fixture()
def token_file(tmp_path, monkeypatch):
    import tidal_hqp.tidal.session as ts
    f = tmp_path / "token.json"
    monkeypatch.setattr(ts, "TOKEN_FILE", f)
    return f


def test_save_token_writes_the_oauth_fields(token_file, tidal_session):
    import datetime as dt
    import json
    import tidal_hqp.tidal.session as ts

    tidal_session.token_type = "Bearer"
    tidal_session.access_token = "acc"
    tidal_session.refresh_token = "ref"
    tidal_session.expiry_time = dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc)

    ts.save_token()

    data = json.loads(token_file.read_text())
    assert data["token_type"] == "Bearer"
    assert data["access_token"] == "acc"
    assert data["refresh_token"] == "ref"
    assert data["expiry_time"] == tidal_session.expiry_time.timestamp()


def test_save_token_handles_a_missing_expiry(token_file, tidal_session):
    import json
    import tidal_hqp.tidal.session as ts

    tidal_session.token_type = "Bearer"
    tidal_session.access_token = "acc"
    tidal_session.refresh_token = "ref"
    tidal_session.expiry_time = None

    ts.save_token()

    assert json.loads(token_file.read_text())["expiry_time"] is None


def test_load_token_returns_false_without_a_file(token_file):
    import tidal_hqp.tidal.session as ts
    assert ts.load_token() is False


def test_load_token_returns_false_on_corrupt_json(token_file):
    import tidal_hqp.tidal.session as ts
    token_file.write_text("{not json")
    assert ts.load_token() is False


def test_load_token_returns_false_when_a_field_is_missing(token_file):
    import tidal_hqp.tidal.session as ts
    token_file.write_text('{"token_type": "Bearer"}')
    assert ts.load_token() is False


def test_load_token_restores_a_valid_session(token_file, tidal_session):
    import tidal_hqp.tidal.session as ts
    token_file.write_text(
        '{"token_type":"Bearer","access_token":"acc","refresh_token":"ref","expiry_time":null}'
    )
    tidal_session.load_oauth_session.return_value = True
    tidal_session.check_login.return_value = True

    assert ts.load_token() is True
    tidal_session.load_oauth_session.assert_called_once_with("Bearer", "acc", "ref")


def test_load_token_returns_false_when_the_token_is_rejected(token_file, tidal_session):
    import tidal_hqp.tidal.session as ts
    token_file.write_text(
        '{"token_type":"Bearer","access_token":"acc","refresh_token":"ref","expiry_time":null}'
    )
    tidal_session.load_oauth_session.return_value = False

    assert ts.load_token() is False


def test_load_token_returns_false_when_the_session_loads_but_is_not_logged_in(token_file, tidal_session):
    """A stale refresh token loads fine but fails check_login."""
    import tidal_hqp.tidal.session as ts
    token_file.write_text(
        '{"token_type":"Bearer","access_token":"acc","refresh_token":"ref","expiry_time":null}'
    )
    tidal_session.load_oauth_session.return_value = True
    tidal_session.check_login.return_value = False

    assert ts.load_token() is False


def test_load_token_survives_a_raising_session(token_file, tidal_session):
    import tidal_hqp.tidal.session as ts
    token_file.write_text(
        '{"token_type":"Bearer","access_token":"acc","refresh_token":"ref","expiry_time":null}'
    )
    tidal_session.load_oauth_session.side_effect = Exception("network down")

    assert ts.load_token() is False
