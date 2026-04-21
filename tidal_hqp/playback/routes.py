import os
import tempfile
import threading
import time

from fastapi import APIRouter
from pydantic import BaseModel

from tidal_hqp.config import PREBUFFER_BYTES, PROXY_HOST, PROXY_PORT
from tidal_hqp.hqplayer.client import hqp_play_url, hqp_stop
from tidal_hqp.streaming.downloader import download
from tidal_hqp.streaming.state import _active, _active_lock, kill_active
from tidal_hqp.tidal.session import require_login, track_stream_url

router = APIRouter()


class PlayRequest(BaseModel):
    track_id: int


@router.post("/play")
def play(req: PlayRequest):
    """Download Tidal FLAC to a temp file, then tell HQPlayer to play via localhost proxy."""
    require_login()
    try:
        hqp_stop()
    except Exception:
        pass
    kill_active()

    tidal_url = track_stream_url(req.track_id)

    tmp = tempfile.NamedTemporaryFile(suffix=".flac", delete=False)
    tmp_path = tmp.name
    tmp.close()

    t = threading.Thread(target=download, args=(tidal_url, tmp_path), daemon=True)
    with _active_lock:
        _active["tmp_path"]  = tmp_path
        _active["dl_thread"] = t
    t.start()

    # Wait for prebuffer before handing the URL to HQPlayer
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if os.path.getsize(tmp_path) >= PREBUFFER_BYTES:
                break
        except OSError:
            pass
        if not t.is_alive():
            break
        time.sleep(0.05)

    proxy_url = f"http://{PROXY_HOST}:{PROXY_PORT}/stream/{req.track_id}"
    hqp_play_url(proxy_url)
    return {"ok": True}


@router.post("/stop")
def stop():
    hqp_stop()
    return {"ok": True}
