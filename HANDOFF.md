# DfAM Toolkit — Project Handoff

## What this is

A design-for-additive-manufacturing audit tool that mechanically enforces
print physics on STL geometry — and, in its ambitious form, tells you **how
to fix the part** instead of scaffolding around it.

Born from a real build: a threaded pH-probe holder iterated v2→v7 under a
human slicer-eye review loop. Every failure mode was diagnosed, fixed, and
frozen as a test fixture. The tool caught real defects — including a 0.65mm
internal micro-bridge its own author introduced — before any filament moved.

## The thesis (why this deserves to exist)

Slicers paint overhangs red and answer every problem with supports. They
treat geometry as immutable. This tool's differentiators:

1. **Prescriptive repair.** Classify each violation (*starts-in-air* /
   *steep growth* / *bridge* / *island*) and map it to a fix taxonomy:
   ground it (gusset/hull to nearest solid), morph the transition,
   teardrop-down, reorient, or accept-as-bridge. Output like: *"boss at
   z=36 starts in air — hull it to the flange corner at (19.6, 0)."*
   Nothing in the hobbyist ecosystem says that sentence.
2. **Functional-surface-aware orientation.** User tags faces ("seal face:
   must print as floor/wall", "thread: vertical"). An orientation solver
   searches poses weighted by those constraints, not just support volume.
   Existing auto-orienters (Tweaker-3 etc.) don't know a gland seat from
   a cosmetic face.
3. **The core rule as one test:** every slice must lie within a
   `dz·tan(max_angle)` dilation of the slice below. This single check
   subsumes overhang detection, floating features, and unsupported starts.

## What exists and is proven (`dfam_audit.py`)

- Slices the mesh at `dz` (default 0.4mm), builds each slice's region in
  **world coordinates** directly from `section.discrete` loops (nested
  loops resolved by area-sorted union/difference).
- Flags any area of slice N outside `buffer(slice N-1, dz·tan(angle)+0.05)`.
- Cylindrical **exclusion zones** (`--ex zlo:zhi:rmax`) for thread helices,
  which legitimately move sideways along their flanks and false-positive
  otherwise.
- Reports violations with z, area, span, centroid; small spans are
  presented as bridges **for human judgment** — deliberate design choice,
  not a gap.
- Deps: `numpy`, `trimesh`, `shapely`. Pure Python, no slicer needed.

## Hard-won engineering notes (do not relearn these)

- **Never use `Path3D.to_2D()` per-slice for comparisons**: each slice gets
  an arbitrary rotation frame; cross-slice comparison then hallucinates
  violations at every rotationally-asymmetric feature. World-space
  `section.discrete` is the way. (This bug was found because a known-clean
  part failed and a symmetric one didn't — asymmetry-only failures are the
  fingerprint.)
- **Thread helices** violate vertical-growth logic at any practical dz;
  exclusion zones are correct for v1. A future helix-aware detector could
  auto-recognize them (periodic angular migration of a constant-area lobe).
- **Bridges are judgment calls**: a 5mm round-hole ceiling is deliberately
  kept (tap integrity) and should be *reported*, not failed. Keep the
  human in the loop until the classifier (Tier 2) exists.
- **The design principles the tool enforces** are in `DFAM_RULES.md` —
  headline: *the transition IS the shape.*

## Test fixtures (`fixtures/`)

Six frozen STLs = the genuine failure history of one part, catalogued with
known defects and expected results in `fixtures/FIXTURES.md`. This is the
regression suite: any refactor must reproduce the baseline (01 worst → 06
clean-with-one-judged-bridge). `source_probe_holder.scad` regenerates 06
(OpenSCAD + BOSL2).

## Roadmap

- **Tier 1 (a weekend):** harden the CLI; export violations as a colored
  mesh (PLY/3MF) openable in any viewer; `pip` packaging; pytest wrapping
  the fixture baselines; README + license. This alone is a publishable
  small open-source tool for the OpenSCAD/BOSL2 crowd.
- **Tier 2:** violation classifier (starts-in-air / steep-growth / bridge /
  island) via region tracking across slices.
- **Tier 3:** repair suggester — map classes to parametrized fixes with
  concrete geometry ("hull to nearest solid at ...").
- **Tier 4:** constraint-aware orientation solver with face tagging.
- **Prior art to position against:** slicer overhang painting, Tweaker-3
  (auto-orientation), Netfabb/Magics (industrial repair). The gap is
  prescriptive *design* feedback for parametric-CAD hobbyists.

## Status 2026-07-18 — Tier 1 largely done

- Baseline confirmed on all six fixtures (9/5/4/4/4/3). **Correction:** the
  single documented audit command only fits fixtures 04–06; the BSP
  lengthening at 04 shifted the part +10mm, so 01–03 need `--ex 44:55:13`
  for the M24 helix. FIXTURES.md updated; `test_fixtures.py` encodes it.
- `test_fixtures.py`: 13 pytest cases — parametrized baseline (counts + z
  signatures) plus per-defect semantic tests (boss underside, floating
  apex, functional flat reported-not-passed, 0.65mm micro-ring, judged
  bridge, exclusion-zone sanity, export round-trip).
- Colored-mesh export shipped: `--export out.ply` paints violating faces
  red (face-centroid within one layer of a violation z and inside the
  region buffered 0.4mm). `audit_mesh()` / `export_colored()` are now a
  clean Python API; CLI exit code 0=PASS, 1=violations.
- Packaging: `pyproject.toml` (`pip install .` → `dfam-audit` console
  script), MIT LICENSE, README rewritten. Name still open.

Remaining Tier 1: pick a name, git init, publish. Then Tier 2 (classifier).

## Status 2026-07-18 (later) — Tier 2 shipped

- Classifier in `dfam_audit.py`: each violation classified by in-plane
  anchoring — starts-in-air / island (no anchor) / steep-growth (one-sided)
  / bridge (opposing anchors, ≥120° subtended). Severities: fail / judge /
  tolerable, thresholds from the literature study (LITERATURE.md):
  Adam & Zimmer 1.8mm ledge allowance, Hinchy 10mm bridge span.
- Exclusion zones count as anchoring material (a region touching a thread
  helix is not an island) — without this the flange ring misclassified.
- `aggregate()` groups per-slice violations into physical defect features
  (same class group, consecutive z, plan overlap, with transitive merge);
  the six fixtures now report their catalogue stories: 06 = "1 defect:
  judged bridge", 01 = flange fail + boss fail + bridge.
- Export colours by severity (red fail / orange judge / gold tolerable).
- 18 pytest cases; baseline 9/5/4/4/4/3 untouched.
- Known limitation: per-layer bridge free-span measures the corbel step
  (~2·dz·tan45), not the physical roofed diameter; the feature-level span
  should eventually be derived from the merged geometry.

Next: Tier 3 repair suggester (violation feature -> parametrized fix with
concrete geometry: hull to nearest solid, gusset, teardrop/diamond,
flatten-apex, reorient). Every suggested repair must be re-audited —
Adam & Zimmer's own rules show fillets can create new overhangs.

## Status 2026-07-18 (later still) — Tier 3 shipped (v0.3.0)

- `suggest_repairs()` + CLI `--suggest`: every defect feature gets
  parametrized fixes. Fail features are grounded via `_find_anchor()` —
  a reachability search over the slice stack for the highest solid a
  45° hull can descend onto (clearance <= drop * tan(angle)), reported
  with coordinates. The flange suggestion reproduces the real v4 fix
  ("45° cone, 8.6mm tall"); the target sentence from this handoff's
  thesis ("hull it to the solid at (x,y) z=...") now prints.
- Repair taxonomy: ground-it (hull/gusset w/ coords, bed pillar), morph
  (with required transition height = ledge), teardrop/diamond (apex ~
  width/2), accept (judged bridge; functional flat per DFAM_RULES #4/#7),
  reorient (Tier 4 pointer). Suggestions echo the design rules by number.
- 21 pytest cases; baseline still 9/5/4/4/4/3.

Next: Tier 4 orientation solver. Recipe from LITERATURE.md (Goguelin
2021): pose = (θx, θy), GP surrogate + Matérn kernel, ~35 evaluations,
support-ray-length proxy — but with Tier-2-informed objective (islands
fatal, judged bridges cheap) and user-tagged functional-surface
constraints ("seal face floor/wall", "thread vertical"), which nothing
in the literature provides. Also still open: name, git init.

## Status 2026-07-18 (evening) — Tier 4 shipped (v0.4.0)

- `dfam_orient.py` + `dfam-orient` console script. Pose = (θx, θy) with
  drop-to-plate; objective = area-weighted support-ray-length proxy
  (Goguelin's best proxy) + constraint penalties. Constraints:
  `--axis-vertical x,y,z` (threads; up or down both fine) and
  `--face nx,ny,nz:floor|up|wall|not-down`. Part-frame `--ex` cylinders
  mask thread-helix faces out of the proxy (valid while the axis
  constraint holds). Constraint weight auto-calibrated: 15° of violation
  ≈ worst seed-pose support cost.
- Search: hand-rolled GP (Matérn 5/2 on wrap-around angle distance,
  LCB acquisition over random candidates + local jitter), numpy-only —
  no scikit-learn dependency. ~3s for 28 evaluations on the 13k-face
  probe holder.
- Validation: fixture 06 + thread-vertical constraint returns the
  identity pose (how the part was really printed); an unconstrained T
  shape escapes its upright overhang pose (>70% proxy reduction); a
  floor-face constraint forces the 180° flip against support cost.
- 24 pytest cases; baseline untouched.
- Known limits: proxy is facet-based (no island detection per pose —
  re-audit the saved pose with dfam_audit.py, which the CLI reminds you
  to do); exclusion mask is part-frame only.

All four tiers of the original roadmap now exist. Remaining: git init,
publish; then refinements (feature-level bridge span from merged
geometry, Saunders 30° warn band, wall-thickness lint, Tier-2-informed
orientation objective).

## Status 2026-07-18 (night) — refinements (v0.5.0)

- Feature-level bridge span: `aggregate()` now measures the roofed
  width on the merged multi-layer region (minimum-rotated-rectangle
  minor axis); >10mm escalates the feature to fail. Fixture 06 reports
  "roofed width ~2.4mm" instead of the misleading 1.2mm corbel step.
- `--warn-angle 30` (Saunders yellow band): regions fine at 45 deg but
  outside the milder dilation are linted as surface-quality warnings —
  correctly flags 06's 45 deg morph cone (13 layers) without touching
  the violation count. `--min-wall 0.8` thin-feature lint
  (morphological opening per slice; exclusion zones respected).
  Warnings never affect PASS/FAIL or the baseline.
- Orientation proxy is now severity-weighted (Tier-2-informed): facet
  weight 0.25 at the critical angle up to 1.0 facing straight down —
  near-45 deg overhangs cost little, flat undersides cost full.
- Suggest footer adds the Lieneke z-snap tip. networkx+scipy declared
  as dependencies (first field run on Windows caught the omission).
- 27 pytest cases; baseline untouched.

## Status 2026-07-18 (late night) — helix auto-detection (v0.6.0)

The future-work item from the original handoff ("a future helix-aware
detector could auto-recognize them — periodic angular migration of a
constant-area lobe") now exists: `detect_helix_zones()` + `--auto-ex`.

- Recognition: small violations clustered by contiguous z; Kasa
  circle fit on lobe centroids (radial-outlier rejection + refit);
  gates: >=8 members over >=6 layers, radius 3-60mm, fit RMS <
  max(0.15r, 0.6mm), median per-layer angular step 10-160 deg with
  >=70% sign consistency. Measured on the fixtures: BSP +79.4
  deg/layer @ r9.1, M24 +71.9 deg/layer @ r11.0 — textbook clean.
- Thread-runout absorption: ledges just above a helix within the zone
  radius are absorbed, growing the zone in z AND r under a hard cap
  (rmax0+2.0) so zones can never creep onto real defects.
- Exclusion zones generalised to (zlo, zhi, rmax[, cx, cy]) everywhere
  (audit, anchoring, lint, orient mask); --ex accepts 5-field form;
  --auto-ex prints detected zones in reusable --ex syntax.
- THE GATE: auto-detection reproduces the hand-tuned baseline
  9/5/4/4/4/3 on all six fixtures with zero manual input, and finds
  exactly 2 zones per fixture (boss lobes, bridges, islands, prisms
  all correctly rejected). 35 pytest cases green.
- GETTING_STARTED.md added (plain-English guide incl. GitHub Desktop
  publishing path).

## Status 2026-07-18 (v0.7.0) — interactive HTML 3D report

- `--report out.html` (dfam_report.py): one self-contained file — panel
  with logo/stats/defect cards + three.js viewer (z-up custom orbit,
  drag/wheel/right-drag). Clicking a defect flies the camera to it FROM
  BELOW (defects are undersides), shows a wireframe locus marker, and
  expands the Tier-3 repairs in the card. Severity face colours match
  the PLY export. PASS case renders green.
- three.js r128 vendored (vendor_three.py, gzip+b64, MIT) after the
  sandbox browser exposed the CDN as a point of failure — reports work
  fully offline forever. Verified end-to-end with headless-Chromium
  screenshots (the fixture-01 flange ring renders red with its morph
  suggestion alongside).
- Logo: user supplied a mark (layered stalagmite + plumb line); an SVG
  recreation is inline in the report header. Original PNG still to be
  added to the repo when supplied as a file.
- 37 pytest cases green. This is also the GUI decision point captured:
  HTML report first, publish, then judge whether a full app earns it.

## Named 2026-07-18: **stalagmite**

"Make stalagmites, not stalactites" — stalagmites grow from the ground
and stand; stalactites hang and need support. PyPI name checked
available. Console scripts: `stalagmite` (audit), `stalagmite-orient`;
legacy `dfam-audit`/`dfam-orient` aliases kept. Module filenames
unchanged for now (dfam_audit.py, dfam_orient.py) — rename to a
`stalagmite/` package at git init if desired.

## Suggested first session in the new project

1. `pip install numpy trimesh shapely`; run the audit on all six fixtures;
   confirm the baseline table in FIXTURES.md.
2. Wrap that as pytest.
3. Build the colored-mesh violation export (paint offending faces red into
   a PLY) — the single highest-value UX addition.
4. Pick a name, init the repo, MIT license.
