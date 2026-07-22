"""A deliberately unprintable design for stalagmite-autofix.

    stalagmite-autofix examples/autofix_demo.py --budget 24

A 20 mm block with a shelf sticking out of one wall at z = 12. Two
knobs are on the table:

    shelf_len  how far the shelf reaches (the design intent: 10 mm)
    gusset     how much of the shelf's underside a 38-degree wedge
               supports (0 = none .. 1 = all of it)

The nominal design (shelf_len = 10, gusset = 0) drops a 10 mm ledge
into thin air at z = 12 -- a hard FAIL. And here is the trap built
into the parameter box: shrinking the shelf alone can NEVER fix it,
because even at the minimum shelf_len of 3 mm the unsupported ledge
is ~2.6 mm -- past the 1.8 mm limit Adam & Zimmer measured (their
2.0 mm ledge destroyed itself). The only way out is the gusset, which
the search has to discover on its own. The closest printable design
keeps the shelf at (or near) its full 10 mm and grows a gusset under
~80 % of it.

Pure trimesh -- no CadQuery needed. A real workflow would put a
CadQuery build here; stalagmite audits those in memory the same way.
"""
import numpy as np
import trimesh

PARAMS = {
    "shelf_len": (3.0, 10.0),
    "gusset": (0.0, 1.0),
}
NOMINAL = {"shelf_len": 10.0, "gusset": 0.0}

BASE_X, BASE_Y, BASE_Z = 20.0, 16.0, 20.0     # the block
SHELF_Z0, SHELF_T = 12.0, 3.0                 # shelf underside + thickness
WEDGE_RISE = 1.3                              # rise per unit run (~38 deg)


def build(shelf_len, gusset):
    x1 = BASE_X / 2.0                                  # wall the shelf leaves
    base = trimesh.creation.box(extents=[BASE_X, BASE_Y, BASE_Z])
    base.apply_translation([0, 0, BASE_Z / 2.0])

    shelf = trimesh.creation.box(
        extents=[shelf_len + 1.0, BASE_Y, SHELF_T])   # +1: overlap into base
    shelf.apply_translation([x1 + shelf_len / 2.0 - 0.5, 0,
                             SHELF_Z0 + SHELF_T / 2.0])
    parts = [base, shelf]

    run = gusset * shelf_len
    if run > 1e-6:
        drop = min(SHELF_Z0, WEDGE_RISE * run)         # never below the bed
        y = BASE_Y / 2.0
        pts = np.array([
            [x1 - 0.5, -y, SHELF_Z0], [x1 - 0.5, y, SHELF_Z0],
            [x1 + run, -y, SHELF_Z0], [x1 + run, y, SHELF_Z0],
            [x1 - 0.5, -y, SHELF_Z0 - drop], [x1 - 0.5, y, SHELF_Z0 - drop],
        ])
        parts.append(trimesh.convex.convex_hull(pts))

    return trimesh.util.concatenate(parts)
