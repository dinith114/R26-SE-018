/**
 * How the sensor placement was decided - every step, with this house's numbers.
 *
 * Built for the question asked at PP2: what data decides where the sensors go,
 * how is the variation in the readings handled, what are the evaluation
 * metrics, and how far does one node reach. The answer used to be "PySensors
 * picked these", which is a name, not an explanation.
 *
 * The steps ARE a sequence - each one's output is the next one's input - so they
 * are numbered. Every number on this screen is read from the analysis the
 * server ran on the readings the nodes recorded (placement_analysis.py). Where
 * a step could not be done - no co-location, too few pairs for a coverage fit -
 * the screen says so in words instead of drawing something plausible.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  useWindowDimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { useCan } from '../config/auth';
import ScreenHeader from '../components/ScreenHeader';
import DigitalTwin from '../components/DigitalTwin';
import FlowChart from '../components/FlowChart';
import Toast from '../components/Toast';
import { getHouse, getPlacementAnalysis, runPlacementAnalysis } from '../services/careV2';
import {
  coverageChart, placementChart, seriesChart, periodSplit, cleaningRows,
  fmt, farmTime, reachText, METHOD_LABEL,
} from '../services/placementFlow';

const FIELD = {
  temperature: { label: 'Temperature', short: 'Temp', color: COLORS.temperature, digits: 2 },
  humidity:    { label: 'Humidity',    short: 'RH',   color: COLORS.humidity,    digits: 1 },
  vpd:         { label: 'VPD',         short: 'VPD',  color: COLORS.estimated,   digits: 3 },
};
const FIELDS = ['temperature', 'humidity', 'vpd'];

const METHOD_COLOR = {
  pysensors: COLORS.estimated,
  grid: COLORS.info,
  kriging_greedy: COLORS.warning,
  random: COLORS.textTertiary,
};

// One colour per node on the time chart; repeats past eight, which the legend
// makes unambiguous.
const NODE_COLORS = ['#047857', '#0369A1', '#C2410C', '#6D28D9',
                     '#B45309', '#BE123C', '#0F766E', '#4D7C0F'];

const COVERAGE_STATUS = {
  measured: 'Inside the distances actually measured between nodes.',
  extrapolated: 'Beyond the farthest pair of nodes, so the line is extended to reach it - '
    + 'an estimate, not a measurement.',
  'no-growth': 'The difference did not grow with distance across this house: one node '
    + 'covers at least the whole span measured.',
  'direction-dependent': 'Some close pairs already differ by more than the accuracy while '
    + 'pairs farther apart agree - the house changes more in one direction (sun edge to '
    + 'back, say) than another. So there is no single radius, only an upper bound: one '
    + 'node does not reach as far as the closest pair that disagrees.',
  'below-spacing': 'Even the closest nodes differed by more than the sensor accuracy.',
  'too-few-pairs': 'Too few node pairs at different distances to fit a line.',
};

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

export default function PlacementFlowScreen({ route, navigation }) {
  const houseId = route.params?.houseId;
  const can = useCan();
  const { width: screenW } = useWindowDimensions();
  const chartW = screenW - SPACE.lg * 4;

  const [analysis, setAnalysis] = useState(route.params?.analysis || null);
  const [house, setHouse] = useState(null);
  const [loading, setLoading] = useState(!route.params?.analysis);
  const [missing, setMissing] = useState(false);
  const [running, setRunning] = useState(false);
  const [toast, setToast] = useState(null);
  const [seriesField, setSeriesField] = useState('temperature');
  const [covField, setCovField] = useState('temperature');

  const load = useCallback(async () => {
    try {
      const a = await getPlacementAnalysis(houseId);
      setAnalysis(a);
      setMissing(false);
    } catch (e) {
      if (e.status === 404) setMissing(true);
      else setToast({ text: e.message, kind: 'error' });
    } finally {
      setLoading(false);
    }
  }, [houseId]);

  useEffect(() => {
    if (!route.params?.analysis) load();
    getHouse(houseId).then((r) => setHouse(r?.house || null)).catch(() => {});
  }, [houseId, load, route.params?.analysis]);

  /* A real run: ten to twenty seconds of kriging on the server. The spinner is
     for that wait, and nothing pretends to progress while it happens. */
  const rerun = async () => {
    setRunning(true);
    try {
      setAnalysis(await runPlacementAnalysis(houseId));
      setMissing(false);
      setToast({ text: 'Analysis run on the latest readings.', kind: 'success' });
    } catch (e) {
      setToast({ text: e.message, kind: 'error' });
    } finally {
      setRunning(false);
    }
  };

  const series = useMemo(() => seriesChart(analysis, seriesField), [analysis, seriesField]);
  const cov = useMemo(() => coverageChart(analysis, covField), [analysis, covField]);
  const pc = useMemo(() => placementChart(analysis), [analysis]);
  const split = useMemo(() => periodSplit(analysis), [analysis]);
  const cleaning = useMemo(() => cleaningRows(analysis), [analysis]);

  const header = (
    <ScreenHeader title="How it was decided" subtitle={house?.meta?.name || houseId}
      navigation={navigation} showBack />
  );

  if (loading) {
    return (
      <View style={styles.container}>
        {header}
        <View style={styles.center}><ActivityIndicator size="large" color={COLORS.primary} /></View>
      </View>
    );
  }

  if (!analysis) {
    return (
      <View style={styles.container}>
        {header}
        <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />
        <View style={styles.center}>
          <Ionicons name="analytics-outline" size={26} color={COLORS.textTertiary} />
          <Text style={styles.emptyTitle}>
            {missing ? 'No analysis has been run for this house yet' : 'Could not load the analysis'}
          </Text>
          {can('runPlacementAnalysis') && (
            <TouchableOpacity style={styles.primary} onPress={rerun} disabled={running}
              activeOpacity={0.85}>
              {running ? <ActivityIndicator color="#FFF" />
                       : <Text style={styles.primaryTxt}>Run it on the recorded readings</Text>}
            </TouchableOpacity>
          )}
        </View>
      </View>
    );
  }

  const ids = analysis.sections || [];
  const colorOf = (sid) => NODE_COLORS[ids.indexOf(sid) % NODE_COLORS.length];
  const b = analysis.buckets || {};
  const bias = analysis.bias;
  const v = analysis.variation || {};
  const node = (analysis.coverage || {}).node;
  const reach = reachText(node);
  const loo = analysis.leaveOneOut || [];
  const p = analysis.placement || {};
  const tol = analysis.tolerance || {};
  const totalRecords = cleaning.reduce((s, r) => s + r.records, 0);
  const days = b.fromMs && b.toMs ? (b.toMs - b.fromMs) / 86400000 : null;
  const noLight = cleaning.length && cleaning.every((r) => r.validLight === 0);

  const W = house?.meta?.width || 10;
  const L = house?.meta?.length || 14;
  const positions = analysis.positions || {};
  const mapNodes = ids.filter((sid) => positions[sid]).map((sid) => ({
    id: sid, short: String(sid).replace(/^S/, ''),
    x: Number(positions[sid].x), y: Number(positions[sid].y), kind: 'real',
  }));
  const keep = new Set(p.keep || []);
  const chosen = (p.rows || []).find((r) => r.sensors === p.recommended);
  const chosenM = chosen && chosen.selected ? chosen.methods[chosen.selected] : null;

  return (
    <View style={styles.container}>
      {header}
      <Toast text={toast?.text} kind={toast?.kind} onDone={() => setToast(null)} />
      <ScrollView contentContainerStyle={styles.scroll}>

        {/* ── the answer first, then how it was reached ── */}
        <View style={[styles.card, styles.answer, SHADOW.sm]}>
          <Text style={styles.answerHead}>The answer</Text>
          <Text style={styles.answerTxt}>
            {p.recommended
              ? `Keep ${p.recommended} sensors (${(p.keep || []).join(', ')}), chosen by `
                + `${METHOD_LABEL[p.selectedMethod] || p.selectedMethod}.`
              : (p.note || 'No sensors can be removed from this house.')}
          </Text>
          {chosenM && (
            <Text style={styles.answerTxt}>
              Error at the sections without a sensor, on readings no method saw:
              {' '}±{fmt(chosenM.temperature?.mae, 2)} °C, ±{fmt(chosenM.humidity?.mae, 1)} %,
              {' '}±{fmt(chosenM.vpd?.mae, 3)} kPa.
            </Text>
          )}
          {reach && (
            <Text style={styles.answerTxt}>One node covers {reach.long}.</Text>
          )}
          <Text style={styles.answerSrc}>
            From {ids.length} nodes, {farmTime(b.fromMs)} → {farmTime(b.toMs)}
            {days != null ? ` (${days.toFixed(1)} days)` : ''}.
          </Text>
        </View>

        {/* ── 1 ── */}
        <Step n={1} title="The readings"
          what="Everything the nodes recorded during calibration. This is the only input - nothing is generated.">
          <Text style={styles.big}>
            {totalRecords.toLocaleString()} readings · {ids.length} nodes
          </Text>
          <View style={styles.chips}>
            <View style={[styles.chip, { backgroundColor: COLORS.temperatureDim }]}>
              <Text style={[styles.chipTxt, { color: COLORS.temperature }]}>Temperature · DHT22</Text>
            </View>
            <View style={[styles.chip, { backgroundColor: COLORS.humidityDim }]}>
              <Text style={[styles.chipTxt, { color: COLORS.humidity }]}>Humidity · DHT22</Text>
            </View>
            <View style={[styles.chip, { backgroundColor: COLORS.estimatedDim }]}>
              <Text style={[styles.chipTxt, { color: COLORS.estimated }]}>VPD · from both</Text>
            </View>
          </View>
          <Text style={styles.note}>
            VPD is used because it is what the watering model reads; a placement
            that got temperature right and humidity wrong would still water wrongly.
            {noLight ? ' Light is not used: these nodes carry no light sensor.'
                     : ' Light is not used to place sensors: it changes with every cloud.'}
          </Text>

          <Tabs value={seriesField} onChange={setSeriesField} />
          <FlowChart width={chartW} height={150}
            xDomain={[0, Math.max(1, series.xMax)]} yDomain={[series.yMin, series.yMax]}
            yLabel={`${FIELD[seriesField].label} (${(analysis.units || {})[seriesField] || ''}), hourly mean`}
            xLabel={`hours from ${farmTime(series.t0)}`}
            xFormat={(x) => String(Math.round(x))}
            yFormat={(y) => y.toFixed(seriesField === 'vpd' ? 1 : 0)}
            layers={ids.map((sid) => ({
              type: 'line', points: series.lines[sid] || [], color: colorOf(sid), width: 1.5,
            }))} />
          <Legend items={ids.map((sid) => ({ label: sid, color: colorOf(sid) }))} />
        </Step>

        {/* ── 2 ── */}
        <Step n={2} title="Cleaning"
          what="A failed read (-999), a missing value or an impossible one is dropped - never replaced with a default, which would look like a real measurement.">
          <Table
            head={['Node', 'Readings', 'Failed', 'Impossible', 'Kept']}
            flex={[0.8, 1, 0.8, 1, 0.8]}
            rows={cleaning.map((r) => [
              r.sid, r.records.toLocaleString(), r.failed, r.implausible,
              r.records ? `${Math.round((r.validT / r.records) * 100)}%` : '—',
            ])} />
        </Step>

        {/* ── 3 ── */}
        <Step n={3} title="Sensor bias"
          what="Two DHT22s in the same air can disagree by a few tenths of a degree. Spread across a house, that looks exactly like a warm corner.">
          {bias ? (
            <>
              <Text style={styles.note}>
                Measured with every node side by side, {farmTime(bias.startMs)} – {farmTime(bias.endMs, false)}
                {' '}({bias.buckets} ten-minute periods). Each node's offset from the group is
                removed from all its later readings.
              </Text>
              <Table
                head={['Node', 'Temp offset', 'RH offset']}
                flex={[0.8, 1, 1]}
                rows={ids.map((sid) => [sid, (bias.offsets || {})[sid] || null])
                  .map(([sid, o]) => [
                  sid,
                  o ? `${o.temperature >= 0 ? '+' : ''}${fmt(o.temperature, 2)} °C` : 'not there',
                  o ? `${o.humidity >= 0 ? '+' : ''}${fmt(o.humidity, 1)} %` : 'not there',
                ])} />
            </>
          ) : (
            <View style={styles.warn}>
              <Ionicons name="alert-circle-outline" size={15} color={COLORS.warning} />
              <Text style={styles.warnTxt}>
                Not measured - the nodes were not run side by side before being spread out.
                The differences below include each sensor's own offset (up to ±0.5 °C).
              </Text>
            </View>
          )}
        </Step>

        {/* ── 4 ── */}
        <Step n={4} title="Lining up in time, and splitting it"
          what={`Nodes do not report at the same second, so readings are averaged into ${b.minutes || 10}-minute periods. Only periods where every node reported are used.`}>
          <Text style={styles.big}>{b.common} periods in common</Text>
          {split && (
            <>
              <View style={styles.split}>
                {split.parts.map((part) => (
                  <View key={part.key} style={[styles.splitPart, {
                    flex: Math.max(0.05, part.frac),
                    backgroundColor: part.key === 'test' ? COLORS.primary
                      : part.key === 'validate' ? COLORS.info : COLORS.textTertiary,
                  }]} />
                ))}
              </View>
              <View style={styles.splitKey}>
                <Text style={styles.splitTxt}>
                  <Text style={{ color: COLORS.textTertiary, fontWeight: '800' }}>Choose</Text>
                  {' '}{split.parts[0].hours.toFixed(0)} h - each method picks its sensors here
                </Text>
                <Text style={styles.splitTxt}>
                  <Text style={{ color: COLORS.info, fontWeight: '800' }}>Validate</Text>
                  {' '}{split.parts[1].hours.toFixed(0)} h - the methods are compared, the best is selected
                </Text>
                <Text style={styles.splitTxt}>
                  <Text style={{ color: COLORS.primary, fontWeight: '800' }}>Test</Text>
                  {' '}{split.parts[2].hours.toFixed(0)} h - later readings nothing was fitted on; every error below is from here
                </Text>
              </View>
            </>
          )}
        </Step>

        {/* ── 5 ── */}
        <Step n={5} title="Variation in the readings"
          what="How different the sections really are, against how much two sensors can disagree on their own. A placement chosen from differences smaller than that would be choosing noise.">
          <Table
            head={['', 'Avg spread', 'Day', 'Night', '2 sensor errors', 'Uneven']}
            flex={[0.7, 1, 0.75, 0.75, 1.05, 0.9]}
            rows={FIELDS.map((f) => {
              const x = (v.between || {})[f] || {};
              const d = FIELD[f].digits;
              return [
                FIELD[f].short, fmt(x.meanSpread, d), fmt(x.daySpread, d), fmt(x.nightSpread, d),
                fmt(x.twoSensorErrors, d),
                x.fractionBeyondSensorError == null ? '—'
                  : { text: `${Math.round(x.fractionBeyondSensorError * 100)}%`,
                      color: x.fractionBeyondSensorError > 0.5 ? COLORS.primary : COLORS.warning },
              ];
            })} />
          <Text style={styles.note}>
            Spread = warmest section minus coolest, at the same moment. "Uneven" is the share
            of moments when that spread was bigger than two sensors could disagree by - when
            the house was measurably not the same everywhere.
          </Text>
          <Table
            head={['Node', 'Mean temp', 'Range', 'Noise', 'Mean RH']}
            flex={[0.8, 1, 1.2, 0.8, 1]}
            rows={ids.map((sid) => {
              const n = ((v.perNode || {})[sid]) || {};
              const t = n.temperature || {};
              const h = n.humidity || {};
              return [sid, `${fmt(t.mean, 1)} °C`, `${fmt(t.min, 1)}–${fmt(t.max, 1)}`,
                      `±${fmt(t.noise, 2)}`, `${fmt(h.mean, 0)} %`];
            })} />
          <Text style={styles.note}>
            Noise is the typical spread of one node's readings inside ten minutes - an upper
            bound, since real flicker is in it too.
          </Text>
        </Step>

        {/* ── 6 ── */}
        <Step n={6} title="How far one node reaches"
          what="Every pair of nodes is one dot: how far apart they are, and how different their readings were on average. That difference is exactly the error you would make using one of them for the other's spot. Where the fitted line crosses the sensor's own accuracy is one node's reach.">
          <Tabs value={covField} onChange={setCovField} />
          <FlowChart width={chartW} height={170}
            xDomain={[0, cov.xMax]} yDomain={[0, cov.yMax]}
            yLabel={`mean difference (${cov.unit})`} xLabel="distance between the two nodes (m)"
            yFormat={(y) => y.toFixed(covField === 'vpd' ? 2 : covField === 'humidity' ? 0 : 1)}
            layers={[
              { type: 'hline', y: cov.tolerance, color: COLORS.danger,
                label: `sensor accuracy ±${cov.tolerance} ${cov.unit}` },
              ...(cov.line ? [{ type: 'line', color: FIELD[covField].color, width: 2, opacity: 0.8,
                                points: [{ x: cov.line.x0, y: cov.line.y0 },
                                         { x: cov.line.x1, y: cov.line.y1 }] }] : []),
              ...(cov.radius != null ? [{ type: 'vline', x: cov.radius, color: COLORS.primary,
                                          label: `${fmt(cov.radius, 1)} m` }] : []),
              ...(cov.radius == null && cov.atMost != null
                ? [{ type: 'vline', x: cov.atMost, color: COLORS.warning,
                     label: `under ${fmt(cov.atMost, 1)} m` }] : []),
              { type: 'dots', points: cov.points, color: FIELD[covField].color, size: 8 },
            ]} />
          <Text style={styles.covResult}>
            {cov.radius != null
              ? `${FIELD[covField].label}: one node stays within ±${cov.tolerance} ${cov.unit} out to ${fmt(cov.radius, 1)} m.`
              : cov.atMost != null
                ? `${FIELD[covField].label}: one node does not reach ${fmt(cov.atMost, 1)} m - nodes that close already differ.`
                : `${FIELD[covField].label}: no radius.`}
            {cov.r2 != null ? `  (fit R² ${fmt(cov.r2, 2)}, ${cov.points.length} pairs)` : ''}
          </Text>
          <Text style={styles.note}>{COVERAGE_STATUS[cov.status] || cov.note || ''}</Text>

          {node && node.radius != null && (
            <View style={styles.reach}>
              <Text style={styles.reachHead}>One node: {reach.long}</Text>
              <Text style={styles.note}>
                The smallest of the three, set by {FIELD[node.limitedBy]?.label.toLowerCase()} -
                a node only covers a spot if it gets every quantity right there.
              </Text>
              <View style={{ alignItems: 'center', marginTop: SPACE.sm }}>
                <DigitalTwin width={W} length={L} nodes={mapNodes} showPipes={false}
                  maxHeight={260}
                  coverage={{ radius: node.radius, label: `One node's reach, ${reach.short}` }} />
              </View>
            </View>
          )}
        </Step>

        {/* ── 7 ── */}
        <Step n={7} title="Cross-check: hide one node at a time"
          what="Each node is hidden and its readings estimated from the others, the way the system fills in a section with no sensor. If the coverage figure is right, nodes with a near neighbour come out close.">
          <Table
            head={['Hidden', 'Nearest', 'Temp err', 'RH err', 'VPD err']}
            flex={[0.8, 0.9, 1, 0.9, 1]}
            rows={loo.map((r) => [
              r.section, `${fmt(r.nearest, 1)} m`,
              ...FIELDS.map((f) => {
                const e = (r[f] || {}).mae;
                return e == null ? '—' : { text: fmt(e, FIELD[f].digits),
                  color: e <= (tol[f] ?? Infinity) ? COLORS.primary : COLORS.warning };
              }),
            ])} />
          <Text style={styles.note}>
            Mean absolute error. Green is within the sensor's own accuracy.
          </Text>
        </Step>

        {/* ── 8 ── */}
        <Step n={8} title="Choosing the sensors, and the score"
          what="For every number of sensors, three methods each pick which sections keep one: PySensors (SSPOR) from the patterns in the readings, an even spread, and kriging variance. The missing sections are rebuilt by kriging and compared with what was really measured.">
          {pc.ks.length ? (
            <>
              <FlowChart width={chartW} height={180}
                xDomain={[pc.xMin, pc.xMax]} yDomain={[0, pc.yMax]}
                xTicks={pc.ks} xFormat={(x) => String(x)}
                yFormat={(y) => y.toFixed(1)}
                yLabel="error ÷ sensor accuracy (test period)"
                xLabel="sensors kept"
                layers={[
                  { type: 'range', points: pc.range, color: COLORS.primary },
                  { type: 'hline', y: 1, color: COLORS.danger, label: 'as wrong as the sensor' },
                  ...Object.entries(pc.lines).map(([m, pts]) => ({
                    type: 'line', points: pts, color: METHOD_COLOR[m], width: 2 })),
                  ...Object.entries(pc.lines).map(([m, pts]) => ({
                    type: 'dots', points: pts, color: METHOD_COLOR[m], size: 6 })),
                  { type: 'dots', points: pc.selected, color: COLORS.text, size: 11, hollow: true },
                  ...(pc.recommended != null ? [{ type: 'vline', x: pc.recommended,
                    color: COLORS.primary, label: 'recommended' }] : []),
                ]} />
              <Legend items={[
                ...Object.keys(pc.lines).map((m) => ({ label: METHOD_LABEL[m], color: METHOD_COLOR[m] })),
                ...(pc.range.length ? [{ label: 'Best–worst of every layout', color: COLORS.primary,
                                         style: { opacity: 0.25 } }] : []),
                { label: 'Selected on validation', color: 'transparent',
                  style: { borderWidth: 1.5, borderColor: COLORS.text } },
              ]} />
              <Text style={styles.note}>
                1.0 means a section without a sensor is as uncertain as a sensor itself. Lower is better.
                The best–worst bars come from trying every possible layout - the limits any method
                could reach, not something anyone could know in advance.
              </Text>

              <Table
                head={['Kept', 'Chosen by', 'Temp', 'RH', 'VPD', 'Random']}
                flex={[0.6, 1.5, 0.8, 0.7, 0.8, 0.9]}
                rows={(p.rows || []).map((r) => {
                  const m = r.selected ? r.methods[r.selected] : null;
                  const rnd = r.methods.random;
                  return [
                    { text: `${r.sensors}${r.sensors === p.recommended ? ' ★' : ''}`,
                      color: r.sensors === p.recommended ? COLORS.primary : undefined },
                    m ? (METHOD_LABEL[r.selected] || r.selected).replace(' (SSPOR)', '') : '—',
                    m ? fmt(m.temperature?.mae, 2) : '—',
                    m ? fmt(m.humidity?.mae, 1) : '—',
                    m ? fmt(m.vpd?.mae, 3) : '—',
                    rnd ? fmt(rnd.temperature?.mae, 2) : '—',
                  ];
                })} />
              <Text style={styles.note}>
                Mean absolute error on the test period, at the sections without a sensor
                (°C, %, kPa). Random is the temperature error of six random layouts, averaged.
                {(p.rows || []).some((r) => !r.runtimeUsable)
                  ? ` Fewer than 4 sensors is shown for comparison only: kriging needs 4 to run, so the system never uses less.`
                  : ''}
              </Text>
              <View style={styles.rec}>
                <Ionicons name="checkmark-circle" size={16} color={COLORS.primary} />
                <Text style={styles.recTxt}>
                  {p.recommended
                    ? `Recommended: ${p.recommended} sensors - where adding another stops paying for itself (the elbow of the validation curve${p.elbow != null && p.elbow !== p.recommended ? ` at ${p.elbow}` : ''}).`
                    : ''}
                  {p.note ? ` ${p.note}` : ''}
                </Text>
              </View>
            </>
          ) : (
            <Text style={styles.note}>{p.note || 'Not enough sections to compare layouts.'}</Text>
          )}
        </Step>

        {!!keep.size && (
          <View style={[styles.card, SHADOW.sm, { alignItems: 'center' }]}>
            <Text style={styles.mapHead}>The kept sensors and their reach</Text>
            <DigitalTwin width={W} length={L} showPipes={false} maxHeight={300}
              nodes={mapNodes.map((n) => ({ ...n, kind: keep.has(n.id) ? 'real' : 'estimated' }))}
              coverage={node && node.radius != null
                ? { radius: node.radius, label: `Reach of a kept node, ${reach.short}` }
                : null} />
          </View>
        )}

        {can('runPlacementAnalysis') && !route.params?.analysis && (
          <TouchableOpacity style={[styles.secondary, running && { opacity: 0.6 }]}
            onPress={rerun} disabled={running} activeOpacity={0.85}>
            {running ? <ActivityIndicator color={COLORS.primary} />
                     : <Text style={styles.secondaryTxt}>Run again on the latest readings</Text>}
          </TouchableOpacity>
        )}
        {!!analysis.computedAtMs && (
          <Text style={styles.foot}>Computed {farmTime(analysis.computedAtMs)}</Text>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.bg },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: SPACE.xl,
            gap: SPACE.sm },
  emptyTitle: { color: COLORS.text, fontSize: FONT.md, fontWeight: '800', textAlign: 'center' },
  scroll: { padding: SPACE.lg, paddingBottom: SPACE.xl * 3, gap: SPACE.md },

  card: { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: SPACE.lg },

  answer:     { backgroundColor: COLORS.primaryDim, gap: 6 },
  answerHead: { color: COLORS.primary, fontSize: FONT.xs, fontWeight: '800',
                letterSpacing: 0.4, textTransform: 'uppercase' },
  answerTxt:  { color: COLORS.text, fontSize: FONT.sm, lineHeight: 19, fontWeight: '600' },
  answerSrc:  { color: COLORS.textSecondary, fontSize: FONT.xs, marginTop: 2 },

  stepHead:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  stepNum:    { width: 22, height: 22, borderRadius: 11, backgroundColor: COLORS.primary,
                alignItems: 'center', justifyContent: 'center' },
  stepNumTxt: { color: '#FFF', fontSize: 11, fontWeight: '800' },
  stepTitle:  { flex: 1, color: COLORS.text, fontSize: FONT.md, fontWeight: '800' },
  what:       { color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17,
                marginTop: SPACE.sm, marginBottom: SPACE.md },

  big:  { color: COLORS.text, fontSize: FONT.lg, fontWeight: '800', marginBottom: SPACE.sm,
          fontVariant: ['tabular-nums'] },
  note: { color: COLORS.textTertiary, fontSize: 11, lineHeight: 16, marginTop: SPACE.sm },

  chips:   { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip:    { borderRadius: RADIUS.full, paddingHorizontal: 9, paddingVertical: 4 },
  chipTxt: { fontSize: 10.5, fontWeight: '800' },

  tabs:   { flexDirection: 'row', gap: 6, marginTop: SPACE.md, marginBottom: SPACE.sm },
  tab:    { borderRadius: RADIUS.full, paddingHorizontal: 11, paddingVertical: 5,
            backgroundColor: COLORS.bgCardAlt },
  tabTxt: { color: COLORS.textSecondary, fontSize: 11, fontWeight: '800' },

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

  warn:    { flexDirection: 'row', gap: SPACE.sm, backgroundColor: COLORS.warningDim,
             borderRadius: RADIUS.sm, padding: SPACE.md },
  warnTxt: { flex: 1, color: COLORS.textSecondary, fontSize: FONT.xs, lineHeight: 17 },

  split:     { flexDirection: 'row', height: 12, borderRadius: 6, overflow: 'hidden', gap: 2 },
  splitPart: { height: 12 },
  splitKey:  { marginTop: SPACE.sm, gap: 4 },
  splitTxt:  { color: COLORS.textSecondary, fontSize: 11, lineHeight: 16 },

  covResult: { color: COLORS.text, fontSize: FONT.sm, fontWeight: '700', marginTop: SPACE.sm,
               lineHeight: 18 },
  reach:     { marginTop: SPACE.md, paddingTop: SPACE.md, borderTopWidth: 1,
               borderTopColor: COLORS.borderLight },
  reachHead: { color: COLORS.primary, fontSize: FONT.md, fontWeight: '800' },

  rec:    { flexDirection: 'row', gap: SPACE.sm, alignItems: 'flex-start',
            backgroundColor: COLORS.primaryDim, borderRadius: RADIUS.sm, padding: SPACE.md,
            marginTop: SPACE.md },
  recTxt: { flex: 1, color: COLORS.text, fontSize: FONT.xs, lineHeight: 17, fontWeight: '600' },

  mapHead: { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '800',
             letterSpacing: 0.4, textTransform: 'uppercase', marginBottom: SPACE.sm },

  primary:    { backgroundColor: COLORS.primary, borderRadius: RADIUS.sm, paddingVertical: SPACE.md,
                paddingHorizontal: SPACE.xl, alignItems: 'center', marginTop: SPACE.md },
  primaryTxt: { color: '#FFF', fontSize: FONT.sm, fontWeight: '800' },
  secondary:  { borderWidth: 1.5, borderColor: COLORS.primary, borderRadius: RADIUS.sm,
                paddingVertical: SPACE.md, alignItems: 'center' },
  secondaryTxt: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '800' },
  foot: { color: COLORS.textTertiary, fontSize: FONT.xs, textAlign: 'center' },
});
