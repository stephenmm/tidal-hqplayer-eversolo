from fastapi import APIRouter
from pydantic import BaseModel

from tidal_hqp.playback.player import play_track_id, stop_playback
from tidal_hqp.playback.queue import mark_user_stopped
from tidal_hqp.tidal.session import require_login

router = APIRouter()


class PlayRequest(BaseModel):
    track_id: int


@router.post("/play")
def play(req: PlayRequest):
    """Play a single track directly (bypasses queue)."""
    require_login()
    import threading
    threading.Thread(target=play_track_id, args=(req.track_id,), daemon=True).start()
    return {"ok": True}


@router.post("/stop")
def stop():
    mark_user_stopped()
    stop_playback()
    return {"ok": True}
