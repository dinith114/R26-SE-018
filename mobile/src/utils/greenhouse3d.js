/**
 * greenhouse3d.js — Shared realistic greenhouse 3D scene builder (Three.js in WebView).
 *
 * Generates a self-contained HTML page that renders a to-scale greenhouse:
 *   • Soil floor + 1 m measurement grid
 *   • Semi-transparent glass walls + a real pitched (gable) roof
 *   • Green structural frame lines
 *   • Windows + a door drawn from the model data
 *   • Dimension annotations (W / L / H) labelled in metres
 *   • Potted orchid plants laid out in rows
 *   • Caller-supplied markers (trial sensors / placement recommendations)
 *   • Optional irrigation pipeline
 *
 * All runtime logic uses `var` plain JS — only ${payload} is interpolated at build time.
 *
 * @param {Object}  opts
 * @param {Object}  opts.model     { width, length, height, windows[] }
 * @param {Array}   opts.plants    [{ x, y }]  (metres, origin at corner)
 * @param {Array}   opts.markers   [{ x, y, color, label, pole, coverage, cross, ground }]
 * @param {Object}  opts.pipeline  { pipe_segments:[{from:{x,y},to:{x,y}}] } | null
 * @param {Array}   opts.legend    [{ color, text }]
 * @param {Boolean} opts.showDimensions
 */
export function buildGreenhouseHTML({
  model,
  plants = [],
  markers = [],
  pipeline = null,
  legend = [],
  showDimensions = true,
}) {
  const payload = JSON.stringify({
    model: {
      width:  Number(model?.width)  || 10,
      length: Number(model?.length) || 20,
      height: Number(model?.height) || 3,
      windows: Array.isArray(model?.windows) ? model.windows : [],
    },
    plants,
    markers,
    pipeline,
    showDimensions,
  });

  const legendHtml = legend
    .map(
      (l) =>
        `<div class="li"><span class="dot" style="background:${l.color}"></span><span class="lt">${l.text}</span></div>`
    )
    .join('');

  return `<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:100%;height:100%;overflow:hidden;background:#0d1220}
#legend{position:absolute;top:10px;left:10px;background:rgba(0,0,0,0.55);border-radius:8px;padding:8px 10px;pointer-events:none}
.li{display:flex;align-items:center;gap:6px;margin-bottom:3px}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block}
.lt{color:rgba(255,255,255,0.8);font-size:10px;font-family:sans-serif}
#hint{position:absolute;bottom:8px;left:0;right:0;text-align:center;color:rgba(255,255,255,0.32);font-size:10px;font-family:sans-serif;pointer-events:none}
</style></head><body>
${legend.length ? `<div id="legend">${legendHtml}</div>` : ''}
<div id="hint">Drag to rotate · Pinch to zoom · Two-finger pan</div>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
var D = ${payload};
var M = D.model, PLANTS = D.plants || [], MARKERS = D.markers || [], PIPE = D.pipeline, SHOWDIM = D.showDimensions;

var W = M.width, L = M.length, WALL_H = M.height;
var ROOF_RISE = Math.max(0.6, W * 0.22);     // roof peak above the eave
var PEAK = WALL_H + ROOF_RISE;
var MAXD = Math.max(W, L);
var LABEL_SCALE = Math.max(0.5, MAXD * 0.05);

function fx(x){ return x - W / 2; }          // data-x  -> world-x
function fz(y){ return y - L / 2; }          // data-y  -> world-z

// ── Renderer / scene / camera ───────────────────────────────────────────────
var renderer = new THREE.WebGLRenderer({ antialias:true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement);

var scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d1220);
scene.fog = new THREE.Fog(0x0d1220, MAXD * 3, MAXD * 8);

var camera = new THREE.PerspectiveCamera(48, window.innerWidth/window.innerHeight, 0.1, MAXD * 14);
camera.position.set(W * 0.85, PEAK + MAXD * 0.7, L * 0.98);

var controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.dampingFactor = 0.08;
controls.minDistance = 1.5; controls.maxDistance = MAXD * 6;
controls.target.set(0, WALL_H * 0.4, 0);
controls.update();

// ── Lights ──────────────────────────────────────────────────────────────────
scene.add(new THREE.HemisphereLight(0xdfeaff, 0x2a3326, 0.75));
scene.add(new THREE.AmbientLight(0xffffff, 0.25));
var sun = new THREE.DirectionalLight(0xffffff, 0.75);
sun.position.set(W, PEAK * 3, L); scene.add(sun);

// ── Outside ground ──────────────────────────────────────────────────────────
var ground = new THREE.Mesh(
  new THREE.PlaneGeometry(MAXD * 5, MAXD * 5),
  new THREE.MeshLambertMaterial({ color:0x1c2a1c }));
ground.rotation.x = -Math.PI/2; ground.position.y = -0.02; scene.add(ground);

// ── Inside soil floor ───────────────────────────────────────────────────────
var floor = new THREE.Mesh(
  new THREE.PlaneGeometry(W, L),
  new THREE.MeshLambertMaterial({ color:0x4a3d2c }));
floor.rotation.x = -Math.PI/2; scene.add(floor);

// ── 1 m measurement grid on the floor ───────────────────────────────────────
var step = MAXD > 40 ? 5 : (MAXD > 18 ? 2 : 1);
var gpts = [];
for (var gx = 0; gx <= W + 0.001; gx += step) {
  gpts.push(new THREE.Vector3(fx(gx), 0.012, fz(0)), new THREE.Vector3(fx(gx), 0.012, fz(L)));
}
for (var gy = 0; gy <= L + 0.001; gy += step) {
  gpts.push(new THREE.Vector3(fx(0), 0.012, fz(gy)), new THREE.Vector3(fx(W), 0.012, fz(gy)));
}
var grid = new THREE.LineSegments(
  new THREE.BufferGeometry().setFromPoints(gpts),
  new THREE.LineBasicMaterial({ color:0x5b7da6, transparent:true, opacity:0.35 }));
scene.add(grid);

// ── Glass walls + gable end walls ───────────────────────────────────────────
var glassMat = new THREE.MeshLambertMaterial({ color:0xa9d6e8, transparent:true, opacity:0.16, side:THREE.DoubleSide });

var leftWall = new THREE.Mesh(new THREE.PlaneGeometry(L, WALL_H), glassMat);
leftWall.rotation.y = Math.PI/2; leftWall.position.set(-W/2, WALL_H/2, 0); scene.add(leftWall);
var rightWall = new THREE.Mesh(new THREE.PlaneGeometry(L, WALL_H), glassMat);
rightWall.rotation.y = -Math.PI/2; rightWall.position.set(W/2, WALL_H/2, 0); scene.add(rightWall);

// Gable (pentagon) end walls: rectangle + triangle peak
var gable = new THREE.Shape();
gable.moveTo(-W/2, 0); gable.lineTo(W/2, 0); gable.lineTo(W/2, WALL_H);
gable.lineTo(0, PEAK);  gable.lineTo(-W/2, WALL_H); gable.lineTo(-W/2, 0);
var gableGeo = new THREE.ShapeGeometry(gable);
var frontWall = new THREE.Mesh(gableGeo, glassMat); frontWall.position.set(0, 0, L/2); scene.add(frontWall);
var backWall  = new THREE.Mesh(gableGeo, glassMat); backWall.position.set(0, 0, -L/2); scene.add(backWall);

// ── Pitched roof (two slopes) ───────────────────────────────────────────────
function roofSlope(eaveX) {
  var sign = eaveX < 0 ? -1 : 1;
  var v = new Float32Array([
    sign*W/2, WALL_H, -L/2,   sign*W/2, WALL_H, L/2,   0, PEAK, L/2,
    sign*W/2, WALL_H, -L/2,   0, PEAK, L/2,            0, PEAK, -L/2,
  ]);
  var g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(v, 3));
  g.computeVertexNormals();
  return new THREE.Mesh(g, new THREE.MeshLambertMaterial({ color:0xc4e4f2, transparent:true, opacity:0.22, side:THREE.DoubleSide }));
}
scene.add(roofSlope(-1));
scene.add(roofSlope(1));

// ── Structural frame lines ──────────────────────────────────────────────────
var fp = [];
function edge(ax,ay,az,bx,by,bz){ fp.push(new THREE.Vector3(ax,ay,az), new THREE.Vector3(bx,by,bz)); }
var hw = W/2, hl = L/2;
// base + eave rectangles
[[0],[WALL_H]].forEach(function(h){ var y=h[0];
  edge(-hw,y,-hl, hw,y,-hl); edge(hw,y,-hl, hw,y,hl); edge(hw,y,hl, -hw,y,hl); edge(-hw,y,hl, -hw,y,-hl);
});
// corner posts
edge(-hw,0,-hl,-hw,WALL_H,-hl); edge(hw,0,-hl,hw,WALL_H,-hl);
edge(hw,0,hl,hw,WALL_H,hl);     edge(-hw,0,hl,-hw,WALL_H,hl);
// ridge
edge(0,PEAK,-hl, 0,PEAK,hl);
// gable rafters both ends
[-hl,hl].forEach(function(z){ edge(-hw,WALL_H,z, 0,PEAK,z); edge(0,PEAK,z, hw,WALL_H,z); });
var frame = new THREE.LineSegments(
  new THREE.BufferGeometry().setFromPoints(fp),
  new THREE.LineBasicMaterial({ color:0x3f7d5c }));
scene.add(frame);

// ── Windows ─────────────────────────────────────────────────────────────────
var winMat = new THREE.MeshLambertMaterial({ color:0x8fe0ff, transparent:true, opacity:0.5, side:THREE.DoubleSide });
var winH = Math.min(1.2, WALL_H * 0.5);
var winCY = WALL_H * 0.5;
for (var wi = 0; wi < M.windows.length; wi++) {
  var win = M.windows[wi];
  var wall = (win.wall || 'south');
  var pos  = (win.position != null ? win.position : 0.5);
  var wWid = (win.width || 1.5);
  var panel;
  if (wall === 'south' || wall === 'north') {
    panel = new THREE.Mesh(new THREE.PlaneGeometry(wWid, winH), winMat);
    var cx = -W/2 + pos * W;
    var z  = wall === 'south' ? L/2 : -L/2;
    panel.position.set(cx, winCY, z + (wall === 'south' ? 0.02 : -0.02));
  } else {
    panel = new THREE.Mesh(new THREE.PlaneGeometry(wWid, winH), winMat);
    panel.rotation.y = Math.PI/2;
    var cz = -L/2 + pos * L;
    var x  = wall === 'east' ? W/2 : -W/2;
    panel.position.set(x + (wall === 'east' ? 0.02 : -0.02), winCY, cz);
  }
  scene.add(panel);
}

// ── Door (south wall, centre) ───────────────────────────────────────────────
var doorH = Math.min(2.1, WALL_H * 0.85);
var door = new THREE.Mesh(new THREE.PlaneGeometry(Math.min(1.0, W*0.12), doorH),
  new THREE.MeshLambertMaterial({ color:0x6d4c33, side:THREE.DoubleSide }));
door.position.set(0, doorH/2, L/2 + 0.03); scene.add(door);

// ── Potted orchid plants ────────────────────────────────────────────────────
var detailed = PLANTS.length <= 150;
var POT_H = 0.14;
var POT_GEO = new THREE.CylinderGeometry(0.07, 0.05, POT_H, 8);
var POT_MAT = new THREE.MeshLambertMaterial({ color:0x8d5b3f });
var LEAF_GEO = new THREE.SphereGeometry(0.13, 8, 6);
var LEAF_MAT = new THREE.MeshLambertMaterial({ color:0x6fae3d });
var SPIKE_GEO = new THREE.CylinderGeometry(0.01, 0.01, 0.32, 5);
var SPIKE_MAT = new THREE.MeshLambertMaterial({ color:0x4c7a2e });
var FLOWER_GEO = new THREE.SphereGeometry(0.045, 6, 5);
var FLOWER_MAT = new THREE.MeshLambertMaterial({ color:0x9c4dcc });
for (var pi = 0; pi < PLANTS.length; pi++) {
  var px = fx(PLANTS[pi].x), pz = fz(PLANTS[pi].y);
  var pot = new THREE.Mesh(POT_GEO, POT_MAT); pot.position.set(px, POT_H/2, pz); scene.add(pot);
  var leaf = new THREE.Mesh(LEAF_GEO, LEAF_MAT);
  leaf.position.set(px, POT_H + 0.09, pz); leaf.scale.set(1, 0.65, 1); scene.add(leaf);
  if (detailed) {
    var spike = new THREE.Mesh(SPIKE_GEO, SPIKE_MAT); spike.position.set(px, POT_H + 0.26, pz); scene.add(spike);
    var fl1 = new THREE.Mesh(FLOWER_GEO, FLOWER_MAT); fl1.position.set(px + 0.04, POT_H + 0.42, pz); scene.add(fl1);
    var fl2 = new THREE.Mesh(FLOWER_GEO, FLOWER_MAT); fl2.position.set(px - 0.03, POT_H + 0.36, pz + 0.03); scene.add(fl2);
  }
}

// ── Label sprite helper ─────────────────────────────────────────────────────
function makeLabel(text, bg, fg) {
  var c = document.createElement('canvas');
  var ctx = c.getContext('2d');
  var fs = 48; ctx.font = 'bold ' + fs + 'px sans-serif';
  var tw = ctx.measureText(text).width;
  c.width = tw + 36; c.height = fs + 26;
  ctx = c.getContext('2d'); ctx.font = 'bold ' + fs + 'px sans-serif';
  ctx.fillStyle = bg;
  var r = 12, x0 = 3, y0 = 3, w0 = c.width - 6, h0 = c.height - 6;
  ctx.beginPath();
  ctx.moveTo(x0+r,y0); ctx.lineTo(x0+w0-r,y0); ctx.quadraticCurveTo(x0+w0,y0,x0+w0,y0+r);
  ctx.lineTo(x0+w0,y0+h0-r); ctx.quadraticCurveTo(x0+w0,y0+h0,x0+w0-r,y0+h0);
  ctx.lineTo(x0+r,y0+h0); ctx.quadraticCurveTo(x0,y0+h0,x0,y0+h0-r);
  ctx.lineTo(x0,y0+r); ctx.quadraticCurveTo(x0,y0,x0+r,y0); ctx.fill();
  ctx.fillStyle = fg; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(text, c.width/2, c.height/2);
  var spr = new THREE.Sprite(new THREE.SpriteMaterial({ map:new THREE.CanvasTexture(c), depthTest:false, transparent:true }));
  spr.scale.set(LABEL_SCALE * c.width / c.height, LABEL_SCALE, 1);
  return spr;
}

// ── Dimension annotations ───────────────────────────────────────────────────
if (SHOWDIM) {
  var mg = Math.max(0.7, MAXD * 0.05);
  var dimMat = new THREE.LineBasicMaterial({ color:0xffd24a });
  function dimLine(pts){ scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), dimMat)); }

  // Width (front edge, along x)
  dimLine([new THREE.Vector3(-hw,0.02,hl+mg), new THREE.Vector3(hw,0.02,hl+mg)]);
  dimLine([new THREE.Vector3(-hw,0.02,hl+mg), new THREE.Vector3(-hw,0.4,hl+mg)]);
  dimLine([new THREE.Vector3(hw,0.02,hl+mg),  new THREE.Vector3(hw,0.4,hl+mg)]);
  var wLab = makeLabel('W = ' + W.toFixed(1) + ' m', '#1b2233', '#ffd24a');
  wLab.position.set(0, 0.5, hl + mg); scene.add(wLab);

  // Length (right edge, along z)
  dimLine([new THREE.Vector3(hw+mg,0.02,-hl), new THREE.Vector3(hw+mg,0.02,hl)]);
  dimLine([new THREE.Vector3(hw+mg,0.02,-hl), new THREE.Vector3(hw+mg,0.4,-hl)]);
  dimLine([new THREE.Vector3(hw+mg,0.02,hl),  new THREE.Vector3(hw+mg,0.4,hl)]);
  var lLab = makeLabel('L = ' + L.toFixed(1) + ' m', '#1b2233', '#ffd24a');
  lLab.position.set(hw + mg, 0.5, 0); scene.add(lLab);

  // Height (front-left corner, vertical)
  dimLine([new THREE.Vector3(-hw-mg,0,hl), new THREE.Vector3(-hw-mg,WALL_H,hl)]);
  var hLab = makeLabel('H = ' + WALL_H.toFixed(1) + ' m', '#1b2233', '#ffd24a');
  hLab.position.set(-hw - mg, WALL_H/2, hl); scene.add(hLab);
}

// ── Markers (sensors / recommendations) ─────────────────────────────────────
var markerH = Math.min(1.2, WALL_H * 0.55);
for (var mi = 0; mi < MARKERS.length; mi++) {
  var m = MARKERS[mi];
  var mx = fx(m.x), mz = fz(m.y), col = new THREE.Color(m.color || '#888');

  if (m.pole) {
    var pole = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, markerH, 8),
      new THREE.MeshLambertMaterial({ color:0x9aa7b0 }));
    pole.position.set(mx, markerH/2, mz); scene.add(pole);
    var bulb = new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 12),
      new THREE.MeshLambertMaterial({ color:col }));
    bulb.position.set(mx, markerH + 0.22, mz); scene.add(bulb);
  }
  if (m.coverage && m.coverage > 0) {
    var dome = new THREE.Mesh(new THREE.SphereGeometry(m.coverage, 18, 12),
      new THREE.MeshBasicMaterial({ color:col, transparent:true, opacity:0.07, side:THREE.DoubleSide }));
    dome.position.set(mx, 0.4, mz); scene.add(dome);
    var cring = new THREE.Mesh(new THREE.RingGeometry(m.coverage - 0.15, m.coverage, 40),
      new THREE.MeshBasicMaterial({ color:col, transparent:true, opacity:0.25, side:THREE.DoubleSide }));
    cring.rotation.x = -Math.PI/2; cring.position.set(mx, 0.02, mz); scene.add(cring);
  }
  if (m.cross) {
    var topY = markerH + 0.22;
    var x1 = new THREE.Mesh(new THREE.BoxGeometry(0.62,0.06,0.06), new THREE.MeshLambertMaterial({ color:0xff3333 }));
    x1.rotation.y = Math.PI/4; x1.position.set(mx, topY, mz); scene.add(x1);
    var x2 = new THREE.Mesh(new THREE.BoxGeometry(0.62,0.06,0.06), new THREE.MeshLambertMaterial({ color:0xff3333 }));
    x2.rotation.y = -Math.PI/4; x2.position.set(mx, topY, mz); scene.add(x2);
  }
  if (m.ground) {
    var gring = new THREE.Mesh(new THREE.RingGeometry(0.4, 0.7, 32),
      new THREE.MeshBasicMaterial({ color:col, transparent:true, opacity:0.85, side:THREE.DoubleSide }));
    gring.rotation.x = -Math.PI/2; gring.position.set(mx, 0.02, mz); scene.add(gring);
    var pl1 = new THREE.Mesh(new THREE.BoxGeometry(0.55,0.09,0.09), new THREE.MeshLambertMaterial({ color:col }));
    pl1.position.set(mx, 0.12, mz); scene.add(pl1);
    var pl2 = new THREE.Mesh(new THREE.BoxGeometry(0.09,0.09,0.55), new THREE.MeshLambertMaterial({ color:col }));
    pl2.position.set(mx, 0.12, mz); scene.add(pl2);
  }
  if (m.label) {
    var lab = makeLabel(m.label, m.color || '#444', '#ffffff');
    lab.position.set(mx, (m.pole ? markerH + 0.95 : 0.7), mz); scene.add(lab);
  }
}

// ── Irrigation pipeline ─────────────────────────────────────────────────────
if (PIPE && PIPE.pipe_segments) {
  var pipeMat = new THREE.LineBasicMaterial({ color:0x2196F3 });
  var nodeMat = new THREE.MeshLambertMaterial({ color:0x1565C0 });
  for (var si = 0; si < PIPE.pipe_segments.length; si++) {
    var seg = PIPE.pipe_segments[si];
    var pp = [ new THREE.Vector3(fx(seg.from.x),0.06,fz(seg.from.y)),
               new THREE.Vector3(fx(seg.to.x),0.06,fz(seg.to.y)) ];
    scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pp), pipeMat));
    var nn1 = new THREE.Mesh(new THREE.SphereGeometry(0.14,8,6), nodeMat);
    nn1.position.set(fx(seg.from.x),0.14,fz(seg.from.y)); scene.add(nn1);
    var nn2 = new THREE.Mesh(new THREE.SphereGeometry(0.14,8,6), nodeMat);
    nn2.position.set(fx(seg.to.x),0.14,fz(seg.to.y)); scene.add(nn2);
  }
}

// ── Compass (N marker) ──────────────────────────────────────────────────────
var nLab = makeLabel('N', '#2a3550', '#ffffff');
nLab.scale.multiplyScalar(0.7);
nLab.position.set(0, 0.3, -L/2 - Math.max(0.7, MAXD*0.05)); scene.add(nLab);

// ── Loop ────────────────────────────────────────────────────────────────────
window.addEventListener('resize', function(){
  camera.aspect = window.innerWidth/window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
function animate(){ requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }
animate();
</script></body></html>`;
}
