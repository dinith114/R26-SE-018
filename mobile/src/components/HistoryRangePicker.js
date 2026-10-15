/**
 * The History tab's range: a bar showing what is on screen, and a sheet to
 * change it - the presets, or any days picked on a calendar.
 *
 * One range drives the chart, the timeline and the export, so the three always
 * agree. The calendar is plain Views: the app has no native date picker
 * installed, and adding a native module means a new build of everything.
 * Dates are farm dates (services/historyRange.js).
 */
import React, { useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import Sheet from './Sheet';
import {
  HISTORY_PRESETS, MAX_RANGE_DAYS, farmDate, farmStamp, monthGrid, monthTitle,
  pickDay, customLabel,
} from '../services/historyRange';

const WEEK = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

function Calendar({ sel, onPick, today }) {
  const anchor = (sel?.to || today).split('-').map(Number);
  const [ym, setYm] = useState({ y: anchor[0], m: anchor[1] });
  const [ty, tm] = today.split('-').map(Number);
  const atLatest = ym.y > ty || (ym.y === ty && ym.m >= tm);
  const move = (d) => setYm(({ y, m }) => {
    const n = m + d;
    return n < 1 ? { y: y - 1, m: 12 } : n > 12 ? { y: y + 1, m: 1 } : { y, m: n };
  });

  return (
    <View>
      <View style={s.calHead}>
        <TouchableOpacity onPress={() => move(-1)} style={s.navBtn}
          accessibilityRole="button" accessibilityLabel="Previous month">
          <Ionicons name="chevron-back" size={20} color={COLORS.primary} />
        </TouchableOpacity>
        <Text style={s.calTitle} accessibilityRole="header">{monthTitle(ym.y, ym.m)}</Text>
        <TouchableOpacity onPress={() => move(1)} style={[s.navBtn, atLatest && { opacity: 0.3 }]}
          disabled={atLatest} accessibilityRole="button" accessibilityLabel="Next month">
          <Ionicons name="chevron-forward" size={20} color={COLORS.primary} />
        </TouchableOpacity>
      </View>
      <View style={s.week}>
        {WEEK.map((w, i) => <Text key={i} style={s.weekDay}>{w}</Text>)}
      </View>
      {monthGrid(ym.y, ym.m).map((week, wi) => (
        <View key={wi} style={s.week}>
          {week.map((d, di) => {
            if (!d) return <View key={di} style={s.cell} />;
            const future = d > today;
            const end = sel && (d === sel.from || d === sel.to);
            const inside = sel && d > sel.from && d < sel.to;
            return (
              <TouchableOpacity key={d} style={[s.cell, inside && s.cellIn]}
                disabled={future} onPress={() => onPick(d)}
                accessibilityRole="button"
                accessibilityState={{ selected: !!end, disabled: future }}
                accessibilityLabel={d}>
                <View style={[s.dayDot, end && s.dayDotOn]}>
                  <Text style={[s.dayTxt, future && s.dayFuture, end && s.dayTxtOn,
                                d === today && !end && s.dayToday]}
                    maxFontSizeMultiplier={1.2}>
                    {Number(d.slice(8))}
                  </Text>
                </View>
              </TouchableOpacity>
            );
          })}
        </View>
      ))}
    </View>
  );
}

export default function HistoryRangePicker({ choice, win, onChange, now }) {
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState(null);
  const today = farmDate(now || Date.now());

  const openSheet = () => {
    setSel(choice?.kind === 'custom' ? { from: choice.from, to: choice.to, done: true } : null);
    setOpen(true);
  };
  const choose = (c) => { setOpen(false); onChange(c); };

  return (
    <>
      <TouchableOpacity style={[s.bar, SHADOW.sm]} onPress={openSheet} activeOpacity={0.75}
        accessibilityRole="button"
        accessibilityLabel={`Showing ${win?.label}. Tap to change the dates.`}>
        <View style={s.barIcon}>
          <Ionicons name="calendar-outline" size={18} color={COLORS.primary} />
        </View>
        <View style={s.barBody}>
          <Text style={s.barLabel}>{win?.label}</Text>
          {win && (
            <Text style={s.barSpan}>{farmStamp(win.start)}  to  {farmStamp(win.end)}</Text>
          )}
        </View>
        <Text style={s.barChange}>Change</Text>
      </TouchableOpacity>

      <Sheet visible={open} onClose={() => setOpen(false)} title="Show history for"
        footer={(
          <>
            <TouchableOpacity style={[s.btn, s.btnGhost]} onPress={() => setOpen(false)}
              accessibilityRole="button">
              <Text style={[s.btnTxt, { color: COLORS.textSecondary }]}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[s.btn, s.btnMain, !sel && { opacity: 0.4 }]}
              disabled={!sel}
              onPress={() => choose({ key: 'custom', kind: 'custom', from: sel.from, to: sel.to })}
              accessibilityRole="button">
              <Text style={[s.btnTxt, { color: COLORS.textInverse }]}>
                {sel ? `Show ${customLabel(sel.from, sel.to)}` : 'Pick dates'}
              </Text>
            </TouchableOpacity>
          </>
        )}>
        <View style={s.presets}>
          {HISTORY_PRESETS.map((p) => {
            const on = choice?.key === p.key;
            return (
              <TouchableOpacity key={p.key} style={[s.preset, on && s.presetOn]}
                onPress={() => choose(p)} activeOpacity={0.7}
                accessibilityRole="button" accessibilityState={{ selected: on }}>
                <Text style={[s.presetTxt, on && s.presetTxtOn]}>{p.label}</Text>
              </TouchableOpacity>
            );
          })}
        </View>

        <Text style={s.or}>
          Or pick days on the calendar: tap the first day, then the last (up to {MAX_RANGE_DAYS} days).
        </Text>
        <Calendar sel={sel} today={today} onPick={(d) => setSel((cur) => pickDay(cur, d, today))} />
      </Sheet>
    </>
  );
}

const s = StyleSheet.create({
  bar:     { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
             backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md,
             borderWidth: 1, borderColor: COLORS.borderLight,
             paddingVertical: SPACE.md, paddingHorizontal: SPACE.md },
  barIcon: { width: 34, height: 34, borderRadius: 10, backgroundColor: COLORS.primaryDim,
             alignItems: 'center', justifyContent: 'center' },
  barBody: { flex: 1 },
  barLabel: { color: COLORS.text, fontSize: FONT.md + 1, fontWeight: '800' },
  barSpan: { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 2,
             fontVariant: ['tabular-nums'] },
  barChange: { width: 70, textAlign: 'right', color: COLORS.primary,
               fontSize: FONT.sm, fontWeight: '800' },

  presets: { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.sm },
  preset:  { width: '48%', flexGrow: 1, paddingVertical: SPACE.md, paddingHorizontal: SPACE.md,
             borderRadius: RADIUS.md, backgroundColor: COLORS.bgCardAlt },
  presetOn: { backgroundColor: COLORS.primaryDim },
  presetTxt: { color: COLORS.text, fontSize: FONT.md },
  presetTxtOn: { color: COLORS.primary, fontWeight: '800' },
  or:      { color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 18,
             marginTop: SPACE.lg, marginBottom: SPACE.sm },

  calHead: { flexDirection: 'row', alignItems: 'center', marginBottom: SPACE.xs },
  navBtn:  { width: 40, height: 40, alignItems: 'center', justifyContent: 'center' },
  calTitle: { flex: 1, textAlign: 'center', color: COLORS.text, fontSize: FONT.md, fontWeight: '800' },
  week:    { flexDirection: 'row' },
  weekDay: { flex: 1, textAlign: 'center', color: COLORS.textTertiary, fontSize: FONT.xs,
             fontWeight: '700', paddingVertical: SPACE.xs },
  cell:    { flex: 1, height: 42, alignItems: 'center', justifyContent: 'center' },
  cellIn:  { backgroundColor: COLORS.primaryDim },
  dayDot:  { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  dayDotOn: { backgroundColor: COLORS.primary },
  dayTxt:  { alignSelf: 'stretch', textAlign: 'center', color: COLORS.text, fontSize: FONT.md,
             fontVariant: ['tabular-nums'] },
  dayTxtOn: { color: COLORS.textInverse, fontWeight: '800' },
  dayToday: { color: COLORS.primary, fontWeight: '800' },
  dayFuture: { color: COLORS.textTertiary, opacity: 0.45 },

  btn:     { flex: 1, minHeight: 48, borderRadius: RADIUS.md, alignItems: 'center',
             justifyContent: 'center', paddingHorizontal: SPACE.sm },
  btnGhost: { backgroundColor: COLORS.bgCardAlt },
  btnMain: { backgroundColor: COLORS.primary },
  btnTxt:  { alignSelf: 'stretch', textAlign: 'center', fontSize: FONT.md, fontWeight: '800' },
});
