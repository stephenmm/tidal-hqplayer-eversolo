import os
import threading

# Module-level singleton shared by downloader, proxy, and playback routes.
_active: dict = {}
_active_lock = threading.Lock()


def kill_active() -> None:
    """Stop any in-progress download and remove the temp file."""
    with _active_lock:
        _active.pop("dl_thread", None)
        tmp_path = _active.pop("tmp_path", None)
        _active.pop("content_length", None)
    if tmp_path:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
