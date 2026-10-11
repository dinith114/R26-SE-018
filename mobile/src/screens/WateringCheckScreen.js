/**
 * How the watering times were checked - the answer to the PP2 question "how did
 * you verify the watering times are correct?".
 *
 * The honest answer has three parts and one limit, so the steps are numbered:
 * where the labels came from, how the model was tested against them, the one
 * assumption the labels rest on that had never been measured (checked here
 * against a sensor inside the house), and what none of it proves.
 *
 * Every number on this screen is read from two endpoints:
 *   /watering-validation          validate_out_of_time.py's table, as shipped
 *   /houses/{h}/shadehouse-check  this house's sensors against the outdoor
 *                                 weather and the assumed indoor conversion
 * Nothing is kept in code to fall back on. Where a check cannot be made - no
 * house, too few hours, a simulated house, the weather service unreachable -
 * the screen says so in the server's words and says what would fix it.
 *
 * Release builds close the app on an unhandled TypeError, so every field is
 * read through the guarded helpers in services/wateringCheck.js.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  useWindowDimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import ScreenHeader from '../components/ScreenHeader';
import FlowChart from '../components/FlowChart';
import { getShadehouseCheck, getWateringValidation } from '../services/careV2';
import { farmTime } from '../services/placementFlow';
import {
  int, num, str, siteName, sentence, dayText, splitRows, headlineSplit, quantityRows,
  verdictGroups, sectionRows, excludedTotals, sourceParts, isoHourMs, isoMs, hourlyChart,
  clockTick, sinceMsFor, checkFailure, SOURCE_LABEL, VERDICT_TEXT, SINCE_CHOICES,
} from '../services/wateringCheck';

const FIELD = {
  temperature: { label: 'Temperature', unit: '°C', color: COLORS.temperature, digits: 0 },
  humidity:    { label: 'Humidity',    unit: '%',  color: COLORS.humidity,    digits: 0 },
};
const FIELDS = ['temperature', 'humidity'];

const PILL = {
  ok:         { fg: COLORS.primary,       bg: COLORS.primaryDim, icon: 'checkmark-circle' },
  bad:        { fg: COLORS.danger,        bg: COLORS.dangerDim,  icon: 'close-circle' },
  unmeasured: { fg: COLORS.textSecondary, bg: COLORS.bgCardAlt,  icon: 'remove-circle-outline' },
  unknown:    { fg: COLORS.textSecondary, bg: COLORS.bgCardAlt,  icon: 'help-circle-outline' },
};

// Where the training data came from, as a chain. Words only: the numbers that
// belong to each link are on the steps below, read from the server.
const CHAIN = [
  { icon: 'cloud-outline', tag: 'measured', color: COLORS.info,
    text: 'Real hourly outdoor weather at each site: ERA5 reanalysis.' },
  { icon: 'home-outline', tag: 'assumed', color: COLORS.warning,
    text: 'Moved indoors with a shade-house conversion nobody had measured. Step 3 checks it.' },
  { icon: 'book-outline', tag: 'rule', color: COLORS.estimated,
    text: 'An expert watering rule turns each day\'s indoor weather into a time and a duration. That is the label.' },
  { icon: 'git-network-outline', tag: 'learned', color: COLORS.primary,
    text: 'The model learns to give the label from the morning\'s conditions. Step 2 tests it.' },
];

function Step({ n, title, what, children }) {
  return (
    <View style={[styles.card, SHADOW.sm]}>
      <View style={styles.stepHead}>
        <View style={styles.stepNum}><Text style={styles.stepNumTxt}>{n}</Text></View>
        <Text style={styles.stepTitle}>{title}</Text>
      </View>
      {!!what && <Text style={styles.what}>{what}</Text>}
      {children}
    </View>
  );
}

function Table({ head, rows, flex }) {
  return (
    <View style={styles.table}>
      <View style={styles.thead}>
        {head.map((h, i) => (
          <Text key={i} style={[styles.th, { flex: flex[i] }, i > 0 && styles.num]}>{h}</Text>
        ))}
      </View>
      {rows.map((r, ri) => (
        <View key={ri} style={styles.tr}>
          {r.map((c, i) => (
            <Text key={i} style={[styles.td, { flex: flex[i] }, i > 0 && styles.num,
                                  i === 0 && styles.tdFirst,
                                  c && c.color ? { color: c.color, fontWeight: '800' } : null]}>
              {c && c.text !== undefined ? c.text : c}
            </Text>
          ))}
        </View>
      ))}
    </View>
  );
}

function Legend({ items }) {
  return (
    <View style={styles.legend}>
      {items.map((it) => (
        <View key={it.label} style={styles.legendItem}>
          <View style={[styles.legendSw, { backgroundColor: it.color }, it.style]} />
          <Text style={styles.legendTxt}>{it.label}</Text>
        </View>
      ))}
    </View>
  );
}

function Tabs({ value, onChange }) {
  return (
    <View style={styles.tabs}>
      {FIELDS.map((f) => (
        <TouchableOpacity key={f} onPress={() => onChange(f)} activeOpacity={0.75}
          style={[styles.tab, value === f && { backgroundColor: FIELD[f].color }]}
          accessibilityRole="button" accessibilityState={{ selected: value === f }}>
          <Text style={[styles.tabTxt, value === f && { color: '#FFF' }]}>{FIELD[f].label}</Text>
        </TouchableOpacity>
      ))}
    </View>
  );
}

function Pill({ kind }) {
  const p = PILL[kind] || PILL.unknown;
  return (
    <View style={[styles.pill, { backgroundColor: p.bg }]}>
      <Ionicons name={p.icon} size={12} color={p.fg} />
      <Text style={[styles.pillTxt, { color: p.fg }]}>{VERDICT_TEXT[kind] || VERDICT_TEXT.unknown}</Text>
    </View>
  );
}

function Stat({ cap, value, strong }) {
  return (
    <View style={styles.stat}>
      <Text style={styles.statCap}>{cap}</Text>
      <Text style={[styles.statVal, strong && styles.statStrong]}>{value}</Text>
    </View>
  );
}

function Notice({ tone = 'warn', icon = 'alert-circle-outline', children }) {
  const bg = tone === 'ok' ? COLORS.primaryDim : tone === 'bad' ? COLORS.dangerDim
    : tone === 'plain' ? COLORS.bgCardAlt : COLORS.warningDim;
  const fg = tone === 'ok' ? COLORS.primary : tone === 'bad' ? COLORS.danger
    : tone === 'plain' ? COLORS.textSecondary : COLORS.warning;
  return (
    <View style={[styles.notice, { backgroundColor: bg }]}>
      <Ionicons name={icon} size={15} color={fg} />
      <View style={{ flex: 1, gap: 4 }}>{children}</View>
    </View>
  );
}

const list = (xs) => xs.map((x) => String(x).toLowerCase()).join(', ');

export default function WateringCheckScreen({ route, navigation }) {
  const params = (route && route.params) || {};
  const houseId = typeof params.houseId === 'string' && params.houseId ? params.houseId : null;
  const houseName = typeof params.houseName === 'string' && params.houseName ? params.houseName : null;
  const houseLabel = houseName || houseId;
  const { width: screenW } = useWindowDimensions();
  const chartW = screenW - SPACE.lg * 4;

  const [validation, setValidation] = useState(null);
  const [valError, setValError] = useState(null);
  const [valLoading, setValLoading] = useState(true);

  const [check, setCheck] = useState(null);
  const [checkError, setCheckError] = useState(null);
  const [checkLoading, setCheckLoading] = useState(!!houseId);
  /* Recent readings by default, not all of them. H1's Aug-Sep history was
     recorded somewhere nobody wrote down, and pooled in it shows a confident
     "out of tolerance" that says nothing about the shade house. Three days
     covers a node placed in the house for the last day or two; older history
     has to be asked for on purpose. */
  const [since, setSince] = useState('3d');
  const [field, setField] = useState('temperature');

  // A newer request wins: changing the read window while a slow check is still
  // running must not let the older answer land on top of the newer one.
  const seq = useRef(0);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const loadValidation = useCallback(async () => {
    setValLoading(true);
    try {
      const v = await getWateringValidation();
      if (!alive.current) return;
      setValidation(v && typeof v === 'object' ? v : null);
      setValError(null);
    } catch (e) {
      if (!alive.current) return;
      setValidation(null);
      setValError(e || new Error('Could not load the validation.'));
    } finally {
      if (alive.current) setValLoading(false);
    }
  }, []);

  const loadCheck = useCallback(async (windowKey) => {
    if (!houseId) return;
    const my = ++seq.current;
    setCheckLoading(true);
    try {
      const c = await getShadehouseCheck(houseId, undefined,
                                         sinceMsFor(windowKey, Date.now()) ?? undefined);
      if (!alive.current || my !== seq.current) return;
      setCheck(c && typeof c === 'object' ? c : null);
      setCheckError(null);
    } catch (e) {
      if (!alive.current || my !== seq.current) return;
      setCheck(null);
      setCheckError(e || new Error('The check could not be loaded.'));
    } finally {
      if (alive.current && my === seq.current) setCheckLoading(false);
    }
  }, [houseId]);

  useEffect(() => { loadValidation(); }, [loadValidation]);
  useEffect(() => { loadCheck(since); }, [loadCheck, since]);

  const splits = useMemo(() => splitRows(validation), [validation]);
  const oot = useMemo(() => headlineSplit(validation), [validation]);
  const qRows = useMemo(() => quantityRows(check), [check]);
  const groups = useMemo(() => verdictGroups(check), [check]);
  const secRows = useMemo(() => sectionRows(check), [check]);
  const excl = useMemo(() => excludedTotals(check), [check]);
  const parts = useMemo(() => sourceParts(check), [check]);
  const chart = useMemo(() => hourlyChart(check, field), [check, field]);
  const failure = !houseId ? checkFailure(null, null)
    : checkError ? checkFailure(checkError, houseId) : null;

  const v = validation || {};
  const ds = (v.dataset && typeof v.dataset === 'object') ? v.dataset : {};
  const sites = Array.isArray(ds.sites) ? ds.sites : [];
  const leftOut = Array.isArray(ds.excluded) ? ds.excluded : [];
  const unseen = (v.unseenWeather && typeof v.unseenWeather === 'object') ? v.unseenWeather : {};
  const unseenSites = Array.isArray(unseen.sites) ? unseen.sites : [];
  const floor = (v.labelNoiseFloor && typeof v.labelNoiseFloor === 'object') ? v.labelNoiseFloor : {};

  const c = check || {};
  const sections = Array.isArray(c.sections) ? c.sections : [];
  const overall = (c.overall && typeof c.overall === 'object') ? c.overall : {};
  const src = (c.outdoorSource && typeof c.outdoorSource === 'object') ? c.outdoorSource : {};
  const loc = (c.location && typeof c.location === 'object') ? c.location : {};
  const ee = (c.estimateError && typeof c.estimateError === 'object') ? c.estimateError : {};
  const fromMs = isoHourMs(c.from);
  const toMs = isoHourMs(c.to);
  const F = FIELD[field];

  const excludedBits = [
    excl.seeded ? `${int(excl.seeded)} seeded test records` : null,
    excl.badClock ? `${int(excl.badClock)} with an unsynced clock` : null,
    excl.beforeSince ? `${int(excl.beforeSince)} from before the chosen window` : null,
    excl.temperature ? `${int(excl.temperature)} temperature readings missing, failed or impossible` : null,
    excl.humidity ? `${int(excl.humidity)} humidity readings missing, failed or impossible` : null,
    excl.light ? `${int(excl.light)} light readings missing, failed (-999) or impossible` : null,
    excl.lightAtCeiling ? `${int(excl.lightAtCeiling)} light readings pinned at the sensor's ceiling` : null,
  ].filter(Boolean);

  const tempErr = (ee.temperature && typeof ee.temperature === 'object') ? ee.temperature : {};
  const rhErr = (ee.humidity && typeof ee.humidity === 'object') ? ee.humidity : {};
  const better = (e) => (Number.isFinite(e.outdoorPlusAssumed) && Number.isFinite(e.outdoorAsIs)
    ? (e.outdoorPlusAssumed < e.outdoorAsIs ? COLORS.primary : COLORS.danger) : undefined);

  const generatedMs = isoMs(v.generatedAt);

  return (
    <View style={styles.container}>
      {/* The header title is one line at 20 px. "How watering times were
          checked" measures ~325 px there (Arial Bold metrics) against 280 px of
          room on a 400 px phone, so it would be cut off mid-word; the full
          title heads the answer card instead, where it can wrap. */}
      <ScreenHeader title="How it was checked"
        subtitle={houseLabel ? `Watering times · ${houseLabel}` : 'Watering times'}
        navigation={navigation} showBack />
      <ScrollView contentContainerStyle={styles.scroll}>

        {/* ── the answer first, then how it was reached ── */}
        <View style={[styles.card, styles.answer, SHADOW.sm]}>
          <Text style={styles.answerHead} accessibilityRole="header">
            How watering times were checked
          </Text>
          {oot ? (
            <Text style={styles.answerTxt}>
              On whole years it never saw ({str(oot.testYears)}), the model's watering time is
              {' '}{num(oot.hourMaeMin, 1)} min from the time its rule gives, on average
              {' '}(R² {num(oot.hourR2, 3)}).
            </Text>
          ) : (
            <Text style={styles.answerTxt}>
              {valLoading ? 'Loading the model test…' : 'The model test could not be loaded - see step 2.'}
            </Text>
          )}
          <Text style={styles.answerTxt}>
            {!houseId
              ? 'The indoor conversion needs a house to be checked in - see step 3.'
              : checkLoading
                ? `Checking the indoor conversion in ${houseLabel}…`
                : check
                  ? [
                      groups.ok.length ? `Inside ${houseLabel}, within tolerance: ${list(groups.ok)}.` : null,
                      groups.bad.length ? `Out of tolerance: ${list(groups.bad)}.` : null,
                      groups.unmeasured.length ? `Not measured: ${list(groups.unmeasured)}.` : null,
                    ].filter(Boolean).join(' ')
                  : `The indoor conversion has not been checked in ${houseLabel} yet - step 3 says why.`}
          </Text>
          <Text style={styles.answerTxt}>
            Neither shows that the rule is the best watering for the plants (step 4).
          </Text>
        </View>

        {/* ── 1 ── */}
        <Step n={1} title="Where the training labels come from"
          what="The model did not learn from growers. Each label was made by applying an expert watering rule to real weather.">
          <View style={styles.chain}>
            {CHAIN.map((k, i) => (
              <View key={k.tag} style={styles.chainRow}>
                <View style={styles.chainRail}>
                  <View style={[styles.chainDot, { backgroundColor: k.color }]}>
                    <Ionicons name={k.icon} size={13} color="#FFF" />
                  </View>
                  {i < CHAIN.length - 1 && <View style={styles.chainLine} />}
                </View>
                <View style={styles.chainBody}>
                  <Text style={[styles.chainTag, { color: k.color }]}>{k.tag}</Text>
                  <Text style={styles.chainTxt}>{k.text}</Text>
                </View>
              </View>
            ))}
          </View>

          {validation ? (
            <>
              <Text style={styles.big}>
                {int(ds.rows)} rows · {sites.length} sites · {str(ds.years)}
              </Text>
              {!!sentence(ds.unit) && <Text style={styles.sub}>{sentence(ds.unit)}</Text>}
              <View style={styles.chips}>
                {sites.map((s) => (
                  <View key={String(s)} style={[styles.chip, { backgroundColor: COLORS.infoDim }]}>
                    <Text style={[styles.chipTxt, { color: COLORS.info }]}>{siteName(s)}</Text>
                  </View>
                ))}
              </View>
              {!!leftOut.length && (
                <Text style={styles.note}>Left out of training: {leftOut.map(siteName).join(', ')}.</Text>
              )}
            </>
          ) : null}

          <Notice tone="warn">
            <Text style={styles.noticeHead}>These are not grower logs</Text>
            <Text style={styles.noticeTxt}>
              No farm's real watering decisions, and no plant's response to them, are in the
              training data. The labels say what the rule would do, not what a grower did.
            </Text>
            {!!str(v.labelSource, '') && <Text style={styles.noticeSrc}>{str(v.labelSource)}</Text>}
          </Notice>
        </Step>

        {/* ── 2 ── */}
        <Step n={2} title="The test"
          what={`The model is scored on rows it was never trained on${splits.length > 1 ? `, split ${splits.length} different ways` : ''}. The error is how far its answer is from the rule's.`}>
          {valLoading && !validation ? (
            <View style={styles.inline}><ActivityIndicator color={COLORS.primary} /></View>
          ) : !validation ? (
            <>
              <Notice tone="warn">
                <Text style={styles.noticeTxt}>{str(valError && valError.message,
                  'The validation could not be loaded.')}</Text>
              </Notice>
              <TouchableOpacity style={[styles.secondary, { marginTop: SPACE.md }]}
                onPress={loadValidation} activeOpacity={0.85}>
                <Text style={styles.secondaryTxt}>Try again</Text>
              </TouchableOpacity>
            </>
          ) : (
            <>
              <Table
                head={['Split', 'Tested on', 'Hour MAE', 'R²', 'Duration MAE']}
                flex={[1.1, 1.25, 0.95, 0.7, 1.05]}
                rows={splits.map((r) => [
                  r.outOfTime ? { text: `${r.name} ★`, color: COLORS.primary } : r.name,
                  str(r.testYears),
                  r.hourMaeMin == null ? '—' : `${num(r.hourMaeMin, 2)} min`,
                  num(r.hourR2, 3),
                  r.durMaeSec == null ? '—' : `${num(r.durMaeSec, 2)} s`,
                ])} />
              <Text style={styles.note}>
                Rows trained / tested:{' '}
                {splits.map((r) => `${r.name} ${int(r.trainRows)} / ${int(r.testRows)}`).join(' · ')}.
                {unseenSites.length
                  ? ` The unseen split is weather downloaded after training: ${unseenSites.map(siteName).join(', ')} only, ${dayText(unseen.from, true)} to ${dayText(unseen.to, true)}.`
                  : ''}
              </Text>

              {oot && (
                <View style={styles.rec}>
                  <Ionicons name="time-outline" size={16} color={COLORS.primary} />
                  <View style={{ flex: 1, gap: 6 }}>
                    <Text style={styles.recTxt}>
                      Why out-of-time matters: a random split mixes days from the same years into
                      training and test, so the model can lean on weather it has half seen.
                      Holding out whole years ({str(oot.testYears)}) tests it the way it is used -
                      on seasons it never saw.
                    </Text>
                    <Text style={styles.recTxt}>
                      An hour MAE of {num(oot.hourMaeMin, 1)} min means that on a held-out day the
                      predicted watering time is, on average, {num(oot.hourMaeMin, 1)} minutes from the
                      time the rule picks for that day
                      {oot.durMaeSec != null ? `, and the duration ${num(oot.durMaeSec, 1)} s from the rule's` : ''}.
                    </Text>
                  </View>
                </View>
              )}

              {Number.isFinite(floor.hourMaeMin) && (
                <Text style={styles.note}>
                  The labels carry deliberate noise. A predictor that knew the rule exactly would
                  still score about {num(floor.hourMaeMin, 1)} min
                  {Number.isFinite(floor.durMaeSec) ? ` and ${num(floor.durMaeSec, 1)} s` : ''} - an
                  expected figure from the code, not a measurement. So the model is as close to
                  the rule as its labels allow: it reproduces the rule. Whether the rule's times
                  suit the plants is a separate question (step 4).
                </Text>
              )}
            </>
          )}
        </Step>

        {/* ── 3 ── */}
        <Step n={3} title="The one assumption never measured"
          what="ERA5 is the open air; the orchids are under shade cloth. Before the rule was applied, the weather was moved indoors with three constants nobody had measured. Only a sensor inside the house can check them, so its readings are put beside the real outdoor weather for the same hours.">
          {!!houseId && (
            <View style={styles.sinceRow}>
              {SINCE_CHOICES.map((ch) => (
                <TouchableOpacity key={ch.key} onPress={() => setSince(ch.key)}
                  disabled={checkLoading && since === ch.key} activeOpacity={0.75}
                  style={[styles.tab, since === ch.key && { backgroundColor: COLORS.primary }]}
                  accessibilityRole="button" accessibilityState={{ selected: since === ch.key }}>
                  <Text style={[styles.tabTxt, since === ch.key && { color: '#FFF' }]}>{ch.label}</Text>
                </TouchableOpacity>
              ))}
              <Text style={styles.sinceNote}>
                Readings from before the node went into the house describe wherever it was then.
                Choose a window that starts after it went in.
              </Text>
            </View>
          )}

          {failure ? (
            <>
              <Notice tone="plain" icon="information-circle-outline">
                <Text style={styles.noticeHead}>Not checked</Text>
                <Text style={styles.noticeTxt}>{failure.reason}</Text>
                {!!failure.needed && (
                  <Text style={styles.noticeTxt}>
                    <Text style={{ fontWeight: '800' }}>What is needed: </Text>{failure.needed}
                  </Text>
                )}
              </Notice>
              {!!houseId && (
                <TouchableOpacity style={[styles.secondary, { marginTop: SPACE.md },
                                          checkLoading && { opacity: 0.6 }]}
                  onPress={() => loadCheck(since)} disabled={checkLoading} activeOpacity={0.85}>
                  {checkLoading ? <ActivityIndicator color={COLORS.primary} />
                                : <Text style={styles.secondaryTxt}>Check again</Text>}
                </TouchableOpacity>
              )}
            </>
          ) : checkLoading && !check ? (
            <View style={styles.inline}>
              <ActivityIndicator color={COLORS.primary} />
              <Text style={styles.sub}>Reading the sensors and fetching the outdoor weather…</Text>
            </View>
          ) : check ? (
            <View style={checkLoading ? { opacity: 0.5 } : null}>
              <Text style={styles.big}>
                {int(c.hours)} hours · {sections.length} section{sections.length === 1 ? '' : 's'}
              </Text>
              <Text style={styles.sub}>
                {farmTime(fromMs)} → {farmTime(toMs)} · {int(c.sectionHours)} section-hours
              </Text>

              {qRows.map((r) => (
                <View key={r.key} style={styles.qRow}>
                  <View style={styles.qHead}>
                    <Text style={styles.qLabel}>{r.label}</Text>
                    <Pill kind={r.kind} />
                  </View>
                  <View style={styles.qNums}>
                    <Stat cap="Assumed" value={r.assumed} />
                    <Stat cap="Measured" value={r.measured} strong />
                    <Stat cap="Tolerance" value={r.tolerance} />
                  </View>
                  <Text style={styles.qFoot}>
                    {r.kind === 'ok' || r.kind === 'bad'
                      ? `Gap ${r.gap} · from ${int(r.hours)} section-hours`
                      : str(r.reason, 'The server gave no verdict for this constant.')}
                  </Text>
                </View>
              ))}

              {!!str(overall.text, '') && (
                <Notice tone={overall.holds === true ? 'ok' : overall.holds === false ? 'bad' : 'warn'}
                  icon={overall.holds === true ? 'checkmark-circle' : 'alert-circle-outline'}>
                  <Text style={styles.noticeTxt}>{str(overall.text)}</Text>
                </Notice>
              )}

              <Text style={styles.subHead}>The outdoor weather it was compared with</Text>
              <Text style={styles.srcLabel}>
                {SOURCE_LABEL[src.source] || str(src.source, 'Source not given')}
              </Text>
              {parts.map((p, i) => (
                <Text key={i} style={[styles.srcPart, !p.era5 && { color: COLORS.warning }]}>
                  {p.api} · {p.from} – {p.to} · {int(p.hours)} h
                </Text>
              ))}
              {!!str(src.note, '') && <Text style={styles.note}>{str(src.note)}</Text>}
              {str(loc.source, '') && loc.source !== 'farm settings' ? (
                <Notice tone="warn">
                  <Text style={styles.noticeTxt}>Location used: {str(loc.source)}.</Text>
                </Notice>
              ) : Number.isFinite(loc.latitude) && Number.isFinite(loc.longitude) ? (
                <Text style={styles.note}>
                  At the farm's own location, {num(loc.latitude, 4)}, {num(loc.longitude, 4)}.
                </Text>
              ) : null}

              <Text style={styles.subHead}>A day inside against the assumed day</Text>
              <Tabs value={field} onChange={setField} />
              {chart.empty ? (
                <Text style={styles.note}>
                  No hour of the day has a {F.label.toLowerCase()} reading in this window.
                </Text>
              ) : (
                <>
                  <FlowChart width={chartW} height={170}
                    xDomain={[0, 24]} yDomain={[chart.yMin, chart.yMax]}
                    xTicks={[0, 6, 12, 18, 24]} xFormat={clockTick}
                    yFormat={(y) => y.toFixed(F.digits)}
                    yLabel={`${F.label} (${F.unit}), median for each hour of the day`}
                    xLabel="time of day at the farm"
                    layers={[
                      ...chart.outdoor.map((pts) => ({
                        type: 'line', points: pts, color: COLORS.textTertiary, width: 1.5, opacity: 0.55 })),
                      ...chart.assumed.map((pts) => ({
                        type: 'line', points: pts, color: COLORS.estimated, width: 2 })),
                      ...chart.indoor.map((pts) => ({
                        type: 'line', points: pts, color: F.color, width: 2 })),
                      { type: 'dots', points: chart.indoor.flat(), color: F.color, size: 5 },
                    ]} />
                  <Legend items={[
                    { label: 'Measured inside', color: F.color },
                    { label: 'Outdoor + assumed (what training used)', color: COLORS.estimated },
                    { label: 'Outdoor as it is', color: COLORS.textTertiary, style: { opacity: 0.55 } },
                  ]} />
                  <Text style={styles.note}>
                    Each point is the median of that hour over every day and section compared
                    ({int(chart.hoursWithIndoor)} of the day's hours have readings). An hour with no
                    readings is left as a gap, not drawn through.
                  </Text>
                </>
              )}

              <Text style={styles.subHead}>Does the conversion help?</Text>
              <Table
                head={['', 'Outdoor + assumed', 'Outdoor as is']}
                flex={[0.8, 1.3, 1.1]}
                rows={[
                  ['Temp', { text: Number.isFinite(tempErr.outdoorPlusAssumed)
                    ? `±${num(tempErr.outdoorPlusAssumed, 2)} °C` : '—', color: better(tempErr) },
                   Number.isFinite(tempErr.outdoorAsIs) ? `±${num(tempErr.outdoorAsIs, 2)} °C` : '—'],
                  ['RH', { text: Number.isFinite(rhErr.outdoorPlusAssumed)
                    ? `±${num(rhErr.outdoorPlusAssumed, 1)} %` : '—', color: better(rhErr) },
                   Number.isFinite(rhErr.outdoorAsIs) ? `±${num(rhErr.outdoorAsIs, 1)} %` : '—'],
                ]} />
              <Text style={styles.note}>
                Average error of the indoor estimate against what the sensors measured
                {Number.isFinite(tempErr.hours) ? `, over ${int(tempErr.hours)} section-hours` : ''}.
                If the conversion does its job, the first column is the smaller one (green); red
                means using the outdoor weather unchanged would have been closer.
              </Text>

              {!!secRows.length && (
                <>
                  <Text style={styles.subHead}>Each section on its own</Text>
                  <Table
                    head={['Section', 'Hours', 'Warming', 'RH lift', 'Light']}
                    flex={[0.85, 0.75, 1, 0.95, 0.85]}
                    rows={secRows.map((s) => [
                      s.sid, int(s.hours),
                      ...['warming', 'humidityLift', 'transmission'].map((q) => ({
                        text: s[q].text,
                        color: s[q].kind === 'ok' ? COLORS.primary
                          : s[q].kind === 'bad' ? COLORS.danger : undefined,
                      })),
                    ])} />
                  <Text style={styles.note}>
                    Measured values. Green is within tolerance, red outside it, a dash too few
                    hours to tell.
                  </Text>
                </>
              )}

              {!!excludedBits.length && (
                <Text style={styles.note}>
                  Left out before comparing: {excludedBits.join('; ')}. A missing reading is
                  dropped, never filled in.
                </Text>
              )}
            </View>
          ) : null}
        </Step>

        {/* ── 4 ── */}
        <Step n={4} title="What this does not prove">
          <Text style={styles.body}>
            That the watering rule itself is the best for these plants. Step 2 shows the model
            follows the rule. Step 3 shows whether the rule was given the right house. Whether
            watering at those times gives healthier roots, growth and flowering is a question
            about the plants: it needs grower outcomes recorded over a season, and none are in
            this data.
          </Text>
          {check && fromMs != null && toMs != null ? (
            <Text style={styles.note}>
              The indoor check covers {farmTime(fromMs, true)} to {farmTime(toMs, true)} only -
              one stretch of one season.
            </Text>
          ) : null}
        </Step>

        {(generatedMs != null || !!str(v.script, '')) && (
          <Text style={styles.foot}>
            Model test generated {generatedMs != null ? farmTime(generatedMs) : '—'}
            {str(v.script, '') ? ` by ${str(v.script)}` : ''}
          </Text>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  scroll: { padding: SPACE.lg, paddingBottom: SPACE.xl * 3, gap: SPACE.md },
  inline: { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, paddingVertical: SPACE.md },

  card: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg },

  answer:     { backgroundColor: COLORS.primaryDim, gap: 6 },
  answerHead: { color: COLORS.primary, fontSize: FONT.xs, fontWeight: '800',
                letterSpacing: 0.4, textTransform: 'uppercase' },
  answerTxt:  { color: COLORS.text, fontSize: FONT.sm, lineHeight: 19, fontWeight: '600' },

  stepHead:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  stepNum:    { width: 22, height: 22, borderRadius: 11, backgroundColor: COLORS.primary,
                alignItems: 'center', justifyContent: 'center' },
  stepNumTxt: { color: '#FFF', fontSize: 11, fontWeight: '800' },
  stepTitle:  { flex: 1, color: COLORS.text, fontSize: FONT.md, fontWeight: '800' },
  what:       { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17,
                marginTop: SPACE.sm, marginBottom: SPACE.md },

  big:  { color: COLORS.text, fontSize: FONT.lg, fontWeight: '800', marginTop: SPACE.md,
          fontVariant: ['tabular-nums'] },
  sub:  { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 16, marginTop: 2,
          marginBottom: SPACE.sm, flexShrink: 1 },
  subHead: { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '800', letterSpacing: 0.4,
             textTransform: 'uppercase', marginTop: SPACE.lg, marginBottom: SPACE.xs },
  note: { color: COLORS.textTertiary, fontSize: 11, lineHeight: 16, marginTop: SPACE.sm },
  body: { color: COLORS.text, fontSize: FONT.sm, lineHeight: 19 },

  chain:     { marginBottom: SPACE.xs },
  chainRow:  { flexDirection: 'row', gap: SPACE.sm },
  chainRail: { width: 24, alignItems: 'center' },
  chainDot:  { width: 24, height: 24, borderRadius: 12, alignItems: 'center',
               justifyContent: 'center' },
  chainLine: { flex: 1, width: 2, backgroundColor: COLORS.border, marginVertical: 2 },
  chainBody: { flex: 1, paddingBottom: SPACE.md },
  chainTag:  { fontSize: 9.5, fontWeight: '800', letterSpacing: 0.4, textTransform: 'uppercase' },
  chainTxt:  { color: COLORS.text, fontSize: FONT.xs, lineHeight: 16, marginTop: 1 },

  chips:   { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: SPACE.xs },
  chip:    { borderRadius: RADIUS.full, paddingHorizontal: 9, paddingVertical: 4 },
  chipTxt: { fontSize: 10.5, fontWeight: '800' },

  notice:     { flexDirection: 'row', gap: SPACE.sm, borderRadius: RADIUS.sm, padding: SPACE.md,
                marginTop: SPACE.md },
  noticeHead: { color: COLORS.text, fontSize: FONT.xs, fontWeight: '800' },
  noticeTxt:  { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17 },
  noticeSrc:  { color: COLORS.textTertiary, fontSize: 10.5, lineHeight: 15, fontStyle: 'italic' },

  tabs:     { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: SPACE.xs,
              marginBottom: SPACE.sm },
  sinceRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginBottom: SPACE.sm },
  sinceNote: { width: '100%', color: COLORS.textTertiary, fontSize: 10.5, lineHeight: 15,
               marginTop: 2 },
  tab:      { borderRadius: RADIUS.full, paddingHorizontal: 11, paddingVertical: 5,
              backgroundColor: COLORS.bgCardAlt },
  tabTxt:   { color: COLORS.textSecondary, fontSize: 11, fontWeight: '800' },

  table: { marginTop: SPACE.xs },
  thead: { flexDirection: 'row', borderBottomWidth: 1.5, borderBottomColor: COLORS.textSecondary,
           paddingBottom: 5 },
  th:    { color: COLORS.textTertiary, fontSize: 9.5, fontWeight: '800', letterSpacing: 0.2 },
  tr:    { flexDirection: 'row', paddingVertical: 6, borderBottomWidth: 1,
           borderBottomColor: COLORS.borderLight },
  td:    { color: COLORS.textSecondary, fontSize: 11.5, fontVariant: ['tabular-nums'] },
  tdFirst: { color: COLORS.text, fontWeight: '800' },
  num:   { textAlign: 'right' },

  legend:     { flexDirection: 'row', flexWrap: 'wrap', gap: SPACE.md, marginTop: SPACE.sm },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  legendSw:   { width: 10, height: 10, borderRadius: 5 },
  legendTxt:  { color: COLORS.textSecondary, fontSize: 10, fontWeight: '600' },

  qRow:   { paddingVertical: SPACE.md, borderBottomWidth: 1, borderBottomColor: COLORS.borderLight },
  qHead:  { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, flexWrap: 'wrap' },
  qLabel: { flex: 1, minWidth: 120, color: COLORS.text, fontSize: FONT.sm, fontWeight: '800' },
  qNums:  { flexDirection: 'row', gap: SPACE.sm, marginTop: SPACE.sm },
  qFoot:  { color: COLORS.textTertiary, fontSize: 11, lineHeight: 16, marginTop: 6 },
  stat:   { flex: 1 },
  statCap:{ color: COLORS.textTertiary, fontSize: 9.5, fontWeight: '800', letterSpacing: 0.2,
            textTransform: 'uppercase' },
  statVal:{ color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700', marginTop: 2,
            fontVariant: ['tabular-nums'] },
  statStrong: { color: COLORS.text, fontWeight: '800' },

  pill:    { flexDirection: 'row', alignItems: 'center', gap: 4, borderRadius: RADIUS.full,
             paddingHorizontal: 8, paddingVertical: 3 },
  pillTxt: { fontSize: 10.5, fontWeight: '800' },

  srcLabel: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '800', lineHeight: 18 },
  srcPart:  { color: COLORS.textSecondary, fontSize: FONT.xs, marginTop: 3,
              fontVariant: ['tabular-nums'] },

  rec:    { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start',
            backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.sm, padding: SPACE.md,
            marginTop: SPACE.md },
  recTxt: { color: COLORS.text, fontSize: FONT.xs, lineHeight: 17, fontWeight: '600' },

  secondary:  { borderWidth: 1.5, borderColor: COLORS.primary, borderRadius: RADIUS.sm,
                paddingVertical: SPACE.md, alignItems: 'center' },
  secondaryTxt: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '800' },
  foot: { color: COLORS.textTertiary, fontSize: FONT.xs, textAlign: 'center' },
});
