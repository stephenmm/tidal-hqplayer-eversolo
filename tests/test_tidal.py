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


def test_track_stream_url_always_uses_get_url(monkeypatch):
    """track_stream_url must use get_url() for the download URL.

    Manifest URLs from get_stream() may be MPEG-DASH segments and are not
    directly downloadable as FLAC — get_url() returns a direct CDN link.
    """
    import tidal_hqp.tidal.session as ts

    direct_url = "https://cdn.tidal.com/lossless/track.flac"
    stream = MagicMock()
    stream.audio_quality = "HI_RES_LOSSLESS"

    fake_track = MagicMock()
    fake_track.name = "Test Track"
    fake_track.audio_quality = "HI_RES_LOSSLESS"
    fake_track.get_stream.return_value = stream
    fake_track.get_url.return_value = direct_url

    monkeypatch.setattr(ts.session, "track", lambda _id: fake_track)

    url = ts.track_stream_url(42)

    fake_track.get_url.assert_called_once()
    assert url == direct_url


def test_track_stream_url_uses_get_stream_for_quality_only(monkeypatch):
    """get_stream() is called for the quality label but its URLs are never used."""
    import tidal_hqp.tidal.session as ts

    stream = MagicMock()
    stream.audio_quality = "HI_RES_LOSSLESS"

    fake_track = MagicMock()
    fake_track.name = "Test Track"
    fake_track.audio_quality = "HI_RES_LOSSLESS"
    fake_track.get_stream.return_value = stream
    fake_track.get_url.return_value = "https://cdn.tidal.com/track.flac"

    monkeypatch.setattr(ts.session, "track", lambda _id: fake_track)
    ts.track_stream_url(42)

    fake_track.get_stream.assert_called_once()
    stream.get_stream_manifest.assert_not_called()
    assert ts.last_stream_quality == "HI_RES_LOSSLESS"


def test_track_stream_url_quality_falls_back_when_stream_fails(monkeypatch):
    """If get_stream() raises, quality falls back to track.audio_quality."""
    import tidal_hqp.tidal.session as ts

    fake_track = MagicMock()
    fake_track.name = "Test Track"
    fake_track.audio_quality = "LOSSLESS"
    fake_track.get_stream.side_effect = Exception("unavailable")
    fake_track.get_url.return_value = "https://cdn.tidal.com/track.flac"

    monkeypatch.setattr(ts.session, "track", lambda _id: fake_track)
    ts.track_stream_url(42)

    fake_track.get_url.assert_called_once()
    assert ts.last_stream_quality == "LOSSLESS"


def test_track_stream_url_logs_quality(monkeypatch, capsys):
    """Quality info must be printed so it appears in server logs."""
    import tidal_hqp.tidal.session as ts

    stream = MagicMock()
    stream.audio_quality = "HI_RES_LOSSLESS"

    fake_track = MagicMock()
    fake_track.name = "Hi-Res Song"
    fake_track.audio_quality = "HI_RES_LOSSLESS"
    fake_track.get_stream.return_value = stream
    fake_track.get_url.return_value = "https://cdn.tidal.com/track.flac"

    monkeypatch.setattr(ts.session, "track", lambda _id: fake_track)
    ts.track_stream_url(99)

    assert "HI_RES_LOSSLESS" in capsys.readouterr().out
