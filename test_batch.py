"""stalagmite-batch: audit a whole folder, exit with the worst verdict."""
import json
import os

import dfam_batch

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")


def test_audit_folder_rows():
    said = []
    rows = dfam_batch.audit_folder(FIX, say=said.append)
    assert len(rows) == 6                       # the six fixture STLs
    assert [r["file"] for r in rows] == sorted(r["file"] for r in rows)
    for r in rows:
        assert r["status"] == "FAIL" and r["exit_code"] == 1
        assert set(r) >= {"file", "status", "fails", "judge",
                          "tolerable", "exit_code", "seconds"}
    assert len(said) == 6                       # one line per part


def test_main_exit_is_worst_and_json_parses(capsys, tmp_path):
    import shutil
    one = tmp_path / "parts"
    one.mkdir()
    shutil.copy(os.path.join(FIX, "02_teardrop_floating.stl"), one)
    code = dfam_batch.main([str(one), "--json"])
    assert code == 1                            # at least one FAIL
    out = json.loads(capsys.readouterr().out)
    assert out["exit_code"] == 1
    assert len(out["parts"]) == 1
    assert out["counts"] == {"FAIL": 1}
    # csv sidecar
    csv_path = str(tmp_path / "batch.csv")
    code = dfam_batch.main([str(one), "--csv", csv_path])
    assert code == 1
    lines = open(csv_path).read().strip().splitlines()
    assert len(lines) == 2 and lines[0].startswith("file,")


def test_main_rejects_non_folder(tmp_path, capsys):
    assert dfam_batch.main([str(tmp_path / "nope")]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert dfam_batch.main([str(empty)]) == 2   # no meshes found


def test_gui_batchrow_helper():
    """The Batch tab's server half: bytes -> one table row."""
    import dfam_gui
    raw = open(os.path.join(FIX, "02_teardrop_floating.stl"), "rb").read()
    row = dfam_gui.run_batch_row(raw, "02.stl", "", False)
    assert row["ok"] and row["status"] == "FAIL" and row["fails"] == 4
    assert row["exit_code"] == 1 and row["seconds"] >= 0


def test_gui_landing_has_batch_tab():
    import dfam_gui
    h = dfam_gui._landing()
    for frag in ('data-t="batch"', "p-batch", "go-batch", "/batchrow"):
        assert frag in h, frag
