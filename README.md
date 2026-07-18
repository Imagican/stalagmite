# stalagmite

**Make stalagmites, not stalactites.** Stalagmites grow from the ground
and stand; stalactites hang and need support. Stalagmite mechanically
enforces that rule on your STL — then tells you how to fix the part, not
where to put the scaffolding.

![stalagmite interactive report: a failed flange ring shown in red with
its repair suggestion alongside](docs/report_screenshot.png)

*The interactive 3D report (`--report`): click a defect, the camera
flies underneath it, and the fix is spelled out with coordinates —
"replace the flat with a ≥45° cone at least 10.1mm tall."*

Start with `HANDOFF.md` for the full story; design principles are in
`DFAM_RULES.md`; the literature behind every threshold is in
`LITERATURE.md`.

**The core rule as one test:** every slice must lie within a
`dz·tan(max_angle)` dilation of the slice below it. This single containment
check subsumes overhang detection, floating features, and unsupported starts.
Slicers paint overhangs red and scaffold around them; this tool exists to
tell you the *design* is wrong, and (eventually) how to fix it.

## Install

    pip install .
    # or manually:
    pip install numpy trimesh shapely networkx scipy

(`networkx` and `scipy` are quiet trimesh requirements — slicing fails
without them.)

## Quick start

    # audit any part -- thread helices are detected automatically
    stalagmite part.stl --auto-ex

    # the clean reference part, with manual exclusion zones instead
    python3 dfam_audit.py fixtures/06_clean_final.stl --ex 0:16.5:11 --ex 54:65:13

    # write a copy of the mesh with violating faces painted red
    # (open the .ply in any mesh viewer - MeshLab, f3d, Blender, PrusaSlicer)
    python3 dfam_audit.py part.stl --ex 0:16.5:11 --export part_violations.ply

Exit code is 0 on PASS, 1 when violations are reported.

Flags: `--angle` (default 45), `--dz` layer height (default 0.4mm),
`--ex zlo:zhi:rmax` cylindrical exclusion zone for thread helices
(repeatable), `--export out.ply` colored violation mesh, `--suggest`
parametrized repair suggestions (Tier 3), `--warn-angle 30` surface-
quality lint (prints, but degraded downskin — Saunders' yellow band),
`--min-wall 0.8` thin-feature lint (Hinchy FFF minimum). Lint warnings
never fail the audit.

Bridge features report the **roofed width** measured on the merged
multi-layer region (the physical span being crossed); a roofed width
beyond 10mm escalates the feature to fail severity.

## Interactive 3D report (`--report`)

    stalagmite part.stl --auto-ex --report report.html

One self-contained HTML file, openable in any browser, shareable as a
file, fully offline (three.js is vendored inline). A rotating 3D view
of the part with defect faces coloured by severity, beside a clickable
defect list — selecting a defect flies the camera underneath it (defects
are undersides) and reveals the Tier-3 repair suggestions. The clean
part shows a green PASS.

## Helix auto-detection (`--auto-ex`)

Thread helices legitimately migrate sideways along their flanks and
would otherwise false-positive. `--auto-ex` recognises them from a
first audit pass by their signature — many consecutive layers of small
constant-area lobes whose centroids lie on a circle and advance by a
consistent per-layer angle (the helix pitch) — then excludes the fitted
cylinders and re-audits. Real defects don't share the signature (flat
ledges are single wide layers; boss undersides are mirror-symmetric
pairs; bridges last a couple of layers), and thread-runout ledges just
above a helix are absorbed into its zone with a bounded growth cap.
On the six-fixture regression suite, auto-detection reproduces the
hand-tuned baseline exactly, and prints each zone in `--ex` form for
reuse. New users: see `GETTING_STARTED.md`.

## Tier 3: repair suggestions (`--suggest`)

Each defect feature gets concrete, parametrized fixes rather than "add
supports". Fail-severity features are grounded by a reachability search:
the highest solid a 45° hull can descend onto, reported with coordinates —

    [fail] steep-growth  z 14.3  ledge 8.6mm
        -> morph the transition: replace the flat with a >=45 deg
           chamfer/cone at least 8.6mm tall (the transition IS the shape)
        -> or gusset down to the solid at (-1.3,10.2) z=13.1

Repair taxonomy: ground-it (hull/gusset to nearest solid or bed pillar),
morph the transition, teardrop/diamond the opening, flatten/chamfer,
accept (judged bridge / functional flat per DFAM_RULES #4 and #7), or
reorient (Tier 4). Always re-audit after applying a repair — fixes can
create new overhangs (Adam & Zimmer 2014).

## Tier 2: violation classification

Every violation is classified by in-plane anchoring and given a severity
(thresholds are literature-sourced, see `LITERATURE.md`, and boundary-
condition dependent — treat them as defaults, not physics constants):

| class | meaning | severity |
|---|---|---|
| starts-in-air | new body appears with nothing below | fail |
| island | unsupported below AND unattached in-plane | fail |
| steep-growth | cantilever ledge, one-sided anchor | tolerable ≤1.8mm (Adam & Zimmer 2014), else fail |
| bridge | anchored on opposing sides | judge ≤10mm free span (Hinchy 2019), else fail |

Per-slice violations are aggregated into physical *defect features*
(consecutive layers, overlapping regions), so a six-fixture regression
part reports "1 defect: judged bridge" instead of three slice records.
The colored export encodes severity: red = fail, orange = judged bridge,
gold = tolerable ledge. Bridges are still reported **for human judgment**
— a deliberate design choice (see `DFAM_RULES.md` #7 and #10); note the
per-layer free-span figure measures corbelling steps, which understates
the physical hole diameter being roofed.

## Tier 4: orientation solver (`dfam_orient.py`)

Searches build poses minimising support volume *subject to what the part
is for* — the constraints plain auto-orienters don't know:

    # thread must stay vertical; helix zones excluded from the proxy
    python3 dfam_orient.py part.stl --axis-vertical 0,0,1 \
        --ex 0:16.5:11 --ex 54:65:13 --save oriented.stl

    # a seal face must print as the floor
    python3 dfam_orient.py part.stl --face 0,0,1:floor

Face modes: `floor` (normal ends up facing down), `up`, `wall`
(vertical), `not-down` (never support-scarred). Search is Gaussian-
process Bayesian optimisation (Matérn 5/2, LCB), ~35 evaluations, after
Goguelin, Dhokia & Flynn 2021; the objective is their support-ray-length
proxy plus heavily weighted constraint penalties (15° of violation ≈ the
worst-case support cost). Always re-audit the oriented mesh with
`dfam_audit.py` before printing.

## Python API

    import trimesh
    from dfam_audit import audit_mesh, export_colored

    mesh = trimesh.load("part.stl", force="mesh")
    bed_area, violations = audit_mesh(mesh, max_angle=45, dz=0.4,
                                      exclude=[(0, 16.5, 11)])
    for v in violations:
        print(v.z, v.area, v.kind, v.note)
    export_colored(mesh, violations, 0.4, "part_violations.ply")

## Tests

    pip install pytest
    python3 -m pytest test_fixtures.py

The six STLs in `fixtures/` are the genuine failure history of one real part
(a threaded pH-probe holder, v2→v7) with known defects — the regression
baseline any refactor must reproduce. See `fixtures/FIXTURES.md`.

## License

MIT
