"""Tests for queue state management and queue routes."""
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


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
#
# These drive the real _monitor_tick(). Do not re-implement its condition in the
# test — that is what the previous version of this file did, and it meant the
# whole auto-advance block could be deleted without a test failing.

@pytest.fixture()
def monitor(monkeypatch):
    """Drive _monitor_tick with a scripted HQPlayer state and record dispatches."""
    import tidal_hqp.playback.queue as Q

    rec = {"played": [], "stopped": 0}
    monkeypatch.setattr(Q, "_dispatch_play", lambda idx: rec["played"].append(idx))
    monkeypatch.setattr(Q, "hqp_stop", lambda: rec.__setitem__("stopped", rec["stopped"] + 1))

    def run(states, prev_state=None):
        """Feed each state through a tick; returns the recorder."""
        for st in states:
            if isinstance(st, Exception):
                monkeypatch.setattr(Q, "hqp_status", MagicMock(side_effect=st))
            else:
                monkeypatch.setattr(Q, "hqp_status", lambda st=st: {"state": st})
            prev_state = Q._monitor_tick(prev_state)
        rec["prev_state"] = prev_state
        return rec

    return run


def test_monitor_advances_on_natural_end(monitor, queued):
    """Playing → stopped with no user stop must advance to the next track."""
    queued(TRACKS, current_index=0)
    rec = monitor([2, 0])
    assert rec["played"] == [1]
    assert rec["stopped"] == 0


def test_monitor_does_not_advance_when_user_stopped(monitor, queued):
    """An explicit stop must suppress auto-advance."""
    queued(TRACKS, current_index=0, user_stopped=True)
    rec = monitor([2, 0])
    assert rec["played"] == []


def test_monitor_does_not_advance_while_loading(monitor, queued):
    """A prebuffer in progress must suppress auto-advance."""
    queued(TRACKS, current_index=0, loading=True)
    rec = monitor([2, 0])
    assert rec["played"] == []


def test_monitor_does_not_advance_without_current_track(monitor, queued):
    """With no current track there is nothing to advance from."""
    queued(TRACKS, current_index=None)
    rec = monitor([2, 0])
    assert rec["played"] == []


def test_monitor_ignores_states_that_are_not_a_2_to_0_transition(monitor, queued):
    """Only the playing→stopped edge advances; steady states must not."""
    queued(TRACKS, current_index=0)
    assert monitor([2, 2, 2])["played"] == []

    queued(TRACKS, current_index=0)
    assert monitor([0, 0])["played"] == []

    queued(TRACKS, current_index=0)
    assert monitor([0, 2])["played"] == []


def test_monitor_stops_hqplayer_at_end_of_queue(monitor, queued):
    """The last track ending must stop HQPlayer and latch user_stopped."""
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=2)

    rec = monitor([2, 0])

    assert rec["played"] == []
    assert rec["stopped"] == 1
    with Q._queue_lock:
        assert Q._queue["user_stopped"] is True


def test_monitor_end_of_queue_survives_hqp_stop_failure(monitor, queued, monkeypatch):
    """A failing hqp_stop must not stop the monitor latching user_stopped."""
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=2)
    monkeypatch.setattr(Q, "hqp_stop", MagicMock(side_effect=Exception("unreachable")))

    monitor([2, 0])

    with Q._queue_lock:
        assert Q._queue["user_stopped"] is True


def test_monitor_resets_prev_state_when_hqplayer_unreachable(monitor, queued):
    """A failed status read must reset prev_state, not carry a stale 2 across."""
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=0)

    rec = monitor([2, Exception("unreachable")])
    assert rec["prev_state"] is None

    # The 0 that follows the outage is not a 2→0 edge, so nothing advances.
    rec = monitor([0], prev_state=rec["prev_state"])
    assert rec["played"] == []


def test_monitor_advances_in_shuffle_order(monitor, queued):
    """Auto-advance must follow shuffle_order, not the track order."""
    queued(TRACKS, current_index=2, shuffle=True, shuffle_order=[2, 0, 1])
    rec = monitor([2, 0])
    assert rec["played"] == [0]


def test_monitor_tick_returns_state_for_next_call(monitor, queued):
    """The tick must hand back the state it saw, so the loop can compare edges."""
    queued(TRACKS, current_index=0)
    assert monitor([2])["prev_state"] == 2
    assert monitor([0])["prev_state"] == 0


def test_start_monitor_is_not_an_import_side_effect():
    """Importing the queue module must not start the polling thread."""
    import threading
    import tidal_hqp.playback.queue as Q

    assert Q._monitor_thread is None or not Q._monitor_thread.is_alive(), (
        "the monitor thread must be started by start_monitor(), not on import"
    )
    assert not [t for t in threading.enumerate() if t.name == "queue-monitor"]


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


# ── set_queue / _do_play ──────────────────────────────────────────────────────

@pytest.fixture()
def no_play(monkeypatch):
    """Capture play_track_id calls instead of hitting Tidal and HQPlayer."""
    import tidal_hqp.playback.player as pp
    played = []
    monkeypatch.setattr(pp, "play_track_id", lambda tid: played.append(tid))
    return played


def test_set_queue_replaces_tracks_and_plays(no_play):
    import tidal_hqp.playback.queue as Q

    Q.set_queue(TRACKS, 1)

    state = Q.get_state()
    assert [t["id"] for t in state["tracks"]] == [1, 2, 3]
    assert state["current_index"] == 1
    assert no_play == [2]


def test_set_queue_clears_a_previous_user_stop(no_play, queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=0, user_stopped=True)

    Q.set_queue(TRACKS, 0)

    with Q._queue_lock:
        assert Q._queue["user_stopped"] is False


def test_set_queue_copies_the_track_list(no_play):
    """The caller's list must not stay wired to queue state."""
    import tidal_hqp.playback.queue as Q
    caller = list(TRACKS)

    Q.set_queue(caller, 0)
    caller.append({"id": 99})

    assert len(Q.get_state()["tracks"]) == 3


def test_set_queue_with_an_out_of_range_index_plays_nothing(no_play):
    import tidal_hqp.playback.queue as Q

    Q.set_queue(TRACKS, 99)

    assert no_play == []
    assert Q.get_state()["current_index"] is None


def test_do_play_sets_then_clears_loading(monkeypatch, queued):
    import tidal_hqp.playback.player as pp
    import tidal_hqp.playback.queue as Q
    queued(TRACKS)

    seen = {}
    monkeypatch.setattr(pp, "play_track_id", lambda tid: seen.update(loading=Q._queue["loading"]))

    Q._do_play(0)

    assert seen["loading"] is True, "loading must be set while the track prebuffers"
    assert Q.get_state()["loading"] is False, "loading must be cleared afterwards"


def test_do_play_clears_loading_even_when_playback_raises(monkeypatch, queued):
    import tidal_hqp.playback.player as pp
    import tidal_hqp.playback.queue as Q
    queued(TRACKS)
    monkeypatch.setattr(pp, "play_track_id", MagicMock(side_effect=Exception("tidal down")))

    Q._do_play(0)  # must not raise

    assert Q.get_state()["loading"] is False
    assert Q.get_state()["current_index"] == 0


def test_do_play_ignores_an_out_of_range_index(no_play, queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS)

    Q._do_play(-1)
    Q._do_play(3)

    assert no_play == []
    assert Q.get_state()["current_index"] is None


def test_do_play_clears_user_stopped(no_play, queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, user_stopped=True)

    Q._do_play(0)

    with Q._queue_lock:
        assert Q._queue["user_stopped"] is False


def test_dispatch_play_runs_off_the_caller_thread(monkeypatch, queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS)
    done = threading.Event()
    monkeypatch.setattr(Q, "_do_play", lambda idx: done.set())

    Q._dispatch_play(0)

    assert done.wait(3), "_dispatch_play must actually run _do_play"


# ── skip_next / skip_previous ────────────────────────────────────────────────

def test_skip_next_advances_and_plays(no_play, queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=0)

    assert Q.skip_next() is True
    assert no_play == [2]
    assert Q.get_state()["current_index"] == 1


def test_skip_next_at_the_end_returns_false(no_play, queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=2)

    assert Q.skip_next() is False
    assert no_play == []


def test_skip_next_on_an_empty_queue_returns_false(no_play):
    import tidal_hqp.playback.queue as Q
    assert Q.skip_next() is False


def test_skip_next_from_idle_starts_at_the_first_track(no_play, queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=None)

    assert Q.skip_next() is True
    assert no_play == [1]


def test_skip_previous_goes_back_and_plays(no_play, queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=2)

    assert Q.skip_previous() is True
    assert no_play == [2]
    assert Q.get_state()["current_index"] == 1


def test_skip_previous_at_the_start_returns_false(no_play, queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=0)

    assert Q.skip_previous() is False
    assert no_play == []


def test_skip_previous_when_idle_returns_false(no_play, queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=None)
    assert Q.skip_previous() is False


# ── Shuffle traversal ────────────────────────────────────────────────────────

def test_next_index_in_shuffle_from_idle_takes_the_first_of_the_order(queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=None, shuffle=True, shuffle_order=[2, 0, 1])
    assert Q._next_index() == 2


def test_next_index_in_shuffle_at_the_end_returns_none(queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=1, shuffle=True, shuffle_order=[2, 0, 1])
    assert Q._next_index() is None


def test_next_index_recovers_when_current_is_not_in_the_order(queued):
    """A stale shuffle_order must not crash traversal."""
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=2, shuffle=True, shuffle_order=[0, 1])
    assert Q._next_index() == 0


def test_prev_index_in_shuffle_walks_back_through_the_order(queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=0, shuffle=True, shuffle_order=[2, 0, 1])
    assert Q._prev_index() == 2


def test_prev_index_at_the_start_of_the_order_returns_none(queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=2, shuffle=True, shuffle_order=[2, 0, 1])
    assert Q._prev_index() is None


def test_prev_index_returns_none_when_current_is_not_in_the_order(queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=2, shuffle=True, shuffle_order=[0, 1])
    assert Q._prev_index() is None


def test_next_index_on_an_empty_queue_returns_none():
    import tidal_hqp.playback.queue as Q
    assert Q._next_index() is None


# ── append / remove edge cases ───────────────────────────────────────────────

def test_append_in_shuffle_mode_queues_the_track_after_the_current_one(queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=0, shuffle=True, shuffle_order=[0, 1, 2])

    Q.append_track({"id": 4, "title": "Delta"})

    with Q._queue_lock:
        order = Q._queue["shuffle_order"]
    assert sorted(order) == [0, 1, 2, 3], "the new track must enter the shuffle order"
    assert order.index(3) > 0, "it must not be scheduled before the current track"


def test_remove_track_rejects_an_out_of_range_index(queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=0)

    assert Q.remove_track(99) is False
    assert Q.remove_track(-1) is False
    assert len(Q.get_state()["tracks"]) == 3


def test_remove_track_after_current_leaves_the_index_alone(queued):
    import tidal_hqp.playback.queue as Q
    queued(TRACKS, current_index=0)

    Q.remove_track(2)

    assert Q.get_state()["current_index"] == 0


# ── Monitor loop plumbing ────────────────────────────────────────────────────

def test_monitor_loop_feeds_prev_state_forward(monkeypatch):
    """The loop must thread each tick's return value into the next call."""
    import tidal_hqp.playback.queue as Q

    class Stop(Exception):
        pass

    seen = []

    def fake_tick(prev):
        seen.append(prev)
        if len(seen) == 3:
            raise Stop()
        return len(seen)

    monkeypatch.setattr(Q, "_monitor_tick", fake_tick)
    monkeypatch.setattr(Q.time, "sleep", lambda _s: None)

    with pytest.raises(Stop):
        Q._monitor_loop()

    assert seen == [None, 1, 2]


def test_start_monitor_is_idempotent(monkeypatch):
    """Repeat calls must not pile up polling threads."""
    import tidal_hqp.playback.queue as Q

    release = threading.Event()
    monkeypatch.setattr(Q, "_monitor_loop", lambda: release.wait(5))
    monkeypatch.setattr(Q, "_monitor_thread", None)

    first = Q.start_monitor()
    second = Q.start_monitor()

    try:
        assert first is second
        assert first.name == "queue-monitor"
        assert first.daemon is True
    finally:
        release.set()
        first.join(timeout=5)
