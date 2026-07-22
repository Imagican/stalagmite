"""Tests for stalagmite-fix (Stage B): verdict logic, the apply->verify
pipeline, the never-worse guarantee, CLI contract, API, GUI endpoint."""
import io
import os
import json
import contextlib

import pytest
import trimesh

import dfam_fix
from dfam_audit import audit_mesh, aggregate, overall_status, load_mesh
from dfam_fix import apply_fixes, decide_verdict

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
EX_EARLY = [(0, 16.5, 11), (44, 55, 13)]


# ------------------------------------------------- verdict logic (pure)

def F(sev, cls="steep-growth", z=(10, 11), c=(0, 0)):
    from shapely.geometry import Point
    from dfam_audit import Violation
    g = Point(*c).buffer(2.0)
    v = Violation(z[0], g.area, 4.0, c, "unsupported", g,
                  cls=cls, severity=sev, ledge=1.0)
    return {"cls": cls, "severity": sev, "zlo": z[0], "zhi": z[1],
            "layers": [v], "geom": g}


def test_verdict_nothing_to_fix():
    v, d = decide_verdict([F("judge", "bridge")], [F("judge", "bridge")])
    assert v == "NOTHING_TO_FIX"


def test_verdict_verified():
    before = [F("fail"), F("judge", "bridge", c=(30, 0))]
    after = [F("judge", "bridge", c=(30, 0))]
    v, d = decide_verdict(before, after)
    assert v == "VERIFIED" and d["fails_after"] == 0


def test_verdict_partial():
    before = [F("fail", c=(0, 0)), F("fail", c=(40, 0))]
    after = [F("fail", c=(40, 0))]
    v, d = decide_verdict(before, after)
    assert v == "PARTIAL"


def test_verdict_not_improved_on_new_fail():
    before = [F("fail", c=(0, 0))]
    after = [F("tolerable", c=(0, 0)), F("fail", cls="island", c=(40, 0))]
    v, d = decide_verdict(before, after)
    assert v == "NOT_IMPROVED" and d["new_fails"]


def test_verdict_not_improved_when_worsened():
    before = [F("fail", c=(0, 0)), F("tolerable", c=(40, 0))]
    after = [F("fail", c=(40, 0))]          # first resolved, second worsened
    v, d = decide_verdict(before, after)
    assert v == "NOT_IMPROVED" and d["worsened"]


# ----------------------------------------------------- the real pipeline

def test_apply_fixes_fixture01_verified():
    """The headline: the worst fixture is repaired and PROVEN repaired."""
    m = load_mesh(os.path.join(FIX, "01_teardrop_point_up.stl"))
    r = apply_fixes(m, exclude=EX_EARLY)
    assert r.status_before == "FAIL"
    assert r.verdict == "VERIFIED"
    assert r.status_after in ("REVIEW", "PASS_WITH_LIMITS", "PASS")
    assert r.detail["fails_after"] == 0
    assert r.n_bodies >= 1 and r.exit_code == 0
    assert r.ok_to_write
    d = r.to_dict()
    json.dumps(d)
    assert d["verdict"] == "VERIFIED" and d["resolved"]


def test_apply_fixes_clean_part_nothing_to_do():
    box = trimesh.creation.box(extents=[10, 10, 10])
    box.apply_translation([0, 0, 5])
    r = apply_fixes(box)
    assert r.verdict == "NOTHING_TO_FIX" and r.n_bodies == 0
    assert r.exit_code == 0


def test_api_fix():
    import stalagmite
    r = stalagmite.fix(os.path.join(FIX, "02_teardrop_floating.stl"),
                       exclude=EX_EARLY)
    assert r.status_before == "FAIL"
    assert r.verdict in ("VERIFIED", "PARTIAL")
    assert r.detail["fails_after"] < r.detail["fails_before"]


# -------------------------------------------------------------- the CLI

def test_cli_fix_writes_and_reports(tmp_path):
    out = str(tmp_path / "fixed.stl")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dfam_fix.main([os.path.join(FIX,
                              "01_teardrop_point_up.stl"),
                              "-o", out,
                              "--ex", "0:16.5:11", "--ex", "44:55:13"])
    text = buf.getvalue()
    assert code == 0
    assert os.path.exists(out)
    assert "FIX: VERIFIED" in text and "RESOLVED" in text
    fixed = trimesh.load(out, force="mesh")
    assert len(fixed.faces) > 1000
    # and the written file re-audits clean of fails, independently
    _, v = audit_mesh(load_mesh(out), exclude=EX_EARLY)
    feats = aggregate(v, 0.4)
    assert not any(f["severity"] == "fail" for f in feats)


def test_cli_fix_json(tmp_path):
    out = str(tmp_path / "fixed.stl")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dfam_fix.main([os.path.join(FIX,
                              "01_teardrop_point_up.stl"),
                              "-o", out, "--json",
                              "--ex", "0:16.5:11", "--ex", "44:55:13"])
    payload = json.loads(buf.getvalue())
    assert code == 0
    assert payload["verdict"] == "VERIFIED"
    assert payload["wrote"] == out
    assert payload["status_before"] == "FAIL"
    assert payload["fails_after"] == 0


def test_cli_fix_error_exit2(tmp_path):
    err = io.StringIO()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        code = dfam_fix.main([str(tmp_path / "missing.stl")])
    assert code == 2 and "error:" in err.getvalue()


def test_cli_fix_nothing_to_fix(tmp_path):
    box = trimesh.creation.box(extents=[10, 10, 10])
    box.apply_translation([0, 0, 5])
    p = str(tmp_path / "box.stl")
    box.export(p)
    out = str(tmp_path / "box_fixed.stl")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dfam_fix.main([p, "-o", out])
    assert code == 0
    assert "NOTHING_TO_FIX" in buf.getvalue()
    assert not os.path.exists(out)          # nothing written


# -------------------------------------------------------------- the GUI

def test_gui_fix_endpoint():
    import dfam_gui
    raw = open(os.path.join(FIX, "01_teardrop_point_up.stl"), "rb").read()
    out = dfam_gui.run_fix(raw, "01.stl", "generic-fdm", True)
    assert out["ok"] and out["verdict"] == "VERIFIED"
    assert out["status_before"] == "FAIL"
    assert out["stl_b64"] and out["stl_name"].endswith("_fixed.stl")
    assert "fixed_report" in out and "REVIEW" in out["fixed_report"]
    json.dumps({k: v for k, v in out.items() if k != "fixed_report"})


# ------------------------------------------------ sculpt-driven fixing

def _entry(f, **kw):
    c = f["geom"].centroid
    return dict(cls=f["cls"], zlo=float(f["zlo"]), zhi=float(f["zhi"]),
                cx=float(c.x), cy=float(c.y),
                optional=f["severity"] != "fail", **kw)


def test_apply_fixes_with_sculpt_settings():
    """Sculptor settings drive the applied bodies: a taller chamfer
    reaches deeper down the cavity than the default."""
    import stalagmite
    from test_roofcone import cap, hole_areas
    r0 = stalagmite.check(cap())
    fail = next(f for f in r0.features if f["severity"] == "fail")
    r = apply_fixes(stalagmite.to_mesh(cap()),
                    sculpt=[_entry(fail, height=14.0, easing=1.2)])
    assert r.verdict == "VERIFIED"
    rc = next(s for s in r.specs if s["kind"] == "roofcone")
    z_probe = rc["z_close"] - 12.0          # below default reach (~10.8)
    sculpted = min(hole_areas(r.mesh_fixed, z_probe))
    stock = min(hole_areas(apply_fixes(
        stalagmite.to_mesh(cap())).mesh_fixed, z_probe))
    assert sculpted < stock - 20            # taller cone narrowed it


def test_sculpt_opts_in_optional_and_stays_honest():
    """Opting the rim skirt in adds a body; the skirt is ANNULAR (the
    cavity must NOT be plugged -- the fan-cap loft regression); and the
    verdict stays honest (the thread-blocked crescent still fails)."""
    import os
    import stalagmite
    from shapely.geometry import Polygon
    from dfam_audit import slice_region
    FLAT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "examples", "flat_roof.stl")
    if not os.path.exists(FLAT):
        import pytest
        pytest.skip("user example not present")
    r0 = stalagmite.check(FLAT, auto_ex=True)
    tol = next(f for f in r0.features if f["severity"] == "tolerable")
    fail = next(f for f in r0.features if f["severity"] == "fail")
    r = apply_fixes(stalagmite.to_mesh(FLAT), exclude=r0.exclude,
                    sculpt=[_entry(fail),
                            _entry(tol, height=3.5, easing=1.8)])
    assert [s["kind"] for s in r.specs] == ["roofcone", "skirt"]
    assert r.n_bodies == 2
    assert r.verdict == "NOT_IMPROVED"      # crescent honestly remains
    # the cavity survives: skirt did not plug the interior
    s = slice_region(r.mesh_fixed, 5.0)
    ps = [s] if s.geom_type == "Polygon" else list(s.geoms)
    holes = [abs(Polygon(i).area) for p in ps for i in p.interiors]
    assert holes and max(holes) > 500


def test_sculpt_concentric_twins_resolve_by_severity():
    """flat_roof's fail and tolerable are CONCENTRIC same-class rings:
    with GUI-rounded coords both entries used to match the fail and the
    skirt silently vanished. The optional flag now gates severity."""
    import os
    import stalagmite
    FLAT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "examples", "flat_roof.stl")
    if not os.path.exists(FLAT):
        import pytest
        pytest.skip("user example not present")
    r0 = stalagmite.check(FLAT, auto_ex=True)

    def gui_entry(f, **kw):
        c = f["geom"].centroid
        return dict(cls=f["cls"], zlo=round(float(f["zlo"]), 1),
                    zhi=round(float(f["zhi"]), 1),
                    cx=round(float(c.x), 1), cy=round(float(c.y), 1),
                    optional=f["severity"] != "fail", **kw)
    tol = next(f for f in r0.features if f["severity"] == "tolerable")
    fail = next(f for f in r0.features if f["severity"] == "fail")
    r = apply_fixes(stalagmite.to_mesh(FLAT), exclude=r0.exclude,
                    sculpt=[gui_entry(fail),
                            gui_entry(tol, height=3.5, easing=1.8)])
    assert [s["kind"] for s in r.specs] == ["roofcone", "skirt"]
    assert r.n_bodies == 2


def test_sculpt_unmatched_entry_noted():
    box = trimesh.creation.box(extents=[10, 10, 10])
    box.apply_translation([0, 0, 5])
    shelf = trimesh.creation.box(extents=[9, 10, 2])
    shelf.apply_translation([5 + 4.5 - 0.5, 0, 4])
    m = trimesh.util.concatenate([box, shelf])
    r = apply_fixes(m, sculpt=[{"cls": "island", "zlo": 99.0,
                                "zhi": 99.0, "cx": 0, "cy": 0,
                                "optional": False, "height": 5.0}])
    assert any("did not match" in n for n in r.notes)


def test_gui_not_improved_shows_attempt():
    """NOT_IMPROVED must still return the re-audited attempt: report
    loaded in the viewer + honestly-named forced-download STL."""
    import os
    import dfam_gui
    FLAT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "examples", "flat_roof.stl")
    if not os.path.exists(FLAT):
        import pytest
        pytest.skip("user example not present")
    raw = open(FLAT, "rb").read()
    out = dfam_gui.run_fix(raw, "flat_roof.stl", "generic-fdm", True)
    assert out["verdict"] == "NOT_IMPROVED"
    assert "fixed_report" in out                 # evidence always shown
    assert out["stl_name"].endswith("_attempt_FAILS.stl")
    assert out["stl_b64"]                        # forced path available


def test_report_ships_persistent_ghosts():
    import stalagmite
    from test_roofcone import cap
    import tempfile
    import os as _os
    r = stalagmite.check(cap())
    p = tempfile.NamedTemporaryFile(suffix=".html", delete=False).name
    try:
        r.write_report(p)
        text = open(p, encoding="utf-8").read()
        assert "refreshAllGhosts" in text and "ghostAll" in text
    finally:
        _os.unlink(p)


def test_report_partial_badge_keeps_slope_readout():
    """v0.34: the over_allowance badge must APPEND the live cone-slope
    line, not replace it -- hiding the readout is how the user ended up
    with an over-eased sculpt that silently exceeded the angle."""
    import stalagmite
    from test_roofcone import cap
    import tempfile
    import os as _os
    r = stalagmite.check(cap())
    p = tempfile.NamedTemporaryFile(suffix=".html", delete=False).name
    try:
        r.write_report(p)
        text = open(p, encoding="utf-8").read()
        assert "cone surface OK" in text
        assert "cone surface EXCEEDS" in text
        assert "reduce easing" in text
    finally:
        _os.unlink(p)
