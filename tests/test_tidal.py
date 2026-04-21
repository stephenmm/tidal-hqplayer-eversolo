"""Tests for Tidal helpers — formatting and session guards."""
from unittest.mock import MagicMock

import pytest

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

    ts.session.check_login.return_value = False

    with pytest.raises(HTTPException) as exc:
        ts.require_login()

    assert exc.value.status_code == 401
