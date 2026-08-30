"""Tests for the download path and the temp-file lifecycle.

downloader.py was the least-covered module in the repository: its whole body
could be replaced with `pass` without a test noticing, and kill_active() was
only ever reached with an empty state dict, so the unlink it exists to perform
never ran.
"""
import os
import threading
from unittest.mock import MagicMock

import pytest

from tidal_hqp.streaming.downloader import download
from tidal_hqp.streaming.state import _active, _active_lock, kill_active


# ── Fakes ────────────────────────────────────────────────────────────────────

def fake_response(chunks, *, content_length=None, raise_for_status=None):
    r = MagicMock()
    r.iter_content.return_value = iter(chunks)
    total = content_length if content_length is not None else sum(len(c) for c in chunks)
    r.headers = {"Content-Length": str(total)}
    r.raise_for_status = MagicMock(side_effect=raise_for_status)
    return r


@pytest.fixture()
def tmp_target(tmp_path):
    return str(tmp_path / "track.flac")


# ── download() ───────────────────────────────────────────────────────────────

def test_download_writes_body_to_disk(monkeypatch, tmp_target):
    monkeypatch.setattr(
        "tidal_hqp.streaming.downloader.requests.get",
        MagicMock(return_value=fake_response([b"abc", b"def"])),
    )

    download("https://cdn.tidal.com/x.flac", tmp_target)

    assert open(tmp_target, "rb").read() == b"abcdef"


def test_download_preserves_chunk_order(monkeypatch, tmp_target):
    chunks = [bytes([i]) * 1024 for i in range(8)]
    monkeypatch.setattr(
        "tidal_hqp.streaming.downloader.requests.get",
        MagicMock(return_value=fake_response(chunks)),
    )

    download("https://cdn.tidal.com/x.flac", tmp_target)

    assert open(tmp_target, "rb").read() == b"".join(chunks)


def test_download_publishes_content_length(monkeypatch, tmp_target):
    monkeypatch.setattr(
        "tidal_hqp.streaming.downloader.requests.get",
        MagicMock(return_value=fake_response([b"x" * 10], content_length=4096)),
    )

    download("https://cdn.tidal.com/x.flac", tmp_target)

    with _active_lock:
        assert _active["content_length"] == 4096


def test_download_requests_a_streaming_response(monkeypatch, tmp_target):
    """Buffering a hi-res FLAC into memory would defeat the prebuffer design."""
    get = MagicMock(return_value=fake_response([b"x"]))
    monkeypatch.setattr("tidal_hqp.streaming.downloader.requests.get", get)

    download("https://cdn.tidal.com/x.flac", tmp_target)

    assert get.call_args.kwargs["stream"] is True
    assert get.call_args.kwargs["timeout"] == 30


def test_download_treats_a_missing_content_length_as_zero(monkeypatch, tmp_target):
    resp = fake_response([b"x"])
    resp.headers = {}
    monkeypatch.setattr("tidal_hqp.streaming.downloader.requests.get", MagicMock(return_value=resp))

    download("https://cdn.tidal.com/x.flac", tmp_target)

    with _active_lock:
        assert _active["content_length"] == 0


# ── download() failure paths ─────────────────────────────────────────────────

def test_download_swallows_connection_errors(monkeypatch, tmp_target):
    """The download runs in a daemon thread, so it must never raise."""
    monkeypatch.setattr(
        "tidal_hqp.streaming.downloader.requests.get",
        MagicMock(side_effect=OSError("connection reset")),
    )

    download("https://cdn.tidal.com/x.flac", tmp_target)  # must not raise

    assert not os.path.exists(tmp_target)


def test_download_swallows_http_errors(monkeypatch, tmp_target):
    monkeypatch.setattr(
        "tidal_hqp.streaming.downloader.requests.get",
        MagicMock(return_value=fake_response([b"x"], raise_for_status=Exception("404"))),
    )

    download("https://cdn.tidal.com/x.flac", tmp_target)  # must not raise

    with _active_lock:
        assert "content_length" not in _active, "a failed download must not publish a length"


def test_download_reports_the_error(monkeypatch, tmp_target, capsys):
    monkeypatch.setattr(
        "tidal_hqp.streaming.downloader.requests.get",
        MagicMock(side_effect=OSError("connection reset")),
    )

    download("https://cdn.tidal.com/x.flac", tmp_target)

    assert "connection reset" in capsys.readouterr().out


# ── kill_active() ────────────────────────────────────────────────────────────

def test_kill_active_removes_the_temp_file(fake_flac):
    with _active_lock:
        _active["tmp_path"] = fake_flac
        _active["content_length"] = 100_000
        _active["dl_thread"] = None

    kill_active()

    assert not os.path.exists(fake_flac), "the temp file must be deleted"


def test_kill_active_clears_every_key(fake_flac):
    with _active_lock:
        _active["tmp_path"] = fake_flac
        _active["content_length"] = 100_000
        _active["dl_thread"] = threading.Thread(target=lambda: None)

    kill_active()

    with _active_lock:
        assert _active == {}


def test_kill_active_is_safe_when_nothing_is_active():
    kill_active()  # must not raise
    with _active_lock:
        assert _active == {}


def test_kill_active_is_safe_when_the_file_is_already_gone(tmp_path):
    missing = str(tmp_path / "never-written.flac")
    with _active_lock:
        _active["tmp_path"] = missing

    kill_active()  # must not raise

    with _active_lock:
        assert _active == {}


def test_kill_active_twice_is_idempotent(fake_flac):
    with _active_lock:
        _active["tmp_path"] = fake_flac

    kill_active()
    kill_active()

    assert not os.path.exists(fake_flac)


# ── Interaction: play twice, leak nothing ────────────────────────────────────

def test_consecutive_plays_leave_exactly_one_temp_file(monkeypatch, tmp_path):
    """play_track_id must clean up the previous track's temp file."""
    import tidal_hqp.playback.player as pp

    monkeypatch.setattr(pp, "hqp_stop", MagicMock())
    monkeypatch.setattr(pp, "hqp_play_url", MagicMock())
    monkeypatch.setattr(pp, "track_stream_url", MagicMock(return_value="https://cdn/x.flac"))
    monkeypatch.setattr(pp.tempfile, "tempdir", str(tmp_path))

    def instant_download(url, path):
        with open(path, "wb") as f:
            f.write(b"\x00" * (8 * 1024 * 1024 + 1))

    monkeypatch.setattr(pp, "download", instant_download)

    pp.play_track_id(1)
    first = _active["tmp_path"]
    pp.play_track_id(2)
    second = _active["tmp_path"]

    assert first != second
    assert not os.path.exists(first), "the previous track's temp file leaked"
    assert os.path.exists(second)

    kill_active()
