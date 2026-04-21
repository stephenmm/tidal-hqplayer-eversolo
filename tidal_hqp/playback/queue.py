"""Queue state singleton and auto-advance monitor thread."""
import random
import threading
import time

from tidal_hqp.hqplayer.client import hqp_status, hqp_stop

_queue: dict = {
    "tracks":        [],    # list[dict] — {id, title, artist, album, duration}
    "current_index": None,  # int | None
    "shuffle":       False,
    "shuffle_order": [],    # permuted indices, rebuilt on every shuffle toggle
    "loading":       False, # True while prebuffer is in progress — blocks monitor
    "user_stopped":  False, # True after explicit stop; cleared when next track starts
}
_queue_lock = threading.Lock()


# ── Public helpers (called by routes) ────────────────────────────────────────

def get_state() -> dict:
    with _queue_lock:
        return {
            "tracks":        list(_queue["tracks"]),
            "current_index": _queue["current_index"],
            "shuffle":       _queue["shuffle"],
            "loading":       _queue["loading"],
        }


def set_queue(tracks: list[dict], play_index: int) -> None:
    """Replace queue and start playing at play_index."""
    with _queue_lock:
        _queue["tracks"]        = list(tracks)
        _queue["current_index"] = None
        _queue["user_stopped"]  = False
        _rebuild_shuffle_order_locked()
    _do_play(play_index)


def append_track(track: dict) -> int:
    """Append one track. Returns new queue length."""
    with _queue_lock:
        _queue["tracks"].append(track)
        if _queue["shuffle"]:
            insert_at = random.randint(
                (_queue["current_index"] or 0) + 1,
                len(_queue["tracks"]) - 1,
            )
            _queue["shuffle_order"].insert(insert_at, len(_queue["tracks"]) - 1)
        return len(_queue["tracks"])


def remove_track(index: int) -> bool:
    """Remove track at index. Returns True if the current track was removed (playback stopped)."""
    with _queue_lock:
        if index < 0 or index >= len(_queue["tracks"]):
            return False
        _queue["tracks"].pop(index)
        current_removed = _queue["current_index"] == index
        if current_removed:
            _queue["user_stopped"] = True
            _queue["current_index"] = None
        elif _queue["current_index"] is not None and index < _queue["current_index"]:
            _queue["current_index"] -= 1
        _rebuild_shuffle_order_locked()
        return current_removed


def set_shuffle(enabled: bool) -> None:
    with _queue_lock:
        _queue["shuffle"] = enabled
        _rebuild_shuffle_order_locked()


def skip_next() -> bool:
    """Advance to next track. Returns False if at end of queue."""
    idx = _next_index()
    if idx is None:
        return False
    _do_play(idx)
    return True


def skip_previous() -> bool:
    """Go to previous track. Returns False if at start."""
    idx = _prev_index()
    if idx is None:
        return False
    _do_play(idx)
    return True


def mark_user_stopped() -> None:
    with _queue_lock:
        _queue["user_stopped"] = True


# ── Internal ──────────────────────────────────────────────────────────────────

def _rebuild_shuffle_order_locked() -> None:
    n = len(_queue["tracks"])
    order = list(range(n))
    random.shuffle(order)
    cur = _queue["current_index"]
    if cur is not None and cur in order:
        order.remove(cur)
        order.insert(0, cur)
    _queue["shuffle_order"] = order


def _next_index() -> int | None:
    with _queue_lock:
        tracks = _queue["tracks"]
        cur    = _queue["current_index"]
        if not tracks:
            return None
        if _queue["shuffle"]:
            order = _queue["shuffle_order"]
            if cur is None:
                return order[0] if order else None
            try:
                pos = order.index(cur)
                return order[pos + 1] if pos + 1 < len(order) else None
            except ValueError:
                return order[0] if order else None
        else:
            if cur is None:
                return 0
            return cur + 1 if cur + 1 < len(tracks) else None


def _prev_index() -> int | None:
    with _queue_lock:
        tracks = _queue["tracks"]
        cur    = _queue["current_index"]
        if not tracks or cur is None:
            return None
        if _queue["shuffle"]:
            order = _queue["shuffle_order"]
            try:
                pos = order.index(cur)
                return order[pos - 1] if pos > 0 else None
            except ValueError:
                return None
        else:
            return cur - 1 if cur > 0 else None


def _do_play(index: int) -> None:
    """Internal: set loading state, play the track, update current_index."""
    with _queue_lock:
        if index < 0 or index >= len(_queue["tracks"]):
            return
        track = _queue["tracks"][index]
        _queue["loading"]      = True
        _queue["user_stopped"] = False
        _queue["current_index"] = index

    # Import here to avoid circular import at module load time
    from tidal_hqp.playback.player import play_track_id
    try:
        play_track_id(track["id"])
    except Exception as e:
        print(f"[queue] play error: {e}", flush=True)
    finally:
        with _queue_lock:
            _queue["loading"] = False


# ── Monitor thread ────────────────────────────────────────────────────────────

def _monitor_loop() -> None:
    prev_state = None
    while True:
        time.sleep(0.5)
        try:
            status = hqp_status()
        except Exception:
            prev_state = None
            continue

        with _queue_lock:
            loading      = _queue["loading"]
            user_stopped = _queue["user_stopped"]
            current      = _queue["current_index"]

        state = int(status.get("state", 0))

        if loading:
            prev_state = state
            continue

        if state != prev_state:
            print(f"[monitor] state {prev_state}→{state}  current={current}  user_stopped={user_stopped}", flush=True)

        if prev_state == 2 and state == 0 and not user_stopped and current is not None:
            next_idx = _next_index()
            if next_idx is not None:
                print(f"[monitor] auto-advance → {next_idx}", flush=True)
                threading.Thread(target=_do_play, args=(next_idx,), daemon=True).start()
            else:
                print("[monitor] end of queue — stopping HQPlayer", flush=True)
                try:
                    hqp_stop()
                except Exception:
                    pass
                with _queue_lock:
                    _queue["user_stopped"] = True

        prev_state = state


threading.Thread(target=_monitor_loop, daemon=True, name="queue-monitor").start()
