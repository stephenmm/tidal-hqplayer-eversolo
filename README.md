# tidal-hqplayer-eversolo

Stream Tidal audio through HQPlayer Desktop to an Eversolo NAA device — no Roon required.

## What it does

- Authenticates with Tidal via OAuth device flow (browser-based, token persisted across restarts)
- Browses favorites, albums, playlists, and search results via a single-page web UI
- Downloads each track to a local temp file and serves it via a localhost HTTP proxy with full Range request support — eliminating TLS overhead and CDN jitter from HQPlayer's source pipeline
- Sends the proxy URL to HQPlayer's TCP XML control API (port 4321)
- HQPlayer upsamples and streams to the Eversolo over NAA as normal
- Exposes a `/hqplayer/configure` API to patch HQPlayer's `settings.xml` and relaunch it — useful for changing output sample rate and NAA buffer size without touching the GUI

## Architecture

```
Browser UI  ──POST /play──▶  FastAPI server  ──downloads──▶  Tidal CDN
                                   │
                          serves localhost HTTP
                                   │
                             HQPlayer Desktop  ──NAA──▶  Eversolo DAC
```

### Package layout

```
tidal_hqp/
  config.py              — all env vars (host, port, paths, prebuffer size)
  app.py                 — FastAPI app, router registration, lifespan
  hqplayer/
    client.py            — TCP XML client: hqp_send, hqp_play_url, hqp_stop, hqp_status
    configure.py         — close HQPlayer, patch settings.xml, relaunch
  tidal/
    session.py           — OAuth singleton, load/save token, require_login
    browse.py            — fmt_track, fmt_album formatters
    routes.py            — /auth/* and /tidal/* routes
  streaming/
    state.py             — _active download dict + kill_active()
    downloader.py        — background requests download thread
    proxy.py             — /stream/{id} with HTTP Range support
  playback/
    routes.py            — /play, /stop (glues tidal + hqplayer + streaming)
  hqplayer_routes.py     — /hqplayer/configure, /hqplayer/settings
static/
  index.html             — single-file frontend, no build step
tests/                   — 27 pytest tests, no real credentials needed
server.py                — 4-line entry point
```

## Requirements

- Python 3.12+
- HQPlayer Desktop 5 running on Windows
- Eversolo (or any NAA-compatible device) configured as HQPlayer's network output
- Tidal HiFi or Tidal Max subscription

## Setup

### Conda (recommended)

```bash
conda env create -f environment.yml
conda activate tidal-hqp
```

### pip

```bash
pip install fastapi uvicorn tidalapi requests python-dotenv
```

### Configuration

Copy `.env.example` to `.env`:

```env
HQPLAYER_HOST=localhost
HQPLAYER_PORT=4321
TOKEN_FILE=tidal_token.json
HQPLAYER_EXE=C:/Program Files/Signalyst/HQPlayer 5 Desktop/HQPlayer5Desktop.exe
```

## Run

```bash
python server.py
```

Open **http://localhost:8080** — on first run it will walk you through Tidal OAuth login.

## WiFi / NAA buffer tuning

HQPlayer upsamples audio and streams it to the Eversolo over the local network. At high output rates (705.6 kHz+) this requires ~45 Mbps of sustained throughput — which WiFi can struggle with. If you hear stuttering:

1. **Lower the output rate** via the API:
   ```bash
   curl -X POST http://localhost:8080/hqplayer/configure \
     -H "Content-Type: application/json" \
     -d '{"samplerate": 176400}'
   ```
   This closes HQPlayer, edits `settings.xml`, and relaunches it automatically.

2. **Increase the NAA buffer** (`period_time`) for more jitter tolerance:
   ```bash
   curl -X POST http://localhost:8080/hqplayer/configure \
     -H "Content-Type: application/json" \
     -d '{"samplerate": 176400, "period_time": 100000}'
   ```

3. Read current settings without changing anything:
   ```bash
   curl http://localhost:8080/hqplayer/settings
   ```

Confirmed stable rates over WiFi in testing: **176.4 kHz** (11 Mbps). Ethernet will support 705.6 kHz comfortably.

## HQPlayer TCP XML API

HQPlayer Desktop listens on TCP port 4321 for raw XML commands. Key commands used:

| Command | Purpose |
|---|---|
| `<PlaylistAdd uri="..." queued="0" clear="1" />` | Load a URL into the playlist |
| `<Play />` | Start playback |
| `<Stop />` | Stop playback |
| `<Status subscribe="0" />` | Get playback state, buffer fill, process speed |
| `<SetRate value="176400" />` | Change output sample rate live |
| `<GetFilters />` | List available DSP filters |
| `<Quit />` | Close HQPlayer |

The API uses raw TCP sockets (not HTTP). Protocol reverse-engineered from the [hqpwv](https://github.com/zeropointnine/hqpwv) open-source client.

## Running tests

```bash
pip install pytest httpx pytest-mock
pytest
```

All 27 tests run without real Tidal credentials or a live HQPlayer instance — sockets and sessions are fully mocked.

```bash
# With coverage
python -m coverage run -m pytest && python -m coverage report
```

## Known limitations

- Queue/next-track is not implemented — plays one track at a time
- HQPlayer must be running before the first `/play` call (unless using `/hqplayer/configure` which handles launch)
- Tidal stream URLs are time-limited; the server fetches a fresh URL per play request
