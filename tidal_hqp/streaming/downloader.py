import requests

from tidal_hqp.streaming.state import _active, _active_lock


def download(tidal_url: str, tmp_path: str) -> None:
    """Stream a Tidal FLAC URL into tmp_path. Runs in a background thread."""
    try:
        r = requests.get(tidal_url, stream=True, timeout=30)
        r.raise_for_status()
        with _active_lock:
            _active["content_length"] = int(r.headers.get("Content-Length", 0))
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
    except Exception as e:
        print(f"[dl] error: {e}", flush=True)
