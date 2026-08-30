"""Tests for the Tidal browse endpoints — auth guard, response shape, empties.

These are the endpoints static/index.html consumes. Before this file existed the
`require_login()` call could be removed from every route here without a single
test failing.
"""
from unittest.mock import MagicMock

import pytest


# ── Fakes ────────────────────────────────────────────────────────────────────

def fake_track(id=1, name="Song", artist="Artist", album="Album", duration=240,
               quality="HI_RES_LOSSLESS"):
    t = MagicMock()
    t.id = id
    t.name = name
    t.artist.name = artist
    t.album.name = album
    t.duration = duration
    t.audio_quality = quality
    return t


def fake_album(id=10, name="Record", artist="Band", year=2024,
               cover="https://example.com/cover.jpg"):
    a = MagicMock()
    a.id = id
    a.name = name
    a.artist.name = artist
    a.year = year
    a.image = MagicMock(return_value=cover)
    return a


def fake_playlist(id="pl-1", name="Roadtrip", num_tracks=12):
    p = MagicMock()
    p.id = id
    p.name = name
    p.num_tracks = num_tracks
    return p


# Every route in tidal/routes.py that is behind require_login().
GUARDED_ROUTES = [
    "/tidal/search?q=hello",
    "/tidal/album/5/tracks",
    "/tidal/favorites/tracks",
    "/tidal/favorites/albums",
    "/tidal/playlists",
    "/tidal/playlist/pl-1/tracks",
]


# ── Auth guard ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", GUARDED_ROUTES)
def test_browse_routes_require_login(client, path):
    """Every browse endpoint must 401 when the session is not authenticated."""
    resp = client.get(path)
    assert resp.status_code == 401, f"{path} is reachable without a login"
    assert "Not logged in" in resp.json()["detail"]


@pytest.mark.parametrize("path", GUARDED_ROUTES)
def test_browse_routes_reachable_when_logged_in(client, logged_in_session, path):
    """The same endpoints must not 401 once authenticated."""
    logged_in_session.search.return_value = MagicMock(tracks=[], albums=[])
    logged_in_session.album.return_value.tracks.return_value = []
    logged_in_session.playlist.return_value.tracks.return_value = []
    logged_in_session.user.favorites.tracks.return_value = []
    logged_in_session.user.favorites.albums.return_value = []
    logged_in_session.user.playlists.return_value = []

    assert client.get(path).status_code == 200


# ── /tidal/search ────────────────────────────────────────────────────────────

def test_search_returns_tracks_and_albums(client, logged_in_session):
    logged_in_session.search.return_value = MagicMock(
        tracks=[fake_track(id=1, name="Alpha"), fake_track(id=2, name="Beta")],
        albums=[fake_album(id=9, name="Record")],
    )

    body = client.get("/tidal/search?q=alpha").json()

    assert [t["id"] for t in body["tracks"]] == [1, 2]
    assert body["tracks"][0]["title"] == "Alpha"
    assert body["tracks"][0]["quality"] == "HI_RES_LOSSLESS"
    assert body["albums"] == [{
        "id": 9, "title": "Record", "artist": "Band",
        "year": 2024, "cover": "https://example.com/cover.jpg",
    }]


def test_search_passes_query_and_limit_through(client, logged_in_session):
    logged_in_session.search.return_value = MagicMock(tracks=[], albums=[])

    client.get("/tidal/search?q=miles%20davis&limit=5")

    args, kwargs = logged_in_session.search.call_args
    assert args[0] == "miles davis"
    assert kwargs["limit"] == 5


def test_search_defaults_to_limit_20(client, logged_in_session):
    logged_in_session.search.return_value = MagicMock(tracks=[], albums=[])
    client.get("/tidal/search?q=x")
    assert logged_in_session.search.call_args.kwargs["limit"] == 20


def test_search_handles_none_results(client, logged_in_session):
    """tidalapi returns None rather than [] for an empty facet."""
    logged_in_session.search.return_value = MagicMock(tracks=None, albums=None)

    body = client.get("/tidal/search?q=nothing").json()

    assert body == {"tracks": [], "albums": []}


def test_search_requires_the_q_parameter(client, logged_in_session):
    assert client.get("/tidal/search").status_code == 422


# ── /tidal/album/{id}/tracks ─────────────────────────────────────────────────

def test_album_tracks_returns_formatted_tracks(client, logged_in_session):
    logged_in_session.album.return_value.tracks.return_value = [
        fake_track(id=11, name="One"), fake_track(id=12, name="Two"),
    ]

    body = client.get("/tidal/album/77/tracks").json()

    logged_in_session.album.assert_called_once_with(77)
    assert [t["title"] for t in body] == ["One", "Two"]


def test_album_tracks_rejects_a_non_numeric_id(client, logged_in_session):
    assert client.get("/tidal/album/not-a-number/tracks").status_code == 422


# ── /tidal/favorites ─────────────────────────────────────────────────────────

def test_favorite_tracks_returns_formatted_tracks(client, logged_in_session):
    logged_in_session.user.favorites.tracks.return_value = [fake_track(id=3, name="Fav")]

    body = client.get("/tidal/favorites/tracks").json()

    assert body[0]["id"] == 3 and body[0]["title"] == "Fav"
    assert logged_in_session.user.favorites.tracks.call_args.kwargs["limit"] == 50


def test_favorite_albums_returns_formatted_albums(client, logged_in_session):
    logged_in_session.user.favorites.albums.return_value = [fake_album(id=4, name="FavRec")]

    body = client.get("/tidal/favorites/albums?limit=7").json()

    assert body[0]["id"] == 4 and body[0]["title"] == "FavRec"
    assert logged_in_session.user.favorites.albums.call_args.kwargs["limit"] == 7


def test_favorites_empty_returns_empty_list(client, logged_in_session):
    logged_in_session.user.favorites.tracks.return_value = []
    assert client.get("/tidal/favorites/tracks").json() == []


# ── /tidal/playlists ─────────────────────────────────────────────────────────

def test_playlists_returns_id_name_and_count(client, logged_in_session):
    logged_in_session.user.playlists.return_value = [
        fake_playlist(id="a", name="Roadtrip", num_tracks=12),
        fake_playlist(id="b", name="Focus", num_tracks=40),
    ]

    body = client.get("/tidal/playlists").json()

    assert body == [
        {"id": "a", "name": "Roadtrip", "num_tracks": 12},
        {"id": "b", "name": "Focus", "num_tracks": 40},
    ]


def test_playlist_tracks_returns_formatted_tracks(client, logged_in_session):
    logged_in_session.playlist.return_value.tracks.return_value = [
        fake_track(id=21, name="Track A"),
    ]

    body = client.get("/tidal/playlist/pl-99/tracks").json()

    logged_in_session.playlist.assert_called_once_with("pl-99")
    assert body[0]["title"] == "Track A"


# ── Track formatting through the route ───────────────────────────────────────

def test_track_payload_carries_every_field_the_frontend_reads(client, logged_in_session):
    """static/index.html reads id, title, artist, album, duration and quality."""
    logged_in_session.user.favorites.tracks.return_value = [
        fake_track(id=1, name="T", artist="A", album="B", duration=305, quality="LOSSLESS"),
    ]

    track = client.get("/tidal/favorites/tracks").json()[0]

    assert track == {
        "id": 1, "title": "T", "artist": "A", "album": "B",
        "duration": 305, "quality": "LOSSLESS",
    }


def test_track_payload_survives_a_missing_artist_and_album(client, logged_in_session):
    t = fake_track()
    t.artist = None
    t.album = None
    logged_in_session.user.favorites.tracks.return_value = [t]

    track = client.get("/tidal/favorites/tracks").json()[0]

    assert track["artist"] == "" and track["album"] == ""
