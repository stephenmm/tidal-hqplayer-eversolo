import json
import time

import tidalapi
from fastapi import HTTPException

from tidal_hqp.config import TOKEN_FILE

# Module-level singleton — shared across all route modules.
session = tidalapi.Session(tidalapi.Config(quality=tidalapi.Quality.hi_res_lossless))

# Set by /auth/login, cleared on success.
pending_login: dict | None = None


def save_token() -> None:
    data = {
        "token_type":    session.token_type,
        "access_token":  session.access_token,
        "refresh_token": session.refresh_token,
        "expiry_time":   session.expiry_time.timestamp() if session.expiry_time else None,
    }
    TOKEN_FILE.write_text(json.dumps(data))


def load_token() -> bool:
    """Restore a saved OAuth session. Returns True if the session is valid."""
    if not TOKEN_FILE.exists():
        return False
    try:
        data = json.loads(TOKEN_FILE.read_text())
        ok = session.load_oauth_session(
            data["token_type"],
            data["access_token"],
            data["refresh_token"],
        )
        return bool(ok and session.check_login())
    except Exception:
        return False


def require_login() -> None:
    if not session.check_login():
        raise HTTPException(
            status_code=401,
            detail="Not logged in to Tidal. POST /auth/login first.",
        )


def track_stream_url(track_id: int) -> str:
    track = session.track(track_id)
    print(f"[tidal] '{track.name}' — track quality: {track.audio_quality}", flush=True)
    try:
        stream = track.get_stream()
        print(f"[tidal] stream quality: {stream.audio_quality}", flush=True)
        urls = stream.get_stream_manifest().get_urls()
        print(f"[tidal] manifest URLs: {len(urls)}", flush=True)
        return urls[0]
    except Exception as e:
        print(f"[tidal] manifest failed ({e}), falling back to get_url()", flush=True)
        return track.get_url()
