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
            "repair_spec": f.get("repair_spec"),
            "intent": bool(f.get("intent_hits")),
        })
    return out


def render_report(mesh, violations, features, meta=None):
    """Build the self-contained report HTML and return it as a string."""
    meta = meta or {}
    dz = meta.get("dz", 0.4)
    # attach adjustable repair specs to fail features (real slice contours)
    try:
        from dfam_repair import make_repair_specs
        make_repair_specs(mesh, features, dz, meta.get("angle", 45.0),
                          avoid=[tuple(z) for z in
                                 meta.get("zones", [])],
                          severities=("fail", "judge", "tolerable"))
    except Exception:
        pass
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
    from dfam_logo import logo_data_uri
    return _TEMPLATE.replace("__THREE__", three_js()) \
                    .replace("__LOGO__", logo_data_uri()) \
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
  .card .protect{float:right;font-size:10.5px;padding:3px 8px;
        border-radius:20px;border:1px solid var(--line);cursor:pointer;
        background:transparent;color:var(--dim)}
  .card .protect.on{background:#7b5cd6;border-color:#7b5cd6;color:#fff}
  .card .protect:hover{border-color:#7b5cd6}
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
  #fixpanel{position:absolute;right:14px;top:14px;width:250px;
         background:rgba(28,33,41,.95);border:1px solid var(--line);
         border-radius:9px;padding:11px 12px;display:none}
  #fixpanel h4{margin:0 0 3px;font-size:12.5px;color:#3fd089}
  #fixpanel .cap{color:var(--dim);font-size:10.5px;margin-bottom:8px}
  #fixpanel label{display:block;font-size:10.5px;color:var(--dim);
         margin:7px 0 1px}
  #fixpanel input[type=range]{width:100%}
  #fixbadge{font-size:11px;font-weight:700;margin-top:8px}
  #fixdl{display:inline-block;margin-top:9px;padding:7px 12px;
         border-radius:8px;border:1px solid #3fd089;color:#3fd089;
         font-size:12px;font-weight:700;text-decoration:none;
         cursor:pointer}
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
  <div style="display:flex;flex-direction:column;gap:6px">
    <img src="__LOGO__" alt="STALAGMITE — The transition IS the design"
         style="height:46px;align-self:flex-start">
    <h1><span>audit report</span></h1>
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
<div id="view"><div id="hint">drag rotate &middot; wheel zoom &middot; right-drag pan</div><div id="slice"></div>
<div id="fixpanel">
  <h4 id="fixhead">Suggested repair (adjustable)</h4>
  <div class="cap" id="fixcap"></div>
  <label>Height: <span id="hval"></span> mm</label>
  <input type="range" id="hslide" min="0" max="100" value="0" step="0.5">
  <label>Easing (chamfer &rarr; fillet)</label>
  <input type="range" id="eslide" min="1" max="2.5" value="1" step="0.05">
  <div id="flarerow">
    <label>Flare (pillar foot spread)</label>
    <input type="range" id="fslide" min="1" max="1.35" value="1"
           step="0.01">
  </div>
  <div id="fixbadge"></div>
  <a id="fixdl">Download repair STL</a>
</div></div>
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
// design-intent: when embedded in the GUI, every defect can be marked
// "protected" -- a keep-clear zone derived from its own geometry is
// sent up to the GUI, and Auto-fix will refuse to touch it.
const EMBEDDED = (() => { try { return window.parent !== window; }
                          catch (e) { return false; } })();
const KEEP = new Map();
function keepZoneOf(f) {
  const pad = Math.max(1.0, 2 * D.meta.dz);
  return [+(f.zlo - pad).toFixed(2), +(f.zhi + pad).toFixed(2),
          +(f.radius + 1.0).toFixed(2), f.center[0], f.center[1]];
}
function pushKeep() {
  if (EMBEDDED) window.parent.postMessage(
    {stalagmite: 'keep', zones: [...KEEP.values()]}, '*');
}
D.features.forEach(f => {
  const c = document.createElement('div');
  c.className = 'card'; c.id = 'card' + f.id;
  c.innerHTML =
    `<span class="tag ${f.severity}">${f.severity}</span><b>${f.cls}</b>` +
    (f.intent ? ' <span class="tag" style="background:#7b5cd6;color:#fff">' +
                'on keep-clear zone</span>' : '') +
    (EMBEDDED ? `<button class="protect" title="mark this region as a ` +
      `functional surface: Auto-fix will not weld repairs onto it">` +
      `&#9098; protect</button>` : '') +
    `<div class="where">z ${f.zlo}-${f.zhi} - ${f.layers} layer(s)` +
    (f.dims ? ` - ${f.dims}` : '') + ` - ${f.sevLabel}</div>` +
    (f.repairs.length ?
      '<ul>' + f.repairs.map(r => `<li>${r}</li>`).join('') + '</ul>' : '');
  c.onclick = () => select(f);
  const pb = c.querySelector('.protect');
  if (pb) pb.onclick = (ev) => {
    ev.stopPropagation();
    if (KEEP.has(f.id)) { KEEP.delete(f.id); pb.classList.remove('on');
                          pb.innerHTML = '&#9098; protect'; }
    else { KEEP.set(f.id, keepZoneOf(f)); pb.classList.add('on');
           pb.innerHTML = '&#9098; protected'; }
    pushKeep();
  };
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
                               transparent: true, opacity: 0.07,
                               depthWrite: false}));
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
// ---- adjustable repair ghost (REAL slice contours, lofted live)
let ghost = null, spec = null, curF = null;
const RINGS = 32;
function buildLoftTris(sp, H, ease, flare) {
  const top = sp.top, bot0 = sp.bot, n = top.length;
  let cbx=0, cby=0;
  bot0.forEach(p => { cbx += p[0]/n; cby += p[1]/n; });
  const pillar = sp.kind === 'pillar';
  // pillar: whole foot scales (wider anchor on the BED is legitimate).
  // loft: flare is ignored -- base pinned to the landing, top pinned
  // to the defect; the concave chamfer->cove family lives in easing.
  const bot = pillar
    ? bot0.map(p => [cbx + (p[0]-cbx)*flare, cby + (p[1]-cby)*flare])
    : bot0;
  const zTop = sp.z_top, zBot = zTop - H;
  const ring = (s) => {
    const te = Math.pow(s, ease), z = zBot + H*s;
    const r = new Array(n);
    for (let j = 0; j < n; j++)
      r[j] = [bot[j][0] + (top[j][0]-bot[j][0])*te,
              bot[j][1] + (top[j][1]-bot[j][1])*te, z];
    return r;
  };
  const rings = [];
  for (let k = 0; k <= RINGS; k++) rings.push(ring(k/RINGS));
  window._ghostRings = rings;
  const tris = [];
  for (let k = 0; k < RINGS; k++) {
    const a = rings[k], b = rings[k+1];
    for (let j = 0; j < n; j++) {
      const j2 = (j+1)%n;
      tris.push(a[j], a[j2], b[j], a[j2], b[j2], b[j]);
    }
  }
  // caps
  let ctx=0, cty=0; top.forEach(p => { ctx += p[0]/n; cty += p[1]/n; });
  const cb=[cbx,cby,zBot], ct=[ctx,cty,zTop], A=rings[0], B=rings[RINGS];
  for (let j = 0; j < n; j++) {
    const j2=(j+1)%n;
    tris.push(cb, A[j2], A[j]);
    tris.push(ct, B[j], B[j2]);
  }
  return tris;
}
function buildRoofTris(sp, H, ease) {
  // internal roof chamfer: corbelled ring from the opening wall (bot)
  // up-and-inward to the bore/apex (top), plus outer wall + top annulus
  const top = sp.top, bot = sp.bot, n = top.length;
  const zTop = sp.z_top,
        zClose = (sp.z_close !== undefined ? sp.z_close : sp.z_top),
        zBot = zClose - H;
  const ring = (s) => {
    const te = Math.pow(s, ease), z = zBot + H*s;
    const r = new Array(n);
    for (let j = 0; j < n; j++)
      r[j] = [bot[j][0] + (top[j][0]-bot[j][0])*te,
              bot[j][1] + (top[j][1]-bot[j][1])*te, z];
    return r;
  };
  const rings = [];
  for (let k = 0; k <= RINGS; k++) rings.push(ring(k/RINGS));
  if (zTop > zClose + 1e-6)                 // vertical weld band
    rings.push(top.map(p => [p[0], p[1], zTop]));
  window._ghostRings = rings;
  const tris = [];
  for (let k = 0; k < rings.length - 1; k++) {
    const a = rings[k], b = rings[k+1];
    for (let j = 0; j < n; j++) {
      const j2 = (j+1)%n;
      tris.push(a[j], a[j2], b[j], a[j2], b[j2], b[j]);
    }
  }
  const W = bot.map(p => [p[0], p[1], zTop]);
  const A = rings[0], B = rings[rings.length-1];
  for (let j = 0; j < n; j++) {
    const j2 = (j+1)%n;
    tris.push(A[j], W[j], A[j2], A[j2], W[j], W[j2]);   // outer wall
    tris.push(B[j], B[j2], W[j], B[j2], W[j2], W[j]);   // top annulus
  }
  return tris;
}
function maxGap(sp, flare) {
  const n = sp.top.length; let cbx=0, cby=0;
  sp.bot.forEach(p => { cbx += p[0]/n; cby += p[1]/n; });
  const f = sp.kind === 'pillar' ? flare : 1;   // loft base is pinned
  let g = 0;
  for (let j = 0; j < n; j++) {
    const bx = cbx + (sp.bot[j][0]-cbx)*f,
          by = cby + (sp.bot[j][1]-cby)*f;
    g = Math.max(g, Math.hypot(sp.top[j][0]-bx, sp.top[j][1]-by));
  }
  return g;
}
function worstSlopeDeg() {
  // honest slope: measured on the ACTUAL generated rings, so easing
  // AND flare belly are both accounted for
  const R = window._ghostRings;
  if (!R || R.length < 2) return 0;
  let w = 0;
  for (let k = 0; k < R.length - 1; k++) {
    const dz = R[k+1][0][2] - R[k][0][2];
    if (dz <= 1e-6) continue;
    for (let j = 0; j < R[k].length; j++) {
      const t = Math.hypot(R[k+1][j][0]-R[k][j][0],
                           R[k+1][j][1]-R[k][j][1]);
      w = Math.max(w, t/dz);
    }
  }
  return Math.atan(w) * 180/Math.PI;
}
function refreshGhost(touched) {
  if (!spec) return;
  const ease = +document.getElementById('eslide').value;
  const roof = spec.kind === 'roofcone';
  const fs = document.getElementById('fslide');
  // flare = foot spread on the BED, pillars only. A loft's base is
  // pinned to its landing and its top to the defect: any profile
  // fuller than the straight chamfer must bulge CONVEX somewhere.
  // The concave family (chamfer -> cove) is what Easing controls.
  fs.disabled = spec.kind !== 'pillar';
  // don't show a dead control: the row only appears for bed pillars
  document.getElementById('flarerow').style.display =
    spec.kind === 'pillar' ? '' : 'none';
  const flare = spec.kind === 'pillar' ? +fs.value : 1;
  const gap = maxGap(spec, flare);
  const tanA = Math.tan(spec.angle * Math.PI/180);
  const hMin = Math.max(gap * ease / tanA, spec.dz * 2);
  const zcl = (spec.z_close !== undefined ? spec.z_close : spec.z_top);
  const hBed = zcl - (spec.z_floor !== undefined
                      ? spec.z_floor : spec.z_bot);
  const hs = document.getElementById('hslide');
  const hMax = Math.min(Math.max(hMin * 3, zcl - spec.z_bot,
                                 hMin + 5), hBed);
  hs.min = Math.min(hMin, hBed).toFixed(1); hs.max = hMax.toFixed(1);
  let H = +hs.value;
  if (spec.kind === 'pillar') { H = spec.z_top - spec.z_bot; hs.disabled = true; }
  else { hs.disabled = false;
         if (H < hMin) { H = Math.min(hMin, hBed); hs.value = H; }
         if (H > hBed) { H = hBed; hs.value = H; } }
  document.getElementById('hval').textContent = H.toFixed(1);
  if (touched === true && curF) {          // remember per-defect sculpt
    SCULPT.set(curF.id, {H: H, ease: ease, flare: flare});
    updateDlLabel();
  }
  const tris = (roof || spec.kind === 'skirt')
                    ? buildRoofTris(spec, H, ease)
                    : buildLoftTris(spec, H, ease, flare);
  // slope measured on the ACTUAL rings (easing + flare belly included)
  const worst = worstSlopeDeg();
  const okPhys = worst <= spec.angle + 0.51 || spec.kind === 'pillar';
  const okBed = hMin <= hBed + 0.01 || spec.kind === 'pillar';
  document.getElementById('fixbadge').innerHTML =
    !okBed ? `<span style="color:#dc1e1e">won't fit above the bed at this easing &mdash; reduce easing</span>`
    : okPhys
    ? `<span style="color:#3fd089">physics OK</span> <span style="color:#9aa4b2">&mdash; worst slope ${worst.toFixed(0)}&deg; (limit ${spec.angle}&deg;)</span>`
    : `<span style="color:#dc1e1e">exceeds ${spec.angle}&deg; &mdash; lower flare, reduce easing, or raise height</span>`;
  if (roof && spec.over_allowance)
    document.getElementById('fixbadge').innerHTML =
      `<span style="color:#dc1e1e">partial only: ` +
      `${spec.residual_ledge}mm ledge remains beyond the ` +
      `${spec.ledge_max}mm allowance (threads block a full cone) ` +
      `&mdash; expect droop; the real fix is raising/doming the ` +
      `roof</span><br>` +
      (worst <= spec.angle + 0.51
        ? `<span style="color:#3fd089">cone surface OK &mdash; worst ` +
          `slope ${worst.toFixed(0)}&deg; (limit ${spec.angle}&deg;)</span>`
        : `<span style="color:#dc1e1e">cone surface EXCEEDS ` +
          `${spec.angle}&deg; (${worst.toFixed(0)}&deg;) &mdash; ` +
          `reduce easing</span>`);
  const pos = new Float32Array(tris.length * 3);
  tris.forEach((p, i) => { pos[3*i]=p[0]; pos[3*i+1]=p[1]; pos[3*i+2]=p[2]; });
  if (ghost) { scene.remove(ghost); ghost.geometry.dispose(); }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.computeVertexNormals();
  ghost = new THREE.Mesh(g, new THREE.MeshStandardMaterial({
    color: 0x3fd089, transparent: true, opacity: 0.42,
    side: THREE.DoubleSide, depthWrite: false, roughness: 0.9}));
  scene.add(ghost);
  window._ghostTris = tris;
}
['hslide','eslide','fslide'].forEach(id =>
  document.getElementById(id).addEventListener('input',
    () => refreshGhost(true)));
// -- multi-body export: per-defect sculpt settings are remembered, and
//    the STL bundles every repair that belongs in the file: all fail
//    repairs (your settings, or defaults if untouched) plus optional
//    repairs you actually adjusted.
const SCULPT = new Map();                 // feature id -> {H, ease, flare}
function defSettings(sp) {
  return {H: Math.max((sp.z_close !== undefined ? sp.z_close : sp.z_top)
                      - sp.z_bot, sp.min_h), ease: 1, flare: 1};
}
function trisForSpec(sp, st) {
  return (sp.kind === 'roofcone' || sp.kind === 'skirt')
    ? buildRoofTris(sp, st.H, st.ease)
    : buildLoftTris(sp, st.H, st.ease, st.flare);
}
function exportSet() {
  return D.features.filter(f => f.repair_spec &&
    (!f.repair_spec.optional || SCULPT.has(f.id)));
}
let ghostAll = null;
function refreshAllGhosts() {
  // every repair in the export set stays VISIBLE (dim) while you edit
  // another -- the selected one is the bright editable ghost
  if (ghostAll) {
    scene.remove(ghostAll);
    ghostAll.children.forEach(m => m.geometry.dispose());
    ghostAll = null;
  }
  const others = exportSet().filter(f => !curF || f.id !== curF.id);
  if (!others.length) return;
  ghostAll = new THREE.Group();
  others.forEach(f => {
    const sp = f.repair_spec;
    const tris = trisForSpec(sp, SCULPT.get(f.id) || defSettings(sp));
    const pos = new Float32Array(tris.length * 3);
    tris.forEach((p, i) => { pos[3*i]=p[0]; pos[3*i+1]=p[1];
                             pos[3*i+2]=p[2]; });
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.computeVertexNormals();
    ghostAll.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({
      color: 0x2f8f66, transparent: true, opacity: 0.16,
      side: THREE.DoubleSide, depthWrite: false, roughness: 0.9})));
  });
  scene.add(ghostAll);
}
function updateDlLabel() {
  const n = exportSet().length;
  document.getElementById('fixdl').textContent =
    n > 1 ? `Download repair STL (${n} bodies)` : 'Download repair STL';
  pushSculpt();
  refreshAllGhosts();
}
function pushSculpt() {
  // hand the sculpt state up to the GUI so Auto-fix can APPLY it:
  // per-defect settings + which optional repairs were opted in
  if (!EMBEDDED) return;
  const entries = exportSet().map(f => {
    const s = SCULPT.get(f.id);
    const e = {id: f.id, cls: f.cls, zlo: f.zlo, zhi: f.zhi,
               cx: f.center[0], cy: f.center[1],
               optional: !!f.repair_spec.optional};
    if (s) { e.height = s.H; e.easing = s.ease; e.flare = s.flare; }
    return e;
  });
  window.parent.postMessage({stalagmite: 'sculpt', entries: entries},
                            '*');
}
document.getElementById('fixdl').onclick = () => {
  const set = exportSet();
  let tris = [];
  if (set.length) {
    set.forEach(f => {
      const sp = f.repair_spec;
      tris = tris.concat(trisForSpec(sp, SCULPT.get(f.id)
                                         || defSettings(sp)));
    });
    if (spec) refreshGhost();            // restore the live ghost rings
  } else {
    tris = window._ghostTris;
  }
  if (!tris || !tris.length) return;
  const nT = tris.length / 3;
  const buf = new ArrayBuffer(84 + nT * 50);
  const dv = new DataView(buf);
  dv.setUint32(80, nT, true);
  let o = 84;
  for (let i = 0; i < tris.length; i += 3) {
    const [a, b, c] = [tris[i], tris[i+1], tris[i+2]];
    const u = [b[0]-a[0], b[1]-a[1], b[2]-a[2]],
          v = [c[0]-a[0], c[1]-a[1], c[2]-a[2]];
    let nx = u[1]*v[2]-u[2]*v[1], ny = u[2]*v[0]-u[0]*v[2],
        nz = u[0]*v[1]-u[1]*v[0];
    const L = Math.hypot(nx, ny, nz) || 1;
    [nx/L, ny/L, nz/L, ...a, ...b, ...c].forEach(x => {
      dv.setFloat32(o, x, true); o += 4; });
    dv.setUint16(o, 0, true); o += 2;
  }
  const aEl = document.createElement('a');
  aEl.href = URL.createObjectURL(new Blob([buf],
    {type: 'model/stl'}));
  aEl.download = 'stalagmite_repair.stl';
  aEl.click();
};
function showRepair(f) {
  spec = f.repair_spec || null;
  curF = f;
  const el = document.getElementById('fixpanel');
  // internal repairs (roof chamfer) live INSIDE the part: go x-ray so
  // the ghost is visible; restore when deselected
  mat.transparent = (spec && spec.kind === 'roofcone');
  mat.opacity = mat.transparent ? 0.38 : 1.0;
  mat.depthWrite = !mat.transparent;
  mat.needsUpdate = true;
  if (!spec) { el.style.display='none';
    if (ghost) { scene.remove(ghost); ghost = null; }
    updateDlLabel(); return; }
  const head = document.getElementById('fixhead');
  head.textContent = spec.optional
    ? 'Optional quality repair (adjustable)'
    : 'Suggested repair (adjustable)';
  head.style.color = spec.optional ? '#d9b23c' : '#3fd089';
  document.getElementById('fixcap').textContent =
    (spec.optional ? 'this defect already prints within allowance - ' +
     'sculpt this only if you want a cleaner underside; Auto-fix ' +
     'never applies it. ' : '') +
    (spec.kind === 'pillar' ? 'ground pillar to the bed' :
     spec.kind === 'skirt' ?
       'external skirt chamfer under the overhanging rim - annular, ' +
       'so the part interior stays hollow' :
     spec.kind === 'roofcone' ?
       'internal roof chamfer - closes the ceiling as a gentle cone; ' +
       'the cavity stays hollow and bores stay open' +
       (spec.clamped_above ? `; clamped ABOVE the functional zone at ` +
        `z ${spec.clamped_above[0]}-${spec.clamped_above[1]} (threads ` +
        `untouched)` : '') +
       (spec.residual_ledge ? (spec.over_allowance
         ? `; PARTIAL only - the remaining ledge exceeds allowance ` +
           `(see badge); the real fix is raising/doming the roof`
         : `; partial closure - remaining ${spec.residual_ledge}mm ` +
           `ledge is within allowance`) : '') +
       (spec.drill && spec.drill.length ?
        ` (${spec.drill.length} vent shaft(s) are drilled through the ` +
        `applied body so secondary roof holes stay continuous; this ` +
        `browser-downloaded ghost STL does not include the shafts)` :
        '') :
     'morph loft to real support below') +
    ` - union this body into your part, then re-audit`;
  const hs = document.getElementById('hslide');
  const saved = SCULPT.get(f.id);          // restore this defect's sculpt
  hs.value = saved ? saved.H
    : ((spec.z_close !== undefined ? spec.z_close : spec.z_top)
       - spec.z_bot).toFixed(1);
  document.getElementById('eslide').value = saved ? saved.ease : 1;
  document.getElementById('fslide').value = saved ? saved.flare : 1;
  el.style.display = 'block';
  updateDlLabel();
  refreshGhost();
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
  showRepair(f);
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
