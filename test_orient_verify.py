"""Tests for orientation pose verification (Terra #8): the proxy
proposes, the containment audit disposes."""
import numpy as np
import trimesh

from dfam_orient import (solve_orientation, verify_pose, pose_mesh,
                         transform_zones, rotmat, _top_distinct)


def mushroom():
    """Stem + wide cap: upright FAILs (cap overhang), flipped prints."""
    stem = trimesh.creation.cylinder(radius=5, height=12, sections=48)
    stem.apply_translation([0, 0, 6])
    cap = trimesh.creation.cylinder(radius=15, height=5, sections=64)
    cap.apply_translation([0, 0, 14.5])
    return trimesh.util.concatenate([stem, cap])


# ------------------------------------------------------------- plumbing

def test_pose_mesh_drops_to_bed():
    m = mushroom()
    m2, tz = pose_mesh(m, rotmat(180, 0))
    assert abs(m2.bounds[0][2]) < 1e-6
    assert tz != 0.0


def test_transform_zones_upright_flip_tilt():
    m = mushroom()
    zone = (2.0, 10.0, 6.0, 1.0, 0.0)
    # upright: identity
    _, tz = pose_mesh(m, rotmat(0, 0))
    zs, dropped = transform_zones([zone], rotmat(0, 0), tz)
    assert dropped == 0 and zs[0][:3] == (2.0, 10.0, 6.0)
    # flipped: z-range mirrored + shifted, still valid
    R = rotmat(180, 0)
    _, tz = pose_mesh(m, R)
    zs, dropped = transform_zones([zone], R, tz)
    assert dropped == 0 and len(zs) == 1
    lo, hi, r, cx, cy = zs[0]
    assert hi > lo and r == 6.0 and abs(cx - 1.0) < 1e-6
    # tilted 90 deg: the cylinder axis is horizontal -> honest drop
    R = rotmat(90, 0)
    _, tz = pose_mesh(m, R)
    zs, dropped = transform_zones([zone], R, tz)
    assert dropped == 1 and zs == []


def test_top_distinct_respects_separation():
    X = np.array([[0.0, 0.0], [1.0, 1.0], [180.0, 0.0], [2.0, 359.0]])
    Y = np.array([1.0, 1.1, 2.0, 3.0])
    picked = _top_distinct(X, Y, 3, min_sep=20.0)
    assert picked[0] == 0
    assert 1 not in picked and 3 not in picked   # both within 20 deg of 0
    assert 2 in picked


# ----------------------------------------------------------- the physics

def test_verify_pose_mushroom():
    m = mushroom()
    up = verify_pose(m, 0, 0)
    down = verify_pose(m, 180, 0)
    assert up["status"] == "FAIL" and up["fails"] >= 1
    assert down["status"] == "PASS" and down["fails"] == 0


def test_solve_orientation_verify_picks_printable():
    """With verification on, the winner must be a pose the audit
    accepts -- and the evidence rides along in the result."""
    m = mushroom()
    res = solve_orientation(m, iters=6, n_init=6, seed=0, verify_top=3)
    assert res["chosen_by"] == "containment-audit"
    assert res["audit"]["fails"] == 0
    assert len(res["verified"]) >= 2
    # flipped-ish: the cap must end up low, not high
    m2, _ = pose_mesh(m, res["R"])
    zc = m2.triangles_center[:, 2]
    wide = m2.area_faces > np.percentile(m2.area_faces, 90)
    assert zc[wide].mean() < m2.bounds[1][2] * 0.6


def test_solve_orientation_verify_off_keeps_old_contract():
    m = mushroom()
    res = solve_orientation(m, iters=4, n_init=4, seed=0)
    assert res["chosen_by"] == "proxy"
    assert res["audit"] is None and res["verified"] == []
