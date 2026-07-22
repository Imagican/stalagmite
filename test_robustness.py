"""Robustness torture battery: stalagmite must survive anything a
stranger's STL can throw at it. Every pathological mesh here must either
audit cleanly (returning a status) or raise a clean ValueError -- never
an unhandled exception, never a hang.

Run with test_fixtures.py:  python -m pytest test_fixtures.py test_robustness.py
"""
import io
import os
import json
import time
import contextlib

import numpy as np
import pytest
import trimesh

import stalagmite
import dfam_audit


def box(e=(10, 10, 10), t=(0, 0, 5)):
    b = trimesh.creation.box(extents=e)
    b.apply_translation(t)
    return b


# ------------------------------------------------- must-audit-cleanly set

def _pathological_cases():
    b = box()
    yield "open_box", trimesh.Trimesh(b.vertices, b.faces[:-3],
                                      process=False)
    yield "inverted", trimesh.Trimesh(b.vertices, b.faces[:, ::-1],
                                      process=False)
    v = b.vertices.copy()
    v[0] = [np.nan, 0, 0]
    yield "nan_vertex", trimesh.Trimesh(v, b.faces, process=False)
    v2 = b.vertices.copy()
    v2[1] = [np.inf, 0, 0]
    yield "inf_vertex", trimesh.Trimesh(v2, b.faces, process=False)
    yield "self_intersect", trimesh.util.concatenate(
        [box(), box(t=(3, 3, 7))])
    yield "multi_shell", trimesh.util.concatenate(
        [box(), box(t=(50, 0, 5))])
    yield "flat_plate", trimesh.Trimesh(
        vertices=[[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]],
        faces=[[0, 1, 2], [0, 2, 3]], process=False)
    yield "one_tri", trimesh.Trimesh(
        vertices=[[0, 0, 0], [5, 0, 0], [0, 5, 0]],
        faces=[[0, 1, 2]], process=False)
    yield "tiny_units", box(e=(0.5, 0.5, 0.5), t=(0, 0, 0.25))
    yield "dup_degenerate", trimesh.Trimesh(
        b.vertices, np.vstack([b.faces, b.faces[0:1], [[0, 0, 0]]]),
        process=False)


@pytest.mark.parametrize("name,mesh", list(_pathological_cases()),
                         ids=[n for n, _ in _pathological_cases()])
def test_pathological_mesh_audits(name, mesh):
    r = stalagmite.check(mesh)
    assert r.status in ("PASS", "PASS_WITH_LIMITS", "REVIEW", "FAIL")
    assert isinstance(r.to_dict(), dict)
    json.dumps(r.to_dict())


def test_inverted_mesh_is_repaired_or_flagged():
    """A consistently inside-out mesh is auto-flipped by sanitize (so the
    audit is meaningful), or at minimum flagged in health."""
    b = box()
    inv = trimesh.Trimesh(b.vertices, b.faces[:, ::-1], process=False)
    m = dfam_audit.sanitize_mesh(inv)
    assert m.volume > 0, "sanitize must flip an inside-out mesh"
    assert not any("inside-out" in n for n in dfam_audit.mesh_health(m))


def test_open_mesh_flagged_in_health():
    b = box()
    open_m = trimesh.Trimesh(b.vertices, b.faces[:-3], process=False)
    r = stalagmite.check(open_m)
    assert any("watertight" in n for n in r.health)


def test_tall_part_slice_count_note():
    tall = box(e=(5, 5, 2000), t=(0, 0, 1000))
    notes = dfam_audit.mesh_health(tall, dz=0.4)
    assert any("slices" in n for n in notes)


# ------------------------------------------------- must-reject-cleanly set

def test_empty_inputs_raise_valueerror():
    with pytest.raises(ValueError):
        stalagmite.check((np.zeros((0, 3)), np.zeros((0, 3), int)))
    with pytest.raises(ValueError):
        stalagmite.check(trimesh.Trimesh(
            vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[],
            process=False))


def test_garbage_file_raises_valueerror(tmp_path):
    p = tmp_path / "garbage.stl"
    p.write_bytes(b"this is not a mesh at all \x00\x01\x02" * 100)
    with pytest.raises(ValueError):
        dfam_audit.load_mesh(str(p))


def test_missing_file_cli_exits_2(tmp_path):
    buf = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        code = dfam_audit.main([str(tmp_path / "nope.stl")])
    assert code == 2
    assert "error:" in err.getvalue()


def test_garbage_file_cli_json_error_object(tmp_path):
    p = tmp_path / "garbage.stl"
    p.write_bytes(b"nonsense" * 50)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dfam_audit.main([str(p), "--json"])
    assert code == 2
    payload = json.loads(buf.getvalue())
    assert payload["status"] == "ERROR" and payload["exit_code"] == 2
    assert not payload["printable"] and "error" in payload


# ------------------------------------------------------------ performance

def test_high_poly_audit_within_bounds():
    """A ~20k-face organic mesh audits in reasonable time (regression
    guard against pathological slowdowns, generous bound for CI)."""
    s = trimesh.creation.icosphere(subdivisions=4, radius=15)  # 20480 faces
    s.apply_translation([0, 0, 15])
    t0 = time.time()
    r = stalagmite.check(s)
    took = time.time() - t0
    assert r.status in ("PASS", "PASS_WITH_LIMITS", "REVIEW", "FAIL")
    assert took < 120, f"audit took {took:.0f}s -- performance regression"


def test_ascii_stl_roundtrip(tmp_path):
    """ASCII STL (not just binary) loads and audits."""
    b = box()
    p = tmp_path / "ascii.stl"
    p.write_text(trimesh.exchange.stl.export_stl_ascii(b))
    r = stalagmite.check(str(p))
    assert r.status == "PASS"
