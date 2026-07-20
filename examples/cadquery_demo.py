#!/usr/bin/env python3
"""
CadQuery + stalagmite: the design-check-fix loop in one script.

CadQuery (https://cadquery.readthedocs.io) is code-based CAD: you describe
a part in Python and run the script to build it. Because a CadQuery part
is a Python object, stalagmite can audit it directly -- no exporting an
STL, no round-trip. This closes the design loop: build -> audit -> tweak a
parameter -> re-audit, all in one place.

Run:
    pip install cadquery      # one-time (large, pulls OpenCascade)
    python examples/cadquery_demo.py

You do NOT need to know CadQuery to read this -- the comments explain
each step.
"""
import os
import sys

# so the demo runs straight from the repo (a pip install makes this moot)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import cadquery as cq
except ImportError:
    sys.exit("This demo needs CadQuery:  pip install cadquery")

import stalagmite


def make_boss(taper_mm):
    """A 28mm-wide cap carried on an 8mm post -- a classic FDM problem:
    the wide cap overhangs the thin post. `taper_mm` is the height of a
    cone that eases the post out to the cap. taper_mm=0 is a flat
    'mushroom' (a horizontal overhang); a taller taper is a gentler,
    more printable slope.

    This is the whole point of a parameter: one number changes the part.
    """
    top_z = 26
    base = cq.Workplane("XY").box(40, 40, 4).translate((0, 0, 2))
    post_top = top_z - taper_mm
    part = base.union(
        cq.Workplane("XY").workplane(offset=4).circle(4)
        .extrude(post_top - 4))
    if taper_mm > 0:                      # cone from post (r4) to cap (r14)
        part = part.union(
            cq.Workplane("XY").workplane(offset=post_top).circle(4)
            .workplane(offset=taper_mm).circle(14).loft())
    part = part.union(
        cq.Workplane("XY").workplane(offset=top_z).circle(14).extrude(4))
    return part


def main():
    print("=" * 60)
    print("1) The obvious design: a flat cap on a post (a mushroom).")
    bad = make_boss(taper_mm=0)
    r = stalagmite.check(bad)             # audit the CadQuery part directly
    print(f"   status: {r.status}")
    for d in r.defects():
        print(f"     - {d}")
    r.write_report("boss_mushroom_report.html")
    print("   wrote boss_mushroom_report.html")

    print("=" * 60)
    print("2) Let the audit drive the fix: grow the taper until it prints.")
    best = None
    for taper in range(0, 16, 2):
        r = stalagmite.check(make_boss(taper))
        flag = "PRINTS" if r.printable else "fails "
        print(f"   taper {taper:2d}mm -> {flag}  [{r.status}]")
        if r.printable and best is None:
            best = taper
    print(f"\n   Minimum taper that prints cleanly: {best}mm")
    print("   (matches the 45-deg rule: the cap is 10mm wider in radius")
    print("    than the post, so it needs ~10mm of height to rise at 45.)")

    print("=" * 60)
    print("3) Ship the fixed part.")
    good = make_boss(taper_mm=best)
    r = stalagmite.check(good)
    print(f"   final status: {r.status}  ->  {'OK' if r.printable else 'NO'}")
    cq.exporters.export(good, "boss_fixed.stl")
    r.write_report("boss_fixed_report.html")
    print("   wrote boss_fixed.stl + boss_fixed_report.html")
    # a build script could gate on this:
    sys.exit(r.exit_code)               # 0 if printable, 1 if it FAILs


if __name__ == "__main__":
    main()
