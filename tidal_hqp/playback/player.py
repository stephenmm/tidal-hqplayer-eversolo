"""Core play/stop logic shared by routes and the queue auto-advance monitor."""
import os
import tempfile
import threading
import time

from tidal_hqp.config import PREBUFFER_BYTES, PROXY_HOST, PROXY_PORT
from tidal_hqp.hqplayer.client import hqp_play_url, hqp_stop
from tidal_hqp.streaming.downloader import download
from tidal_hqp.streaming.state import _active, _active_lock, kill_active
from tidal_hqp.tidal.session import track_stream_url


def play_track_id(track_id: int) -> None:
    """Download a Tidal track and hand its proxy URL to HQPlayer."""
    try:
        hqp_stop()
    except Exception:
        pass
    kill_active()

    tidal_url = track_stream_url(track_id)

    tmp = tempfile.NamedTemporaryFile(suffix=".flac", delete=False)
    tmp_path = tmp.name
    tmp.close()

    t = threading.Thread(target=download, args=(tidal_url, tmp_path), daemon=True)
    with _active_lock:
        _active["tmp_path"]  = tmp_path
        _active["dl_thread"] = t
    t.start()

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

    hqp_play_url(f"http://{PROXY_HOST}:{PROXY_PORT}/stream/{track_id}")


def stop_playback() -> None:
    hqp_stop()
