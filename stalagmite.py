#!/usr/bin/env python3
"""
stalagmite - public Python API.

    import stalagmite
    result = stalagmite.check(part)          # part = CadQuery obj, STL path,
    print(result.status)                     #        trimesh, or (verts,faces)
    if result.failed:
        result.write_report("audit.html")

The point of this module is a one-call audit that drops into any Python
CAD workflow -- especially CadQuery, whose models are audited directly in
memory with no STL round-trip. Everything here is a thin, friendly facade
over the tested internals (dfam_audit / dfam_report / dfam_profiles /
dfam_orient / dfam_diff).
"""
from dataclasses import dataclass, field

import numpy as np
import trimesh

import dfam_audit as _audit
import dfam_profiles as _profiles
from dfam_audit import (audit_mesh, aggregate, suggest_repairs,
                        overall_status, load_mesh, sanitize_mesh,
                        mesh_health, detect_helix_zones, slice_region,
                        STATUS_BLURB, STATUS_EXIT)
from dfam_report import write_report, render_report
from dfam_profiles import list_profiles

try:                                   # optional -- only if installed
    from dfam_orient import solve_orientation
except Exception:                      # pragma: no cover
    solve_orientation = None
from dfam_diff import diff_audits

__all__ = ["check", "fix", "autofix", "keep_zone", "to_mesh",
           "AuditResult", "profile", "list_profiles", "diff_audits",
           "solve_orientation", "write_report"]


def fix(obj, profile=None, exclude=(), auto_ex=False, height=None,
        easing=1.0, flare=1.0, keep=()):
    """Stage B: apply generated repairs to a part and verify by re-audit.

    Returns a dfam_fix.FixResult: .verdict (NOTHING_TO_FIX / VERIFIED /
    PARTIAL / NOT_IMPROVED), .status_before/.status_after, .mesh_fixed,
    .write(path), .to_dict(). The never-worse guarantee applies:
    .ok_to_write is False when the fix did not improve the audit.

    `keep` = design-intent keep-clear zones (tuples or keep_zone()
    results): no repair body may touch them.
    """
    from dfam_fix import apply_fixes
    if isinstance(profile, _profiles.ResolvedProfile):
        prof = profile
    else:
        prof = _profiles.resolve(profile if isinstance(profile, str)
                                 else None)
    return apply_fixes(to_mesh(obj), prof, exclude, auto_ex,
                       height, easing, flare, keep=keep)


def keep_zone(obj, pad=1.0):
    """Design-intent on-ramp: turn a geometric selection into a
    keep-clear cylinder zone (zlo, zhi, rmax, cx, cy) for check(keep=)
    / fix(keep=) / --keep.

    Accepts a CadQuery face/edge selection (e.g. part.faces(">Z") --
    intent lives next to the design), a trimesh, an (n, 3) point array,
    or an explicit ((min xyz), (max xyz)) bounds pair. `pad` (mm) grows
    the zone so kiss-contact still counts as touching.
    """
    from dfam_intent import zone_from_bounds
    if _looks_like_cadquery(obj):
        shapes = obj.vals() if hasattr(obj, "vals") else [obj]
        boxes = [s.BoundingBox() for s in shapes
                 if hasattr(s, "BoundingBox")]
        if not boxes:
            raise ValueError("keep_zone: CadQuery selection is empty")
        lo = (min(b.xmin for b in boxes), min(b.ymin for b in boxes),
              min(b.zmin for b in boxes))
        hi = (max(b.xmax for b in boxes), max(b.ymax for b in boxes),
              max(b.zmax for b in boxes))
        return zone_from_bounds((lo, hi), pad)
    if isinstance(obj, trimesh.Trimesh):
        return zone_from_bounds(obj.bounds, pad)
    arr = np.asarray(obj, dtype=float)
    if arr.ndim == 2 and arr.shape[1] == 3 and len(arr) >= 1:
        return zone_from_bounds((arr.min(axis=0), arr.max(axis=0)), pad)
    if arr.shape == (2, 3):
        return zone_from_bounds((arr[0], arr[1]), pad)
    raise TypeError("keep_zone expects a CadQuery selection, a trimesh, "
                    "(n,3) points, or ((min xyz),(max xyz)) bounds")


def autofix(build, params, nominal=None, profile=None, exclude=(),
            auto_ex=False, budget=32, seed=0, verbose=False):
    """Stage C: fix the DESIGN, not the mesh. Search `params` (a dict
    {name: (lo, hi)}) for the smallest move away from `nominal` that
    makes build(**params) audit printable -- every candidate is rebuilt
    from source and fully audited, and the winner is rebuilt once more
    and proven before it is returned.

    build : callable(**params) returning anything check() accepts
            (CadQuery object, trimesh, (vertices, faces), or a path)

    Returns a dfam_autofix.AutofixResult: .verdict (NOTHING_TO_DO /
    FOUND / NONE_FOUND), .params_best, .moves, .distance, .mesh_best,
    .write(path), .to_dict(). Never-worse guarantee: .ok_to_write is
    False on NONE_FOUND.
    """
    from dfam_autofix import autofix as _autofix
    if isinstance(profile, _profiles.ResolvedProfile):
        prof = profile
    else:
        prof = _profiles.resolve(profile if isinstance(profile, str)
                                 else None)
    say = print if verbose else (lambda *a: None)
    return _autofix(build, params, nominal, prof, exclude, auto_ex,
                    budget, seed, say)


def profile(name=None, path=None, **overrides):
    """Resolve a process profile (see dfam_profiles). Pass a built-in
    name, a JSON file path, and/or threshold overrides."""
    return _profiles.resolve(name, path, **overrides)


# ------------------------------------------------------ input conversion

def _looks_like_cadquery(obj):
    mod = type(obj).__module__ or ""
    return mod.startswith("cadquery") or (
        hasattr(obj, "val") and hasattr(obj, "objects")
        and hasattr(obj, "vals"))


def _cq_to_mesh(obj, tol=0.1, ang_tol=0.3):
    """Tessellate a CadQuery Workplane/Shape into a trimesh, no file
    round-trip. Falls back to CadQuery's STL exporter if needed."""
    # shapes to tessellate
    if hasattr(obj, "vals"):
        shapes = [s for s in obj.vals() if hasattr(s, "tessellate")]
    elif hasattr(obj, "val"):
        shapes = [obj.val()]
    elif hasattr(obj, "tessellate"):
        shapes = [obj]
    else:
        shapes = []
    verts, faces, off = [], [], 0
    for s in shapes:
        try:
            vs, ts = s.tessellate(tol, ang_tol)
        except TypeError:
            vs, ts = s.tessellate(tol)
        for v in vs:
            verts.append((v.x, v.y, v.z))
        for t in ts:
            faces.append((t[0] + off, t[1] + off, t[2] + off))
        off = len(verts)
    if verts and faces:
        m = trimesh.Trimesh(vertices=np.asarray(verts, dtype=float),
                            faces=np.asarray(faces, dtype=np.int64),
                            process=False)
        return sanitize_mesh(m)
    # fallback: export STL and load
    import os
    import tempfile
    import cadquery as cq
    f = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    f.close()
    try:
        cq.exporters.export(obj, f.name)
        return load_mesh(f.name)
    finally:
        try:
            os.unlink(f.name)
        except OSError:
            pass


def to_mesh(obj):
    """Coerce any supported input to a sanitized trimesh.Trimesh:
    a trimesh, an STL/OBJ/PLY/3MF path, a CadQuery Workplane/Shape, or a
    (vertices, faces) pair."""
    from dfam_audit import _require_usable as _usable
    if isinstance(obj, trimesh.Trimesh):
        return _usable(sanitize_mesh(obj), "trimesh")
    if isinstance(obj, trimesh.Scene):
        return _usable(load_mesh_scene(obj), "scene")
    if isinstance(obj, str):
        return load_mesh(obj)
    from dfam_audit import _require_usable
    if isinstance(obj, (tuple, list)) and len(obj) == 2:
        V, F = obj
        V = np.asarray(V, dtype=float).reshape(-1, 3)
        F = np.asarray(F, dtype=np.int64).reshape(-1, 3)
        if len(V) == 0 or len(F) == 0:
            raise ValueError("empty (vertices, faces) input")
        return _require_usable(sanitize_mesh(trimesh.Trimesh(
            vertices=V, faces=F, process=False)), "(vertices, faces)")
    if _looks_like_cadquery(obj):
        return _require_usable(_cq_to_mesh(obj), "CadQuery object")
    raise TypeError(
        "stalagmite.check expects a CadQuery object, an STL/mesh file "
        f"path, a trimesh, or (vertices, faces) -- got {type(obj)!r}")


def load_mesh_scene(scene):
    g = trimesh.util.concatenate(tuple(scene.geometry.values()))
    return sanitize_mesh(g)


# --------------------------------------------------------------- result

@dataclass
class AuditResult:
    """The outcome of stalagmite.check(). `status` is the four-state
    string; `printable` is True unless it FAILs."""
    status: str
    mesh: object
    violations: list
    features: list
    bed_area: float
    profile_name: str
    health: list = field(default_factory=list)
    exclude: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    auto_zones: list = field(default_factory=list)
    dz: float = 0.4
    angle: float = 45.0
    ledge_max: float = 1.8
    bridge_max: float = 10.0
    min_wall: float = None
    warn_angle: float = None
    keep: list = field(default_factory=list)

    @property
    def printable(self):
        return self.status != "FAIL"

    @property
    def failed(self):
        return self.status == "FAIL"

    @property
    def exit_code(self):
        return STATUS_EXIT.get(self.status, 1)

    def count(self, severity):
        return sum(1 for f in self.features
                   if f["severity"] == severity)

    @property
    def fails(self):
        return self.count("fail")

    def defects(self):
        """Human-readable one-liners for each defect feature."""
        out = []
        for f in self.features:
            c = f["geom"].centroid if f.get("geom") is not None else None
            loc = f" @({c.x:.0f},{c.y:.0f})" if c is not None else ""
            out.append(f"[{f['severity']}] {f['cls']} "
                       f"z{f['zlo']:.1f}-{f['zhi']:.1f}{loc}")
        return out

    def to_dict(self):
        """The same JSON-serialisable shape as the CLI's --json output."""
        return _audit.result_dict(
            self.profile_name, self.status, self.features, self.bed_area,
            self.profile_name,
            {"angle": self.angle, "dz": self.dz,
             "ledge_max": self.ledge_max, "bridge_max": self.bridge_max,
             "min_wall": self.min_wall, "warn_angle": self.warn_angle},
            self.health, self.exclude, self.auto_zones, self.keep)

    def to_json(self, **kw):
        import json
        return json.dumps(self.to_dict(), **kw)

    def write_report(self, path):
        write_report(self.mesh, self.violations, self.features, path,
                     meta={"part": path, "angle": self.angle, "dz": self.dz,
                           "bed": self.bed_area, "status": self.status,
                           "profile": self.profile_name,
                           "health": self.health,
                           "zones": [list(z) for z in self.exclude]})
        return path

    def __repr__(self):
        return (f"<AuditResult {self.status}: {self.fails} fail, "
                f"{self.count('judge')} judge, "
                f"{self.count('tolerable')} tolerable "
                f"({len(self.features)} feature(s))>")

    def __str__(self):
        return f"{self.status} -- {STATUS_BLURB.get(self.status, '')}"


# --------------------------------------------------------------- check

def check(obj, profile=None, exclude=(), auto_ex=False,
          angle=None, dz=None, suggest=True, lint=True, keep=()):
    """Audit a part and return an AuditResult (does not print).

    obj      : CadQuery object, STL/mesh path, trimesh, or (verts, faces)
    profile  : profile name, a ResolvedProfile, or None (generic-fdm)
    auto_ex  : auto-detect & exclude thread helices
    angle/dz : override the profile's angle / layer height
    suggest  : attach repair suggestions to features
    lint     : run the profile's surface / thin-wall notes
    keep     : design-intent keep-clear zones (see keep_zone()); defects
               touching one get feature['intent_hits'] set
    """
    if isinstance(profile, _profiles.ResolvedProfile):
        prof = profile
    else:
        prof = _profiles.resolve(
            profile if isinstance(profile, str) else None,
            angle=angle, dz=dz)
    mesh = to_mesh(obj)
    exclude = list(exclude)
    auto_zones = []
    if auto_ex:
        _, p1 = audit_mesh(mesh, prof.angle, prof.dz, exclude,
                           prof.ledge_max, prof.bridge_max)
        auto_zones = detect_helix_zones(p1, prof.dz)
        for zn in auto_zones:
            exclude.append((zn["zlo"], zn["zhi"], zn["rmax"],
                            zn["cx"], zn["cy"]))
    warnings = []
    bed, viol = audit_mesh(
        mesh, prof.angle, prof.dz, exclude, prof.ledge_max, prof.bridge_max,
        warn_angle=prof.warn_angle if lint else None,
        min_wall=prof.min_wall if lint else None, warnings_out=warnings)
    feats = aggregate(viol, prof.dz)
    keep = list(keep)
    if keep:
        from dfam_intent import annotate_features
        annotate_features(feats, keep)
    if suggest:
        suggest_repairs(mesh, feats, prof.dz, prof.angle)
    status = overall_status(feats, warnings)
    return AuditResult(status=status, mesh=mesh, violations=viol,
                       features=feats, bed_area=bed or 0.0,
                       profile_name=prof.name,
                       health=mesh_health(mesh, prof.dz),
                       exclude=exclude, warnings=warnings,
                       auto_zones=auto_zones, dz=prof.dz, angle=prof.angle,
                       ledge_max=prof.ledge_max, bridge_max=prof.bridge_max,
                       min_wall=prof.min_wall, warn_angle=prof.warn_angle,
                       keep=keep)
