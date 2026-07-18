#!/usr/bin/env python3
"""
dfam_audit.py - mechanical enforcement of the 45-degree rule.
Every slice must lie within a 45-deg dilation of the slice below it
(the layer-physics of FDM). Violations = material starting in air or
growing outward too fast. Small violations are reported as bridges
for human judgment, not auto-rejected.

Usage: python3 dfam_audit.py part.stl [--angle 45] [--dz 0.4]
                [--ex zlo:zhi:rmax ...] [--export out.ply]

The core algorithm is unchanged from the proven original: slices are
built in WORLD coordinates from section.discrete loops (never
Path3D.to_2D(), whose arbitrary per-slice rotation frames hallucinate
violations on rotationally-asymmetric features).
"""
import sys
import numpy as np
import trimesh
from dataclasses import dataclass
from shapely.geometry import MultiPolygon, Point, Polygon

AREA_FLOOR = 0.8      # mm^2 - ignore slivers below this
GROW_SLOP = 0.05      # mm  - numerical slack added to the dilation
BRIDGE_SPAN = 8.0     # mm  - legacy note threshold ("judge as bridge")

# Literature-sourced thresholds (see LITERATURE.md; all boundary-condition
# dependent -- override per printer/material as needed):
LEDGE_MAX = 1.8       # mm  - max unsupported cantilever ledge for FDM
                      #       (Adam & Zimmer 2014: OK to 1.8, destroyed at 2.0)
BRIDGE_MAX = 10.0     # mm  - max unsupported FDM bridge span (Hinchy, after
                      #       Redwood et al. 2017); rough downskin below that
CONTACT_EPS = 0.15    # mm  - tolerance for "touches" tests in classification

# Tier-2 classes and severities
#   starts-in-air : new body appears with nothing below (fatal)
#   island        : region unsupported below AND unattached in-plane (fatal)
#   steep-growth  : cantilever ledge, anchored on one side
#   bridge        : anchored on two+ opposing sides
# severity: "fail" | "judge" (printable but human decides) | "tolerable"
# lint-only: "surface" (prints, degraded quality -- never fails the audit)
SEVERITY_ORDER = {"fail": 0, "judge": 1, "tolerable": 2, "surface": 3}


@dataclass
class Violation:
    z: float
    area: float          # mm^2
    span: float          # mm (max bbox extent; 0 for air-starts)
    centroid: tuple      # (x, y)
    kind: str            # "air-start" | "unsupported"
    geom: object = None  # shapely geometry of the offending region
    cls: str = None      # Tier-2 class (see above); None = unclassified
    severity: str = None
    ledge: float = None  # mm, cantilever reach (steep-growth)
    free_span: float = None  # mm, unsupported crossing distance (bridge)

    @property
    def note(self):
        if self.kind == "air-start":
            base = "material (re)starts in air"
        else:
            base = (f"span {self.span:.1f}mm "
                    f"@({self.centroid[0]:.0f},{self.centroid[1]:.0f})")
        if self.cls:
            extra = ""
            if self.cls == "steep-growth" and self.ledge is not None:
                extra = f" ledge {self.ledge:.1f}mm"
            elif self.cls == "bridge" and self.free_span is not None:
                extra = f" free {self.free_span:.1f}mm"
            base += f"  [{self.cls}{extra} -> {self.severity}]"
        return base


def slices(mesh, dz):
    z0, z1 = mesh.bounds[0][2], mesh.bounds[1][2]
    zs = np.arange(z0 + dz * 0.51, z1 - dz * 0.11, dz)
    for z in zs:
        sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if sec is None:
            yield z, None
            continue
        # build region directly from world-space section loops (no 2D frame)
        loops = [np.asarray(d)[:, :2] for d in sec.discrete if len(d) >= 3]
        polys = []
        for l in loops:
            p = Polygon(l)
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty:
                polys.append(p)
        polys.sort(key=lambda p: p.area, reverse=True)
        region = None
        for p in polys:
            if region is None:
                region = p
            elif region.contains(p.representative_point()):
                region = region.difference(p)
            else:
                region = region.union(p)
        yield z, region


def _ex_parts(e):
    """Exclusion zone as (zlo, zhi, rmax, cx, cy); center optional."""
    if len(e) == 5:
        return e
    zlo, zhi, rmax = e
    return zlo, zhi, rmax, 0.0, 0.0


def _geom_max_r(geom, cx, cy):
    try:
        xs, ys = geom.exterior.coords.xy
        return float(np.hypot(np.asarray(xs) - cx,
                              np.asarray(ys) - cy).max())
    except Exception:
        b = geom.bounds
        return max(np.hypot(b[0] - cx, b[1] - cy),
                   np.hypot(b[2] - cx, b[3] - cy))


def _kasa_circle(xy):
    """Least-squares circle fit. Returns (cx, cy, r, rms_residual)."""
    x, y = xy[:, 0], xy[:, 1]
    A = np.column_stack([x, y, np.ones(len(x))])
    b = x * x + y * y
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0, 0.0, 0.0, np.inf
    cx, cy = sol[0] / 2, sol[1] / 2
    r = np.sqrt(max(sol[2] + cx * cx + cy * cy, 0.0))
    res = np.sqrt(((np.hypot(x - cx, y - cy) - r) ** 2).mean())
    return float(cx), float(cy), float(r), float(res)


def detect_helix_zones(violations, dz=0.4, max_area=30.0):
    """Auto-recognise thread helices from an un-excluded audit.

    Signature (HANDOFF: "periodic angular migration of a constant-area
    lobe"): many consecutive layers of small violations whose centroids
    lie on a circle and advance in angle by a consistent per-layer step.
    Real defects don't do this -- flat ledges are single wide layers,
    boss undersides are mirror-symmetric lobe pairs, bridges last a
    couple of layers.

    Returns a list of dicts {zlo, zhi, rmax, cx, cy, step_deg, n}.
    """
    small = sorted((v for v in violations
                    if v.area < max_area and v.geom is not None),
                   key=lambda v: v.z)
    if not small:
        return []
    # z-contiguous clusters
    clusters, cur = [], [small[0]]
    for v in small[1:]:
        if v.z - cur[-1].z <= dz * 2.001:
            cur.append(v)
        else:
            clusters.append(cur)
            cur = [v]
    clusters.append(cur)

    zones = []
    for cl in clusters:
        if len(cl) < 8 or len({round(v.z, 3) for v in cl}) < 6:
            continue
        pts = np.array([v.centroid for v in cl])
        cx, cy, r, res = _kasa_circle(pts)
        # drop radial outliers (mixed clusters) and refit once
        rr = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
        keep = np.abs(rr - np.median(rr)) <= 3.0
        if keep.sum() < 8:
            continue
        cl = [v for v, k in zip(cl, keep) if k]
        pts = pts[keep]
        cx, cy, r, res = _kasa_circle(pts)
        if not (3.0 <= r <= 60.0) or res > max(0.15 * r, 0.6):
            continue
        # angular progression: consistent nonzero per-layer step
        order = np.argsort([v.z for v in cl])
        ang = np.degrees(np.arctan2(pts[order, 1] - cy,
                                    pts[order, 0] - cx))
        steps = (np.diff(ang) + 180.0) % 360.0 - 180.0
        steps = steps[np.abs(steps) > 1e-6]
        if len(steps) < 5:
            continue
        med = np.median(np.abs(steps))
        if not (10.0 <= med <= 160.0):
            continue
        signs = np.sign(steps[np.abs(steps) > 2.0])
        if len(signs) and np.abs(signs.sum()) < 0.7 * len(signs):
            continue
        rmax = max(_geom_max_r(v.geom, cx, cy) for v in cl) + 0.5
        zones.append({"zlo": min(v.z for v in cl) - dz,
                      "zhi": max(v.z for v in cl) + dz,
                      "rmax": rmax, "cx": cx, "cy": cy,
                      "step_deg": float(np.median(steps)),
                      "n": len(cl)})
    # absorption: thread-runout ledges just above a helix that sit
    # within (or barely beyond) the zone radius belong to the thread
    # feature -- extend the zone in z AND radius, with a hard growth cap
    # so the zone can never creep out to swallow real defects
    for zn in zones:
        rmax0 = zn["rmax"]
        grew = True
        while grew:
            grew = False
            for v in violations:
                if (zn["zhi"] < v.z <= zn["zhi"] + 6 * dz
                        and v.geom is not None):
                    gr = _geom_max_r(v.geom, zn["cx"], zn["cy"])
                    if gr <= min(zn["rmax"] + 1.0, rmax0 + 2.0):
                        zn["zhi"] = v.z + dz
                        zn["rmax"] = max(zn["rmax"], gr + 0.3)
                        grew = True
    return zones


def _components(geom):
    if geom.is_empty:
        return []
    if hasattr(geom, "geoms"):
        return [g for g in geom.geoms if not g.is_empty and g.area > 1e-6]
    return [geom]


def classify(g, cur_supported, ledge_max=LEDGE_MAX, bridge_max=BRIDGE_MAX):
    """Tier-2 classification of one unsupported region `g`.

    cur_supported = the part of the current slice that IS supported by the
    slice below (already dilation-buffered). Classification is by in-plane
    anchoring:
      no anchor          -> island        (fatal: nothing holds it)
      one anchor side    -> steep-growth  (cantilever; Adam & Zimmer ledge)
      opposing anchors   -> bridge        (two-sided; Hinchy span limit)
    Returns (cls, severity, ledge, free_span).
    """
    try:
        adj = g.buffer(CONTACT_EPS).intersection(cur_supported)
    except Exception:
        adj = g.buffer(CONTACT_EPS).buffer(0).intersection(cur_supported.buffer(0))
    anchors = _components(adj)
    if not anchors:
        return "island", "fail", None, None
    # reach = deepest point of g from any anchoring material
    merged = adj if not adj.is_empty else anchors[0]
    try:
        reach = g.hausdorff_distance(merged)
    except Exception:
        reach = max(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1])
    # bridge test: >=2 anchor patches subtending a wide angle around g
    if len(anchors) >= 2:
        cx, cy = g.centroid.x, g.centroid.y
        angs = [np.arctan2(a.centroid.y - cy, a.centroid.x - cx)
                for a in anchors]
        best = 0.0
        for i in range(len(angs)):
            for j in range(i + 1, len(angs)):
                d = abs(angs[i] - angs[j]) % (2 * np.pi)
                best = max(best, min(d, 2 * np.pi - d))
        if np.degrees(best) >= 120.0:
            # crossing distance: deepest unsupported point sits mid-span
            free = 2.0 * reach
            sev = "judge" if free <= bridge_max else "fail"
            return "bridge", sev, None, free
    # cantilever
    sev = "tolerable" if reach <= ledge_max else "fail"
    return "steep-growth", sev, reach, None


def audit_mesh(mesh, max_angle=45.0, dz=0.4, exclude=(),
               ledge_max=LEDGE_MAX, bridge_max=BRIDGE_MAX,
               warn_angle=None, min_wall=None, warnings_out=None):
    """Run the audit on a loaded trimesh. Returns (bed_area, [Violation]).

    Optional lint passes (results appended to `warnings_out` list, never
    to the violations -- they do not affect PASS/FAIL):
      warn_angle: e.g. 30.0 -- regions self-supporting at max_angle but
        not at warn_angle print with degraded downskin surface (Saunders'
        traffic-light: green/yellow/red).
      min_wall: e.g. 0.8 -- flag in-plane features locally thinner than
        this (morphological opening test; Hinchy 0.8mm FFF minimum,
        Gibson: walls >= 2x nozzle diameter).
    """
    grow = dz * np.tan(np.radians(max_angle)) + GROW_SLOP
    grow_warn = (dz * np.tan(np.radians(warn_angle)) + GROW_SLOP
                 if warn_angle else None)
    prev = None
    first_area = None
    violations = []
    for z, cur in slices(mesh, dz):
        if cur is None or cur.is_empty:
            prev = cur
            continue
        if min_wall and warnings_out is not None:
            r = min_wall / 2.0
            try:
                thin = cur.difference(cur.buffer(-r).buffer(r * 1.01))
            except Exception:
                thin = None
            if thin is not None and not thin.is_empty:
                for e in exclude:
                    zlo, zhi, rmax, cx, cy = _ex_parts(e)
                    if zlo <= z <= zhi:
                        thin = thin.difference(Point(cx, cy).buffer(rmax))
                for g in _components(thin):
                    if g.area > AREA_FLOOR:
                        warnings_out.append(Violation(
                            z, g.area, 0.0,
                            (g.centroid.x, g.centroid.y),
                            "thin-wall", g, cls="thin-wall",
                            severity="surface"))
        if prev is None or prev.is_empty:
            if first_area is None:
                first_area = cur.area
            else:
                violations.append(Violation(z, cur.area, 0.0,
                                            (cur.centroid.x, cur.centroid.y),
                                            "air-start", cur,
                                            cls="starts-in-air",
                                            severity="fail"))
        else:
            supported = prev.buffer(grow)
            unsupported = cur.difference(supported)
            for e in exclude:
                zlo, zhi, rmax, cx, cy = _ex_parts(e)
                if zlo <= z <= zhi:
                    unsupported = unsupported.difference(
                        Point(cx, cy).buffer(rmax))
            if unsupported.area > AREA_FLOOR:
                # exclusion zones count as anchoring material: they are
                # declared legitimately printable (thread helices), so a
                # region touching one is not an island
                anchor_base = supported
                for e in exclude:
                    zlo, zhi, rmax, cx, cy = _ex_parts(e)
                    if zlo <= z <= zhi:
                        anchor_base = anchor_base.union(
                            Point(cx, cy).buffer(rmax))
                cur_supported = cur.intersection(anchor_base)
                geoms = (unsupported.geoms
                         if isinstance(unsupported, MultiPolygon)
                         else [unsupported])
                for g in geoms:
                    if g.area > AREA_FLOOR:
                        b = g.bounds
                        span = max(b[2] - b[0], b[3] - b[1])
                        cls, sev, ledge, free = classify(
                            g, cur_supported, ledge_max, bridge_max)
                        violations.append(Violation(
                            z, g.area, span,
                            (g.centroid.x, g.centroid.y),
                            "unsupported", g,
                            cls=cls, severity=sev,
                            ledge=ledge, free_span=free))
            if grow_warn is not None and warnings_out is not None:
                # yellow band: fine at max_angle, degraded at warn_angle
                band = cur.difference(prev.buffer(grow_warn)).difference(
                    unsupported.buffer(CONTACT_EPS))
                for e in exclude:
                    zlo, zhi, rmax, cx, cy = _ex_parts(e)
                    if zlo <= z <= zhi:
                        band = band.difference(Point(cx, cy).buffer(rmax))
                for g in _components(band):
                    if g.area > AREA_FLOOR:
                        warnings_out.append(Violation(
                            z, g.area, 0.0,
                            (g.centroid.x, g.centroid.y),
                            "warn-band", g, cls="steep-surface",
                            severity="surface"))
        prev = cur
    return first_area, violations


def aggregate(violations, dz=0.4):
    """Group per-slice violations into multi-layer features.

    Violations of the same class in consecutive slices whose regions
    overlap in plan view are one physical defect. Returns a list of dicts
    sorted worst-severity-first then by z.
    """
    features = []   # each: {cls, severity, zlo, zhi, layers[], geom}
    open_feats = []
    last_z = None
    for v in sorted(violations, key=lambda v: v.z):
        if last_z is not None and v.z - last_z > dz * 1.5:
            features.extend(open_feats)
            open_feats = []
        matched = None
        for f in open_feats:
            same_group = (f["cls"] == v.cls or
                          {f["cls"], v.cls} <= {"steep-growth", "bridge"})
            if (same_group and v.geom is not None
                    and f["geom"] is not None
                    and abs(v.z - f["zhi"]) <= dz * 1.5
                    and f["geom"].buffer(dz * 1.5).intersects(v.geom)):
                # buffer covers one 45-deg dilation step (dz*tan45 + slop),
                # so successive corbel strips of one defect chain together
                matched = f
                break
        if matched:
            matched["zhi"] = v.z
            if v.cls == "bridge":
                matched["cls"] = "bridge"   # bridge wins over steep-growth
            matched["layers"].append(v)
            try:
                matched["geom"] = matched["geom"].union(v.geom)
            except Exception:
                pass
            if SEVERITY_ORDER.get(v.severity, 0) < SEVERITY_ORDER.get(
                    matched["severity"], 0):
                matched["severity"] = v.severity
        else:
            open_feats.append({"cls": v.cls, "severity": v.severity,
                               "zlo": v.z, "zhi": v.z, "layers": [v],
                               "geom": v.geom})
        last_z = v.z
    features.extend(open_feats)
    # transitive closure: merge features that touch in plan and in z
    # (first-match-wins in the pass above can split mirror-symmetric
    # lobes of one defect)
    merged = True
    while merged:
        merged = False
        for i in range(len(features)):
            for j in range(i + 1, len(features)):
                a, b = features[i], features[j]
                same_group = (a["cls"] == b["cls"] or
                              {a["cls"], b["cls"]} <= {"steep-growth",
                                                       "bridge"})
                z_touch = (a["zlo"] - dz * 1.5 <= b["zhi"] and
                           b["zlo"] - dz * 1.5 <= a["zhi"])
                if (same_group and z_touch and a["geom"] is not None
                        and b["geom"] is not None
                        and a["geom"].buffer(dz * 1.5).intersects(b["geom"])):
                    a["zlo"] = min(a["zlo"], b["zlo"])
                    a["zhi"] = max(a["zhi"], b["zhi"])
                    a["layers"].extend(b["layers"])
                    if b["cls"] == "bridge":
                        a["cls"] = "bridge"
                    if SEVERITY_ORDER.get(b["severity"], 0) < \
                            SEVERITY_ORDER.get(a["severity"], 0):
                        a["severity"] = b["severity"]
                    try:
                        a["geom"] = a["geom"].union(b["geom"])
                    except Exception:
                        pass
                    del features[j]
                    merged = True
                    break
            if merged:
                break
    # feature-level bridge span: the minor axis of the merged region's
    # minimum rotated rectangle ~ the physical width being roofed
    # (per-layer free spans only measure the corbelling step)
    for f in features:
        if f["cls"] == "bridge" and f["geom"] is not None:
            try:
                mrr = f["geom"].minimum_rotated_rectangle
                xs, ys = mrr.exterior.coords.xy
                e1 = np.hypot(xs[1] - xs[0], ys[1] - ys[0])
                e2 = np.hypot(xs[2] - xs[1], ys[2] - ys[1])
                f["roof_width"] = float(min(e1, e2))
                if f["roof_width"] > BRIDGE_MAX and f["severity"] != "fail":
                    f["severity"] = "fail"
            except Exception:
                f["roof_width"] = None
    features.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 0),
                                 f["zlo"]))
    return features


def audit(path, max_angle=45.0, dz=0.4, exclude=(), export=None,
          suggest=False, warn_angle=None, min_wall=None, auto_ex=False,
          report=None):
    """CLI-style audit: load, run, print report. Returns True on PASS."""
    m = trimesh.load(path, force='mesh')
    exclude = list(exclude)
    print(f"== DfAM audit: {path}  (rule: {max_angle} deg, layer {dz}mm) ==")
    if auto_ex:
        _, pass1 = audit_mesh(m, max_angle, dz, exclude)
        zones = detect_helix_zones(pass1, dz)
        for zn in zones:
            print(f"auto-ex: helix detected z {zn['zlo']:.1f}-"
                  f"{zn['zhi']:.1f}, r<={zn['rmax']:.1f} around "
                  f"({zn['cx']:.1f},{zn['cy']:.1f}), "
                  f"{zn['step_deg']:+.1f} deg/layer ({zn['n']} lobes) "
                  f"-- reusable as --ex "
                  f"{zn['zlo']:.1f}:{zn['zhi']:.1f}:{zn['rmax']:.1f}")
            exclude.append((zn["zlo"], zn["zhi"], zn["rmax"],
                            zn["cx"], zn["cy"]))
        if not zones:
            print("auto-ex: no thread helices detected")
    warnings = [] if (warn_angle or min_wall) else None
    first_area, violations = audit_mesh(m, max_angle, dz, exclude,
                                        warn_angle=warn_angle,
                                        min_wall=min_wall,
                                        warnings_out=warnings)
    print(f"bed contact: {first_area:.0f} mm2")
    if export:
        n = export_colored(m, violations, dz, export)
        print(f"violation mesh written: {export} ({n} faces painted)")
    if report:
        from dfam_report import write_report
        rfeats = aggregate(violations, dz)
        suggest_repairs(m, rfeats, dz, max_angle)
        write_report(m, violations, rfeats, report,
                     meta={"part": path.split("/")[-1].split("\\")[-1],
                           "angle": max_angle, "dz": dz,
                           "bed": first_area,
                           "zones": [list(_ex_parts(e)) for e in exclude]})
        print(f"interactive report written: {report}")
    if warnings:
        wf = aggregate(warnings, dz)
        print(f"{len(wf)} lint warning(s) (do not fail the audit):")
        for f in wf[:8]:
            v0 = max(f["layers"], key=lambda v: v.area)
            label = ("surface <" + f"{warn_angle:.0f} deg"
                     if f["cls"] == "steep-surface"
                     else f"wall <{min_wall}mm")
            print(f"  [{label}] z {f['zlo']:.1f}-{f['zhi']:.1f} "
                  f"@({v0.centroid[0]:.0f},{v0.centroid[1]:.0f}) "
                  f"({len(f['layers'])} layer(s))")
        if len(wf) > 8:
            print(f"  ... +{len(wf) - 8} more")
    if not violations:
        print("PASS - every layer supported within the angle rule.")
        return True
    print(f"{len(violations)} violation(s):")
    for v in violations[:12]:
        print(f"  z={v.z:6.1f}  {v.area:7.1f} mm2  {v.note}")
    if len(violations) > 12:
        print(f"  ... +{len(violations)-12} more")
    feats = aggregate(violations, dz)
    if suggest:
        suggest_repairs(m, feats, dz, max_angle)
    print(f"-- {len(feats)} defect feature(s) --")
    for f in feats:
        v0 = max(f["layers"], key=lambda v: v.area)
        dims = ""
        if f["cls"] == "steep-growth":
            led = max((v.ledge or 0) for v in f["layers"])
            dims = f", ledge {led:.1f}mm"
        elif f["cls"] == "bridge":
            if f.get("roof_width"):
                dims = f", roofed width ~{f['roof_width']:.1f}mm"
            else:
                fre = max((v.free_span or 0) for v in f["layers"])
                dims = f", free span {fre:.1f}mm"
        print(f"  [{f['severity']:9s}] {f['cls']:13s} "
              f"z {f['zlo']:.1f}-{f['zhi']:.1f} "
              f"({len(f['layers'])} layer(s)"
              f", @({v0.centroid[0]:.0f},{v0.centroid[1]:.0f}){dims})")
        for r in f.get("repairs", []):
            print(f"      -> {r}")
    print("severity: fail = will not print | judge = printable bridge,")
    print("rough downskin, human decides | tolerable = ledge within the")
    print(f"{LEDGE_MAX}mm allowance (Adam & Zimmer 2014).")
    if suggest:
        print("re-audit after applying any repair: fixes can create new "
              "overhangs (Adam & Zimmer 2014).")
        print(f"tip: critical z-heights print most accurately at integer "
              f"multiples of the layer height ({dz}mm) -- snap them "
              f"(Lieneke et al. 2016).")
    return False


def export_colored(mesh, violations, dz, out_path, halo=0.4):
    """Write a copy of the mesh with faces near violations painted red.

    A face is painted when its centroid lies within one layer of a
    violation's z and inside the violation region dilated by `halo` mm.
    Colour encodes severity: red = fail, orange = judge (printable
    bridge), gold = tolerable ledge. Everything else is light gray.
    Output format from extension (.ply recommended). Returns the number
    of painted faces.
    """
    from shapely.prepared import prep
    SEV_COLOR = {"fail": [220, 30, 30, 255],
                 "judge": [240, 140, 20, 255],
                 "tolerable": [230, 200, 40, 255]}
    mesh = mesh.copy()
    colors = np.tile(np.array([200, 200, 200, 255], dtype=np.uint8),
                     (len(mesh.faces), 1))
    centers = mesh.triangles_center
    cz = centers[:, 2]
    painted = np.zeros(len(mesh.faces), dtype=bool)
    # paint worst severity last so it wins overlaps
    order = sorted(violations,
                   key=lambda v: -SEVERITY_ORDER.get(v.severity or "fail", 0))
    for v in order:
        if v.geom is None or v.geom.is_empty:
            continue
        col = SEV_COLOR.get(v.severity or "fail", SEV_COLOR["fail"])
        zone = prep(v.geom.buffer(halo))
        for i in np.where(np.abs(cz - v.z) <= dz)[0]:
            if zone.contains(Point(centers[i][0], centers[i][1])):
                colors[i] = col
                painted[i] = True
    mesh.visual.face_colors = colors
    mesh.export(out_path)
    return int(painted.sum())


def _find_anchor(fgeom, zlo, slice_stack, max_angle):
    """Find the highest solid a 45-deg (max_angle) hull from `fgeom` at
    height `zlo` can descend onto. Returns (ax, ay, z') or None.

    Feasibility: planar clearance c from the feature to the slice region
    at z' must satisfy c <= (zlo - z') * tan(max_angle) -- the hull loses
    at most tan(angle) of lateral reach per unit drop.
    """
    from shapely.ops import nearest_points
    t = np.tan(np.radians(max_angle))
    best = None
    for z, region in slice_stack:
        if z >= zlo - 1e-6 or region is None or region.is_empty:
            continue
        try:
            c = fgeom.distance(region)
        except Exception:
            continue
        if c <= (zlo - z) * t + GROW_SLOP:
            if best is None or z > best[2]:
                p = nearest_points(fgeom, region)[1]
                best = (p.x, p.y, z)
    return best


def suggest_repairs(mesh, features, dz=0.4, max_angle=45.0):
    """Tier 3: attach concrete repair suggestions to each defect feature.

    Mutates each feature dict, adding a "repairs" list of human-readable,
    parametrized suggestions (with anchor coordinates where applicable).
    Returns the same features list. Every applied repair must be
    re-audited: fixes can create new overhangs (Adam & Zimmer 2014).
    """
    stack = [(z, r) for z, r in slices(mesh, dz)
             if r is not None and not r.is_empty]
    z_bed = mesh.bounds[0][2]
    for f in features:
        cls, sev = f["cls"], f["severity"]
        g, zlo = f["geom"], f["zlo"]
        cx, cy = (g.centroid.x, g.centroid.y) if g is not None else (0, 0)
        rep = []
        anchor = None
        if g is not None and sev == "fail":
            anchor = _find_anchor(g, zlo, stack, max_angle)
        if cls in ("island", "starts-in-air"):
            if anchor and anchor[2] > z_bed + dz:
                ax, ay, az = anchor
                rep.append(
                    f"ground it: hull/gusset from ({cx:.1f},{cy:.1f}) at "
                    f"z={zlo:.1f} down to the solid at ({ax:.1f},{ay:.1f}) "
                    f"z={az:.1f} -- a {max_angle:.0f} deg hull reaches it "
                    f"(drop {zlo - az:.1f}mm)")
            rep.append(
                f"ground it: pillar/cone straight down to the bed at "
                f"({cx:.1f},{cy:.1f}), height {zlo - z_bed:.1f}mm, "
                f"widening at {max_angle:.0f} deg toward the base")
            rep.append("or reorient so the feature grows from existing "
                       "material (Tier 4)")
        elif cls == "steep-growth":
            led = max((v.ledge or 0) for v in f["layers"])
            if sev == "tolerable":
                rep.append(
                    f"within the {LEDGE_MAX}mm ledge allowance -- accept, "
                    f"or tidy with a {led:.1f}mm 45 deg chamfer")
            else:
                rep.append(
                    f"morph the transition: the underside reaches "
                    f"{led:.1f}mm past support -- replace the flat with a "
                    f">= {max_angle:.0f} deg chamfer/cone at least "
                    f"{led:.1f}mm tall (the transition IS the shape)")
                if anchor:
                    ax, ay, az = anchor
                    rep.append(
                        f"or gusset down to the solid at "
                        f"({ax:.1f},{ay:.1f}) z={az:.1f}")
                rep.append(
                    "or keep the flat if functional (washer face, gland "
                    "seat) and orient it upward or give it minimal "
                    "painted support (DFAM_RULES #4)")
        elif cls == "bridge":
            b = g.bounds if g is not None else (0, 0, 0, 0)
            width = min(b[2] - b[0], b[3] - b[1])
            if sev == "judge":
                rep.append(
                    "accept as bridge: prints with rough downskin "
                    "(<= 10mm span); round holes <= 6mm stay round for "
                    "tapping integrity (DFAM_RULES #7)")
                rep.append(
                    f"or teardrop/diamond the opening -- apex adds "
                    f"~{width / 2:.1f}mm of height at {max_angle:.0f} deg")
            else:
                fre = max((v.free_span or 0) for v in f["layers"])
                rep.append(
                    f"span too long ({fre:.1f}mm free): teardrop/diamond "
                    f"the opening (apex ~{width / 2:.1f}mm at "
                    f"{max_angle:.0f} deg), or reorient the opening's "
                    f"axis vertical")
        f["repairs"] = rep
    return features


def main(argv=None):
    import argparse
    import signal
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # play nice with head/grep
    except (AttributeError, ValueError):
        pass                                            # Windows / non-main thread
    ap = argparse.ArgumentParser(
        description="Mechanical enforcement of the 45-degree rule on STL geometry.")
    ap.add_argument("stl")
    ap.add_argument("--angle", type=float, default=45.0)
    ap.add_argument("--dz", type=float, default=0.4)
    ap.add_argument("--ex", action="append", default=[],
                    help="zlo:zhi:rmax[:cx:cy] thread/helix exclusion "
                         "cylinder")
    ap.add_argument("--auto-ex", action="store_true",
                    help="auto-detect thread helices and exclude them "
                         "(no manual --ex needed)")
    ap.add_argument("--report", metavar="OUT.html", default=None,
                    help="write an interactive 3D HTML report "
                         "(open in any browser)")
    ap.add_argument("--export", metavar="OUT.ply", default=None,
                    help="write mesh with violating faces painted red")
    ap.add_argument("--suggest", action="store_true",
                    help="Tier 3: print parametrized repair suggestions")
    ap.add_argument("--warn-angle", type=float, default=None,
                    metavar="DEG",
                    help="also lint surfaces beyond this milder angle "
                         "(e.g. 30: prints, but degraded downskin)")
    ap.add_argument("--min-wall", type=float, default=None, metavar="MM",
                    help="also lint in-plane features thinner than this "
                         "(e.g. 0.8)")
    a = ap.parse_args(argv)
    ex = [tuple(map(float, e.split(":"))) for e in a.ex]
    ok = audit(a.stl, a.angle, a.dz, ex, export=a.export,
               suggest=a.suggest, warn_angle=a.warn_angle,
               min_wall=a.min_wall, auto_ex=a.auto_ex, report=a.report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
