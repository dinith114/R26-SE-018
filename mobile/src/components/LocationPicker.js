/**
 * Pick the farm's location by looking at a map.
 *
 * The farm's coordinates decide which place the outdoor weather forecast is
 * downloaded for, and that forecast feeds the watering decision. Asking a
 * farmer to type a latitude was the wrong question: nobody knows their
 * coordinates, and a typo in one produces a forecast for somewhere else with
 * nothing on any screen looking wrong.
 *
 * So: a map. Search for the town, or drag the pin onto the greenhouse.
 *
 * Why Leaflet in a WebView rather than react-native-maps: Google Maps needs a
 * native module and a Maps API key in the native manifest. This project's
 * android/ folder is prebuilt and `expo prebuild` must never be run over it, so
 * a new native dependency is a genuine risk. react-native-webview is already a
 * dependency and already renders the Three.js greenhouse views, and
 * OpenStreetMap needs no key at all.
 *
 * Needs internet for map tiles and for the name search. That is not a new
 * requirement - the forecast this setting feeds needs internet too - but the
 * map says so plainly if tiles fail, and coordinates can still be typed by hand
 * as a fallback.
 */
import React, { useState, useRef } from 'react';
import {
  View, Text, StyleSheet, Modal, TouchableOpacity, TextInput,
  ActivityIndicator, Platform, PermissionsAndroid,
} from 'react-native';
import { WebView } from 'react-native-webview';
import { Ionicons } from '@expo/vector-icons';
import { COLORS, FONT, SPACE, RADIUS, SHADOW } from '../config/theme';

/* Centre of Sri Lanka when nothing has been chosen yet. Deliberately NOT the
   Peradeniya training default: showing that as a pre-placed pin invites someone
   to accept it without looking, which is the mistake this screen exists to
   prevent. A pin the farmer placed is the only pin worth trusting. */
const FALLBACK = { lat: 7.8731, lon: 80.7718, zoom: 7 };

/* `lat`/`lon` are ALWAYS real numbers - they centre the map. `pin` decides
   whether a marker starts on it. Passing null for lat to mean "no pin yet" made
   Leaflet throw `Invalid LatLng object: (null, ...)` on the very first call, so
   the map died before drawing anything - in exactly the case that matters, a
   farm whose location has never been set. */
const mapHtml = (lat, lon, zoom, pin) => `<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  html,body,#map{height:100%;margin:0;padding:0;background:#e8ebe5}
  .err{position:absolute;top:50%;left:0;right:0;transform:translateY(-50%);
       text-align:center;font:14px -apple-system,Roboto,sans-serif;color:#6A645E;padding:24px}
</style>
</head><body>
<div id="map"></div>
<div class="err" id="err" style="display:none">
  The map could not load.<br>Check the internet connection, or type coordinates instead.
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  var post = function (o) {
    if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(JSON.stringify(o));
  };
  try {
    if (typeof L === 'undefined') {
      document.getElementById('err').style.display = 'block';
      post({ type: 'fail', why: 'Leaflet did not load' });
    }
    else {
      var map = L.map('map').setView([${lat}, ${lon}], ${zoom});
      /* Esri, not OpenStreetMap's own tiles.

         OSM's servers are volunteer run and their usage policy forbids app use;
         they answer a blocked client with HTTP 418 and an image reading "Access
         blocked", which is what this picker showed at first. Esri serves these
         free with attribution and no API key, and no billing account - which is
         what Google Maps would need even inside its free allowance.

         Two basemaps, because they answer different questions. Satellite is how
         you find YOUR greenhouse - roofs and tree lines are recognisable in a
         way street names are not. Street is how you confirm you are in the
         right village. Satellite carries a labels overlay so it is not an
         unreadable green blur. */
      var esri = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
      var sat = L.tileLayer(esri + 'World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 19, attribution: 'Imagery (c) Esri' });
      var labels = L.tileLayer(esri + 'Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 19, pane: 'overlayPane' });
      var street = L.tileLayer(esri + 'World_Street_Map/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 19, attribution: '(c) Esri' });

      var mode = 'sat';
      sat.addTo(map); labels.addTo(map);
      window.setLayer = function (which) {
        mode = which;
        if (which === 'sat') { map.removeLayer(street); sat.addTo(map); labels.addTo(map); }
        else { map.removeLayer(sat); map.removeLayer(labels); street.addTo(map); }
      };

      /* If a provider ever blocks us the way OSM did, fall back rather than
         showing a blank map. Counted, because one failed tile at the edge of
         the world is normal and must not trigger a switch. */
      var tileFails = 0, swapped = false, anyOk = false;
      sat.on('tileerror', function () {
        tileFails++;
        if (tileFails >= 4 && !swapped && !anyOk) {
          swapped = true;
          map.removeLayer(sat); map.removeLayer(labels);
          L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
            { maxZoom: 19, attribution: '(c) OpenStreetMap, (c) CARTO' }).addTo(map);
          post({ type: 'tilesok' });
        }
      });
      sat.on('load', function () { anyOk = true; post({ type: 'tilesok' }); });
      street.on('load', function () { anyOk = true; post({ type: 'tilesok' }); });
      post({ type: 'ready' });

      var marker = null;
      var place = function (la, lo) {
        if (marker) marker.setLatLng([la, lo]);
        else marker = L.marker([la, lo], { draggable: true }).addTo(map)
               .on('dragend', function (e) {
                 var p = e.target.getLatLng();
                 post({ type: 'pick', lat: p.lat, lon: p.lng });
               });
        post({ type: 'pick', lat: la, lon: lo });
      };

      ${pin ? `place(${lat}, ${lon});` : ''}
      map.on('click', function (e) { place(e.latlng.lat, e.latlng.lng); });

      /* Where the phone is. The farmer is usually STANDING at the greenhouse
         when they set this up, so this is the shortest path to a correct pin -
         no typing, no searching, no knowing the name of the nearest village. */
      window.locateMe = function () {
        if (!navigator.geolocation) { post({ type: 'gpsfail' }); return; }
        post({ type: 'locating' });
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            var la = pos.coords.latitude, lo = pos.coords.longitude;
            map.setView([la, lo], 18);
            place(la, lo);
            post({ type: 'located' });
          },
          function () { post({ type: 'gpsfail' }); },
          { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 }
        );
      };

      // Name search, so "Peradeniya" is a valid answer and coordinates are not.
      window.searchPlace = function (q) {
        post({ type: 'searching' });
        fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&q=' + encodeURIComponent(q))
          .then(function (r) { return r.json(); })
          .then(function (j) {
            if (!j || !j.length) { post({ type: 'noresult' }); return; }
            var la = parseFloat(j[0].lat), lo = parseFloat(j[0].lon);
            map.setView([la, lo], 14);
            place(la, lo);
            post({ type: 'found', name: j[0].display_name });
          })
          .catch(function () { post({ type: 'noresult' }); });
      };
    }
  } catch (e) {
    document.getElementById('err').style.display = 'block';
    post({ type: 'fail', why: String(e && e.message || e) });
  }
  window.onerror = function (m) { post({ type: 'fail', why: String(m) }); };
</script>
</body></html>`;

export default function LocationPicker({ visible, initial, onCancel, onPick }) {
  const hasInitial = initial?.latitude != null && initial?.longitude != null;
  const startLat = hasInitial ? Number(initial.latitude) : FALLBACK.lat;
  const startLon = hasInitial ? Number(initial.longitude) : FALLBACK.lon;

  const web = useRef(null);
  const [picked, setPicked] = useState(hasInitial ? { lat: startLat, lon: startLon } : null);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState(null);      // 'searching' | 'noresult' | 'fail:…' | place name
  const [loaded, setLoaded] = useState(false);    // the map reported itself alive
  const [layerMode, setLayerMode] = useState('sat');
  const [manual, setManual] = useState(null);      // { lat, lon } when typing instead

  const onMessage = (e) => {
    let m = null;
    try { m = JSON.parse(e.nativeEvent.data); } catch (_) { return; }
    if (m.type === 'pick') { setPicked({ lat: m.lat, lon: m.lon }); setStatus(null); }
    else if (m.type === 'searching') setStatus('searching');
    else if (m.type === 'noresult') setStatus('noresult');
    else if (m.type === 'found') setStatus(m.name);
    else if (m.type === 'ready') setLoaded(true);
    else if (m.type === 'tilesok') { setLoaded(true); setStatus((st) => (st || '').startsWith('fail') ? null : st); }
    else if (m.type === 'tileerror') setStatus('fail:Map tiles could not be downloaded. Check the internet connection.');
    else if (m.type === 'fail') setStatus('fail:' + m.why);
    else if (m.type === 'locating') setStatus('locating');
    else if (m.type === 'located') setStatus(null);
    else if (m.type === 'gpsfail')
      setStatus('fail:Could not get a GPS fix. Go outside, or search for the town instead.');
  };

  /* Android needs the runtime permission before the WebView is allowed a fix.
     PermissionsAndroid is part of React Native itself, so this costs no new
     dependency - which matters here, because a new native module would mean
     touching a prebuilt android/ folder that must never see `expo prebuild`. */
  const locateMe = async () => {
    try {
      if (Platform.OS === 'android') {
        const granted = await PermissionsAndroid.request(
          PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
          {
            title: 'Use this phone\u2019s location?',
            message: 'So the pin can start where you are standing, at the greenhouse.',
            buttonPositive: 'Allow',
            buttonNegative: 'Not now',
          },
        );
        if (granted !== PermissionsAndroid.RESULTS.GRANTED) {
          setStatus('fail:Location permission was declined. Search for the town instead.');
          return;
        }
      }
      web.current?.injectJavaScript('window.locateMe && window.locateMe(); true;');
    } catch (e) {
      setStatus('fail:' + e.message);
    }
  };

  const setLayer = (which) => {
    setLayerMode(which);
    web.current?.injectJavaScript(`window.setLayer && window.setLayer('${which}'); true;`);
  };

  const search = () => {
    const q = query.trim();
    if (!q) return;
    web.current?.injectJavaScript(`window.searchPlace(${JSON.stringify(q)}); true;`);
  };

  const confirmManual = () => {
    const la = parseFloat(manual?.lat), lo = parseFloat(manual?.lon);
    if (Number.isNaN(la) || Number.isNaN(lo) ||
        la < -90 || la > 90 || lo < -180 || lo > 180) return;
    onPick({ latitude: la, longitude: lo });
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onCancel}>
      <View style={s.wrap}>
        <View style={s.head}>
          <TouchableOpacity onPress={onCancel} style={s.headBtn} accessibilityRole="button"
            accessibilityLabel="Cancel choosing a location">
            <Ionicons name="close" size={22} color={COLORS.text} />
          </TouchableOpacity>
          <View style={{ flex: 1 }}>
            <Text style={s.title}>Where is the farm?</Text>
            <Text style={s.sub}>Search for the town, or tap the map</Text>
          </View>
        </View>

        {manual ? (
          <View style={s.manualWrap}>
            <Text style={s.manualHint}>
              Type the coordinates if you already have them. Otherwise go back to the map.
            </Text>
            <View style={s.row}>
              <View style={{ flex: 1 }}>
                <Text style={s.fieldLabel}>Latitude</Text>
                <TextInput style={s.input} value={manual.lat} placeholder="7.2683"
                  placeholderTextColor={COLORS.textTertiary}
                  keyboardType="numbers-and-punctuation"
                  onChangeText={(v) => setManual({ ...manual, lat: v })} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.fieldLabel}>Longitude</Text>
                <TextInput style={s.input} value={manual.lon} placeholder="80.5960"
                  placeholderTextColor={COLORS.textTertiary}
                  keyboardType="numbers-and-punctuation"
                  onChangeText={(v) => setManual({ ...manual, lon: v })} />
              </View>
            </View>
            <View style={s.row}>
              <TouchableOpacity style={s.ghost} onPress={() => setManual(null)}>
                <Text style={s.ghostTxt}>Back to map</Text>
              </TouchableOpacity>
              <TouchableOpacity style={s.primary} onPress={confirmManual}>
                <Text style={s.primaryTxt}>Use these</Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : (
          <>
            <View style={s.searchRow}>
              <Ionicons name="search" size={16} color={COLORS.textTertiary} />
              <TextInput
                style={s.search}
                value={query}
                onChangeText={setQuery}
                onSubmitEditing={search}
                returnKeyType="search"
                placeholder="Town or village, e.g. Peradeniya"
                placeholderTextColor={COLORS.textTertiary}
                maxFontSizeMultiplier={1.15}
              />
              <TouchableOpacity onPress={search} style={s.searchBtn} accessibilityRole="button"
                accessibilityLabel="Search for this place">
                <Text style={s.searchBtnTxt}>Find</Text>
              </TouchableOpacity>
            </View>

            <View style={s.mapWrap}>
              <View style={s.overlay} pointerEvents="box-none">
                <View style={s.segment}>
                  {[['sat', 'Satellite'], ['street', 'Map']].map(([k, label]) => (
                    <TouchableOpacity key={k}
                      style={[s.segBtn, layerMode === k && s.segBtnOn]}
                      onPress={() => setLayer(k)} accessibilityRole="button">
                      <Text style={[s.segTxt, layerMode === k && s.segTxtOn]}>{label}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
                <TouchableOpacity style={s.gpsBtn} onPress={locateMe}
                  accessibilityRole="button" accessibilityLabel="Centre the map on where I am now">
                  {status === 'locating'
                    ? <ActivityIndicator size="small" color={COLORS.primary} />
                    : <Ionicons name="locate" size={20} color={COLORS.primary} />}
                </TouchableOpacity>
              </View>
              <WebView
                ref={web}
                originWhitelist={['*']}
                /* baseUrl gives the page a real origin. Without it Android
                   serves the HTML from about:blank, and the place-name lookup
                   becomes a null-origin cross-site request that is refused. */
                source={{
                  html: mapHtml(startLat, startLon, hasInitial ? 14 : FALLBACK.zoom, hasInitial),
                  baseUrl: 'https://www.openstreetmap.org',
                }}
                onMessage={onMessage}
                javaScriptEnabled
                domStorageEnabled
                /* flex:1 is not optional here. Without it the WebView collapses
                   to zero height inside a flex parent and the map appears not to
                   load at all - it is drawing correctly into nothing. */
                style={s.web}
                onError={(e) => setStatus('fail:' + (e.nativeEvent?.description || 'load error'))}
                onHttpError={(e) => setStatus('fail:HTTP ' + e.nativeEvent?.statusCode)}
                geolocationEnabled
                {...(Platform.OS === 'android' ? { mixedContentMode: 'always' } : {})}
              />
            </View>

            <View style={s.foot}>
              {typeof status === 'string' && status.startsWith('fail:') ? (
                <Text style={[s.status, { color: COLORS.danger }]}>
                  {status.slice(5)}{'\n'}Use “I already know the coordinates” below if this persists.
                </Text>
              ) : !loaded ? (
                <View style={s.statusRow}>
                  <ActivityIndicator size="small" color={COLORS.primary} />
                  <Text style={s.status}>Loading the map…</Text>
                </View>
              ) : status === 'locating' ? (
                <View style={s.statusRow}>
                  <ActivityIndicator size="small" color={COLORS.primary} />
                  <Text style={s.status}>Finding where you are…</Text>
                </View>
              ) : status === 'searching' ? (
                <View style={s.statusRow}>
                  <ActivityIndicator size="small" color={COLORS.primary} />
                  <Text style={s.status}>Looking that up…</Text>
                </View>
              ) : status === 'noresult' ? (
                <Text style={[s.status, { color: COLORS.warning }]}>
                  No place found by that name. Try the nearest town, or tap the map.
                </Text>
              ) : status ? (
                <Text style={s.status} numberOfLines={2}>{status}</Text>
              ) : picked ? (
                <Text style={s.status}>Pin placed. Drag it to fine-tune.</Text>
              ) : (
                <Text style={s.status}>Tap the map where the greenhouse is.</Text>
              )}

              <TouchableOpacity
                style={[s.primary, !picked && s.primaryOff]}
                disabled={!picked}
                onPress={() => picked && onPick({ latitude: picked.lat, longitude: picked.lon })}
                accessibilityRole="button"
                accessibilityState={{ disabled: !picked }}>
                <Text style={s.primaryTxt}>Use this location</Text>
              </TouchableOpacity>

              <TouchableOpacity onPress={() => setManual({ lat: '', lon: '' })}>
                <Text style={s.link} numberOfLines={1} maxFontSizeMultiplier={1.15}>
                  Enter coordinates instead
                </Text>
              </TouchableOpacity>
            </View>
          </>
        )}
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  wrap:     { flex: 1, backgroundColor: COLORS.bg },
  head:     { flexDirection: 'row', alignItems: 'center', gap: SPACE.md,
              paddingHorizontal: SPACE.lg, paddingTop: SPACE.xl + SPACE.md, paddingBottom: SPACE.md },
  headBtn:  { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center',
              backgroundColor: COLORS.bgCard },
  title:    { color: COLORS.text, fontSize: FONT.lg, fontWeight: '800' },
  sub:      { color: COLORS.textTertiary, fontSize: FONT.xs, marginTop: 1 },

  searchRow:{ flexDirection: 'row', alignItems: 'center', gap: SPACE.sm, marginHorizontal: SPACE.lg,
              backgroundColor: COLORS.bgCard, borderRadius: RADIUS.md, paddingHorizontal: SPACE.md,
              borderWidth: 1, borderColor: COLORS.border },
  search:   { flex: 1, color: COLORS.text, fontSize: FONT.sm, paddingVertical: SPACE.md },
  searchBtn:{ paddingHorizontal: SPACE.md, paddingVertical: SPACE.sm },
  searchBtnTxt: { color: COLORS.primary, fontSize: FONT.sm, fontWeight: '800' },

  overlay:  { position: 'absolute', top: SPACE.sm, left: SPACE.sm, right: SPACE.sm, zIndex: 5,
              flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between' },
  segment:  { flexDirection: 'row', backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm,
              padding: 3, gap: 2, ...SHADOW.sm },
  segBtn:   { paddingHorizontal: SPACE.md, paddingVertical: SPACE.xs + 2, borderRadius: RADIUS.sm - 2 },
  segBtnOn: { backgroundColor: COLORS.primary },
  segTxt:   { color: COLORS.textSecondary, fontSize: FONT.xs, fontWeight: '700' },
  segTxtOn: { color: '#FFF' },
  gpsBtn:   { width: 40, height: 40, borderRadius: 20, backgroundColor: COLORS.bgCard,
              alignItems: 'center', justifyContent: 'center', ...SHADOW.sm },
  web:      { flex: 1, backgroundColor: 'transparent' },
  mapWrap:  { flex: 1, margin: SPACE.lg, borderRadius: RADIUS.md, overflow: 'hidden',
              borderWidth: 1, borderColor: COLORS.border, ...SHADOW.sm },

  foot:     { paddingHorizontal: SPACE.lg, paddingBottom: SPACE.xl, gap: SPACE.md, alignItems: 'center' },
  statusRow:{ flexDirection: 'row', alignItems: 'center', gap: SPACE.sm },
  status:   { color: COLORS.textSecondary, fontSize: FONT.xs, textAlign: 'center', lineHeight: 16 },

  primary:  { alignSelf: 'stretch', alignItems: 'center', justifyContent: 'center',
              paddingVertical: SPACE.md + 2, borderRadius: RADIUS.md, backgroundColor: COLORS.primary },
  primaryOff:{ backgroundColor: COLORS.bgCardAlt },
  primaryTxt:{ color: '#FFF', fontSize: FONT.sm, fontWeight: '800' },
  link:     { color: COLORS.textTertiary, fontSize: FONT.xs, textDecorationLine: 'underline' },

  manualWrap:{ padding: SPACE.lg, gap: SPACE.md },
  manualHint:{ color: COLORS.textTertiary, fontSize: FONT.xs, lineHeight: 16 },
  row:      { flexDirection: 'row', gap: SPACE.md },
  fieldLabel:{ color: COLORS.textTertiary, fontSize: FONT.xs, fontWeight: '700', marginBottom: 4 },
  input:    { backgroundColor: COLORS.bgCard, borderRadius: RADIUS.sm, borderWidth: 1,
              borderColor: COLORS.border, paddingHorizontal: SPACE.md, paddingVertical: SPACE.sm,
              color: COLORS.text, fontSize: FONT.md },
  ghost:    { flex: 1, alignItems: 'center', justifyContent: 'center', paddingVertical: SPACE.md,
              borderRadius: RADIUS.md, borderWidth: 1, borderColor: COLORS.border },
  ghostTxt: { color: COLORS.textSecondary, fontSize: FONT.sm, fontWeight: '700' },
});
