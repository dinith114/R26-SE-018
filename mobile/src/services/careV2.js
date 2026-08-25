/**
 * Smart Care v2 API client.
 * Hierarchy: farm -> houses -> sections (a section = one microclimate zone = one device)
 */
import { Platform } from 'react-native';

/**
 * Where the backend lives.
 *
 * On a real device this MUST be the laptop's LAN address, not localhost -
 * localhost on the phone means the phone. The address changes whenever you move
 * between Wi-Fi and the hotspot, and a stale value here shows up as "Cannot
 * connect" on every screen, so it is read from Expo's dev-server host when that
 * is available and only falls back to the constant below.
 *
 * Check it with:  node preflight.js   (prints this machine's current IPv4)
 */
const LAN_IP = '192.168.1.129';         // only used when USE_USB_TUNNEL is false
// true  = phone on USB, reached through 'adb reverse tcp:8000 tcp:8000'
// false = phone on the same Wi-Fi as the laptop, reached at LAN_IP
const USE_USB_TUNNEL = false;   // release build: reach the backend over Wi-Fi

function resolveHost() {
  if (Platform.OS === 'web') return 'http://localhost:8000';

  // localhost FIRST, because the phone is attached by USB and
  //     adb reverse tcp:8000 tcp:8000
  // makes "localhost" on the phone mean this laptop. That path works on any
  // network, including university Wi-Fi that blocks device-to-device traffic
  // (which is exactly what broke the LAN-IP approach on SLIIT-STD).
  //
  // The LAN address is kept as a fallback for running over Wi-Fi with no cable.
  // If the app cannot reach the backend, the tunnel is almost always missing:
  //     adb reverse tcp:8000 tcp:8000
  return USE_USB_TUNNEL ? 'http://localhost:8000' : `http://${LAN_IP}:8000`;
}

export const BASE_URL = resolveHost();

const API = `${BASE_URL}/api/v2/care`;

async function req(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    let detail = `Server error ${res.status}`;
    try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

/* ── read ── */
export const getOverview = () => req('/overview');
export const getHouse    = (h) => req(`/houses/${h}`);
export const getModelInfo= () => req('/model-info');
export const getAlerts   = () => req('/alerts');
export const getHistory  = (h, s, points = 48, hours = 24) =>
  req(`/houses/${h}/sections/${s}/history?points=${points}&hours=${hours}`);

/** Ranges offered in the chart's dropdown. */
export const HISTORY_RANGES = [
  { label: 'Last 6 hours', hours: 6,   points: 36 },
  { label: 'Last 24 hours', hours: 24, points: 48 },
  { label: 'Last 3 days',  hours: 72,  points: 60 },
  { label: 'Last 7 days',  hours: 168, points: 70 },
];

/* ── rename (name only — never touches other settings) ── */
export const renameFarm    = (name)    => req('/farm', { method: 'PUT', body: JSON.stringify({ name }) });
export const renameHouse   = (h, name) => req(`/houses/${h}`, { method: 'PUT', body: JSON.stringify({ name }) });
export const renameSection = (h, s, name) =>
  req(`/houses/${h}/sections/${s}/name`, { method: 'PUT', body: JSON.stringify({ name }) });

/* ── edit / delete ── */
export const editHouse     = (h, body) => req(`/houses/${h}`, { method: 'PUT', body: JSON.stringify(body) });
export const deleteHouse   = (h)       => req(`/houses/${h}`, { method: 'DELETE' });
export const deleteSection = (h, s)    => req(`/houses/${h}/sections/${s}`, { method: 'DELETE' });

/* ── setup / hierarchy ── */
export const setupFarm   = (cfg)      => req('/setup',  { method: 'POST', body: JSON.stringify(cfg) });
export const addHouse    = (house)    => req('/houses', { method: 'POST', body: JSON.stringify(house) });
export const addSection  = (h, s)     => req(`/houses/${h}/sections`, { method: 'POST', body: JSON.stringify(s) });
export const updateSection = (h, s, body) =>
  req(`/houses/${h}/sections/${s}`, { method: 'PUT', body: JSON.stringify(body) });

/* ── ML ── */
export const planSection = (h, s) => req(`/houses/${h}/sections/${s}/plan`, { method: 'POST' });
export const planAll     = ()     => req('/plan-all', { method: 'POST' });
export const trayCheck   = (h, s) => req(`/houses/${h}/sections/${s}/tray-check`, { method: 'POST' });
export const trayCheckAll= ()     => req('/tray-check-all', { method: 'POST' });

/**
 * Has the node actually carried out the last command for this section?
 *
 * `confirmed` is true only when the acknowledgement's id MATCHES the pending
 * command, so a stale ack from an earlier run cannot be read as this one having
 * worked. The run screen polls this to say "node confirmed" rather than the
 * much weaker "sent" - those are different claims, and this project has already
 * shipped a command path that reached no hardware while every screen said
 * success.
 */
export const getCommandStatus = (h, s, id) =>
  req(`/houses/${h}/sections/${s}/command-status`
      + (id ? `?id=${encodeURIComponent(id)}` : ''));

/* ── control ── */
export const waterSection = (h, s, durationSec = 45, withFertilizer = false) =>
  req(`/houses/${h}/sections/${s}/water`,
      { method: 'POST', body: JSON.stringify({ durationSec, withFertilizer, triggeredBy: 'user' }) });

export const fillTray = (h, s, fillSeconds = 15) =>
  req(`/houses/${h}/sections/${s}/tray-fill`,
      { method: 'POST', body: JSON.stringify({ fillSeconds, triggeredBy: 'user' }) });

/**
 * Cut a running pour short.
 *
 * This was impossible until the firmware loop was made cooperative: the node
 * used to wait out a whole pour inside one delay(), so nothing could reach it
 * while water was actually moving. It now checks for this every 5 seconds while
 * the relay is on, so Stop bites within about that.
 *
 * Safe to send when nothing is running - the node acknowledges it as idle
 * rather than leaving the app waiting for a confirmation that never comes.
 */
export const stopSection = (h, s) =>
  req(`/houses/${h}/sections/${s}/stop`, { method: 'POST' });

/**
 * Move this section's node onto a different Wi-Fi network.
 *
 * The node treats the change as provisional: it keeps the working network as a
 * backup and rolls back by itself if the new one does not come up, so a typo
 * costs a reboot rather than a node. It restarts either way, so expect it to go
 * quiet for about a minute.
 */
export const setNodeWifi = (h, s, ssid, password) =>
  req(`/houses/${h}/sections/${s}/wifi`,
      { method: 'POST', body: JSON.stringify({ ssid, password }) });

/** Any subset of { mode, trayEnabled, fertEnabled } — omitted keys are left alone. */
export const setMode = (h, s, patch) =>
  req(`/houses/${h}/sections/${s}/mode`, { method: 'PUT', body: JSON.stringify(patch) });

/** Same, but for every section on the farm (the My Farm master switches). */
export const setModeAll = (patch) =>
  req('/mode-all', { method: 'PUT', body: JSON.stringify(patch) });

/** Feed now: fertilizer is only ever delivered with water, never onto dry roots. */
export const fertilizeSection = (h, s, durationSec = 45) =>
  req(`/houses/${h}/sections/${s}/water`,
      { method: 'POST', body: JSON.stringify({ durationSec, withFertilizer: true, triggeredBy: 'user' }) });

/* ── automation engine (one switch for the whole farm) ── */
const AUTO = `${BASE_URL}/api/v2/auto`;

async function autoReq(path, options = {}) {
  const res = await fetch(`${AUTO}${path}`, {
    headers: { 'Content-Type': 'application/json' }, ...options,
  });
  if (!res.ok) {
    let detail = `Server error ${res.status}`;
    try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

export const getAutoMode = ()  => autoReq('/auto-mode');
export const setAutoMode = (on) =>
  autoReq('/auto-mode', { method: 'PUT', body: JSON.stringify({ autoMode: !!on }) });

/** Per-section override: 'auto' | 'manual' | null (null = follow the farm switch). */
export const setSectionOverride = (h, s, override) =>
  autoReq(`/sections/${h}/${s}/override`, { method: 'PUT', body: JSON.stringify({ override }) });

export const getAlarms   = (limit = 50) => autoReq(`/alarms?limit=${limit}`);
export const ackAlarm    = (id) => autoReq(`/alarms/${id}/ack`, { method: 'PUT' });
export const getEngine   = ()   => autoReq('/engine');
export const registerPushToken = (token, platform) =>
  autoReq('/push/register', { method: 'POST', body: JSON.stringify({ token, platform }) });

/* ── devices: pairing physical nodes with sections ──
 *
 * A node announces itself under its own MAC as soon as it joins WiFi, so the
 * farmer never types an id. The app's job is only to show what has appeared and
 * let them say which section it belongs to.
 *
 * The one-to-one rule lives in the backend, not here: two phones could otherwise
 * assign two boards to the same section at the same moment. A 409 from assign()
 * is that rule firing, and its detail message is written to be shown as-is.
 */
const DEV = `${BASE_URL}/api/v2/devices`;

async function devReq(path, options = {}) {
  const res = await fetch(`${DEV}${path}`, {
    headers: { 'Content-Type': 'application/json' }, ...options,
  });
  if (!res.ok) {
    let detail = `Server error ${res.status}`;
    try { const j = await res.json(); if (j.detail) detail = j.detail; } catch (_) {}
    const err = new Error(detail);
    err.status = res.status;          // 409 means the 1:1 rule refused the change
    throw err;
  }
  return res.json();
}

/** Every node that has ever announced itself, online ones first. */
export const getDevices = () => devReq('/');

/** Only boards waiting to be claimed - what the Add Section picker shows. */
export const getUnassignedDevices = () => devReq('/?only_unassigned=true');

/** Which node reports for a section, or null for "No device - not reporting". */
export const getSectionDevice = (h, s) => devReq(`/section/${h}/${s}`);

/**
 * Bind a node to a section.
 * Throws with status 409 if the node or the section is already paired; pass
 * force to move it anyway, which releases the previous pairing first.
 */
export const assignDevice = (mac, house, section, force = false) =>
  devReq(`/${mac}/assign`, { method: 'PUT', body: JSON.stringify({ house, section, force }) });

export const unassignDevice = (mac) => devReq(`/${mac}/assign`, { method: 'DELETE' });

/** Blinks the node's onboard LED for ~10s so the farmer can find the physical box. */
export const identifyDevice = (mac) => devReq(`/${mac}/identify`, { method: 'POST' });

/**
 * Ask the NODE which Wi-Fi networks it can see.
 *
 * The board scans, not the phone. They are in different places - the node is in
 * the greenhouse, the phone is in a hand - so the phone's list would offer
 * networks the node cannot reach. Asynchronous: this only asks. The node picks
 * the request up within about five seconds and the scan itself takes a few more,
 * so poll `getDeviceScan` until `scanning` goes false or networks appear.
 */
export const requestDeviceScan = (mac) => devReq(`/${mac}/scan`, { method: 'POST' });
export const getDeviceScan = (mac) => devReq(`/${mac}/scan`);

/**
 * How often the node reads its sensors, in milliseconds.
 *
 * The board picks this up inside the assignment fetch it already makes every
 * cycle, so it costs no extra request and takes effect within one interval.
 * The backend clamps to 5 s - 1 hour; below that a node hammers Firebase, above
 * it the freshness rules call it stale long before it speaks again.
 */
export const setDeviceInterval = (mac, ms) =>
  devReq(`/${mac}/interval`, { method: 'PUT', body: JSON.stringify({ readIntervalMs: ms }) });

/** Offered in the UI. Discrete choices, not a free slider: these are the only
 *  values anyone actually wants, and a stray 1 s would flood the database. */
export const READ_INTERVALS = [
  { label: '15s',  ms: 15000,  hint: 'Demo' },
  { label: '30s',  ms: 30000,  hint: 'Bench' },
  { label: '1min', ms: 60000,  hint: 'Normal' },
  { label: '5min', ms: 300000, hint: 'Production' },
];

/** "every 15s" / "every 5 min" — how the interval reads in a sentence. */
export function intervalLabel(ms) {
  if (ms == null) return '--';
  const s = Math.round(ms / 1000);
  return s < 60 ? `every ${s}s` : `every ${Math.round(s / 60)} min`;
}

/** Signal strength as words. Farmers do not read dBm. */
export function signalLabel(rssi) {
  if (rssi == null) return { label: '--', color: '#94a3b8' };
  if (rssi >= -55) return { label: 'Strong', color: '#22c55e' };
  if (rssi >= -70) return { label: 'Good',   color: '#84cc16' };
  if (rssi >= -80) return { label: 'Weak',   color: '#f59e0b' };
  return { label: 'Very weak', color: '#ef4444' };
}

/** "just now" / "2 min ago" - a farmer standing next to a board needs to know
 *  it is the one that just powered up, not one from last week. */
export function lastSeenLabel(sec) {
  if (sec == null) return 'never';
  if (sec < 15) return 'just now';
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  return `${Math.floor(sec / 86400)} d ago`;
}

/* ── helpers used by the UI ── */
export const RH_LOW = 60, RH_HIGH = 80;

export function humidityStatus(rh) {
  if (rh == null) return { label: '--', color: '#94a3b8' };
  if (rh < RH_LOW)  return { label: 'DRY',  color: '#f59e0b' };
  if (rh > RH_HIGH) return { label: 'HUMID',color: '#3b82f6' };
  return { label: 'GOOD', color: '#22c55e' };
}

export function vpdStatus(vpd) {
  if (vpd == null) return { label: '--', color: '#94a3b8' };
  if (vpd < 0.8) return { label: 'low drying',  color: '#3b82f6' };
  if (vpd < 1.6) return { label: 'normal',      color: '#22c55e' };
  if (vpd < 2.4) return { label: 'high drying', color: '#f59e0b' };
  return { label: 'extreme', color: '#ef4444' };
}
