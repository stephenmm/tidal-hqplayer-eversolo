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
