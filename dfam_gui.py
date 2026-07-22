#!/usr/bin/env python3
"""
dfam_gui.py - a local web GUI for stalagmite, so you never have to touch
the command line.

    stalagmite-gui

Opens http://127.0.0.1:8757 in your browser with three tabs:
  * Audit    - drop an STL, get the full interactive 3D report
  * Orient   - find a better build orientation, download the rotated STL
  * Compare  - drop two revisions, see what your change fixed / broke

The server is localhost-only; nothing leaves your machine. All three
tabs run the same tested Python behind dfam_audit / dfam_orient /
dfam_diff -- the browser is just a front door.
"""
import os
import sys
import json
import html
import base64
import tempfile
import webbrowser
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BYTES = 300 * 1024 * 1024   # 300 MB per file


# ---------------------------------------------------------------- helpers

def _tmp_write(raw, name):
    suffix = os.path.splitext(name)[1] or ".stl"
    t = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    t.write(raw)
    t.close()
    return t.name


def run_audit_html(raw, name, profile_name, auto_ex, suggest):
    """Bytes -> full report HTML string. Testable without a server."""
    import dfam_profiles
    from dfam_audit import (load_mesh, audit_mesh, aggregate,
                            suggest_repairs, detect_helix_zones,
                            overall_status, mesh_health)
    from dfam_report import render_report
    profile = dfam_profiles.resolve(profile_name or None)
    path = _tmp_write(raw, name)
    try:
        m = load_mesh(path)
        exclude = []
        if auto_ex:
            _, p1 = audit_mesh(m, profile.angle, profile.dz, exclude,
                               profile.ledge_max, profile.bridge_max)
            for zn in detect_helix_zones(p1, profile.dz):
                exclude.append((zn["zlo"], zn["zhi"], zn["rmax"],
                                zn["cx"], zn["cy"]))
        warnings = []
        bed, viol = audit_mesh(m, profile.angle, profile.dz, exclude,
                               profile.ledge_max, profile.bridge_max,
                               warn_angle=profile.warn_angle,
                               min_wall=profile.min_wall,
                               warnings_out=warnings)
        feats = aggregate(viol, profile.dz)
        if suggest:
            suggest_repairs(m, feats, profile.dz, profile.angle)
        status = overall_status(feats, warnings)
        return render_report(m, viol, feats, meta={
            "part": os.path.basename(name), "angle": profile.angle,
            "dz": profile.dz, "bed": bed, "status": status,
            "profile": profile.name, "health": mesh_health(m, profile.dz),
            "zones": [list(z) for z in exclude]})
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def run_orient(raw, name, profile_name, axis):
    """Bytes -> orientation result dict (with oriented STL base64)."""
    import numpy as np
    import dfam_profiles
    from dfam_audit import load_mesh
    from dfam_orient import (solve_orientation, parse_constraints,
                            support_proxy, rotmat)
    profile = dfam_profiles.resolve(profile_name or None)
    path = _tmp_write(raw, name)
    try:
        m = load_mesh(path)
        cons = []
        axmap = {"x": "1,0,0", "y": "0,1,0", "z": "0,0,1"}
        if axis in axmap:
            cons = parse_constraints([axmap[axis]], [])
        res = solve_orientation(m, cons, max_angle=profile.angle,
                                dz=profile.dz, iters=24)
        before = support_proxy(m, rotmat(0, 0), profile.angle, profile.dz)
        after = res["proxy"]
        # export the oriented mesh (dropped to the plate)
        R = res["R"]
        T = np.eye(4)
        T[:3, :3] = R
        out = m.copy()
        out.apply_transform(T)
        out.apply_translation([0, 0, -out.bounds[0][2]])
        stl = out.export(file_type="stl")
        if isinstance(stl, str):
            stl = stl.encode()
        stem = os.path.splitext(os.path.basename(name))[0]
        red = (100.0 * (before - after) / before) if before > 1e-9 else 0.0
        return {
            "ok": True,
            "theta_x": round(res["theta_x"], 1),
            "theta_y": round(res["theta_y"], 1),
            "before": round(before, 1), "after": round(after, 1),
            "reduction": round(max(0.0, red), 1),
            "penalty": round(res["penalty_deg"], 1),
            "axis": axis,
            "stl_b64": base64.b64encode(stl).decode(),
            "stl_name": f"{stem}_oriented.stl",
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def run_fix(raw, name, profile_name, auto_ex, keep=(), sculpt=()):
    """Bytes -> fix result dict incl. fixed STL (b64) and a full report
    of the FIXED part, so the GUI can show before -> after seamlessly.
    `keep` = design-intent keep-clear zones (from the report's protect
    toggles): no repair may touch them."""
    import dfam_profiles
    from dfam_audit import (load_mesh, suggest_repairs, mesh_health,
                            _ex_parts)
    from dfam_fix import apply_fixes
    from dfam_report import render_report
    profile = dfam_profiles.resolve(profile_name or None)
    path = _tmp_write(raw, name)
    try:
        m = load_mesh(path)
        r = apply_fixes(m, profile, auto_ex=auto_ex, keep=keep,
                        sculpt=sculpt)
        out = r.to_dict()
        out["ok"] = True
        out["part"] = os.path.basename(name)
        stem = os.path.splitext(os.path.basename(name))[0]
        if r.verdict in ("VERIFIED", "PARTIAL", "NOT_IMPROVED"):
            stl = r.mesh_fixed.export(file_type="stl")
            if isinstance(stl, str):
                stl = stl.encode()
            out["stl_b64"] = base64.b64encode(stl).decode()
            # NOT_IMPROVED: the file is available but honestly named --
            # this is the GUI's equivalent of the CLI's --force
            out["stl_name"] = (f"{stem}_fixed.stl"
                               if r.verdict != "NOT_IMPROVED"
                               else f"{stem}_attempt_FAILS.stl")
        # ALWAYS show the re-audited outcome -- including a refused
        # attempt (never-worse withholds the STL, not the evidence)
        if r.verdict in ("VERIFIED", "PARTIAL", "NOT_IMPROVED"):
            label = out.get("stl_name") or \
                f"{stem} — attempted fix (output withheld)"
            if keep:
                from dfam_intent import annotate_features
                annotate_features(r.feats_after, keep)
            suggest_repairs(r.mesh_fixed, r.feats_after, profile.dz,
                            profile.angle)
            out["fixed_report"] = render_report(
                r.mesh_fixed,
                [v for f in r.feats_after for v in f["layers"]],
                r.feats_after,
                meta={"part": label, "angle": profile.angle,
                      "dz": profile.dz, "status": r.status_after,
                      "profile": profile.name,
                      "health": mesh_health(r.mesh_fixed, profile.dz),
                      "zones": [list(_ex_parts(e)) for e in r.exclude]})
        return out
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def run_diff(old_raw, old_name, new_raw, new_name, profile_name, auto_ex):
    """Two byte blobs -> diff result dict (serializable)."""
    import dfam_profiles
    from dfam_diff import diff_audits, _label
    profile = dfam_profiles.resolve(profile_name or None)
    op = _tmp_write(old_raw, old_name)
    np_ = _tmp_write(new_raw, new_name)
    try:
        r = diff_audits(op, np_, profile, auto_ex=auto_ex)

        def sev_of(f):
            return f["severity"]
        resolved = [{"label": _label(r["old_f"][i]),
                     "sev": sev_of(r["old_f"][i])} for i in r["resolved"]]
        persists = []
        for oi, nj in r["persist"]:
            so, sn = sev_of(r["old_f"][oi]), sev_of(r["new_f"][nj])
            persists.append({"label": _label(r["new_f"][nj]),
                             "from": so, "to": sn})
        introduced = [{"label": _label(r["new_f"][j]),
                       "sev": sev_of(r["new_f"][j]),
                       "fail": sev_of(r["new_f"][j]) == "fail"}
                      for j in r["introduced"]]
        return {
            "ok": True, "verdict": r["verdict"],
            "old_status": r["old_status"], "new_status": r["new_status"],
            "regressed": r["regressed"],
            "resolved": resolved, "persists": persists,
            "introduced": introduced,
            "old_name": os.path.basename(old_name),
            "new_name": os.path.basename(new_name),
        }
    finally:
        for p in (op, np_):
            try:
                os.unlink(p)
            except OSError:
                pass


def _landing():
    import dfam_profiles
    opts = "".join(f'<option value="{html.escape(k)}">{html.escape(k)}'
                   f'</option>' for k in dfam_profiles.list_profiles())
    from dfam_logo import logo_data_uri
    return _LANDING.replace("__PROFILE_OPTS__", opts) \
                   .replace("__LOGO__", logo_data_uri())


def _err_json(msg):
    return json.dumps({"ok": False, "error": msg})


# ---------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        if n <= 0 or n > MAX_BYTES:
            return None
        return self.rfile.read(n)

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self._send(200, _landing())
        elif p == "/favicon.ico":
            self._send(204, b"")
        else:
            self._send(404, "not found")

    def do_POST(self):
        p = urlparse(self.path).path
        q = parse_qs(urlparse(self.path).query)
        raw = self._body()
        JSON = "application/json; charset=utf-8"
        try:
            if p == "/audit":
                if not raw:
                    self._send(200, _error("File missing or too large."))
                    return
                out = run_audit_html(
                    raw, q.get("name", ["part.stl"])[0],
                    q.get("profile", [""])[0],
                    q.get("auto_ex", ["1"])[0] == "1",
                    q.get("suggest", ["1"])[0] == "1")
                self._send(200, out)
            elif p == "/orient":
                if not raw:
                    self._send(200, _err_json("File missing."), JSON)
                    return
                out = run_orient(raw, q.get("name", ["part.stl"])[0],
                                 q.get("profile", [""])[0],
                                 q.get("axis", ["none"])[0])
                self._send(200, json.dumps(out), JSON)
            elif p == "/fix":
                if not raw:
                    self._send(200, _err_json("File missing."), JSON)
                    return
                from dfam_intent import parse_keep
                out = run_fix(raw, q.get("name", ["part.stl"])[0],
                              q.get("profile", [""])[0],
                              q.get("auto_ex", ["1"])[0] == "1",
                              parse_keep(q.get("keep", [])),
                              json.loads(q.get("sculpt", ["[]"])[0]))
                self._send(200, json.dumps(out), JSON)
            elif p == "/diff":
                obj = json.loads(raw.decode())
                out = run_diff(
                    base64.b64decode(obj["old"]), obj.get("oldname", "old"),
                    base64.b64decode(obj["new"]), obj.get("newname", "new"),
                    obj.get("profile", ""), obj.get("auto_ex", True))
                self._send(200, json.dumps(out), JSON)
            else:
                self._send(404, "not found")
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            if p == "/audit":
                self._send(200, _error(msg))
            else:
                self._send(200, _err_json(msg), JSON)


def _error(msg):
    return ("<!doctype html><meta charset=utf-8>"
            "<body style='background:#14171c;color:#e8eaed;"
            "font:15px system-ui;padding:40px'>"
            "<h2>stalagmite could not process that file</h2>"
            f"<p style='color:#dc6b6b'>{html.escape(msg)}</p>"
            "<p style='color:#9aa4b2'>Check it is a valid STL/OBJ/PLY mesh. "
            "<a style='color:#6ba7e6' href='/'>&larr; back</a></p></body>")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Launch the stalagmite browser GUI (localhost).")
    ap.add_argument("--port", type=int, default=8757)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"stalagmite GUI running at {url}")
    print("open the page, drop a part, audit / orient / compare. "
          "Ctrl+C to stop.")
    if not a.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


_LANDING = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>stalagmite</title>
<style>
  :root{--bg:#14171c;--card:#1c2129;--card2:#232a34;--line:#2e3742;
        --text:#e8eaed;--dim:#9aa4b2;--acc:#6ba7e6;
        --fail:#dc1e1e;--rev:#f08c14;--ok:#3fb96a}
  *{box-sizing:border-box;margin:0}
  body{background:var(--bg);color:var(--text);min-height:100vh;
       font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;
       display:flex;align-items:flex-start;justify-content:center;
       padding:34px 24px}
  .wrap{width:100%;max-width:580px}
  header{display:flex;align-items:center;gap:14px;margin-bottom:4px}
  h1{font-size:26px} h1 span{color:var(--dim);font-weight:400;font-size:17px}
  .tag{color:var(--dim);font-size:13px;margin:0 0 18px 66px}
  .tabs{display:flex;gap:6px;margin-bottom:16px}
  .tab{flex:1;text-align:center;padding:9px;border-radius:9px;
       background:var(--card);border:1px solid var(--line);cursor:pointer;
       font-size:14px;color:var(--dim)}
  .tab.on{background:var(--card2);color:var(--text);border-color:#3d4a5a}
  .pane{display:none} .pane.on{display:block}
  .drop{background:var(--card);border:2px dashed var(--line);
        border-radius:13px;padding:34px 20px;text-align:center;
        cursor:pointer;transition:.15s;margin-bottom:6px}
  .drop.hot{border-color:var(--acc);background:#1f2733}
  .drop b{font-size:15px} .drop small{color:var(--dim)}
  .fn{margin-top:9px;color:var(--acc);font-size:13px;min-height:16px}
  .row{display:flex;gap:14px;margin-top:16px;flex-wrap:wrap;
       align-items:flex-end}
  .fld{flex:1;min-width:150px}
  label{display:block;font-size:12px;color:var(--dim);margin-bottom:4px}
  select{width:100%;background:var(--card);color:var(--text);
         border:1px solid var(--line);border-radius:8px;padding:8px}
  .chk{display:flex;align-items:center;gap:7px;font-size:14px}
  button{margin-top:18px;width:100%;background:var(--acc);color:#0b1017;
         border:0;border-radius:10px;padding:13px;font-size:15px;
         font-weight:700;cursor:pointer}
  button:disabled{opacity:.5;cursor:default}
  .busy{display:none;margin-top:14px;color:var(--dim);text-align:center}
  .res{display:none;margin-top:18px;background:var(--card);
       border:1px solid var(--line);border-radius:12px;padding:16px}
  .res h3{font-size:15px;margin-bottom:8px}
  .statusbadge{display:inline-block;font-weight:700;font-size:12px;
       padding:2px 10px;border-radius:11px;color:#111}
  .b-PASS,.b-PASS_WITH_LIMITS{background:var(--ok)}
  .b-REVIEW,.b-CHANGED{background:var(--rev)}
  .b-FAIL,.b-REGRESSED{background:var(--fail);color:#fff}
  .b-IMPROVED{background:var(--ok)} .b-UNCHANGED{background:#55617a;color:#fff}
  .big{font-size:26px;font-weight:700;margin:6px 0}
  .sub{color:var(--dim);font-size:13px}
  .btnrow{display:flex;gap:10px;margin-top:14px}
  .btnrow a,.btnrow button{margin-top:0;text-decoration:none;text-align:center;
       padding:11px;border-radius:9px;font-size:14px;font-weight:700}
  .ghost{background:transparent;border:1px solid var(--acc);color:var(--acc)}
  #viewer{display:none;position:fixed;inset:0;background:var(--bg);
          flex-direction:column;z-index:50}
  .vbar{display:flex;align-items:center;gap:10px;padding:8px 12px;
        background:var(--card);border-bottom:1px solid var(--line)}
  .vbar button,.vbar a{margin:0;width:auto;padding:7px 13px;font-size:13px;
        border-radius:8px}
  .vbar .vbtn{background:transparent;border:1px solid var(--acc);
        color:var(--acc);text-decoration:none;font-weight:700}
  .vsp{flex:1}
  #vframe{flex:1;width:100%;border:0;background:var(--bg)}
  ul.diff{list-style:none;margin:8px 0 0;font-size:13px}
  ul.diff li{padding:4px 0;border-bottom:1px solid var(--line)}
  .t-RESOLVED{color:var(--ok);font-weight:700}
  .t-NEW,.t-NEWFAIL{color:var(--fail);font-weight:700}
  .t-PERSISTS{color:var(--dim);font-weight:700}
  .foot{color:var(--dim);font-size:12px;margin-top:18px;text-align:center}
</style></head><body><div class="wrap">
  <header>
    <img src="__LOGO__" alt="STALAGMITE — The transition IS the design"
         style="height:58px">
    <h1><span>toolkit</span></h1>
  </header>
  <p class="tag">Make stalagmites, not stalactites.</p>

  <div class="tabs">
    <div class="tab on" data-t="audit">Audit</div>
    <div class="tab" data-t="orient">Orient</div>
    <div class="tab" data-t="compare">Compare</div>
  </div>

  <!-- AUDIT -->
  <div class="pane on" id="p-audit">
    <div class="drop" id="d-audit"><b>Drop an STL here</b><br>
      <small>or click to choose &middot; STL / OBJ / PLY / 3MF</small>
      <div class="fn" id="fn-audit"></div></div>
    <div class="row">
      <div class="fld"><label>Process profile</label>
        <select id="prof-audit">__PROFILE_OPTS__</select></div>
    </div>
    <div class="row">
      <label class="chk"><input type="checkbox" id="ax-audit" checked> Auto-detect thread helices</label>
      <label class="chk"><input type="checkbox" id="sg-audit" checked> Repair suggestions</label>
    </div>
    <button id="go-audit" disabled>Run audit</button>
    <div class="busy" id="busy-audit">auditing &hellip; slicing the mesh, a few seconds</div>
  </div>

  <!-- ORIENT -->
  <div class="pane" id="p-orient">
    <div class="drop" id="d-orient"><b>Drop an STL to orient</b><br>
      <small>finds a build pose with fewer overhangs</small>
      <div class="fn" id="fn-orient"></div></div>
    <div class="row">
      <div class="fld"><label>Process profile</label>
        <select id="prof-orient">__PROFILE_OPTS__</select></div>
      <div class="fld"><label>Keep an axis vertical (threads)</label>
        <select id="axis-orient">
          <option value="none">none</option>
          <option value="z">part Z</option>
          <option value="x">part X</option>
          <option value="y">part Y</option></select></div>
    </div>
    <button id="go-orient" disabled>Find best orientation</button>
    <div class="busy" id="busy-orient">searching poses &hellip; ~24 trials</div>
    <div class="res" id="res-orient"></div>
  </div>

  <!-- COMPARE -->
  <div class="pane" id="p-compare">
    <div class="drop" id="d-old"><b>Drop the OLD revision</b>
      <div class="fn" id="fn-old"></div></div>
    <div class="drop" id="d-new" style="margin-top:10px"><b>Drop the NEW revision</b>
      <div class="fn" id="fn-new"></div></div>
    <div class="row">
      <div class="fld"><label>Process profile</label>
        <select id="prof-cmp">__PROFILE_OPTS__</select></div>
      <label class="chk"><input type="checkbox" id="ax-cmp" checked> Auto-detect threads</label>
    </div>
    <button id="go-cmp" disabled>Compare revisions</button>
    <div class="busy" id="busy-cmp">auditing both revisions &hellip;</div>
    <div class="res" id="res-cmp"></div>
  </div>

  <p class="foot">Runs locally on your machine. Nothing is uploaded.</p>
</div>
<div id="viewer">
  <div class="vbar">
    <button id="v-back">&larr; New audit</button>
    <span id="v-verdict" style="font-size:13px;color:var(--dim)"></span>
    <span class="vsp"></span>
    <a id="v-dlstl" class="vbtn" style="display:none">Download fixed STL</a>
    <button id="v-fix">Auto-fix &amp; re-audit</button>
    <a id="v-open" class="vbtn" target="_blank">Open in new tab</a>
    <a id="v-dl" class="vbtn">Download report</a>
  </div>
  <iframe id="vframe"></iframe>
</div>
<script>
// ---- tabs
document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('on'));
  document.querySelectorAll('.pane').forEach(x => x.classList.remove('on'));
  t.classList.add('on');
  document.getElementById('p'+'-'+t.dataset.t).classList.add('on');
});
// ---- reusable dropzone wiring
function dz(dropId, fnId, cb){
  const d = document.getElementById(dropId), fn = document.getElementById(fnId);
  const inp = document.createElement('input'); inp.type='file';
  inp.accept='.stl,.obj,.ply,.3mf'; inp.style.display='none';
  document.body.appendChild(inp);
  d.onclick = () => inp.click();
  inp.onchange = () => { if(inp.files[0]){ fn.textContent=inp.files[0].name; cb(inp.files[0]); } };
  ['dragover','dragenter'].forEach(e=>d.addEventListener(e,ev=>{ev.preventDefault();d.classList.add('hot');}));
  ['dragleave','drop'].forEach(e=>d.addEventListener(e,ev=>{ev.preventDefault();d.classList.remove('hot');}));
  d.addEventListener('drop', ev=>{ if(ev.dataTransfer.files[0]){ fn.textContent=ev.dataTransfer.files[0].name; cb(ev.dataTransfer.files[0]); }});
}
function b64(buf){ let s='',a=new Uint8Array(buf); for(let i=0;i<a.length;i++) s+=String.fromCharCode(a[i]); return btoa(s); }

// ---- AUDIT
let fAudit=null;
dz('d-audit','fn-audit', f=>{ fAudit=f; document.getElementById('go-audit').disabled=false; });
document.getElementById('go-audit').onclick = async () => {
  if(!fAudit) return;
  const go=document.getElementById('go-audit'); go.disabled=true;
  document.getElementById('busy-audit').style.display='block';
  const buf=await fAudit.arrayBuffer();
  const qs=new URLSearchParams({name:fAudit.name,
    profile:document.getElementById('prof-audit').value,
    auto_ex:document.getElementById('ax-audit').checked?'1':'0',
    suggest:document.getElementById('sg-audit').checked?'1':'0'});
  const r=await fetch('/audit?'+qs,{method:'POST',body:buf});
  const t=await r.text();
  const url=URL.createObjectURL(new Blob([t],{type:'text/html'}));
  const name=fAudit.name.replace(/\.[^.]+$/,'')+'_report.html';
  document.getElementById('vframe').src=url;
  document.getElementById('v-open').href=url;
  const dl=document.getElementById('v-dl'); dl.href=url; dl.download=name;
  document.getElementById('viewer').style.display='flex';
  document.getElementById('busy-audit').style.display='none';
  go.disabled=false;
};
document.getElementById('v-back').onclick=()=>{
  document.getElementById('viewer').style.display='none';
  document.getElementById('vframe').src='about:blank';
  document.getElementById('v-verdict').textContent='';
  const dl0=document.getElementById('v-dlstl');
  dl0.style.display='none'; dl0.textContent='Download fixed STL';
  dl0.style.borderColor=''; dl0.style.color='';
  const vf=document.getElementById('v-fix');
  vf.style.display=''; vf.textContent='Auto-fix & re-audit';
  vKeep=[]; vSculpt=[];
};
// keep-clear zones + sculpt state pushed up by the report
let vKeep=[], vSculpt=[];
window.addEventListener('message', e=>{
  const d=e.data;
  if(d && d.stalagmite==='keep'){
    vKeep=d.zones||[];
    const vd=document.getElementById('v-verdict');
    vd.textContent = vKeep.length
      ? vKeep.length+' defect(s) protected — Auto-fix will keep clear'
      : '';
  }
  if(d && d.stalagmite==='sculpt'){
    vSculpt=d.entries||[];
    const custom = vSculpt.some(x=>x.height!==undefined||x.optional);
    document.getElementById('v-fix').textContent =
      custom ? 'Apply sculpt & re-audit' : 'Auto-fix & re-audit';
  }
});
document.getElementById('v-fix').onclick = async () => {
  if(!fAudit) return;
  const vb=document.getElementById('v-fix'); vb.disabled=true;
  const vd=document.getElementById('v-verdict');
  vd.textContent='fixing: building repairs, unioning, re-auditing ...';
  const buf=await fAudit.arrayBuffer();
  const qs=new URLSearchParams({name:fAudit.name,
    profile:document.getElementById('prof-audit').value,
    auto_ex:document.getElementById('ax-audit').checked?'1':'0'});
  vKeep.forEach(z=>qs.append('keep', z.join(':')));
  if(vSculpt.length) qs.set('sculpt', JSON.stringify(vSculpt));
  try {
    const r=await fetch('/fix?'+qs,{method:'POST',body:buf});
    const j=await r.json();
    if(!j.ok){ vd.textContent='fix error: '+(j.error||'unknown'); vb.disabled=false; return; }
    const nblk=(j.notes||[]).filter(n=>n.indexOf('keep-clear')>=0).length;
    vd.innerHTML=`<b style="color:${j.verdict==='VERIFIED'?'#3fb96a':
      j.verdict==='PARTIAL'?'#f08c14':'#9aa4b2'}">${j.verdict}</b> `+
      `${j.status_before} &rarr; ${j.status_after} &middot; `+
      `${j.fails_before-j.fails_after} fail(s) cleared`+
      (nblk?` &middot; <span style="color:#7b5cd6">${nblk} repair(s) `+
            `withheld (protected)</span>`:'')+
      (j.verdict==='NOT_IMPROVED'
        ? ' &middot; <span style="color:#9aa4b2">output withheld '+
          '(never-worse) — showing the re-audited attempt</span>':'');
    if(j.stl_b64){
      const stl=Uint8Array.from(atob(j.stl_b64),c=>c.charCodeAt(0));
      const dl=document.getElementById('v-dlstl');
      dl.href=URL.createObjectURL(new Blob([stl],{type:'model/stl'}));
      dl.download=j.stl_name; dl.style.display='';
      const forced = j.verdict==='NOT_IMPROVED';
      dl.textContent = forced
        ? 'Download attempt STL (still fails)' : 'Download fixed STL';
      dl.style.borderColor = forced ? '#f08c14' : '';
      dl.style.color = forced ? '#f08c14' : '';
    }
    if(j.fixed_report){
      const url=URL.createObjectURL(new Blob([j.fixed_report],{type:'text/html'}));
      document.getElementById('vframe').src=url;
      document.getElementById('v-open').href=url;
      const dr=document.getElementById('v-dl');
      dr.href=url; dr.download=(j.stl_name||'part').replace(/\.stl$/,'')+'_report.html';
      vb.style.display='none';       // already fixed
    }
  } catch(e){ vd.textContent='fix error: '+e; }
  vb.disabled=false;
};

// ---- ORIENT
let fOri=null;
dz('d-orient','fn-orient', f=>{ fOri=f; document.getElementById('go-orient').disabled=false; });
document.getElementById('go-orient').onclick = async () => {
  if(!fOri) return;
  const go=document.getElementById('go-orient'); go.disabled=true;
  document.getElementById('busy-orient').style.display='block';
  document.getElementById('res-orient').style.display='none';
  const buf=await fOri.arrayBuffer();
  const qs=new URLSearchParams({name:fOri.name,
    profile:document.getElementById('prof-orient').value,
    axis:document.getElementById('axis-orient').value});
  const r=await fetch('/orient?'+qs,{method:'POST',body:buf});
  const j=await r.json();
  document.getElementById('busy-orient').style.display='none';
  const el=document.getElementById('res-orient'); el.style.display='block';
  if(!j.ok){ el.innerHTML='<h3>Could not orient</h3><div class="sub">'+j.error+'</div>'; go.disabled=false; return; }
  const stl=Uint8Array.from(atob(j.stl_b64),c=>c.charCodeAt(0));
  const url=URL.createObjectURL(new Blob([stl],{type:'model/stl'}));
  el.innerHTML=
    '<h3>Recommended orientation</h3>'+
    '<div class="sub">rotate part: X '+j.theta_x+'&deg;, Y '+j.theta_y+'&deg;'+
    (j.axis!=='none'?' &middot; kept '+j.axis.toUpperCase()+' vertical':'')+'</div>'+
    '<div class="big">support &minus;'+j.reduction+'%</div>'+
    '<div class="sub">support proxy '+j.before+' &rarr; '+j.after+
    ' (lower is better)</div>'+
    '<div class="btnrow"><a download="'+j.stl_name+'" href="'+url+'">Download oriented STL</a></div>'+
    '<div class="sub" style="margin-top:10px">Re-audit the oriented file '+
    '(Audit tab, auto-detect threads on) to see the new status.</div>';
  go.disabled=false;
};

// ---- COMPARE
let fOld=null,fNew=null;
function cmpReady(){ document.getElementById('go-cmp').disabled=!(fOld&&fNew); }
dz('d-old','fn-old', f=>{ fOld=f; cmpReady(); });
dz('d-new','fn-new', f=>{ fNew=f; cmpReady(); });
document.getElementById('go-cmp').onclick = async () => {
  if(!(fOld&&fNew)) return;
  const go=document.getElementById('go-cmp'); go.disabled=true;
  document.getElementById('busy-cmp').style.display='block';
  document.getElementById('res-cmp').style.display='none';
  const body=JSON.stringify({
    old:b64(await fOld.arrayBuffer()), oldname:fOld.name,
    new:b64(await fNew.arrayBuffer()), newname:fNew.name,
    profile:document.getElementById('prof-cmp').value,
    auto_ex:document.getElementById('ax-cmp').checked});
  const r=await fetch('/diff',{method:'POST',body});
  const j=await r.json();
  document.getElementById('busy-cmp').style.display='none';
  const el=document.getElementById('res-cmp'); el.style.display='block';
  if(!j.ok){ el.innerHTML='<h3>Could not compare</h3><div class="sub">'+j.error+'</div>'; go.disabled=false; return; }
  let li='';
  j.resolved.forEach(x=>li+='<li><span class="t-RESOLVED">RESOLVED</span> '+x.label+'</li>');
  j.persists.forEach(x=>li+='<li><span class="t-PERSISTS">PERSISTS</span> '+x.label+' ['+x.from+'&rarr;'+x.to+']</li>');
  j.introduced.forEach(x=>li+='<li><span class="'+(x.fail?'t-NEWFAIL':'t-NEW')+'">'+(x.fail?'NEW-FAIL':'NEW')+'</span> '+x.label+'</li>');
  if(!li) li='<li class="sub">no defect features in either revision</li>';
  el.innerHTML=
    '<h3>'+j.old_name+' &rarr; '+j.new_name+'</h3>'+
    '<div class="sub">old <span class="statusbadge b-'+j.old_status+'">'+j.old_status.replace(/_/g,' ')+
    '</span> &rarr; new <span class="statusbadge b-'+j.new_status+'">'+j.new_status.replace(/_/g,' ')+'</span></div>'+
    '<div class="big"><span class="statusbadge b-'+j.verdict+'">'+j.verdict+'</span></div>'+
    '<ul class="diff">'+li+'</ul>';
  go.disabled=false;
};
</script></body></html>"""


if __name__ == "__main__":
    sys.exit(main())
