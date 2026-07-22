#!/usr/bin/env python3
"""
dfam_repair.py - Stage A of "doing": turn fail defects into REAL,
parameter-adjustable repair geometry.

Every repair is a loft between two contours taken from the actual
audited slices (never invented primitives -- the v0.12.0 lesson):

  top contour    = outline of the part's slice at the defect, i.e. the
                   shape that needs supporting
  bottom contour = outline of real existing support lower down (or the
                   defect's own footprint for a bed pillar)

Both contours are resampled to the same vertex count and aligned, so a
loft is plain per-vertex interpolation -- cheap enough for a browser to
rebuild live as the user drags Height / Easing / Flare sliders. Physics
stays a hard constraint: height can never drop below what the profile's
angle permits (max horizontal travel <= tan(angle) * height).

make_repair_specs()  -> JSON-able specs for the report / GUI
loft_solid()         -> a watertight trimesh from a spec (+ user params)
emit_fix_stl()       -> write all repairs at chosen params to one STL
"""
import numpy as np
import trimesh
from shapely.geometry import Point, Polygon

from dfam_audit import slice_region, _components

# Repair kinds:
#   loft     - morph down to real support found by walk-down
#   pillar   - ground the footprint straight to the bed
#   roofcone - INTERNAL ROOF CHAMFER: a flat internal ceiling anchored
#              all around (bottle-cap roof) is closed by a corbelled
#              cone ring climbing from the opening's wall to the
#              ceiling -- the cavity stays hollow and bores stay open.
#              A downward loft would plug the whole cavity; the chamfer
#              is what a designer would actually model ("chamfer the
#              roof into a gentle cone").

N_RING = 96          # vertices per contour ring (shared by py + js lofts)


# ------------------------------------------------------------- contours

def _largest_component_near(region, x, y):
    """The polygon component of a slice region nearest (x, y)."""
    comps = _components(region) if region is not None else []
    if not comps:
        return None
    p = Point(x, y)
    comps.sort(key=lambda g: (g.distance(p), -g.area))
    return comps[0]


def _resample_ring(poly, n=N_RING):
    """Exterior ring of a polygon resampled to n points, CCW, as (n,2)."""
    ring = poly.exterior
    if not ring.is_ccw:
        ring = type(ring)(list(ring.coords)[::-1])
    L = ring.length
    if L <= 0:
        return None
    pts = [ring.interpolate(d) for d in np.linspace(0, L, n, endpoint=False)]
    return np.array([[p.x, p.y] for p in pts])


def _align_rings(bot, top):
    """Rotate the bottom ring's start index so vertices pair off with the
    top ring by nearest angular position -- keeps the loft untwisted."""
    cb = bot.mean(axis=0)
    ct = top.mean(axis=0)
    ang_b = np.arctan2(bot[:, 1] - cb[1], bot[:, 0] - cb[0])
    ang_t = np.arctan2(top[0, 1] - ct[1], top[0, 0] - ct[0])
    k = int(np.argmin(np.abs((ang_b - ang_t + np.pi) % (2 * np.pi)
                             - np.pi)))
    return np.roll(bot, -k, axis=0)


def _max_gap(bot, top):
    """Max horizontal vertex travel between paired rings (mm)."""
    return float(np.hypot(*(top - bot).T).max())


# ------------------------------------------------------- roof detection

def _roof_opening(mesh, f, dz):
    """Is this fail feature a flat internal ceiling landing on a
    surrounding wall ring (the bottle-cap signature)?

    Returns (opening_poly, target_poly_or_None, drill_polys) when the
    support slice below has an interior hole (the cavity opening) that
    contains the defect; else None.

    `target` is the contour the chamfer closes DOWN TO -- the selected
    DEFECT's own largest inner boundary when it has one (so a tolerable
    ring near the wall gets a small corner chamfer scoped to itself,
    not a clone of the fail's full funnel), else the roof's largest
    through-hole (spigot bore). `drill_polys` are the roof through-
    holes the chamfer would actually cover (not the ones safely inside
    the target opening) -- each gets a vent shaft."""
    g = f.get("geom")
    if g is None or g.is_empty:
        return None
    c = g.centroid
    sup = slice_region(mesh, f["zlo"] - dz)
    if sup is None:
        return None
    for comp in _components(sup):
        for hole in getattr(comp, "interiors", []):
            hp = Polygon(hole)
            if not hp.is_valid or hp.area < 4 * dz * dz:
                continue
            # the defect must actually LIE in the opening -- centroid
            # tests lie for ring-shaped regions (an outer-rim overhang's
            # centroid sits in the cavity while the ring itself is
            # entirely outside the wall)
            try:
                frac = g.intersection(hp).area / max(g.area, 1e-9)
            except Exception:
                frac = 0.0
            if frac >= 0.6 and g.area <= hp.area * 1.25:
                bores = []
                roof = slice_region(mesh, f["zlo"])
                if roof is not None:
                    rc = _largest_component_near(roof, c.x, c.y)
                    for h2 in getattr(rc, "interiors", []):
                        p2 = Polygon(h2)
                        if p2.is_valid and \
                                hp.contains(p2.representative_point()):
                            bores.append(p2)
                bores.sort(key=lambda p: -p.area)
                # closure target: the DEFECT's own inner boundary first
                # (region-scoped repair), else the roof's largest bore
                own = []
                for gc in (g.geoms if g.geom_type == "MultiPolygon"
                           else [g]):
                    for h3 in getattr(gc, "interiors", []):
                        p3 = Polygon(h3)
                        if p3.is_valid and p3.area > 0.5 and \
                                hp.contains(p3.representative_point()):
                            own.append(p3)
                # the closure annulus supports everything OUTSIDE the
                # target -- so a candidate hole is only valid if the
                # defect does not lie inside it (a merged multi-layer
                # fail can carry huge artifact holes from its upper
                # rings; closing to those "repairs" a sliver and leaves
                # the real defect untouched)
                cands = own + [b for b in bores if b.area > 0.5]
                target = None
                for p4 in sorted(cands, key=lambda p: -p.area):
                    try:
                        if g.intersection(p4).area \
                                <= max(1.0, 0.02 * g.area):
                            target = p4
                            break
                    except Exception:
                        continue
                # vent shafts only for holes the chamfer actually
                # covers -- holes inside the target opening stay open
                drill_polys = []
                if target is not None:
                    for p2 in bores:
                        if not target.contains(
                                p2.representative_point()):
                            drill_polys.append(p2)
                else:
                    drill_polys = list(bores)
                return hp, target, drill_polys
    return None


# ---------------------------------------------------------------- specs

def make_repair_specs(mesh, features, dz=0.4, angle=45.0, keep=(),
                      avoid=(), ledge_max=1.8, severities=("fail",)):
    """Attach a 'repair_spec' to each fail-severity feature where a clean
    single-contour loft exists (the overwhelmingly common case). Returns
    the list of specs. Multi-lobed cases get no spec (the corbel emitter
    still covers them conservatively via loft to their own footprint).

    `keep`  = design-intent keep-clear zones (dfam_intent): repairs must
              not touch them.
    `avoid` = audit exclusion zones (thread helices etc.). You excluded
              them because that geometry is FUNCTIONAL -- so repairs
              treat them exactly like keep-clear: no anchor landings
              inside, and a roof chamfer clamps its wall attachment
              ABOVE them. If full closure no longer fits, a partial
              chamfer is emitted when the residual ledge is within
              `ledge_max`; otherwise the defect is honestly left
              unrepaired with a design-change suggestion.
    `severities` = which feature severities get specs. Default: fail
              only (what automation may weld). The report passes all
              three so a human can sculpt OPTIONAL quality repairs for
              tolerable ledges / judged bridges too -- those specs are
              marked optional=True and are never applied by
              stalagmite-fix or --emit-fix."""
    hands_off = list(keep) + list(avoid)
    if hands_off:
        from dfam_intent import geom_hits
    t = np.tan(np.radians(angle))
    z0 = float(mesh.bounds[0][2])
    specs = []
    for i, f in enumerate(features):
        f["repair_spec"] = None
        if f.get("severity") not in severities or f.get("geom") is None \
                or f["geom"].is_empty:
            continue
        optional = f.get("severity") != "fail"
        cx, cy = f["geom"].centroid.x, f["geom"].centroid.y
        z_top = f["zhi"] + dz * 0.5

        # -- the bottle-cap case first: flat internal ceiling anchored
        #    all around -> corbelled chamfer ring, NOT a cavity plug
        roof = _roof_opening(mesh, f, dz)
        if roof is not None:
            hp, target, vents = roof
            # every secondary through-hole (vent) gets a vertical
            # clearance shaft drilled through the chamfer -- a vent
            # that stops at the chamfer is not a vent
            drill = []
            for p in vents:
                ring = _resample_ring(p.buffer(0.15, 16), n=24)
                if ring is not None:
                    drill.append(np.round(ring, 2).tolist())
            O = _resample_ring(hp.buffer(0.3, 32))    # bite into the wall
            # the chamfer attaches to the opening's wall: it must start
            # ABOVE any functional zone on that wall.
            #   keep zones  = declared volumes: anywhere inside counts.
            #   avoid zones = thread helices ON A WALL: they only claim
            #     the wall NEAR the zone's lateral boundary -- a landing
            #     surface several mm inside rmax (e.g. an applied cone's
            #     funnel) is NOT that threaded wall.
            z_wall_min = z0 + dz
            clamped_by = None
            d_wall = hp.exterior.distance(Point(cx, cy))
            for zn, volume in ([(k, True) for k in keep]
                               + [(a, False) for a in avoid]):
                from dfam_audit import _ex_parts
                klo, khi, rmax, kx, ky = _ex_parts(zn)
                if khi >= z_top or khi <= z_wall_min:
                    continue
                dw = hp.exterior.distance(Point(kx, ky))
                hit = (dw <= rmax) if volume \
                    else (rmax - 2.5 <= dw <= rmax + 0.5)
                if hit and khi + dz > z_wall_min:
                    z_wall_min = khi + dz
                    clamped_by = (klo, khi, rmax)
            # and the wall must actually EXIST below the opening: walk
            # down and require the bite ring to stay inside material
            # (a sloped funnel wall recedes -- a chamfer column there
            # would hang in air)
            if O is not None:
                pts = [Point(x, y) for x, y in O[::8]]
                z_close_probe = f["zlo"] - dz
                zz = z_close_probe
                while zz > z_wall_min + dz * 0.5:
                    supz = slice_region(mesh, zz)
                    n_in = 0 if supz is None else \
                        sum(1 for p in pts if supz.contains(p))
                    if n_in < 0.9 * len(pts):
                        z_wall_min = zz + dz
                        if clamped_by is None:
                            clamped_by = (round(zz, 2), round(zz, 2),
                                          0.0)
                        break
                    zz -= dz
            if target is not None:
                Iring = _resample_ring(target)
            else:                                     # close to an apex
                Iring = _resample_ring(Point(cx, cy).buffer(
                    max(0.6, dz), 32))
            if O is not None and Iring is not None:
                O = _align_rings(O, Iring)
                gap = _max_gap(O, Iring)
                need = max(gap / max(t, 1e-6) * 1.05, dz * 2)
                # closure must COMPLETE at the roof underside -- the
                # roof's first slice needs the finished ring below it.
                # z_top is the weld band biting into the roof above.
                z_close = f["zlo"] - dz * 0.5
                h_avail = z_close - z_wall_min
                residual = 0.0
                over = False
                if h_avail >= need:                   # full closure fits
                    z_bot = z_close - need
                elif h_avail > dz * 2:
                    # partial closure at the profile angle: close what
                    # physics allows, leave the rest as a ledge
                    reach = h_avail * t
                    residual = gap - reach
                    over = bool(residual - dz * t > ledge_max)
                    if over:
                        f["repair_blocked"] = (
                            f"roof cone limited: functional zone "
                            f"(threads?) occupies the wall to "
                            f"z={z_wall_min - dz:.1f}; a {angle:.0f} deg "
                            f"cone needs {need:.1f}mm of clear wall "
                            f"below the ceiling but only {h_avail:.1f}mm "
                            f"exists, leaving a {residual:.1f}mm ledge "
                            f"beyond the {ledge_max}mm allowance -- "
                            f"raise/dome the roof or shorten the "
                            f"threads (design change; stalagmite-"
                            f"autofix can search it if parametric)")
                        f.setdefault("repairs", []).append(
                            f["repair_blocked"])
                    frac = np.clip(reach / np.maximum(
                        np.hypot(*(Iring - O).T), 1e-9), 0.0, 1.0)
                    Iring = O + (Iring - O) * frac[:, None]
                    gap = _max_gap(O, Iring)
                    z_bot = z_wall_min
                else:
                    f["repair_blocked"] = (
                        f"roof cone blocked: no usable wall below the "
                        f"ceiling (wall unavailable below "
                        f"z={z_wall_min - dz:.1f} -- functional zone, "
                        f"or a sloped/receding landing a chamfer "
                        f"column cannot sit on) -- fix the ORIGINAL "
                        f"part or redesign; patching a patch rarely "
                        f"ends well")
                    f.setdefault("repairs", []).append(
                        f["repair_blocked"])
                    continue
                spec = {
                    "optional": optional,
                    "severity": f["severity"],
                    "over_allowance": over,
                    "ledge_max": ledge_max,
                    "feature": i, "kind": "roofcone",
                    "z_top": round(float(z_top), 3),
                    "z_close": round(float(z_close), 3),
                    "z_bot": round(float(z_bot), 3),
                    "z_floor": round(float(max(z0, z_wall_min - dz)), 3),
                    "min_h": round(float(min(need, z_close - z_bot)), 3),
                    "max_gap": round(float(gap), 3),
                    "angle": angle, "dz": dz,
                    "drill": drill,
                    "residual_ledge": round(float(max(0.0, residual)), 2),
                    "clamped_above": ([round(v, 2) for v in clamped_by]
                                      if clamped_by else None),
                    "top": np.round(Iring, 2).tolist(),
                    "bot": np.round(O, 2).tolist(),
                }
                f["repair_spec"] = spec
                specs.append(spec)
                continue

        top_slice = slice_region(mesh, min(z_top - 1e-3, f["zhi"]))
        top_comp = _largest_component_near(top_slice, cx, cy)
        if top_comp is None:
            continue
        top = _resample_ring(top_comp)
        if top is None:
            continue
        # walk down for the highest feasible landing: support component
        # whose contour the loft can reach at >= the profile angle
        best = None
        z = f["zlo"] - dz
        while z > z0 + dz * 0.25:
            sup = _largest_component_near(slice_region(mesh, z), cx, cy)
            if sup is not None and hands_off \
                    and geom_hits(sup, z, z, hands_off):
                sup = None                    # functional surface: pass
            if sup is not None:
                # a RING landing (support with a hole inside -- e.g. a
                # tube wall under an overhanging rim) must NOT be
                # fan-cap lofted: the caps would plug the interior and
                # a true boolean union then FILLS the cavity. Use the
                # annular skirt construction instead (roof-chamfer
                # topology mirrored outward: sloped face + inner wall
                # column + top annulus -- the inside stays hollow).
                if len(getattr(sup, "interiors", [])) > 0:
                    inner = Polygon(sup.exterior).buffer(-0.3, 32)
                    bot = _resample_ring(inner) \
                        if not inner.is_empty else None
                    if bot is not None:
                        bot = _align_rings(bot, top)
                        need = _max_gap(bot, top) / max(t, 1e-6)
                        if (z_top - z) >= need * 0.999:
                            best = ("skirt", z, bot)
                            break
                else:
                    bot = _resample_ring(sup)
                    if bot is not None:
                        bot = _align_rings(bot, top)
                        need = _max_gap(bot, top) / max(t, 1e-6)
                        if (z_top - z) >= need * 0.999:
                            best = ("loft", z, bot)
                            break
            z -= dz
        if best is None:
            # bed pillar: land the footprint straight on the plate
            bot = top.copy()
            best = ("pillar", z0, bot)
        kind, z_bot, bot = best
        gap = _max_gap(bot, top)
        min_h = max(gap / max(t, 1e-6), dz * 2)
        spec = {
            "optional": optional,
            "severity": f["severity"],
            "feature": i, "kind": kind,
            "z_top": round(float(z_top), 3),
            "z_bot": round(float(z_bot), 3),
            "z_floor": round(z0, 3),          # bed: repairs cannot go below
            "min_h": round(float(min_h), 3),
            "max_gap": round(float(gap), 3),
            "angle": angle, "dz": dz,
            "top": np.round(top, 2).tolist(),
            "bot": np.round(bot, 2).tolist(),
        }
        if kind == "skirt":
            spec["z_close"] = spec["z_top"]   # annulus welds at the rim
        f["repair_spec"] = spec
        specs.append(spec)
    return specs


# ---------------------------------------------------------------- lofts

def loft_solid(spec, height=None, easing=1.0, flare=1.0, rings=32):
    """Build a watertight loft solid from a spec.

    height: total height of the transition (>= spec min_h; default:
            z_top - z_bot as found, i.e. the discovered landing)
    easing: silhouette exponent -- 1 = straight chamfer, >1 concave
            (fillet-like), <1 convex
    flare : PILLAR ONLY -- scales the foot on the build plate (a wider
            bed anchor is legitimate). Lofts ignore it entirely: their
            base is pinned to the landing contour and their top to the
            defect, so any profile fuller than the straight chamfer
            must bulge convex somewhere -- the concave family
            (chamfer -> cove) belongs to `easing`.
    """
    top = np.asarray(spec["top"], dtype=float)
    bot = np.asarray(spec["bot"], dtype=float)
    z_top = spec["z_top"]
    h_found = z_top - spec["z_bot"]
    H = max(float(height) if height else h_found, spec["min_h"])
    if "z_floor" in spec:                 # never build below the bed
        H = min(H, z_top - spec["z_floor"])
    z_bot = z_top - H
    cb = bot.mean(axis=0)
    pillar = spec.get("kind") == "pillar"
    if pillar:
        bot = cb + (bot - cb) * float(flare)
    n = len(top)
    verts, faces = [], []
    for k in range(rings + 1):
        s = k / rings
        te = s ** float(easing)                 # eased blend bottom->top
        ring = bot + (top - bot) * te
        z = z_bot + H * s
        for x, y in ring:
            verts.append((x, y, z))
    for k in range(rings):
        a0, b0 = k * n, (k + 1) * n
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((a0 + j, a0 + j2, b0 + j))
            faces.append((a0 + j2, b0 + j2, b0 + j))
    # caps (fan around centroid; contours from slices are near-simple)
    cbot = len(verts)
    verts.append((*bot.mean(axis=0), z_bot))
    ctop = len(verts)
    verts.append((*top.mean(axis=0), z_top))
    for j in range(n):
        j2 = (j + 1) % n
        faces.append((cbot, j2, j))                          # bottom
        faces.append((ctop, rings * n + j, rings * n + j2))  # top
    m = trimesh.Trimesh(vertices=np.array(verts, dtype=float),
                        faces=np.array(faces, dtype=np.int64),
                        process=True)
    try:
        trimesh.repair.fix_normals(m)
    except Exception:
        pass
    return m


def roof_chamfer_solid(spec, height=None, easing=1.0, rings=32):
    """Build the internal roof chamfer: a corbelled ring climbing from
    the opening's wall contour (bot, at z_bot) up-and-inward to the
    bore contour / apex (top, at z_top), closed by the outer wall face
    and the top annulus. Cross-section is the classic chamfer triangle;
    the cavity below stays hollow and the bore stays open.

    height: chamfer depth below the ceiling (>= min_h; more = gentler)
    easing: 1 = straight chamfer, >1 concave (dome-like)
    """
    top = np.asarray(spec["top"], dtype=float)     # inner ring @ z_close
    bot = np.asarray(spec["bot"], dtype=float)     # opening ring @ z_bot
    z_top = spec["z_top"]                          # weld top (in roof)
    z_close = spec.get("z_close", z_top)           # closure completes here
    H = max(float(height) if height else (z_close - spec["z_bot"]),
            spec["min_h"])
    if "z_floor" in spec:
        H = min(H, z_close - spec["z_floor"] - spec["dz"])
    z_bot = z_close - H
    n = len(top)
    verts, faces = [], []
    for k in range(rings + 1):                     # the cone surface
        s = k / rings
        te = s ** float(easing)
        ring = bot + (top - bot) * te
        z = z_bot + H * s
        for x, y in ring:
            verts.append((x, y, z))
    n_rings = rings + 1
    if z_top > z_close + 1e-6:                     # vertical weld band
        for x, y in top:
            verts.append((x, y, z_top))
        n_rings += 1
    for k in range(n_rings - 1):
        a0, b0 = k * n, (k + 1) * n
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((a0 + j, a0 + j2, b0 + j))
            faces.append((a0 + j2, b0 + j2, b0 + j))
    w0 = len(verts)                                # outer ring @ z_top
    for x, y in bot:
        verts.append((x, y, z_top))
    A = 0                                          # bottom cone ring
    B = (n_rings - 1) * n                          # topmost inner ring
    for j in range(n):
        j2 = (j + 1) % n
        faces.append((A + j, w0 + j, A + j2))      # outer wall
        faces.append((A + j2, w0 + j, w0 + j2))
        faces.append((B + j, B + j2, w0 + j))      # top annulus
        faces.append((B + j2, w0 + j2, w0 + j))
    m = trimesh.Trimesh(vertices=np.array(verts, dtype=float),
                        faces=np.array(faces, dtype=np.int64),
                        process=True)
    try:
        trimesh.repair.fix_normals(m)
    except Exception:
        pass
    m = _drill_vents(m, spec, z_bot, z_top)
    return m


def _drill_vents(body, spec, z_bot, z_top):
    """Subtract a vertical clearance shaft for every secondary roof
    hole (vent) the chamfer would otherwise cover. Requires a real
    boolean engine (manifold3d is a dependency); on failure the
    undrilled body is returned with metadata flagging it."""
    drill = spec.get("drill") or []
    body.metadata["vents"] = len(drill)
    body.metadata["vents_drilled"] = 0
    if not drill:
        return body
    from shapely.geometry import Polygon as _Poly
    drilled = body
    n_ok = 0
    for ring in drill:
        try:
            prism = trimesh.creation.extrude_polygon(
                _Poly(ring), height=(z_top - z_bot) + 2.0)
            prism.apply_translation([0, 0, z_bot - 1.0])
            out = trimesh.boolean.difference([drilled, prism])
            if out is None or len(out.faces) == 0:
                raise ValueError("empty difference result")
            drilled = out
            n_ok += 1
        except Exception:
            continue
    drilled.metadata["vents"] = len(drill)
    drilled.metadata["vents_drilled"] = n_ok
    return drilled


def build_body(spec, height=None, easing=1.0, flare=1.0):
    """One repair solid from a spec, dispatched by kind. `skirt`
    (external annular chamfer under an overhanging rim) shares the
    roof-chamfer topology -- sloped face, wall column, top annulus --
    so the part interior stays hollow."""
    if spec.get("kind") in ("roofcone", "skirt"):
        return roof_chamfer_solid(spec, height, easing)
    return loft_solid(spec, height, easing, flare)


def emit_fix_stl(mesh, features, out_path, dz=0.4, angle=45.0,
                 height=None, easing=1.0, flare=1.0, keep=(), avoid=()):
    """Build repair solids for every fail feature and write them as one
    STL of union-ready bodies. Returns the number of bodies written.
    Bodies that intersect a keep-clear zone are not emitted."""
    specs = [s for s in
             make_repair_specs(mesh, features, dz, angle, keep, avoid)
             if not s.get("over_allowance")]
    if not specs:
        return 0
    bodies = [build_body(s, height, easing, flare) for s in specs]
    if keep:
        from dfam_intent import body_blocked
        bodies = [b for b in bodies if not body_blocked(b, keep)]
    if not bodies:
        return 0
    trimesh.util.concatenate(bodies).export(out_path)
    return len(bodies)
