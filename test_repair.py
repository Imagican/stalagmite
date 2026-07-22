"""Tests for dfam_repair: real-contour repair specs, loft solids, the
bed-floor constraint, --emit-fix, and the Stage-B taste test (union the
generated fix into the part -> the audit must improve)."""
import io
import os
import contextlib

import numpy as np
import pytest
import trimesh

from dfam_audit import audit_mesh, aggregate, overall_status
from dfam_repair import make_repair_specs, loft_solid, emit_fix_stl

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")
EX_EARLY = [(0, 16.5, 11), (44, 55, 13)]


def _flange_setup():
    m = trimesh.load(os.path.join(FIX, "01_teardrop_point_up.stl"),
                     force="mesh")
    _, v = audit_mesh(m, exclude=EX_EARLY)
    feats = aggregate(v, 0.4)
    specs = make_repair_specs(m, feats, 0.4, 45.0)
    return m, feats, specs


def test_flange_spec_is_true_cone():
    """The flange repair spans the real neck (~r10) to the real hex
    (~r18-20), needing ~10mm of height -- the actual v4 fix. The neck
    is a TUBE (probe bore through it), so the landing is a ring and
    the body must be the ANNULAR skirt -- a fan-capped loft would plug
    the bore (the v0.31 fake-VERIFIED lesson)."""
    _, feats, specs = _flange_setup()
    s = [x for x in specs if abs(x["z_top"] - 14.5) < 0.5][0]
    assert s["kind"] == "skirt"
    top = np.asarray(s["top"])
    bot = np.asarray(s["bot"])
    rt = np.hypot(*(top - top.mean(0)).T).mean()
    rb = np.hypot(*(bot - bot.mean(0)).T).mean()
    assert 15 < rt < 21 and 8 < rb < 12
    assert 8 < s["min_h"] < 13
    assert len(s["top"]) == len(s["bot"])          # paired rings


def test_rectangular_ledge_gets_grounded_spec():
    """A rectangular ledge (the enclosure-style case that killed the old
    ghost) gets a spec built from its true rectangular outline."""
    base = trimesh.creation.box(extents=[30, 20, 10])
    base.apply_translation([0, 0, 5])
    ledge = trimesh.creation.box(extents=[50, 28, 4])
    ledge.apply_translation([0, 0, 12])
    part = trimesh.util.concatenate([base, ledge])
    _, v = audit_mesh(part, dz=0.4)
    feats = aggregate(v, 0.4)
    specs = make_repair_specs(part, feats, 0.4, 45.0)
    assert specs, "rect ledge must get a repair spec"
    solid = loft_solid(specs[0])
    b = solid.bounds
    # follows the true rectangular footprint, not an invented circle
    assert abs((b[1][0] - b[0][0]) - 50) < 3
    assert abs((b[1][1] - b[0][1]) - 28) < 3
    assert solid.is_watertight


def test_loft_watertight_and_variants():
    _, _, specs = _flange_setup()
    s = specs[0]
    for kw in ({}, {"easing": 2.0}, {"flare": 1.2},
               {"height": s["min_h"] + 6}):
        solid = loft_solid(s, **kw)
        assert solid.is_watertight and solid.volume > 0


def test_loft_never_below_bed():
    """The bed-floor constraint: no repair may extend below z_floor."""
    _, _, specs = _flange_setup()
    s = specs[0]
    solid = loft_solid(s, height=10_000)
    assert solid.bounds[0][2] >= s["z_floor"] - 1e-6


def test_emit_fix_cli(tmp_path):
    import dfam_audit
    out = str(tmp_path / "fix.stl")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dfam_audit.main([os.path.join(FIX,
                                "01_teardrop_point_up.stl"),
                                "--ex", "0:16.5:11", "--ex", "44:55:13",
                                "--emit-fix", out])
    assert code == 1                    # still FAIL until the user unions
    assert os.path.exists(out)
    assert "repair bodies written" in buf.getvalue()
    m = trimesh.load(out)
    assert len(m.faces) > 1000


def test_union_fix_improves_audit():
    """STAGE B TASTE TEST: union the generated repairs into the worst
    fixture -> FAIL must become printable (REVIEW/PASS_WITH_LIMITS),
    with no fail features left."""
    pytest.importorskip("manifold3d")
    m, feats, specs = _flange_setup()
    assert overall_status(feats) == "FAIL"
    fixed = m
    for s in specs:
        fixed = trimesh.boolean.union([fixed, loft_solid(s)])
    _, v2 = audit_mesh(fixed, exclude=EX_EARLY)
    f2 = aggregate(v2, 0.4)
    status = overall_status(f2)
    assert status in ("REVIEW", "PASS_WITH_LIMITS", "PASS")
    assert not any(f["severity"] == "fail" for f in f2)


def test_report_embeds_repair_spec(tmp_path):
    from dfam_report import write_report
    m, feats, _ = _flange_setup()
    out = str(tmp_path / "r.html")
    _, v = audit_mesh(m, exclude=EX_EARLY)
    write_report(m, v, feats, out, meta={"part": "01", "dz": 0.4,
                                         "angle": 45.0})
    h = open(out).read()
    assert '"repair_spec"' in h and '"z_floor"' in h
    assert "fixpanel" in h and "buildLoftTris" in h


# ---------------------------------------------- flare semantics (v0.28)

def test_loft_ignores_flare_entirely():
    """User reports: flare off the landing floats the base (step);
    pinned-base belly goes convex. With base and top both pinned, any
    profile fuller than the straight chamfer must bulge convex -- so
    lofts ignore flare; the concave family belongs to easing."""
    import numpy as np
    import stalagmite
    from dfam_repair import make_repair_specs, loft_solid
    base = trimesh.creation.box(extents=[20, 20, 14])
    base.apply_translation([0, 0, 7])
    lid = trimesh.creation.box(extents=[26, 26, 4])     # 3mm brim
    lid.apply_translation([0, 0, 16])
    m = trimesh.util.concatenate([base, lid])
    r = stalagmite.check(m)
    spec = next(s for s in make_repair_specs(r.mesh, r.features,
                                             r.dz, r.angle)
                if s["kind"] == "loft")
    n = len(spec["top"])
    b1 = loft_solid(spec, flare=1.0).vertices
    b2 = loft_solid(spec, flare=1.35).vertices
    assert np.allclose(b1, b2)                  # flare is a no-op


def test_pillar_flare_still_spreads_foot():
    """A pillar's foot lands on the BED -- spreading it is legitimate
    and keeps the classic behaviour."""
    import numpy as np
    from dfam_repair import loft_solid
    ring = [[float(np.cos(a))*3, float(np.sin(a))*3]
            for a in np.linspace(0, 2*np.pi, 96, endpoint=False)]
    p = {"kind": "pillar", "z_top": 8.0, "z_bot": 0.0, "z_floor": 0.0,
         "min_h": 2.0, "max_gap": 0.0, "angle": 45.0, "dz": 0.4,
         "top": ring, "bot": ring}
    n = len(ring)
    f1 = loft_solid(p, flare=1.0).vertices[:n]
    f2 = loft_solid(p, flare=1.3).vertices[:n]
    assert not np.allclose(f1, f2)
