# stalagmite

**Make stalagmites, not stalactites.** Stalagmites grow from the ground
and stand; stalactites hang and need support. Stalagmite mechanically
enforces that rule on your STL — then tells you how to fix the part, not
where to put the scaffolding.

![stalagmite interactive report: a failed flange ring shown in red with
its repair suggestion alongside](https://raw.githubusercontent.com/Imagican/stalagmite/main/docs/report_screenshot.png)

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

## Quick start — no command line needed

    stalagmite-gui

Opens a local page in your browser with three tabs, so the whole toolkit
works without the command line:
- **Audit** — drop an STL, get the full interactive 3D report (open or download it)
- **Orient** — find a better build pose, see the support reduction, download the rotated STL
- **Compare** — drop two revisions, see what your change resolved / introduced

Runs entirely on your machine (localhost); nothing is uploaded.

## Quick start — command line

    # audit any part -- thread helices are detected automatically
    stalagmite part.stl --auto-ex

    # the clean reference part, with manual exclusion zones instead
    python3 dfam_audit.py fixtures/06_clean_final.stl --ex 0:16.5:11 --ex 54:65:13

    # write a copy of the mesh with violating faces painted red
    # (open the .ply in any mesh viewer - MeshLab, f3d, Blender, PrusaSlicer)
    python3 dfam_audit.py part.stl --ex 0:16.5:11 --export part_violations.ply

## Diff two revisions (`stalagmite-diff`)

Iterating on a part? Compare the old and new STL and see exactly what
your change did:

    stalagmite-diff old.stl new.stl --auto-ex

Reports each defect feature as **RESOLVED** (gone), **PERSISTS** (still
there, with any severity change), or **NEW / NEW-FAIL** (introduced), and
a verdict of IMPROVED / REGRESSED / CHANGED / UNCHANGED. Exit code is 1
only if the change *regressed* (introduced or worsened a failure), so you
can gate a parametric-CAD workflow on "my edit didn't break anything." It
assumes both revisions share a coordinate frame (they're iterations of
one part, not re-orientations).

## Automating a "before I ship" gate

Machine-readable output for scripts and CI, three equivalent ways in:

Bash — exit code only (simplest gate):

    stalagmite part.stl --auto-ex || { echo "not printable"; exit 1; }

Bash — full JSON to log/parse (`--json` prints one object; exit code
unchanged: 0 = PASS/PASS_WITH_LIMITS/REVIEW, 1 = FAIL):

    stalagmite part.stl --auto-ex --json > audit.json
    # audit.json: {status, printable, exit_code, profile, thresholds,
    #   counts:{fail,judge,tolerable}, features:[{class,severity,z,
    #   centroid,ledge_mm|roof_width_mm,repairs}], exclusions,
    #   auto_zones:[{zlo,zhi,rmax,center,step_deg,lobes}], health}

Python — the same dict, plus the live objects:

    import stalagmite
    r = stalagmite.check("part.stl", auto_ex=True)
    if r.failed:
        raise SystemExit(f"{r.status}: " + "; ".join(r.defects()))
    r.to_dict()      # same shape as --json
    r.to_json()

The JSON shape (and `AuditResult.to_dict()`) is the stable contract —
gate and log against those keys.

## Result states

The audit reports one of four truthful states — a deliberate bridge does
not read like an unprintable floating boss:

| state | meaning | exit |
|---|---|---|
| PASS | every layer supported; no concerns | 0 |
| PASS_WITH_LIMITS | prints as-is; only within-allowance ledges / surface notes | 0 |
| REVIEW | printable, but contains judged bridge(s) — eyeball first | 0 |
| FAIL | will not print as oriented; needs a fix or reorient | 1 |

Only FAIL is a nonzero exit, so it's safe in CI while still distinguishing
the printable-but-noteworthy cases in the status line and report.

## Process profiles

There are no universal thresholds: the slice-containment *principle* is
universal, but the *numbers* (overhang angle, bridge span, wall, ledge)
depend on nozzle, layer height, material and machine. Profiles bundle them
under a name, with provenance for each value.

    stalagmite part.stl                              # conservative generic-fdm (default)
    stalagmite part.stl --profile generic-fdm-fine   # 0.2mm-layer variant
    stalagmite part.stl --profile-file myprinter.json  # your calibrated setup
    stalagmite --list-profiles

You never have to pick a printer — the default is a documented, cautious
generic-FDM profile. A named or custom profile just makes the advice
machine-specific. Individual flags (`--angle`, `--dz`, `--ledge-max`,
`--bridge-max`, `--warn-angle`, `--min-wall`) override any profile value.
See `docs/profiles/` for the JSON format.

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

Selecting a defect in the report also draws its **transition diagram** —
a 2D cross-section showing the supporting slice below, the allowed 45°
envelope grown from it, this slice, and the material poking past the
envelope in red. It shows *why* the feature fails and what shape would
have been allowed, not just which facets are wrong. For fail features it
adds a one-line fix: morph the red back within the dashed envelope (the
envelope outline is the exact allowed shape for that cross-section), or
ground it to the solid below.

Face modes: `floor` (normal ends up facing down), `up`, `wall`
(vertical), `not-down` (never support-scarred). Search is Gaussian-
process Bayesian optimisation (Matérn 5/2, LCB), ~35 evaluations, after
Goguelin, Dhokia & Flynn 2021; the objective is their support-ray-length
proxy plus heavily weighted constraint penalties (15° of violation ≈ the
worst-case support cost). Always re-audit the oriented mesh with
`dfam_audit.py` before printing.

## Python API — `import stalagmite`

One call audits a part and hands back a result. It accepts a **CadQuery
object, an STL/OBJ/PLY/3MF path, a trimesh, or a (vertices, faces) pair**:

    import stalagmite

    r = stalagmite.check(part, auto_ex=True)   # part = any of the above
    print(r.status)          # PASS / PASS_WITH_LIMITS / REVIEW / FAIL
    print(r.printable)       # True unless FAIL
    for d in r.defects():
        print(d)
    if r.failed:
        r.write_report("audit.html")
    exit(r.exit_code)        # 0 printable, 1 FAIL -- gate a CI/build step

### CadQuery: the design loop in code

Because a CadQuery model is a Python object, stalagmite audits it directly
— no STL export, no round-trip. Build → audit → tweak a parameter →
re-audit, all in one script:

    import cadquery as cq, stalagmite
    part = make_bracket(gusset=False)
    if stalagmite.check(part).failed:
        part = make_bracket(gusset=True)      # change a parameter
    stalagmite.check(part).write_report("ok.html")

See `examples/cadquery_demo.py` for a runnable version that lets the audit
*drive* the fix — sweeping a taper parameter until the part prints
(`pip install stalagmite[cadquery]`).

### Lower-level

    import trimesh
    from dfam_audit import audit_mesh, export_colored
    mesh = trimesh.load("part.stl", force="mesh")
    bed_area, violations = audit_mesh(mesh, max_angle=45, dz=0.4,
                                      exclude=[(0, 16.5, 11)])
    export_colored(mesh, violations, 0.4, "part_violations.ply")

## Robustness

`load_mesh()` sanitises input (drops infinite/NaN coords and degenerate/
duplicate faces, merges coincident vertices, concatenates scenes) and
`mesh_health()` caveats non-watertight meshes, inconsistent winding, and
suspicious units — so real-world and messy STLs are audited without
crashing, with an honest note about how much to trust the result.

## Tests

    pip install pytest
    python3 -m pytest test_fixtures.py

The six STLs in `fixtures/` are the genuine failure history of one real part
(a threaded pH-probe holder, v2→v7) with known defects — the regression
baseline any refactor must reproduce. See `fixtures/FIXTURES.md`.

## License

MIT
