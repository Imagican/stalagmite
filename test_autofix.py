"""Tests for stalagmite-autofix (Stage C): parameter-space search,
verdicts, the never-worse contract, CLI, API, determinism."""
import io
import os
import json
import contextlib

import pytest
import trimesh

import dfam_autofix
from dfam_autofix import autofix, load_design, _check_space, _dist

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "examples", "autofix_demo.py")


def demo():
    return load_design(DEMO)


# ------------------------------------------------------------- plumbing

def test_check_space_validation():
    with pytest.raises(ValueError):
        _check_space({})
    with pytest.raises(ValueError):
        _check_space({"a": (5.0, 5.0)})
    s = _check_space({"a": [1, 3]})
    assert s["a"] == (1.0, 3.0)


def test_load_design_demo():
    build, space, nominal = demo()
    assert callable(build)
    assert set(space) == {"shelf_len", "gusset"}
    assert nominal == {"shelf_len": 10.0, "gusset": 0.0}


def test_load_design_rejects_junk(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("x = 1\n")
    with pytest.raises(ValueError):
        load_design(str(p))


def test_dist():
    assert _dist([0, 0], [0, 0]) == 0.0
    assert abs(_dist([0, 0], [1, 1]) - 1.0) < 1e-12


# -------------------------------------------------------------- verdicts

def test_nominal_printable_short_circuits():
    """A printable nominal touches nothing and costs one evaluation."""
    build, space, _ = demo()
    r = autofix(build, space, {"shelf_len": 3.0, "gusset": 0.9},
                budget=32)
    assert r.verdict == "NOTHING_TO_DO"
    assert r.evals == 1 and r.distance == 0.0
    assert r.moves == [] and r.exit_code == 0 and r.ok_to_write


def test_found_on_demo():
    """The headline: FAIL design in, proven-printable parameters out --
    and the search must discover the gusset (shrinking the shelf alone
    cannot fix this design)."""
    build, space, nominal = demo()
    r = autofix(build, space, nominal, budget=24, seed=0)
    assert r.verdict == "FOUND"
    assert r.status_before == "FAIL" and r.fails_after == 0
    assert r.status_after != "FAIL"
    assert r.exit_code == 0 and r.ok_to_write
    assert r.params_best["gusset"] > 0.1          # the trap sprung
    assert 0 < r.distance < 1
    d = r.to_dict()
    json.dumps(d)
    assert d["verdict"] == "FOUND" and d["moves"]


def test_deterministic():
    build, space, nominal = demo()
    r1 = autofix(build, space, nominal, budget=16, seed=3)
    r2 = autofix(build, space, nominal, budget=16, seed=3)
    assert r1.params_best == r2.params_best
    assert r1.trials == r2.trials


def test_none_found_withholds():
    """A box the search cannot escape -> NONE_FOUND, exit 1, no write.
    Whatever the offset, the floating cube stays a detached island."""
    def build(offset):
        base = trimesh.creation.box(extents=[30, 30, 5])
        base.apply_translation([0, 0, 2.5])
        island = trimesh.creation.box(extents=[6, 6, 6])
        island.apply_translation([offset, 0, 15 + 3])   # 10 mm of air
        return trimesh.util.concatenate([base, island])
    r = autofix(build, {"offset": (-8.0, 8.0)}, {"offset": 0.0},
                budget=8, seed=0)
    assert r.verdict == "NONE_FOUND"
    assert r.exit_code == 1 and not r.ok_to_write


def test_broken_nominal_raises():
    def build(a):
        raise RuntimeError("boom")
    with pytest.raises(ValueError, match="nominal design does not build"):
        autofix(build, {"a": (0.0, 1.0)}, {"a": 0.5}, budget=4)


def test_partial_build_failures_survive():
    """Candidates that crash become high-cost trials, not crashes."""
    def build(ledge):
        if ledge > 12.0:
            raise RuntimeError("CAD kernel tantrum")
        base = trimesh.creation.box(extents=[20, 20, 10])
        base.apply_translation([0, 0, 5])
        shelf = trimesh.creation.box(extents=[ledge + 1, 20, 2])
        shelf.apply_translation([10 + ledge / 2 - 0.5, 0, 7])
        return trimesh.util.concatenate([base, shelf])
    r = autofix(build, {"ledge": (0.5, 20.0)}, {"ledge": 10.0},
                budget=14, seed=0)
    assert r.verdict == "FOUND"                   # tiny ledges print
    assert r.params_best["ledge"] < 3.0
    assert any(t["error"] for t in r.trials)      # the tantrums recorded


# ------------------------------------------------------------------ CLI

def test_cli_autofix_writes(tmp_path):
    out = str(tmp_path / "best.stl")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dfam_autofix.main([DEMO, "-o", out, "--budget", "20"])
    text = buf.getvalue()
    assert code == 0
    assert os.path.exists(out)
    assert "AUTOFIX: FOUND" in text and "gusset" in text
    # the written STL independently re-audits printable
    import stalagmite
    assert stalagmite.check(out).printable


def test_cli_autofix_json(tmp_path):
    out = str(tmp_path / "best.stl")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = dfam_autofix.main([DEMO, "-o", out, "--budget", "16",
                                  "--json"])
    payload = json.loads(buf.getvalue())
    assert code == 0
    assert payload["verdict"] == "FOUND"
    assert payload["wrote"] == out
    assert payload["status_before"] == "FAIL"
    assert payload["fails_after"] == 0
    assert payload["moves"]


def test_cli_autofix_error_exit2(tmp_path):
    err = io.StringIO()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        code = dfam_autofix.main([str(tmp_path / "missing.py")])
    assert code == 2 and "error:" in err.getvalue()


# ------------------------------------------------------------------ API

def test_api_autofix():
    import stalagmite
    build, space, nominal = demo()
    r = stalagmite.autofix(build, space, nominal, budget=20)
    assert r.verdict == "FOUND"
    assert r.status_after != "FAIL"
