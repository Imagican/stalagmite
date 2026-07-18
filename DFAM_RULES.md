# DfAM rules for this project (hard-won, session of 2026-07-17)

1. **The transition IS the shape.** Never stack a wide feature on a narrow
   one at 90°. Morph between cross-sections (hull, cone, gusset) so the
   junction itself satisfies the print physics.
2. **45° rule, enforced mechanically:** every slice must lie within a 45°
   dilation of the slice below. Run `dfam_audit.py part.stl --ex z0:z1:r`
   (exclude thread helices) before any STL ships.
3. **Features must reach ground.** A 45° profile starting in mid-air is
   worthless — hull/gusset it down to the nearest solid (flange, wall, bed).
4. **Ask what each right angle is FOR.** Functional flats (gland seats,
   washer faces, wrench flats) are kept deliberately and either oriented
   upward or given minimal painted support. Non-functional ones get morphed.
5. **Orientation is chosen by the critical surface.** Sealing surfaces
   print as upward-facing floors or vertical walls, never as ceilings.
   Threads print vertical, best-quality end nearest the bed.
6. **Bosses = teardrop point-DOWN or grounded gusset.** Point-up teardrops
   are for holes (ceilings), not solids.
7. **Horizontal holes ≤6mm stay round** (tapping integrity beats the tiny
   bridge); larger ones get teardropped.
8. **Verify by containment, not by eye.** Watertightness + 3D point tests
   + the slice audit; renders are illustration, the human slicer eye is
   the final gate.
9. **Sometimes the constraint dissolves the feature:** lengthening the BSP
   thread + PTFE sealing deleted the washer (and its seat, and its
   purchase) entirely. Question whether the awkward face needs to exist.
10. **Coupon-first still rules.** Design tools reduce iterations; they do
    not replace the thread-test print.
