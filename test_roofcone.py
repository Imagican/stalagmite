"""Tests for the internal roof-chamfer repair primitive (the bottle-cap
case): a flat internal ceiling must be closed by a corbelled cone ring
that keeps the cavity hollow and the bore open -- never by a plug."""
import os

import numpy as np
import pytest
import trimesh
from shapely.geometry import Polygon

import stalagmite
from dfam_audit import slice_region
from dfam_repair import make_repair_specs, roof_chamfer_solid, build_body

HERE = os.path.dirname(os.path.abspath(__file__))
FLAT_ROOF = os.path.join(HERE, "examples", "flat_roof.stl")


def cap(R=15.0, wall=2.0, H=20.0, roof_t=3.0, bore=3.0, spigot_h=6.0):
    """A synthetic bottle cap: tube wall, flat internal ceiling with a
    bore, spigot on top. Printed open-end down = the classic fail."""
    walls = trimesh.creation.annulus(r_min=R - wall, r_max=R, height=H,
                                     sections=64)
    walls.apply_translation([0, 0, H / 2])
    roof = trimesh.creation.annulus(r_min=bore, r_max=R, height=roof_t,
                                    sections=64)
    roof.apply_translation([0, 0, H + roof_t / 2])
    spigot = trimesh.creation.annulus(r_min=bore, r_max=bore + 2.0,
                                      height=spigot_h, sections=64)
    spigot.apply_translation([0, 0, H + roof_t + spigot_h / 2])
    return trimesh.util.concatenate([walls, roof, spigot])


def hole_areas(mesh, z):
    s = slice_region(mesh, z)
    if s is None:
        return []
    polys = [s] if s.geom_type == "Polygon" else list(s.geoms)
    return sorted((abs(Polygon(i).area) for p in polys
                   for i in p.interiors), reverse=True)


# ------------------------------------------------------------ detection

def test_cap_defect_gets_roofcone_spec():
    r = stalagmite.check(cap())
    assert r.failed
    specs = make_repair_specs(r.mesh, r.features, r.dz, r.angle)
    kinds = {s["kind"] for s in specs}
    assert "roofcone" in kinds
    rc = next(s for s in specs if s["kind"] == "roofcone")
    # tall enough for the span at the profile angle, above the bed
    assert rc["min_h"] >= rc["max_gap"] / np.tan(np.radians(r.angle))
    assert rc["z_bot"] > 0


def test_one_sided_ledge_still_gets_loft():
    """A plain cantilever ledge must NOT be misread as a roof."""
    base = trimesh.creation.box(extents=[20, 20, 10])
    base.apply_translation([0, 0, 5])
    shelf = trimesh.creation.box(extents=[9, 20, 2])
    shelf.apply_translation([10 + 4.5 - 0.5, 0, 7])
    m = trimesh.util.concatenate([base, shelf])
    r = stalagmite.check(m)
    specs = make_repair_specs(r.mesh, r.features, r.dz, r.angle)
    assert specs and all(s["kind"] != "roofcone" for s in specs)


# ------------------------------------------------------------- geometry

def test_roof_chamfer_solid_watertight_and_annular():
    r = stalagmite.check(cap())
    specs = make_repair_specs(r.mesh, r.features, r.dz, r.angle)
    rc = next(s for s in specs if s["kind"] == "roofcone")
    body = roof_chamfer_solid(rc)
    assert body.is_watertight
    assert len(body.faces) > 100
    # the body is a ring: a slice through its middle has a hole
    zmid = (rc["z_top"] + rc["z_bot"]) / 2
    s = slice_region(body, zmid)
    polys = [s] if s.geom_type == "Polygon" else list(s.geoms)
    assert any(len(p.interiors) >= 1 for p in polys)
    assert build_body(rc).is_watertight       # dispatcher routes by kind


# ------------------------------------------------- the fix, end to end

def test_cap_fix_keeps_cavity_hollow_and_bore_open():
    """The headline: the cap is repaired WITHOUT plugging the cavity or
    swallowing the spigot bore."""
    m = cap()
    hollow_before = hole_areas(m, 4.0)[0]
    bore_before = hole_areas(m, 26.0)[0]
    r = stalagmite.fix(m)
    assert r.verdict == "VERIFIED"
    assert r.status_after != "FAIL" and r.detail["fails_after"] == 0
    fixed = r.mesh_fixed
    # cavity still hollow below the chamfer start
    rc = next(s for s in r.specs if s["kind"] == "roofcone")
    z_low = rc["z_bot"] - 1.0
    assert hole_areas(fixed, z_low)[0] == pytest.approx(hollow_before,
                                                        rel=0.05)
    # bore still open through the spigot
    assert hole_areas(fixed, 26.0)[0] == pytest.approx(bore_before,
                                                       rel=0.05)
    # and the funnel narrows in between: the chamfer ring's opening at
    # mid-height is well under the cavity's full cross-section (with
    # shell concat, wall and chamfer ring can slice as separate
    # polygons -- the funnel opening is the smallest hole present)
    zmid = (rc["z_top"] + rc["z_bot"]) / 2
    holes = hole_areas(fixed, zmid)
    assert holes and min(holes) < hollow_before * 0.6


@pytest.mark.skipif(not os.path.exists(FLAT_ROOF),
                    reason="user example not present")
def test_flat_roof_example_honest_about_threads():
    """The user's real cap has internal threads to z=11.4; a full 45-deg
    cone does not fit above them and the partial one leaves a 2.7mm
    ledge. Automation must NOT weld over the threads OR ship the
    over-allowance partial -- it refuses with a design-change note.
    The sculptor still gets the partial ghost, flagged."""
    r = stalagmite.fix(FLAT_ROOF, auto_ex=True)
    assert r.verdict == "NOT_IMPROVED"
    assert r.exit_code == 1 and not r.ok_to_write
    assert any("raise/dome the roof" in n for n in r.notes)
    rc = next(s for s in r.specs if s["kind"] == "roofcone")
    assert rc["over_allowance"] is True
    assert rc["z_bot"] >= 11.4          # ghost starts above the threads
    assert rc["clamped_above"] is not None
    # the attempted chamfer never reached the thread region
    from dfam_repair import build_body
    assert build_body(rc).bounds[0][2] >= 11.4
    a = hole_areas(r.mesh_fixed, 8.0)
    b = hole_areas(stalagmite.to_mesh(FLAT_ROOF), 8.0)
    assert all(x == pytest.approx(y, abs=1e-3) for x, y in zip(a, b))


def test_chamfer_partial_within_allowance():
    """Functional zone high on the wall but leaving JUST enough room:
    partial chamfer above it, residual ledge within allowance, proven
    by re-audit -- threads untouched, cap printable."""
    m = cap()                                     # roof underside z=20
    threads = (0.0, 11.0, 14.0)                   # fake thread zone
    r = stalagmite.fix(m, exclude=[threads])
    assert r.verdict == "VERIFIED"
    assert r.detail["fails_after"] == 0
    rc = next(s for s in r.specs if s["kind"] == "roofcone")
    assert rc["over_allowance"] is False
    assert 0 < rc["residual_ledge"] <= 2.5
    assert rc["z_bot"] >= threads[1]              # above the zone
    assert any("clamped above" in n for n in r.notes)


def test_chamfer_blocked_when_zone_reaches_ceiling():
    """Zone right under the ceiling: no clear wall at all -- no spec,
    no cavity plug either, automation refuses honestly."""
    m = cap()
    zone = (0.0, 19.6, 14.0)          # ON the wall, like real threads
    r = stalagmite.fix(m, exclude=[zone])
    assert r.verdict == "NOT_IMPROVED" and r.n_bodies == 0
    assert not any(s["kind"] == "roofcone" for s in r.specs)
    assert any("no usable wall" in n for n in r.notes)
    # and emit_fix_stl emits nothing rather than a plug
    import tempfile
    from dfam_repair import emit_fix_stl
    from dfam_audit import audit_mesh, aggregate
    _, v = audit_mesh(m, exclude=[zone])
    feats = aggregate(v, 0.4)
    p = tempfile.mktemp(suffix=".stl")
    n = emit_fix_stl(m, feats, p, avoid=[zone])
    assert n == 0 and not os.path.exists(p)


# --------------------------------------------------------------- report

def test_report_ships_roofcone_sculptor():
    r = stalagmite.check(cap())
    import tempfile
    import os as _os
    p = tempfile.NamedTemporaryFile(suffix=".html", delete=False).name
    try:
        r.write_report(p)
        text = open(p, encoding="utf-8").read()
        assert "buildRoofTris" in text
        assert "internal roof chamfer" in text
        assert '"kind": "roofcone"' in text
    finally:
        _os.unlink(p)


# ----------------------------------------- optional (quality) sculpting

def test_optional_specs_for_tolerable_and_judge():
    """Every severity is sculptable by the human; only fail specs are
    default (what automation may weld)."""
    r = stalagmite.check(cap())
    # default: fail only
    specs = make_repair_specs(r.mesh, r.features, r.dz, r.angle)
    assert all(s["severity"] == "fail" for s in specs)
    assert all(s["optional"] is False for s in specs)
    # report mode: everything
    specs_all = make_repair_specs(
        r.mesh, r.features, r.dz, r.angle,
        severities=("fail", "judge", "tolerable"))
    assert len(specs_all) >= len(specs)
    assert all(s["optional"] == (s["severity"] != "fail")
               for s in specs_all)


def test_report_ships_optional_sculptor():
    r = stalagmite.check(cap())
    import tempfile
    import os as _os
    p = tempfile.NamedTemporaryFile(suffix=".html", delete=False).name
    try:
        r.write_report(p)
        text = open(p, encoding="utf-8").read()
        assert "Optional quality repair" in text
        assert "Auto-fix" in text and "never applies it" in text
    finally:
        _os.unlink(p)


def test_automation_never_welds_optional():
    """Even a clean-except-tolerable part: apply_fixes touches nothing."""
    r = stalagmite.fix(cap(), exclude=[(0.0, 11.0, 14.0)])
    # after this VERIFIED fix the part has only tolerables left; a
    # second fix pass must be NOTHING_TO_FIX with zero bodies
    r2 = stalagmite.fix(r.mesh_fixed, exclude=[(0.0, 11.0, 14.0)])
    assert r2.verdict == "NOTHING_TO_FIX" and r2.n_bodies == 0


# --------------------------------------------------------- vent shafts

def cap_vent(vent_xy=(9.0, 0.0), vent_r=0.7):
    """Cap with a small vent hole through the lid next to the spigot."""
    from shapely.geometry import Point
    R, wall, H, roof_t, bore = 15.0, 2.0, 20.0, 3.0, 3.0
    walls = trimesh.creation.annulus(r_min=R - wall, r_max=R, height=H,
                                     sections=64)
    walls.apply_translation([0, 0, H / 2])
    roof_poly = (Point(0, 0).buffer(R, 64)
                 .difference(Point(0, 0).buffer(bore, 32))
                 .difference(Point(*vent_xy).buffer(vent_r, 16)))
    roof = trimesh.creation.extrude_polygon(roof_poly, height=roof_t)
    roof.apply_translation([0, 0, H])
    spigot = trimesh.creation.annulus(r_min=bore, r_max=bore + 2,
                                      height=6, sections=64)
    spigot.apply_translation([0, 0, H + roof_t + 3])
    return trimesh.util.concatenate([walls, roof, spigot])


def test_vent_shaft_drilled_through_chamfer():
    """The user's vent-hole report: a through-hole next to the spigot
    must stay continuous through the applied chamfer."""
    from shapely.geometry import Point
    r = stalagmite.fix(cap_vent())
    assert r.verdict == "VERIFIED" and r.detail["fails_after"] == 0
    rc = next(s for s in r.specs if s["kind"] == "roofcone")
    assert len(rc["drill"]) == 1
    assert any("vent shaft" in n and "drilled" in n for n in r.notes)
    f = r.mesh_fixed
    for z in (rc["z_close"] - 1.0, 21.5):     # chamfer body, then roof
        s = slice_region(f, z)
        assert not s.contains(Point(9.0, 0.0))
    # and the main bore is of course still open too
    assert not slice_region(f, 21.5).contains(Point(0.0, 0.0))


def test_vent_drill_fallback_is_honest(monkeypatch):
    """Boolean engine dies -> undrilled body ships with a truthful
    're-drill manually' note, never a silent cover-up."""
    import trimesh.boolean

    def boom(*a, **k):
        raise RuntimeError("no engine")
    monkeypatch.setattr(trimesh.boolean, "difference", boom)
    r = stalagmite.fix(cap_vent())
    assert any("could NOT be drilled" in n for n in r.notes)


@pytest.mark.skipif(not os.path.exists(FLAT_ROOF),
                    reason="user example not present")
def test_tolerable_gets_its_own_scoped_repair():
    """User reports: the tolerable card's sliders were sculpting a
    clone of the fail's internal funnel. flat_roof's tolerable is the
    OUTER RIM overhanging the outside of the wall (its ring centroid
    sits in the cavity -- the classic ring-centroid trap). It must get
    an EXTERNAL skirt loft under the rim, never an internal roofcone."""
    r = stalagmite.check(FLAT_ROOF, auto_ex=True)
    specs = make_repair_specs(r.mesh, r.features, r.dz, r.angle,
                              avoid=r.exclude,
                              severities=("fail", "judge", "tolerable"))
    f = next(s for s in specs if s["severity"] == "fail")
    t = next(s for s in specs if s["severity"] == "tolerable")
    assert f["kind"] == "roofcone"              # internal ceiling: cone
    assert t["kind"] == "skirt"                 # outer rim: ANNULAR skirt
    assert t["min_h"] < f["min_h"] * 0.5        # scoped, not a clone
    # the skirt's top ring is the RIM contour, outside the wall (r=15)
    top = np.asarray(t["top"])
    ctr = top.mean(axis=0)
    rr = np.hypot(*(top - ctr).T)
    assert rr.min() > 15.0


def test_report_ships_multibody_export():
    """Download repair STL bundles every fail repair plus any optional
    repair the user sculpted; per-defect slider settings persist."""
    r = stalagmite.check(cap())
    import tempfile
    import os as _os
    p = tempfile.NamedTemporaryFile(suffix=".html", delete=False).name
    try:
        r.write_report(p)
        text = open(p, encoding="utf-8").read()
        assert "SCULPT" in text and "exportSet" in text
        assert "trisForSpec" in text and "updateDlLabel" in text
    finally:
        _os.unlink(p)


@pytest.mark.skipif(not os.path.exists(FLAT_ROOF),
                    reason="user example not present")
def test_closure_target_never_contains_defect():
    """User report: on a re-audited attempt part, the fail (the applied
    cone's own too-steep surface, a stack of thin rings) got 'repaired'
    by a sliver ring closing to a 404mm2 artifact hole with 98% of the
    defect INSIDE it. A closure target is only valid if the defect is
    not inside it -- selection walks down to the bore."""
    import stalagmite
    from dfam_repair import _roof_opening
    from dfam_fix import apply_fixes
    r0 = stalagmite.check(FLAT_ROOF, auto_ex=True)

    def entry(f, **kw):
        c = f["geom"].centroid
        return dict(cls=f["cls"], zlo=float(f["zlo"]),
                    zhi=float(f["zhi"]), cx=float(c.x), cy=float(c.y),
                    optional=f["severity"] != "fail", **kw)
    tol = next(f for f in r0.features if f["severity"] == "tolerable")
    fail = next(f for f in r0.features if f["severity"] == "fail")
    rA = apply_fixes(stalagmite.to_mesh(FLAT_ROOF), exclude=r0.exclude,
                     sculpt=[entry(fail, height=7.8, easing=2.5),
                             entry(tol, height=2.2, easing=1.0)])
    r1 = stalagmite.check(rA.mesh_fixed, exclude=r0.exclude)
    f1 = next(x for x in r1.features if x["severity"] == "fail")
    res = _roof_opening(r1.mesh, f1, r1.dz)
    assert res is not None
    _, target, _ = res
    assert target is not None
    # the chosen closure target contains (essentially) no defect area
    assert f1["geom"].intersection(target).area <= \
        max(1.0, 0.02 * f1["geom"].area)
    assert target.area == pytest.approx(33.2, abs=2.0)   # the bore
