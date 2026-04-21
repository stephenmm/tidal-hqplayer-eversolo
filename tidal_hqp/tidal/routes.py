import time

import tidalapi
from fastapi import APIRouter

from tidal_hqp.tidal.browse import fmt_album, fmt_track
from tidal_hqp.tidal.session import pending_login, require_login, save_token, session
from tidal_hqp.config import TOKEN_FILE

router = APIRouter()


@router.post("/auth/login")
def start_login():
    """Initiate OAuth device-flow. Returns a URL to open in browser; poll /auth/status."""
    global pending_login
    import tidal_hqp.tidal.session as _s
    _s.session.config = tidalapi.Config(quality=tidalapi.Quality.high_lossless)
    login, future = _s.session.login_oauth()
    _s.pending_login = {"future": future, "started": time.time()}
    url = login.verification_uri_complete
    if url and not url.startswith("http"):
        url = "https://" + url
    return {"login_url": url, "expires_in": login.expires_in}


@router.get("/auth/status")
def auth_status():
    import tidal_hqp.tidal.session as _s
    logged_in = _s.session.check_login()
    if logged_in and _s.pending_login:
        save_token()
        _s.pending_login = None
    return {
        "logged_in": logged_in,
        "user": _s.session.user.email if logged_in else None,
    }


@router.post("/auth/logout")
def logout():
    TOKEN_FILE.unlink(missing_ok=True)
    return {"ok": True}


@router.get("/tidal/search")
def search(q: str, limit: int = 20):
    require_login()
    import tidal_hqp.tidal.session as _s
    results = _s.session.search(q, [tidalapi.Track, tidalapi.Album, tidalapi.Artist], limit=limit)
    return {
        "tracks": [fmt_track(t) for t in (results.tracks or [])],
        "albums": [fmt_album(a) for a in (results.albums or [])],
    }


@router.get("/tidal/album/{album_id}/tracks")
def album_tracks(album_id: int):
    require_login()
    import tidal_hqp.tidal.session as _s
    return [fmt_track(t) for t in _s.session.album(album_id).tracks()]


@router.get("/tidal/favorites/tracks")
def fav_tracks(limit: int = 50):
    require_login()
    import tidal_hqp.tidal.session as _s
    return [fmt_track(t) for t in _s.session.user.favorites.tracks(limit=limit)]


@router.get("/tidal/favorites/albums")
def fav_albums(limit: int = 50):
    require_login()
    import tidal_hqp.tidal.session as _s
    return [fmt_album(a) for a in _s.session.user.favorites.albums(limit=limit)]


@router.get("/tidal/playlists")
def playlists():
    require_login()
    import tidal_hqp.tidal.session as _s
    return [
        {"id": p.id, "name": p.name, "num_tracks": p.num_tracks}
        for p in _s.session.user.playlists()
    ]


@router.get("/tidal/playlist/{playlist_id}/tracks")
def playlist_tracks(playlist_id: str):
    require_login()
    import tidal_hqp.tidal.session as _s
    return [fmt_track(t) for t in _s.session.playlist(playlist_id).tracks()]
