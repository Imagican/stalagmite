# Getting started with stalagmite

*Make stalagmites, not stalactites.* This is the plain-English guide —
no prior command-line experience assumed.

## One-time setup

1. You need Python. If you use Miniforge/conda (you do, if you have a
   `cq` environment for CadQuery), open your usual prompt and activate
   it: `conda activate cq`. Otherwise install Python from python.org and
   tick **"Add Python to PATH"** during install.
2. Install stalagmite from this folder:

       cd "C:\Users\User\Desktop\DFAM TOOLKIT\dfam-toolkit"
       pip install .

   That pulls in everything it needs and gives you two commands:
   `stalagmite` and `stalagmite-orient`.

## Everyday use

Audit any STL — thread detection is automatic:

    stalagmite mypart.stl --auto-ex

Read the report bottom-up: the **defect features** list is the story
(each entry is one physical problem, not one slice), and the severity
tag tells you what to do — `fail` will not print, `judge` is a
printable bridge you get to keep or fix, `tolerable` is within the
1.8mm ledge allowance.

Ask it how to fix things:

    stalagmite mypart.stl --auto-ex --suggest

See the problems on the model (open the .ply in PrusaSlicer, MeshLab,
or Windows 3D Viewer; red = fail, orange = judged bridge, gold =
tolerable):

    stalagmite mypart.stl --auto-ex --export check.ply

The full treatment — surface-quality lint and thin-wall lint included:

    stalagmite mypart.stl --auto-ex --warn-angle 30 --min-wall 0.8 --suggest

Find the best build orientation when your part has functional surfaces
(threads must stay vertical; a seal face must print as the floor):

    stalagmite-orient mypart.stl --axis-vertical 0,0,1 --save oriented.stl
    stalagmite-orient mypart.stl --face 0,0,1:floor --save oriented.stl

Then re-audit `oriented.stl` before printing.

## What the flags mean

| flag | what it does |
|---|---|
| `--auto-ex` | auto-detect thread helices so they don't false-alarm |
| `--ex zlo:zhi:rmax` | manual exclusion cylinder (printed by --auto-ex for reuse) |
| `--suggest` | concrete repair suggestions with coordinates |
| `--export out.ply` | severity-coloured copy of the mesh |
| `--warn-angle 30` | also flag surfaces that print rough (not failing) |
| `--min-wall 0.8` | also flag walls thinner than 0.8mm |
| `--angle`, `--dz` | printer physics: overhang rule (45°) and layer height (0.4mm) |

## When something looks wrong

The thresholds (1.8mm ledge, 10mm bridge, 0.8mm wall) are community
defaults measured on specific machines — your printer may do better or
worse. Everything is a flag, nothing is hardcoded. The regression suite
(`python -m pytest test_fixtures.py`) should always pass; if it doesn't
after you edit something, the baseline in FIXTURES.md is the truth.

## Publishing it (when you're ready)

Install GitHub Desktop (desktop.github.com), sign up free, "Add local
repository" → this folder, then "Publish repository". That's the whole
git story. `LITERATURE.md` has every citation you'd want for a README
or a writeup.
