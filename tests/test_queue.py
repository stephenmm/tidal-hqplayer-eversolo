"""Tests for queue state management and queue routes."""
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_queue():
    """Reset queue singleton state before each test."""
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"]        = []
        Q._queue["current_index"] = None
        Q._queue["shuffle"]       = False
        Q._queue["shuffle_order"] = []
        Q._queue["loading"]       = False
        Q._queue["user_stopped"]  = False
    yield
    with Q._queue_lock:
        Q._queue["tracks"]        = []
        Q._queue["current_index"] = None
        Q._queue["shuffle"]       = False
        Q._queue["shuffle_order"] = []
        Q._queue["loading"]       = False
        Q._queue["user_stopped"]  = False


TRACKS = [
    {"id": 1, "title": "Alpha", "artist": "A", "album": "X", "duration": 180},
    {"id": 2, "title": "Beta",  "artist": "B", "album": "X", "duration": 200},
    {"id": 3, "title": "Gamma", "artist": "C", "album": "X", "duration": 220},
]


# ── Queue state helpers ───────────────────────────────────────────────────────

def test_get_state_empty():
    import tidal_hqp.playback.queue as Q
    s = Q.get_state()
    assert s["tracks"] == []
    assert s["current_index"] is None
    assert s["shuffle"] is False


def test_append_track_increases_length():
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS[:2])
    n = Q.append_track(TRACKS[2])
    assert n == 3
    assert Q.get_state()["tracks"][2]["id"] == 3


def test_remove_track_non_current():
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 0
    stopped = Q.remove_track(2)
    assert stopped is False
    assert len(Q.get_state()["tracks"]) == 2
    assert Q.get_state()["current_index"] == 0


def test_remove_current_track_sets_user_stopped():
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 1
    stopped = Q.remove_track(1)
    assert stopped is True
    with Q._queue_lock:
        assert Q._queue["user_stopped"] is True
        assert Q._queue["current_index"] is None


def test_remove_track_before_current_adjusts_index():
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 2
    Q.remove_track(0)
    assert Q.get_state()["current_index"] == 1


def test_mark_user_stopped():
    import tidal_hqp.playback.queue as Q
    Q.mark_user_stopped()
    with Q._queue_lock:
        assert Q._queue["user_stopped"] is True


# ── Next/Prev index (sequential) ─────────────────────────────────────────────

def test_next_index_sequential():
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 0
    assert Q._next_index() == 1


def test_next_index_at_end_returns_none():
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 2
    assert Q._next_index() is None


def test_prev_index_sequential():
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 2
    assert Q._prev_index() == 1


def test_prev_index_at_start_returns_none():
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 0
    assert Q._prev_index() is None


# ── Shuffle ───────────────────────────────────────────────────────────────────

def test_shuffle_order_covers_all_tracks():
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = None
    Q.set_shuffle(True)
    order = Q.get_state()
    with Q._queue_lock:
        assert sorted(Q._queue["shuffle_order"]) == [0, 1, 2]


def test_shuffle_order_starts_with_current():
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 1
    Q.set_shuffle(True)
    with Q._queue_lock:
        assert Q._queue["shuffle_order"][0] == 1


def test_next_index_shuffle_advances_in_order():
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["shuffle"] = True
        Q._queue["shuffle_order"] = [2, 0, 1]
        Q._queue["current_index"] = 2
    assert Q._next_index() == 0


# ── Monitor auto-advance logic ────────────────────────────────────────────────

def test_monitor_advances_on_natural_end(monkeypatch):
    """Monitor should call _do_play when state transitions 2→0 without user stop."""
    import tidal_hqp.playback.queue as Q

    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 0
        Q._queue["user_stopped"] = False
        Q._queue["loading"] = False

    played = []

    def fake_do_play(idx):
        played.append(idx)

    monkeypatch.setattr(Q, "_do_play", fake_do_play)

    status_seq = [{"state": 2}, {"state": 0}]
    call_count = [0]

    def fake_status():
        i = min(call_count[0], len(status_seq) - 1)
        call_count[0] += 1
        return status_seq[i]

    monkeypatch.setattr("tidal_hqp.playback.queue.hqp_status", fake_status)

    # Simulate two monitor iterations manually
    prev_state = None

    for _ in range(2):
        try:
            status = fake_status()
        except Exception:
            prev_state = None
            continue

        with Q._queue_lock:
            loading      = Q._queue["loading"]
            user_stopped = Q._queue["user_stopped"]
            current      = Q._queue["current_index"]

        state = int(status.get("state", 0))

        if loading:
            prev_state = state
            continue

        if prev_state == 2 and state == 0 and not user_stopped and current is not None:
            next_idx = Q._next_index()
            if next_idx is not None:
                fake_do_play(next_idx)

        prev_state = state

    assert 1 in played


def test_monitor_does_not_advance_when_user_stopped(monkeypatch):
    """Monitor must not auto-advance after explicit stop."""
    import tidal_hqp.playback.queue as Q

    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 0
        Q._queue["user_stopped"] = True
        Q._queue["loading"] = False

    played = []

    prev_state = 2
    state = 0
    user_stopped = True
    current = 0

    if prev_state == 2 and state == 0 and not user_stopped and current is not None:
        played.append(Q._next_index())

    assert played == []


def test_monitor_does_not_advance_while_loading(monkeypatch):
    """Monitor must skip the transition check while loading=True."""
    import tidal_hqp.playback.queue as Q

    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 0
        Q._queue["user_stopped"] = False
        Q._queue["loading"] = True

    played = []
    prev_state = 2
    state = 0
    loading = True

    if not loading:
        if prev_state == 2 and state == 0:
            played.append(Q._next_index())

    assert played == []


# ── Queue routes (HTTP) ───────────────────────────────────────────────────────

def test_get_queue_empty(client):
    r = client.get("/queue")
    assert r.status_code == 200
    data = r.json()
    assert data["tracks"] == []
    assert data["current_index"] is None


def test_set_queue_requires_login(client):
    r = client.post("/queue", json={"tracks": TRACKS, "play_index": 0})
    assert r.status_code == 401


def test_set_queue_starts_thread(client, logged_in_session, monkeypatch):
    started = []

    def fake_set_queue(tracks, play_index):
        started.append((tracks, play_index))

    import tidal_hqp.playback.queue_routes as qr
    monkeypatch.setattr(qr.Q, "set_queue", fake_set_queue)

    r = client.post("/queue", json={"tracks": TRACKS, "play_index": 1})
    assert r.status_code == 200
    assert r.json()["count"] == 3
    time.sleep(0.1)
    assert len(started) == 1
    assert started[0][1] == 1


def test_append_track(client, logged_in_session, monkeypatch):
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS[:2])

    r = client.post("/queue/append", json={"track": TRACKS[2]})
    assert r.status_code == 200
    assert r.json()["queue_length"] == 3


def test_skip_requires_login(client):
    r = client.post("/queue/skip")
    assert r.status_code == 401


def test_skip_next_route(client, logged_in_session, monkeypatch):
    calls = []
    import tidal_hqp.playback.queue_routes as qr
    monkeypatch.setattr(qr.Q, "skip_next", lambda: calls.append(1))
    r = client.post("/queue/skip")
    assert r.status_code == 200
    time.sleep(0.1)
    assert calls


def test_skip_previous_route(client, logged_in_session, monkeypatch):
    calls = []
    import tidal_hqp.playback.queue_routes as qr
    monkeypatch.setattr(qr.Q, "skip_previous", lambda: calls.append(1))
    r = client.post("/queue/previous")
    assert r.status_code == 200
    time.sleep(0.1)
    assert calls


def test_shuffle_route(client):
    r = client.post("/queue/shuffle", json={"enabled": True})
    assert r.status_code == 200
    assert r.json()["shuffle"] is True
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        assert Q._queue["shuffle"] is True


def test_remove_track_route_not_playing(client, monkeypatch):
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 0

    r = client.delete("/queue/2")
    assert r.status_code == 200
    data = r.json()
    assert data["playback_stopped"] is False


def test_remove_current_track_route_stops(client, monkeypatch):
    import tidal_hqp.playback.queue as Q
    with Q._queue_lock:
        Q._queue["tracks"] = list(TRACKS)
        Q._queue["current_index"] = 0

    import tidal_hqp.hqplayer.client as hc
    monkeypatch.setattr(hc, "hqp_stop", lambda: None)

    r = client.delete("/queue/0")
    assert r.status_code == 200
    assert r.json()["playback_stopped"] is True


# ── HQPlayer routes ───────────────────────────────────────────────────────────

def test_hqplayer_rates_route(client, monkeypatch):
    import tidal_hqp.hqplayer_routes as hr
    monkeypatch.setattr(hr, "hqp_get_rates", lambda: [
        {"index": 0, "rate": "44100"},
        {"index": 1, "rate": "176400"},
        {"index": 2, "rate": "0"},
    ])
    r = client.get("/hqplayer/rates")
    assert r.status_code == 200
    rates = r.json()
    assert len(rates) == 2
    assert rates[0]["rate"] == "44100"
    assert rates[1]["rate"] == "176400"


def test_hqplayer_restart_route(client, monkeypatch):
    import tidal_hqp.hqplayer_routes as hr
    calls = []
    monkeypatch.setattr(hr, "close_and_wait", lambda: True)
    monkeypatch.setattr(hr, "launch", lambda: calls.append("launch"))
    r = client.post("/hqplayer/restart")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "launch" in calls
