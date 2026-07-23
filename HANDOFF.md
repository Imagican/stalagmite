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

## Status 2026-07-21 (v0.17.0) — STAGE B: stalagmite-fix (apply + prove)

The apply-and-verify loop, maximum-effort build. `dfam_fix.py`:
- apply_fixes(mesh, profile, ...): audit -> make_repair_specs ->
  loft_solid bodies -> union_bodies() -> re-audit -> decide_verdict().
- union_bodies(): engines in trust order manifold -> trimesh default ->
  shell concat; degrades PER BODY with notes, never aborts the fix.
- decide_verdict() (pure, unit-tested): NOTHING_TO_FIX / VERIFIED (no
  fails after, no new fails, nothing worsened) / PARTIAL / NOT_IMPROVED.
  Uses dfam_diff.match_features (renamed from _match, now the shared
  brain of diff + fix).
- NEVER-WORSE GUARANTEE: NOT_IMPROVED withholds the output file
  (--force overrides). Exit contract: 0 printable / 1 still-FAIL or
  not-improved / 2 error. --json full machine object incl. wrote path.
- CLI stalagmite-fix: -o out (default <name>_fixed.stl), --height/
  --easing/--flare (same params as the sculptor), --report fixed.html
  (interactive report of the FIXED part), --auto-ex, profiles.
- stalagmite.fix() API -> FixResult (.verdict/.mesh_fixed/.write/
  .to_dict/.ok_to_write/.exit_code).
- GUI: /fix endpoint (run_fix returns verdict + fixed STL b64 + FULL
  fixed-part report HTML); viewer bar gains "Auto-fix & re-audit" ->
  verdict banner (VERIFIED green), Download fixed STL, iframe swaps to
  the fixed report. Verified end-to-end with Playwright: fixture 01 ->
  "VERIFIED FAIL -> REVIEW, 1 resolved", fixed geometry visibly shows
  the cone + boss gusset, 0 fail.
- Headline test: fixture 01 FAIL(2 fail) -> VERIFIED -> REVIEW(0 fail),
  written file independently re-audits clean. 103 tests total
  (64 fixtures + 19 robustness + 7 repair + 13 fix).

## Status 2026-07-21 (v0.16.0) — Stage A "doing": sculptable repairs

The telling->DOING roadmap's Stage A, incl. the user's sculpting idea.
`dfam_repair.py`:
- make_repair_specs(): per fail feature, a loft spec from REAL slice
  contours (the anti-v0.12.0 principle: geometry only from the audited
  slices). top = part outline at the defect; bottom = walk down for the
  highest support whose contour a >=angle loft can reach; else bed
  pillar (own footprint to plate). Contours resampled to N_RING=96 and
  angle-aligned so lofting = per-vertex lerp (cheap enough for live JS).
  Spec: {kind, z_top, z_bot, z_floor(bed), min_h, max_gap, top, bot}.
- loft_solid(spec, height, easing, flare): watertight trimesh (side
  strips + centroid-fan caps); height clamped to z_floor (a repair may
  never extend below the bed -- found via browser STL that landed at
  z=-4.3).
- emit_fix_stl() + CLI `--emit-fix OUT.stl`: default bodies for all
  fail features, union-ready.
Report: #fixpanel sculptor -- live green loft ghost rebuilt on Height/
Easing(1..2.5 chamfer->fillet)/Flare sliders; physics badge (worst
slope = atan(gap*easing/H) vs profile angle; red "won't fit above the
bed" when easing pushes min height past z_floor); Download repair STL
(binary STL written in JS from the ghost triangles -- works offline).
Pillar kind locks the height slider.
STAGE B TASTE TEST (test_union_fix_improves_audit, manifold3d): union
generated repairs into fixture 01 -> FAIL becomes REVIEW, zero fail
features. The tool now fixes parts and verifies its own fix.
Flange spec = the real v4 cone (neck r~10 -> hex r~18, min_h 10.5);
rect-ledge case gets its true rectangular footprint. 90 tests
(64 fixtures + 19 robustness + 7 repair). Known limits: multi-lobed
fixes get no sculptor spec (emit-fix still covers); boss-type fixes
loft the whole containing component (a collar, valid but heavy);
easing>1 raises min height by xeasing (badge enforces).

## Status 2026-07-20 (v0.15.0) — robustness round 2: torture battery

test_robustness.py: pathological meshes (open, inverted winding, NaN/inf
vertices, self-intersecting, disconnected shells, zero-height plate,
single triangle, tiny/huge units, dup+degenerate faces) must audit
cleanly; empty/garbage inputs must raise clean ValueError; CLI must
never traceback. Findings + fixes:
- empty (verts,faces) / faceless trimesh crashed with TypeError (bounds
  None) -> _require_usable() guard in load_mesh + stalagmite.to_mesh
  (all branches) -> clean ValueError.
- inside-out meshes (consistent inverted winding: watertight, volume<0)
  audited as meaningless PASS -> sanitize_mesh now auto-inverts;
  mesh_health flags "inside-out" if still negative.
- load_mesh wraps parser exceptions -> ValueError with filename.
- CLI exit-code contract extended: 2 = could not audit (ValueError/
  OSError), stderr "error: ..." or --json {"status":"ERROR",
  "exit_code":2} object. 0/1 semantics unchanged. Documented in README
  gate section ("treat 1 and 2 as do-not-ship").
- mesh_health(mesh, dz=None): new slice-count note (>2500 slices ->
  "audit may be slow, coarser --dz"); callers pass dz.
- perf regression guard: 20k-face icosphere audits < bound (currently
  ~2s); ASCII STL round-trip test.
NaN-vertex case investigated: sanitize welds to a valid corner-chopped
solid -> honest PASS, no fix needed. 83 tests total (64 + 19).

## Status 2026-07-20 (v0.14.0) — machine interface: --json + to_dict()

For "before I ship" automation. `result_dict()` in dfam_audit is the one
serializer; both CLI `--json` and `AuditResult.to_dict()`/`.to_json()`
use it -> identical shape. Keys: part, status, printable, exit_code,
profile, thresholds, bed_contact_mm2, health, counts{fail,judge,
tolerable}, feature_count, features[{class,severity,z,layers,centroid,
ledge_mm/cumulative_reach_mm/roof_width_mm,repairs}], exclusions,
auto_zones[{zlo,zhi,rmax,center,step_deg,lobes}]. `--json` prints ONE
object and suppresses human text (say() shim); exit codes unchanged
(FAIL=1 else 0), so `stalagmite p.stl --auto-ex --json` gates cleanly.
audit() gained as_json param; AuditResult stores auto_zones + thresholds.
64 pytest (added 2). This is the stable machine contract.

## Status 2026-07-19 (v0.13.0) — Python API + CadQuery + classifier fix

- **`import stalagmite` public API** (stalagmite.py facade module):
  `check(obj, ...)` -> `AuditResult` (status, printable, failed,
  exit_code, count(), defects(), write_report()). `to_mesh(obj)` coerces
  a CadQuery Workplane/Shape, an STL/OBJ/PLY/3MF path, a trimesh, a
  trimesh Scene, or a (verts, faces) pair. Also re-exports profile(),
  diff_audits, solve_orientation, write_report.
- **CadQuery integration**: `_cq_to_mesh()` tessellates a Workplane/Shape
  in memory (fallback: cq STL export) -- audits a CadQuery part with no
  file round-trip. Optional extra `pip install stalagmite[cadquery]`.
  Worked demo `examples/cadquery_demo.py`: parametric boss, audit-driven
  taper sweep finds the 45-deg minimum (10mm), writes reports, exits 0/1
  for CI. Verified end-to-end (cadquery 2.8 installed in dev).
- **Classifier fix found via the CadQuery test**: a steep cone that grows
  ~1.6mm/layer (a ~79deg overhang) was mis-rated "tolerable" because each
  per-layer ledge was under the 1.8mm allowance. The allowance is for an
  ISOLATED ledge; a sustained slope stacks. aggregate() now sums per-
  layer cantilever reaches into `cum_reach`; a steep-growth feature with
  cum_reach > LEDGE_MAX escalates tolerable->fail. Baseline 9/5/4/4/4/3
  and all severity tests unchanged (per-violation severity untouched;
  only feature-level). 62 pytest (added 6).

## Status 2026-07-19 (v0.12.1) — REVERTED the 3D fix ghost (was wrong)

v0.12.0 tried a translucent green 3D ghost of the fix (cone/pillar).
REMOVED in 0.12.1: it modelled every fix as a circular CONE primitive
centred on the feature centroid with a bbox radius -> for a rectangular
enclosure with a small edge overhang it drew a giant green disc floating
mid-part, obscuring the real defect. User (correctly): "way off, does
more harm than good." Lesson: a circular primitive is only honest for
axisymmetric features; a correct 3D fix ghost needs a real swept-
envelope solid lofted from the actual support polygon (deferred - hard,
maybe later). Instead the accurate 2D transition diagram (already exact
for ANY cross-section, incl. rectangles) now carries a one-line fix
caption on fail features: "morph the red back within the dashed
envelope, or ground to solid below." _fix_preview()/showFix()/fixtog
all removed. 56 pytest (dropped the 2 fix tests).

Kept from this session: v0.11.1 UX -- Audit tab shows the report inline
full-screen immediately (iframe #viewer + slim bar New audit/Download/
Open), no separate "open" click (user feedback).

## Status 2026-07-19 (v0.11.0) — full GUI (audit + orient + compare)

The browser app is now the whole toolkit, no CLI needed. `dfam_gui.py`
rewritten with three tabs and testable endpoint helpers:
- run_audit_html(bytes,...) -> report HTML (Audit tab; Open + Download).
- run_orient(bytes, axis) -> JSON {theta_x, theta_y, before, after,
  reduction%, oriented STL base64}. Orient tab shows support-% cut +
  "Download oriented STL"; optional keep-axis-vertical for threads.
- run_diff(old_bytes, new_bytes,...) -> JSON verdict + resolved/persist/
  introduced (serializable via dfam_diff._label). Compare tab renders a
  coloured diff list + status badges.
POST routes: /audit (raw->HTML), /orient (raw->JSON+b64 STL),
/diff (JSON{old,new b64}->JSON). All localhost, 300MB cap. Verified
end-to-end with Playwright (drove the Compare flow: 05->06 IMPROVED).
56 pytest cases (added 4 GUI-endpoint tests). T-shape orient demo:
-100% support (rotates flat).

## Status 2026-07-19 (v0.10.0) — kernel robustness + browser GUI

- **Robustness (Terra #7).** `load_mesh(path)` concatenates scenes,
  rejects empty/non-mesh, and `sanitize_mesh()` drops infinite/NaN
  coords + degenerate/duplicate faces + merges vertices (all guarded for
  trimesh API drift). `mesh_health(mesh)` returns notes (non-watertight,
  winding, near-zero height, suspicious units) shown in CLI and report.
  `slice_region()` fully wrapped -> None on any bad section instead of
  crashing. audit()/diff/gui all use load_mesh. Baseline untouched
  (tests still load fixtures via trimesh.load + audit_mesh directly).
- **Browser GUI (`stalagmite-gui`).** `dfam_gui.py`: stdlib
  ThreadingHTTPServer on 127.0.0.1:8757, branded drop-an-STL landing
  page (profile dropdown, auto-ex + suggest checkboxes), POST /audit
  receives raw bytes -> runs the real tested pipeline -> returns the
  report HTML, which the page opens as a blob URL. Localhost only,
  nothing uploaded. `dfam_report.render_report()` factored out (returns
  HTML string) so the GUI reuses the exact report code. 300MB cap,
  graceful error page.
- 52 pytest cases. Answers "is it CLI-only?" -> no longer.

## Status 2026-07-19 (v0.9.0) — diff mode (the v2->v7 loop as a command)

My addition beyond Terra's list (they missed it). `dfam_diff.py` +
`stalagmite-diff old.stl new.stl`: audits both revisions under one
profile, matches defect features by class-group + plan position + z
overlap (same coordinate frame assumed), and reports each as RESOLVED /
PERSISTS (with severity delta) / NEW / NEW-FAIL. Verdict IMPROVED /
REGRESSED / CHANGED / UNCHANGED; exit 1 only on regression (introduced
or worsened a fail) -> CI-gateable. Validated on the real history:
05->06 = micro-ring RESOLVED, bridge PERSISTS, IMPROVED; 03->01 =
boss NEW-FAIL, REGRESSED/exit1. `diff_audits()` public API. 49 pytest.

## Status 2026-07-19 (v0.8.1) — transition-explainer overlay

Terra review point #9, shipped. Selecting a defect in the HTML report
now draws a 2D cross-section (SVG) beside the 3D view: support slice
below (gray fill), the 45-deg allowed envelope grown from it (blue
dashed), this slice (light outline), and material past the envelope
(red fill). Turns "red facets" into "here's why, and here's the allowed
shape." Refactored `slice_region(mesh, z)` out of `slices()` (single-z
sectioning, reused by the report). `dfam_report._transition_diagram()`
+ `_rings()` build the payload; JS `drawSlice()` renders it in the
`#slice` panel. 45 pytest cases. The flange fixture's diagram is the
poster child: giant red hex on a tiny dashed-circle envelope = wide
feature on a narrow neck.

## Status 2026-07-19 (v0.8.0) — truthful states + profiles

Acting on external review (ChatGPT "Terra 5.6"): its two highest-value,
lowest-risk points, both shipped.

- **Truthful result states.** `overall_status()` -> PASS /
  PASS_WITH_LIMITS / REVIEW / FAIL from aggregated feature severities +
  lint. Fixes a real inconsistency: fixture 06 ("clean, one intentional
  bridge") used to exit 1 like an unprintable boss; now REVIEW/exit 0.
  Only FAIL is nonzero (CI-safe). Status shown in CLI final line and as
  a coloured banner in the HTML report. `audit()` now RETURNS the status
  string (was bool); `main()` maps via STATUS_EXIT.
- **Process profiles (`dfam_profiles.py`).** Named threshold bundles
  with per-value provenance. Built-ins: `generic-fdm` (conservative
  default) + `generic-fdm-fine` (0.2mm). `--profile NAME`,
  `--profile-file JSON`, `--list-profiles`; flags override; `--no-lint`
  to silence surface/wall notes. JSON accepts *_mm/*_deg aliases. Sample
  in docs/profiles/example_bambu_petg.json. Default profile now activates
  min_wall+warn_angle lint by default (was opt-in) -> clean parts with a
  chamfer read PASS_WITH_LIMITS. audit_mesh() signature UNCHANGED so the
  9/5/4/4/4/3 baseline is untouched (profiles only affect the CLI path).
- 43 pytest cases. Not yet done from Terra's list: regression corpus (a
  data discipline), design-intent tags/sidecar (the anonymous-mesh-face
  UX problem), transition-explainer overlay in report (#9, good next),
  parametric-source repair (#6, hard - deferred), a diff mode (my add).

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

## Status 2026-07-21 (v0.18.0) — STAGE C: stalagmite-autofix (fix the design)

One level above Stage B: search the DESIGN's parameter space instead of
patching the mesh. `dfam_autofix.py`:
- autofix(build, PARAMS, NOMINAL, ...): evaluate nominal -> GP/LCB
  Bayesian search (numpy-only Matern 5/2, same family as dfam_orient)
  over the unit-normalised parameter box -> coordinate-wise HOMING pass
  (pull each knob individually back toward nominal, largest deviation
  first, full-restore try then bisection) -> rebuild the winner fresh
  and re-audit to PROVE it before returning.
- Objective: W_FAIL*fails + W_JUDGE*judges + W_TOL*tolerables +
  W_DIST*dist-from-nominal (10/0.5/0.05/1.0) — a fail always outweighs
  any distance, so printable dominates; among printable, closest wins.
- Candidate build exceptions become high-cost trials (COST_BUILD_ERROR),
  recorded with the error string — the GP learns to avoid the region.
  A nominal that doesn't build raises ValueError (broken design file).
- Verdicts: NOTHING_TO_DO / FOUND / NONE_FOUND. Never-worse: NONE_FOUND
  withholds output (exit 1) unless --force. Exit 0/1/2 contract kept.
- CLI `stalagmite-autofix design.py -o best.stl --budget 32 --json
  --report best.html`; design file = build(**params) + PARAMS dict
  (+ optional NOMINAL). load_design() validates.
- API: stalagmite.autofix(build, params, nominal, ...) -> AutofixResult
  (.verdict, .params_best, .moves, .distance, .mesh_best, .write,
  .to_dict with full trial history).
- examples/autofix_demo.py: trimesh-only shelf+gusset design with a
  TRAP: min shelf_len still fails; the search must discover the gusset.
  Demo run: FAIL (1 fail) -> PASS_WITH_LIMITS, moves listed, ~3s/24
  evals. Deterministic per seed (verified).
- test_autofix.py: 14 cases (verdicts, trap sprung, determinism,
  NONE_FOUND withholding, broken-nominal ValueError, candidate-crash
  survival, CLI human/JSON/error, API, written STL independently
  re-audits printable). Full suite: 117 passed.
- NOT wired into the GUI (a build function can't be uploaded safely);
  documented as the code-first tier of the doing story:
  report sculptor (human) -> stalagmite-fix (mesh) -> autofix (design).
- Remaining roadmap: design-intent tags (CadQuery named faces),
  regression corpus of real-world STLs, orient objective = containment
  audit, batch mode, GitHub release tag. GitHub still at v0.14, PyPI at
  0.7.0 — needs one catch-up push + upload.

## Status 2026-07-21 (v0.19.0) — DESIGN-INTENT TAGS (--keep)

Terra #4 / the Stage-D prerequisite. New dfam_intent.py:
- Keep-clear zones: cylinders, same zlo:zhi:rmax[:cx:cy] syntax as --ex
  but the OPPOSITE meaning (--ex = "ignore violations", --keep = "this
  is functional, no repair may touch it").
- parse_keep() (validating), geom_hits(), annotate_features()
  (feature["intent_hits"] = zone indices), body_blocked() (vertex-in-
  cylinder test, 0.05mm kiss-contact forgiveness), zone_from_bounds().
- Audit: stalagmite --keep flags defects on tagged surfaces
  ("[ON KEEP-CLEAR ZONE]" text tag; result_dict gains keep_zones +
  per-feature intent_hits — ADDITIVE keys, machine interface stable).
  Report: purple "on keep-clear zone" badge on the defect card.
- Repairs: make_repair_specs(keep=) skips anchor landings whose support
  contour touches a zone (walk-down passes functional material);
  emit_fix_stl(keep=) drops blocked bodies; dfam_fix.apply_fixes(keep=)
  drops blocked bodies WITH notes; all-blocked -> part untouched,
  NOT_IMPROVED (never-worse holds; verdicts stay honest — blocking the
  boss repair on fixture 01 gives PARTIAL with the cone still fixed).
- API: stalagmite.check(keep=), fix(keep=), keep_zone(obj, pad) on-ramp
  accepting CadQuery face selections (BoundingBox union), trimesh,
  (n,3) points, or bounds — intent lives next to the design.
- NOT in GUI (no manual zone entry exists there; documented CLI/API).
- test_intent.py: 14 cases (parsing, gating, blocking, walk-down skip
  proven deeper landing, all-blocked never-worse, CLI human/JSON/error,
  report badge, baseline VERIFIED without keep). Suite: 131 passed.
- Remaining: Stage D source patching (now unblocked by intent tags),
  regression corpus, orient-objective=containment, batch mode. GitHub
  still at v0.14, PyPI 0.7.0 — one catch-up push/upload covers 0.15-0.19.

## Status 2026-07-21 (v0.20.0) — LOGO + ORIENT CONTAINMENT VERIFY (Terra #8)

Brand: user's STALAGMITE lockup (tagline "The transition IS the design")
integrated:
- logo.png at repo root (user-supplied); README header image.
- dfam_logo.py: white-on-transparent 112px b64 PNG (black bg removed,
  luma-keyed alpha) so GUI + reports stay offline-self-contained;
  replaces the old hand-drawn SVG cone in both headers. Playwright-
  verified on the dark theme.

Orient: "the proxy proposes, the audit disposes."
- solve_orientation(verify_top=K): _top_distinct picks the K best
  poses >=20 deg apart (wrapped); verify_pose() runs the FULL
  containment audit per pose (pose_mesh drops to bed; transform_zones
  remaps part-frame exclusion cylinders when the pose keeps their axis
  vertical -- upright or flipped -- else drops them with an honest
  count); winner = (fewest fails, fewest judges, proxy score).
- Result gains chosen_by / audit / verified (per-pose evidence).
  verify_top=0 keeps the old proxy-only contract (API default 0;
  CLI --verify-top default 3).
- Demo caught the exact failure mode Terra predicted: on fixture 01 the
  proxy's favourite tilted pose (169 deg) audits at 14 fails; the
  verifier discarded it and kept upright (2 fails).
- test_orient_verify.py: 6 cases (zone remap upright/flip/tilt-drop,
  top-distinct separation, mushroom part: upright FAIL / flipped PASS,
  verified winner has 0 fails + cap prints low, verify-off contract).
  Suite: 137 passed.
- Remaining: Stage D source patching, regression corpus, batch mode.
  GitHub v0.14 / PyPI 0.7.0 -- catch-up push now covers 0.15-0.20.

## Status 2026-07-21 (v0.21.0) — INTENT ZONES IN THE GUI (protect toggles)

User asked "are the intent zones in the gui yet?" — now they are, with
zero coordinate entry:
- Report defect cards get a "protect" toggle (rendered only when the
  report is EMBEDDED in the GUI: window.parent !== window). Toggling
  derives a keep-clear zone from the defect's own payload (zlo/zhi
  +- max(1, 2dz) pad, radius+1, centroid) and postMessages
  {stalagmite:'keep', zones:[...]} to the parent.
- GUI viewer listens, shows "N defect(s) protected — Auto-fix will
  keep clear", appends keep=zlo:zhi:r:cx:cy params to POST /fix
  (validated server-side by parse_keep), resets on new audit/back.
- run_fix(keep=): apply_fixes(keep=), feats_after annotated so the
  FIXED report shows the purple badges; verdict banner appends
  "N repair(s) withheld (protected)" (counted from notes).
- Playwright end-to-end proven: audit 01 -> protect boss card ->
  Auto-fix -> "PARTIAL FAIL → FAIL · 1 resolved · 1 repair(s) withheld
  (protected)"; fixed report shows cone repaired, boss badged
  (screenshot delivered to user).
- 2 new tests (GUI run_fix keep + report ships protect machinery);
  suite 139 passed. Wheel 0.21.0 twine-checked.
- GitHub v0.14 / PyPI 0.7.0 — catch-up now spans 0.15-0.21.

## Status 2026-07-21 (v0.22.0) — ROOF CHAMFER PRIMITIVE (the bottle-cap case)

User field report: flat internal ceiling (bottle cap w/ spigot,
examples/flat_roof.stl) -- old repair lofted DOWN and plugged the whole
cavity, filling the spigot. User's insight: the real fix is the
"inverted green ghost, internally" = chamfer the roof into a gentle
cone. Notably the Tier-3 TEXT already said exactly that; the geometry
generator just couldn't build it. Now it can:
- dfam_repair._roof_opening(): detects ring-anchored ceilings -- the
  support slice below has an interior hole (the cavity opening) that
  contains the defect. Returns opening poly + largest roof through-hole
  (the bore; chamfer must stop at its edge) + count of other holes.
- Spec kind "roofcone": bot ring = opening contour buffered +0.3 into
  the wall (union bite), top ring = bore contour (or 0.6mm apex ring),
  min_h = max_gap/tan(angle)*1.05, requires fitting above the bed else
  falls back to the old loft path.
- roof_chamfer_solid(): watertight annular solid -- cone surface rings
  (easing exponent), outer wall face, top annulus. Cross-section is the
  classic chamfer triangle. build_body() dispatches by kind everywhere
  (fix, emit-fix, report).
- Report: buildRoofTris JS mirror; part goes X-RAY (mat transparent
  0.38) while a roofcone ghost is shown; caption explains + warns about
  covered holes; flare slider disabled (meaningless). GUI banner now
  says "N fail(s) cleared" (a fail that downgrades to tolerable is a
  PERSIST, so "0 resolved" read wrong).
- flat_roof.stl: FAIL -> VERIFIED/PASS_WITH_LIMITS, 0 fails; cavity
  hole 605mm2 intact at z=4; bore 33mm2 open through the spigot;
  funnel narrows between. Playwright-verified ghost + auto-fix.
- KNOWN NUANCE: with shell-concat unions, slice_region can resolve
  crossing shell contours as separate polygons (wall ring + chamfer
  ring) rather than one merged region -- physically fine (slicers
  union shells; re-audit still honest) but hole-area measurements must
  look at the smallest hole, not the largest (see test).
- test_roofcone.py: 6 cases (detection, cantilever NOT misread as roof,
  watertight annular body, cap end-to-end hollow+bore preserved,
  flat_roof example, report ships sculptor). Suite: 145 passed.
- GitHub v0.14 / PyPI 0.7.0 -- catch-up now spans 0.15-0.22.

## Status 2026-07-21 (v0.23.0) — THREAD-AWARE CHAMFERS + TRUE MULTI-BODY SLICING

User field report #2 on the same cap: the chamfer welded over the
internal THREADS (helix zone z 4.6-11.4; chamfer attached from z 8.5).
Plus: selection marker sphere too loud (opacity 0.35 -> 0.07,
depthWrite off).

Chamfer now respects functional wall geometry:
- make_repair_specs(avoid=..., ledge_max=...): exclusion zones join
  keep zones as hands-off for repairs (walk-down skip + roofcone wall
  clamp). Principle: you excluded that zone BECAUSE it's functional.
- roofcone clamps z_bot above overlapping zones (zhi+dz). If the full
  cone no longer fits: PARTIAL closure (per-vertex frac toward the
  bore) when predicted residual ledge <= allowance; else spec flagged
  over_allowance=True -- built and ghost-shown for the human sculptor
  (red badge "expect droop; raise/dome the roof") but STILL attempted
  by apply_fixes, where the RE-AUDIT is the judge (never-worse
  withholds if it doesn't prove out). h_avail<=2dz -> no spec at all
  and NO cavity-plug fallback (continue skips the loft path).
- z_close fix: closure must COMPLETE at the roof underside (zlo-dz/2),
  with a separate vertical weld band up to z_top biting into the roof.
  Before this, the last half-layer of closure arrived above the roof's
  first slice and partial chamfers audited worse than predicted.
  Spec gains z_close; py + JS builders mirror it.

TRUE MULTI-BODY SLICING (the deep fix this forced):
- slice_region was even-odd by containment on ALL loops: correct for
  one manifold shell, XOR-wrong for concatenated/overlapping shells
  (crossing loops got differenced; a solid repair body nested inside a
  roof outline got counted as a hole).
- _mesh_bodies(mesh): split into components, memoized (_sm_bodies).
  WATERTIGHT bodies slice independently via _section_region (even-odd
  provably right per closed shell) and union. OPEN shells stay GROUPED
  and resolve together by global even-odd (an open tube can BE another
  component's hole wall -- trimesh annulus splits into such tubes).
  Single-body meshes take the old path unchanged (fixture baseline
  9/5/4/4/4/3 intact, all 64 fixture tests green).
- aggregate(): bridge roofed width is now HOLE-AWARE -- annular roofs
  (ring around an open bore) measure 2x max inscribed radius
  (shapely polylabel) instead of the MRR minor axis, which measured
  the ring's OUTER DIAMETER and overstated spans wildly.

Outcomes on the cap family (all re-audit-proven):
- no threads: VERIFIED, FAIL -> PASS (z_close made it fully clean)
- threads to z=11.0: VERIFIED, FAIL -> PASS_WITH_LIMITS, partial
  chamfer above threads, threads untouched
- flat_roof.stl (threads to 11.4): NOT_IMPROVED, exit 1, honest
  "raise/dome the roof or shorten the threads" + flagged sculptor
  ghost sitting visibly above the threads (Playwright-verified).
Suite: 147 passed. GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.23.

## Status 2026-07-21 (v0.24.0) — OPTIONAL QUALITY REPAIRS (user request)

"i think even tolerable zones should be editable by the user also" --
now every severity is sculptable, with the fail/optional line kept
crisp:
- make_repair_specs(severities=("fail",)): new param. Default = fail
  only (unchanged for apply_fixes / --emit-fix -- automation never
  welds cosmetic repairs). render_report passes all three severities.
- Non-fail specs carry optional=True + severity; the fixpanel header
  turns GOLD "Optional quality repair (adjustable)" with the honest
  caption "this defect already prints within allowance - sculpt this
  only if you want a cleaner underside; Auto-fix never applies it."
  Same sliders, physics badge, and repair-STL download.
- Works with every primitive (loft / pillar / roofcone) -- flat_roof's
  tolerable sibling gets an optional roofcone ghost; fixture 06's
  judged bridge gets an optional loft. Playwright-verified.
- 3 new tests incl. "second fix pass on a tolerable-only part is
  NOTHING_TO_FIX with zero bodies". Suite: 150 passed.
- GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.24.

## Status 2026-07-21 (v0.25.0) — VENT SHAFTS (user field report #3)

"the fix blocks off the vent hole" -- the note that apologized
("may cover 1 small roof hole -- re-drill if functional") is replaced
by geometry that doesn't need to apologize:
- _roof_opening returns the actual vent polygons (all secondary roof
  through-holes inside the opening); spec gains drill=[24-pt rings,
  +0.15mm clearance] replacing holes_covered.
- _drill_vents(): per vent, extrude_polygon prism z_bot-1..z_top+1,
  trimesh.boolean.difference. Result metadata vents/vents_drilled;
  apply_fixes notes "N vent shaft(s) drilled" or the honest fallback
  "could NOT be drilled (boolean engine unavailable?) -- re-drill
  manually" (monkeypatch-tested).
- manifold3d PROMOTED TO DEPENDENCY (Windows wheels exist) -- also
  upgrades union_bodies to true booleans wherever inputs are volumes.
- Report caption: "N vent shaft(s) are drilled through the applied
  body... browser-downloaded ghost STL does not include the shafts"
  (the JS loft cannot CSG; the applied body is the source of truth).
- cap_vent test: VERIFIED FAIL -> PASS, vent column PROVEN open through
  chamfer AND roof (slice contains-point checks), bore open. flat_roof
  spec carries 1 drill ring (its vent) for the sculptor/force path.
  Suite: 152 passed.
- GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.25.

## Status 2026-07-22 (v0.26.0) — REGION-SCOPED CHAMFERS (user report #4)

"trying to adjust the tolerable parameters, its still only changing
the failed part" -- the tolerable card's optional ghost was a clone of
the fail's full funnel, because the roofcone always closed to the
roof's BORE regardless of which defect was selected.
- _roof_opening now returns a closure TARGET: the selected defect's
  own largest inner boundary when it has one (region-scoped), falling
  back to the roof's largest through-hole. On flat_roof: fail -> bore-
  deep partial funnel as before (min_h 7.8, over_allowance, 1 vent
  shaft); tolerable -> its own 2.3mm corner chamfer (min_h 2.26,
  z_bot 17.3, no over flag, no drills) -- visibly different sliders.
- drill list recomputed against the target: only through-holes the
  chamfer actually covers get vent shafts; holes inside the target
  opening stay open by construction.
- Regression test: tolerable spec min_h < half the fail's, no drill,
  higher z_bot. Suite: 153 passed.
- GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.26.

## Status 2026-07-22 (v0.27.0) — THE RING-CENTROID TRAP (user report #5)

"it should be selecting the yellow tolerable region" -- flat_roof's
tolerable is the OUTER RIM of the lid overhanging the outside of the
wall. _roof_opening matched it to the INTERNAL cavity because it
tested hp.contains(centroid): an annular region's centroid sits at its
centre = inside the cavity, even though the ring itself lies entirely
OUTSIDE the wall. Result: a bogus "internal chamfer" band passing
through the wall (measured ghost r 14.2-16.4).
- Fix: containment by AREA OVERLAP, not centroid --
  g.intersection(hp).area / g.area >= 0.6. Ring-shaped outer overhangs
  now fall through to the generic loft path, which produces exactly
  the right repair: an EXTERNAL skirt collar lofting the rim contour
  (r 18.1) down onto the outer wall (r 15), min_h 2.2 -- the classic
  v2->v7-style skirt, sitting visibly under the yellow ring
  (Playwright-verified, ghost extent measured from window._ghostTris).
- Regression test rewritten: fail = roofcone, tolerable = loft with
  top-ring radius > wall outer; scoped (min_h < half the fail's).
  Suite: 153 passed.
- LESSON (recorded for classifier work): ring/annular regions break
  centroid-based spatial tests; always use area fractions.
- GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.27.

## Status 2026-07-22 (v0.28.0) — FLARE SEMANTICS (user report #6)

"flare (base spread) should only flare FROM the base... it flares the
bottom side too creating an unwanted step" -- exactly right. Flare
scaled the loft's BOTTOM ring off its landing contour: for a skirt
landing on a wall, the base floated in air beyond the support with a
step under it, while the analytic badge claimed "worst slope 3deg"
(it only measured endpoint travel, blind to where the base landed).
- loft kind: base ring PINNED to the landing contour; flare grows
  upward from the base (per-ring scale 1+(flare-1)*s), bellying the
  body out toward the ring above -- py loft_solid + JS buildLoftTris
  in lockstep. pillar kind keeps classic whole-foot spread (a wider
  anchor ON THE BED is legitimate); maxGap ignores flare for lofts.
- Badge rewritten: worstSlopeDeg() measured on the ACTUAL generated
  rings (window._ghostRings) -- easing AND flare belly included, all
  ghost kinds. At the user's exact repro (H5.7/ease2.5/flare1.35) it
  now honestly reads red "exceeds 45deg -- lower flare, reduce
  easing, or raise height" instead of green 3deg over a floating step.
- Playwright-measured: base ring radius identical at flare 1.0 and
  1.35 (pinned); mid ring bellies 17.0->18.4.
- Tests: loft pins base + bellies mid; pillar still spreads foot.
  Suite: 155 passed.
- GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.28.

## Status 2026-07-22 (v0.29.0) — CONCAVE TRANSITIONS (user report #7)

"the transition is convex when it should be concave" -- geometric
truth surfaced: with a loft's base pinned to its landing and its top
pinned to the defect, ANY profile fuller than the straight chamfer
must bulge convex somewhere (the belly has to decelerate back to the
pinned top). The concave family (straight chamfer -> cove/fillet) is
exactly what Easing controls at flare=1.
- Flare is now PILLAR-ONLY (foot spread on the build plate -- the one
  place widening a base is physically legitimate). Lofts ignore it in
  py loft_solid AND JS buildLoftTris; slider disabled for loft/roofcone
  ghosts; label renamed "Flare (pillar foot spread)"; maxGap already
  pillar-scoped from v0.28.
- Verified in-browser: slider disabled on the rim skirt; profile
  measured on window._ghostRings has ZERO convex dips (outward step
  rate non-decreasing going up = purely concave cove) at ease 2.5;
  badge 44 deg.
- Tests updated: loft_solid(flare=1.35) is bit-identical to flare=1.0;
  pillar still spreads. Suite: 155 passed.
- GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.29.

## Status 2026-07-22 (v0.29.1) — flare row hides instead of greying

"the pillar footspread is greyed out?" -- it was disabled by design
(v0.29: flare is pillar-only), but a dead greyed slider reads as a
bug. The Flare row (#flarerow) now HIDES entirely unless the selected
spec is a bed pillar; loft/roofcone panels show just Height + Easing.
Playwright-verified hidden on both skirt and roofcone. 155 tests.

## Status 2026-07-22 (v0.30.0) — MULTI-BODY REPAIR EXPORT (user report #8)

"if i change both a tolerable and a fail region, download only gives
the fail" -- true: the button exported only window._ghostTris (the
ghost on screen) and card-switching discarded slider settings.
- SCULPT map: per-defect {H, ease, flare} saved on slider input,
  restored on card re-select (settings survive switching).
- Download repair STL = exportSet(): ALL fail repairs (user settings
  or defaults) + every OPTIONAL repair the user actually sculpted
  (viewing alone does not opt it in). Button label shows the count:
  "Download repair STL (N bodies)". Bodies are concatenated
  union-ready, same convention as --emit-fix.
- E2E proven: sculpt tolerable -> label "(2 bodies)"; switch cards,
  settings restored; downloaded STL = 13056 tris vs 6336 single.
- Suite: 156 passed.
- GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.30.

## Status 2026-07-22 (v0.31.0) — SCULPT-DRIVEN FIXING + THE FAN-CAP PLUG BUG

"i guess the next step is saving fully compiled fixed stls?" -- yes:
the sculptor now drives the REAL fix.
- apply_fixes(sculpt=[entries]): each report entry {cls, zlo, zhi, cx,
  cy, optional, height?, easing?, flare?} is matched to a before-audit
  feature (class + z + centroid, 5mm gate); its settings drive that
  body; matched OPTIONAL repairs join the fix. Unmatched entries noted.
- Report pushes sculpt state to the GUI (postMessage 'sculpt' on every
  change); the Auto-fix button becomes "Apply sculpt & re-audit" when
  custom settings/opt-ins exist; /fix carries sculpt= JSON; run_fix
  passes through. Result: full part unioned (manifold when inputs are
  volumes), vent-drilled, RE-AUDITED -- the downloaded fixed STL is
  the compiled, proven part.
- CRITICAL BUG FOUND EN ROUTE (fake VERIFIED): the rim skirt was
  generated by the generic LOFT path whose fan-caps close the contour
  interior -- between two full circles (wall/rim outlines) the "loft"
  is a SOLID PLUG, and manifold union FILLED the cavity from z16.5-20,
  "supporting" the thread-blocked crescent. Fix: ring landings
  (support component with interior holes) now emit kind="skirt" --
  the roof-chamfer topology mirrored outward (sloped face + wall
  column + top annulus, z_close=z_top), bot ring = support exterior
  buffered -0.3 into the wall. build_body + JS route skirt through
  the annular builder. flat_roof sculpt case now honestly
  NOT_IMPROVED with the cavity intact (605mm2 at z5).
- E2E: sculpt height on the cap -> button flips -> Apply -> VERIFIED
  FAIL -> PASS_WITH_LIMITS. Tests: sculpted height reaches deeper than
  default (probed), optional opt-in adds annular skirt + stays honest,
  unmatched entry noted. Suite: 159 passed.
- GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.31.

## Status 2026-07-22 (v0.32.0) — SCULPT UX ROUND-OUT (user reports #11-13)

Three GUI truths from live use:
1. "should it not then load the reaudited part?" -- run_fix now ALWAYS
   returns fixed_report for VERIFIED/PARTIAL/NOT_IMPROVED; the viewer
   swaps to the re-audited outcome even when the fix was refused
   (never-worse withholds the STL, not the evidence). Banner appends
   "output withheld (never-worse) -- showing the re-audited attempt".
2. "you need a way to download it" -- NOT_IMPROVED ships the attempt
   STL too, honestly named <stem>_attempt_FAILS.stl, behind an
   orange "Download attempt STL (still fails)" button -- the GUI
   equivalent of the CLI's --force. Styling/text reset on New audit.
3. "the change to the tolerable section disappears" -- persistent
   ghosts: refreshAllGhosts() renders EVERY export-set repair as a dim
   (0.16) ghost while the selected one stays bright/editable; rebuilt
   on every sculpt change/selection via updateDlLabel.
E2E on flat_roof: sculpt tolerable -> select fail (dim skirt persists,
"2 bodies") -> Apply sculpt -> NOT_IMPROVED banner + attempt report
loaded + forced download visible. Suite: 161 passed.
GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.32.

## Status 2026-07-22 (v0.32.1) — CONCENTRIC-TWIN SCULPT MATCHING (user report #14)

"the downloaded stl retained the FAIL modification, but not the
tolerable" -- flat_roof's fail and tolerable are CONCENTRIC same-class
rings (both steep-growth, both z 19.8, ring centroids at the part
centre). The sculpt matcher (class + z + centroid) mapped BOTH GUI
entries (coords rounded to 0.1) onto the fail feature; the tolerable's
opt-in was silently swallowed, so the skirt never built. Tests missed
it because exact centroids broke the tie by luck.
- _match_entry: severity gate ((severity != fail) must equal
  entry.optional) + report feature id fast-path (payload now carries
  id); fuzzy fallback keeps the gate.
- Regression test with GUI-rounded coords: kinds [roofcone, skirt],
  2 bodies. run_fix end-to-end: skirt present in the attempt report.
  Suite: 162 passed.
GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.32.1.

## Status 2026-07-22 (v0.32.2) — CLOSURE TARGET MUST COVER THE DEFECT (report #15)

"its not modifying the failed region, its modifying a ring around it"
-- on a re-audited attempt, the residual fail (the applied cone's own
too-steep surface, sculpted at max easing under the over-allowance
badge override) is a STACK of thin rings merged z17-19.8. The v0.26
own-hole target picker chose the topmost ring's 404mm2 artifact hole:
closure "repaired" a 4.5mm2 sliver with 98% of the defect INSIDE the
target (ghost = useless outer ring, Height 0.9).
- Rule: a closure target is only valid if the defect does not lie
  inside it. Candidate holes (defect's own + roof through-holes) are
  walked largest-first; first with defect-intersection <= max(1mm2,
  2% of defect) wins -> here the BORE (33.2mm2, 0.0 inside).
- Regression test reproduces the sculpted-attempt flow and pins:
  target = bore, defect-inside-target ~ 0. Suite: 163 passed.
- Known UX niggle (not fixed): over_allowance badge override hides the
  live slope readout, so max-easing sculpts can exceed 45 deg unseen
  until re-audit catches them (it does -- that's how this fail was
  born). Candidate improvement: show both messages.
GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.32.2.

## Status 2026-07-22 (v0.33.0) — WALL VALIDATION + THREAD-BAND CLAMP (report #16)

"still doesnt look like its modifying from the correct region" -- two
compounding causes on the re-audited attempt part:
1. THREAD CLAMP MISFIRE: the zone test was "landing wall anywhere
   inside rmax" -- the applied cone's funnel wall (r~10.5) is radially
   inside the thread cylinder (rmax 13.9) though the threads live AT
   the boundary (r~13-14). Cost 6.8mm of closure for nothing. Fix:
   avoid (helix) zones clamp only when the wall sits in the BOUNDARY
   BAND (rmax-2.5 <= d <= rmax+0.5); keep zones stay volume-semantics.
2. SLOPED LANDING: roofcone assumed the opening wall is vertical
   below; on the attempt the "wall" is the first cone's funnel, which
   recedes -- the chamfer's base column would hang in air. Fix: walk
   down and require the bite ring (every 8th vertex, >=90%) to stay
   inside material; first miss sets z_wall_min (geometric clamp).
Result for the attempt part: no misleading ghost -- the fail card says
"no usable wall below the ceiling (... sloped/receding landing ...)
fix the ORIGINAL part or redesign; patching a patch rarely ends well."
Original flat_roof / cap behaviours unchanged (thread test zone in
tests moved onto the wall, rmax 16->14, per band semantics).
Suite: 164 passed. FUTURE PRIMITIVE noted: sloped-landing gusset
(cone-on-cone) would make attempt parts repairable.
GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.33.

## Status 2026-07-22 (v0.34.0) — BATCH GATE + CORPUS NET + BADGE FIX

Housekeeping release; no engine changes.
- BADGE: the over_allowance override no longer HIDES the live slope
  readout -- it appends it (green "cone surface OK -- worst slope N
  deg" / red "cone surface EXCEEDS ... reduce easing"). This was the
  v0.32.2 known niggle: the origin of the user's over-eased sculpt.
- NEW: stalagmite-batch <folder> [--profile --auto-ex --json --csv]
  (dfam_batch.py). One audit line per STL/OBJ/PLY/3MF, summary counts,
  exit = worst per-file code (0/1/2). "Before I ship the catalogue."
- NEW: test_corpus.py -- corpus regression net pinning check() on all
  six fixtures RAW (no zones) + flat_roof --auto-ex to exact recorded
  (status, fails, judge, tolerable, exit); plus zoned 06 -> REVIEW/0.
  Complements test_fixtures.py (zone-level baseline). Any engine drift
  anywhere in the corpus now fails here first.
- SLOPED-LANDING GUSSET (roadmap item from v0.33) INVESTIGATED and
  parked: for THIS attempt part geometry proves it futile -- a 45 deg
  closure from the funnel wall (r~10.5) would apex at z~23.9, above
  the z19.8 roof. The honest block stands. Primitive remains valid for
  shallower funnels; keep on roadmap.
Suite: 175 passed (12 new: 8 corpus, 3 batch, 1 badge).
GitHub v0.14 / PyPI 0.7.0 -- catch-up 0.15-0.34.

## Status 2026-07-22 (v0.35.0) — STAGE D: SOURCE PATCHING

The fix moves upstream: stalagmite-patch emits each repair as a
parametric snippet (OpenSCAD or CadQuery) to paste into the ORIGINAL
design, so re-exports stop reintroducing the defect (dfam_patch.py).
- Snippets are honest CIRCLE FITS of the audited slice contours:
  every fix header declares fitted radius + max deviation; visibly
  non-circular contours (rect ledges, crescents) get a WARNING
  comment. roofcone -> difference(cylinder, cone void, bore, vents);
  skirt -> cone minus inner column (tube stays hollow, 0.3 bite);
  loft/pillar -> hull()/loft() between fitted circles.
- PARAMETRIC PREVIEW: before writing, the snippet geometry is rebuilt
  as a mesh (same builders as Stage B), unioned, RE-AUDITED, and the
  verdict printed + wired into the exit code (0 only when VERIFIED
  and nothing blocked). --no-verify skips.
- Blocked repairs (thread clamp, no usable wall) are emitted as
  comments quoting the audit refusal, never as geometry. flat_roof:
  partial cone + blocked note + NOT_IMPROVED, exit 1 -- consistent
  with Stage B's honest verdict.
- GOLD-STANDARD TEST: emitted .scad rendered by the REAL openscad
  binary, unioned, re-audited -> cap FAIL becomes PASS, VERIFIED
  (test skips gracefully where openscad is absent).
Suite: 184 passed (9 new in test_patch.py). New console script
stalagmite-patch; module dfam_patch registered.
GitHub/PyPI: user pushed the 0.15-0.34 catch-up TODAY (both live at
0.34.0). Next release ritual is routine again: commit/push, build,
twine upload 0.35.0.

## Status 2026-07-22 (v0.36.0) — GUI BATCH TAB + CLICKABLE STAGE D

Both GUI conveniences the user asked for ("continue with both"):
- BATCH TAB (4th tab): drop/select MULTIPLE parts -> each audited in
  turn via new /batchrow route (run_batch_row: bytes -> status/fails/
  judge/tolerable/exit/seconds). Live table with status badges, rolling
  summary counts, per-row "report" button that opens the FULL viewer
  for that part (openReport() refactor -- viewer context vProf/vAx now
  travels with whichever file opened it, so Auto-fix / sculpt / Patch
  all work from a batch row too).
- PATCH SOURCE BUTTON (viewer bar): language select (OpenSCAD /
  CadQuery) + "Patch source" -> new /patch route (run_patch) runs the
  full Stage D pipeline server-side incl. the parametric preview
  re-audit; browser downloads <part>_patch.scad/.py and the verdict
  line shows "N fix(es), M blocked · preview VERIFIED (PASS) · paste
  into your ORIGINAL design". Keep-clear (protect) zones pass through.
  NOTHING_TO_PATCH and unknown-language paths handled.
Playwright E2E (cloud, chromium): batch of 2 parts -> 2 badges +
summary; row report -> viewer; Patch source -> real .scad download
containing stalagmite_fix_1, verdict VERIFIED (PASS); lang switch ->
.py download. Suite: 188 passed (4 new: 2 batchrow/landing in
test_batch, 2 run_patch/landing in test_patch).
GitHub/PyPI at 0.34.0 -- user should push+upload 0.35.0/0.36.0
(routine: commit/push, delete dist, build, twine upload).
