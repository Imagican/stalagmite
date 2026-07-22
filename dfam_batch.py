#!/usr/bin/env python3
"""
dfam_batch.py - audit every part in a folder with one command.

    stalagmite-batch parts/ --auto-ex
    stalagmite-batch parts/ --json > batch.json
    stalagmite-batch parts/ --csv audits.csv

One line per part (status, fails, judges, tolerables, seconds), a
summary, and the gate contract scaled up: exit 0 = every part
printable, 1 = at least one FAIL, 2 = at least one file could not be
audited. Use it as the "before I ship the whole catalogue" gate.
"""
import os
import sys
import json
import time

EXTS = (".stl", ".obj", ".ply", ".3mf")


def audit_folder(folder, profile=None, auto_ex=False, say=print):
    """Audit every mesh in `folder` (sorted). Returns a list of dicts:
    {file, status, fails, judge, tolerable, seconds, error?}."""
    import stalagmite
    rows = []
    names = sorted(n for n in os.listdir(folder)
                   if n.lower().endswith(EXTS))
    for n in names:
        t0 = time.time()
        row = {"file": n}
        try:
            r = stalagmite.check(os.path.join(folder, n),
                                 profile=profile, auto_ex=auto_ex,
                                 suggest=False)
            row.update(status=r.status, fails=r.fails,
                       judge=r.count("judge"),
                       tolerable=r.count("tolerable"),
                       exit_code=r.exit_code)
        except (ValueError, OSError, TypeError) as e:
            row.update(status="ERROR", error=str(e), exit_code=2)
        row["seconds"] = round(time.time() - t0, 2)
        rows.append(row)
        say(f"  {row['status']:16s} {n}  "
            f"({row.get('fails', '-')} fail, {row['seconds']}s)")
    return rows


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Audit every STL/OBJ/PLY/3MF in a folder.")
    ap.add_argument("folder")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--profile-file", default=None)
    ap.add_argument("--auto-ex", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--csv", metavar="OUT.csv", default=None)
    a = ap.parse_args(argv)
    if not os.path.isdir(a.folder):
        print(f"error: not a folder: {a.folder}", file=sys.stderr)
        return 2
    import dfam_profiles
    try:
        prof = dfam_profiles.resolve(a.profile, a.profile_file)
    except (KeyError, OSError, ValueError) as e:
        ap.error(str(e))
    say = (lambda *x: None) if a.json else print
    say(f"== stalagmite batch: {a.folder} ==")
    say(f"   {prof.summary_line()}")
    rows = audit_folder(a.folder, prof, a.auto_ex, say)
    if not rows:
        print("no mesh files found", file=sys.stderr)
        return 2
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    worst = max(r.get("exit_code", 2) for r in rows)
    if a.csv:
        import csv
        with open(a.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=[
                "file", "status", "fails", "judge", "tolerable",
                "seconds", "error"])
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in w.fieldnames})
        say(f"csv written: {a.csv}")
    if a.json:
        print(json.dumps({"folder": a.folder, "profile": prof.name,
                          "counts": counts, "exit_code": worst,
                          "parts": rows}))
    else:
        say("summary: " + ", ".join(f"{v}x {k}"
                                    for k, v in sorted(counts.items())))
    return worst


if __name__ == "__main__":
    sys.exit(main())
