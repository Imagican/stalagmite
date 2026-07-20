#!/usr/bin/env python3
"""
dfam_report.py - interactive HTML 3D report for stalagmite audits.

write_report() emits a single self-contained HTML file: a three.js
viewer (z-up, custom orbit) showing the part with defect faces coloured
by severity, beside a clickable defect list -- selecting a defect flies
the camera to it and shows the Tier-3 repair suggestions. Open in any
browser; share as a file. three.js is vendored inline (see
vendor_three.py) so reports work fully offline.
"""
import json
import numpy as np
from shapely.geometry import Point

SEV_IDX = {"fail": 1, "judge": 2, "tolerable": 3, "surface": 4}
SEV_LABEL = {"fail": "will not print", "judge": "printable bridge - judge",
             "tolerable": "within ledge allowance", "surface": "surface lint"}


def face_severity_index(mesh, violations, dz, halo=0.4):
    """Per-face severity palette index (0 = ok). Worst severity wins."""
    from shapely.prepared import prep
    centers = mesh.triangles_center
    cz = centers[:, 2]
    idx = np.zeros(len(mesh.faces), dtype=np.uint8)
    order = sorted((v for v in violations if v.geom is not None
                    and not v.geom.is_empty),
                   key=lambda v: -SEV_IDX.get(v.severity or "fail", 1))
    for v in order:
        code = SEV_IDX.get(v.severity or "fail", 1)
        zone = prep(v.geom.buffer(halo))
        for i in np.where(np.abs(cz - v.z) <= dz)[0]:
            if zone.contains(Point(centers[i][0], centers[i][1])):
                idx[i] = code
    return idx


def _rings(geom, tol=0.08):
    """Flatten a shapely (Multi)Polygon to a list of [x,y] rings
    (exteriors + holes), lightly simplified for a compact payload."""
    if geom is None or geom.is_empty:
        return []
    try:
        geom = geom.simplify(tol, preserve_topology=True)
    except Exception:
        pass
    polys = geom.geoms if hasattr(geom, "geoms") else [geom]
    rings = []
    for p in polys:
        if p.is_empty or not hasattr(p, "exterior"):
            continue
        for ring in [p.exterior, *p.interiors]:
            pts = [[round(x, 2), round(y, 2)] for x, y in ring.coords]
            if len(pts) >= 3:
                rings.append(pts)
    return rings


def _transition_diagram(mesh, feature, dz, angle):
    """Cross-section evidence for one defect: the supporting slice below,
    the 45-deg allowed envelope grown from it, this slice, and the
    material poking past the envelope. Renders in the report as a 2-D
    'here's why, and here's the allowed shape' panel."""
    from dfam_audit import slice_region, GROW_SLOP
    try:
        layer = max(feature["layers"], key=lambda v: v.area)
        zc = layer.z
        cur = slice_region(mesh, zc)
        prev = slice_region(mesh, zc - dz)
        if cur is None or cur.is_empty:
            return None
        grow = dz * np.tan(np.radians(angle)) + GROW_SLOP
        env = prev.buffer(grow) if (prev is not None and not prev.is_empty) \
            else cur.buffer(0).difference(cur)   # empty
        bad = cur.difference(env) if not env.is_empty else cur
        ref = cur.union(env) if not env.is_empty else cur
        b = ref.bounds
        return {
            "z": round(zc, 1), "zprev": round(zc - dz, 1),
            "prev": _rings(prev), "cur": _rings(cur),
            "env": _rings(env), "bad": _rings(bad),
            "bbox": [round(b[0], 1), round(b[1], 1),
                     round(b[2], 1), round(b[3], 1)],
        }
    except Exception:
        return None


def _feature_payload(features, mesh=None, dz=0.4, angle=45.0):
    out = []
    for k, f in enumerate(features):
        g = f.get("geom")
        if g is not None and not g.is_empty:
            b = g.bounds
            cx, cy = g.centroid.x, g.centroid.y
            rad = max(b[2] - b[0], b[3] - b[1], f["zhi"] - f["zlo"], 2.0)
        else:
            v0 = f["layers"][0]
            cx, cy = v0.centroid
            rad = max(v0.span, 2.0)
        dims = ""
        if f["cls"] == "steep-growth":
            led = max((v.ledge or 0) for v in f["layers"])
            dims = f"ledge {led:.1f}mm"
        elif f["cls"] == "bridge":
            if f.get("roof_width"):
                dims = f"roofed width ~{f['roof_width']:.1f}mm"
        out.append({
            "id": k, "cls": f["cls"], "severity": f["severity"],
            "sevLabel": SEV_LABEL.get(f["severity"], f["severity"]),
            "zlo": round(f["zlo"], 1), "zhi": round(f["zhi"], 1),
            "layers": len(f["layers"]), "dims": dims,
            "center": [round(cx, 1), round(cy, 1),
                       round((f["zlo"] + f["zhi"]) / 2, 1)],
            "radius": round(rad / 2 + 1.5, 1),
            "repairs": f.get("repairs", []),
            "diagram": (_transition_diagram(mesh, f, dz, angle)
                        if mesh is not None else None),
        })
    return out


def render_report(mesh, violations, features, meta=None):
    """Build the self-contained report HTML and return it as a string."""
    meta = meta or {}
    dz = meta.get("dz", 0.4)
    fidx = face_severity_index(mesh, violations, dz)
    tri = mesh.triangles.reshape(-1, 3)          # 3 verts per face, soup
    pos = np.round(tri, 2).astype(float).flatten().tolist()
    data = {
        "positions": pos,
        "faceSev": fidx.tolist(),
        "bounds": [list(np.round(mesh.bounds[0], 1)),
                   list(np.round(mesh.bounds[1], 1))],
        "features": _feature_payload(features, mesh, dz,
                                     meta.get("angle", 45.0)),
        "meta": {
            "part": meta.get("part", "part"),
            "angle": meta.get("angle", 45.0),
            "dz": dz,
            "bed": meta.get("bed"),
            "zones": meta.get("zones", []),
            "passed": len(violations) == 0,
            "status": meta.get("status"),
            "profile": meta.get("profile"),
            "health": meta.get("health", []),
            "counts": {s: sum(1 for f in features if f["severity"] == s)
                       for s in ("fail", "judge", "tolerable")},
            "nviol": len(violations),
        },
    }
    from vendor_three import three_js
    return _TEMPLATE.replace("__THREE__", three_js()) \
                    .replace("__DATA__", json.dumps(data))


def write_report(mesh, violations, features, out_path, meta=None):
    """Emit the self-contained HTML report to a file. Returns the path."""
    html = render_report(mesh, violations, features, meta)
    with open(out_path, "w") as fh:
        fh.write(html)
    return out_path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>stalagmite report</title>
<script>__THREE__</script>
<style>
  :root{--bg:#14171c;--panel:#1c2129;--card:#232a34;--text:#e8eaed;
        --dim:#9aa4b2;--line:#2e3742;
        --fail:#dc1e1e;--judge:#f08c14;--tol:#e6c828;--ok:#3fb96a}
  *{box-sizing:border-box;margin:0}
  body{background:var(--bg);color:var(--text);
       font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif;
       display:flex;height:100vh;overflow:hidden}
  #panel{width:340px;min-width:300px;background:var(--panel);
         border-right:1px solid var(--line);overflow-y:auto;padding:18px}
  #view{flex:1;position:relative}
  canvas{display:block}
  h1{font-size:17px;letter-spacing:.3px}
  h1 span{color:var(--dim);font-weight:400}
  .sub{color:var(--dim);font-size:12px;margin:4px 0 14px}
  .stats{display:flex;gap:8px;margin-bottom:14px}
  .stat{flex:1;background:var(--card);border:1px solid var(--line);
        border-radius:8px;padding:8px 10px;text-align:center}
  .stat b{display:block;font-size:19px}
  .stat i{font-style:normal;font-size:11px;color:var(--dim)}
  .stat.fail b{color:var(--fail)} .stat.judge b{color:var(--judge)}
  .stat.tol b{color:var(--tol)}
  .pass{background:var(--card);border:1px solid var(--ok);color:var(--ok);
        border-radius:8px;padding:12px;text-align:center;font-weight:600}
  .statusbar{background:var(--card);border:1px solid var(--line);
        border-left-width:4px;border-radius:8px;padding:9px 12px;
        margin-bottom:10px}
  .statusbar b{font-size:13px;letter-spacing:.4px;display:block}
  .statusbar span{color:var(--dim);font-size:11.5px}
  .card{background:var(--card);border:1px solid var(--line);
        border-radius:8px;padding:10px 12px;margin-bottom:8px;
        cursor:pointer;transition:border-color .15s}
  .card:hover{border-color:#4a5462}
  .card.sel{border-color:#7a8798}
  .card .tag{display:inline-block;font-size:11px;font-weight:700;
             padding:1px 8px;border-radius:10px;margin-right:6px;color:#111}
  .tag.fail{background:var(--fail);color:#fff}
  .tag.judge{background:var(--judge)} .tag.tolerable{background:var(--tol)}
  .card .where{color:var(--dim);font-size:12px;margin-top:3px}
  .card ul{margin:8px 0 2px 16px;padding:0;font-size:12px;color:var(--dim);
           display:none}
  .card.sel ul{display:block}
  .card li{margin-bottom:4px}
  .legend{font-size:11px;color:var(--dim);margin-top:14px;
          border-top:1px solid var(--line);padding-top:10px}
  .dot{display:inline-block;width:9px;height:9px;border-radius:5px;
       margin:0 4px 0 10px}
  #hint{position:absolute;right:12px;bottom:10px;color:var(--dim);
        font-size:11px;background:rgba(20,23,28,.7);padding:4px 10px;
        border-radius:6px}
  #slice{position:absolute;left:14px;bottom:14px;width:280px;
         background:rgba(28,33,41,.95);border:1px solid var(--line);
         border-radius:9px;padding:11px 12px;display:none}
  #slice h4{margin:0 0 2px;font-size:12px}
  #slice .cap{color:var(--dim);font-size:10.5px;margin-bottom:7px}
  #slice svg{width:100%;height:170px;background:#0f1216;border-radius:6px}
  #slice .leg{font-size:10px;color:var(--dim);margin-top:7px;line-height:1.7}
  #slice .sw{display:inline-block;width:16px;height:0;vertical-align:middle;
         margin:0 5px 0 9px}
</style>
</head>
<body>
<div id="panel">
  <div style="display:flex;align-items:center;gap:10px">
    <svg width="44" height="44" viewBox="0 0 100 100" fill="none"
         aria-label="stalagmite logo">
      <ellipse cx="50" cy="86" rx="34" ry="7" stroke="#e8eaed"
               stroke-width="2.6"/>
      <ellipse cx="50" cy="86" rx="26" ry="4.6" stroke="#e8eaed"
               stroke-width="1.6" opacity=".6"/>
      <path d="M50 8 C48 14 46 20 43 27 C40 34 36 42 32 51
               C28 60 24 70 22 82 L78 82 C76 70 72 60 68 51
               C64 42 60 34 57 27 C54 20 52 14 50 8 Z"
            fill="#e8eaed"/>
      <path d="M34 46 Q50 52 66 46 M30 57 Q50 64 70 57 M26 69 Q50 77 74 69
               M39 35 Q50 39 61 35" stroke="#14171c" stroke-width="3.2"
            fill="none"/>
      <line x1="50" y1="10" x2="50" y2="84" stroke="#14171c"
            stroke-width="2.6"/>
      <circle cx="50" cy="22" r="3.4" fill="#14171c" stroke="#e8eaed"
              stroke-width="1.8"/>
      <circle cx="50" cy="50" r="3.4" fill="#14171c" stroke="#e8eaed"
              stroke-width="1.8"/>
      <circle cx="50" cy="80" r="3.8" fill="#14171c" stroke="#e8eaed"
              stroke-width="1.8"/>
    </svg>
    <h1>stalagmite <span>audit report</span></h1>
  </div>
  <div class="sub" id="sub"></div>
  <div id="stats"></div>
  <div id="defects"></div>
  <div class="legend">
    <b>Face colours</b><br>
    <span class="dot" style="background:var(--fail)"></span>fail
    <span class="dot" style="background:var(--judge)"></span>judged bridge
    <span class="dot" style="background:var(--tol)"></span>tolerable
    <span class="dot" style="background:#8b939e"></span>ok
    <div style="margin-top:8px">Click a defect to fly to it.
    Make stalagmites, not stalactites.</div>
  </div>
</div>
<div id="view"><div id="hint">drag rotate &middot; wheel zoom &middot; right-drag pan</div><div id="slice"></div></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const M = D.meta;
document.getElementById('sub').textContent =
  `${M.part} - ${M.angle} deg rule, ${M.dz}mm layers` +
  (M.profile ? ` - profile: ${M.profile}` : '') +
  (M.zones.length ? ` - ${M.zones.length} helix zone(s) excluded` : '');
if (M.health && M.health.length) {
  const h = document.createElement('div');
  h.style.cssText = 'color:#e0a24a;font-size:11px;margin:2px 0 12px';
  h.textContent = 'mesh health: ' + M.health.join('; ');
  document.getElementById('sub').after(h);
}

// ---- panel
const STATUS_INFO = {
  PASS:             {c:'#3fb96a', t:'every layer supported; no concerns.'},
  PASS_WITH_LIMITS: {c:'#e6c828', t:'prints as-is; only within-allowance ledges or surface notes.'},
  REVIEW:           {c:'#f08c14', t:'printable, but contains judged bridge(s) - eyeball first.'},
  FAIL:             {c:'#dc1e1e', t:'will NOT print as oriented; needs a fix or reorient.'},
};
const stats = document.getElementById('stats');
const st = M.status || (M.passed ? 'PASS' : 'FAIL');
const si = STATUS_INFO[st] || STATUS_INFO.FAIL;
let html = `<div class="statusbar" style="border-color:${si.c}">` +
  `<b style="color:${si.c}">${st.replace(/_/g,' ')}</b>` +
  `<span>${si.t}</span></div>`;
if (!M.passed) {
  html += '<div class="stats">' +
    `<div class="stat fail"><b>${M.counts.fail}</b><i>fail</i></div>` +
    `<div class="stat judge"><b>${M.counts.judge}</b><i>judge</i></div>` +
    `<div class="stat tol"><b>${M.counts.tolerable}</b><i>tolerable</i></div>` +
    '</div>';
}
stats.innerHTML = html;
const list = document.getElementById('defects');
D.features.forEach(f => {
  const c = document.createElement('div');
  c.className = 'card'; c.id = 'card' + f.id;
  c.innerHTML =
    `<span class="tag ${f.severity}">${f.severity}</span><b>${f.cls}</b>` +
    `<div class="where">z ${f.zlo}-${f.zhi} - ${f.layers} layer(s)` +
    (f.dims ? ` - ${f.dims}` : '') + ` - ${f.sevLabel}</div>` +
    (f.repairs.length ?
      '<ul>' + f.repairs.map(r => `<li>${r}</li>`).join('') + '</ul>' : '');
  c.onclick = () => select(f);
  list.appendChild(c);
});

// ---- three.js scene (z-up)
const view = document.getElementById('view');
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setPixelRatio(window.devicePixelRatio);
view.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x14171c);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
camera.up.set(0, 0, 1);

const PAL = [[0.55,0.58,0.62],[0.86,0.12,0.12],[0.94,0.55,0.08],
             [0.90,0.78,0.16],[0.62,0.66,0.72]];
const pos = new Float32Array(D.positions);
const col = new Float32Array(pos.length);
for (let i = 0; i < D.faceSev.length; i++) {
  const c = PAL[D.faceSev[i]];
  for (let v = 0; v < 3; v++) {
    col[9*i + 3*v] = c[0]; col[9*i + 3*v + 1] = c[1]; col[9*i + 3*v + 2] = c[2];
  }
}
const geo = new THREE.BufferGeometry();
geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
geo.computeVertexNormals();
const mat = new THREE.MeshStandardMaterial({vertexColors: true,
  flatShading: true, metalness: 0.05, roughness: 0.85});
scene.add(new THREE.Mesh(geo, mat));

scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const key = new THREE.DirectionalLight(0xffffff, 0.85);
key.position.set(1, -1.2, 1.6); scene.add(key);
const rim = new THREE.DirectionalLight(0x8899bb, 0.35);
rim.position.set(-1.5, 1, 0.4); scene.add(rim);

const b0 = D.bounds[0], b1 = D.bounds[1];
const cx = (b0[0]+b1[0])/2, cy = (b0[1]+b1[1])/2;
const diag = Math.hypot(b1[0]-b0[0], b1[1]-b0[1], b1[2]-b0[2]);
// bed grid at z of part bottom
const grid = new THREE.GridHelper(diag*1.6, 20, 0x2e3742, 0x232a34);
grid.rotation.x = Math.PI/2;
grid.position.set(cx, cy, b0[2]); scene.add(grid);

// highlight marker
const marker = new THREE.Mesh(
  new THREE.SphereGeometry(1, 24, 18),
  new THREE.MeshBasicMaterial({color: 0xffffff, wireframe: true,
                               transparent: true, opacity: 0.35}));
marker.visible = false; scene.add(marker);

// ---- custom z-up orbit
let tgt = new THREE.Vector3(cx, cy, (b0[2]+b1[2])/2);
let sph = {r: diag*1.7, th: -Math.PI/3, ph: 0.42};   // theta azimuth, phi elev
let goal = {tgt: tgt.clone(), r: sph.r, ph: null};
function applyCam() {
  camera.position.set(
    tgt.x + sph.r*Math.cos(sph.ph)*Math.cos(sph.th),
    tgt.y + sph.r*Math.cos(sph.ph)*Math.sin(sph.th),
    tgt.z + sph.r*Math.sin(sph.ph));
  camera.lookAt(tgt);
}
let drag = null;
renderer.domElement.addEventListener('contextmenu', e => e.preventDefault());
renderer.domElement.addEventListener('pointerdown', e => {
  drag = {x: e.clientX, y: e.clientY, btn: e.button};
});
window.addEventListener('pointerup', () => drag = null);
window.addEventListener('pointermove', e => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.x = e.clientX; drag.y = e.clientY;
  if (drag.btn === 2) {                       // pan
    const s = sph.r * 0.0016;
    const right = new THREE.Vector3().subVectors(camera.position, tgt)
      .cross(camera.up).normalize();
    const upv = new THREE.Vector3(0, 0, 1);
    tgt.addScaledVector(right, dx*s).addScaledVector(upv, dy*s);
    goal.tgt.copy(tgt);
  } else {                                    // orbit
    sph.th -= dx*0.006;
    sph.ph = Math.min(1.45, Math.max(-1.45, sph.ph + dy*0.006));
    goal.ph = null;                           // user takes over elevation
  }
});
renderer.domElement.addEventListener('wheel', e => {
  e.preventDefault();
  goal.r = Math.min(diag*6, Math.max(diag*0.15,
           goal.r * (e.deltaY > 0 ? 1.12 : 0.89)));
}, {passive: false});

function ringsToPath(rings, tf) {
  return rings.map(r => 'M' + r.map((p,i) =>
    (i?'L':'') + tf(p).join(' ')).join(' ') + 'Z').join(' ');
}
function drawSlice(f) {
  const el = document.getElementById('slice');
  const d = f.diagram;
  if (!d) { el.style.display = 'none'; return; }
  const W = 256, H = 156, pad = 12;
  const [x0,y0,x1,y1] = d.bbox;
  const s = Math.min((W-2*pad)/Math.max(x1-x0,1e-3),
                     (H-2*pad)/Math.max(y1-y0,1e-3));
  const ox = (W - (x1-x0)*s)/2, oy = (H - (y1-y0)*s)/2;
  // world (x,y up) -> svg (y down)
  const tf = p => [ +(ox + (p[0]-x0)*s).toFixed(1),
                    +(H - oy - (p[1]-y0)*s).toFixed(1) ];
  const P = (rings, attr) => rings.length ?
    `<path d="${ringsToPath(rings, tf)}" fill-rule="evenodd" ${attr}/>` : '';
  const svg =
    `<svg viewBox="0 0 ${W} ${H}">` +
    P(d.prev, 'fill="#3a4658" opacity="0.55"') +          // support below
    P(d.env,  'fill="none" stroke="#4f7fd0" stroke-width="1.3" stroke-dasharray="4 3"') + // allowed envelope
    P(d.cur,  'fill="none" stroke="#c9d2de" stroke-width="1.2"') +   // this slice
    P(d.bad,  'fill="#dc1e1e" opacity="0.72"') +           // beyond envelope
    `</svg>`;
  el.innerHTML =
    `<h4>Why: the transition at z=${d.z}</h4>` +
    `<div class="cap">this slice vs its support at z=${d.zprev} ` +
    `(&Delta;${(d.z-d.zprev).toFixed(1)}mm)</div>` + svg +
    `<div class="leg">` +
    `<span class="sw" style="border-top:2px dashed #4f7fd0"></span>allowed 45&deg; envelope` +
    `<span class="sw" style="border-top:2px solid #c9d2de"></span>this slice<br>` +
    `<span class="sw" style="background:#3a4658;height:8px;border-radius:2px"></span>support below` +
    `<span class="sw" style="background:#dc1e1e;height:8px;border-radius:2px"></span>past envelope` +
    `</div>` +
    (f.severity === 'fail'
      ? `<div class="cap" style="margin-top:7px;color:#4f7fd0">` +
        `Fix: morph the red back within the dashed envelope, or ground it ` +
        `to solid below.</div>` : '');
  el.style.display = 'block';
}
function select(f) {
  document.querySelectorAll('.card').forEach(c =>
    c.classList.remove('sel'));
  document.getElementById('card'+f.id).classList.add('sel');
  goal.tgt.set(f.center[0], f.center[1], f.center[2]);
  goal.r = Math.max(f.radius*5, diag*0.35);
  goal.ph = -0.35;      // defects are undersides: approach from below
  marker.position.set(f.center[0], f.center[1], f.center[2]);
  marker.scale.setScalar(f.radius);
  marker.visible = true;
  drawSlice(f);
}

function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h); camera.aspect = w/h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);

function tick() {
  requestAnimationFrame(tick);
  tgt.lerp(goal.tgt, 0.12);
  sph.r += (goal.r - sph.r)*0.12;
  if (goal.ph !== null) {
    sph.ph += (goal.ph - sph.ph)*0.12;
    if (Math.abs(goal.ph - sph.ph) < 0.01) goal.ph = null;
  }
  applyCam();
  renderer.render(scene, camera);
}
resize(); applyCam(); tick();
</script>
</body>
</html>
"""
