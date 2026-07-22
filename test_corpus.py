"""Corpus regression net: every shipped mesh, audited raw, must keep
producing exactly the recorded verdicts.

test_fixtures.py checks the six probe-holder STLs *with their exclusion
zones* at audit_mesh level; this file pins the higher-level
stalagmite.check() outcomes with NO zones (plus flat_roof with auto-ex,
the way the GUI runs it). Any engine change that shifts a status or a
severity count anywhere in the corpus fails here first.
"""
import os

import pytest

import stalagmite

HERE = os.path.dirname(os.path.abspath(__file__))

# (path, auto_ex, status, fails, judge, tolerable, exit_code)
CORPUS = [
    ("fixtures/01_teardrop_point_up.stl", False, "FAIL", 4, 1, 0, 1),
    ("fixtures/02_teardrop_floating.stl", False, "FAIL", 4, 1, 0, 1),
    ("fixtures/03_gusset_flat_flange.stl", False, "FAIL", 3, 1, 0, 1),
    ("fixtures/04_cone_crescent_rims.stl", False, "FAIL", 2, 1, 2, 1),
    ("fixtures/05_flush_morph.stl", False, "FAIL", 2, 1, 2, 1),
    ("fixtures/06_clean_final.stl", False, "FAIL", 2, 1, 1, 1),
    ("examples/flat_roof.stl", True, "FAIL", 1, 0, 1, 1),
]


@pytest.mark.parametrize(
    "path,auto,status,fails,judge,tol,code", CORPUS,
    ids=[os.path.basename(c[0]) for c in CORPUS])
def test_corpus_verdict(path, auto, status, fails, judge, tol, code):
    r = stalagmite.check(os.path.join(HERE, path),
                         auto_ex=auto, suggest=False)
    got = (r.status, r.fails, r.count("judge"), r.count("tolerable"),
           r.exit_code)
    assert got == (status, fails, judge, tol, code), (
        f"{path}: recorded {status}/{fails}f/{judge}j/{tol}t/exit{code}, "
        f"got {got}")


def test_corpus_zoned_06_reviews_clean():
    """With its real thread/boss zones declared, the final probe holder
    drops to REVIEW (one judged bridge -- the bleed hole) and exit 0."""
    r = stalagmite.check(
        os.path.join(HERE, "fixtures/06_clean_final.stl"),
        exclude=[(0, 16.5, 11), (54, 65, 13)], suggest=False)
    assert (r.status, r.fails, r.count("judge"), r.exit_code) == \
        ("REVIEW", 0, 1, 0)
