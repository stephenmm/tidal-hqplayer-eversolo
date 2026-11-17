# Troubleshooting

A running log of issues encountered and how to resolve them.

---

## First step: check the HQPlayer log

When anything seems wrong with playback, NAA connectivity, or HQPlayer behaviour, the log is the first place to look:

```
C:\Users\PC\AppData\Local\HQPlayer\HQPlayer5Desktop.log
```

It records NAA device discovery, control connections, errors, and state changes in real time. Key line prefixes:

| Prefix | Meaning |
|--------|---------|
| `&` | NAA device discovered on the network |
| `?` | Warning / unexpected state |
| `+` / `-` | Control connection opened / closed |

**Quick tail via PowerShell:**
```powershell
Get-Content "C:\Users\PC\AppData\Local\HQPlayer\HQPlayer5Desktop.log" -Tail 50
```

---

## Second step: verify the HQPlayer settings file

If the log shows the Eversolo is being discovered but HQPlayer still won't connect, check that `settings.xml` looks correct:

```
C:\Users\PC\AppData\Local\HQPlayer\settings.xml
```

**Key things to verify:**

1. `type="network6"` on the `<engine>` element — confirms NAA network output mode is active.
2. `<network device="Eversolo:T8" .../>` — the device name must match exactly what the log shows after `name=`. If this is blank, HQPlayer has no target.
3. `address=""` — leave this empty; HQPlayer matches by device name from discovery, not by IP.

**Known-good `<network>` line:**
```xml
<network address="" any_dsd="1" dac_bits="0" device="Eversolo:T8" dualwire="0" ipv6="1" pack_sdm="1" period_time="0"/>
```

**If `device=""` is blank:** HQPlayer lost its NAA selection (happens after an unclean shutdown or double-instance kill). Fix by opening HQPlayer GUI → File → Settings → Output → select **Eversolo:T8** from the dropdown → OK. HQPlayer writes the correct value back to `settings.xml` itself — do not edit the file manually while HQPlayer is running.

**If the rates dropdown in the web UI is empty:** this is a symptom of HQPlayer not being connected to any output device. Fix the NAA connection first; rates will populate automatically once HQPlayer connects to the Eversolo.

---

## HQPlayer cannot see the Eversolo NAA

**Symptom:** HQPlayer is running but the Eversolo does not appear as an output device, or playback is silent.

**Cause (most common):** Two instances of HQPlayer are running simultaneously. The second instance starts but cannot claim the NAA device because the first still holds it.

**Fix:**
1. Open Task Manager → Details tab → look for multiple `HQPlayer.exe` processes.
2. Kill all of them.
3. Relaunch HQPlayer once (via the web UI Restart HQP button or manually).

**Cause (secondary):** HQPlayer restarted while the Eversolo was asleep or off the network. It re-scans at startup only, so it finds nothing and saves an empty `address=""` device in `settings.xml`.

**Fix:**
1. Make sure the Eversolo is powered on and awake.
2. Open HQPlayer GUI → File → Settings → Output → select the Eversolo from the dropdown → OK.
3. HQPlayer saves the selection back to `settings.xml`.

---

## Two instances of HQPlayer running

**Symptom:** Clicking "Restart HQP" or "Apply" (rate change) launches a second HQPlayer instead of replacing the first. NAA device becomes unreachable.

**Cause:** `close_and_wait()` sent a Quit command but the process didn't exit before `launch()` ran.

**Workaround:** Kill all `HQPlayer.exe` processes via Task Manager, then use "Restart HQP" in the web UI to start a fresh single instance.

**Long-term fix:** Add a process-existence check to `close_and_wait()` before calling `launch()`.

---

## Server starts but buttons / new routes return 404

**Symptom:** The web UI loads but Shuffle, Next, rate selector, or other buttons do nothing. Console shows 404.

**Cause:** An old server process is still running on port 8080 (from a previous session or a failed restart). The new `python server.py` binds to a different port or fails silently, and the browser is still talking to the stale process.

**Fix:**
1. Find the old PID: `netstat -ano | findstr :8080`
2. Kill it: `Stop-Process -Id <PID> -Force`
3. Restart: `E:\Users\PC\miniconda3\envs\tidal-hqp\python.exe server.py`

---

## Browser shows old UI after code changes

**Symptom:** Code was updated but the page still behaves as before (buttons missing, errors not shown, etc.).

**Cause:** Browser has cached `index.html`. The Python server restarts on `.py` file changes (`reload=True`) but static files are served as-is; the browser cache isn't invalidated.

**Fix:** Hard-reload the page with **Ctrl+Shift+R** (Windows/Linux) or use the **Reload Page** button in the footer.

---

## Queue clears after saving a Python file

**Symptom:** A track was queued and playing; after editing and saving a `.py` file the queue is empty and playback stops.

**Cause:** `uvicorn` is running with `reload=True`. Any `.py` file save triggers a full process restart, which resets all in-memory state (queue, active download thread, etc.).

**Workaround:** Re-select the playlist/track after restarting. Persistent queue (saved to disk) would solve this permanently but is not yet implemented.

---

## Wrong song plays when clicking a track while one is already playing

**Symptom:** Click track B while track A is still buffering. Track A ends up playing instead of B (or vice-versa).

**Cause (fixed):** Race condition — the old `play_track_id` thread completed its prebuffer check and called `hqp_play_url` after the new thread had already taken over.

**Fix applied:** `player.py` now checks `_active["tmp_path"]` as a generation token before calling `hqp_play_url`. If another call has replaced it, the old thread aborts silently. Regression test: `test_play_superseded_does_not_call_hqp`.

---

## HQPlayer shows two HTTP stream entries in the playlist

**Symptom:** After clicking a track, HQPlayer's playlist shows two rows — both pointing to the same `/stream/<id>` URL.

**Cause:** This is normal. HQPlayer internally prefetches a second playlist slot for gapless/seamless transitions. It is not a bug.

---

## Auto-advance does not start the next track

**Symptom:** A track finishes but the next track never starts.

**Cause (most likely):** The server was restarted mid-session (file save triggered reload). The queue is now empty so there is nothing to advance to.

**Cause (secondary):** HQPlayer briefly dips through `state=2 → state=0` between tracks during gapless prefetch. If the monitor thread's 0.5 s poll misses the `state=2` window, it never sees the `2→0` transition that triggers auto-advance.

**Fix:** Re-queue the playlist after any server restart. The 0.5 s monitor poll is the current mitigation for the gapless edge case.

---

## Tidal always reports 44.1 kHz / 16-bit (HIFI instead of Hi-Res)

**Symptom:** Quality badge always shows "HiFi". HQPlayer input always shows `44.1k / 16`.

**Cause (resolved):** `track.get_stream().get_stream_manifest().get_urls()[0]` returns MPEG-DASH segment URLs, not a direct FLAC file. HQPlayer received a DASH manifest it couldn't parse, silently fell back, or the download produced garbage.

**Fix applied:** `track_stream_url()` now uses `track.get_url()` for the actual download URL (direct CDN FLAC link). `get_stream()` is called only to read the quality label for the badge.

**Note:** Many tracks on Tidal only have a 44.1 kHz / 16-bit master even with a Hi-Res subscription. The badge will show "HiFi" for those. Hi-Res masters show "Hi-Res" in gold.

---

## Rate dropdown resets to 44.1 kHz after clicking Apply

**Symptom:** Select 96 kHz, click Apply — HQPlayer restarts with 96 kHz, but the dropdown reverts to 44.1 kHz.

**Cause (fixed):** `loadRates()` fetched available rates but did not mark the currently-configured rate as `selected`.

**Fix applied:** `loadRates()` now fetches rates and current settings in parallel, then sets the `selected` attribute on the matching `<option>`.

---

## Search gives no feedback on failure

**Symptom:** Type a search query, press Enter, nothing changes on screen. No error, no "no results" message.

**Cause (fixed):** `doSearch()` had no error handling — a 401 (not logged in) or network error was silently swallowed.

**Fix applied:** `doSearch()` now shows "Searching…" while in flight, a red error message with the server's detail string on failure, and "No results for …" when the query returns empty.
