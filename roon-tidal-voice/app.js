/**
 * roon-tidal-voice
 * -------------------------------------------------------------
 * Voice-trigger Tidal playlists in Roon and play them to the Eversolo T8.
 *
 *   "Hey Google, play <playlist>"
 *        -> IFTTT (Google Assistant trigger -> Webhooks)
 *        -> POST/GET this server's /play endpoint
 *        -> Roon browse API finds the playlist (fuzzy match)
 *        -> Roon transport plays it to your target zone (the T8)
 *
 * Runs on the same PC/LAN as Roon Server. Enable it once in
 * Roon: Settings -> Extensions -> Enable "Tidal Voice".
 * -------------------------------------------------------------
 */

const fs = require("fs");
const path = require("path");
const express = require("express");
const Fuse = require("fuse.js");

const RoonApi = require("node-roon-api");
const RoonApiStatus = require("node-roon-api-status");
const RoonApiTransport = require("node-roon-api-transport");
const RoonApiBrowse = require("node-roon-api-browse");

// ---- config -------------------------------------------------
const cfgPath = path.join(__dirname, "config.json");
if (!fs.existsSync(cfgPath)) {
  console.error("Missing config.json. Copy config.example.json to config.json and edit it.");
  process.exit(1);
}
const config = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
const FUZZY = typeof config.fuzzyThreshold === "number" ? config.fuzzyThreshold : 0.5;

function log(...a) { console.log(new Date().toISOString(), ...a); }

// ---- Roon state ---------------------------------------------
let core = null;
let transport = null;
let browse = null;
let zones = {}; // zone_id -> zone object (has display_name, outputs[])

const roon = new RoonApi({
  extension_id: "com.stephenm.roon-tidal-voice",
  display_name: "Tidal Voice (Google -> Roon -> T8)",
  display_version: "1.0.0",
  publisher: "stephenmm",
  email: "stephenmeckley@gmail.com",

  core_paired: function (core_) {
    core = core_;
    transport = core.services.RoonApiTransport;
    browse = core.services.RoonApiBrowse;
    log("Paired with Roon core:", core.display_name);
    status.set_status("Paired with " + core.display_name, false);

    transport.subscribe_zones((cmd, data) => {
      if (!data) return;
      if (data.zones)        data.zones.forEach(z => (zones[z.zone_id] = z));
      if (data.zones_added)  data.zones_added.forEach(z => (zones[z.zone_id] = z));
      if (data.zones_changed)data.zones_changed.forEach(z => (zones[z.zone_id] = z));
      if (data.zones_removed)data.zones_removed.forEach(id => delete zones[id]);
    });
  },

  core_unpaired: function () {
    log("Unpaired from Roon core.");
    core = null; transport = null; browse = null;
  },
});

const status = new RoonApiStatus(roon);
status.set_status("Starting up, waiting for Roon...", false);

roon.init_services({
  required_services: [RoonApiTransport, RoonApiBrowse],
  provided_services: [status],
});
roon.start_discovery();

// ---- helpers ------------------------------------------------
function knownZoneNames() {
  const names = new Set();
  Object.values(zones).forEach(z => {
    names.add(z.display_name);
    (z.outputs || []).forEach(o => names.add(o.display_name));
  });
  return [...names];
}

// Resolve a zone/output id by (case-insensitive, substring) display name.
function resolveZone(nameWanted) {
  const want = String(nameWanted || "").toLowerCase();
  for (const z of Object.values(zones)) {
    if (z.display_name && z.display_name.toLowerCase().includes(want)) return z.zone_id;
    for (const o of z.outputs || []) {
      if (o.display_name && o.display_name.toLowerCase().includes(want)) return o.output_id;
    }
  }
  return null;
}

function browseAsync(opts) {
  return new Promise((res, rej) => browse.browse(opts, (err, body) => (err ? rej(new Error(err)) : res(body))));
}
function loadAsync(opts) {
  return new Promise((res, rej) => browse.load(opts, (err, body) => (err ? rej(new Error(err)) : res(body))));
}

// List all Tidal/local playlists visible in Roon.
async function listPlaylists() {
  await browseAsync({ hierarchy: "playlists", pop_all: true, set_display_offset: 0 });
  const body = await loadAsync({ hierarchy: "playlists", offset: 0, count: 500 });
  return (body.items || []).filter(i => i.item_key);
}

// Browse into a playlist, open its action menu, and invoke "Play Now".
// Roon's tree: playlist -> [Play Playlist, ...tracks] -> [Play Now, Shuffle, Add Next, Queue, Start Radio].
// Invoking "Play Now" starts playback; Roon then pops back to the list, so we must STOP there.
async function invokePlay(itemKey, zoneId) {
  const browseInto = (key) =>
    browseAsync({ hierarchy: "playlists", item_key: key, zone_or_output_id: zoneId });
  const loadItems = async () =>
    (await loadAsync({ hierarchy: "playlists", offset: 0, count: 100 })).items || [];

  // Step 1: open the playlist.
  await browseInto(itemKey);
  let items = await loadItems();
  log(`Playlist view: [${items.map(i => i.title).join(" | ")}]`);

  // Some hierarchies expose "Play Now" here directly; otherwise "Play Playlist" opens the action menu.
  let entry =
    items.find(i => /^play now$/i.test(i.title)) ||
    items.find(i => /^play playlist$/i.test(i.title)) ||
    items.find(i => /^play$/i.test(i.title));
  if (!entry) throw new Error(`No play entry found. Items: ${items.map(i => i.title).join(", ")}`);

  await browseInto(entry.item_key);
  if (/^play now$/i.test(entry.title)) {
    log(`Invoked "Play Now" directly — playback started.`);
    return;
  }

  // Step 2: we opened the action menu; pick "Play Now" and invoke it (terminal).
  items = await loadItems();
  log(`Action menu: [${items.map(i => i.title).join(" | ")}]`);
  const playNow =
    items.find(i => /^play now$/i.test(i.title)) ||
    items.find(i => /^play$/i.test(i.title));
  if (!playNow) throw new Error(`No "Play Now" in action menu. Items: ${items.map(i => i.title).join(", ")}`);

  await browseInto(playNow.item_key);
  log(`Invoked "Play Now" — playback started.`);
}

async function playPlaylist(spokenName, zoneId) {
  const playlists = await listPlaylists();
  if (!playlists.length) throw new Error("Roon returned no playlists.");
  const fuse = new Fuse(playlists, { keys: ["title"], threshold: FUZZY, includeScore: true });
  const hits = fuse.search(spokenName);
  if (!hits.length) {
    throw new Error(`No playlist matched "${spokenName}". Available: ${playlists.map(p => p.title).join(", ")}`);
  }
  const match = hits[0].item;
  log(`Matched "${spokenName}" -> "${match.title}" (score ${hits[0].score.toFixed(3)})`);
  await invokePlay(match.item_key, zoneId);
  return match.title;
}

// ---- webhook server ----------------------------------------
const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

function auth(req, res, next) {
  const s = req.query.secret || req.headers["x-secret"] || (req.body && req.body.secret);
  if (config.secret && s !== config.secret) return res.status(401).send("bad or missing secret");
  next();
}

app.get("/health", (req, res) => res.send(core ? "paired" : "waiting for Roon"));
app.get("/zones", (req, res) => res.json(knownZoneNames()));

app.get("/playlists", auth, async (req, res) => {
  if (!core) return res.status(503).send("not paired with Roon yet");
  try { res.json((await listPlaylists()).map(p => p.title)); }
  catch (e) { res.status(500).send(e.message); }
});

// The main endpoint IFTTT calls. Accepts ?playlist= or JSON {playlist}.
app.all("/play", auth, async (req, res) => {
  const name = req.query.playlist || req.query.q || (req.body && req.body.playlist);
  if (!name) return res.status(400).send("missing 'playlist'");
  if (!core) return res.status(503).send("not paired with Roon yet");

  const zoneId = resolveZone(config.targetZone);
  if (!zoneId) {
    return res.status(500).send(`Zone "${config.targetZone}" not found. Known zones: ${knownZoneNames().join(", ")}`);
  }
  // Tolerate natural spoken phrases: "play jazz on roon" -> "jazz"
  const cleaned = String(name).trim()
    .replace(/^(please\s+)?(play|start)\s+/i, "")
    .replace(/\s+(on\s+(roon|the\s+t8|t8)|playlist)\s*$/i, "")
    .trim() || String(name).trim();

  try {
    const played = await playPlaylist(cleaned, zoneId);
    res.send(`Playing "${played}" on ${config.targetZone}`);
  } catch (e) {
    log("PLAY ERROR:", e.message);
    res.status(500).send(e.message);
  }
});

app.listen(config.port, () => log(`Webhook listening on http://0.0.0.0:${config.port}`));
