/**
 * Everything recorded for one section over the chosen range, in one timeline.
 *
 * The History tab used to show a 48-point chart and the latest 40 waterings,
 * and the server deleted events past the 60th, so last month's feeds were gone
 * for good. The farmer asked for all of it: every reading with its time, and
 * every watering, feed and tray fill with theirs (15 Oct 2026). Events are now
 * kept forever, and this reads them a page at a time with the readings between
 * them, newest first, grouped by farm day.
 *
 * Text widths. This phone family runs with the system's Bold text setting on,
 * and React Native measures a label at its regular weight while Android draws it
 * bold, so a label sized exactly to its own text is cut off ("06:..." on the
 * chart axis, seen 15 Oct). Every label here sits in a box sized by the layout
 * (a flex share, a full row, or a width with room to spare), never by itself.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Linking, PixelRatio,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { useCan } from '../config/auth';
import { getTimeline, exportTimeline, BASE_URL } from '../services/careV2';
import {
  HISTORY_TYPES, typesFor, groupByDay, clockOf, spanDays, localStamp, MAX_EXPORT_DAYS,
} from '../services/historyRange';

const PAGE = 100;

// Room for "06:42:10" drawn bold at the phone's text size, plus a little.
const FONT_SCALE = Math.min(PixelRatio.getFontScale() || 1, 1.3);
const TIME_W = Math.ceil(FONT.sm * FONT_SCALE * 5.6);

const fmtNum = (v, digits = 1) => (typeof v === 'number' ? v.toFixed(digits) : null);
const fmtLux = (v) => (typeof v === 'number'
  ? Math.round(v).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',') : null);

function ReadingRow({ it, divided }) {
  const t = fmtNum(it.temperature);
  const h = fmtNum(it.humidity, 0);
  const lx = fmtLux(it.light);
  const missing = t === null && h === null;
  return (
    <View style={[s.row, divided && s.rowDiv]}
      accessible
      accessibilityLabel={`${clockOf(it)} reading. ${missing ? 'Sensor not answering.' : ''}`
        + `${t !== null ? ` ${t} degrees,` : ''}${h !== null ? ` humidity ${h} percent,` : ''}`
        + `${lx !== null ? ` light ${lx} lux` : ''}`}>
      <Text style={s.time}>{clockOf(it)}</Text>
      <View style={s.readVals}>
        {missing ? (
          <Text style={[s.val, { color: COLORS.warning }]}>Sensor not answering</Text>
        ) : (
          <>
            <Text style={[s.val, { color: COLORS.temperature }]}>{t !== null ? `${t}°C` : '--'}</Text>
            <Text style={[s.val, { color: COLORS.humidity }]}>{h !== null ? `${h}%` : '--'}</Text>
          </>
        )}
        <Text style={[s.val, s.valWide, { color: COLORS.light }]}>
          {lx !== null ? `${lx} lx` : ''}
        </Text>
      </View>
    </View>
  );
}

function EventRow({ it, divided }) {
  const tray = it.kind === 'tray';
  const fed = !tray && it.withFertilizer;
  const tint = tray ? COLORS.info : fed ? COLORS.fertilizer : COLORS.primary;
  const tintDim = tray ? COLORS.infoDim : fed ? COLORS.fertilizerDim : COLORS.primaryDim;
  const what = tray ? 'Tray filled' : fed ? 'Watered with food' : 'Watered';
  const secs = it.stoppedEarly && typeof it.ranSec === 'number'
    ? `${it.ranSec} of ${it.durationSec} s` : `${it.durationSec ?? '?'} s`;
  const status = it.stoppedEarly ? 'stopped' : it.confirmed ? 'confirmed' : 'sent';
  const details = [
    fed && it.npkType && it.npkType !== 'None' ? `NPK ${it.npkType}` : null,
    it.by === 'auto' ? 'automatic' : 'by you',
  ].filter(Boolean).join('  ·  ');
  return (
    <View style={[s.row, s.evRow, divided && s.rowDiv]}
      accessible
      accessibilityLabel={`${clockOf(it)}. ${what} for ${secs}. ${details}. ${status}.`}>
      <Text style={s.time}>{clockOf(it)}</Text>
      <View style={[s.evIcon, { backgroundColor: tintDim }]}>
        <Ionicons name={tray ? 'add-circle-outline' : fed ? 'flask-outline' : 'rainy-outline'}
          size={15} color={tint} />
      </View>
      <View style={s.evBody}>
        <Text style={[s.evWhat, { color: tint }]}>{what}  {secs}</Text>
        <Text style={s.evDetail}>{details}</Text>
      </View>
      <Text style={[s.evStatus, { color: it.confirmed ? COLORS.success : COLORS.textTertiary }]}>
        {status}
      </Text>
    </View>
  );
}

export default function HistoryTimeline({ houseId, sectionId, win, onToast }) {
  const can = useCan();
  const [typeKey, setTypeKey] = useState('all');
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState(null);
  const [next, setNext] = useState(null);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState(null);
  const [exporting, setExporting] = useState(false);
  // A slow answer for a range the farmer has already left must not land.
  const ask = useRef(0);

  const start = win?.start;
  const end = win?.end;
  const types = typesFor(typeKey);

  const loadFirst = useCallback(async () => {
    if (!Number.isFinite(start) || !Number.isFinite(end)) return;
    const n = ++ask.current;
    setLoading(true);
    setError(null);
    try {
      const r = await getTimeline(houseId, sectionId, { start, end, limit: PAGE, types });
      if (n !== ask.current) return;
      setItems(r?.items || []);
      setNext(r?.nextBefore ?? null);
      if (r?.counts) setCounts(r.counts);
    } catch (e) {
      if (n === ask.current) { setError(e.message); setItems([]); setNext(null); }
    } finally {
      if (n === ask.current) setLoading(false);
    }
  }, [houseId, sectionId, start, end, types]);

  useEffect(() => { loadFirst(); }, [loadFirst]);

  const loadMore = async () => {
    if (!next || more) return;
    const n = ask.current;
    setMore(true);
    try {
      const r = await getTimeline(houseId, sectionId, { start, end, before: next, limit: PAGE, types });
      if (n !== ask.current) return;
      setItems((prev) => prev.concat(r?.items || []));
      setNext(r?.nextBefore ?? null);
    } catch (e) {
      onToast?.({ text: e.message, kind: 'error' });
    } finally {
      setMore(false);
    }
  };

  const days = spanDays(win || { start: 0, end: 0 });
  const canExport = can('exportTimeline') && days <= MAX_EXPORT_DAYS;
  const doExport = async () => {
    setExporting(true);
    try {
      const r = await exportTimeline(houseId, sectionId, { start, end, types });
      await Linking.openURL(`${BASE_URL}${r.path}`);
      onToast?.({ text: `Downloading ${r.filename}`, kind: 'success' });
    } catch (e) {
      onToast?.({ text: e.message, kind: 'error' });
    } finally {
      setExporting(false);
    }
  };

  const groups = groupByDay(items);

  return (
    <View>
      {/* What happened in the range, before the detail. */}
      <View style={s.tiles}>
        {[
          ['waterings', counts?.waterings, COLORS.primary],
          ['with food', counts?.feeds, COLORS.fertilizer],
          ['tray fills', counts?.trays, COLORS.info],
        ].map(([label, v, c]) => (
          <View key={label} style={s.tile}>
            <Text style={[s.tileV, { color: c }]}>{v ?? '-'}</Text>
            <Text style={s.tileK}>{label}</Text>
          </View>
        ))}
      </View>
      <View style={s.lastFed}>
        <Ionicons name="flask" size={14} color={COLORS.fertilizer} />
        <Text style={s.lastFedTxt}>
          Last fed: <Text style={s.lastFedV}>
            {counts?.lastFed ? localStamp(counts.lastFed) : 'not in this range'}
          </Text>
        </Text>
      </View>

      {/* Filter by type: one row of five equal parts, so no label sizes itself. */}
      <View style={s.chips} accessibilityRole="tablist">
        {HISTORY_TYPES.map((t) => {
          const on = t.key === typeKey;
          return (
            <TouchableOpacity key={t.key}
              style={[s.chip, on && s.chipOn]}
              onPress={() => setTypeKey(t.key)}
              activeOpacity={0.7}
              accessibilityRole="tab"
              accessibilityState={{ selected: on }}
              accessibilityLabel={`Show ${t.label.toLowerCase()}`}>
              <Text style={[s.chipTxt, on && s.chipTxtOn]} maxFontSizeMultiplier={1.15}>{t.label}</Text>
            </TouchableOpacity>
          );
        })}
      </View>

      {loading && !items.length ? (
        <View style={[s.card, SHADOW.sm, s.centerBox]}>
          <ActivityIndicator color={COLORS.primary} />
        </View>
      ) : error ? (
        <View style={[s.card, SHADOW.sm]}>
          <Text style={s.none}>Could not load the history: {error}</Text>
          <TouchableOpacity style={s.moreBtn} onPress={loadFirst} accessibilityRole="button">
            <Text style={s.moreTxt}>Try again</Text>
          </TouchableOpacity>
        </View>
      ) : !items.length ? (
        <View style={[s.card, SHADOW.sm]}>
          <Text style={s.none}>
            Nothing recorded in this range{typeKey !== 'all' ? ' of this type' : ''}.
          </Text>
        </View>
      ) : (
        <>
          {groups.map((g, gi) => (
            <View key={g.day} style={gi > 0 && s.dayGap}>
              <Text style={s.dayTitle} accessibilityRole="header">{g.title}</Text>
              <View style={[s.card, SHADOW.sm, s.listCard]}>
                {g.items.map((it, i) => (it.kind === 'reading'
                  ? <ReadingRow key={`r${it.t}-${i}`} it={it} divided={i > 0} />
                  : <EventRow key={`e${it.t}-${i}`} it={it} divided={i > 0} />))}
              </View>
            </View>
          ))}
          {next ? (
            <TouchableOpacity style={s.moreBtn} onPress={loadMore} disabled={more}
              accessibilityRole="button" accessibilityLabel="Load older records">
              {more
                ? <ActivityIndicator color={COLORS.primary} />
                : <Text style={s.moreTxt}>Load older ({items.length} shown)</Text>}
            </TouchableOpacity>
          ) : (
            <Text style={s.endNote}>
              That is everything from the start of the range ({items.length} records).
            </Text>
          )}
        </>
      )}

      {can('exportTimeline') && (
        <>
          <TouchableOpacity style={[s.exportBtn, !canExport && { opacity: 0.5 }]}
            onPress={doExport} disabled={!canExport || exporting}
            accessibilityRole="button" accessibilityLabel="Export this range as a CSV file">
            {exporting
              ? <ActivityIndicator color={COLORS.primary} />
              : (
                <>
                  <Ionicons name="download-outline" size={17} color={COLORS.primary} />
                  <Text style={s.exportTxt}>Export this range as CSV</Text>
                </>
              )}
          </TouchableOpacity>
          <Text style={s.endNote}>
            {canExport
              ? 'Opens a spreadsheet file in the browser, with every row above and the current type filter.'
              : `Export takes up to ${MAX_EXPORT_DAYS} days at a time. Pick a shorter range to export it.`}
          </Text>
        </>
      )}
      <Text style={s.endNote}>
        “Confirmed” means the node reported back that the relay ran. “Sent” means the
        command was written but no acknowledgement has arrived.
      </Text>
    </View>
  );
}

const s = StyleSheet.create({
  card:   { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, padding: SPACE.lg,
            borderWidth: 1, borderColor: COLORS.borderLight },
  centerBox: { alignItems: 'center', paddingVertical: SPACE.xl },
  listCard: { paddingVertical: SPACE.xs, paddingHorizontal: SPACE.md },
  none:   { color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 18 },

  tiles:  { flexDirection: 'row', gap: SPACE.sm },
  tile:   { flex: 1, backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm,
            borderWidth: 1, borderColor: COLORS.borderLight,
            paddingVertical: SPACE.md, paddingHorizontal: SPACE.md },
  tileV:  { fontSize: FONT.xl, fontWeight: '800', fontVariant: ['tabular-nums'] },
  tileK:  { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 2 },
  lastFed: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
             marginTop: SPACE.sm, paddingVertical: SPACE.sm, paddingHorizontal: SPACE.md,
             backgroundColor: COLORS.fertilizerDim, borderRadius: RADIUS.sm },
  lastFedTxt: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.sm },
  lastFedV: { color: COLORS.text, fontWeight: '700', fontVariant: ['tabular-nums'] },

  chips:  { flexDirection: 'row', padding: 3, borderRadius: RADIUS.full,
            backgroundColor: COLORS.bgCard, borderWidth: 1, borderColor: COLORS.border,
            marginTop: SPACE.lg, marginBottom: SPACE.md },
  chip:   { flex: 1, alignItems: 'center', justifyContent: 'center', minHeight: 36,
            paddingHorizontal: 2, borderRadius: RADIUS.full },
  chipOn: { backgroundColor: COLORS.primary },
  chipTxt: { alignSelf: 'stretch', textAlign: 'center',
             color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700' },
  chipTxtOn: { color: COLORS.textInverse },

  dayGap:  { marginTop: SPACE.lg },
  dayTitle: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '800',
              letterSpacing: 0.3, marginBottom: SPACE.sm, marginLeft: 2 },

  row:    { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, paddingVertical: 7 },
  rowDiv: { borderTopWidth: 1, borderTopColor: COLORS.borderLight },
  time:   { width: TIME_W, color: COLORS.textSecondary, fontSize: FONT.sm,
            fontVariant: ['tabular-nums'] },
  readVals: { flex: 1, flexDirection: 'row', alignItems: 'center' },
  val:    { flex: 1, fontSize: FONT.sm, fontWeight: '700', fontVariant: ['tabular-nums'] },
  valWide: { flex: 1.3, textAlign: 'right' },

  evRow:  { paddingVertical: SPACE.md },
  evIcon: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  evBody: { flex: 1 },
  evWhat: { fontSize: FONT.md, fontWeight: '800' },
  evDetail: { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 1 },
  evStatus: { width: Math.ceil(FONT.sm * FONT_SCALE * 6.2), textAlign: 'right',
              fontSize: FONT.sm, fontWeight: '700' },

  moreBtn: { marginTop: SPACE.md, alignItems: 'center', justifyContent: 'center',
             minHeight: 44, borderRadius: RADIUS.md, backgroundColor: COLORS.primaryDim },
  moreTxt: { alignSelf: 'stretch', textAlign: 'center',
             color: COLORS.primary, fontSize: FONT.md, fontWeight: '700' },
  exportBtn: { marginTop: SPACE.xl, flexDirection: 'row', alignItems: 'center',
               justifyContent: 'center', gap: SPACE.sm, minHeight: 46, paddingHorizontal: SPACE.lg,
               borderRadius: RADIUS.md, borderWidth: 1.5, borderColor: COLORS.primary,
               backgroundColor: COLORS.bgCard },
  exportTxt: { flexShrink: 1, color: COLORS.primary, fontSize: FONT.md, fontWeight: '800' },
  endNote: { color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16, marginTop: SPACE.sm },
});
