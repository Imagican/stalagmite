#!/usr/bin/env python3
"""
dfam_intent.py - design-intent tags: keep-clear zones.

An exclusion zone (--ex) says "ignore violations here -- I know better"
(thread helices). A keep-clear zone (--keep) says the opposite: "this
region is FUNCTIONAL -- a seal face, a bore, a mating surface -- and no
generated repair may touch it."

Zones are cylinders in part frame, same syntax as --ex:

    --keep zlo:zhi:rmax            (centred on the z-axis)
    --keep zlo:zhi:rmax:cx:cy      (centred at (cx, cy))

What they change:

  * the audit annotates any defect feature that overlaps a keep-clear
    zone (`intent_hits`) -- you learn a defect sits ON a functional
    surface before deciding how to fix it;
  * stalagmite-fix refuses to weld repair geometry into a zone: anchor
    landings inside a zone are skipped during walk-down, and any built
    body that still pokes into a zone is dropped with a note. If that
    leaves a fail unfixed, the ordinary verdict machinery reports it
    honestly (PARTIAL / NOT_IMPROVED) -- intent never silently degrades
    the audit's truthfulness.

CadQuery on-ramp: stalagmite.keep_zone(part.faces(">Z"), pad=1) turns a
named-face selection into a zone tuple, so intent can live next to the
design instead of in CLI flags.
"""
import numpy as np
from shapely.geometry import Point

from dfam_audit import _ex_parts


def parse_keep(specs):
    """['zlo:zhi:rmax[:cx:cy]', ...] -> [(zlo, zhi, rmax[, cx, cy]), ...]"""
    zones = []
    for s in specs or ():
        try:
            parts = tuple(float(x) for x in str(s).split(":"))
        except ValueError:
            raise ValueError(
                f"keep-clear zone {s!r}: expected numbers as "
                f"zlo:zhi:rmax[:cx:cy]")
        if len(parts) not in (3, 5):
            raise ValueError(
                f"keep-clear zone {s!r}: expected zlo:zhi:rmax[:cx:cy]")
        zlo, zhi, rmax = parts[:3]
        if zhi <= zlo or rmax <= 0:
            raise ValueError(f"keep-clear zone {s!r}: needs zhi > zlo "
                             f"and rmax > 0")
        zones.append(parts)
    return zones


def zone_disc(zone):
    """The zone's footprint as a shapely disc."""
    zlo, zhi, rmax, cx, cy = _ex_parts(zone)
    return Point(cx, cy).buffer(rmax, 64)


def geom_hits(geom, zlo, zhi, zones):
    """Indices of zones a (geometry, z-range) overlaps."""
    hits = []
    if geom is None or getattr(geom, "is_empty", True):
        return hits
    for i, zn in enumerate(zones or ()):
        klo, khi, rmax, cx, cy = _ex_parts(zn)
        if zhi < klo or zlo > khi:
            continue
        try:
            if geom.distance(Point(cx, cy)) <= rmax:
                hits.append(i)
        except Exception:
            continue
    return hits


def annotate_features(features, zones):
    """Set f['intent_hits'] on every feature; returns count annotated."""
    n = 0
    for f in features:
        f["intent_hits"] = geom_hits(f.get("geom"), f["zlo"], f["zhi"],
                                     zones)
        n += bool(f["intent_hits"])
    return n


def body_blocked(body, zones, shrink=0.05):
    """True if any vertex of a repair body lies inside a keep-clear
    zone. `shrink` (mm) forgives kiss-contact at the zone boundary."""
    if not zones:
        return False
    V = np.asarray(body.vertices if hasattr(body, "vertices") else body,
                   dtype=float)
    if V.size == 0:
        return False
    for zn in zones:
        zlo, zhi, rmax, cx, cy = _ex_parts(zn)
        inz = (V[:, 2] >= zlo - 1e-9) & (V[:, 2] <= zhi + 1e-9)
        if not inz.any():
            continue
        r = np.hypot(V[inz, 0] - cx, V[inz, 1] - cy)
        if (r < rmax - shrink).any():
            return True
    return False


def zone_from_bounds(bounds, pad=1.0):
    """Enclosing keep-clear cylinder for an AABB ((min xyz), (max xyz))."""
    (x0, y0, z0), (x1, y1, z1) = bounds
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    rmax = float(np.hypot(x1 - x0, y1 - y0) / 2.0 + pad)
    return (float(z0 - pad), float(z1 + pad), rmax,
            float(cx), float(cy))


def zone_label(zone):
    zlo, zhi, rmax, cx, cy = _ex_parts(zone)
    return f"z {zlo:g}-{zhi:g} r<={rmax:g} @({cx:g},{cy:g})"
