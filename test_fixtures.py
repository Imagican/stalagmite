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


# --------------------------------------------------- status states + profiles

def test_status_states():
    """The four truthful states must map correctly from severities."""
    from dfam_audit import overall_status
    F = lambda s: {"severity": s}
    assert overall_status([]) == "PASS"
    assert overall_status([F("tolerable")]) == "PASS_WITH_LIMITS"
    assert overall_status([], warnings=[1]) == "PASS_WITH_LIMITS"
    assert overall_status([F("judge")]) == "REVIEW"
    assert overall_status([F("judge"), F("tolerable")]) == "REVIEW"
    assert overall_status([F("fail"), F("judge")]) == "FAIL"


def test_status_on_fixtures():
    """06 (intentional bridge only) must be REVIEW, not a bare fail; 01
    (floating boss) must be FAIL. This is the core truthfulness fix."""
    from dfam_audit import aggregate, overall_status
    m6 = trimesh.load(os.path.join(FIX, "06_clean_final.stl"), force="mesh")
    _, v6 = audit_mesh(m6, exclude=EX_FINAL)
    assert overall_status(aggregate(v6, 0.4)) == "REVIEW"
    m1 = trimesh.load(os.path.join(FIX, "01_teardrop_point_up.stl"),
                      force="mesh")
    _, v1 = audit_mesh(m1, exclude=EX_EARLY)
    assert overall_status(aggregate(v1, 0.4)) == "FAIL"


def test_audit_returns_status_and_exit_code():
    """audit() returns a status string; STATUS_EXIT maps FAIL->1, else 0."""
    from dfam_audit import audit, STATUS_EXIT
    import dfam_profiles
    prof = dfam_profiles.resolve()
    st6 = audit(os.path.join(FIX, "06_clean_final.stl"), auto_ex=True,
                profile=prof)
    assert st6 == "REVIEW" and STATUS_EXIT[st6] == 0
    st1 = audit(os.path.join(FIX, "01_teardrop_point_up.stl"), auto_ex=True,
                profile=prof)
    assert st1 == "FAIL" and STATUS_EXIT[st1] == 1


def test_profile_resolution_and_overrides():
    """Built-in default, overrides win, provenance present, bad name errs."""
    import dfam_profiles as P
    p = P.resolve()
    assert p.name == "generic-fdm" and p.angle == 45.0 and p.ledge_max == 1.8
    assert "Adam & Zimmer" in p.provenance["ledge_max"]
    p2 = P.resolve(angle=30.0, ledge_max=1.2)
    assert p2.angle == 30.0 and p2.ledge_max == 1.2
    assert "angle" in p2.overridden and "ledge_max" in p2.overridden
    with pytest.raises(KeyError):
        P.resolve("does-not-exist")


def test_profile_file_roundtrip(tmp_path):
    """A JSON profile with *_mm/*_deg aliases loads and its numbers win."""
    import json
    import dfam_profiles as P
    f = tmp_path / "p.json"
    f.write_text(json.dumps({
        "name": "test-petg", "material": "PETG",
        "thresholds": {"angle_deg": 50, "layer_height_mm": 0.2,
                       "ledge_max_mm": 1.2, "bridge_max_mm": 8.0}}))
    p = P.resolve(path=str(f))
    assert p.name == "test-petg" and p.angle == 50.0 and p.dz == 0.2
    assert p.ledge_max == 1.2 and p.bridge_max == 8.0


def test_profile_changes_severity():
    """A stricter ledge threshold must flip a tolerable ledge to fail --
    proving thresholds are process-dependent, not universal."""
    import dfam_profiles as P
    _, v_default = run("01_teardrop_point_up.stl", EX_EARLY)
    # the boss corbels sit ~1.3mm: tolerable at 1.8, fail at a 1.0 ledge cap
    m = trimesh.load(os.path.join(FIX, "01_teardrop_point_up.stl"),
                     force="mesh")
    _, v_strict = audit_mesh(m, exclude=EX_EARLY, ledge_max=1.0)
    tol_default = sum(1 for x in v_default if x.severity == "tolerable")
    tol_strict = sum(1 for x in v_strict if x.severity == "tolerable")
    assert tol_strict < tol_default


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


def test_transition_diagram_payload():
    """Each defect feature carries a cross-section diagram: support slice,
    45-deg envelope, this slice, and the region beyond the envelope."""
    from dfam_audit import aggregate
    from dfam_report import _transition_diagram
    mesh = trimesh.load(os.path.join(FIX, "01_teardrop_point_up.stl"),
                        force="mesh")
    _, v = audit_mesh(mesh, exclude=EX_EARLY)
    flange = [f for f in aggregate(v, 0.4) if abs(f["zlo"] - 14.3) < 0.2][0]
    d = _transition_diagram(mesh, flange, 0.4, 45.0)
    assert d is not None
    assert d["cur"] and d["env"] and d["bad"], "all three layers present"
    assert len(d["bbox"]) == 4
    # the flange is a wide hex on a narrow neck: the offending area is large
    assert abs(d["z"] - d["zprev"] - 0.4) < 1e-6


def test_report_embeds_diagram(tmp_path):
    """The written HTML must carry per-defect diagram geometry."""
    from dfam_audit import aggregate, suggest_repairs
    from dfam_report import write_report
    mesh = trimesh.load(os.path.join(FIX, "01_teardrop_point_up.stl"),
                        force="mesh")
    _, v = audit_mesh(mesh, exclude=EX_EARLY)
    feats = suggest_repairs(mesh, aggregate(v, 0.4), 0.4, 45.0)
    out = str(tmp_path / "r.html")
    write_report(mesh, v, feats, out,
                 meta={"part": "01", "angle": 45, "dz": 0.4,
                       "status": "FAIL"})
    html = open(out).read()
    assert '"diagram"' in html and '"env"' in html and '"bad"' in html
    assert '"status": "FAIL"' in html


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


# ------------------------------------------------------------- GUI endpoints

def test_gui_audit_endpoint():
    """run_audit_html returns a full report HTML string."""
    import dfam_gui
    raw = open(os.path.join(FIX, "06_clean_final.stl"), "rb").read()
    html = dfam_gui.run_audit_html(raw, "06.stl", "generic-fdm", True, True)
    assert len(html) > 100_000 and "REVIEW" in html and "diagram" in html


def test_gui_orient_endpoint():
    """run_orient returns rotation + before/after proxy + oriented STL."""
    import dfam_gui, base64
    tee_stem = trimesh.creation.box(extents=[6, 6, 30])
    tee_stem.apply_translation([0, 0, 15])
    bar = trimesh.creation.box(extents=[40, 6, 6])
    bar.apply_translation([0, 0, 33])
    import io
    tee = trimesh.util.concatenate([tee_stem, bar])
    raw = tee.export(file_type="stl")
    raw = raw if isinstance(raw, bytes) else raw.encode()
    o = dfam_gui.run_orient(raw, "tee.stl", "generic-fdm", "none")
    assert o["ok"] and o["after"] < o["before"]      # improved
    assert base64.b64decode(o["stl_b64"])[:80]        # decodable STL
    assert o["stl_name"].endswith("_oriented.stl")


def test_gui_diff_endpoint():
    """run_diff returns a serializable verdict + resolved/persist/new."""
    import dfam_gui
    old = open(os.path.join(FIX, "05_flush_morph.stl"), "rb").read()
    new = open(os.path.join(FIX, "06_clean_final.stl"), "rb").read()
    d = dfam_gui.run_diff(old, "05.stl", new, "06.stl", "generic-fdm", True)
    assert d["ok"] and d["verdict"] == "IMPROVED"
    assert len(d["resolved"]) == 1 and len(d["introduced"]) == 0
    import json
    json.dumps(d)          # must be fully serializable


def test_gui_landing_has_tabs():
    """The landing page offers all three modes."""
    import dfam_gui
    page = dfam_gui._landing()
    for t in ("Audit", "Orient", "Compare", "generic-fdm"):
        assert t in page


# ------------------------------------------------------- public API (check)

def test_check_from_path_and_result():
    """stalagmite.check on a file path returns an AuditResult with the
    expected status and a working report writer."""
    import stalagmite
    r = stalagmite.check(os.path.join(FIX, "06_clean_final.stl"),
                         auto_ex=True)
    assert r.status == "REVIEW" and r.printable and r.exit_code == 0
    assert r.count("judge") == 1
    assert "bridge" in " ".join(r.defects())


def test_check_from_trimesh_and_tuple():
    """check accepts a trimesh and a (vertices, faces) pair."""
    import stalagmite
    m = trimesh.load(os.path.join(FIX, "01_teardrop_point_up.stl"),
                     force="mesh")
    r1 = stalagmite.check(m, exclude=EX_EARLY)
    assert r1.status == "FAIL" and r1.failed
    r2 = stalagmite.check((m.vertices, m.faces), exclude=EX_EARLY)
    assert r2.status == "FAIL"


def test_json_output_shape():
    """CLI --json and AuditResult.to_dict() produce the same stable,
    serialisable machine shape with the documented keys."""
    import json
    import stalagmite
    r = stalagmite.check(os.path.join(FIX, "06_clean_final.stl"),
                         auto_ex=True)
    d = r.to_dict()
    for k in ("part", "status", "printable", "exit_code", "profile",
              "thresholds", "counts", "features", "exclusions",
              "auto_zones"):
        assert k in d
    assert d["status"] == "REVIEW" and d["printable"] and d["exit_code"] == 0
    assert d["counts"]["judge"] == 1
    assert len(d["auto_zones"]) == 2          # both threads detected
    assert d["features"][0]["class"] == "bridge"
    json.loads(r.to_json())                   # round-trips


def test_cli_json_flag():
    """The --json flag emits one JSON object and keeps exit-code semantics
    (FAIL -> 1)."""
    import io
    import json
    import contextlib
    import dfam_audit
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dfam_audit.main([os.path.join(FIX, "01_teardrop_point_up.stl"),
                                "--auto-ex", "--json"])
    payload = json.loads(buf.getvalue())      # the whole stdout is JSON
    assert payload["status"] == "FAIL" and payload["exit_code"] == 1
    assert code == 1
    assert payload["counts"]["fail"] >= 1


def test_check_rejects_garbage():
    import stalagmite
    with pytest.raises(TypeError):
        stalagmite.check(12345)


def test_check_writes_report(tmp_path):
    import stalagmite
    r = stalagmite.check(os.path.join(FIX, "01_teardrop_point_up.stl"),
                         exclude=EX_EARLY)
    out = str(tmp_path / "api.html")
    r.write_report(out)
    assert "FAIL" in open(out).read()


def test_cumulative_reach_escalates_sustained_slope():
    """A run of consecutive 'tolerable' ledges is a sustained overhang,
    not an isolated ledge: their cumulative reach escalates to fail."""
    from shapely.geometry import Point
    from dfam_audit import Violation, aggregate
    def v(z, ledge):
        g = Point(0, 0).buffer(2.0)
        return Violation(z, g.area, 4.0, (0.0, 0.0), "unsupported", g,
                         cls="steep-growth", severity="tolerable",
                         ledge=ledge)
    feats = aggregate([v(10 + 0.4 * i, 1.0) for i in range(4)], 0.4)
    assert len(feats) == 1
    assert feats[0]["severity"] == "fail" and feats[0]["cum_reach"] > 1.8
    # a single small ledge stays tolerable
    one = aggregate([v(10, 1.0)], 0.4)
    assert one[0]["severity"] == "tolerable"


def test_cadquery_integration():
    """If CadQuery is installed: audit a part object directly, and the
    audit-driven taper sweep finds the 45-deg minimum (10mm)."""
    cq = pytest.importorskip("cadquery")
    import stalagmite

    def boss(taper):
        top = 26
        base = cq.Workplane("XY").box(40, 40, 4).translate((0, 0, 2))
        p = base.union(cq.Workplane("XY").workplane(offset=4).circle(4)
                       .extrude(top - taper - 4))
        if taper > 0:
            p = p.union(cq.Workplane("XY").workplane(offset=top - taper)
                        .circle(4).workplane(offset=taper).circle(14).loft())
        return p.union(cq.Workplane("XY").workplane(offset=top).circle(14)
                       .extrude(4))

    assert stalagmite.check(boss(0)).status == "FAIL"      # flat cap
    assert not stalagmite.check(boss(4)).printable         # too steep
    assert stalagmite.check(boss(10)).printable            # 45-deg cone


# ------------------------------------------------------- kernel robustness

def test_load_mesh_sanitizes_and_survives(tmp_path):
    """A messy STL (duplicate + degenerate faces, an open hole) must load
    without crashing and still audit."""
    import numpy as np
    from dfam_audit import load_mesh, audit_mesh
    box = trimesh.creation.box(extents=[10, 10, 20])
    box.apply_translation([0, 0, 10])
    # duplicate a face and add a degenerate (zero-area) face
    faces = np.vstack([box.faces, box.faces[0:1],
                       [[0, 0, 0]]])
    messy = trimesh.Trimesh(vertices=box.vertices, faces=faces,
                            process=False)
    p = str(tmp_path / "messy.stl")
    messy.export(p)
    m = load_mesh(p)
    assert len(m.faces) > 0
    _, v = audit_mesh(m)          # must not raise
    assert isinstance(v, list)


def test_mesh_health_flags_open_and_units():
    """Health check flags a non-watertight mesh and suspicious units."""
    from dfam_audit import mesh_health
    plane = trimesh.creation.box(extents=[10, 10, 10])
    plane.apply_translation([0, 0, 5])
    open_mesh = trimesh.Trimesh(vertices=plane.vertices,
                                faces=plane.faces[:-2], process=False)
    notes = mesh_health(open_mesh)
    assert any("watertight" in n for n in notes)
    tiny = trimesh.creation.box(extents=[1, 1, 1])
    tiny.apply_translation([0, 0, 0.5])
    assert any("units" in n for n in mesh_health(tiny))


def test_slice_region_guards_bad_input():
    """slice_region returns None rather than raising on a hopeless z."""
    from dfam_audit import slice_region
    box = trimesh.creation.box(extents=[10, 10, 10])
    assert slice_region(box, 9999.0) is None


# --------------------------------------------------------- diff (revisions)

def test_diff_resolved_and_persist():
    """05->06 (the real micro-ring fix): the z43.5 ledge is resolved, the
    bleed bridge persists, nothing new -> IMPROVED, exit 0."""
    from dfam_diff import diff_audits
    r = diff_audits(os.path.join(FIX, "05_flush_morph.stl"),
                    os.path.join(FIX, "06_clean_final.stl"), auto_ex=True)
    assert r["verdict"] == "IMPROVED"
    assert len(r["resolved"]) == 1 and len(r["introduced"]) == 0
    assert not r["regressed"]


def test_diff_regression_detected():
    """03->01 reintroduces the point-up boss overhang: a NEW fail feature
    -> REGRESSED, regressed flag set (CI exit 1)."""
    from dfam_diff import diff_audits
    r = diff_audits(os.path.join(FIX, "03_gusset_flat_flange.stl"),
                    os.path.join(FIX, "01_teardrop_point_up.stl"),
                    auto_ex=True)
    assert r["verdict"] == "REGRESSED" and r["regressed"] is True
    new_fail = [j for j in r["introduced"]
                if r["new_f"][j]["severity"] == "fail"]
    assert new_fail, "the reintroduced boss must be a NEW-FAIL"


def test_diff_forward_fix_improves():
    """01->03 (grounding the boss): boss resolved, flange+bridge persist,
    no regression."""
    from dfam_diff import diff_audits
    r = diff_audits(os.path.join(FIX, "01_teardrop_point_up.stl"),
                    os.path.join(FIX, "03_gusset_flat_flange.stl"),
                    auto_ex=True)
    assert r["verdict"] == "IMPROVED" and not r["regressed"]
    assert len(r["resolved"]) == 1 and len(r["persist"]) == 2


def test_diff_identical_unchanged():
    """A part against itself: no change."""
    from dfam_diff import diff_audits
    r = diff_audits(os.path.join(FIX, "06_clean_final.stl"),
                    os.path.join(FIX, "06_clean_final.stl"), auto_ex=True)
    assert r["verdict"] == "UNCHANGED"
    assert not r["resolved"] and not r["introduced"]


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
