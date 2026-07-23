#!/usr/bin/env python3
"""
dfam_patch.py - Stage D: emit repairs as DESIGN SOURCE, not mesh surgery.

    stalagmite-patch part.stl                      -> part_patch.scad
    stalagmite-patch part.stl --lang cadquery      -> part_patch.py
    stalagmite-patch part.stl --auto-ex --json

Stages A-C weld repair bodies onto the STL. That fixes the artifact;
the DESIGN is still broken -- every re-export reintroduces the defect.
Stage D translates each repair spec into a parametric snippet (OpenSCAD
or CadQuery) you paste into the ORIGINAL model, so the fix lives
upstream where it belongs.

Honesty rules carry over:
- Snippets are CIRCLE FITS of the real slice contours. Every fix is
  headed by the fitted radius and its max deviation; visibly
  non-circular contours get a WARNING comment instead of silence.
- Before writing anything, the parametric geometry is rebuilt as a
  mesh, unioned, and RE-AUDITED (--no-verify skips). The verdict is
  printed and drives the exit code -- pasting source you can't trust
  is Stage A's bug, not Stage D's feature.
- Blocked repairs (no usable wall, functional zones) are emitted as
  comments quoting the audit's reason, never as geometry.

Exit: 0 = patch written and parametric preview VERIFIED (or nothing to
patch), 1 = patch written but preview PARTIAL/NOT_IMPROVED or some
fails have no emittable repair, 2 = could not process.
"""
import os
import sys
import json

import numpy as np

FN = 96                       # $fn / facet count hint in emitted source
EPS = 0.2                     # boolean overlap used by emitted cuts


def _g(v):
    """Emit-friendly number: rounded to 3 decimals, no float noise."""
    return format(round(float(v), 3), "g")


# ------------------------------------------------------------ circle fit

def fit_circle(ring):
    """Least-effort robust fit: centroid + mean radius. Returns
    (cx, cy, r, max_dev). Good exactly where Stage D is honest about
    being good: near-circular openings, bores, rims and feet."""
    pts = np.asarray(ring, dtype=float)
    cx, cy = pts.mean(axis=0)
    d = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
    r = float(d.mean())
    return float(cx), float(cy), r, float(np.abs(d - r).max())


def _fit(ring):
    cx, cy, r, dev = fit_circle(ring)
    return {"cx": round(cx, 3), "cy": round(cy, 3),
            "r": round(r, 3), "dev": round(dev, 3)}


def _noncircular(c):
    return c["dev"] > max(0.5, 0.08 * c["r"])


# ------------------------------------------------------------ parameters

def fix_params(mesh, features, dz=0.4, angle=45.0, keep=(), avoid=(),
               ledge_max=1.8):
    """Circle-fit parameter blocks for every fail feature with a repair
    spec. Returns (params, blocked_notes)."""
    from dfam_repair import make_repair_specs
    specs = make_repair_specs(mesh, features, dz, angle, keep,
                              avoid=avoid, ledge_max=ledge_max,
                              severities=("fail",))
    params = []
    for s in specs:
        f = features[s["feature"]]
        p = {
            "feature": s["feature"], "kind": s["kind"],
            "cls": f["cls"], "severity": f["severity"],
            "z_top": s["z_top"], "z_bot": s["z_bot"],
            "z_close": s.get("z_close", s["z_top"]),
            "z_floor": s.get("z_floor", 0.0),
            "min_h": s["min_h"], "angle": s["angle"], "dz": s["dz"],
            "top": _fit(s["top"]), "bot": _fit(s["bot"]),
            "vents": [_fit(r) for r in (s.get("drill") or [])],
            "over_allowance": bool(s.get("over_allowance")),
            "residual_ledge": s.get("residual_ledge"),
            "ledge_max": s.get("ledge_max"),
            "warnings": [],
        }
        for label, c in (("top contour", p["top"]),
                         ("bottom contour", p["bot"])):
            if _noncircular(c):
                p["warnings"].append(
                    f"{label} is not circular (max deviation "
                    f"{c['dev']}mm on r={c['r']}mm) -- the snippet "
                    f"approximates it; re-audit after applying")
        off = float(np.hypot(p["top"]["cx"] - p["bot"]["cx"],
                             p["top"]["cy"] - p["bot"]["cy"]))
        if p["kind"] in ("roofcone", "skirt") and off > 1.0:
            p["warnings"].append(
                f"top/bottom centers differ by {off:.1f}mm; emitted "
                f"concentric on the opening center")
        if p["over_allowance"]:
            p["warnings"].append(
                f"PARTIAL closure only: {p['residual_ledge']}mm ledge "
                f"remains beyond the {p['ledge_max']}mm allowance -- "
                f"the real fix is raising/doming the roof")
        params.append(p)
    blocked = [f["repair_blocked"] for f in features
               if f.get("repair_blocked")]
    return params, blocked


# --------------------------------------------------- parametric preview

def _circle_ring(c, n=64, r=None):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    rr = c["r"] if r is None else r
    return np.stack([c["cx"] + rr * np.cos(a),
                     c["cy"] + rr * np.sin(a)], axis=1)


def body_from_params(p):
    """Rebuild the snippet's geometry as a watertight mesh (same
    radii/z, circular contours) so the patch can be re-audited BEFORE
    the user pastes it. Uses the same builders as Stage B."""
    from dfam_repair import build_body, _max_gap
    top = _circle_ring(p["top"])
    bot = _circle_ring(p["bot"])
    spec = {
        "kind": p["kind"], "feature": p["feature"],
        "z_top": p["z_top"], "z_bot": p["z_bot"],
        "z_floor": p["z_floor"], "min_h": p["min_h"],
        "max_gap": float(_max_gap(bot, top)),
        "angle": p["angle"], "dz": p["dz"],
        "drill": [_circle_ring(v, n=24).tolist() for v in p["vents"]],
        "top": top.tolist(), "bot": bot.tolist(),
    }
    if p["kind"] in ("roofcone", "skirt"):
        spec["z_close"] = p["z_close"]
    return build_body(spec)


def verify_params(before, params, profile):
    """Union the parametric preview bodies and re-audit. Returns
    (verdict, after_result, notes)."""
    import stalagmite
    from dfam_fix import union_bodies, decide_verdict
    bodies = [body_from_params(p) for p in params]
    fixed, engine, notes = union_bodies(before.mesh, bodies)
    after = stalagmite.check(fixed, profile=profile,
                             exclude=[tuple(e) if not isinstance(e, tuple)
                                      else e for e in before.exclude],
                             keep=before.keep, suggest=False, lint=False)
    verdict, _ = decide_verdict(before.features, after.features)
    return verdict, after, notes


# ------------------------------------------------------------- OpenSCAD

def _scad_fix(p, n):
    k, t, b = p["kind"], p["top"], p["bot"]
    zt, zb, zc = p["z_top"], p["z_bot"], p["z_close"]
    head = [f"// fix {n}: {k} for {p['cls']} at "
            f"z{zb:g}-{zt:g}  (circle-fit of the audited contours)",
            f"//   bottom r={b['r']}mm (max dev {b['dev']}mm), "
            f"top r={t['r']}mm (max dev {t['dev']}mm)"]
    head += [f"// WARNING: {w}" for w in p["warnings"]]
    L = [f"module stalagmite_fix_{n}() {{"]
    if k == "roofcone":
        h = zt - zb
        slope = (b["r"] - t["r"]) / max(zc - zb, 1e-9)
        r1e = b["r"] + slope * EPS
        L += ["  difference() {",
              f"    translate([{b['cx']}, {b['cy']}, {zb}]) "
              f"cylinder(h={_g(h)}, r={b['r']}, $fn={FN});",
              f"    // chamfer cone: the new printable underside",
              f"    translate([{b['cx']}, {b['cy']}, {_g(zb - EPS)}]) "
              f"cylinder(h={_g(zc - zb + EPS)}, r1={_g(r1e)}, "
              f"r2={t['r']}, $fn={FN});",
              f"    // keep the bore open through the weld band",
              f"    translate([{b['cx']}, {b['cy']}, {_g(zb - EPS)}]) "
              f"cylinder(h={_g(h + 2 * EPS)}, r={t['r']}, $fn={FN});"]
        for v in p["vents"]:
            L.append(f"    translate([{v['cx']}, {v['cy']}, {_g(zb - EPS)}])"
                     f" cylinder(h={_g(h + 2 * EPS)}, r={v['r']}, "
                     f"$fn={FN});  // vent shaft (kept clear)")
        L.append("  }")
    elif k == "skirt":
        h = zt - zb
        L += ["  // external annular chamfer under the overhanging rim",
              "  difference() {",
              f"    translate([{b['cx']}, {b['cy']}, {zb}]) "
              f"cylinder(h={_g(h)}, r1={_g(b['r'] + 0.3)}, "
              f"r2={t['r']}, $fn={FN});",
              f"    // keep the tube hollow (0.3mm bite welds the wall)",
              f"    translate([{b['cx']}, {b['cy']}, {_g(zb - EPS)}]) "
              f"cylinder(h={_g(h + 2 * EPS)}, r={b['r']}, $fn={FN});",
              "  }"]
    else:                                   # loft / pillar
        zb2 = p["z_floor"] if k == "pillar" else zb
        L += [f"  // {'bed pillar' if k == 'pillar' else 'loft'}: "
              f"hull between landing and defect (convex contours only)",
              "  hull() {",
              f"    translate([{b['cx']}, {b['cy']}, {zb2}]) "
              f"cylinder(h=0.02, r={b['r']}, $fn={FN});",
              f"    translate([{t['cx']}, {t['cy']}, {_g(zt - 0.02)}]) "
              f"cylinder(h=0.02, r={t['r']}, $fn={FN});",
              "  }"]
    L.append("}")
    return "\n".join(head + L)


def emit_openscad(params, blocked, meta):
    out = [f"// stalagmite patch -- {meta.get('part', 'part')} "
           f"({meta.get('profile', 'generic-fdm')})",
           "// Stage D: paste these modules into your ORIGINAL design,",
           "// union stalagmite_patch() with your part, re-export the",
           "// STL and run stalagmite again -- the audit is the judge.",
           ""]
    for i, p in enumerate(params, 1):
        out += [_scad_fix(p, i), ""]
    if params:
        calls = "\n".join(f"    stalagmite_fix_{i}();"
                          for i in range(1, len(params) + 1))
        out += ["module stalagmite_patch() {", "  union() {", calls,
                "  }", "}", "",
                "// preview when opened directly; DELETE this call after",
                "// pasting -- your design should call it instead:",
                "//   union() { your_part(); stalagmite_patch(); }",
                "stalagmite_patch();"]
    for msg in blocked:
        out += ["", "// NOT EMITTED (audit refused a geometric repair):",
                "// " + msg.replace("\n", "\n// ")]
    return "\n".join(out) + "\n"


# ------------------------------------------------------------- CadQuery

def _cq_fix(p, n):
    k, t, b = p["kind"], p["top"], p["bot"]
    zt, zb, zc = p["z_top"], p["z_bot"], p["z_close"]
    doc = [f'    """fix {n}: {k} for {p["cls"]} at z{zb:g}-{zt:g}',
           f"    bottom r={b['r']}mm (max dev {b['dev']}mm), "
           f"top r={t['r']}mm (max dev {t['dev']}mm)"]
    doc += [f"    WARNING: {w}" for w in p["warnings"]]
    doc.append('    """')
    L = [f"def stalagmite_fix_{n}():"] + doc
    if k == "roofcone":
        h = zt - zb
        slope = (b["r"] - t["r"]) / max(zc - zb, 1e-9)
        r1e = b["r"] + slope * EPS
        L += [f"    body = cq.Solid.makeCylinder({b['r']}, {_g(h)}, "
              f"cq.Vector({b['cx']}, {b['cy']}, {zb}))",
              f"    # chamfer cone: the new printable underside",
              f"    body = body.cut(cq.Solid.makeCone({_g(r1e)}, "
              f"{t['r']}, {_g(zc - zb + EPS)}, "
              f"cq.Vector({b['cx']}, {b['cy']}, {_g(zb - EPS)})))",
              f"    # keep the bore open through the weld band",
              f"    body = body.cut(cq.Solid.makeCylinder({t['r']}, "
              f"{_g(h + 2 * EPS)}, "
              f"cq.Vector({b['cx']}, {b['cy']}, {_g(zb - EPS)})))"]
        for v in p["vents"]:
            L.append(f"    body = body.cut(cq.Solid.makeCylinder("
                     f"{v['r']}, {_g(h + 2 * EPS)}, cq.Vector({v['cx']}, "
                     f"{v['cy']}, {_g(zb - EPS)})))  # vent shaft")
        L.append("    return body")
    elif k == "skirt":
        h = zt - zb
        L += [f"    # external annular chamfer under the overhanging rim",
              f"    body = cq.Solid.makeCone({_g(b['r'] + 0.3)}, "
              f"{t['r']}, {_g(h)}, cq.Vector({b['cx']}, {b['cy']}, {zb}))",
              f"    # keep the tube hollow (0.3mm bite welds the wall)",
              f"    body = body.cut(cq.Solid.makeCylinder({b['r']}, "
              f"{_g(h + 2 * EPS)}, "
              f"cq.Vector({b['cx']}, {b['cy']}, {_g(zb - EPS)})))",
              "    return body"]
    else:                                   # loft / pillar
        zb2 = p["z_floor"] if k == "pillar" else zb
        L += [f"    # {'bed pillar' if k == 'pillar' else 'loft'}: "
              f"circle-to-circle loft (convex contours only)",
              f"    return (cq.Workplane('XY')",
              f"            .workplane(offset={zb2})"
              f".center({b['cx']}, {b['cy']})",
              f"            .circle({b['r']})",
              f"            .workplane(offset={_g(zt - zb2)})"
              f".center({_g(t['cx'] - b['cx'])}, "
              f"{_g(t['cy'] - b['cy'])})",
              f"            .circle({t['r']})",
              f"            .loft(combine=False).val())"]
    return "\n".join(L)


def emit_cadquery(params, blocked, meta):
    out = [f"# stalagmite patch -- {meta.get('part', 'part')} "
           f"({meta.get('profile', 'generic-fdm')})",
           "# Stage D: paste into your ORIGINAL CadQuery design, union",
           "# stalagmite_patch() with your part, re-export the STL and",
           "# run stalagmite again -- the audit is the judge.",
           "import cadquery as cq", ""]
    for i, p in enumerate(params, 1):
        out += [_cq_fix(p, i), ""]
    if params:
        names = ", ".join(f"stalagmite_fix_{i}()"
                          for i in range(1, len(params) + 1))
        out += ["def stalagmite_patch():",
                f"    parts = [{names}]",
                "    out = parts[0]",
                "    for s in parts[1:]:",
                "        out = out.fuse(s)",
                "    return out", "",
                "# USAGE in your design:",
                "#   result = your_wp.union(cq.Workplane(obj="
                "stalagmite_patch()))",
                "if 'show_object' in globals():   # CQ-editor preview",
                "    show_object(cq.Workplane(obj=stalagmite_patch()))"]
    for msg in blocked:
        out += ["", "# NOT EMITTED (audit refused a geometric repair):",
                "# " + msg.replace("\n", "\n# ")]
    return "\n".join(out) + "\n"


EMITTERS = {"openscad": (emit_openscad, ".scad"),
            "cadquery": (emit_cadquery, ".py")}


# ------------------------------------------------------------------ CLI

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Emit stalagmite's repairs as design source "
                    "(OpenSCAD / CadQuery) to paste into the original "
                    "model.")
    ap.add_argument("stl")
    ap.add_argument("--lang", choices=sorted(EMITTERS), default="openscad")
    ap.add_argument("-o", "--out", default=None,
                    help="output path (default: <name>_patch.scad/.py)")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--profile-file", default=None)
    ap.add_argument("--auto-ex", action="store_true")
    ap.add_argument("--ex", action="append", default=[])
    ap.add_argument("--keep", action="append", default=[],
                    metavar="ZLO:ZHI:RMAX[:CX:CY]")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the parametric-preview re-audit")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    import dfam_profiles
    try:
        prof = dfam_profiles.resolve(a.profile, a.profile_file)
    except (KeyError, OSError, ValueError) as e:
        ap.error(str(e))
    emit, ext = EMITTERS[a.lang]
    out_path = a.out or (os.path.splitext(a.stl)[0] + "_patch" + ext)
    say = (lambda *x: None) if a.json else print
    try:
        import stalagmite
        from dfam_intent import parse_keep
        keep = parse_keep(a.keep)
        ex = [tuple(map(float, e.split(":"))) for e in a.ex]
        say(f"== stalagmite patch: {a.stl} ==")
        say(f"   {prof.summary_line()}")
        r = stalagmite.check(a.stl, profile=prof, exclude=ex,
                             auto_ex=a.auto_ex, keep=keep, suggest=False)
        params, blocked = fix_params(
            r.mesh, r.features, prof.dz, prof.angle, keep=keep,
            avoid=r.exclude, ledge_max=prof.ledge_max)
    except (ValueError, OSError) as e:
        if a.json:
            print(json.dumps({"verdict": "ERROR", "error": str(e),
                              "exit_code": 2}))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 2
    if not params and not blocked and r.fails == 0:
        say("NOTHING_TO_PATCH -- no fail-severity defects.")
        if a.json:
            print(json.dumps({"verdict": "NOTHING_TO_PATCH",
                              "fixes": [], "blocked": [],
                              "exit_code": 0}))
        return 0
    verdict, notes = None, []
    if params and not a.no_verify:
        verdict, after, notes = verify_params(r, params, prof)
        say(f"parametric preview re-audit: {verdict} "
            f"(after: {after.status}, {after.fails} fail)")
    text = emit(params, blocked, {"part": os.path.basename(a.stl),
                                  "profile": prof.summary_line()})
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    say(f"patch source written: {out_path} "
        f"({len(params)} fix(es), {len(blocked)} blocked)")
    for w in [w for p in params for w in p["warnings"]]:
        say(f"  warning: {w}")
    for msg in blocked:
        say(f"  blocked: {msg.splitlines()[0]}")
    ok = bool(params) and (verdict in (None, "VERIFIED")) and not blocked
    code = 0 if ok else 1
    if a.json:
        print(json.dumps({"wrote": out_path, "lang": a.lang,
                          "fixes": params, "blocked": blocked,
                          "verdict": verdict, "exit_code": code}))
    return code


if __name__ == "__main__":
    sys.exit(main())
