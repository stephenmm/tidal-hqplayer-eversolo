"""Tests for the HQPlayer control routes — error paths and restart/resume."""
from unittest.mock import MagicMock

import pytest

import tidal_hqp.hqplayer_routes as hr


SETTINGS = (
    '<?xml version="1.0" encoding="utf-8"?>'
    "<hqplayer>"
    '<engine adaptive_rate="0">'
    '<defaults samplerate="44100" />'
    '<network period_time="250" />'
    "</engine>"
    "</hqplayer>"
)


@pytest.fixture()
def settings_xml(tmp_path, monkeypatch):
    import tidal_hqp.hqplayer.configure as cfg
    f = tmp_path / "settings.xml"
    f.write_text(SETTINGS)
    monkeypatch.setattr(hr, "HQP_SETTINGS_XML", f)
    monkeypatch.setattr(cfg, "HQP_SETTINGS_XML", f)
    return f


@pytest.fixture()
def stub_process(monkeypatch):
    """Stub the close/launch pair that hqplayer_routes imported by name."""
    close = MagicMock(return_value=True)
    launch = MagicMock()
    monkeypatch.setattr(hr, "close_and_wait", close)
    monkeypatch.setattr(hr, "launch", launch)
    return close, launch


# ── /hqplayer/settings ───────────────────────────────────────────────────────

def test_settings_returns_current_values(client, settings_xml):
    body = client.get("/hqplayer/settings").json()
    assert body == {"samplerate": "44100", "period_time": "250", "adaptive_rate": "0"}


def test_settings_404_when_the_file_is_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(hr, "HQP_SETTINGS_XML", tmp_path / "nope.xml")

    resp = client.get("/hqplayer/settings")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "settings.xml not found"


# ── /hqplayer/configure ──────────────────────────────────────────────────────

def test_configure_404_when_the_file_is_missing(client, tmp_path, monkeypatch, stub_process):
    monkeypatch.setattr(hr, "HQP_SETTINGS_XML", tmp_path / "nope.xml")

    resp = client.post("/hqplayer/configure", json={"samplerate": 192000})

    assert resp.status_code == 404
    close, _ = stub_process
    close.assert_not_called(), "must not touch HQPlayer when there is nothing to patch"


def test_configure_500_when_hqplayer_will_not_close(client, settings_xml, monkeypatch):
    monkeypatch.setattr(hr, "close_and_wait", MagicMock(return_value=False))
    launch = MagicMock()
    monkeypatch.setattr(hr, "launch", launch)

    resp = client.post("/hqplayer/configure", json={"samplerate": 192000})

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Could not close HQPlayer"
    launch.assert_not_called(), "must not relaunch after a failed close"


def test_configure_marks_user_stopped(client, settings_xml, stub_process):
    """Otherwise the monitor auto-advances while HQPlayer is restarting."""
    import tidal_hqp.playback.queue as Q

    client.post("/hqplayer/configure", json={"samplerate": 192000})

    with Q._queue_lock:
        assert Q._queue["user_stopped"] is True


def test_configure_relaunches_after_patching(client, settings_xml, stub_process):
    close, launch = stub_process

    resp = client.post("/hqplayer/configure", json={"samplerate": 192000})

    assert resp.status_code == 200
    close.assert_called_once()
    launch.assert_called_once()


def test_configure_resumes_the_current_track(client, settings_xml, stub_process, monkeypatch, queued):
    """A restart with something playing must schedule a resume of that index."""
    resumed = []
    monkeypatch.setattr(hr.threading, "Thread",
                        lambda target, args=(), **kw: MagicMock(start=lambda: resumed.append(args)))
    queued([{"id": 1}, {"id": 2}], current_index=1)

    client.post("/hqplayer/configure", json={"samplerate": 192000})

    assert resumed == [(1,)]


def test_configure_does_not_resume_when_nothing_was_playing(client, settings_xml, stub_process, monkeypatch):
    resumed = []
    monkeypatch.setattr(hr.threading, "Thread",
                        lambda target, args=(), **kw: MagicMock(start=lambda: resumed.append(args)))

    client.post("/hqplayer/configure", json={"samplerate": 192000})

    assert resumed == []


# ── /hqplayer/restart ────────────────────────────────────────────────────────

def test_restart_500_when_hqplayer_will_not_close(client, monkeypatch):
    monkeypatch.setattr(hr, "close_and_wait", MagicMock(return_value=False))
    launch = MagicMock()
    monkeypatch.setattr(hr, "launch", launch)

    resp = client.post("/hqplayer/restart")

    assert resp.status_code == 500
    launch.assert_not_called()


def test_restart_marks_user_stopped(client, stub_process):
    import tidal_hqp.playback.queue as Q

    client.post("/hqplayer/restart")

    with Q._queue_lock:
        assert Q._queue["user_stopped"] is True


# ── /hqplayer/rates ──────────────────────────────────────────────────────────

def test_rates_filters_out_zero_rates(client, monkeypatch):
    monkeypatch.setattr(hr, "hqp_get_rates", lambda: [
        {"index": 0, "rate": "44100"},
        {"index": 1, "rate": "0"},
        {"index": 2, "rate": "705600"},
    ])

    assert [r["rate"] for r in client.get("/hqplayer/rates").json()] == ["44100", "705600"]


def test_rates_handles_an_empty_list(client, monkeypatch):
    monkeypatch.setattr(hr, "hqp_get_rates", lambda: [])
    assert client.get("/hqplayer/rates").json() == []


def test_rates_treats_a_missing_rate_key_as_zero(client, monkeypatch):
    monkeypatch.setattr(hr, "hqp_get_rates", lambda: [{"index": 0}])
    assert client.get("/hqplayer/rates").json() == []


# ── _resume_after_restart ────────────────────────────────────────────────────

def test_resume_plays_once_hqplayer_answers(monkeypatch):
    monkeypatch.setattr(hr.time, "sleep", lambda _s: None)
    monkeypatch.setattr(hr, "hqp_status", MagicMock(return_value={"state": "0"}))
    played = []
    monkeypatch.setattr("tidal_hqp.playback.queue._do_play", lambda i: played.append(i))

    hr._resume_after_restart(3)

    assert played == [3]


def test_resume_retries_until_hqplayer_is_ready(monkeypatch):
    monkeypatch.setattr(hr.time, "sleep", lambda _s: None)
    status = MagicMock(side_effect=[Exception("down"), Exception("down"), {"state": "0"}])
    monkeypatch.setattr(hr, "hqp_status", status)
    played = []
    monkeypatch.setattr("tidal_hqp.playback.queue._do_play", lambda i: played.append(i))

    hr._resume_after_restart(1)

    assert played == [1]
    assert status.call_count == 3


def test_resume_gives_up_after_the_deadline(monkeypatch, capsys):
    """HQPlayer never comes back — resume must give up, not play blindly."""
    monkeypatch.setattr(hr.time, "sleep", lambda _s: None)
    times = iter([0] + [100] * 5)
    monkeypatch.setattr(hr.time, "time", lambda: next(times))
    monkeypatch.setattr(hr, "hqp_status", MagicMock(side_effect=Exception("down")))
    played = []
    monkeypatch.setattr("tidal_hqp.playback.queue._do_play", lambda i: played.append(i))

    hr._resume_after_restart(1)

    assert played == []
    assert "never became ready" in capsys.readouterr().out


# ── Queue-state helpers ──────────────────────────────────────────────────────

def test_current_queue_index_reads_the_queue(queued):
    queued([{"id": 1}, {"id": 2}], current_index=1)
    assert hr._current_queue_index() == 1


def test_current_queue_index_is_none_when_idle():
    assert hr._current_queue_index() is None


def test_queue_helpers_tolerate_a_broken_queue_module(monkeypatch):
    """The restart path must never fail because queue state is unavailable."""
    import tidal_hqp.playback.queue as Q

    monkeypatch.setattr(Q, "get_state", MagicMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(Q, "mark_user_stopped", MagicMock(side_effect=RuntimeError("boom")))

    assert hr._current_queue_index() is None
    hr._set_user_stopped()  # must not raise
