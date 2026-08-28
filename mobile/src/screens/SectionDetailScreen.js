import React, { useState, useCallback, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, RefreshControl, Switch, Dimensions, TextInput,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import { LIVE_MS } from '../hooks/useLiveData';
import RenameDialog from '../components/RenameDialog';
import ConfirmSheet from '../components/ConfirmSheet';
import SelectSheet from '../components/SelectSheet';
import Toast from '../components/Toast';
import { SectionSkeleton } from '../components/Skeleton';
import NodePicker from '../components/NodePicker';
import Sheet from '../components/Sheet';
import { FreshnessBadge, StaleWarning } from '../components/Freshness';
import LineChart from '../components/LineChart';
import RangePicker from '../components/RangePicker';
import {
  getHouse, waterSection, fillTray, setMode,
  getHistory, deleteSection, renameSection, humidityStatus, vpdStatus,
  setSectionOverride, getAutoMode, HISTORY_RANGES, RH_LOW, RH_HIGH,
  getSectionDevice, unassignDevice, assignDevice, identifyDevice, pingDevice,
  setSectionDurations, setSectionPosition,
  getPingResult, lastSeenLabel, signalLabel,
  stopSection, setNodeWifi, requestDeviceScan, getDeviceScan, getSectionEvents,
  setDeviceInterval, READ_INTERVALS, intervalLabel, getCommandStatus,
} from '../services/careV2';

/* A settings row that opens a chooser. Reads as a value you can change rather
   than a wall of buttons: the three-way control used to be three segments and
   the read interval four chips, each with its own explanatory paragraph, which
   made the screen look like a form instead of a status page. */
function DropRow({ icon, label, value, onPress, disabled }) {
  return (
    <TouchableOpacity
      style={[styles.dropRow, disabled && { opacity: 0.5 }]}
      onPress={onPress}
      disabled={disabled}
      activeOpacity={0.7}
      accessibilityRole="button"
      accessibilityLabel={`${label}, currently ${value}. Tap to change.`}>
      {!!icon && <Ionicons name={icon} size={17} color={COLORS.textTertiary} />}
      <Text style={styles.dropLabel}>{label}</Text>
      <Text style={styles.dropValue}>{value}</Text>
      <Ionicons name="chevron-down" size={16} color={COLORS.textTertiary} />
    </TouchableOpacity>
  );
}

/* A section heading that carries meaning rather than just separating.

   Every block on this screen used the same plain bold line, so a farmer
   scanning for the tray had to read all eight to find it. The icon and its
   tint identify the subject before the words are read; the pill on the right
   carries the one fact that decides whether the block needs opening at all. */
function SectionHead({ icon, title, tint, tintDim, status, statusTone, first, style }) {
  const tone = statusTone || tint;
  return (
    <View style={[styles.shead, first && { marginTop: 0 }, style]}>
      <View style={[styles.sheadIcon, { backgroundColor: tintDim }]}>
        <Ionicons name={icon} size={14} color={tint} />
      </View>
      <Text style={styles.sheadTitle} numberOfLines={1}
        maxFontSizeMultiplier={1.15}>{title}</Text>
      {!!status && (
        <View style={[styles.sheadPill, { backgroundColor: `${tone}1A` }]}>
          <Text style={[styles.sheadPillTxt, { color: tone }]} numberOfLines={1}
            maxFontSizeMultiplier={1.1}>{status}</Text>
        </View>
      )}
    </View>
  );
}

/* The three control positions. 'follow' is the normal case and the reason this
   is not a two-position switch. */
const CONTROL_OPTIONS = [
  { key: 'follow', override: null,     label: 'Follow the farm' },
  { key: 'auto',   override: 'auto',   label: 'Always automatic' },
  { key: 'manual', override: 'manual', label: 'Always manual' },
];

// screen width minus the page padding and the card padding on both sides
const CHART_W = Dimensions.get('window').width - (24 * 2) - (16 * 2);

/* How a ping is chased.

   The node re-reads its device record every ~5s, so an answer usually lands
   inside two polls. Measured on real hardware: 6.2s and 8.3s on quiet trials,
   but 18.5s when the ping arrived while the board was mid-reading-cycle and
   could not poll until its sensor read and uploads finished.

   30s is set from that worst case, not from the happy path. An earlier 12s
   guess would have declared a perfectly healthy node unreachable. Whatever
   happens the button reaches a definite state - answered, or no answer - and
   never leaves the farmer watching a spinner that means nothing. */
const PING_POLL_MS = 1000;
const PING_TIMEOUT_MS = 30000;

export default function SectionDetailScreen({ route, navigation }) {
  const { houseId, sectionId, houseName } = route.params;

  const [sec,     setSec]     = useState(null);
  const [fert,    setFert]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(false);
  const [busy,    setBusy]    = useState(null);
  const [trayOn,  setTrayOn]  = useState(true);
  const [series,  setSeries]  = useState([]);
  const [renaming, setRenaming] = useState(false);
  const [range,    setRange]    = useState(HISTORY_RANGES[1]);   // Last 24 hours
  // 'auto' | 'manual' | null. null means "follow the farm switch".
  const [override, setOverride] = useState(null);
  const [farmAuto, setFarmAuto] = useState(true);
  // The physical node reporting for this section, or null. Null is a normal
  // state - a section can be created before its hardware arrives.
  const [device,   setDevice]   = useState(null);
  const [unlinking, setUnlinking] = useState(false);
  // Link mode replaces the whole screen, the way Add Section does. NodePicker
  // is a FlatList; nesting it in a sheet's ScrollView breaks its scrolling.
  const [picking,  setPicking]  = useState(false);
  const [linking,  setLinking]  = useState(false);
  /* The pour that is happening right now, as the NODE reports it:
     { kind, id, secs, remaining, phase: 'sending' | 'running', sentAt }.
     Null when nothing is running. */
  const [run,      setRun]      = useState(null);
  const [stopping, setStopping] = useState(false);
  // Wi-Fi form: kept out of `sheet` because it holds text being typed.
  const [wifi,     setWifi]     = useState(null);   // { ssid, pass, saving }
  // Shown after a pour ends on its own: { kind, secs }
  const [again,    setAgain]    = useState(null);
  /* Whether plant food goes into the next manual watering.
     Seeded from whether it is due each time the sheet opens, but the farmer
     decides - previously the app just announced that food would be mixed in and
     gave no way to decline, which is the wrong default for something that burns
     roots if overdone. */
  const [addFert,  setAddFert]  = useState(false);
  /* The screen was twelve stacked cards on one scroll: readings, actions,
     control, chart, forecast, plan, tray, plant food, sensor node, interval,
     Wi-Fi, rename, delete. Everything was one swipe away and nothing was
     findable. Split by what the farmer came to do. */
  const [tab,      setTab]      = useState('now');
  const [events,   setEvents]   = useState(null);
  const [evLoading, setEvLoading] = useState(false);
  const [blinking,  setBlinking]  = useState(false);
  const [ping,      setPing]      = useState(null);   // { state: asking|ok|timeout }
  /* Manual pour lengths. null in either slot means "let the model decide".
     Kept as strings while editing so a half-typed number is not coerced to 0. */
  const [durEdit,   setDurEdit]   = useState(null);  // { water, tray } as text
  const [durSaving, setDurSaving] = useState(false);
  const [posEdit,   setPosEdit]   = useState(null);  // { x, y } as text
  const [posSaving, setPosSaving] = useState(false);
  const [savingIv,  setSavingIv]  = useState(null);
  // One sheet at a time: 'water' | 'fill' | 'interval' | 'control' | 'unlink'
  const [sheet, setSheet] = useState(null);
  const [toast, setToast] = useState(null);      // { text, kind }
  const [pendingCtl, setPendingCtl] = useState(null);

  const load = useCallback(async () => {
    try {
      // The device lookup is allowed to fail on its own: an older backend
      // without /api/v2/devices should still render the whole screen.
      //
      // The CHART is deliberately not in this list. Readings refresh every 15 s,
      // but the history behind the chart is ~57 KB a call and barely changes in
      // that time - fetching it on every poll was tens of megabytes a day of
      // Firebase egress for a line that looks identical. It reloads when the
      // screen opens and when the range changes, which is when it can actually
      // differ.
      const [{ house }, dev] = await Promise.all([
        getHouse(houseId),
        getSectionDevice(houseId, sectionId).catch(() => null),
      ]);
      const s = house?.sections?.[sectionId];
      setSec(s || null);
      setDevice(dev?.device || null);
      // fertilizer is stored with the plan, so show it immediately
      if (s?.fertilizer && 'due' in s.fertilizer) setFert(s.fertilizer);
      const c = s?.control || {};
      setOverride(c.override ?? null);
      setTrayOn(c.trayEnabled !== false);
      try { setFarmAuto((await getAutoMode()).autoMode !== false); } catch (_) {}
    } catch (e) { setToast({ text: e.message, kind: 'error' }); }
    finally { setLoading(false); setRefresh(false); }
  }, [houseId, sectionId, range]);

  const removeSection = async () => {
    setSheet(null);
    try { await deleteSection(houseId, sectionId); navigation.goBack(); }
    catch (e) { setToast({ text: e.message, kind: 'error' }); }
  };

  // Releasing a node is reversible and the board keeps running - the firmware
  // reverts to its fallback section within ~15s and becomes claimable again -
  // so this warns about losing readings rather than about destroying anything.
  const unlinkNode = async () => {
    const id = device?.shortId;
    setSheet(null);
    setUnlinking(true);
    try {
      await unassignDevice(device.mac);
      setDevice(null);
      await load();
      setToast({ text: `Node ${id} unlinked`, kind: 'success' });
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally { setUnlinking(false); }
  };

  /* Ask the node what it can see, then poll for the answer.

     The node scans, not the phone: they are in different places, so the phone's
     list would offer networks the board cannot actually reach. Typing the name
     by hand was the first version of this and it is a bad way to enter an SSID
     you are only reading off a router label. */
  const scanWifi = useCallback(async () => {
    if (!device?.mac) return;
    setWifi((w) => ({ ...(w || {}), scanning: true, networks: [] }));
    try {
      await requestDeviceScan(device.mac);
    } catch (e) {
      setWifi((w) => (w ? { ...w, scanning: false } : w));
      setToast({ text: e.message, kind: 'error' });
      return;
    }
    // The node picks the request up within ~5 s and the scan takes a few more.
    const deadline = Date.now() + 45000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const r = await getDeviceScan(device.mac);
        if (r?.networks?.length) {
          setWifi((w) => (w ? { ...w, scanning: false, networks: r.networks } : w));
          return;
        }
      } catch (_) { /* keep waiting; the node may not have looked yet */ }
    }
    setWifi((w) => (w ? { ...w, scanning: false } : w));
  }, [device?.mac]);

  /* Move the node onto a different network.

     Safe to get wrong: the firmware saves the new credentials on trial and
     keeps the working ones as a backup, so if the new network does not come up
     it rolls back and restarts on the old one. The node goes quiet either way
     while it reboots, which is why this says so rather than leaving the farmer
     watching a section that has apparently died. */
  const applyWifi = async () => {
    const ssid = (wifi?.ssid || '').trim();
    if (!ssid) return;
    setWifi((w) => ({ ...w, saving: true }));
    try {
      const r = await setNodeWifi(houseId, sectionId, ssid, wifi?.pass || '');
      setWifi(null);
      setToast({ text: r?.message || `Node moving to ${ssid}`, kind: 'success' });
    } catch (e) {
      setWifi((w) => ({ ...w, saving: false }));
      setToast({ text: e.message, kind: 'error' });
    }
  };

  /* The other half of unlinkNode. A section can be created before its hardware
     arrives, and until now the only way to attach a node afterwards was to go
     back through Add Section - so a section with no node was a dead end on the
     one screen that told you about it. */
  const linkNode = async (dev) => {
    setPicking(false);
    setLinking(true);
    try {
      await assignDevice(dev.mac, houseId, sectionId);
      await load();
      setToast({ text: `Node ${dev.shortId || dev.mac.slice(-4)} linked`, kind: 'success' });
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally { setLinking(false); }
  };

  // How often the board reads. Optimistic: the chip highlights immediately, and
  // rolls back if the write fails, because the node itself takes up to one full
  // interval to actually adopt the new value and we do not want the UI to look
  // frozen for five minutes.
  const applyInterval = async (ms) => {
    if (!device) return;
    const prev = device.readIntervalMs;
    setSheet(null);
    setSavingIv(ms);
    setDevice({ ...device, readIntervalMs: ms });
    try {
      await setDeviceInterval(device.mac, ms);
      setToast({ text: `Now reading ${intervalLabel(ms)}`, kind: 'success' });
    } catch (e) {
      setDevice({ ...device, readIntervalMs: prev });
      setToast({ text: e.message, kind: 'error' });
    }
    finally { setSavingIv(null); }
  };

  // Same trick the Add Section picker uses: blink the board's LED so the farmer
  // can tell which of four identical boxes they are about to unlink.
  /* Save the grower's own pour lengths.

     Blank means automatic, so an empty box is a deliberate value here rather
     than a missing one - it is how you hand a section back to the model. The
     backend re-checks both numbers against the relay cap and the tray's real
     capacity, so this only catches the obvious mistakes early. */
  const saveDurations = async () => {
    const parse = (v) => {
      const t = String(v ?? '').trim();
      if (!t) return null;
      const n = parseInt(t, 10);
      return Number.isNaN(n) ? null : n;
    };
    const w = parse(durEdit?.water);
    const t = parse(durEdit?.tray);
    if (w != null && (w < 30 || w > 120)) {
      Alert.alert('Watering length', 'Must be between 30 and 120 seconds.');
      return;
    }
    if (t != null && (t < 1 || t > (tray?.maxSeconds ?? 15))) {
      Alert.alert('Tray fill length',
                  `Must be between 1 and ${tray?.maxSeconds ?? 15} seconds — longer than `
                  + `that overflows the tray.`);
      return;
    }
    try {
      setDurSaving(true);
      await setSectionDurations(houseId, sectionId, w, t);
      setDurEdit(null);
      load();
      setToast({ text: w == null && t == null ? 'Back to automatic' : 'Lengths saved',
                 kind: 'success' });
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setDurSaving(false);
    }
  };

  /* Save where this section sits. Metres, so a plain number is the whole
     input - a map picker can replace this later without the API changing. */
  const savePosition = async () => {
    const x = parseFloat(String(posEdit?.x ?? '').trim());
    const y = parseFloat(String(posEdit?.y ?? '').trim());
    if (Number.isNaN(x) || Number.isNaN(y)) {
      Alert.alert('Position', 'Enter both X and Y in metres, for example 3.5 and 8.');
      return;
    }
    if (x < 0 || y < 0 || x > 500 || y > 500) {
      Alert.alert('Position', 'Coordinates are metres inside the house, 0 to 500.');
      return;
    }
    try {
      setPosSaving(true);
      await setSectionPosition(houseId, sectionId, x, y);
      setPosEdit(null);
      load();
      setToast({ text: `Placed at ${x} m, ${y} m`, kind: 'success' });
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setPosSaving(false);
    }
  };

  const blinkNode = async () => {
    if (!device) return;
    try {
      setBlinking(true);
      await identifyDevice(device.mac);
      setTimeout(() => setBlinking(false), 10000);   // matches the firmware's ~10s
    } catch (e) { setBlinking(false); setToast({ text: e.message, kind: 'error' }); }
  };

  /* "Is this node there?", answered in seconds rather than a heartbeat interval.

     The status dot on this card comes from the node's heartbeat, so it can be up
     to ~90s behind. That is fine for a dot and useless for someone standing at
     the box with the lid open. This asks the board directly and waits for it to
     answer, the same request-and-acknowledge shape as Water Now.

     A token comes back from the POST and is matched against the token the board
     echoes. That is what makes the answer trustworthy: without it, an ack left
     over from an earlier ping would report a dead node as alive - which is
     precisely the false confidence this button exists to remove. */
  const checkNode = async () => {
    if (!device || ping?.state === 'asking') return;
    setPing({ state: 'asking' });
    try {
      const { token } = await pingDevice(device.mac);
      const deadline = Date.now() + PING_TIMEOUT_MS;
      while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, PING_POLL_MS));
        let res = null;
        // A dropped poll is not a dead node - keep asking until the deadline.
        try { res = await getPingResult(device.mac, token); } catch { continue; }
        if (res?.answered) {
          setPing({ state: 'ok' });
          load();                        // pull the fresher lastSeen into the card
          setTimeout(() => setPing(null), 4000);
          return;
        }
      }
      setPing({ state: 'timeout' });
      setTimeout(() => setPing(null), 6000);
    } catch (e) {
      setPing({ state: 'timeout' });
      setToast({ text: e.message, kind: 'error' });
      setTimeout(() => setPing(null), 6000);
    }
  };

  useFocusEffect(useCallback(() => {
    load();                                   // live: refresh every 15 s while open
    const id = setInterval(load, LIVE_MS);
    return () => clearInterval(id);
  }, [load]));

  // The chart, on its own much slower schedule. See the note in load().
  useFocusEffect(useCallback(() => {
    let alive = true;
    const pull = async () => {
      try {
        const h = await getHistory(houseId, sectionId, range.points, range.hours);
        if (alive) setSeries(h?.series || []);
      } catch (_) { /* the readings above are what matter; a chart gap is cosmetic */ }
    };
    pull();
    const id = setInterval(pull, 120000);
    return () => { alive = false; clearInterval(id); };
  }, [houseId, sectionId, range]));

  /* Start a pour and hand it to the live run state.
     Nothing here waits for the node - `runWatch` below does that, so the screen
     stays usable and the farmer can Stop rather than only watch. */
  const runAction = async (kind, seconds) => {
    const secs = seconds ?? (kind === 'water'
      ? (sec?.plan?.durationSec || 45)
      : (sec?.tray?.fillSeconds || 15));
    setSheet(null);
    setAgain(null);
    setBusy(kind);
    try {
      const r = kind === 'water'
        ? await waterSection(houseId, sectionId, secs, !!addFert)
        : await fillTray(houseId, sectionId, secs);
      const id = r?.command?.id || r?.nodeCommand?.id || null;
      setRun({ kind, id, secs, remaining: secs, phase: 'sending', sentAt: Date.now() });
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setBusy(null);
    }
  };

  /* Follows a pour using what the NODE says, never a timer the phone started.

     The node acknowledges twice: once with started=true the moment the relay
     closes, and again when it opens. Those two messages are the only honest
     basis for a countdown - for months this project reported success from the
     server accepting a command, while no hardware had heard of it. */
  useEffect(() => {
    if (!run) return undefined;
    let alive = true;

    const tick = async () => {
      try {
        /* Ask about OUR command by id.

           This used to read whatever command document happened to be present
           and bail out unless its id matched. Pressing Stop REPLACES that
           document with the stop, so from that moment the check could never
           match again: the poll returned early forever, the countdown kept
           running and the Stop button span indefinitely, while the relay had
           in fact already opened. The ack keeps its own id, so that is what
           this follows. */
        const st = await getCommandStatus(houseId, sectionId, run.id);
        if (!alive || !run.id || st.ack?.id !== run.id) return;

        if (st.running) {
          setRun((r) => (r && r.id === run.id
            ? { ...r, phase: 'running',
                remaining: st.remainingSec != null ? st.remainingSec : r.remaining }
            : r));
          return;
        }

        if (st.ack?.done) {
          const wasStopped = !!st.ack.stopped;
          setRun(null);
          setStopping(false);
          load();
          if (wasStopped) {
            setToast({ text: `${sec?.meta?.name || sectionId}: stopped early`,
                       kind: 'info' });
          } else {
            // Ran its full time. Offer another go rather than making the farmer
            // walk back through the confirm sheet to add a little more water.
            setAgain({ kind: run.kind, secs: run.secs });
          }
        }
      } catch (_) { /* a dropped poll is not a failure; the next one will do */ }
    };

    // A node that never picks the command up must not leave a spinner forever.
    const giveUp = setTimeout(() => {
      if (!alive) return;
      setRun((r) => {
        if (r && r.id === run.id && r.phase === 'sending') {
          setToast({ text: 'The node has not picked this up. It may be offline.',
                     kind: 'error' });
          return null;
        }
        return r;
      });
    }, 60000);

    const id = setInterval(tick, 2000);
    tick();
    return () => { alive = false; clearInterval(id); clearTimeout(giveUp); };
  }, [run?.id, houseId, sectionId]);

  // History is fetched only when its tab is opened, and again after any run
  // finishes — there is no reason to pay for it while the farmer is on Now.
  useEffect(() => {
    if (tab !== 'history') return undefined;
    let alive = true;
    setEvLoading(true);
    getSectionEvents(houseId, sectionId, 40)
      .then((r) => { if (alive) setEvents(r); })
      .catch(() => { if (alive) setEvents(null); })
      .finally(() => { if (alive) setEvLoading(false); });
    return () => { alive = false; };
  }, [tab, houseId, sectionId, run?.id]);

  // Local 1 s countdown between server polls, so the number moves smoothly.
  useEffect(() => {
    if (run?.phase !== 'running') return undefined;
    const id = setInterval(() => {
      setRun((r) => (r && r.remaining > 0 ? { ...r, remaining: r.remaining - 1 } : r));
    }, 1000);
    return () => clearInterval(id);
  }, [run?.phase]);

  /* Cut a pour short.
     The node checks for this about every 5 s while the relay is on, so the
     button reports "Stopping" rather than pretending it is instant. */
  const stopRun = async () => {
    setSheet(null);
    setStopping(true);
    try {
      await stopSection(houseId, sectionId);
      setToast({ text: 'Stop sent to the node…', kind: 'info' });
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
      setStopping(false);
    }
  };

  // setMode takes a patch: send only the key that changed, so one toggle can
  // never silently reset the other. Failures roll the switch back instead of
  // leaving the UI showing a state the device never accepted.
  // A section normally follows the farm switch. Pinning is for the odd case:
  // one tray leaking, or a section being repotted, without having to turn the
  // whole farm manual.
  const applyOverride = async (v) => {
    const prev = override;
    setSheet(null);
    setOverride(v);
    try {
      await setSectionOverride(houseId, sectionId, v);
      await load();
      const opt = CONTROL_OPTIONS.find((o) => o.override === v) || CONTROL_OPTIONS[0];
      setToast({ text: `This section now: ${opt.label.toLowerCase()}`, kind: 'success' });
    } catch (e) {
      setOverride(prev);
      setToast({ text: e.message, kind: 'error' });
    }
  };
  const toggleTray = async (v) => {
    setTrayOn(v);
    try { await setMode(houseId, sectionId, { trayEnabled: v }); }
    catch (e) { setTrayOn(!v); setToast({ text: e.message, kind: 'error' }); }
  };

  // Skeleton, not a spinner: this screen takes a second or two to load and a
  // bare spinner on a blank page reads as a hang.
  if (loading) return (
    <View style={styles.container}>
      <ScreenHeader title="Loading…" subtitle={houseName || houseId}
        navigation={navigation} showBack />
      <ScrollView contentContainerStyle={styles.scroll}>
        <SectionSkeleton />
      </ScrollView>
    </View>
  );

  if (picking || linking) return (
    <View style={styles.container}>
      <ScreenHeader title="Link a node"
        subtitle={`for ${sec?.meta?.name || sectionId}`}
        navigation={navigation} showBack />
      {linking
        ? <View style={[styles.container, styles.center]}>
            <ActivityIndicator color={COLORS.primary} />
            <Text style={styles.linkWait}>Linking…</Text>
          </View>
        : <NodePicker onSelect={linkNode} onSkip={() => setPicking(false)} />}
    </View>
  );

  const est    = sec?.estimated || null;
  const plan   = sec?.plan   || {};
  const tray   = sec?.tray   || {};
  const meta   = sec?.meta   || {};
  const fcast  = sec?.forecast || null;
  /* An estimate is only worth showing while it still describes this hour. An
     hour-old kriging of a farm's microclimate is describing weather that has
     moved on, and it would look exactly as confident as a fresh one. */
  const rawLatest = sec?.latest || {};
  const estAgeMin = est?.timestampMs ? (Date.now() - est.timestampMs) / 60000 : null;
  const estUsable = !!est && estAgeMin != null && estAgeMin >= 0 && estAgeMin <= 60;
  /* Only stand in where there is nothing of this section's own. A stale real
     reading still beats a neighbour's guess, because it at least happened
     here. */
  const usingEstimate = estUsable && !rawLatest.timestamp;

  const latest = usingEstimate
    ? { temperature: est.temperature, humidity: est.humidity,
        light: est.light, vpd: est.vpd, timestamp: est.timestampMs }
    : rawLatest;

  const rh = humidityStatus(latest.humidity);
  const vp = vpdStatus(latest.vpd ?? tray.vpd);
  const sig = signalLabel(device?.rssi);

  /* Three questions, answered once, that the rest of the screen reads from.

     `live` is the only state in which a number is shown in colour or an action
     button is pressable. The backend marks a reading untrusted as soon as the
     node has missed two of the readings it promised - 10 minutes on the 5-minute
     production setting, 1.5 minutes on the 15-second demo setting - so this
     follows the node's own interval rather than a fixed timeout.

     Watering is blocked rather than merely discouraged: the firmware only acts
     on a command it polls for, so a command sent to a silent node does nothing
     while the app reports success. Better to say why up front. */
  const fresh = usingEstimate
    ? { state: 'estimated',
        ageMinutes: Math.round(estAgeMin),
        label: `estimated ${Math.round(estAgeMin)} min ago`,
        trusted: false,
        message: `No sensor in this zone. These figures are interpolated from `
                 + `${est.anchorCount} nearby section(s) that do have one.` }
    : (sec?.freshness || null);

  const live   = fresh?.state === 'live';
  const noNode = fresh?.state === 'nonode' || (!device && !latest.timestamp);

  /* Two separate questions, and conflating them is what makes a control lie.

     Do we have numbers worth acting on?  live, or a fresh estimate.
     Is there anything that will act?      something must COLLECT the command.

     The second is the one that matters here. The firmware polls only its own
     assigned section - BASE + "/command.json" - so a section with no node has
     nobody reading its command path. A command written there is not delayed,
     it is never seen, while the app reports success, a countdown runs and the
     event log records a watering that did not happen.

     There is no master controller in the deployed firmware. `routedTo` is the
     hook for one: when the backend can route an unmonitored zone's commands to
     a shared valve it will set that field, and these buttons come alive with no
     further change here. Until then an estimated section can be READ from and
     not watered, which is the truth. */
  const dataOk    = live || usingEstimate;
  const canActuate = !!device || !!(sec?.control?.routedTo);
  const actionsOff = !dataOk || !canActuate;

  const blockReason = !canActuate
    ? (usingEstimate
        ? 'These readings are estimated from nearby sections, but this zone has no '
          + 'node or valve of its own, so there is nothing here to open. Link a node '
          + 'to water it from the app.'
        : 'No sensor node is linked to this section, so there is nothing to send the '
          + 'command to.')
    : `This node last reported ${fresh?.label || 'a while ago'} and has missed readings since. `
      + 'Watering on numbers this old could soak plants that do not need it.';
  /* The tray is on a cooldown of its own, separate from node health.
     A 3 cm tray physically cannot dry out inside the cooldown, so a second fill
     would overflow rather than help - which is why the backend refuses one and
     why the button must not invite it. Only Fill Tray is affected; watering the
     roots is a different loop and stays available. */
  const trayCoolingDown = tray?.status === 'cooldown' && Number(tray?.hoursUntilNextFill) > 0;
  const trayCoolReason  =
    `The tray was filled ${tray?.hoursSinceFill != null ? `${tray.hoursSinceFill}h ago` : 'recently'}`
    + ` and cannot take more for another ${tray?.hoursUntilNextFill}h.`
    + ' Refilling now would overflow it rather than raise humidity.';

  // A missing value prints as -- rather than as a plausible-looking number.
  const fmt = (v, d) => (v == null || Number.isNaN(Number(v)) ? '--' : Number(v).toFixed(d));

  return (
    <View style={styles.container}>
      {/* showBack: this screen is pushed from My Farm, so it needs a way out */}
      <ScreenHeader title={meta.name || sectionId}
        subtitle={`${houseName || houseId}${meta.label ? ' · ' + meta.label : ''}`}
        navigation={navigation} showBack />

      <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />

      {/* Every dialog that can move water, or destroy something, goes through
          these. They replace Alert.alert, which is the operating system's own
          box: unstyleable, and unable to show a list or a value. */}
      <ConfirmSheet
        visible={sheet === 'water'}
        icon="rainy-outline"
        title="Water this section?"
        body={`The pump will run for ${sec?.plan?.durationSec || 45} seconds in `
            + `${sec?.meta?.name || sectionId}.`}
        caution="Vanda roots rot if they are watered too often. Only do this if the plants clearly need it."
        confirmLabel={addFert ? 'Water and feed' : 'Water now'}
        busy={busy === 'water'}
        onCancel={() => setSheet(null)}
        onConfirm={() => runAction('water')}>

        {/* Plant food is a decision made HERE, with the evidence to make it.
            Fertiliser only ever goes in with water, so this is the only moment
            it can be chosen - but the app used to announce it as already
            decided, with no way to decline and no indication of when the
            section was last fed. */}
        <View style={styles.fsBox}>
          <View style={styles.fsHead}>
            <Ionicons name="flask-outline" size={17}
              color={addFert ? COLORS.fertilizer : COLORS.textTertiary} />
            <View style={{ flex: 1 }}>
              <Text style={styles.fsTitle}>Mix in plant food</Text>
              <Text style={styles.fsSub}>
                {fert?.due
                  ? `Due now · ${fert.npkType} at ${Math.round((fert.strength || 0.5) * 100)}% strength`
                  : 'Not due yet'}
              </Text>
            </View>
            <Switch
              value={addFert}
              onValueChange={setAddFert}
              trackColor={{ false: COLORS.border, true: `${COLORS.fertilizer}40` }}
              thumbColor={addFert ? COLORS.fertilizer : COLORS.textTertiary}
              accessibilityLabel="Mix plant food into this watering"
            />
          </View>

          <View style={styles.fsRow}>
            <Text style={styles.fsKey}>Last fed</Text>
            <Text style={styles.fsVal}>
              {fert?.everFertilized
                ? (fert.lastFertilizedAt || `${Math.round(fert.daysSinceFertilize || 0)} days ago`)
                : 'Not recorded yet'}
            </Text>
          </View>
          <View style={styles.fsRow}>
            <Text style={styles.fsKey}>Feeds every</Text>
            <Text style={styles.fsVal}>
              {fert?.intervalDays || 7} days · {fert?.growthStage || 'Active'}
            </Text>
          </View>

          {addFert && !fert?.due && (
            <Text style={styles.fsWarn}>
              This section is not due. Feeding early builds up salts in the roots.
            </Text>
          )}
        </View>
      </ConfirmSheet>

      <ConfirmSheet
        visible={sheet === 'fill'}
        icon="add-circle-outline"
        title="Fill the humidity tray?"
        body={`The valve will open for ${sec?.tray?.fillSeconds || 15} seconds. The water `
            + 'evaporates to raise humidity around the plants; it does not touch the roots.'}
        confirmLabel="Fill tray"
        busy={busy === 'fill'}
        onCancel={() => setSheet(null)}
        onConfirm={() => runAction('fill')}
      />

      {/* Shown when a pour ended on its OWN, never when it was stopped.

          A farmer watching a plant take water often wants a little more, and
          before this the only route was back through the confirm sheet. The
          extra run is deliberately shorter than the first: topping up is the
          common case, repeating a full dose is not. */}
      <ConfirmSheet
        visible={!!again}
        icon={again?.kind === 'water' ? 'checkmark-circle-outline' : 'checkmark-circle-outline'}
        title={again?.kind === 'water' ? 'Watering finished' : 'Tray filled'}
        body={`${sec?.meta?.name || sectionId} ran for ${again?.secs || 0} seconds and stopped `
            + 'by itself. Does it need a little more?'}
        caution={again?.kind === 'water'
          ? 'Vanda roots rot if they stay wet. Only add more if the roots still look silvery.'
          : undefined}
        confirmLabel={`Run ${Math.max(5, Math.round((again?.secs || 10) / 2))}s more`}
        cancelLabel="No, done"
        onCancel={() => setAgain(null)}
        onConfirm={() => {
          const extra = Math.max(5, Math.round((again?.secs || 10) / 2));
          const kind = again?.kind;
          setAgain(null);
          runAction(kind, extra);
        }}
      />

      {/* Stopping mid-pour is a real decision: a half-delivered dose is not the
          same as none, and the farmer has to choose knowing that. */}
      <ConfirmSheet
        visible={sheet === 'stop'}
        icon="stop-circle-outline"
        title={run?.kind === 'water' ? 'Stop watering?' : 'Stop filling the tray?'}
        body={`${sec?.meta?.name || sectionId} has about ${Math.max(0, run?.remaining || 0)} `
            + 'seconds left. Stopping now leaves it part-way through, and the node '
            + 'takes a few seconds to react.'}
        confirmLabel="Stop now"
        destructive
        busy={stopping}
        cancelLabel="Keep going"
        onCancel={() => setSheet(null)}
        onConfirm={stopRun}
      />

      <ConfirmSheet
        visible={sheet === 'unlink'}
        icon="unlink-outline"
        title={`Unlink Node ${device?.shortId || ''}?`}
        body={'This section will stop receiving readings until another node is linked. '
            + 'The node itself keeps running and becomes free to link elsewhere.'}
        confirmLabel="Unlink"
        destructive
        busy={unlinking}
        onCancel={() => setSheet(null)}
        onConfirm={unlinkNode}
      />

      <ConfirmSheet
        visible={sheet === 'delete'}
        icon="trash-outline"
        title="Delete this section?"
        body="Its readings and settings will be removed, and any node linked to it is released."
        caution="This cannot be undone."
        confirmLabel="Delete"
        destructive
        onCancel={() => setSheet(null)}
        onConfirm={removeSection}
      />

      <SelectSheet
        visible={sheet === 'control'}
        title="How should this section run?"
        options={CONTROL_OPTIONS.map((o) => ({
          key: o.key,
          label: o.label,
          sub: o.key === 'follow'
            ? `Automatic care is currently ${farmAuto ? 'ON' : 'OFF'}`
            : o.key === 'auto'
              ? 'Acts by itself even when the farm switch is off'
              : 'Only ever alerts you, never acts',
        }))}
        value={(CONTROL_OPTIONS.find((o) => o.override === override) || CONTROL_OPTIONS[0]).key}
        confirmOnSelect={false}
        confirmLabel="Save"
        onCancel={() => setSheet(null)}
        onConfirm={(key) =>
          applyOverride((CONTROL_OPTIONS.find((o) => o.key === key) || CONTROL_OPTIONS[0]).override)}
      />

      <SelectSheet
        visible={sheet === 'interval'}
        title="How often should this node read?"
        subtitle="Faster suits a demo, slower saves battery. The node picks the change up on its next cycle."
        options={READ_INTERVALS.map((o) => ({
          key: String(o.ms), label: o.label, sub: o.hint,
        }))}
        value={String(device?.readIntervalMs ?? '')}
        confirmOnSelect={false}
        confirmLabel="Save"
        busy={savingIv != null}
        onCancel={() => setSheet(null)}
        onConfirm={(key) => applyInterval(Number(key))}
      />

      {/* Two fields and a warning. Deliberately not a scan-and-pick list: the
          node cannot report the networks IT can see, only the ones this phone
          can, and those are not the same place. */}
      <Sheet
        visible={!!wifi}
        title="Change the node's Wi-Fi"
        subtitle={`Node ${device?.shortId || ''} will restart onto the new network.`}
        onClose={() => (wifi?.saving ? null : setWifi(null))}>
        <View style={styles.wHead}>
          <Text style={[styles.wLbl, { marginTop: 0 }]}>Network</Text>
          <TouchableOpacity onPress={scanWifi} disabled={!!wifi?.scanning || !!wifi?.saving}
            activeOpacity={0.7} accessibilityRole="button"
            accessibilityLabel="Scan again for networks">
            <Text style={styles.wRescan}>{wifi?.scanning ? 'Scanning…' : 'Scan again'}</Text>
          </TouchableOpacity>
        </View>

        {/* What the NODE can see, strongest first. */}
        {wifi?.scanning && !wifi?.networks?.length ? (
          <View style={styles.wScan}>
            <ActivityIndicator size="small" color={COLORS.primary} />
            <Text style={styles.wScanTxt}>
              Asking the node which networks it can reach. This takes a few seconds.
            </Text>
          </View>
        ) : null}

        {!wifi?.scanning && !wifi?.networks?.length && !wifi?.manual ? (
          <View style={styles.wScan}>
            <Ionicons name="alert-circle-outline" size={18} color={COLORS.textTertiary} />
            <Text style={styles.wScanTxt}>
              The node did not report any networks. It may be offline, or the scan
              may still be running — try again, or enter the name by hand.
            </Text>
          </View>
        ) : null}

        {wifi?.networks?.map((net) => {
          const chosen = net.ssid === wifi?.ssid;
          return (
            <TouchableOpacity key={net.ssid}
              style={[styles.wNet, chosen && styles.wNetOn]}
              onPress={() => setWifi((w) => ({ ...w, ssid: net.ssid }))}
              disabled={!!wifi?.saving}
              activeOpacity={0.7}
              accessibilityRole="button"
              accessibilityState={{ selected: chosen }}
              accessibilityLabel={`${net.ssid}, signal ${net.rssi} dBm`
                + `${net.secure ? ', password needed' : ', open network'}`}>
              <Ionicons
                name={net.rssi > -60 ? 'wifi' : net.rssi > -80 ? 'wifi-outline' : 'cellular-outline'}
                size={18}
                color={chosen ? COLORS.primary : COLORS.textTertiary} />
              <View style={{ flex: 1 }}>
                <Text style={[styles.wNetName, chosen && { color: COLORS.primary }]}
                  numberOfLines={1}>{net.ssid}</Text>
                <Text style={styles.wNetSub}>
                  {net.rssi > -60 ? 'Strong' : net.rssi > -80 ? 'Usable' : 'Weak'}
                  {` · ${net.rssi} dBm`}{net.secure ? '' : ' · open'}
                </Text>
              </View>
              {!!net.secure && (
                <Ionicons name="lock-closed" size={13} color={COLORS.textTertiary} />
              )}
              {chosen && <Ionicons name="checkmark-circle" size={19} color={COLORS.primary} />}
            </TouchableOpacity>
          );
        })}

        {/* A hidden network never appears in a scan, so typing stays possible. */}
        {wifi?.manual ? (
          <TextInput
            style={[styles.wInput, { marginTop: SPACE.sm }]}
            value={wifi?.ssid || ''}
            onChangeText={(t) => setWifi((w) => ({ ...w, ssid: t }))}
            placeholder="Network name"
            placeholderTextColor={COLORS.textTertiary}
            autoCapitalize="none"
            autoCorrect={false}
            editable={!wifi?.saving}
          />
        ) : (
          <TouchableOpacity onPress={() => setWifi((w) => ({ ...w, manual: true, ssid: '' }))}
            activeOpacity={0.7} accessibilityRole="button"
            accessibilityLabel="Type a hidden network name instead">
            <Text style={styles.wManual}>My network is hidden — type the name</Text>
          </TouchableOpacity>
        )}

        <Text style={styles.wLbl}>Password</Text>
        <TextInput
          style={styles.wInput}
          value={wifi?.pass || ''}
          onChangeText={(t) => setWifi((w) => ({ ...w, pass: t }))}
          placeholder="Leave empty for an open network"
          placeholderTextColor={COLORS.textTertiary}
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
          editable={!wifi?.saving}
        />

        <View style={styles.wNote}>
          <Ionicons name="shield-checkmark-outline" size={16} color={COLORS.textTertiary} />
          <Text style={styles.wNoteTxt}>
            2.4 GHz only — the board has no 5 GHz radio. If the new network does not
            work, the node returns to the current one by itself after about a minute.
          </Text>
        </View>

        <TouchableOpacity
          style={[styles.wSave, (!((wifi?.ssid || '').trim()) || wifi?.saving) && { opacity: 0.5 }]}
          onPress={applyWifi}
          disabled={!((wifi?.ssid || '').trim()) || !!wifi?.saving}
          activeOpacity={0.85}
          accessibilityRole="button"
          accessibilityLabel="Send the new Wi-Fi settings to the node">
          {wifi?.saving
            ? <ActivityIndicator color="#FFF" size="small" />
            : <Ionicons name="wifi-outline" size={17} color="#FFF" />}
          <Text style={styles.wSaveTxt}>{wifi?.saving ? 'Sending…' : 'Move node to this network'}</Text>
        </TouchableOpacity>
      </Sheet>

      <RenameDialog
        visible={renaming}
        title="Rename section"
        label="Section name"
        value={meta.name || sectionId}
        placeholder="e.g. Section 1"
        onCancel={() => setRenaming(false)}
        onSave={async (name) => {
          await renameSection(houseId, sectionId, name);
          setRenaming(false);
          await load();
        }}
      />
      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}
        refreshControl={<RefreshControl refreshing={refresh} tintColor={COLORS.primary}
          onRefresh={() => { setRefresh(true); load(); }} />}>

        {/* Three jobs, not one scroll: what is happening now, what has
            happened, and how this section is set up. */}
        <View style={styles.tabs}>
          {[['now', 'Now', 'pulse-outline'],
            ['history', 'History', 'time-outline'],
            ['settings', 'Setup', 'options-outline']].map(([k, label, ic]) => (
            <TouchableOpacity key={k}
              style={[styles.tab, tab === k && styles.tabOn]}
              onPress={() => setTab(k)}
              activeOpacity={0.8}
              accessibilityRole="tab"
              accessibilityState={{ selected: tab === k }}
              accessibilityLabel={label}>
              <Ionicons name={ic} size={15}
                color={tab === k ? COLORS.primary : COLORS.textTertiary} />
              <Text style={[styles.tabTxt, tab === k && styles.tabTxtOn]}>{label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {tab === 'now' && (<>
          {/* How old these numbers are, said BEFORE they are shown.
              A reading with no age on it is the thing this project keeps getting
              caught by: a dead node's last value looks identical to a live one. */}
          <StaleWarning freshness={sec?.freshness} name={meta.name || sectionId} />

          {/* Live readings.

              Greyed, uncoloured and unlabelled the moment the node stops keeping
              its promise. An old number in full colour is indistinguishable from
              a current one, which is how a section with NO node at all came to
              display 28C and a green 70% "GOOD" - those were the model's fallback
              defaults leaking through, and 70% happens to sit in the ideal band.
              Nothing here is invented now: no reading prints as --. */}
          <View style={styles.grid}>
            {[
              ['thermometer-outline', COLORS.temperature, fmt(latest.temperature, 1), '°C',
               'Temperature', est?.temperatureSd],
              ['water-outline',       rh.color,           fmt(latest.humidity, 0),    '%',
               live ? `Humidity · ${rh.label}` : 'Humidity', est?.humiditySd],
              ['sunny-outline',       COLORS.light,       fmt(latest.light, 0),       'lux',
               'Light', est?.lightSd],
              ['speedometer-outline', vp.color,           fmt(latest.vpd ?? tray.vpd, 2), 'kPa',
               live ? `Drying · ${vp.label}` : 'Drying', null],
            ].map(([ic, c, v, u, l, sd], i) => {
              // An estimate is shown in its own colour, never in the colour a
              // measured reading uses, and never greyed out as though absent.
              const tone = usingEstimate ? COLORS.estimated
                         : live ? c : COLORS.textTertiary;
              return (
              <View key={i} style={[styles.tile, SHADOW.sm,
                                    !live && !usingEstimate && styles.tileDead,
                                    usingEstimate && styles.tileEst]}>
                <Ionicons name={ic} size={17} color={tone} />
                <Text style={[styles.tileVal, { color: tone }]}>
                  {v}<Text style={styles.tileUnit}>{u}</Text>
                </Text>
                {/* The spread is the point of kriging: an estimate without one
                    is just a number wearing someone else's confidence. */}
                {usingEstimate && sd != null && (
                  <Text style={styles.tileSd} maxFontSizeMultiplier={1.15}>
                    ±{Number(sd).toFixed(sd >= 10 ? 0 : 1)}{u}
                  </Text>
                )}
                <Text style={styles.tileLbl} numberOfLines={1}
                adjustsFontSizeToFit maxFontSizeMultiplier={1.15}>{l}</Text>
              </View>
              );
            })}
          </View>

          {/* Directly under the numbers, because it is the caveat on them: how
              old they are, and whether there is a node behind them at all. */}
          <View style={styles.freshRow}>
            <Text style={[styles.freshLbl, !live && { color: COLORS.warning }]}
            numberOfLines={1} adjustsFontSizeToFit maxFontSizeMultiplier={1.15}>
              {noNode ? 'No sensor node detected'
                      : live ? 'Last read'
                             : 'No signal — last read'}
            </Text>
            {!noNode && <FreshnessBadge freshness={fresh} />}
          </View>

          {/* While water is moving, the buttons are replaced by what is
              actually happening. The countdown and the Stop button are both
              anchored to the node's own acknowledgements, not to a timer this
              screen started - the node says when the relay closed and when it
              opened, and everything here follows that. */}
          {run ? (
            <View style={[styles.runCard, SHADOW.md]}>
              <View style={styles.runTop}>
                <Ionicons
                  name={run.kind === 'water' ? 'rainy' : 'add-circle'}
                  size={20}
                  color={run.kind === 'water' ? COLORS.primary : COLORS.info} />
                <Text style={styles.runTitle}>
                  {run.phase === 'sending'
                    ? (run.kind === 'water' ? 'Starting watering' : 'Starting tray fill')
                    : (run.kind === 'water' ? 'Watering now' : 'Filling the tray')}
                </Text>
                {run.phase === 'sending' && <ActivityIndicator size="small" color={COLORS.textTertiary} />}
              </View>

              {run.phase === 'sending' ? (
                <Text style={styles.runWait}>
                  Waiting for the node to pick this up. It checks every couple of seconds.
                </Text>
              ) : (
                <>
                  <Text style={styles.runCount}>
                    {Math.max(0, run.remaining)}<Text style={styles.runCountUnit}>s left</Text>
                  </Text>
                  <View style={styles.runTrack}>
                    <View style={[styles.runFill, {
                      width: `${Math.max(0, Math.min(100,
                        ((run.secs - Math.max(0, run.remaining)) / Math.max(1, run.secs)) * 100))}%`,
                      backgroundColor: run.kind === 'water' ? COLORS.primary : COLORS.info,
                    }]} />
                  </View>
                  <Text style={styles.runNote}>
                    It stops by itself after {run.secs} seconds.
                  </Text>
                </>
              )}

              <TouchableOpacity
                style={[styles.stopBtn, stopping && { opacity: 0.6 }]}
                onPress={() => setSheet('stop')}
                disabled={stopping}
                activeOpacity={0.85}
                accessibilityRole="button"
                accessibilityLabel="Stop this now">
                {stopping
                  ? <ActivityIndicator color={COLORS.danger} size="small" />
                  : <Ionicons name="stop-circle-outline" size={18} color={COLORS.danger} />}
                <Text style={styles.stopTxt}>{stopping ? 'Stopping…' : 'Stop now'}</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <>
            {/* The two things a farmer opens this screen to do, directly under the
                readings they decide from. They used to sit below the chart, the
                forecast, the plan, the tray, the fertilizer and the control card -
                far enough down that they were genuinely hard to find. */}
            <View style={styles.btnGrid}>
              {[
                ['water', 'Water Now',   'rainy-outline',      COLORS.primary,
               () => { setAddFert(!!fert?.due); setSheet('water'); }],
                ['fill',  'Fill Tray',   'add-circle-outline', COLORS.info,    () => setSheet('fill')],
              ].map(([k, label, ic, c, fn]) => {
                // Fill Tray carries one extra block the other button does not.
                const cooling = k === 'fill' && trayCoolingDown;
                const off = actionsOff || cooling;
                const why = cooling ? trayCoolReason : blockReason;
                return (
                <TouchableOpacity key={k}
                  style={[styles.btn, { backgroundColor: off ? COLORS.bgCardAlt : c },
                          !off && SHADOW.md, busy && { opacity: 0.6 }]}
                  onPress={fn} disabled={!!busy || off} activeOpacity={0.85}
                  accessibilityRole="button"
                  accessibilityState={{ disabled: off }}
                  accessibilityLabel={off ? `${label}, unavailable. ${why}` : label}>
                  {busy === k
                    ? <ActivityIndicator color="#FFF" size="small" />
                    : <Ionicons name={ic} size={17}
                        color={off ? COLORS.textTertiary : '#FFF'} />}
                  <Text style={[styles.btnText, off && { color: COLORS.textTertiary }]}>
                    {label}
                  </Text>
                </TouchableOpacity>
                );
              })}
            </View>

            {/* Same rule as below: a greyed button needs its reason beside it.
                Shown only when the node is otherwise fine, so the two notes
                never stack and contradict each other. */}
            {!actionsOff && trayCoolingDown && (
              <View style={styles.blockNote}>
                <Ionicons name="time-outline" size={14} color={COLORS.info} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.blockTxt}>{trayCoolReason}</Text>
                </View>
              </View>
            )}

            {/* A disabled button with no reason next to it reads as a broken app. */}
            {actionsOff && (
              <View style={styles.blockNote}>
                <Ionicons name="lock-closed-outline" size={14} color={COLORS.textTertiary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.blockTxt}>{blockReason}</Text>
                  {noNode && (
                    <TouchableOpacity onPress={() => setPicking(true)} activeOpacity={0.7}
                      accessibilityRole="button"
                      accessibilityLabel="Link a sensor node to this section">
                      <Text style={styles.blockLink}>Link a node</Text>
                    </TouchableOpacity>
                  )}
                </View>
              </View>
            )}
            </>
          )}

          {/* controls */}
          <SectionHead icon="options-outline" title="How this section runs"
            tint={COLORS.primary} tintDim={COLORS.primaryDim}
            status={(CONTROL_OPTIONS.find((o) => o.override === override) || CONTROL_OPTIONS[0])
                      .label.replace('Follow the farm', farmAuto ? 'Auto' : 'Manual')
                      .replace('Always automatic', 'Auto')
                      .replace('Always manual', 'Manual')}
            statusTone={override === 'manual' || (!override && !farmAuto)
                          ? COLORS.warning : COLORS.primary} />
          <View style={[styles.card, SHADOW.sm]}>
            <View style={styles.tRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.tTitle}>This section</Text>
              </View>
            </View>

            <DropRow
              icon="options-outline"
              label="Runs"
              value={(CONTROL_OPTIONS.find((o) => o.override === override) || CONTROL_OPTIONS[0]).label}
              onPress={() => setSheet('control')}
            />

            <View style={[styles.tRow, { borderTopWidth: 1, borderTopColor: COLORS.border, paddingTop: SPACE.md, marginTop: SPACE.md }]}>
              <View style={{ flex: 1 }}>
                <Text style={styles.tTitle}>Humidity tray</Text>
                <Text style={styles.tDesc}>Keep the 3 cm tray topped up automatically</Text>
              </View>
              <Switch value={trayOn} onValueChange={toggleTray}
                trackColor={{ false: COLORS.border, true: `${COLORS.info}40` }}
                thumbColor={trayOn ? COLORS.info : COLORS.textTertiary} />
            </View>
          </View>

          {/* today's plan */}
          <SectionHead icon="rainy-outline" title="Today's watering"
            tint={COLORS.info} tintDim={COLORS.infoDim}
            status={plan.waterTime || 'no plan'}
            statusTone={plan.waterTime ? COLORS.info : COLORS.textTertiary} />
          <View style={[styles.card, SHADOW.sm]}>
            {plan.waterTime ? (
              <>
                <View style={styles.planTop}>
                  <Text style={styles.planTime}>{plan.waterTime}</Text>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.planDur}>for {plan.durationSec} seconds</Text>
                    <Text style={styles.planDate}>{plan.date}</Text>
                  </View>
                </View>
                <Text style={styles.reason}>{plan.reason}</Text>
              </>
            ) : <Text style={styles.none}>No plan worked out for today yet.</Text>}
          </View>

          {/* humidity tray */}
          <SectionHead icon="water-outline" title="Humidity tray"
            tint={COLORS.humidity} tintDim={COLORS.humidityDim}
            status={tray.status === 'fill' ? 'needs water'
                  : tray.status === 'cooldown' ? 'resting'
                  : tray.status ? 'ok' : '\u2014'}
            statusTone={tray.status === 'fill' ? COLORS.warning
                      : tray.status === 'cooldown' ? COLORS.info : COLORS.success} />
          <View style={[styles.card, SHADOW.sm]}>
            <View style={styles.trayTop}>
              <Ionicons
                name={tray.status === 'cooldown' ? 'time' : 'water'}
                size={20}
                color={tray.status === 'fill' ? COLORS.warning
                     : tray.status === 'cooldown' ? COLORS.info : COLORS.success} />
              <Text style={styles.trayTxt}>{tray.message || `Target ${RH_LOW}–${RH_HIGH}% RH.`}</Text>
            </View>

            {tray.status === 'cooldown' && (
              <View style={styles.cooldown}>
                <View style={styles.cdRow}>
                  <Text style={styles.cdLabel}>Filled</Text>
                  <Text style={styles.cdVal}>{tray.hoursSinceFill}h ago</Text>
                </View>
                <View style={styles.cdRow}>
                  <Text style={styles.cdLabel}>Next fill allowed in</Text>
                  <Text style={[styles.cdVal, { color: COLORS.info }]}>{tray.hoursUntilNextFill}h</Text>
                </View>
                <View style={styles.cdBarTrack}>
                  <View style={[styles.cdBarFill, {
                    width: `${Math.max(0, Math.min(100,
                      ((tray.cooldownHours - tray.hoursUntilNextFill) / tray.cooldownHours) * 100))}%` }]} />
                </View>
                {tray.trayAtLimit && (
                  <Text style={styles.cdNote}>
                    Humidity is still low, but the tray has water, the air is very dry today.
                    Refilling would only overflow. Extra watering is the right fix.
                  </Text>
                )}
              </View>
            )}
            <View style={styles.barTrack}>
              <View style={[styles.barIdeal, { left: `${RH_LOW}%`, width: `${RH_HIGH - RH_LOW}%` }]} />
              {latest.humidity != null && (
                <View style={[styles.barMark, { left: `${Math.max(0, Math.min(100, latest.humidity))}%`, backgroundColor: rh.color }]} />
              )}
            </View>
            <Text style={styles.barLbl}>0%     ideal band {RH_LOW}–{RH_HIGH}%     100%</Text>
          </View>

          {/* Plant food.

              Read through one resolved object: the guard used to allow `fert` to
              be null while `sec.fertilizer` existed, and then read `fert.due`
              straight after - a crash waiting for the first section whose plan
              had not run yet.

              The card now shows WHEN it was last fed and when the next feed is
              due, because "due / not due" alone gave the farmer nothing to check
              against and no way to tell whether a feed had been recorded at
              all. */}
          {(() => {
            const f = fert || sec?.fertilizer;
            if (!f) return null;
            const due = !!f.due;
            const tone = due ? COLORS.fertilizer : COLORS.textTertiary;
            const every = f.intervalDays || 7;
            const since = f.daysSinceFertilize;
            const left = Math.max(0, Math.round(every - (since ?? 0)));
            return (
              <>
                <SectionHead icon="flask-outline" title="Plant food"
                  tint={COLORS.fertilizer} tintDim={COLORS.fertilizerDim}
                  status={due ? 'due now' : `in ${left}d`}
                  statusTone={due ? COLORS.fertilizer : COLORS.textTertiary} />
                <View style={[styles.card, SHADOW.sm,
                              { borderLeftWidth: 3, borderLeftColor: due ? COLORS.fertilizer : COLORS.border }]}>
                  <View style={styles.fertTop}>
                    <Ionicons name="flask-outline" size={18} color={tone} />
                    <Text style={[styles.fertNpk, { color: tone }]}>
                      {due ? `Due now \u00b7 ${f.npkType} at ${Math.round((f.strength || 0.5) * 100)}% strength`
                           : `Next feed in about ${left} day${left === 1 ? '' : 's'}`}
                    </Text>
                  </View>

                  <View style={styles.fertRows}>
                    <View style={styles.fertRow}>
                      <Text style={styles.fertKey}>Last fed</Text>
                      <Text style={styles.fertVal}>
                        {f.everFertilized
                          ? (f.lastFertilizedAt || `${Math.round(since ?? 0)} days ago`)
                          : 'Not recorded yet'}
                      </Text>
                    </View>
                    <View style={styles.fertRow}>
                      <Text style={styles.fertKey}>Feeds every</Text>
                      <Text style={styles.fertVal}>
                        {every} days \u00b7 {f.growthStage || 'Active'}
                      </Text>
                    </View>
                  </View>

                  {/* How far through the feeding cycle this section is. A date
                    alone does not answer "is it nearly due"; a bar does, at a
                    glance, without arithmetic. */}
                <View style={styles.fertBarWrap}>
                  <View style={styles.fertBarTrack}>
                    <View style={[styles.fertBarFill, {
                      width: `${Math.max(3, Math.min(100,
                        ((since ?? 0) / Math.max(1, every)) * 100))}%`,
                      backgroundColor: due ? COLORS.fertilizer : `${COLORS.fertilizer}66`,
                    }]} />
                  </View>
                  <Text style={styles.fertBarTxt}>
                    {due ? 'due' : `${left}d`}
                  </Text>
                </View>

                <Text style={styles.fertMsg}>{f.message}</Text>

                  {!f.everFertilized && (
                    <Text style={styles.fertHint}>
                      No feed has been recorded for this section yet, so it is shown as due once.
                      Watering it with plant food starts the schedule.
                    </Text>
                  )}
                </View>
              </>
            );
          })()}
        </>)}

        {tab === 'history' && (<>
          {/* history, over a range the farmer chooses */}
          <View style={styles.chartHead}>
            <SectionHead first style={{ flex: 1, marginBottom: 0 }}
              icon="analytics-outline" title="Conditions over time"
              tint={COLORS.temperature} tintDim={COLORS.temperatureDim} />
            <RangePicker
              options={HISTORY_RANGES}
              value={range.hours}
              onChange={(o) => setRange(o)}
            />
          </View>
          <View style={[styles.card, SHADOW.sm]}>
            <LineChart series={series} band={{ low: RH_LOW, high: RH_HIGH }} width={CHART_W} />
          </View>

          {/* What the model expects for the REST of today. This is what lets the
              tray be topped up before the heat instead of chasing it. */}
          {fcast?.hours?.length > 1 && (
            <>
              <View style={styles.chartHead}>
                <SectionHead first style={{ flex: 1, marginBottom: 0 }}
                  icon="partly-sunny-outline" title="Expected today"
                  tint={COLORS.light} tintDim={COLORS.lightDim} />
                {fcast.hotDay && (
                  <View style={styles.hotPill}>
                    <Ionicons name="flame" size={13} color={COLORS.danger} />
                    <Text style={styles.hotPillTxt}>Hot day</Text>
                  </View>
                )}
              </View>
              <View style={[styles.card, SHADOW.sm]}>
                <Text style={styles.fcLead}>
                  Around {String(fcast.peakHour).padStart(2, '0')}:00 this section is expected to
                  reach {fcast.peakTemp}°C, with humidity down to {fcast.minHumidity}%.
                </Text>
                <LineChart width={CHART_W} band={{ low: RH_LOW, high: RH_HIGH }}
                  series={fcast.hours.map((h, i) => ({
                    temperature: fcast.temperature[i],
                    humidity: fcast.humidity[i],
                    label: String(h).padStart(2, '0') + ':00',
                  }))} />
                <Text style={styles.fcNote}>
                  Predicted at dawn, so it is an estimate: peak temperature is usually within
                  {' '}{fcast.confidence?.peakTempMae?.toFixed?.(1) ?? '1'}°C. The system uses it
                  to act early, never to skip watering.
                </Text>
              </View>
            </>
          )}

          {/* What actually happened, from the node's own acknowledgements. */}
          <SectionHead first icon="list-outline" title="Watering and feeding"
            tint={COLORS.primary} tintDim={COLORS.primaryDim}
            status={events?.counts ? `${events.counts.waterings} runs` : undefined} />
          {evLoading && !events ? (
            <View style={[styles.card, SHADOW.sm, { alignItems: 'center', paddingVertical: SPACE.xl }]}>
              <ActivityIndicator color={COLORS.primary} />
            </View>
          ) : !events?.events?.length ? (
            <View style={[styles.card, SHADOW.sm]}>
              <Text style={styles.none}>
                Nothing recorded yet. Every watering and tray fill from now on is logged here,
                with how long it ran and whether plant food went in.
              </Text>
            </View>
          ) : (
            <>
              <View style={styles.evSummary}>
                <View style={styles.evStat}>
                  <Text style={styles.evStatV}>{events.counts?.waterings ?? 0}</Text>
                  <Text style={styles.evStatK}>waterings</Text>
                </View>
                <View style={styles.evStat}>
                  <Text style={styles.evStatV}>{events.counts?.feeds ?? 0}</Text>
                  <Text style={styles.evStatK}>with food</Text>
                </View>
                <View style={[styles.evStat, { flex: 1.6 }]}>
                  <Text style={styles.evStatV} numberOfLines={1}>{events.lastFed || 'never'}</Text>
                  <Text style={styles.evStatK}>last fed</Text>
                </View>
              </View>

              <View style={[styles.card, SHADOW.sm, { paddingVertical: SPACE.sm }]}>
                {events.events.map((e, i) => (
                  <View key={e.id || i}
                    style={[styles.evRow, i > 0 && styles.evRowDiv]}>
                    <Ionicons
                      name={e.action === 'tray' ? 'add-circle-outline' : 'rainy-outline'}
                      size={16}
                      color={e.action === 'tray' ? COLORS.info : COLORS.primary} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.evWhen}>{e.atLocal}</Text>
                      <Text style={styles.evWhat}>
                        {e.action === 'tray' ? 'Tray fill' : 'Watered'} {e.durationSec}s
                        {e.withFertilizer && e.npkType && e.npkType !== 'None'
                          ? `  \u00b7  ${e.npkType}`
                          : ''}
                        {`  \u00b7  ${e.by === 'auto' ? 'automatic' : 'by you'}`}
                      </Text>
                    </View>
                    {e.withFertilizer && (
                      <Ionicons name="flask" size={13} color={COLORS.fertilizer} />
                    )}
                    <Text style={[styles.evOk,
                                  { color: e.confirmed ? COLORS.success : COLORS.textTertiary }]}>
                      {e.stoppedEarly ? 'stopped' : e.confirmed ? 'confirmed' : 'sent'}
                    </Text>
                  </View>
                ))}
              </View>
              <Text style={styles.evNote}>
                “Confirmed” means the node reported back that the relay ran. “Sent” means the
                command was written but no acknowledgement has arrived.
              </Text>
            </>
          )}
        </>)}

        {tab === 'settings' && (<>
          {/* Which physical node reports for this section. A section with no node
              is a normal state, not an error, so it gets an explanation rather
              than a warning. */}
          <SectionHead first icon="hardware-chip-outline" title="Sensor node"
            tint={COLORS.textSecondary} tintDim={COLORS.bgCardAlt}
            status={device ? (device.online ? 'online' : 'offline') : 'none linked'}
            statusTone={device?.online ? COLORS.success : COLORS.textTertiary} />
          <View style={[styles.card, SHADOW.sm]}>
            {device ? (
              <>
                <View style={styles.nodeTop}>
                  <View style={[styles.nodeDot, { backgroundColor: device.online ? COLORS.success : COLORS.textTertiary }]} />
                  <Text style={styles.nodeName}>Node {device.shortId}</Text>
                  <Text style={[styles.nodeState, { color: device.online ? COLORS.success : COLORS.textTertiary }]}>
                    {device.online ? 'Online' : 'Offline'}
                  </Text>
                </View>
                <Text style={styles.nodeMeta}>
                  Seen {lastSeenLabel(device.lastSeenSec)} · {sig.label} signal
                  {device.ip ? ` · ${device.ip}` : ''}
                </Text>
                <Text style={styles.nodeMac}>{device.mac}</Text>

                <View style={styles.ivBlock}>
                  <DropRow
                    icon="reload-outline"
                    label="Reads"
                    value={intervalLabel(device.readIntervalMs)}
                    onPress={() => setSheet('interval')}
                    disabled={savingIv != null}
                  />
                  <DropRow
                    icon="wifi-outline"
                    label="Wi-Fi"
                    value={device.ssid || 'Change'}
                    onPress={() => { setWifi({ ssid: '', pass: '', saving: false,
                                               scanning: true, networks: [] });
                                     scanWifi(); }}
                  />
                </View>

                <View style={styles.nodeBtns}>
                  <TouchableOpacity style={[styles.nodeBtn, blinking && styles.nodeBtnOn]}
                    onPress={blinkNode} disabled={blinking} activeOpacity={0.8}
                    accessibilityRole="button"
                    accessibilityLabel={`Identify node ${device.shortId} by blinking its light`}>
                    <Ionicons name="flashlight-outline" size={15}
                      color={blinking ? '#FFF' : COLORS.primary} />
                    <Text style={[styles.nodeBtnTxt, blinking && { color: '#FFF' }]}>
                      {blinking ? 'Blinking' : 'Identify'}
                    </Text>
                  </TouchableOpacity>

                  <TouchableOpacity
                    style={[styles.nodeBtn,
                            ping?.state === 'ok' && styles.nodeBtnOk,
                            ping?.state === 'timeout' && styles.nodeBtnBad]}
                    onPress={checkNode} disabled={ping?.state === 'asking'} activeOpacity={0.8}
                    accessibilityRole="button"
                    accessibilityLabel={`Check whether node ${device.shortId} is responding now`}>
                    {ping?.state === 'asking'
                      ? <ActivityIndicator size="small" color={COLORS.primary} />
                      : <Ionicons
                          name={ping?.state === 'ok' ? 'checkmark-circle-outline'
                                : ping?.state === 'timeout' ? 'alert-circle-outline'
                                : 'pulse-outline'}
                          size={15}
                          color={ping?.state === 'ok' ? '#FFF'
                                 : ping?.state === 'timeout' ? COLORS.danger : COLORS.primary} />}
                    <Text
                      style={[styles.nodeBtnTxt,
                              ping?.state === 'ok' && { color: '#FFF' },
                              ping?.state === 'timeout' && { color: COLORS.danger }]}
                      numberOfLines={1} maxFontSizeMultiplier={1.15}>
                      {ping?.state === 'asking' ? 'Checking…'
                       : ping?.state === 'ok' ? 'Answered'
                       : ping?.state === 'timeout' ? 'No answer' : 'Check'}
                    </Text>
                  </TouchableOpacity>
                </View>

                {/* Unlink gets its own row. Three buttons abreast clipped their
                    labels at large system font sizes. */}
                <View style={[styles.nodeBtns, { marginTop: SPACE.sm }]}>
                  <TouchableOpacity style={styles.unlinkBtn}
                    onPress={() => setSheet('unlink')} disabled={unlinking} activeOpacity={0.8}
                    accessibilityRole="button"
                    accessibilityLabel={`Unlink node ${device.shortId} from this section`}>
                    {unlinking ? <ActivityIndicator color={COLORS.danger} size="small" />
                               : <Ionicons name="unlink-outline" size={15} color={COLORS.danger} />}
                    <Text style={styles.unlinkTxt}>{unlinking ? 'Unlinking…' : 'Unlink node'}</Text>
                  </TouchableOpacity>
                </View>
              </>
            ) : (
              <>
                <View style={styles.nodeTop}>
                  <View style={[styles.nodeDot, { backgroundColor: COLORS.textTertiary }]} />
                  <Text style={styles.nodeName}>No node linked</Text>
                </View>
                <Text style={styles.nodeHint}>
                  This section has no sensor node, so it has no readings and cannot be
                  watered from the app. Power a node on, then link it here.
                </Text>
                <TouchableOpacity style={styles.linkBtn} onPress={() => setPicking(true)}
                  activeOpacity={0.85} accessibilityRole="button"
                  accessibilityLabel="Link a sensor node to this section">
                  <Ionicons name="add-circle-outline" size={16} color="#FFF" />
                  <Text style={styles.linkBtnTxt}>Link a node</Text>
                </TouchableOpacity>
              </>
            )}
          </View>

          {/* ── POSITION ────────────────────────────────────────────────
              Metres from whichever corner of the house the farmer picks, used
              consistently for every section. The origin is arbitrary because
              kriging works on the distances between sections; what matters is
              that it does not move once chosen. */}
          <Text style={styles.sectionLabel}>POSITION IN THE HOUSE</Text>
          <View style={[styles.card, SHADOW.sm]}>
            {posEdit ? (
              <>
                <View style={styles.durRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.durLabel}>X (metres)</Text>
                    <TextInput style={styles.durInput} value={posEdit.x}
                      onChangeText={(v) => setPosEdit({ ...posEdit, x: v })}
                      keyboardType="numbers-and-punctuation" placeholder="0.0"
                      placeholderTextColor={COLORS.textTertiary}
                      maxFontSizeMultiplier={1.15} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.durLabel}>Y (metres)</Text>
                    <TextInput style={styles.durInput} value={posEdit.y}
                      onChangeText={(v) => setPosEdit({ ...posEdit, y: v })}
                      keyboardType="numbers-and-punctuation" placeholder="0.0"
                      placeholderTextColor={COLORS.textTertiary}
                      maxFontSizeMultiplier={1.15} />
                  </View>
                </View>
                <Text style={styles.durHint}>
                  Measure from the same corner for every section. Once four sections
                  are placed and reporting, zones without a node can be estimated
                  from their neighbours.
                </Text>
                <View style={styles.durBtns}>
                  <TouchableOpacity style={styles.durCancel} onPress={() => setPosEdit(null)}
                    disabled={posSaving} accessibilityRole="button">
                    <Text style={styles.durCancelTxt}>Cancel</Text>
                  </TouchableOpacity>
                  <TouchableOpacity style={styles.durSave} onPress={savePosition}
                    disabled={posSaving} accessibilityRole="button">
                    {posSaving ? <ActivityIndicator size="small" color="#FFF" />
                               : <Text style={styles.durSaveTxt}>Save</Text>}
                  </TouchableOpacity>
                </View>
              </>
            ) : (
              <TouchableOpacity style={styles.durView} activeOpacity={0.7}
                onPress={() => setPosEdit({
                  x: meta.x != null ? String(meta.x) : '',
                  y: meta.y != null ? String(meta.y) : '',
                })}
                accessibilityRole="button"
                accessibilityLabel="Set where this section is in the house">
                <Ionicons name="location-outline" size={22}
                  color={meta.x != null ? COLORS.primary : COLORS.textTertiary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.durValue}>
                    {meta.x != null ? `${meta.x} m, ${meta.y} m` : 'Not placed'}
                  </Text>
                  <Text style={styles.durSub}>
                    {meta.x != null
                      ? 'Used to estimate zones that have no sensor of their own.'
                      : 'Tap to say where this section sits in the house.'}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={COLORS.textTertiary} />
              </TouchableOpacity>
            )}
          </View>

          {/* ── POUR LENGTHS ─────────────────────────────────────────────
              How long the pump runs, not when. The models keep deciding the
              time of day and whether the tray needs anything; these only
              replace the length once that decision is made, which is why a
              blank box means "automatic" rather than "never". */}
          <Text style={styles.sectionLabel}>POUR LENGTHS</Text>
          <View style={[styles.card, SHADOW.sm]}>
            {durEdit ? (
              <>
                <View style={styles.durRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.durLabel}>Watering (30–120s)</Text>
                    <TextInput style={styles.durInput} value={durEdit.water}
                      onChangeText={(v) => setDurEdit({ ...durEdit, water: v })}
                      keyboardType="number-pad" placeholder="auto"
                      placeholderTextColor={COLORS.textTertiary}
                      maxFontSizeMultiplier={1.15} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.durLabel}>
                      Tray fill (1–{tray?.maxSeconds ?? 15}s)
                    </Text>
                    <TextInput style={styles.durInput} value={durEdit.tray}
                      onChangeText={(v) => setDurEdit({ ...durEdit, tray: v })}
                      keyboardType="number-pad" placeholder="auto"
                      placeholderTextColor={COLORS.textTertiary}
                      maxFontSizeMultiplier={1.15} />
                  </View>
                </View>
                <Text style={styles.durHint}>
                  Leave a box empty to let the system choose. It still decides when to
                  water — these only set how long the pump runs.
                </Text>
                <View style={styles.durBtns}>
                  <TouchableOpacity style={styles.durCancel} onPress={() => setDurEdit(null)}
                    disabled={durSaving} accessibilityRole="button">
                    <Text style={styles.durCancelTxt}>Cancel</Text>
                  </TouchableOpacity>
                  <TouchableOpacity style={styles.durSave} onPress={saveDurations}
                    disabled={durSaving} accessibilityRole="button">
                    {durSaving ? <ActivityIndicator size="small" color="#FFF" />
                               : <Text style={styles.durSaveTxt}>Save</Text>}
                  </TouchableOpacity>
                </View>
              </>
            ) : (
              <TouchableOpacity style={styles.durView} activeOpacity={0.7}
                onPress={() => setDurEdit({
                  water: plan?.durationSetBy === 'manual' ? String(plan.durationSec) : '',
                  tray:  tray?.manualSeconds != null ? String(tray.manualSeconds) : '',
                })}
                accessibilityRole="button"
                accessibilityLabel="Change how long watering and tray filling run">
                <Ionicons name="timer-outline" size={22} color={COLORS.primary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.durValue}>
                    Watering {plan?.durationSetBy === 'manual'
                      ? `${plan.durationSec}s (yours)` : `${plan?.durationSec ?? '--'}s (auto)`}
                    {'   ·   '}
                    Tray {tray?.manualSeconds != null
                      ? `${tray.manualSeconds}s (yours)` : 'auto'}
                  </Text>
                  <Text style={styles.durSub}>
                    {plan?.litres != null
                      ? `About ${plan.litres} L per watering. Tap to change.`
                      : 'Tap to set your own lengths.'}
                  </Text>
                </View>
                <Ionicons name="chevron-forward" size={18} color={COLORS.textTertiary} />
              </TouchableOpacity>
            )}
          </View>

          <Text style={styles.device}>Device ID: {meta.deviceId || `${houseId}-${sectionId}`}</Text>

          <TouchableOpacity style={styles.renameBtn} onPress={() => setRenaming(true)}
            activeOpacity={0.7} accessibilityRole="button"
            accessibilityLabel={`Rename this section. Currently called ${meta.name || sectionId}.`}>
            <Ionicons name="create-outline" size={18} color={COLORS.primary} />
            <Text style={styles.renameTxt}>Rename this section</Text>
          </TouchableOpacity>

          <TouchableOpacity style={styles.deleteBtn} onPress={() => setSheet('delete')} activeOpacity={0.7}
            accessibilityRole="button" accessibilityLabel="Delete this section">
            <Ionicons name="trash-outline" size={16} color={COLORS.danger} />
            <Text style={styles.deleteTxt}>Delete this section</Text>
          </TouchableOpacity>
        </>)}

        <View style={{ height: 100 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  // the heading's own marginTop lives here instead, otherwise its margin box
  // is what gets centred in this row and the text sits lower than the pill
  dropRow: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
             paddingVertical: SPACE.md, paddingHorizontal: SPACE.md,
             borderRadius: RADIUS.md, backgroundColor: COLORS.bgCardAlt,
             marginTop: SPACE.sm },
  dropLabel: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '600' },
  dropValue: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700' },
  hotPill: { flexDirection: 'row', alignItems: 'center', gap: 4,
             backgroundColor: COLORS.dangerDim, borderRadius: RADIUS.full,
             paddingHorizontal: 10, paddingVertical: 4 },
  hotPillTxt: { fontSize: 12, fontWeight: '800', color: COLORS.danger },
  fcLead:  { fontSize: 14, color: COLORS.text, lineHeight: 20, marginBottom: SPACE.md },
  fcNote:  { fontSize: 11, color: COLORS.textTertiary, lineHeight: 16, marginTop: SPACE.md },
  chartHead: { flexDirection: 'row', alignItems: 'center',
               justifyContent: 'space-between',
               marginTop: SPACE.lg, marginBottom: SPACE.md },
  container: { flex: 1, backgroundColor: COLORS.bg },
  center:    { alignItems: 'center', justifyContent: 'center' },
  scroll:    { padding: SPACE.xl },
  h:         { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', marginBottom: SPACE.md, marginTop: SPACE.lg },

  tileDead: { backgroundColor: COLORS.bgCardAlt },
  shead:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
             marginTop: SPACE.xl, marginBottom: SPACE.sm },
  sheadIcon: { width: 26, height: 26, borderRadius: 8,
               alignItems: 'center', justifyContent: 'center' },
  sheadTitle: { flex: 1, color: COLORS.text, fontSize: 15.5, fontWeight: '800',
                letterSpacing: -0.2 },
  sheadPill: { borderRadius: RADIUS.full, paddingHorizontal: 9, paddingVertical: 3 },
  sheadPillTxt: { fontSize: 11, fontWeight: '800', letterSpacing: 0.2,
                  textTransform: 'lowercase' },

  fertBarWrap: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
                 marginTop: SPACE.md },
  fertBarTrack: { flex: 1, height: 6, borderRadius: 3,
                  backgroundColor: COLORS.border, overflow: 'hidden' },
  fertBarFill: { height: '100%', borderRadius: 3 },
  fertBarTxt: { color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700',
                minWidth: 30, textAlign: 'right' },

  tabs:    { flexDirection: 'row', gap: 4, backgroundColor: COLORS.bgCardAlt,
             borderRadius: RADIUS.md, padding: 4, marginBottom: SPACE.lg },
  tab:     { flex: 1, flexDirection: 'row', alignItems: 'center',
             justifyContent: 'center', gap: 5, paddingVertical: SPACE.sm,
             borderRadius: RADIUS.sm },
  tabOn:   { backgroundColor: COLORS.bgCard, ...SHADOW.sm },
  tabTxt:  { color: COLORS.textTertiary, fontSize: FONT.sm, fontWeight: '700' },
  tabTxtOn:{ color: COLORS.primary },

  evSummary: { flexDirection: 'row', gap: SPACE.sm, marginBottom: SPACE.sm },
  evStat:  { flex: 1, backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm,
             paddingVertical: SPACE.md, paddingHorizontal: SPACE.md },
  evStatV: { color: COLORS.text, fontSize: FONT.lg, fontWeight: '800',
             fontVariant: ['tabular-nums'] },
  evStatK: { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 1 },
  evRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
             paddingVertical: SPACE.md },
  evRowDiv:{ borderTopWidth: 1, borderTopColor: COLORS.border },
  evWhen:  { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700',
             fontVariant: ['tabular-nums'] },
  evWhat:  { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 1 },
  evOk:    { fontSize: FONT.xs, fontWeight: '700' },
  evNote:  { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16,
             marginTop: SPACE.sm },

  fsBox:   { backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.md,
             padding: SPACE.md, marginTop: SPACE.md, gap: 6 },
  fsHead:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
             paddingBottom: SPACE.sm, borderBottomWidth: 1,
             borderBottomColor: COLORS.border, marginBottom: 2 },
  fsTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  fsSub:   { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 1 },
  fsRow:   { flexDirection: 'row', alignItems: 'baseline',
             justifyContent: 'space-between', gap: SPACE.md },
  fsKey:   { color: COLORS.textTertiary, fontSize: FONT.xs },
  fsVal:   { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '700' },
  fsWarn:  { color: COLORS.warning, fontSize: FONT.xs, lineHeight: 16,
             marginTop: SPACE.xs },
  fertRows: { borderTopWidth: 1, borderTopColor: COLORS.border,
              marginTop: SPACE.md, paddingTop: SPACE.md, gap: 6 },
  fertRow:  { flexDirection: 'row', alignItems: 'baseline',
              justifyContent: 'space-between', gap: SPACE.md },
  fertKey:  { color: COLORS.textTertiary, fontSize: FONT.sm },
  fertVal:  { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700' },
  fertHint: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16,
              marginTop: SPACE.sm },
  wLbl:   { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700',
            marginTop: SPACE.md, marginBottom: SPACE.xs },
  wHead:  { flexDirection: 'row', alignItems: 'center',
            justifyContent: 'space-between', marginTop: SPACE.md,
            marginBottom: SPACE.xs },
  wRescan:{ color: COLORS.primary, fontSize: FONT.sm, fontWeight: '800' },
  wScan:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
            backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm,
            padding: SPACE.md },
  wScanTxt: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17 },
  wNet:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
            paddingVertical: SPACE.md, paddingHorizontal: SPACE.md,
            borderRadius: RADIUS.sm, backgroundColor: COLORS.bgCardAlt,
            borderWidth: 1.5, borderColor: 'transparent', marginBottom: 6 },
  wNetOn: { borderColor: COLORS.primary, backgroundColor: `${COLORS.primary}12` },
  wNetName: { color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  wNetSub:  { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 1 },
  wManual:  { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700',
              marginTop: SPACE.sm },
  wInput: { backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm,
            paddingHorizontal: SPACE.md, paddingVertical: SPACE.md,
            color: COLORS.text, fontSize: FONT.md,
            borderWidth: 1, borderColor: COLORS.border },
  wNote:  { flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.sm,
            backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm,
            padding: SPACE.md, marginTop: SPACE.lg },
  wNoteTxt: { flex: 1, color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 17 },
  wSave:  { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
            gap: 6, backgroundColor: COLORS.primary, borderRadius: RADIUS.sm,
            paddingVertical: SPACE.md, marginTop: SPACE.lg },
  wSaveTxt: { color: '#FFF', fontSize: FONT.sm, fontWeight: '800' },
  runCard:  { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md,
              padding: SPACE.lg, marginTop: SPACE.lg, gap: SPACE.sm },
  runTop:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  runTitle: { flex: 1, color: COLORS.text, fontSize: FONT.md, fontWeight: '800' },
  runWait:  { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 19 },
  runCount: { color: COLORS.text, fontSize: 40, fontWeight: '800',
              fontVariant: ['tabular-nums'], marginTop: SPACE.xs },
  runCountUnit: { fontSize: FONT.sm, fontWeight: '700', color: COLORS.textTertiary },
  runTrack: { height: 6, borderRadius: 3, backgroundColor: COLORS.border,
              overflow: 'hidden' },
  runFill:  { height: '100%', borderRadius: 3 },
  runNote:  { color: COLORS.textTertiary, fontSize: FONT.xs },
  stopBtn:  { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
              gap: 6, borderRadius: RADIUS.sm, paddingVertical: SPACE.md,
              borderWidth: 1.5, borderColor: COLORS.danger,
              backgroundColor: COLORS.dangerDim, marginTop: SPACE.sm },
  stopTxt:  { color: COLORS.danger, fontSize: FONT.sm, fontWeight: '800' },
  blockNote: { flexDirection: 'row', alignItems: 'flex-start', gap: SPACE.sm,
               backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm,
               padding: SPACE.md, marginTop: SPACE.sm },
  blockTxt:  { flex: 1, color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17 },
  blockLink: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '800',
               marginTop: SPACE.sm },
  linkBtn:   { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
               gap: 6, backgroundColor: COLORS.primary, borderRadius: RADIUS.sm,
               paddingVertical: SPACE.md, marginTop: SPACE.md },
  linkBtnTxt:{ color: '#FFF', fontSize: FONT.sm, fontWeight: '700' },
  linkWait:  { marginTop: SPACE.md, color: COLORS.textSecondary, fontSize: FONT.sm },
  freshRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
              marginBottom: SPACE.sm },
  freshLbl: { color: COLORS.textTertiary, fontSize: FONT.xs, letterSpacing: 0.3 },

  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm },
  tile: { width: '47.5%', flexGrow: 1, alignItems: 'center', gap: 3, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, paddingVertical: SPACE.lg },
  tileVal: { fontSize: 22, fontWeight: '800', fontVariant: ['tabular-nums'] },
  tileUnit:{ fontSize: FONT.xs, fontWeight: '600' },
  tileLbl: { color: COLORS.textTertiary, fontSize: FONT.xs },

  card: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.lg,
          borderWidth: 1, borderColor: COLORS.borderLight },
  none: { color: COLORS.textTertiary, fontSize: FONT.sm },

  planTop:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  planTime: { color: COLORS.primary, fontSize: 30, fontWeight: '800', fontVariant: ['tabular-nums'] },
  planDur:  { color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },
  planDate: { color: COLORS.textTertiary, fontSize: FONT.xs },
  second:   { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: COLORS.dangerDim, borderRadius: RADIUS.sm, padding: SPACE.sm, marginTop: SPACE.md },
  secondTxt:{ color: COLORS.danger, fontSize: FONT.xs, fontWeight: '600', flex: 1 },
  reason:   { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17, marginTop: SPACE.md },

  trayTop: { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start', marginBottom: SPACE.md },
  trayTxt: { color: COLORS.textSecondary, fontSize: FONT.sm, flex: 1, lineHeight: 18 },
  barTrack:{ height: 12, backgroundColor: COLORS.bgInput, borderRadius: 6, position: 'relative', overflow: 'hidden' },
  barIdeal:{ position: 'absolute', top: 0, bottom: 0, backgroundColor: `${COLORS.success}44` },
  barMark: { position: 'absolute', top: -2, width: 4, height: 16, borderRadius: 2 },
  barLbl:  { color: COLORS.textTertiary, fontSize: 9, marginTop: 4, textAlign: 'center' },

  fertTop: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  fertNpk: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700' },
  fertMsg: { color: COLORS.textSecondary, fontSize: FONT.xs, marginTop: 4, lineHeight: 17 },

  tRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md, marginBottom: SPACE.md },
  tTitle: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '600' },
  tDesc:  { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 1 },

  btnGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm, marginTop: SPACE.lg },
  btn:     { width: '47.5%', flexGrow: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, borderRadius: RADIUS.sm, paddingVertical: SPACE.md },
  btnText: { color: '#FFF', fontSize: FONT.sm, fontWeight: '700' },

  device: { color: COLORS.textTertiary, fontSize: FONT.xs, textAlign: 'center', marginTop: SPACE.xl },

  nodeTop:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  nodeDot:   { width: 9, height: 9, borderRadius: 5 },
  nodeName:  { color: COLORS.text, fontSize: FONT.md, fontWeight: '700', flex: 1 },
  nodeState: { fontSize: FONT.sm, fontWeight: '700' },
  nodeMeta:  { color: COLORS.textSecondary, fontSize: FONT.sm, marginTop: 5 },
  nodeMac:   { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2,
               fontVariant: ['tabular-nums'], letterSpacing: 0.5 },
  nodeHint:  { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 18, marginTop: SPACE.sm },
  ivBlock:   { marginTop: SPACE.md, paddingTop: SPACE.md,
               borderTopWidth: 1, borderTopColor: COLORS.border },

  nodeBtns:  { flexDirection: 'row', gap: SPACE.sm, marginTop: SPACE.lg },
  nodeBtn:   { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
               gap: 6, paddingVertical: SPACE.md - 2, borderRadius: RADIUS.md,
               borderWidth: 1, borderColor: COLORS.primary },
  nodeBtnOn: { backgroundColor: COLORS.primary },
  tileEst:   { borderWidth: 1, borderColor: COLORS.estimated, backgroundColor: COLORS.estimatedDim },
  tileSd:    { color: COLORS.estimated, fontSize: FONT.xs, fontWeight: '700', marginTop: -2 },
  durView:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  durValue:  { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700' },
  durSub:    { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 2, lineHeight: 16 },
  durRow:    { flexDirection: 'row', gap: SPACE.md },
  durLabel:  { color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700', marginBottom: 4 },
  durInput:  { backgroundColor: COLORS.bgCardAlt, borderRadius: RADIUS.sm, borderWidth: 1,
               borderColor: COLORS.border, paddingHorizontal: SPACE.md,
               paddingVertical: SPACE.sm, color: COLORS.text, fontSize: FONT.md },
  durHint:   { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16, marginTop: SPACE.md },
  durBtns:   { flexDirection: 'row', gap: SPACE.sm, marginTop: SPACE.lg },
  durCancel: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: SPACE.md,
               borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  durCancelTxt: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700' },
  durSave:   { flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: SPACE.md,
               borderRadius: RADIUS.md, backgroundColor: COLORS.primary },
  durSaveTxt:{ color: '#FFF', fontSize: FONT.sm, fontWeight: '800' },
  nodeBtnOk: { backgroundColor: COLORS.success, borderColor: COLORS.success },
  nodeBtnBad:{ borderColor: COLORS.danger },
  nodeBtnTxt:{ color: COLORS.primary, fontSize: FONT.sm, fontWeight: '700' },
  unlinkBtn: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
               gap: 6, paddingVertical: SPACE.md - 2, borderRadius: RADIUS.md,
               borderWidth: 1, borderColor: COLORS.danger, backgroundColor: COLORS.dangerDim },
  unlinkTxt: { color: COLORS.danger, fontSize: FONT.sm, fontWeight: '700' },

  cooldown:   { backgroundColor: COLORS.infoDim, borderRadius: RADIUS.sm, padding: SPACE.md, marginBottom: SPACE.md },
  cdRow:      { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 4 },
  cdLabel:    { color: COLORS.textSecondary, fontSize: FONT.xs },
  cdVal:      { color: COLORS.text, fontSize: FONT.xs, fontWeight: '700', fontVariant: ['tabular-nums'] },
  cdBarTrack: { height: 6, backgroundColor: COLORS.bgInput, borderRadius: 3, overflow: 'hidden', marginTop: 4 },
  cdBarFill:  { height: '100%', backgroundColor: COLORS.info, borderRadius: 3 },
  cdNote:     { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 16, marginTop: SPACE.sm },

  renameBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 7,
               paddingVertical: SPACE.md, marginTop: SPACE.lg, borderRadius: RADIUS.md,
               borderWidth: 1, borderColor: COLORS.border, backgroundColor: COLORS.bgCard },
  renameTxt: { color: COLORS.primary, fontSize: FONT.md, fontWeight: '700' },
  deleteBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: SPACE.md, marginTop: SPACE.sm },
  deleteTxt: { color: COLORS.danger, fontSize: FONT.sm, fontWeight: '600' },

  // chart
  chart:   { flexDirection: 'row', alignItems: 'flex-end', position: 'relative', marginBottom: 4 },
  band:    { position: 'absolute', left: 0, right: 0, backgroundColor: `${COLORS.success}22`, borderRadius: 3 },
  col:     { flex: 1, height: '100%', position: 'relative' },
  tempDot: { position: 'absolute', left: '25%', width: 3, height: 3, borderRadius: 2, backgroundColor: COLORS.temperature },
  humDot:  { position: 'absolute', left: '25%', width: 3, height: 3, borderRadius: 2 },
  axis:    { flexDirection: 'row', justifyContent: 'space-between', marginTop: 2 },
  axisTxt: { color: COLORS.textTertiary, fontSize: 9 },
  legend:  { flexDirection: 'row', gap: SPACE.md, marginTop: SPACE.sm, flexWrap: 'wrap' },
  lg:      { flexDirection: 'row', alignItems: 'center', gap: 4 },
  lgDot:   { width: 8, height: 8, borderRadius: 4 },
  lgTxt:   { color: COLORS.textTertiary, fontSize: 9 },
});
