/**
 * Choose where the farm is.
 *
 * REBUILT 19 Oct 2026, because the grower found the old picker hard to use. It
 * opened on the whole of Sri Lanka, its search gave a single guess or nothing,
 * and the farm was marked by tapping a small map and then dragging a small pin
 * with a finger.
 *
 * Now there are three ways in, in the order a farmer reaches for them:
 *   1. "Use my current location", for someone standing at the farm.
 *   2. Search: type a town or village and choose from a LIST of matches, each
 *      with its district, so two villages with one name cannot be confused.
 *   3. The map: the pin stays in the middle and the map moves under it.
 * Typed coordinates or a pasted Google Maps link remain as a fourth way.
 *
 * The nearest village is close enough, and the screen says so. The location
 * decides which place the outdoor weather forecast is downloaded for, and a
 * forecast covers kilometres, not one roof. Saving is held back only while the
 * map is zoomed out so far that the pin could be anywhere in a district.
 *
 * Why Leaflet in a WebView rather than react-native-maps: Google Maps needs a
 * native module and an API key in the native manifest. This project's android/
 * folder is prebuilt and `expo prebuild` must never be run over it, so a new
 * native dependency is a genuine risk. react-native-webview is already one.
 * The map page is locationMapHtml.js; place search is services/places.js.
 */
import React, { useState, useRef, useEffect } from 'react';
import {
  View, Text, StyleSheet, Modal, TouchableOpacity, TextInput, ScrollView,
  ActivityIndicator, Platform, PermissionsAndroid, Keyboard,
} from 'react-native';
import { WebView } from 'react-native-webview';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';
import { mapHtml } from './locationMapHtml';
import { searchPlaces, placeNear, parseCoordinates, inSriLanka } from '../services/places';

/* Centre of Sri Lanka when nothing has been chosen yet. Deliberately NOT the
   Peradeniya default the backend falls back to: a ready-placed pin invites
   someone to accept it without looking. */
const FALLBACK = { lat: 7.8731, lon: 80.7718, zoom: 7 };

/* Below this the screen spans tens of kilometres and the pin could be
   anywhere in a district. At 11 a phone shows about 30 km across, enough to
   put the pin on the right village. */
const MIN_SAVE_ZOOM = 11;

/* The place name is looked up again only when the pin has moved further than
   this, so nudging the map does not flicker the name. */
const RENAME_KM = 0.3;

const GPS_FAIL = {
  1: 'Location is not allowed for this app. Search for your town instead.',
  2: 'The phone could not find where it is. Turn on Location in the phone’s quick settings, or search for your town.',
  3: 'No GPS fix yet. Step outside and try again, or search for your town.',
  0: 'This phone could not give its location here. Search for your town instead.',
};

const km = (a, b) => {
  const dy = (a.lat - b.lat) * 110.57;
  const dx = (a.lon - b.lon) * 111.32 * Math.cos((a.lat * Math.PI) / 180);
  return Math.sqrt(dx * dx + dy * dy);
};

export default function LocationPicker({ visible, onCancel, ...rest }) {
  /* The body mounts afresh every time the picker opens, so it always starts
     from the CURRENT saved location. When the state lived out here it outlived
     the modal: a screen that rendered the picker before its farm had loaded
     would later open it on the empty map, whatever was saved. */
  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onCancel}>
      {visible ? <PickerBody onCancel={onCancel} {...rest} /> : null}
    </Modal>
  );
}

function PickerBody({ initial, onCancel, onPick, saving = false }) {
  const hasInitial = initial?.latitude != null && initial?.longitude != null
    && Number.isFinite(Number(initial.latitude)) && Number.isFinite(Number(initial.longitude));
  const startLat = hasInitial ? Number(initial.latitude) : FALLBACK.lat;
  const startLon = hasInitial ? Number(initial.longitude) : FALLBACK.lon;
  const startZoom = hasInitial ? 15 : FALLBACK.zoom;

  const web = useRef(null);
  // Built once per opening: a new string on a re-render would reload the map.
  const html = useRef(mapHtml({
    lat: startLat, lon: startLon, zoom: startZoom, armed: hasInitial, pinColor: COLORS.primary,
  })).current;

  const [pin, setPin] = useState(hasInitial ? { lat: startLat, lon: startLon } : null);
  const [zoom, setZoom] = useState(startZoom);
  const [place, setPlace] = useState(null);           // { title, detail }: where the pin is, in words
  const [placeBusy, setPlaceBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [mapErr, setMapErr] = useState(null);
  const [layer, setLayerMode] = useState('sat');

  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);       // null while there is no list
  const [searching, setSearching] = useState(false);
  const [searchErr, setSearchErr] = useState(null);

  const [gps, setGps] = useState(null);               // null | 'finding' | why it failed
  const [typing, setTyping] = useState(null);         // the coordinates text, while typing
  const [typingErr, setTypingErr] = useState(null);
  const [note, setNote] = useState(null);             // e.g. "the numbers were swapped"

  const run = (js) => web.current?.injectJavaScript(`${js}; true;`);

  /* A place chosen before the map page has started is kept and applied when
     it reports ready. Injected early, `window.goTo` does not exist yet, and the
     page's error handler would report a failed map that had not failed. */
  const pending = useRef(null);
  const goTo = (lat, lon, z) => {
    if (loaded) run(`window.goTo(${lat}, ${lon}, ${z})`);
    else pending.current = { lat, lon, z };
  };

  /* The pin's place in words, a moment after it stops. Numbered, so a slow
     answer about an old position never replaces a newer one. */
  const lookup = useRef(0);
  const describedAt = useRef(null);
  const describe = (lat, lon) => {
    const id = ++lookup.current;
    describedAt.current = { lat, lon };
    setPlace(null);
    setPlaceBusy(true);
    setTimeout(async () => {
      if (id !== lookup.current) return;
      try {
        const words = await placeNear(lat, lon);
        if (id === lookup.current) setPlace(words ? { title: `Near ${words}` } : null);
      } catch (_) {
        if (id === lookup.current) setPlace(null);    // the coordinates still show
      } finally {
        if (id === lookup.current) setPlaceBusy(false);
      }
    }, 600);
  };
  const forget = () => {
    lookup.current += 1;
    describedAt.current = null;
    setPlace(null);
    setPlaceBusy(false);
  };

  useEffect(() => { if (hasInitial) describe(startLat, startLon); }, []);

  /* Search as the farmer types, after a short pause. Numbered the same way:
     the answer for "Kan" must not replace the answer for "Kandy". */
  const searchId = useRef(0);
  useEffect(() => {
    const q = query.trim();
    const id = ++searchId.current;
    if (q.length < 3) {
      setResults(null); setSearchErr(null); setSearching(false);
      return undefined;
    }
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        const list = await searchPlaces(q);
        if (id === searchId.current) { setResults(list); setSearchErr(null); }
      } catch (e) {
        if (id === searchId.current) { setResults(null); setSearchErr(e.message); }
      } finally {
        if (id === searchId.current) setSearching(false);
      }
    }, 450);
    return () => clearTimeout(t);
  }, [query]);

  const choose = (p) => {
    Keyboard.dismiss();
    setQuery('');
    setNote(null);
    lookup.current += 1;
    describedAt.current = { lat: p.latitude, lon: p.longitude };
    setPlaceBusy(false);
    setPlace({ title: p.name, detail: p.detail });
    setPin({ lat: p.latitude, lon: p.longitude });
    setZoom(p.zoom);
    goTo(p.latitude, p.longitude, p.zoom);
  };

  const onMessage = (e) => {
    let m = null;
    try { m = JSON.parse(e.nativeEvent.data); } catch (_) { return; }
    if (m.type === 'ready') {
      setLoaded(true);
      const g = pending.current;
      pending.current = null;
      if (g) run(`window.goTo(${g.lat}, ${g.lon}, ${g.z})`);
    }
    else if (m.type === 'tilesok') { setLoaded(true); setMapErr(null); }
    else if (m.type === 'fail') setMapErr(m.why || 'The map could not load.');
    else if (m.type === 'view') {
      setZoom(m.zoom);
      if (!m.armed) return;
      const at = { lat: m.lat, lon: m.lon };
      setPin(at);
      if (m.zoom < MIN_SAVE_ZOOM) { forget(); return; }
      if (!describedAt.current || km(at, describedAt.current) > RENAME_KM) describe(at.lat, at.lon);
    }
    else if (m.type === 'gps') {
      setGps(null);
      setPin({ lat: m.lat, lon: m.lon });
      setNote(m.accuracy > 150
        ? `The phone only knows its position to about ${Math.round(m.accuracy)} m here. Check the pin is on the farm.`
        : null);
    }
    else if (m.type === 'gpsfail') setGps(GPS_FAIL[m.code] || GPS_FAIL[0]);
  };

  /* Android needs the runtime permission before the WebView may have a fix.
     PermissionsAndroid is part of React Native and the permission is already
     in the native manifest, so this needs no new native module. */
  const findMe = async () => {
    Keyboard.dismiss();
    setNote(null);
    if (!loaded) { setGps('The map has not finished loading yet. Try again in a moment.'); return; }
    setGps('finding');
    try {
      if (Platform.OS === 'android') {
        const granted = await PermissionsAndroid.request(
          PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
          {
            title: 'Use this phone’s location?',
            message: 'Used once, to put the pin where you are standing.',
            buttonPositive: 'Allow',
            buttonNegative: 'Not now',
          },
        );
        if (granted !== PermissionsAndroid.RESULTS.GRANTED) { setGps(GPS_FAIL[1]); return; }
      }
      run('window.locateMe && window.locateMe()');
    } catch (_) {
      setGps(GPS_FAIL[0]);
    }
  };

  const showTyped = () => {
    const p = parseCoordinates(typing);
    if (!p) {
      setTypingErr('Those could not be read. Write them like 7.2683, 80.5960 (latitude first).');
      return;
    }
    setTyping(null);
    setTypingErr(null);
    forget();
    setPin({ lat: p.latitude, lon: p.longitude });
    setZoom(16);
    setNote(p.swapped
      ? 'The two numbers were the wrong way round, so they were swapped. Check the pin is on the farm.'
      : null);
    goTo(p.latitude, p.longitude, 16);
  };

  const setLayer = (which) => {
    setLayerMode(which);
    run(`window.setLayer && window.setLayer('${which}')`);
  };

  const tooFar = !!pin && zoom < MIN_SAVE_ZOOM;
  const outside = !!pin && !inSriLanka(pin.lat, pin.lon);
  const primary = () => {
    if (!pin || saving) return;
    if (tooFar) { run('window.zoomOnPin && window.zoomOnPin()'); return; }
    onPick({ latitude: Number(pin.lat.toFixed(6)), longitude: Number(pin.lon.toFixed(6)) });
  };

  const q = query.trim();
  const showList = q.length >= 3 && (searching || searchErr || results);

  let chosenTitle;
  let chosenDetail = null;
  let chosenSub = null;
  if (!pin) {
    chosenTitle = 'Nothing chosen yet';
    chosenSub = 'Use your location, search above, or move the map so the pin is on the farm.';
  } else if (tooFar) {
    chosenTitle = 'Zoom in closer';
    chosenSub = 'Move the map so the pin is on your area, then zoom in.';
  } else {
    chosenTitle = placeBusy ? 'Finding the place name…' : (place?.title || 'Pin placed');
    chosenDetail = placeBusy ? null : place?.detail || null;
    chosenSub = `${pin.lat.toFixed(5)}, ${pin.lon.toFixed(5)}`;
  }
  const warning = note
    || (outside ? 'This point is outside Sri Lanka. Check it is right before saving.' : null)
    || (mapErr ? `${mapErr} You can still type the coordinates.` : null);

  return (
    <View style={s.wrap}>
      <View style={s.head}>
        <TouchableOpacity onPress={onCancel} style={s.headBtn} accessibilityRole="button"
          accessibilityLabel="Close without saving">
          <Ionicons name="close" size={22} color={COLORS.text} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Where is your farm?</Text>
          <Text style={s.sub}>For the weather forecast. The nearest village is close enough.</Text>
        </View>
      </View>

      {typing != null ? (
        <View style={s.tools}>
          <Text style={s.fieldLabel}>Coordinates or a Google Maps link</Text>
          <TextInput
            style={s.input}
            value={typing}
            onChangeText={(v) => { setTyping(v); setTypingErr(null); }}
            onSubmitEditing={showTyped}
            placeholder="7.2683, 80.5960"
            placeholderTextColor={COLORS.textTertiary}
            autoCapitalize="none"
            autoCorrect={false}
            autoFocus
            returnKeyType="done"
            accessibilityLabel="Coordinates or a Google Maps link"
          />
          {typingErr
            ? <Text style={s.warnTxt}>{typingErr}</Text>
            : <Text style={s.hint}>
                In Google Maps, press and hold on the farm. The numbers appear at the
                top: copy them and paste them here.
              </Text>}
          <View style={s.row}>
            <TouchableOpacity style={s.ghost} onPress={() => { setTyping(null); setTypingErr(null); }}
              accessibilityRole="button">
              <Text style={s.ghostTxt}>Back</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[s.primary, s.flex1, !typing.trim() && s.primaryOff]}
              disabled={!typing.trim()} onPress={showTyped} accessibilityRole="button">
              <Text style={s.primaryTxt}>Show on the map</Text>
            </TouchableOpacity>
          </View>
        </View>
      ) : (
        <View style={s.tools}>
          <TouchableOpacity style={s.gpsBtn} onPress={findMe} disabled={gps === 'finding'}
            activeOpacity={0.75} accessibilityRole="button"
            accessibilityLabel="Use my current location. Best when you are at the farm now.">
            {gps === 'finding'
              ? <ActivityIndicator size="small" color={COLORS.primary} />
              : <Ionicons name="navigate" size={20} color={COLORS.primary} />}
            <View style={{ flex: 1 }}>
              <Text style={s.gpsTxt}>{gps === 'finding' ? 'Finding where you are…' : 'Use my current location'}</Text>
              <Text style={s.gpsSub}>Best when you are at the farm now</Text>
            </View>
          </TouchableOpacity>
          {gps && gps !== 'finding' ? <Text style={s.warnTxt}>{gps}</Text> : null}

          <View style={s.searchRow}>
            <Ionicons name="search" size={18} color={COLORS.textTertiary} />
            <TextInput
              style={s.search}
              value={query}
              onChangeText={setQuery}
              placeholder="Or search your town or village"
              placeholderTextColor={COLORS.textTertiary}
              returnKeyType="search"
              autoCorrect={false}
              maxFontSizeMultiplier={1.2}
              accessibilityLabel="Search for a town or village"
            />
            {searching
              ? <ActivityIndicator size="small" color={COLORS.primary} />
              : query
                ? (
                  <TouchableOpacity onPress={() => setQuery('')} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                    accessibilityRole="button" accessibilityLabel="Clear the search">
                    <Ionicons name="close-circle" size={20} color={COLORS.textTertiary} />
                  </TouchableOpacity>
                )
                : null}
          </View>
        </View>
      )}

      <View style={s.mapWrap}>
        <WebView
          ref={web}
          originWhitelist={['*']}
          /* A real https origin: the WebView only offers GPS to a secure page,
             and the inline HTML would otherwise be about:blank. */
          source={{ html, baseUrl: 'https://www.openstreetmap.org' }}
          onMessage={onMessage}
          javaScriptEnabled
          domStorageEnabled
          geolocationEnabled
          /* flex:1 is not optional: without it the WebView collapses to zero
             height inside a flex parent and draws the map into nothing. */
          style={s.web}
          onError={(e) => setMapErr(e.nativeEvent?.description || 'The map could not load.')}
          onHttpError={(e) => setMapErr(`The map could not load (HTTP ${e.nativeEvent?.statusCode}).`)}
          {...(Platform.OS === 'android' ? { mixedContentMode: 'always' } : {})}
        />

        <View style={[s.segment, SHADOW.sm]}>
          {[['sat', 'Satellite'], ['street', 'Map']].map(([k, label]) => (
            <TouchableOpacity key={k} style={[s.segBtn, layer === k && s.segBtnOn]}
              onPress={() => setLayer(k)} accessibilityRole="button"
              accessibilityState={{ selected: layer === k }}>
              <Text style={[s.segTxt, layer === k && s.segTxtOn]}>{label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {!loaded && !mapErr ? (
          <View style={s.mapLoading} pointerEvents="none">
            <ActivityIndicator size="small" color={COLORS.primary} />
            <Text style={s.mapLoadingTxt}>Loading the map…</Text>
          </View>
        ) : null}

        {/* Matches cover the top of the map while there are any. Choosing one
            moves the map there and closes the list. */}
        {showList ? (
          <View style={[s.results, SHADOW.md]}>
            {searchErr ? (
              <Text style={s.resultMsg}>{searchErr}</Text>
            ) : !results ? (
              <View style={s.resultBusy}>
                <ActivityIndicator size="small" color={COLORS.primary} />
                <Text style={s.resultMsg}>Searching…</Text>
              </View>
            ) : results.length === 0 ? (
              <Text style={s.resultMsg}>
                No place in Sri Lanka called {'“'}{q}{'”'}. Try the nearest town, or move the map.
              </Text>
            ) : (
              <ScrollView style={s.resultScroll} keyboardShouldPersistTaps="handled">
                {results.map((p, i) => (
                  <TouchableOpacity key={`${p.name}-${p.latitude}-${p.longitude}`}
                    style={[s.result, i > 0 && s.resultLine]} onPress={() => choose(p)}
                    activeOpacity={0.6} accessibilityRole="button"
                    accessibilityLabel={`${p.name}. ${p.detail}`}>
                    <Ionicons name={p.isPlace ? 'location-outline' : 'flag-outline'} size={18}
                      color={COLORS.primary} />
                    <View style={{ flex: 1 }}>
                      <Text style={s.resultName} numberOfLines={1}>{p.name}</Text>
                      {p.detail ? <Text style={s.resultDetail} numberOfLines={2}>{p.detail}</Text> : null}
                    </View>
                  </TouchableOpacity>
                ))}
              </ScrollView>
            )}
          </View>
        ) : null}
      </View>

      <View style={s.foot}>
        <View style={s.chosen} accessibilityLiveRegion="polite">
          <Ionicons name={pin ? 'location' : 'location-outline'} size={22}
            color={pin && !tooFar ? COLORS.primary : COLORS.textTertiary} />
          <View style={{ flex: 1 }}>
            <Text style={s.chosenTitle} numberOfLines={2}>{chosenTitle}</Text>
            {chosenDetail ? <Text style={s.chosenDetail} numberOfLines={2}>{chosenDetail}</Text> : null}
            {chosenSub ? <Text style={s.chosenSub}>{chosenSub}</Text> : null}
          </View>
        </View>
        {warning ? <Text style={s.warnTxt}>{warning}</Text> : null}

        <TouchableOpacity
          style={[s.primary, (!pin || saving) && s.primaryOff]}
          disabled={!pin || saving}
          onPress={primary}
          accessibilityRole="button"
          accessibilityState={{ disabled: !pin || saving }}>
          {saving ? <ActivityIndicator size="small" color="#FFF" /> : null}
          <Text style={s.primaryTxt}>
            {saving ? 'Saving…' : tooFar ? 'Zoom in on the pin' : 'Save this location'}
          </Text>
        </TouchableOpacity>

        {typing == null ? (
          <TouchableOpacity onPress={() => { Keyboard.dismiss(); setNote(null); setTyping(''); }}
            accessibilityRole="button">
            <Text style={s.link} numberOfLines={1} maxFontSizeMultiplier={1.15}>
              Type coordinates or paste a Google Maps link
            </Text>
          </TouchableOpacity>
        ) : null}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap:     { flex: 1, backgroundColor: COLORS.bg },
  head:     { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
              paddingHorizontal: SPACE.lg, paddingTop: SPACE.xl + SPACE.md, paddingBottom: SPACE.md },
  headBtn:  { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center',
              backgroundColor: COLORS.bgCard },
  title:    { color: COLORS.text, fontSize: FONT.xl, fontWeight: '800' },
  sub:      { color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 2, lineHeight: 17 },

  tools:    { paddingHorizontal: SPACE.lg, gap: SPACE.sm },
  gpsBtn:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
              paddingHorizontal: SPACE.lg, paddingVertical: SPACE.md, borderRadius: RADIUS.md,
              borderWidth: 1.5, borderColor: COLORS.primary, backgroundColor: COLORS.primaryDim },
  gpsTxt:   { color: COLORS.primary, fontSize: FONT.md, fontWeight: '800' },
  gpsSub:   { color: COLORS.textSecondary, fontSize: FONT.sm, marginTop: 1 },

  searchRow:{ flexDirection: 'row', alignItems: 'center', gap: SPACE.sm,
              backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, paddingHorizontal: SPACE.md,
              borderWidth: 1, borderColor: COLORS.border },
  search:   { flex: 1, color: COLORS.text, fontSize: FONT.md, paddingVertical: SPACE.md },

  mapWrap:  { flex: 1, marginHorizontal: SPACE.lg, marginTop: SPACE.md, borderRadius: RADIUS.md,
              overflow: 'hidden', borderWidth: 1, borderColor: COLORS.border },
  web:      { flex: 1, backgroundColor: 'transparent' },
  segment:  { position: 'absolute', top: SPACE.sm, left: SPACE.sm, flexDirection: 'row',
              backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, padding: 3, gap: 2 },
  segBtn:   { paddingHorizontal: SPACE.md, paddingVertical: SPACE.xs + 3, borderRadius: RADIUS.sm - 2 },
  segBtnOn: { backgroundColor: COLORS.primary },
  segTxt:   { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700' },
  segTxtOn: { color: '#FFF' },
  mapLoading:{ position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, alignItems: 'center',
               justifyContent: 'center', gap: SPACE.sm },
  mapLoadingTxt:{ color: COLORS.textSecondary, fontSize: FONT.sm },

  results:  { position: 'absolute', top: SPACE.sm, left: SPACE.sm, right: SPACE.sm,
              backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, overflow: 'hidden' },
  resultScroll:{ maxHeight: 300 },
  result:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
              paddingHorizontal: SPACE.md, paddingVertical: SPACE.md },
  resultLine:{ borderTopWidth: 1, borderTopColor: COLORS.borderLight },
  resultName:{ color: COLORS.text, fontSize: FONT.md, fontWeight: '700' },
  resultDetail:{ color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 1 },
  resultBusy:{ flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, padding: SPACE.md },
  resultMsg:{ color: COLORS.textSecondary, fontSize: FONT.sm, lineHeight: 18, padding: SPACE.md },

  foot:     { paddingHorizontal: SPACE.lg, paddingTop: SPACE.md, paddingBottom: SPACE.xl, gap: SPACE.sm },
  chosen:   { flexDirection: 'row', alignItems: 'center', gap: SPACE.md },
  chosenTitle:{ color: COLORS.text, fontSize: FONT.md, fontWeight: '800' },
  chosenDetail:{ color: COLORS.textSecondary, fontSize: FONT.sm, marginTop: 1 },
  chosenSub:{ color: COLORS.textTertiary, fontSize: FONT.sm, marginTop: 1, fontVariant: ['tabular-nums'] },
  warnTxt:  { color: COLORS.warning, fontSize: FONT.sm, lineHeight: 17 },
  hint:     { color: COLORS.textTertiary, fontSize: FONT.sm, lineHeight: 17 },

  primary:  { flexDirection: 'row', gap: SPACE.sm, alignSelf: 'stretch', alignItems: 'center',
              justifyContent: 'center', paddingVertical: SPACE.md + 3, borderRadius: RADIUS.md,
              backgroundColor: COLORS.primary },
  primaryOff:{ backgroundColor: COLORS.textTertiary, opacity: 0.45 },
  primaryTxt:{ color: '#FFF', fontSize: FONT.md, fontWeight: '800' },
  flex1:    { flex: 1 },
  link:     { color: COLORS.textSecondary, fontSize: FONT.sm, textDecorationLine: 'underline',
              textAlign: 'center', paddingVertical: SPACE.xs },

  fieldLabel:{ color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700' },
  input:    { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, borderWidth: 1,
              borderColor: COLORS.border, paddingHorizontal: SPACE.md, paddingVertical: SPACE.md,
              color: COLORS.text, fontSize: FONT.md },
  row:      { flexDirection: 'row', gap: SPACE.md },
  ghost:    { paddingHorizontal: SPACE.xl, alignItems: 'center', justifyContent: 'center',
              borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  ghostTxt: { color: COLORS.textSecondary, fontSize: FONT.md, fontWeight: '700' },
});
