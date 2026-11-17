# roon-tidal-voice

Voice-trigger Tidal playlists in Roon and play them to the Eversolo T8.

```
"Hey Google, play <playlist>"
   -> IFTTT (Google Assistant trigger -> Webhooks)
   -> this server's /play endpoint
   -> Roon browse API finds the playlist (fuzzy match)
   -> Roon transport plays it to the T8 (Roon Ready zone)
```

Because it plays to the **T8's Roon Ready zone directly**, this path does **not** use
HQPlayer upsampling (by design — that was the choice made for voice playback). When you
want the GPU-upsampled path, just play to the **HQPlayer** zone manually in Roon, or change
`targetZone` in `config.json` to your HQPlayer zone name.

---

## Why this design

- **Tidal's API can't drive a Connect device**, and **Google killed custom Assistant Actions
  (June 2023)** — so the "direct to T8" voice approaches are dead ends.
- **Roon's extension API is stable and official**, and its *browse* module can open a specific
  playlist and start it on any zone. That's the reliable mechanism.
- **IFTTT's Google Assistant trigger** is the one remaining free-form voice bridge into a webhook.

---

## Prerequisites

- **Node.js 18+** on the PC running Roon Server. Check with `node -v`. If missing, install the
  LTS from https://nodejs.org.
- Roon Server running on the same machine/LAN.
- The T8 enabled as a **Roon Ready** zone (Roon -> Settings -> Audio -> enable the T8 under
  "Roon Ready", give it a name). Note that exact name.

## Install

```bash
cd roon-tidal-voice
npm install
copy config.example.json config.json   # Windows  (or: cp on mac/linux)
```

Edit `config.json`:

- `targetZone` — the T8's Roon zone name (substring match, case-insensitive). e.g. `"Eversolo T8"`.
- `port` — local port for the webhook (default `8088`).
- `secret` — a long random string; must match the `?secret=` in your IFTTT URL.
- `fuzzyThreshold` — 0 = exact only, 1 = very loose. `0.5` is a good start.

## Run + pair with Roon

```bash
npm start
```

Then in Roon: **Settings -> Extensions**. You'll see **"Tidal Voice (Google -> Roon -> T8)"** —
click **Enable**. The server log should print `Paired with Roon core: ...`.

### Verify locally before touching IFTTT

With it running, from the same PC:

- `http://localhost:8088/health` -> should say `paired`
- `http://localhost:8088/zones` -> lists zone names. Confirm your T8 name is here and matches
  `targetZone`.
- `http://localhost:8088/playlists?secret=YOURSECRET` -> lists your Roon playlist titles.
- Trigger a play:
  `http://localhost:8088/play?secret=YOURSECRET&playlist=<name of one of your playlists>`
  -> the T8 should start playing it. Watch the server log — it prints the fuzzy match and the
  browse steps.

> If playback doesn't start, copy the `Browse level N: [...]` log lines to me — that shows the
> exact action tree for your Roon/Tidal, and I'll tune the play-action matching (this is the one
> part that can vary between setups).

## Expose the webhook to the internet (for IFTTT)

IFTTT's servers must reach your webhook. Easiest options:

- **Cloudflare Tunnel** (free, recommended): install `cloudflared`, then
  `cloudflared tunnel --url http://localhost:8088`
  It prints a public `https://<random>.trycloudflare.com` URL. Use that as your base.
- **ngrok**: `ngrok http 8088` -> gives an `https://<id>.ngrok-free.app` URL.

(Both give a URL that changes each restart on the free tier. For something permanent, a named
Cloudflare Tunnel is the cleaner long-term setup — ask and I'll write that up.)

## IFTTT applet

1. Create applet: **If** *Google Assistant* -> **"Say a phrase with a text ingredient"**.
   - Phrase: `play $ on roon` (the `$` captures the playlist name).
   - Optionally add variants: `play $ playlist`, `start $ on roon`.
2. **Then** *Webhooks* -> **"Make a web request"**:
   - URL: `https://<your-tunnel-url>/play?secret=YOURSECRET&playlist={{TextField}}`
   - Method: `GET`
   - (`{{TextField}}` is the spoken text ingredient.)
3. Save. Say *"Hey Google, play jazz on roon."*

## Endpoints

| Method | Path                          | Purpose                                  |
|--------|-------------------------------|------------------------------------------|
| GET    | `/health`                     | `paired` / `waiting for Roon`            |
| GET    | `/zones`                      | list known zone/output names             |
| GET    | `/playlists?secret=...`       | list Roon playlist titles                |
| ANY    | `/play?secret=...&playlist=X` | fuzzy-find playlist X and play it to T8  |

## Notes & limits

- **NLU is the weak link.** Google may mishear playlist names; the fuzzy matcher absorbs a lot,
  but very short or unusual names can miss. If a name is chronically misheard, add a fixed-phrase
  IFTTT applet that hardcodes `&playlist=Exact Name`.
- **Security:** keep `secret` long and private; anyone with the URL can start playback.
- **Auto-start:** to run on boot, wrap with `pm2` (`npm i -g pm2; pm2 start app.js; pm2 save`)
  or a Windows Task Scheduler "at logon" task.
