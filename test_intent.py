"""Tests for design-intent keep-clear zones (dfam_intent): parsing,
annotation, repair blocking, CLI plumbing, the CadQuery-style on-ramp."""
import io
import os
import json
import contextlib

import numpy as np
import pytest
import trimesh

import dfam_audit
import dfam_fix
import stalagmite
from dfam_intent import (parse_keep, geom_hits, annotate_features,
                         body_blocked, zone_from_bounds)

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
F01 = os.path.join(FIX, "01_teardrop_point_up.stl")
EX = [(0, 16.5, 11), (44, 55, 13)]
EX_ARGS = ["--ex", "0:16.5:11", "--ex", "44:55:13"]
# fixture 01's boss defect: fail steep-growth z 29.5-30.3 @ (17.4, 0)
BOSS_KEEP = (25.0, 33.0, 6.0, 17.4, 0.0)


# ------------------------------------------------------------- plumbing

def test_parse_keep():
    assert parse_keep(["1:2:3"]) == [(1.0, 2.0, 3.0)]
    assert parse_keep(["1:2:3:4:5"]) == [(1.0, 2.0, 3.0, 4.0, 5.0)]
    with pytest.raises(ValueError, match="zlo:zhi:rmax"):
        parse_keep(["1:2"])
    with pytest.raises(ValueError, match="numbers"):
        parse_keep(["a:b:c"])
    with pytest.raises(ValueError):
        parse_keep(["5:2:3"])          # zhi <= zlo
    with pytest.raises(ValueError):
        parse_keep(["1:2:0"])          # rmax <= 0


def test_geom_hits_z_and_xy_gating():
    from shapely.geometry import Point
    g = Point(0, 0).buffer(2)
    zones = [(10.0, 20.0, 5.0)]                  # centred at origin
    assert geom_hits(g, 12, 14, zones) == [0]    # inside
    assert geom_hits(g, 25, 30, zones) == []     # above in z
    far = Point(50, 0).buffer(2)
    assert geom_hits(far, 12, 14, zones) == []   # out of radius


def test_body_blocked():
    cube = trimesh.creation.box(extents=[4, 4, 4])
    cube.apply_translation([0, 0, 12])
    assert body_blocked(cube, [(10.0, 14.0, 5.0)])
    assert not body_blocked(cube, [(30.0, 40.0, 5.0)])      # z misses
    assert not body_blocked(cube, [(10.0, 14.0, 5.0, 50.0, 0.0)])


def test_zone_from_bounds_and_keep_zone():
    z = zone_from_bounds(((0, 0, 5), (10, 10, 8)), pad=1.0)
    zlo, zhi, rmax, cx, cy = z
    assert (zlo, zhi) == (4.0, 9.0)
    assert (cx, cy) == (5.0, 5.0)
    assert rmax == pytest.approx(np.hypot(10, 10) / 2 + 1.0)
    # stalagmite.keep_zone accepts a trimesh and point arrays
    cube = trimesh.creation.box(extents=[2, 2, 2])
    assert stalagmite.keep_zone(cube, pad=0.5)[2] > 0
    pts = np.array([[0, 0, 0], [4, 0, 0], [0, 3, 2]])
    zlo2, zhi2, r2, *_ = stalagmite.keep_zone(pts, pad=0.0)
    assert (zlo2, zhi2) == (0.0, 2.0) and r2 == pytest.approx(2.5)


# ----------------------------------------------------- audit annotation

def test_check_annotates_and_serialises():
    r = stalagmite.check(F01, exclude=EX, keep=[BOSS_KEEP])
    tagged = [f for f in r.features if f.get("intent_hits")]
    assert len(tagged) == 1
    assert tagged[0]["severity"] == "fail"
    assert abs(tagged[0]["geom"].centroid.x - 17.4) < 1.0
    d = r.to_dict()
    json.dumps(d)
    assert d["keep_zones"] == [list(BOSS_KEEP)]
    assert any(f.get("intent_hits") == [0] for f in d["features"])
    # without keep, the key is absent (stable interface, additive only)
    d0 = stalagmite.check(F01, exclude=EX).to_dict()
    assert d0["keep_zones"] == []
    assert not any("intent_hits" in f for f in d0["features"])


def test_annotate_features_counts():
    r = stalagmite.check(F01, exclude=EX)
    n = annotate_features(r.features, [BOSS_KEEP])
    assert n == 1


# ------------------------------------------------------ repair blocking

def test_fix_blocks_repair_on_functional_surface():
    """The headline: with the boss declared functional, its repair is
    withheld; the cone still gets fixed; the verdict is honest."""
    r = stalagmite.fix(F01, exclude=EX, keep=[BOSS_KEEP])
    assert r.verdict == "PARTIAL"                # cone fixed, boss not
    assert r.n_bodies == 1                       # one body dropped
    assert any("keep-clear" in n for n in r.notes)
    assert r.detail["fails_after"] == 1
    # and WITHOUT the keep zone both fails resolve (guards the baseline)
    r2 = stalagmite.fix(F01, exclude=EX)
    assert r2.verdict == "VERIFIED"


def test_fix_all_blocked_never_worse():
    """Every repair blocked -> part untouched, NOT_IMPROVED, exit 1."""
    r = stalagmite.fix(F01, exclude=EX,
                       keep=[(0.0, 60.0, 100.0)])     # covers everything
    assert r.verdict == "NOT_IMPROVED"
    assert r.n_bodies == 0 and not r.ok_to_write
    assert r.exit_code == 1
    assert any("keep-clear" in n for n in r.notes)


def test_walkdown_skips_kept_landing():
    """A keep zone over a mid-height anchor forces the walk-down to pass
    it (deeper landing or bed pillar) rather than weld onto it."""
    from dfam_repair import make_repair_specs
    from dfam_audit import load_mesh, audit_mesh, aggregate
    m = load_mesh(F01)
    _, v = audit_mesh(m, exclude=EX)
    feats = aggregate(v, 0.4)
    def boss_feat(fs):
        return next(f for f in fs
                    if f["severity"] == "fail" and f.get("geom") is not None
                    and abs(f["geom"].centroid.x - 17.4) < 1.0)

    make_repair_specs(m, feats, 0.4, 45.0)
    zb = boss_feat(feats)["repair_spec"]["z_bot"]
    # forbid landing anywhere near that anchor level around the boss
    kz = (zb - 1.0, zb + 1.0, 8.0, 17.4, 0.0)
    make_repair_specs(m, feats, 0.4, 45.0, keep=[kz])
    spec2 = boss_feat(feats)["repair_spec"]
    assert spec2 is not None
    assert spec2["z_bot"] < zb - 0.9             # landed deeper instead


# ------------------------------------------------------------------ CLI

def test_cli_audit_keep_json():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dfam_audit.main([F01, *EX_ARGS, "--json",
                                "--keep", "25:33:6:17.4:0"])
    d = json.loads(buf.getvalue())
    assert code == 1                              # still FAIL, unchanged
    assert d["keep_zones"] == [[25.0, 33.0, 6.0, 17.4, 0.0]]
    assert any(f.get("intent_hits") for f in d["features"])


def test_cli_audit_keep_human_tag():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        dfam_audit.main([F01, *EX_ARGS, "--keep", "25:33:6:17.4:0"])
    assert "[ON KEEP-CLEAR ZONE]" in buf.getvalue()


def test_cli_audit_bad_keep_exit2():
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), \
            contextlib.redirect_stderr(err):
        code = dfam_audit.main([F01, "--keep", "nope"])
    assert code == 2 and "keep-clear zone" in err.getvalue()


def test_cli_fix_keep(tmp_path):
    out = str(tmp_path / "fixed.stl")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dfam_fix.main([F01, "-o", out, *EX_ARGS,
                              "--keep", "25:33:6:17.4:0", "--json"])
    d = json.loads(buf.getvalue())
    assert d["verdict"] == "PARTIAL"
    assert any("keep-clear" in n for n in d["notes"])
    assert code == 1                              # boss still FAIL
    assert os.path.exists(out)                    # partial fix written


# --------------------------------------------------------------- report

def test_report_carries_intent_badge(tmp_path):
    r = stalagmite.check(F01, exclude=EX, keep=[BOSS_KEEP])
    p = str(tmp_path / "r.html")
    r.write_report(p)
    html = open(p, encoding="utf-8").read()
    assert "on keep-clear zone" in html
    assert '"intent": true' in html


# ------------------------------------------------- GUI protect-toggle flow

def test_gui_run_fix_with_keep():
    """The GUI flow: protect toggles send zones; run_fix blocks the
    protected repair and the fixed report carries the badge."""
    import dfam_gui
    raw = open(F01, "rb").read()
    out = dfam_gui.run_fix(raw, "01.stl", "generic-fdm", True,
                           keep=[BOSS_KEEP])
    assert out["ok"] and out["verdict"] == "PARTIAL"
    assert any("keep-clear" in n for n in out["notes"])
    assert "on keep-clear zone" in out["fixed_report"]
    # unprotected control stays VERIFIED (baseline guarded)
    out2 = dfam_gui.run_fix(raw, "01.stl", "generic-fdm", True)
    assert out2["verdict"] == "VERIFIED"


def test_report_ships_protect_machinery():
    """The report embeds the protect toggle + postMessage plumbing
    (only active when embedded in the GUI)."""
    r = stalagmite.check(F01, exclude=EX)
    import tempfile, os as _os
    p = tempfile.NamedTemporaryFile(suffix=".html", delete=False).name
    try:
        r.write_report(p)
        text = open(p, encoding="utf-8").read()
        assert "stalagmite: 'keep'" in text
        assert "protect" in text and "keepZoneOf" in text
        assert "window.parent !== window" in text
    finally:
        _os.unlink(p)
