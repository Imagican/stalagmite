# Fixture catalog — real failure history of one part (probe holder body)

Exclusion zones = BSP and M24 thread helices. **The zones are per-fixture**:
the BSP thread was lengthened at fixture 04 (see rule 9), shifting everything
above it +10mm, so the M24 helix sits lower in the early fixtures.

- fixtures 01–03: `python3 dfam_audit.py fixtures/<f> --ex 0:16.5:11 --ex 44:55:13`
- fixtures 04–06: `python3 dfam_audit.py fixtures/<f> --ex 0:16.5:11 --ex 54:65:13`

(Discovered 2026-07-18: the previously documented single command only fits
04–06; on 01–03 it lets the M24 helix false-positive ~17 extra violations.
`test_fixtures.py` encodes the correct zones and the full baseline.)

| fixture | known defect | expected audit |
|---|---|---|
| 01_teardrop_point_up.stl | Point-UP teardrop boss (hole logic applied to a solid). Boss underside unsupported; apex spike useless. | 9 violations incl. boss underside starting in air ~z38 |
| 02_teardrop_floating.stl | Point-DOWN teardrop but apex floats 7mm above flange — 45° profile starting in mid-air. | 5 violations; apex region flagged as air-start |
| 03_gusset_flat_flange.stl | Grounded gusset (correct) but flat flange underside retained for washer seal — the deliberate functional-flat case. | 4 violations: flange underside ring + bleed bridge |
| 04_cone_crescent_rims.stl | 45° cone to hex-corner CIRCLE: circumscribes hex, leaving crescent ledges past the flats. Longer thread, washer deleted. | 4 violations incl. hull-seam slivers |
| 05_flush_morph.stl | Circle→hex hull morph, flush at flats. One residual: 0.65mm internal ring where chamber/cone overlap was sloppy. | 4 violations: micro-ring z43.5 + bleed bridge |
| 06_clean_final.stl | Final. Morph flush, overlap fixed. Only the intentional round bleed-hole roof remains. | 3 violations: bleed bridge only = PASS with judged bridge |

`source_probe_holder.scad` regenerates the final version (needs OpenSCAD + BOSL2).
Earlier versions are frozen STLs only — that is the point: they are the regression baseline.