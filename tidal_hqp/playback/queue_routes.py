from fastapi import APIRouter
from pydantic import BaseModel

from tidal_hqp.playback import queue as Q
from tidal_hqp.tidal.session import require_login

router = APIRouter()


class QueueSetRequest(BaseModel):
    tracks: list[dict]
    play_index: int = 0


class QueueAppendRequest(BaseModel):
    track: dict


class ShuffleRequest(BaseModel):
    enabled: bool


@router.get("/queue")
def get_queue():
    return Q.get_state()


@router.post("/queue")
def set_queue(req: QueueSetRequest):
    require_login()
    import threading
    threading.Thread(
        target=Q.set_queue, args=(req.tracks, req.play_index), daemon=True
    ).start()
    return {"ok": True, "count": len(req.tracks)}


@router.post("/queue/append")
def append_track(req: QueueAppendRequest):
    require_login()
    length = Q.append_track(req.track)
    return {"ok": True, "queue_length": length}


@router.delete("/queue/{index}")
def remove_track(index: int):
    stopped = Q.remove_track(index)
    from tidal_hqp.hqplayer.client import hqp_stop
    if stopped:
        try:
            hqp_stop()
        except Exception:
            pass
    return {"ok": True, "playback_stopped": stopped}


@router.post("/queue/skip")
def skip_next():
    require_login()
    import threading
    threading.Thread(target=Q.skip_next, daemon=True).start()
    return {"ok": True}


@router.post("/queue/previous")
def skip_previous():
    require_login()
    import threading
    threading.Thread(target=Q.skip_previous, daemon=True).start()
    return {"ok": True}


@router.post("/queue/shuffle")
def set_shuffle(req: ShuffleRequest):
    Q.set_shuffle(req.enabled)
    return {"ok": True, "shuffle": req.enabled}
