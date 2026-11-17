# Galaxy Side-Button → Roon Voice — Complete Setup Guide

Goal: double-press the side (power) button → tap 🎵 Voice → speak a playlist → it
plays on the T8. No extra apps beyond Tasker.

**Do NOT use Tasker's "Export → As App" (App Factory).** Android 14+ blocks
installing the apps it generates (outdated target SDK). If Tasker offered to
"install additional apps" — that was App Factory. Cancel it; it's not needed.

---

## Part 0 — one-time prerequisites (5 min)

1. Both tasks imported into Tasker: **Roon Voice** and **Roon Dispatch**
   (Tasker → turn off Beginner Mode in ⋮ → Preferences → UI → long-press the
   "Tasks" tab title → Import Task → pick each .xml from Downloads).
2. Give each task an icon (Tasker requires this before a task can be used as a
   shortcut or tile):
   - Tasks tab → tap **Roon Dispatch** to open it
   - bottom-right corner: tap the **grid/select-icon button** (square made of dots)
   - pick any built-in icon (e.g. the music note) → back arrow to save
   - repeat for **Roon Voice**
3. Permissions Tasker will ask for on first run — say yes to all:
   - Microphone (for Get Voice)
   - Display over other apps (so the dialog can appear anywhere, incl. lock screen)

## Part 1 — test the tasks by hand FIRST

1. Tasks tab → open **Roon Voice** → tap the ▶ play button (bottom-left).
2. Say a playlist name ("jazz"). Within ~2 s you should see a flash:
   `Playing "jazz" on T8` — and music on the T8.
3. Open **Roon Dispatch** → ▶ → the two-button dialog appears → try both buttons.
   - If 📷 Camera doesn't open your camera: tap action 2 (Launch App) inside the
     task and re-pick your Camera app from the list, then save.

Don't wire any buttons until both tests pass.

## Part 2 — side button double-press (One UI 7 or newer)

One UI 7+ lets the side button trigger an *app shortcut*, not just an app.
Tasker can register tasks as app shortcuts:

1. In Tasker: Tasks tab → **+** → name it `Register Shortcuts` → OK
2. Tap **+** to add an action → search for **Setup App Shortcuts**
3. In its config, add **Roon Dispatch** (and Roon Voice if you like) to the
   shortcut list → back to save
4. Run the task once (▶). Tasker's app shortcuts are now registered.
   (Verify: long-press the Tasker icon on your home screen — "Roon Dispatch"
   should appear in the popup list.)
5. Phone **Settings → Advanced features → Side button**
6. **Double press → Open app** → choose **Tasker**, then tap the **⚙ gear icon**
   next to it → select **Roon Dispatch**
   - No gear icon next to Tasker? Your One UI version doesn't support
     function-level shortcuts for it → use Part 3 instead.

Result: double-press side key → dialog → 🎵 Voice → speak.
Note: you lose the double-press-for-camera default, which is why the dialog's
📷 Camera button exists — camera stays one tap away.

## Part 3 — fallback: Quick Settings tile (works on every version)

1. Tasker → ⋮ → **Preferences → Action tab → Quick Settings Tasks**
2. Tap the first slot → select **Roon Dispatch** (or Roon Voice directly)
3. Swipe down the notification shade fully → tap the **pencil/edit** (⋮ → Edit
   buttons on some versions) → drag the new Tasker tile into the active tiles
4. Optional, to skip unlocking: in Tasker create a one-action task with
   **Setup Quick Setting**, pick the tile, and enable **Can Use On Locked Device**;
   run it once.

Result: swipe down (works on lock screen) → tap tile → speak.

## Part 4 — troubleshooting

- **"Playing …" flash never appears / times out**: check the server —
  on GREEN_MACHINE run `E:\proj\tidal_hqplayer_eversolo\roon-tidal-voice\start-all.bat`
  and test https://bronchially-hydrocyanic-ruthann.ngrok-free.dev/health in a
  browser (should say `paired`).
- **Flash says "no playlist matched"**: the fuzzy matcher didn't find it — check
  the exact names with .../playlists?secret=... in a browser.
- **Voice dialog won't appear when locked**: Settings → Apps → Tasker →
  grant "Display over other apps"; some One UI versions simply refuse the
  Google voice dialog on a secure lock screen — then unlock first or use the tile.
- **Wrong camera opens / nothing opens**: edit the Launch App action in
  Roon Dispatch and re-pick the camera.
- **Tasker vs battery optimization**: Settings → Apps → Tasker → Battery →
  Unrestricted, or One UI may kill the listener.
