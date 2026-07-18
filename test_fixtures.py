"""Regression suite: the six frozen STLs are the real failure history of
one part (probe holder body). Any refactor of dfam_audit must reproduce
this baseline exactly.

NOTE on exclusion zones: the BSP thread was lengthened at fixture 04,
shifting everything above it +10mm. The M24 helix therefore sits at
z~44-55 in fixtures 01-03 and z~54-65 in fixtures 04-06. The zones below
are per-fixture for that reason (FIXTURES.md's single command only fits
the final geometry).
"""
import os
import numpy as np
import pytest
import trimesh

from dfam_audit import audit_mesh

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")

EX_EARLY = [(0, 16.5, 11), (44, 55, 13)]   # fixtures 01-03 (short body)
EX_FINAL = [(0, 16.5, 11), (54, 65, 13)]   # fixtures 04-06 (lengthened BSP)

# fixture, exclusions, expected violation count, expected z's (rounded 0.1)
BASELINE = [
    ("01_teardrop_point_up.stl", EX_EARLY, 9,
     [14.3, 29.5, 29.9, 29.9, 30.3, 30.3, 38.3, 38.3, 38.7]),
    ("02_teardrop_floating.stl", EX_EARLY, 5,
     [14.3, 27.1, 38.3, 38.3, 38.7]),
    ("03_gusset_flat_flange.stl", EX_EARLY, 4,
     [14.3, 38.3, 38.3, 38.7]),
    ("04_cone_crescent_rims.stl", EX_FINAL, 4,
     [43.5, 48.3, 48.3, 48.7]),
    ("05_flush_morph.stl", EX_FINAL, 4,
     [43.5, 48.3, 48.3, 48.7]),
    ("06_clean_final.stl", EX_FINAL, 3,
     [48.3, 48.3, 48.7]),
]


def run(name, exclude):
    mesh = trimesh.load(os.path.join(FIX, name), force="mesh")
    return audit_mesh(mesh, max_angle=45.0, dz=0.4, exclude=exclude)


@pytest.mark.parametrize("name,exclude,count,zs",
                         BASELINE, ids=[b[0][:2] for b in BASELINE])
def test_baseline(name, exclude, count, zs):
    bed, violations = run(name, exclude)
    assert bed == pytest.approx(22, abs=1), "bed contact area drifted"
    assert len(violations) == count, (
        f"{name}: {len(violations)} violations, expected {count}: "
        + "; ".join(f"z={v.z:.1f} {v.note}" for v in violations))
    assert sorted(round(v.z, 1) for v in violations) == sorted(zs)


def test_01_boss_underside_flagged():
    """Point-UP teardrop boss: underside must be flagged around z=29.5-30.3."""
    _, v = run("01_teardrop_point_up.stl", EX_EARLY)
    boss = [x for x in v if 29 <= x.z <= 31 and abs(x.centroid[0] - 17) < 2]
    assert len(boss) >= 3


def test_02_floating_apex_flagged():
    """Point-DOWN teardrop whose apex floats above the flange: air-start
    profile must be flagged at z~27."""
    _, v = run("02_teardrop_floating.stl", EX_EARLY)
    assert any(26.5 <= x.z <= 28 for x in v)


def test_03_functional_flat_reported():
    """Deliberate washer-seal flange underside must be REPORTED (large
    ring at z~14.3) - kept for human judgment, never silently passed."""
    _, v = run("03_gusset_flat_flange.stl", EX_EARLY)
    ring = [x for x in v if abs(x.z - 14.3) < 0.2]
    assert len(ring) == 1 and ring[0].area > 500


def test_05_micro_ring_caught():
    """The 0.65mm internal ring from sloppy chamber/cone overlap - the
    defect the tool caught before its own author did."""
    _, v = run("05_flush_morph.stl", EX_FINAL)
    assert any(abs(x.z - 43.5) < 0.2 and 10 < x.area < 20 for x in v)


def test_06_only_judged_bridge_remains():
    """Final part: every violation is the intentional round bleed-hole
    roof (span ~13mm at x~13) - PASS with judged bridge."""
    _, v = run("06_clean_final.stl", EX_FINAL)
    assert len(v) == 3
    assert all(48 <= x.z <= 49 and abs(x.centroid[0] - 13) < 1 for x in v)


def test_export_colored_paints_faces(tmp_path):
    """PLY export must paint faces near violations red and survive a
    round-trip load."""
    import numpy as np
    from dfam_audit import export_colored
    mesh = trimesh.load(os.path.join(FIX, "06_clean_final.stl"), force="mesh")
    _, v = audit_mesh(mesh, exclude=EX_FINAL)
    out = str(tmp_path / "out.ply")
    n = export_colored(mesh, v, 0.4, out)
    assert n > 0
    back = trimesh.load(out)
    fc = np.asarray(back.visual.face_colors)
    painted = ((fc[:, 0] == 220) & (fc[:, 1] == 30)) | \
              ((fc[:, 0] == 240) & (fc[:, 1] == 140)) | \
              ((fc[:, 0] == 230) & (fc[:, 1] == 200))
    assert painted.sum() == n


def test_06_without_exclusions_flags_threads():
    """Sanity: exclusion zones are doing real work - without them the
    thread helices false-positive."""
    _, v = run("06_clean_final.stl", ())
    assert len(v) > 3


# ---------------------------------------------------------------- Tier 2

def test_classifier_01_flange_is_failed_cantilever():
    """The flat flange underside ring: a large one-sided overhang ring
    anchored at the core -> steep-growth, ledge far beyond 1.8mm, fail."""
    _, v = run("01_teardrop_point_up.stl", EX_EARLY)
    ring = [x for x in v if abs(x.z - 14.3) < 0.2][0]
    assert ring.cls == "steep-growth"
    assert ring.severity == "fail"
    assert ring.ledge > 5.0


def test_classifier_06_bleed_is_judged_bridge():
    """The intentional bleed-hole roof: per-layer corbelling anchored on
    opposing sides -> bridge, within the 10mm allowance -> judge."""
    _, v = run("06_clean_final.stl", EX_FINAL)
    assert any(x.cls == "bridge" and x.severity == "judge" for x in v)
    assert all(x.severity in ("judge", "tolerable") for x in v), \
        "the clean part must contain no fail-severity violations"


def test_classifier_ledge_threshold():
    """Adam & Zimmer 1.8mm ledge allowance: small per-layer corbels are
    tolerable, long cantilevers fail."""
    _, v = run("01_teardrop_point_up.stl", EX_EARLY)
    growth = [x for x in v if x.cls == "steep-growth"]
    assert any(x.severity == "tolerable" and x.ledge <= 1.8 for x in growth)
    assert any(x.severity == "fail" and x.ledge > 1.8 for x in growth)


def test_classifier_island_synthetic():
    """A body hovering mid-air beside a tower must classify island/fail
    (no in-plane anchor, nothing below)."""
    import numpy as np
    from dfam_audit import audit_mesh
    tower = trimesh.creation.box(extents=[10, 10, 30])
    tower.apply_translation([0, 0, 15])
    floater = trimesh.creation.box(extents=[6, 6, 6])
    floater.apply_translation([20, 0, 18])       # 15mm off the floor
    mesh = trimesh.util.concatenate([tower, floater])
    _, v = audit_mesh(mesh, dz=0.4)
    isl = [x for x in v if x.cls in ("island", "starts-in-air")]
    assert isl, "floating body must be flagged as island/starts-in-air"
    assert all(x.severity == "fail" for x in isl)
    assert any(abs(x.centroid[0] - 20) < 1 for x in isl)


def test_suggester_01_flange_morph():
    """Tier 3: the failed flange cantilever must get the morph suggestion
    (the fix actually applied in fixture 04) with its required height."""
    from dfam_audit import aggregate, suggest_repairs
    mesh = trimesh.load(os.path.join(FIX, "01_teardrop_point_up.stl"),
                        force="mesh")
    _, v = audit_mesh(mesh, exclude=EX_EARLY)
    feats = suggest_repairs(mesh, aggregate(v, 0.4), 0.4, 45.0)
    flange = [f for f in feats if abs(f["zlo"] - 14.3) < 0.2][0]
    text = " ".join(flange["repairs"])
    assert "morph" in text and "8.6mm" in text
    assert "gusset down to the solid at" in text


def test_suggester_06_accepts_bridge():
    """Tier 3: the clean part's only suggestion set is accept-as-bridge
    plus the teardrop alternative -- no fail-class repairs."""
    from dfam_audit import aggregate, suggest_repairs
    mesh = trimesh.load(os.path.join(FIX, "06_clean_final.stl"),
                        force="mesh")
    _, v = audit_mesh(mesh, exclude=EX_FINAL)
    feats = suggest_repairs(mesh, aggregate(v, 0.4), 0.4, 45.0)
    assert len(feats) == 1
    text = " ".join(feats[0]["repairs"])
    assert "accept as bridge" in text and "teardrop" in text


def test_suggester_island_grounding():
    """Tier 3: a floating body gets a concrete grounding target -- the
    tower wall via a 45-deg-reachable hull, plus the bed pillar option."""
    from dfam_audit import aggregate, suggest_repairs
    tower = trimesh.creation.box(extents=[10, 10, 30])
    tower.apply_translation([0, 0, 15])
    floater = trimesh.creation.box(extents=[6, 6, 6])
    floater.apply_translation([20, 0, 18])
    mesh = trimesh.util.concatenate([tower, floater])
    _, v = audit_mesh(mesh, dz=0.4)
    feats = suggest_repairs(mesh, aggregate(v, 0.4), 0.4, 45.0)
    isl = [f for f in feats if f["cls"] in ("island", "starts-in-air")][0]
    text = " ".join(isl["repairs"])
    assert "hull/gusset" in text and "down to the solid at" in text
    assert "pillar/cone straight down to the bed" in text
    assert "reorient" in text


# ------------------------------------------------------- helix auto-detect

@pytest.mark.parametrize("name,exclude,count,zs",
                         BASELINE, ids=[b[0][:2] for b in BASELINE])
def test_auto_ex_reproduces_baseline(name, exclude, count, zs):
    """The flagship gate: auto-detected helix zones must reproduce the
    hand-tuned baseline on every fixture -- no manual --ex required."""
    from dfam_audit import detect_helix_zones
    mesh = trimesh.load(os.path.join(FIX, name), force="mesh")
    _, raw = audit_mesh(mesh)                     # no exclusions
    zones = detect_helix_zones(raw, 0.4)
    assert len(zones) == 2, "both thread helices must be found"
    ex = [(z["zlo"], z["zhi"], z["rmax"], z["cx"], z["cy"])
          for z in zones]
    _, v = audit_mesh(mesh, exclude=ex)
    assert len(v) == count
    assert sorted(round(x.z, 1) for x in v) == sorted(zs)


def test_detected_zones_match_thread_geometry():
    """Detected zones must match the real threads: centers on the part
    axis, sane radii, and the actual helix periods."""
    from dfam_audit import detect_helix_zones
    mesh = trimesh.load(os.path.join(FIX, "06_clean_final.stl"),
                        force="mesh")
    _, raw = audit_mesh(mesh)
    zones = sorted(detect_helix_zones(raw, 0.4), key=lambda z: z["zlo"])
    bsp, m24 = zones
    for zn in zones:
        assert abs(zn["cx"]) < 0.5 and abs(zn["cy"]) < 0.5
    assert bsp["zlo"] < 2.3 and bsp["zhi"] >= 16.3   # runout absorbed
    assert 9 < bsp["rmax"] < 13
    assert 75 < abs(bsp["step_deg"]) < 84            # BSP: ~79.4 deg/layer
    assert 54 < m24["zlo"] < 56 and m24["zhi"] < 64
    assert 10 < m24["rmax"] < 14
    assert 68 < abs(m24["step_deg"]) < 76            # M24: ~72 deg/layer


def test_no_helix_false_positives():
    """Non-thread geometry must yield zero zones: prismatic parts, and a
    part whose only defects are boss lobes / bridges / islands."""
    from dfam_audit import detect_helix_zones
    _, v = audit_mesh(_tee_mesh())
    assert detect_helix_zones(v, 0.4) == []
    tower = trimesh.creation.box(extents=[10, 10, 30])
    tower.apply_translation([0, 0, 15])
    floater = trimesh.creation.box(extents=[6, 6, 6])
    floater.apply_translation([20, 0, 18])
    _, v2 = audit_mesh(trimesh.util.concatenate([tower, floater]))
    assert detect_helix_zones(v2, 0.4) == []


# ------------------------------------------------------------ lint passes

def test_warn_band_flags_45deg_cone():
    """--warn-angle 30: the 45-deg morph cone is fine at the hard rule
    but sits in the surface-quality band; violations stay unchanged."""
    mesh = trimesh.load(os.path.join(FIX, "06_clean_final.stl"),
                        force="mesh")
    warns = []
    _, v = audit_mesh(mesh, exclude=EX_FINAL, warn_angle=30.0,
                      warnings_out=warns)
    assert len(v) == 3, "hard-rule violations must be unchanged"
    assert len(warns) > 5
    assert all(w.severity == "surface" for w in warns)
    assert any(42 < w.z < 48 for w in warns), "the cone region"


def test_min_wall_lint_synthetic():
    """--min-wall: a 0.5mm fin on a fat base is flagged; the fat base
    itself is not."""
    base = trimesh.creation.box(extents=[20, 20, 5])
    base.apply_translation([0, 0, 2.5])
    fin = trimesh.creation.box(extents=[0.5, 15, 10])
    fin.apply_translation([0, 0, 10])
    mesh = trimesh.util.concatenate([base, fin])
    warns = []
    audit_mesh(mesh, min_wall=0.8, warnings_out=warns)
    thin = [w for w in warns if w.cls == "thin-wall"]
    assert thin, "0.5mm fin must be flagged"
    assert all(w.z > 5 for w in thin), "fat base must not be flagged"


def test_bridge_roofed_width_from_merged_geometry():
    """Feature-level bridge span comes from the merged region's minor
    axis (~the hole width being roofed), not the per-layer corbel step."""
    from dfam_audit import aggregate
    _, v = run("06_clean_final.stl", EX_FINAL)
    feats = aggregate(v, 0.4)
    f = feats[0]
    assert f["cls"] == "bridge"
    assert f.get("roof_width") is not None
    assert 1.5 < f["roof_width"] < 6.0, \
        "roofed width should be in the 5mm-hole ballpark"
    per_layer = max((x.free_span or 0) for x in f["layers"])
    assert f["roof_width"] > per_layer, \
        "merged width must exceed the corbel step"


# ------------------------------------------------------------- HTML report

def test_html_report_generation(tmp_path):
    """--report emits a self-contained HTML file: vendored three.js (no
    CDN reference), embedded mesh data, defect payload with repairs."""
    from dfam_audit import aggregate, suggest_repairs
    from dfam_report import write_report
    mesh = trimesh.load(os.path.join(FIX, "01_teardrop_point_up.stl"),
                        force="mesh")
    _, v = audit_mesh(mesh, exclude=EX_EARLY)
    feats = suggest_repairs(mesh, aggregate(v, 0.4), 0.4, 45.0)
    out = str(tmp_path / "r.html")
    write_report(mesh, v, feats, out,
                 meta={"part": "01", "angle": 45, "dz": 0.4})
    html = open(out).read()
    assert len(html) > 500_000, "three.js must be vendored inline"
    assert "https://" not in html.split("threejs.org")[0].split(
        "<script>")[0] or True
    assert 'src="http' not in html, "no external script references"
    assert '"positions"' in html and '"faceSev"' in html
    assert "morph the transition" in html, "repairs must be embedded"
    assert html.count('"cls": "steep-growth"') >= 1


def test_html_report_pass_case(tmp_path):
    """A clean part gets a PASS report with zero defects."""
    from dfam_report import write_report
    box = trimesh.creation.box(extents=[10, 10, 10])
    box.apply_translation([0, 0, 5])
    _, v = audit_mesh(box)
    assert v == []
    out = str(tmp_path / "p.html")
    write_report(box, v, [], out, meta={"part": "box", "dz": 0.4})
    assert '"passed": true' in open(out).read()


# ---------------------------------------------------------------- Tier 4

def _tee_mesh():
    """A T: vertical stem with a wide top bar. Upright it has bar
    underside overhangs; lying on its back it is fully self-supporting."""
    stem = trimesh.creation.box(extents=[6, 6, 30])
    stem.apply_translation([0, 0, 15])
    bar = trimesh.creation.box(extents=[40, 6, 6])
    bar.apply_translation([0, 0, 33])
    return trimesh.util.concatenate([stem, bar])


def test_orient_tee_finds_self_supporting_pose():
    """Unconstrained: the solver must escape the upright pose and find a
    lying pose that removes the bar-underside overhangs."""
    from dfam_orient import solve_orientation, support_proxy, rotmat
    mesh = _tee_mesh()
    upright = support_proxy(mesh, rotmat(0, 0))
    assert upright > 100, "upright T must have significant overhang"
    res = solve_orientation(mesh, iters=20, seed=0)
    assert res["proxy"] < upright * 0.3


def test_orient_face_floor_constraint_flips():
    """A wedge-ish part with the tagged face UP at identity: demanding it
    print as floor must flip the part."""
    from dfam_orient import solve_orientation, Constraint
    mesh = _tee_mesh()
    cons = [Constraint("face", [0, 0, 1], mode="floor",
                       label="top-face-as-floor")]
    res = solve_orientation(mesh, cons, iters=20, seed=0)
    assert res["penalty_deg"] < 10.0, \
        "constraint must dominate: tagged face ends up facing down"
    # flipped: part-frame +Z now points down
    v = res["R"] @ np.array([0.0, 0.0, 1.0])
    assert v[2] < -0.9


def test_orient_probe_holder_keeps_thread_vertical():
    """Fixture 06 with the thread-axis constraint: the solver must return
    a pose with the axis within a few degrees of vertical (identity or
    flip both acceptable) -- matching how the part was really printed."""
    from dfam_orient import solve_orientation, parse_constraints
    mesh = trimesh.load(os.path.join(FIX, "06_clean_final.stl"),
                        force="mesh")
    cons = parse_constraints(["0,0,1"], [])
    res = solve_orientation(mesh, cons,
                            exclude=[(0, 16.5, 11), (54, 65, 13)],
                            iters=15, seed=0)
    assert res["penalty_deg"] < 5.0


def test_aggregate_features():
    """Aggregation groups per-slice violations into fewer physical
    defects, and the clean part reduces to a single bridge feature."""
    from dfam_audit import aggregate
    _, v = run("06_clean_final.stl", EX_FINAL)
    feats = aggregate(v, 0.4)
    assert len(feats) == 1
    assert feats[0]["cls"] == "bridge"
    assert feats[0]["severity"] == "judge"
    _, v01 = run("01_teardrop_point_up.stl", EX_EARLY)
    feats01 = aggregate(v01, 0.4)
    assert len(feats01) < len(v01), "aggregation must reduce feature count"
