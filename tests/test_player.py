"""Tests for the play path — prebuffer, handoff URL, and failure tolerance."""
import os
from unittest.mock import MagicMock

import pytest

import tidal_hqp.playback.player as pp
from tidal_hqp.streaming.state import _active, _active_lock


@pytest.fixture()
def player(monkeypatch, tmp_path):
    """Stub everything outside the player and report what it was handed."""
    calls = {"play_url": [], "stop": 0}
    monkeypatch.setattr(pp, "hqp_stop", lambda: calls.__setitem__("stop", calls["stop"] + 1))
    monkeypatch.setattr(pp, "hqp_play_url", lambda url: calls["play_url"].append(url))
    monkeypatch.setattr(pp, "track_stream_url", MagicMock(return_value="https://cdn/x.flac"))
    monkeypatch.setattr(pp.tempfile, "tempdir", str(tmp_path))
    return calls


def _writes(nbytes):
    def download(url, path):
        with open(path, "wb") as f:
            f.write(b"\x00" * nbytes)
    return download


def test_play_hands_hqplayer_the_proxy_url(player, monkeypatch):
    monkeypatch.setattr(pp, "download", _writes(pp.PREBUFFER_BYTES + 1))

    pp.play_track_id(42)

    assert player["play_url"] == [f"http://{pp.PROXY_HOST}:{pp.PROXY_PORT}/stream/42"]


def test_play_stops_the_previous_track_first(player, monkeypatch):
    monkeypatch.setattr(pp, "download", _writes(pp.PREBUFFER_BYTES + 1))

    pp.play_track_id(42)

    assert player["stop"] == 1


def test_play_survives_an_unreachable_hqplayer_on_stop(player, monkeypatch):
    """A dead HQPlayer must not stop us starting the next track."""
    monkeypatch.setattr(pp, "hqp_stop", MagicMock(side_effect=Exception("unreachable")))
    monkeypatch.setattr(pp, "download", _writes(pp.PREBUFFER_BYTES + 1))

    pp.play_track_id(42)  # must not raise

    assert len(player["play_url"]) == 1


def test_play_registers_the_temp_file_for_the_proxy(player, monkeypatch):
    monkeypatch.setattr(pp, "download", _writes(pp.PREBUFFER_BYTES + 1))

    pp.play_track_id(42)

    with _active_lock:
        assert os.path.exists(_active["tmp_path"])
        assert _active["tmp_path"].endswith(".flac")


def test_play_hands_off_early_when_the_download_ends_below_the_prebuffer(player, monkeypatch):
    """A short track must not stall for the full 30 s prebuffer deadline."""
    monkeypatch.setattr(pp, "download", _writes(1024))

    pp.play_track_id(42)

    assert len(player["play_url"]) == 1


def test_play_hands_off_when_the_download_fails_outright(player, monkeypatch):
    """A download that yields nothing must still release the handoff.

    download() swallows its own errors, so the thread simply ends having
    written no bytes — play_track_id must notice and stop waiting.
    """
    def failing(url, path):
        return  # mirrors download()'s own except-and-return

    monkeypatch.setattr(pp, "download", failing)

    pp.play_track_id(42)

    assert len(player["play_url"]) == 1


def test_play_waits_for_the_prebuffer_before_handing_off(player, monkeypatch):
    """HQPlayer must not be pointed at the proxy until enough bytes exist."""
    sizes = []

    def download(url, path):
        with open(path, "wb") as f:
            f.write(b"\x00" * (pp.PREBUFFER_BYTES + 1))

    monkeypatch.setattr(pp, "download", download)
    real_play = pp.hqp_play_url

    def record(url):
        with _active_lock:
            sizes.append(os.path.getsize(_active["tmp_path"]))
        real_play(url)

    monkeypatch.setattr(pp, "hqp_play_url", record)

    pp.play_track_id(42)

    assert sizes and sizes[0] >= pp.PREBUFFER_BYTES


def test_play_gives_up_at_the_deadline(player, monkeypatch):
    """A download that stalls forever must still hand off once time is up."""
    import threading

    release = threading.Event()

    def stalling(url, path):
        open(path, "wb").close()
        release.wait(5)

    monkeypatch.setattr(pp, "download", stalling)
    times = iter([0, 0, 100, 100, 100])
    monkeypatch.setattr(pp.time, "time", lambda: next(times))

    try:
        pp.play_track_id(42)
    finally:
        release.set()

    assert len(player["play_url"]) == 1


def test_stop_playback_calls_hqp_stop(monkeypatch):
    stopped = []
    monkeypatch.setattr(pp, "hqp_stop", lambda: stopped.append(1))

    pp.stop_playback()

    assert stopped == [1]


def test_play_tolerates_the_temp_file_vanishing_mid_prebuffer(player, monkeypatch):
    """kill_active() can unlink the file while the prebuffer poll is running."""
    monkeypatch.setattr(pp, "download", _writes(pp.PREBUFFER_BYTES + 1))

    real_getsize = pp.os.path.getsize
    calls = {"n": 0}

    def flaky_getsize(path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("file vanished")
        return real_getsize(path)

    monkeypatch.setattr(pp.os.path, "getsize", flaky_getsize)

    pp.play_track_id(42)  # must not raise

    assert len(player["play_url"]) == 1
