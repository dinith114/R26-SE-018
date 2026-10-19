/**
 * The page inside the location picker's WebView: a Leaflet map with the pin
 * FIXED in the middle of the screen. The farmer moves the map under the pin,
 * and whatever is under its point is the farm. Nothing small has to be found
 * and dragged with a finger, which is what made the old picker hard to use.
 *
 * Plain JavaScript with no imports, so the page can be opened in a desktop
 * browser and tested without a phone.
 *
 * It tells React Native what happened through window.ReactNativeWebView:
 *   { type: 'ready' }                  the map exists
 *   { type: 'tilesok' }                imagery arrived
 *   { type: 'fail', why }              the map could not start
 *   { type: 'view', lat, lon, zoom, armed }
 *        after every move, however it was moved. `armed` stays false until
 *        the farmer, a search result or the GPS has put the pin somewhere, so
 *        the opening view of all of Sri Lanka is never taken as an answer.
 *   { type: 'gps', lat, lon, accuracy } / { type: 'gpsfail', code }
 *
 * React Native drives it with window.goTo(lat, lon, zoom), window.zoomOnPin(),
 * window.setLayer('sat' | 'street') and window.locateMe().
 */

/* `lat`/`lon` are ALWAYS real numbers: they centre the map. Passing null to
   mean "nothing chosen yet" made Leaflet throw `Invalid LatLng object` and the
   map died before drawing, in exactly the case that matters - a farm whose
   location was never set. `armed` carries "nothing chosen" instead. */
export const mapHtml = ({ lat, lon, zoom, armed, pinColor = '#047857' }) => `<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  html,body,#map{height:100%;margin:0;padding:0;background:#e8ebe5}
  .err{position:absolute;top:50%;left:0;right:0;transform:translateY(-50%);z-index:2000;
       text-align:center;font:14px -apple-system,Roboto,sans-serif;color:#6A645E;padding:24px}
  /* The pin's point sits exactly on the centre of the map. The SVG is 36x48
     with its tip at (18,46), hence the margins. */
  #pin{position:absolute;left:50%;top:50%;width:36px;height:48px;margin:-46px 0 0 -18px;
       z-index:1000;pointer-events:none;transition:transform .15s ease-out}
  .moving #pin{transform:translateY(-10px)}
  #dot{position:absolute;left:50%;top:50%;width:8px;height:4px;margin:-2px 0 0 -4px;
       border-radius:50%;background:rgba(0,0,0,.45);z-index:999;pointer-events:none}
  /* Leaflet's zoom buttons are sized for a mouse. */
  .leaflet-touch .leaflet-bar a{width:44px;height:44px;line-height:44px;font-size:22px}
</style>
</head><body>
<div id="map"></div>
<div id="dot"></div>
<svg id="pin" viewBox="0 0 36 48" aria-hidden="true">
  <path d="M18 2C9.7 2 3 8.7 3 17c0 11.2 15 29 15 29s15-17.8 15-29C33 8.7 26.3 2 18 2z"
        fill="${pinColor}" stroke="#fff" stroke-width="2.5"/>
  <circle cx="18" cy="17" r="5.5" fill="#fff"/>
</svg>
<div class="err" id="err" style="display:none">
  The map could not load.<br>Check the internet connection, or type the coordinates instead.
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
      var map = L.map('map', { zoomControl: false, maxZoom: 18 }).setView([${lat}, ${lon}], ${zoom});
      L.control.zoom({ position: 'bottomright' }).addTo(map);

      /* Esri, not OpenStreetMap's own tiles: OSM's volunteer servers forbid app
         use and answered this picker with HTTP 418 "Access blocked". Esri serves
         these free with attribution, no key and no billing account.
         Satellite is how a farmer recognises their own roof; the street map is
         how they check they are in the right village. */
      var esri = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
      var sat = L.tileLayer(esri + 'World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 18, attribution: 'Imagery (c) Esri' });
      var labels = L.tileLayer(esri + 'Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 18, pane: 'overlayPane' });
      var street = L.tileLayer(esri + 'World_Street_Map/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 18, attribution: '(c) Esri' });

      sat.addTo(map); labels.addTo(map);
      window.setLayer = function (which) {
        if (which === 'sat') { map.removeLayer(street); sat.addTo(map); labels.addTo(map); }
        else { map.removeLayer(sat); map.removeLayer(labels); street.addTo(map); }
      };

      /* If a provider ever blocks us the way OSM did, fall back rather than
         show a blank map. Counted: one failed tile at the edge of the world is
         normal and must not trigger a switch. */
      var tileFails = 0, swapped = false, anyOk = false;
      sat.on('tileerror', function () {
        tileFails++;
        if (tileFails >= 4 && !swapped && !anyOk) {
          swapped = true;
          map.removeLayer(sat); map.removeLayer(labels);
          L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
            { maxZoom: 18, attribution: '(c) OpenStreetMap, (c) CARTO' }).addTo(map);
          post({ type: 'tilesok' });
        }
      });
      sat.on('load', function () { anyOk = true; post({ type: 'tilesok' }); });
      street.on('load', function () { anyOk = true; post({ type: 'tilesok' }); });

      var armed = ${armed ? 'true' : 'false'};
      var report = function () {
        var c = map.getCenter();
        post({ type: 'view', lat: c.lat, lon: c.lng, zoom: map.getZoom(), armed: armed });
      };
      map.on('dragstart', function () { armed = true; });
      map.on('movestart', function () { document.body.classList.add('moving'); });
      map.on('moveend', function () { document.body.classList.remove('moving'); report(); });
      // A tap slides that spot under the pin.
      map.on('click', function (e) { armed = true; map.panTo(e.latlng); });

      window.goTo = function (la, lo, z) { armed = true; map.setView([la, lo], z); };
      window.zoomOnPin = function () { map.setZoom(Math.min(map.getZoom() + 3, 17)); };

      /* Where the phone is. A farmer setting this up is often standing at the
         greenhouse, and then this is the whole job: no typing, no searching. */
      window.locateMe = function () {
        if (!navigator.geolocation) { post({ type: 'gpsfail', code: 0 }); return; }
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            var la = pos.coords.latitude, lo = pos.coords.longitude;
            armed = true;
            map.setView([la, lo], 17);
            post({ type: 'gps', lat: la, lon: lo, accuracy: pos.coords.accuracy });
          },
          function (err) { post({ type: 'gpsfail', code: err && err.code || 0 }); },
          { enableHighAccuracy: true, timeout: 20000, maximumAge: 60000 }
        );
      };

      post({ type: 'ready' });
      report();
    }
  } catch (e) {
    document.getElementById('err').style.display = 'block';
    post({ type: 'fail', why: String(e && e.message || e) });
  }
  window.onerror = function (m) { post({ type: 'fail', why: String(m) }); };
</script>
</body></html>`;
