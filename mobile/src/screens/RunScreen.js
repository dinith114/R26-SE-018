/**
 * Watching a batch action actually happen.
 *
 * The farm-level Water Now and Fill Tray act on several sections at once, and
 * before this screen existed they fired everything off and showed a single
 * "command sent" box. That was the wrong claim twice over: the server accepting
 * a command says nothing about a pump, and a farmer watering four sections has
 * no way to know which of them worked.
 *
 * So each section is run ONE AT A TIME and shown moving through its real
 * states. "Confirmed" here means the node wrote an acknowledgement carrying the
 * same command id — the relay ran. Nothing on this screen claims success on the
 * strength of an HTTP 200.
 *
 * Sequential, not parallel, and deliberately: these are pumps sharing one
 * supply and one reservoir, and firing them together is a brownout and a
 * drained bucket.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { useCan } from '../config/auth';
import ScreenHeader from '../components/ScreenHeader';
import { waterSection, fillTray, getCommandStatus, stopSection } from '../services/careV2';
import ConfirmSheet from '../components/ConfirmSheet';

/** How long to wait for a node BEYOND the length of the pour itself.
 *
 *  This used to be a flat 75 s, which is shorter than a normal watering: a
 *  91-second dose could never confirm inside it, so a perfectly good run was
 *  reported as "sent, not confirmed" every time. The pour's own duration is now
 *  added on top. Commands reach the node in a couple of seconds since the
 *  firmware stopped polling on the sensor clock, so the margin is for the
 *  round trips, not for the water. */
const CONFIRM_GRACE_MS = 45000;
const POLL_MS = 3000;

const STATE = {
  queued:    { icon: 'ellipse-outline',      tint: COLORS.textTertiary, word: 'Waiting its turn' },
  sending:   { icon: 'arrow-up-circle',      tint: COLORS.info,         word: 'Sending…' },
  confirming:{ icon: 'time',                 tint: COLORS.info,         word: 'Waiting for the node…' },
  done:      { icon: 'checkmark-circle',     tint: COLORS.success,      word: 'Node confirmed' },
  unconfirmed:{ icon: 'help-circle',         tint: COLORS.warning,      word: 'Sent, not confirmed' },
  stopped:   { icon: 'stop-circle',          tint: COLORS.warning,      word: 'Stopped early' },
  failed:    { icon: 'close-circle',         tint: COLORS.danger,       word: 'Failed' },
};

export default function RunScreen({ route, navigation }) {
  /* What this account may do. The server refuses the rest whatever
     happens here; this only stops the screen offering a control that
     would come back 403. */
  const can = useCan();
  const { action = 'water', targets = [] } = route.params || {};
  const isWater = action === 'water';

  const [rows, setRows] = useState(
    targets.map((t) => ({ ...t, state: 'queued', note: null })),
  );
  const [running, setRunning] = useState(true);
  // The section pouring RIGHT NOW: { i, houseId, sectionId, id, secs, remaining }
  // Named `live` because each row already has its own local `active` flag.
  const [live,     setLive]     = useState(null);
  const [stopping, setStopping] = useState(false);
  const [askStop,  setAskStop]  = useState(false);
  const alive = useRef(true);

  const setRow = useCallback((i, patch) => {
    setRows((cur) => cur.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }, []);

  useEffect(() => {
    alive.current = true;

    /* Follow one pour to its end, by ACK id.
       Not by the command document: Stop replaces that, and keying off it means
       losing sight of the very run being stopped. */
    const watch = async (houseId, sectionId, cmdId, secs) => {
      const deadline = Date.now() + CONFIRM_GRACE_MS + secs * 1000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, POLL_MS));
        if (!alive.current) return { ok: false };
        try {
          const st = await getCommandStatus(houseId, sectionId, cmdId);
          if (st.ack?.id !== cmdId) continue;
          if (st.ack.done) return { ok: true, stopped: !!st.ack.stopped };
          if (st.ack.started) {
            setLive((a) => (a && a.id === cmdId
              ? { ...a, remaining: st.remainingSec != null ? st.remainingSec : a.remaining }
              : a));
          }
        } catch (_) {
          // A dropped poll is not a failure — the command is already sent.
        }
      }
      return { ok: false };
    };

    /* This screen ACTS on mount - it does not wait for a button. So the
       check has to be here and not only on the two doors that lead here: a
       screen that starts a pour the moment it renders must refuse to render
       for somebody who may not pour, however they arrived.

       The server would refuse it anyway. The point is not to send it. */
    /* Both action names written out rather than computed into one can() call.
       An audit that greps for can('waterSection') has to be able to see it
       here, and a check it cannot see is a check the next person removes. */
    const mayRun = isWater ? can('waterSection') : can('fillTray');
    if (!mayRun) {
      /* 'failed' rather than a new 'blocked' state: the screen already renders
         failed rows with their note, and inventing a state nothing draws would
         leave a blank list, which reads as the screen being broken. */
      setRows(targets.map(() => ({
        state: 'failed', note: 'Your account cannot start this.',
      })));
      return;
    }

    (async () => {
      for (let i = 0; i < targets.length; i++) {
        if (!alive.current) return;
        const t = targets[i];
        setRow(i, { state: 'sending' });
        try {
          const secs = isWater ? (t.durationSec || 45) : (t.fillSeconds || 15);
          const r = isWater
            ? await waterSection(t.houseId, t.sectionId, secs, !!t.withFertilizer)
            : await fillTray(t.houseId, t.sectionId, secs);
          const cmdId = r?.command?.id || r?.nodeCommand?.id || null;

          if (!alive.current) return;
          setRow(i, { state: 'confirming', note: `${secs}s` });
          setLive({ i, houseId: t.houseId, sectionId: t.sectionId,
                    id: cmdId, secs, remaining: secs });

          const res = await watch(t.houseId, t.sectionId, cmdId, secs);
          if (!alive.current) return;
          setLive(null);
          setStopping(false);
          setRow(i, {
            state: res.stopped ? 'stopped' : res.ok ? 'done' : 'unconfirmed',
            note: res.stopped ? 'stopped by you'
                : res.ok ? `${secs}s`
                : 'the node may be offline',
          });
        } catch (e) {
          if (!alive.current) return;
          setRow(i, { state: 'failed', note: e.message });
        }
      }
      if (alive.current) setRunning(false);
    })();

    return () => { alive.current = false; };
  }, []);

  // Ticks between server polls so the number moves smoothly.
  useEffect(() => {
    if (!live) return undefined;
    const id = setInterval(() => {
      setLive((a) => (a && a.remaining > 0 ? { ...a, remaining: a.remaining - 1 } : a));
    }, 1000);
    return () => clearInterval(id);
  }, [live?.id]);

  const stopLive = async () => {
    if (!live) return;
    setAskStop(false);
    setStopping(true);
    try {
      await stopSection(live.houseId, live.sectionId);
    } catch (_) {
      // The watcher decides the outcome either way; it reads the node's ack.
      setStopping(false);
    }
  };

  const done   = rows.filter((r) => r.state === 'done').length;
  const failed = rows.filter((r) => r.state === 'failed').length;
  const unconf = rows.filter((r) => r.state === 'unconfirmed').length;
  const settled = done + failed + unconf;
  const pct = rows.length ? Math.round((settled / rows.length) * 100) : 0;

  const verb = isWater ? 'Watering' : 'Filling trays in';
  const pastVerb = isWater ? 'watered' : 'filled';

  let summary = null;
  if (!running) {
    const bits = [];
    if (done)   bits.push(`${done} ${pastVerb}`);
    if (unconf) bits.push(`${unconf} unconfirmed`);
    if (failed) bits.push(`${failed} failed`);
    summary = bits.join(' · ');
  }

  return (
    <View style={s.screen}>
      <ScreenHeader
        title={running ? `${verb} ${rows.length}` : 'Finished'}
        subtitle={running ? 'One section at a time' : summary}
        navigation={navigation}
        showBack={!running}
      />

      <ConfirmSheet
        visible={askStop}
        icon="stop-circle-outline"
        title={isWater ? 'Stop watering this section?' : 'Stop filling this tray?'}
        body={`${rows[live?.i]?.name || 'This section'} has about `
            + `${Math.max(0, live?.remaining || 0)} seconds left. Stopping leaves it `
            + 'part-way through, and the node takes a few seconds to react. The '
            + 'remaining sections still run.'}
        confirmLabel="Stop now"
        cancelLabel="Keep going"
        destructive
        busy={stopping}
        onCancel={() => setAskStop(false)}
        onConfirm={stopLive}
      />

      <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false}>
        <View style={s.barWrap}>
          <View style={s.barTrack}>
            <View style={[s.barFill, { width: `${pct}%` }]} />
          </View>
          <Text style={s.barTxt}>{settled} of {rows.length}</Text>
        </View>

        {rows.map((r, i) => {
          const st = STATE[r.state] || STATE.queued;
          const active = r.state === 'sending' || r.state === 'confirming';
          return (
            <View key={`${r.houseId}-${r.sectionId}`}
              style={[s.row, SHADOW.sm, active && s.rowActive]}
              accessible
              accessibilityLabel={`${r.name}: ${st.word}`}>
              <View style={s.rowIcon}>
                {active
                  ? <ActivityIndicator size="small" color={st.tint} />
                  : <Ionicons name={st.icon} size={23} color={st.tint} />}
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.rowName}>{r.name}</Text>
                <Text style={[s.rowState, { color: st.tint }]}>
                  {st.word}{r.note ? ` · ${r.note}` : ''}
                </Text>

                {/* The pour actually happening, with a way out of it. Before
                    this the farm screen only ever said "waiting for the node"
                    and gave no way to stop water already moving. */}
                {live && live.i === i && (
                  <>
                    <View style={s.liveRow}>
                      <Text style={s.liveCount}>{Math.max(0, live.remaining)}s</Text>
                      <View style={s.liveTrack}>
                        <View style={[s.liveFill, {
                          width: `${Math.max(0, Math.min(100,
                            ((live.secs - Math.max(0, live.remaining)) / Math.max(1, live.secs)) * 100))}%`,
                        }]} />
                      </View>
                    </View>
                    <TouchableOpacity
                      style={[s.stopBtn, stopping && { opacity: 0.6 }]}
                      disabled={!can('stopSection')}
                      onPress={can('stopSection') ? () => setAskStop(true) : undefined}
                      disabled={stopping}
                      activeOpacity={0.85}
                      accessibilityRole="button"
                      accessibilityLabel={`Stop ${r.name}`}>
                      {stopping
                        ? <ActivityIndicator size="small" color={COLORS.danger} />
                        : <Ionicons name="stop-circle-outline" size={15} color={COLORS.danger} />}
                      <Text style={s.stopTxt}>{stopping ? 'Stopping…' : 'Stop now'}</Text>
                    </TouchableOpacity>
                  </>
                )}
              </View>
              <Text style={s.rowIndex}>{i + 1}</Text>
            </View>
          );
        })}

        {running ? (
          <Text style={s.note}>
            Each section is sent in turn, then we wait for its node to report
            back that the relay actually ran. That takes up to one reading cycle,
            so a short wait here is normal.
          </Text>
        ) : (
          <View style={s.doneCard}>
            <Ionicons
              name={failed || unconf ? 'alert-circle' : 'checkmark-circle'}
              size={30}
              color={failed || unconf ? COLORS.warning : COLORS.success} />
            <Text style={s.doneTitle}>
              {failed || unconf
                ? 'Finished, with something to check'
                : `${done} section${done === 1 ? '' : 's'} ${pastVerb}`}
            </Text>
            {(failed || unconf) > 0 && (
              <Text style={s.doneBody}>
                {unconf ? `${unconf} section${unconf === 1 ? ' was' : 's were'} sent but never confirmed — `
                        + 'check the node is powered and on Wi-Fi. ' : ''}
                {failed ? `${failed} could not be sent at all.` : ''}
              </Text>
            )}
          </View>
        )}
      </ScrollView>

      <View style={s.footer}>
        <TouchableOpacity
          style={[s.btn, running && { backgroundColor: COLORS.bgCardAlt }]}
          onPress={() => navigation.goBack()}
          activeOpacity={0.85}
          accessibilityRole="button"
          accessibilityLabel={running ? 'Run in the background' : 'Done'}>
          <Text style={[s.btnTxt, running && { color: COLORS.textSecondary }]}>
            {running ? 'Leave it running' : 'Done'}
          </Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: COLORS.bg },
  liveRow:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
               marginTop: SPACE.sm },
  liveCount: { color: COLORS.text, fontSize: FONT.md, fontWeight: '800',
               fontVariant: ['tabular-nums'], minWidth: 38 },
  liveTrack: { flex: 1, height: 5, borderRadius: 3,
               backgroundColor: COLORS.border, overflow: 'hidden' },
  liveFill:  { height: '100%', borderRadius: 3, backgroundColor: COLORS.info },
  stopBtn:   { flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
               gap: 5, borderRadius: RADIUS.sm, paddingVertical: SPACE.sm,
               borderWidth: 1.5, borderColor: COLORS.danger,
               backgroundColor: COLORS.dangerDim, marginTop: SPACE.sm },
  stopTxt:   { color: COLORS.danger, fontSize: FONT.sm, fontWeight: '800' },
  scroll: { padding: SPACE.xl, paddingBottom: SPACE.xxl },

  barWrap: { marginBottom: SPACE.xl },
  barTrack: {
    height: 8, borderRadius: 4, overflow: 'hidden',
    backgroundColor: COLORS.bgInput,
  },
  barFill: { height: '100%', borderRadius: 4, backgroundColor: COLORS.primary },
  barTxt: {
    color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: SPACE.sm,
    fontVariant: ['tabular-nums'],
  },

  row: {
    flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md,
    padding: SPACE.lg, marginBottom: SPACE.sm,
    borderWidth: 1, borderColor: 'transparent',
  },
  rowActive: { borderColor: COLORS.info },
  rowIcon: { width: 26, alignItems: 'center' },
  rowName: { color: COLORS.text, fontSize: FONT.lg - 1, fontWeight: '700' },
  rowState: { fontSize: FONT.md, fontWeight: '600', marginTop: 2 },
  rowIndex: {
    color: COLORS.textTertiary, fontSize: FONT.sm,
    fontVariant: ['tabular-nums'],
  },

  note: {
    color: COLORS.textTertiary, fontSize: FONT.md, lineHeight: 19,
    marginTop: SPACE.lg,
  },

  doneCard: {
    alignItems: 'center', gap: SPACE.sm,
    backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md,
    padding: SPACE.xl, marginTop: SPACE.lg,
  },
  doneTitle: {
    color: COLORS.text, fontSize: FONT.lg, fontWeight: '700',
    textAlign: 'center',
  },
  doneBody: {
    color: COLORS.textSecondary, fontSize: FONT.md, lineHeight: 19,
    textAlign: 'center',
  },

  footer: {
    padding: SPACE.xl, paddingTop: SPACE.md,
    borderTopWidth: 1, borderTopColor: COLORS.border,
    backgroundColor: COLORS.bgCard,
  },
  btn: {
    alignItems: 'center', justifyContent: 'center',
    paddingVertical: SPACE.md + 3, borderRadius: RADIUS.md,
    backgroundColor: COLORS.primary, minHeight: 52,
  },
  btnTxt: { color: '#FFF', fontSize: FONT.lg, fontWeight: '700' },
});
