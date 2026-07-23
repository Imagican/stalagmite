"""Stage D: repairs emitted as design source (OpenSCAD / CadQuery).

The contract under test: snippets are honest circle fits (deviations
declared, non-circular contours warned), the parametric preview is
re-audited before anything is written, blocked repairs become comments
quoting the audit, and -- where a real OpenSCAD binary exists -- the
EMITTED SOURCE ITSELF renders to a solid that provably repairs the
part. Language emitters must stay in lockstep: same numbers, same
warnings, both compile/parse.
"""
import io
import json
import os
import shutil
import subprocess
import contextlib

import numpy as np
import pytest
import trimesh

import stalagmite
import dfam_patch
from test_roofcone import cap, cap_vent

HERE = os.path.dirname(os.path.abspath(__file__))
FLAT = os.path.join(HERE, "examples", "flat_roof.stl")


def _mushroom():
    """Stem r6 + cap r12: the rim overhang lofts down to the stem."""
    stem = trimesh.creation.cylinder(radius=6, height=10, sections=64)
    stem.apply_translation([0, 0, 5])
    top = trimesh.creation.cylinder(radius=12, height=4, sections=64)
    top.apply_translation([0, 0, 12])
    return trimesh.util.concatenate([stem, top])


def _run_main(args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dfam_patch.main(args)
    return code, buf.getvalue()


# ------------------------------------------------------------ circle fit

def test_fit_circle_recovers_center_and_radius():
    a = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    ring = np.stack([3 + 7 * np.cos(a), -2 + 7 * np.sin(a)], axis=1)
    cx, cy, r, dev = dfam_patch.fit_circle(ring)
    assert abs(cx - 3) < 1e-6 and abs(cy + 2) < 1e-6
    assert abs(r - 7) < 1e-6 and dev < 1e-6


def test_noncircular_contour_gets_warning():
    """The rectangular-ledge part: a circle is a bad fit and the
    snippet must say so instead of pretending."""
    base = trimesh.creation.box(extents=[30, 20, 10])
    base.apply_translation([0, 0, 5])
    ledge = trimesh.creation.box(extents=[50, 28, 4])
    ledge.apply_translation([0, 0, 12])
    part = trimesh.util.concatenate([base, ledge])
    r = stalagmite.check(part, suggest=False)
    params, _ = dfam_patch.fix_params(r.mesh, r.features)
    assert params
    warns = [w for p in params for w in p["warnings"]]
    assert any("not circular" in w for w in warns)
    scad = dfam_patch.emit_openscad(params, [], {})
    assert "WARNING" in scad and "not circular" in scad


# ------------------------------------------------------- cap (roofcone)

def test_cap_roofcone_scad_written_and_verified(tmp_path):
    p = str(tmp_path / "cap.stl")
    cap_vent().export(p)
    out = str(tmp_path / "cap_patch.scad")
    code, said = _run_main([p, "-o", out])
    assert code == 0
    assert "VERIFIED" in said
    text = open(out).read()
    assert "module stalagmite_fix_1()" in text
    assert "stalagmite_patch();" in text
    assert "vent shaft" in text                  # bore/vent kept open
    assert "r2=" in text                         # a real cone, not a plug


def test_cap_cadquery_compiles_and_matches(tmp_path):
    p = str(tmp_path / "cap.stl")
    cap_vent().export(p)
    out = str(tmp_path / "cap_patch.py")
    code, said = _run_main([p, "--lang", "cadquery", "-o", out])
    assert code == 0
    text = open(out).read()
    compile(text, out, "exec")                   # syntactically sound
    assert "makeCone" in text and "vent shaft" in text
    assert "def stalagmite_patch()" in text


# ------------------------------------------------------------- mushroom

def test_mushroom_is_loft_and_preview_improves():
    r = stalagmite.check(_mushroom(), suggest=False)
    assert r.fails > 0
    params, blocked = dfam_patch.fix_params(r.mesh, r.features)
    assert params and not blocked
    assert any(p["kind"] == "loft" for p in params)
    for p in params:
        body = dfam_patch.body_from_params(p)
        assert body.is_watertight and body.volume > 0
    verdict, after, _ = dfam_patch.verify_params(r, params, _prof())
    assert verdict in ("VERIFIED", "PARTIAL")
    assert after.fails < r.fails
    scad = dfam_patch.emit_openscad(params, [], {})
    assert "hull()" in scad
    cq = dfam_patch.emit_cadquery(params, [], {})
    compile(cq, "<cq>", "exec")
    assert ".loft(" in cq


def _prof():
    import dfam_profiles
    return dfam_profiles.resolve(None, None)


# ------------------------------------------------------- pillar (synth)

def test_pillar_params_emit_from_bed():
    p = {"feature": 0, "kind": "pillar", "cls": "island",
         "severity": "fail", "z_top": 8.0, "z_bot": 0.0, "z_close": 8.0,
         "z_floor": 0.0, "min_h": 2.0, "angle": 45.0, "dz": 0.4,
         "top": {"cx": 5.0, "cy": 1.0, "r": 4.0, "dev": 0.01},
         "bot": {"cx": 5.0, "cy": 1.0, "r": 4.0, "dev": 0.01},
         "vents": [], "over_allowance": False, "residual_ledge": None,
         "ledge_max": None, "warnings": []}
    scad = dfam_patch.emit_openscad([p], [], {})
    assert "hull()" in scad and "bed pillar" in scad
    cq = dfam_patch.emit_cadquery([p], [], {})
    compile(cq, "<cq>", "exec")
    body = dfam_patch.body_from_params(p)
    assert body.is_watertight
    assert body.bounds[0][2] >= -1e-6            # sits on the bed


# ------------------------------------------- flat_roof: honest failure

def test_flat_roof_blocked_note_and_partial_warning(tmp_path):
    out = str(tmp_path / "fr_patch.scad")
    code, said = _run_main([FLAT, "--auto-ex", "-o", out, "--json"])
    assert code == 1                             # honesty: not fixed
    d = json.loads(said.splitlines()[-1])
    assert d["verdict"] == "NOT_IMPROVED"
    assert d["blocked"]
    text = open(out).read()
    assert "NOT EMITTED" in text
    assert "PARTIAL closure" in text
    assert "raising/doming the roof" in text


def test_nothing_to_patch_exits_zero(tmp_path):
    box = trimesh.creation.box(extents=[10, 10, 10])
    box.apply_translation([0, 0, 5])
    p = str(tmp_path / "box.stl")
    box.export(p)
    code, said = _run_main([p])
    assert code == 0 and "NOTHING_TO_PATCH" in said
    assert not os.path.exists(str(tmp_path / "box_patch.scad"))


# ---------------------------------------- gold standard: real OpenSCAD

@pytest.mark.skipif(shutil.which("openscad") is None,
                    reason="openscad binary not installed")
def test_emitted_scad_renders_and_repairs(tmp_path):
    """Render the EMITTED SOURCE with real OpenSCAD, union the result,
    re-audit: FAIL -> PASS. The strongest possible Stage D claim."""
    from dfam_fix import union_bodies, decide_verdict
    p = str(tmp_path / "cap.stl")
    cap_vent().export(p)
    out = str(tmp_path / "cap_patch.scad")
    code, _ = _run_main([p, "-o", out, "--no-verify"])
    stl = str(tmp_path / "patch.stl")
    r = subprocess.run(["openscad", "-o", stl, out],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]
    body = trimesh.load(stl)
    assert body.is_watertight
    before = stalagmite.check(p, suggest=False)
    fixed, _, _ = union_bodies(before.mesh, [body])
    after = stalagmite.check(fixed, suggest=False, lint=False)
    verdict, _ = decide_verdict(before.features, after.features)
    assert verdict == "VERIFIED"
    assert after.status == "PASS" and after.fails == 0


# ------------------------------------------------------------ GUI hooks

def test_gui_run_patch_both_langs(tmp_path):
    """The viewer's 'Patch source' button: bytes -> emitted text +
    honest preview verdict, both languages."""
    import dfam_gui
    p = str(tmp_path / "cap.stl")
    cap_vent().export(p)
    raw = open(p, "rb").read()
    for lang, marker in (("openscad", "module stalagmite_fix_1"),
                         ("cadquery", "def stalagmite_fix_1")):
        d = dfam_gui.run_patch(raw, "cap.stl", "", False, lang)
        assert d["ok"] and not d["nothing"]
        assert d["verdict"] == "VERIFIED" and d["after_status"] == "PASS"
        assert marker in d["text"]
        assert d["fname"].startswith("cap_patch")
    bad = dfam_gui.run_patch(raw, "cap.stl", "", False, "brep")
    assert not bad["ok"]


def test_gui_landing_has_patch_button():
    import dfam_gui
    h = dfam_gui._landing()
    for frag in ("v-patch", "v-lang", "/patch", "cadquery"):
        assert frag in h, frag
