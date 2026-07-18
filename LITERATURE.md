# Literature notes — DfAM reference library (studied 2026-07-18)

Two batches: nine PDFs (~990pp) studied first, then eight more (~135pp) —
see "Second batch" below. Notes organised by what each source contributes
to this toolkit. Full citations at the end of each batch section.

## The library at a glance

| source | what it is | chief value here |
|---|---|---|
| Gibson/Rosen/Stucker 2010 | canonical AM textbook (472pp, Springer) | process physics; support-generation algorithm; orientation objectives |
| Mandolini et al. 2022 | MDPI *Applied Sciences* special-issue reprint, 17 papers (354pp) | Langelaar AM filter = our rule in voxel form; restrictive-DfAM vocabulary |
| Booth et al. 2017 (JMD 139:100904) | Purdue one-page DfAM worksheet, validated | our mission statement in their future-work; 81% stat; audience match |
| Hinchy (book chapter, ~2019) | DfAM tutorial chapter (26pp) | cleanest citable FDM numbers: 45°, 10mm bridge, 0.8mm wall |
| Obilanade et al. 2025 (*Design Science* 11:e50) | 20-expert aerospace DfAM interview study (65pp) | evidence the prescriptive-feedback gap persists even industrially |
| Pourroy & Boujut 2016 (G-SCOP/OIPEC deck, 51 slides) | metal-AM teaching deck | Adam & Zimmer-style rule tables incl. the only FDM-tagged number: overhang ledge ≤ 1.8mm |
| Saunders/Renishaw 2017 ×3 | blog-series feature articles (LPBF) | 45°/30° two-band severity; teardrop/diamond holes; <10mm lateral holes self-support; TO-isn't-printable argument |

## What the literature says about our core rule

- **Physics grounding** (Gibson §6, pp.151–152): Yardimci's bonding model —
  a road bonds only where it contacts material still above a critical
  temperature (bonding potential φ = ∫(T−T_c)dt). The dilation rule is a
  geometric proxy for "every road has a warm neighbour below."
- **Independent convergence** (Fu et al., in Mandolini 2022, p.173–175):
  Langelaar's AM filter used in topology optimisation is *exactly* our rule
  discretised on voxels — an element may exist only if supported by the five
  elements below (itself + 4-neighbourhood). Generalised to arbitrary angles
  via weight ws = 1/tan(α). The TO community converged on our formulation.
- **The 45° number**: Gibson never codifies it (threshold is machine-
  defined, p.350, 356); Hinchy §3.5.6 and Saunders state it explicitly for
  FFF/LPBF; Fu et al. use it as the standard default. Conclusion: keep
  `--angle` configurable, 45° as community default — cite Gibson for the
  *algorithm*, Hinchy/Saunders for the *constant*.
- **Known blind spot, named in the literature** (Fu p.183): "overhang angle
  and length constraints interact" — angle-only checking misses bridge
  length limits. Our Tier-2 bridge classifier addresses exactly this.

## Numbers worth encoding (with provenance)

FDM/FFF (directly applicable):
- 45° self-support threshold; beyond it supports needed (Hinchy §3.5.6)
- Bridges ≤ ~10 mm printable unsupported, rough downskin (Hinchy §3.5.6)
- Unsupported overhang *ledge* length ≤ 1.8 mm before filaments "fall off"
  (Adam & Zimmer-style table, OIPEC slide 10 — the per-slice horizontal
  jump bound; complements the angle rule)
- Min wall/feature 0.8 mm; robust walls ≥ 2× nozzle diameter (Hinchy;
  Gibson p.146); corner radius ≈ nozzle radius (Gibson p.161)
- Holes < 2 mm: undersize and drill (Hinchy); FFF accuracy ±0.5 mm
- Z is the weak direction — align major stress axes with XY (Gibson p.161)

Metal-LPBF heritage (cite as analogy, not FDM gospel):
- 30° "preferable" vs 45° "avoid beyond" → a two-band warn/fail severity
  model, matching Saunders' green/yellow/red layer taxonomy
- Lateral holes < 10 mm self-support in LPBF (Saunders); channels > 7 mm
  need teardrop/diamond sections (Rolinck, in Mandolini 2022, p.62)
- LM overhang ledge ≤ 2.0 mm; Y-junction area-monotonicity rule (cross-
  section going up should stay same or shrink) — OIPEC slides 9–10

## Validation of the toolkit's thesis, tier by tier

- **The gap is real and documented at both ends.** Bottom: Booth's paper
  worksheet alone cut poorly-designed parts 81%, and its future-work
  section *specifies this tool*: "computer-based recommender systems
  embedded in CAD... including wall thickness, the degree to which features
  are unsupported" (p.100904-8). Top: Obilanade 2025 reports (via Wiberg
  2019) that "no commercially available CAE software allows users to input
  an initial part design and automatically generate a version suitable for
  an AM process," and practitioners complain tools "identify problem areas,
  but not the magnitude" — nor the fix.
- **Tier 2 classifier**: every class is attested — islands ("low island
  positions", Adam & Zimmer via Booth), bridges (Hinchy 10mm / DMLS 2mm),
  steep-growth (45° rule everywhere; ledge-length bound), starts-in-air
  (Booth's "long unsupported features" / droop mechanism). Severity bands
  (OK / poor-surface / will-fail) come free from Saunders' traffic-light.
- **Tier 3 repair suggester**: "morph, don't scaffold" is published
  industrial practice — Rolinck: "most of the necessary support structures
  shall be replaced by design elements... identified by build-preparation
  software and then replaced by geometric elements in the design software
  iteratively" (Mandolini 2022, p.62), with a first-time-right manifold as
  proof. Saunders ships diamond holes, merges an offending strut into
  webbing, tapers a base to the plate. New repair archetypes to add to
  hull/gusset/teardrop/morph/reorient: **flatten-apex** (blunt vertical
  extreme points, OIPEC), **integrated scaffold** (retained support that
  ties features together, Saunders manifold), **diamond** as teardrop
  alternative.
- **Tier 4 orientation solver**: Gibson enumerates our objective set
  (accuracy, height/time, support volume, critical-faces-up, Z-weakness);
  Saunders documents the non-locality that makes it a global optimisation
  ("eliminating supports in one area through re-orientation can lead to
  supports being needed elsewhere") and the endgame (align all functional
  features one direction → fully self-supporting part). "Cosmetic/
  functional surface" and "design for surface finish" are the terms of art.
- **Anisotropy nuance** for repair advice (Zouaoui/Allum, Mandolini 2022,
  p.240): PLA layer *interfaces* are near-bulk-strength; anisotropy comes
  from weld-line geometry/stress concentration — relevant when arguing a
  morphed junction beats a supported one.
- **Cost of self-support is small** (Fu): enforcing the rule in TO cost
  1.25–2.91% compliance — quantitative support for "the transition IS the
  shape" being nearly free.

## Positioning (for README / any writeup)

- Vocabulary: this toolkit is **restrictive DfAM** ("design for
  printability") automation; Tier 3–4 push toward **dual DfAM**
  (Laverne/Gibson taxonomy, standard in the field).
- The niche in the literature's own terms: Booth bounds the gap from below
  (paper checklists work but stop at risk scores), Obilanade from above
  (Magics-class tools are expert-operated, costly, and still not
  prescriptive). Moreno Nieto's software survey (Mandolini 2022, Table 1)
  shows the free tier = modelling + mesh repair + slicing; no geometry-
  level printability enforcement for the FreeCAD/OpenSCAD demographic.
  Kukko et al. (open-source FreeCAD clip system) prove that demographic
  exists and publishes.
- Booth's classroom null result is a design lesson: feedback only changes
  behaviour when failure has cost and feedback arrives before design
  lock-in → keep the tool early-loop, fast, and make repairs cheap to apply.
- Nothing in these ~990 pages provides an FDM-specific, validated
  slice-level violation taxonomy. Tier 2 is genuinely novel territory.

## Full citations

- I. Gibson, D.W. Rosen, B. Stucker, *Additive Manufacturing Technologies*,
  Springer, 2010. DOI 10.1007/978-1-4419-1120-9.
- M. Mandolini, P. Pradel, P. Cicconi (eds.), *Design for Additive
  Manufacturing: Methods and Tools*, MDPI Books, 2022. ISBN
  978-3-0365-4926-2. (Esp. Fu et al. p.171; Rolinck et al. p.59; Moreno
  Nieto & Moreno Sánchez p.227; Kukko et al. p.293; Zouaoui et al. p.239.)
- J.W. Booth, J. Alperovich, P. Chawla, J. Ma, T.N. Reid, K. Ramani, "The
  Design for Additive Manufacturing Worksheet," *J. Mech. Des.* 139(10):
  100904, 2017. DOI 10.1115/1.4037251.
- E.P. Hinchy, "Design for Additive Manufacturing," book chapter (ca. 2019),
  Confirm Centre, Univ. of Limerick. (Many numbers secondhand from Redwood,
  Schöffer & Garret, *The 3D Printing Handbook*, 3D Hubs, 2017 — cite both.)
- D. Obilanade, P. Törlind, A. Öhrwall Rönnbäck, "Supporting design for
  additive manufacturing: insights from product development practices in
  the aerospace industry," *Design Science* 11:e50, 2025.
  DOI 10.1017/dsj.2025.10042.
- F. Pourroy, J-F. Boujut, "Design for Additive Manufacturing — Uncover New
  Design Rules," G-SCOP / OIPEC workshop deck, Moscow–Vladimir, Nov 2016.
  (Rule tables in the style of Kranz et al. and Adam & Zimmer.)
- M. Saunders, Renishaw plc feature articles, 2017: "DfAM essentials";
  "DfAM strategy — create 'design space' for maximum AM impact"; "Is
  topological optimisation really optimal?"
- Primary sources worth chasing: G.A.O. Adam, D. Zimmer, "Design for
  Additive Manufacturing—Element transitions and aggregated structures,"
  *CIRP J. Manuf. Sci. Technol.* 7(1):20–28, 2014 (the canonical FDM/LS/LM
  geometry-rule catalogue — NOW STUDIED, see second batch); M. Langelaar,
  "An additive manufacturing filter for topology optimization of
  print-ready designs" (the voxel form of our rule); Wiberg, Persson &
  Ölvander 2019 (the CAE-gap review).

---

# Second batch (8 PDFs, ~135pp, studied 2026-07-18)

| source | what it is | chief value here |
|---|---|---|
| Adam & Zimmer 2014 (CIRP JMST 7:20–28) | THE canonical geometry-rule catalogue (DMDR project, Paderborn) | hard FDM numbers with experimental provenance; the attribute-rule schema |
| Lieneke et al. 2016 (Procedia CIRP 43) | FDM dimensional tolerances (same lab, successor project) | ±0.5mm deviation envelope; z-quantisation finding; IT09–IT14 |
| Bernard/Thompson et al. 2019 (Springer ch.12) | education digest of the CIRP keynote | canonises Adam & Zimmer; commercial design-guide inventory |
| Thompson/Campbell et al. 2016 (CIRP Annals 65:737–760) | THE major DfAM survey keynote ("Campbell draft" = author version) | per-state physics rationale; Leary cantilever numbers; reorient/support/redesign triad |
| Pradel et al. 2018 (J. Eng. Design 29:291–326) | systematic mapping of 81 DfAM studies | heuristics→rules knowledge taxonomy; 45° rule canonical status; machine-vs-process validity caveat |
| Tüzün et al. 2021 (ICED21) | 17 AM-conformity criteria + interdependency matrix | the name "AM-conformity"; criterion 8 = functional-surface orientation |
| Goguelin, Dhokia & Flynn 2021 (IJCIM 34:1263–1284) | Bayesian optimisation of build orientation | the Tier-4 method recipe and benchmark protocol; the gap we fill |
| Ellsel & Stark 2024 (DESIGN 2024, PDS) | knowledge-driven NX-integrated DfAM check tool | closest living relative of Tier 2/3; validates and differentiates |

## Adam & Zimmer 2014 — the rule catalogue (FDM extracts)

Boundary conditions for all numbers: Stratasys Fortus 400mc, Ultem, 0.25mm
layers, tip T16 — the paper insists values only hold for these; make every
threshold parameterisable.

- **Overhang ledge: FDM l_Oh ≤ 1.8 mm** — flat unsupported cantilever
  ledge; OK 0.2–1.8mm, *destroyed* at 2.0mm (Table 5). A remarkably sharp
  cliff. In slice terms: material outside the dilation is not fatal if the
  perpendicular ledge depth ≤ ~1.8mm. This is a *cantilever* (one-sided)
  number — bridges (two-sided) were not tested; keep a separate longer
  bridge threshold (Hinchy's ~10mm).
- **Gap height: FDM h_G ≥ 0.4 mm** minimum vertical clearance between
  non-bonded bodies (smaller gaps seal via agglutinated filaments) —
  directly relevant to thread clearances; gap length/width free for FDM.
- **Islands** (their Sec 3.3 definition is our Tier-2 island class
  verbatim): for FDM, higher island start positions cost build time (tip
  switches every support layer) — a *cost* severity axis on top of
  printability, and a prescriptive direction (lower the start = our
  hull-down repair).
- **Edges**: sharp edges unprintable below melt/filament size; edges at
  vertical extreme points → blunt parallel to build plane (= flatten-apex,
  with sizing rule: blunt area > wall thickness); horizontal extreme
  points → blunt orthogonal (= the teardrop/diamond family); rounding
  radii correlate with outer radii of curved elements.
- **Warning for Tier 3**: their R7 (keep FDM inner edges sharp to avoid
  support-needing surfaces) shows fillet-type repairs can CREATE new
  overhangs — every suggested repair must be re-validated against the
  Tier-1 dilation check.
- Their schema (element + attribute + suitable range + per-process
  applicability + boundary conditions) is a ready-made design for our rule
  database.

## Other hard numbers (second batch)

- Lieneke 2016 (ABS-M30, 0.178mm layers): deviations x +0.03→+0.50mm
  (grows with size), y +0.06→−0.30mm, z alternates +0.12/+0.47mm;
  **dimensions that are integer multiples of layer height print markedly
  more accurately** → cheap suggestion: snap critical z-heights to n·dz.
  FDM lands in IT09–IT14. Clearances should scale with nominal size (a
  0.4mm Adam gap can be eaten by a +0.5mm deviation).
- Wall ≥ 2× layer thickness (RedEye/Stratasys via Pradel 2018).
- Round holes self-support to ~8mm in metal AM (Diegel via Ellsel & Stark);
  their KB returned 60° critical angle for EOS M400-4/TiAl6V4 — more
  evidence thresholds are machine-specific.
- 70% of Adam & Zimmer's 55 design rules are directly or indirectly
  affected by build orientation (Leutenecker-Twelsiek via Goguelin) —
  orientation is the master variable; supports removal = 40–70% of metal
  part cost.

## Tier-4 prior art: Goguelin et al. 2021 (Bayesian orientation)

Method to borrow wholesale: pose = (θx, θy) integer degrees + drop-to-
plate; GP surrogate (Matérn kernel), UCB/EI acquisition, L-BFGS-B on the
acquisition, **budget ≈35 evaluations** beats random search (p<0.05), up
to 17× fewer evals than grid. Best proxy objective: **total support-ray
length** (one downward ray per overhanging-facet centroid to first hit) —
within 3.5% of slicer ground truth (validated in Cura, PLA, 0.4mm nozzle —
our ecosystem). Benchmark parts: GrabCAD Alcoa + GE brackets (public;
their numbers are directly comparable).

The gap we fill: their objective is *only* support quantity — "We explore
optimality from the single standpoint of support structure quantity". No
functional surfaces, no constraints, no classification (all overhangs
equal — but FDM bridges print and islands don't; our Tier-2 classes make
a smarter objective). Their 45° test is per-facet-normal; our slice-
dilation formulation additionally catches islands/starts-in-air that
facet-normal tests miss. Tier 4 = their search machinery + our physics +
user-tagged functional-surface constraints.

## Tier-2/3 prior art: Ellsel & Stark 2024 (NX knowledge-base tool)

Closest living relative: NX plugin + Flask knowledge base; checks include
islands (via slicing — fragile in NX, slow), overhang angle, min wall,
build-volume fit, part height a multiple of layer thickness; one hardcoded
repair (round hole → teardrop) with *manual* hole selection "as not all
holes are suitable to be converted from a functional perspective" — their
only nod to functional surfaces, handled by clicking. Suggestion system
explicitly deferred to future work. Feedback pattern worth copying: per-
check results + red highlighting + per-violation link to a human-readable
explanation. Differentiation: they are CAD-side, NX-licensed, metal-PBF,
feature-heuristic, single-threshold; we are STL-side, open-source, FDM,
physics-invariant, cause-classifying, with repairs as first-class output.

## Framing and positioning (second batch)

- **Physics rationale, best formulation found** (Thompson/Campbell 2016
  §5.2.2): "Additively manufactured artifacts go through a large but
  finite number of states... Each state must be able to resist the forces
  applied to it... AM parts are usually strongest when complete." Our
  invariant = every intermediate state must be valid.
- **Leary cantilever numbers** (same source): no-support build FAILED;
  supported 5.7h (47.8+41.9cm³); self-supporting redesign 2.6h, 54.9cm³ —
  redesign beats supports on time AND material. The single best
  quantitative argument for Tier 3.
- The canonical strategy triad reorient / support / redesign-self-
  supporting maps 1:1 onto Tier 4 / slicer baseline / Tier 3.
- **Knowledge taxonomy** (Pradel 2018, Table 4): heuristics → principles →
  guidelines → rules → specifications. Our dilation check mechanises a
  "design rule" (cause-effect known, quantitative, process-specific);
  orientation is a "specification". Their criterion for design guidance:
  must influence part *shape* — cleanly separates our repairs (design
  guidance) from slicer supports (process guidance).
- **"AM-conformity"** (Tüzün 2021): citable name for what the tool checks.
  Of their 17 criteria we mechanise the strict-sense geometric ones (#2
  guideline compliance, #7 material accumulation, #8 orientation/
  functional surfaces, #13 staircase); economics deliberately out of
  scope. Their 81-edge interdependency matrix justifies re-running the
  audit after every repair.
- Ranjan/Samant/Anand's "producibility index" (iterate until no
  problematic features remain; via Pradel) is the closest academic
  ancestor of the Tier 2→3 loop.
- Pradel's validity caveat, verbatim ammunition for parameterisation: "if
  a design rule states that the minimum wall thickness achievable for FDM
  is 2 mm, it should be made clear whether this is a limitation of the
  specific machine or if it is a limitation of FDM in general."
- Lineage note: our two closest tool-papers share ancestry (Ellsel & Stark
  cite the Bath group's 2016 framework; Goguelin is Bath) — Bath went
  toward orientation search, Berlin toward knowledge checking; this
  toolkit sits at the intersection, for an audience neither serves.

## Second-batch citations

- G.A.O. Adam, D. Zimmer, "Design for Additive Manufacturing—Element
  transitions and aggregated structures," *CIRP J. Manuf. Sci. Technol.*
  7(1):20–28, 2014. DOI 10.1016/j.cirpj.2013.10.001.
- T. Lieneke, V. Denzer, G.A.O. Adam, D. Zimmer, "Dimensional tolerances
  for additive manufacturing: Experimental investigation for Fused
  Deposition Modeling," *Procedia CIRP* 43:286–291, 2016.
- A. Bernard, M.K. Thompson, G. Moroni, T. Vaneker, E. Pei, C. Barlier,
  "Functional, Technical and Economical Requirements Integration for
  Additive Manufacturing Design Education," ch.12 in Pei et al. (eds.),
  *Additive Manufacturing—Developments in Training and Education*,
  Springer, 2019. DOI 10.1007/978-3-319-76084-1_12.
- M.K. Thompson, G. Moroni, T. Vaneker, G. Fadel, R.I. Campbell, I.
  Gibson, A. Bernard, J. Schulz, P. Graf, B. Ahuja, F. Martina, "Design
  for Additive Manufacturing: Trends, Opportunities, Considerations and
  Constraints," *CIRP Annals* 65(2):737–760, 2016.
  DOI 10.1016/j.cirp.2016.05.004.
- P. Pradel, Z. Zhu, R. Bibb, J. Moultrie, "A framework for mapping design
  for additive manufacturing knowledge for industrial and product design,"
  *J. Eng. Design* 29(6):291–326, 2018. DOI 10.1080/09544828.2018.1483011.
- G-J. Tüzün, E. Garrelts, D. Roth, H. Binz, "Derivation of Criteria for
  Assessing Solution Principles Conformal for Additive Manufacturing,"
  *Proc. ICED21*, pp.923–932, 2021. DOI 10.1017/pds.2021.92.
- S. Goguelin, V. Dhokia, J.M. Flynn, "Bayesian optimisation of part
  orientation in additive manufacturing," *Int. J. Computer Integrated
  Manufacturing* 34(12):1263–1284, 2021. DOI 10.1080/0951192X.2021.1972466.
- C. Ellsel, R. Stark, "A knowledge-driven, integrated design support tool
  for additive manufacturing," *Proc. Design Society — DESIGN 2024*,
  pp.1747–1756. DOI 10.1017/pds.2024.177.
