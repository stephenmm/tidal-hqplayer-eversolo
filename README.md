# tidal-hqp

Tidal → HQPlayer bridge. No Roon required.

## What it does

- Authenticates with Tidal via OAuth (opens browser, saves token)
- Browses favorites, albums, playlists, search results
- Sends stream URLs directly to HQPlayer's HTTP control API
- HQPlayer → Eversolo via NAA as normal

## Requirements

- Python 3.9+
- HQPlayer Desktop running on Windows (same machine or LAN)
- Tidal HiFi or Tidal Max subscription

## Setup

```
pip install fastapi uvicorn tidalapi requests python-dotenv
```

Copy `.env.example` to `.env` and edit:

```
HQPLAYER_HOST=localhost   # or IP if HQPlayer is on another machine
HQPLAYER_PORT=4321        # HQPlayer Desktop default control port
```

## Run

```
python server.py
```

Open http://localhost:8080 — it will walk you through Tidal login on first run.

## HQPlayer setup (one-time, in HQPlayer Desktop)

1. In HQPlayer: enable "Allow control from network" (toolbar button)
2. Set output device to your Eversolo NAA endpoint (Settings → Output → Network Audio)
3. Configure your filters/upsampling as desired — the script never touches those settings

## How the HQPlayer API works

HQPlayer Desktop listens on port 4321 for XML-over-HTTP commands.
The key endpoints used here:

- `POST /api/Play`  body: `<Play><Url>https://...tidal-stream-url...</Url></Play>`
- `POST /api/Stop`
- `GET  /api/Status`

**Important:** The exact XML schema can vary between HQPlayer versions.
If playback doesn't start, inspect what HQPlayer actually expects by looking at
the `hqp-control` source that Signalyst publishes on their downloads page.
Run `curl http://localhost:4321/api/Status` to verify the API is reachable.

## Cursor/AI instructions

The three files an AI needs to know about:

- `server.py` — all backend logic, well commented
- `static/index.html` — entire frontend, no build step
- `.env` — config

The HQPlayer API section in server.py has a comment flagging the one thing
most likely to need adjustment: the exact XML body for the Play command.
Everything else (tidalapi, FastAPI routing) has stable public docs.

## Known limitations

- Tidal's stream URLs are time-limited (typically ~30 min). For long albums
  the URL should be refreshed per-track, which is how the current code works.
- HQPlayer must be running and have "Allow control from network" enabled.
- Queue/next-track logic is not implemented — it plays one track at a time.
  Add a `currentIndex` + `autoAdvance` flag in the frontend to extend this.
