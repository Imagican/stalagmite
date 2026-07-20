#!/usr/bin/env python3
"""
dfam_diff.py - compare two revisions of a part and report what a design
change actually did: which defects were RESOLVED, which PERSIST, and
whether any were INTRODUCED.

This is the v2->v7 iteration loop as a single command -- the thing the
whole toolkit was born from. "I morphed the boss; did it fix the
overhang without breaking anything else?"

    stalagmite-diff old.stl new.stl [--auto-ex] [--profile ...]

Both revisions are audited under the same profile and their defect
features matched by class and position (same coordinate frame assumed --
these are iterations of one part, not re-orientations). Exit code is 1
if the change REGRESSED (introduced or worsened a failure), else 0.
"""
import sys
import numpy as np
import trimesh

from dfam_audit import (audit_mesh, aggregate, detect_helix_zones,
                        overall_status, SEVERITY_ORDER, _ex_parts, load_mesh)


def _centroid(f):
    g = f.get("geom")
    if g is not None and not g.is_empty:
        return (g.centroid.x, g.centroid.y)
    v = max(f["layers"], key=lambda v: v.area)
    return v.centroid


def _radius(f):
    g = f.get("geom")
    if g is not None and not g.is_empty:
        b = g.bounds
        return max(b[2] - b[0], b[3] - b[1], f["zhi"] - f["zlo"], 3.0) / 2
    return 3.0


def _group(cls):
    # steep-growth and bridge are the same physical family here
    return "growth" if cls in ("steep-growth", "bridge") else cls


def _z_overlap(a, b, tol=1.2):
    return not (a["zhi"] < b["zlo"] - tol or b["zhi"] < a["zlo"] - tol)


def _match(old_feats, new_feats):
    """Greedy nearest match by class-group, plan position and z overlap.
    Returns (resolved_idx, persist_pairs, introduced_idx)."""
    free = list(range(len(new_feats)))
    persist, resolved = [], []
    for i, of in enumerate(old_feats):
        oc, orad = _centroid(of), _radius(of)
        best, bestd = None, float("inf")
        for j in free:
            nf = new_feats[j]
            if _group(of["cls"]) != _group(nf["cls"]):
                continue
            if not _z_overlap(of, nf):
                continue
            nc = _centroid(nf)
            d = np.hypot(oc[0] - nc[0], oc[1] - nc[1])
            tol = max(orad, _radius(nf), 4.0)
            if d <= tol and d < bestd:
                bestd, best = d, j
        if best is not None:
            free.remove(best)
            persist.append((i, best))
        else:
            resolved.append(i)
    return resolved, persist, free


def _sev_rank(s):
    return SEVERITY_ORDER.get(s, 0)   # lower = more severe


def _label(f):
    c = _centroid(f)
    dims = ""
    if f["cls"] == "steep-growth":
        led = max((v.ledge or 0) for v in f["layers"])
        dims = f", ledge {led:.1f}mm"
    elif f["cls"] == "bridge" and f.get("roof_width"):
        dims = f", roofed ~{f['roof_width']:.1f}mm"
    return (f"{f['cls']} z {f['zlo']:.1f}-{f['zhi']:.1f} "
            f"@({c[0]:.0f},{c[1]:.0f}){dims}")


def _audit_one(path, profile, exclude, auto_ex):
    m = load_mesh(path)
    ex = list(exclude)
    if auto_ex:
        _, p1 = audit_mesh(m, profile.angle, profile.dz, ex,
                           profile.ledge_max, profile.bridge_max)
        for zn in detect_helix_zones(p1, profile.dz):
            ex.append((zn["zlo"], zn["zhi"], zn["rmax"],
                       zn["cx"], zn["cy"]))
    _, v = audit_mesh(m, profile.angle, profile.dz, ex,
                      profile.ledge_max, profile.bridge_max)
    feats = aggregate(v, profile.dz)
    return feats, overall_status(feats)


def diff_audits(old_path, new_path, profile=None, exclude=(), auto_ex=False):
    """Compare two revisions. Returns a structured result dict."""
    if profile is None:
        import dfam_profiles
        profile = dfam_profiles.resolve()
    old_f, old_status = _audit_one(old_path, profile, exclude, auto_ex)
    new_f, new_status = _audit_one(new_path, profile, exclude, auto_ex)
    resolved, persist, introduced = _match(old_f, new_f)

    worsened, improved_sev = [], []
    for oi, nj in persist:
        so, sn = old_f[oi]["severity"], new_f[nj]["severity"]
        if _sev_rank(sn) < _sev_rank(so):
            worsened.append((oi, nj))
        elif _sev_rank(sn) > _sev_rank(so):
            improved_sev.append((oi, nj))

    new_fails = [j for j in introduced if new_f[j]["severity"] == "fail"]
    regressed = bool(new_fails) or bool(worsened)
    if regressed:
        verdict = "REGRESSED"
    elif resolved or improved_sev:
        verdict = "IMPROVED"
    elif introduced:
        verdict = "CHANGED"
    else:
        verdict = "UNCHANGED"

    return {
        "profile": profile, "old_status": old_status,
        "new_status": new_status, "verdict": verdict,
        "old_f": old_f, "new_f": new_f,
        "resolved": resolved, "persist": persist,
        "introduced": introduced, "worsened": worsened,
        "improved_sev": improved_sev, "regressed": regressed,
    }


def print_diff(r, old_path, new_path):
    p = r["profile"]
    print("== stalagmite diff ==")
    print(f"old: {old_path}")
    print(f"new: {new_path}")
    print(f"   {p.summary_line()}")
    print(f"old STATUS: {r['old_status']}   ->   "
          f"new STATUS: {r['new_status']}")
    print("changes:")
    for i in r["resolved"]:
        print(f"  RESOLVED   {_label(r['old_f'][i])}  "
              f"[was {r['old_f'][i]['severity']}]")
    for oi, nj in r["persist"]:
        so, sn = r["old_f"][oi]["severity"], r["new_f"][nj]["severity"]
        note = (f"{so} -> {sn}"
                + ("  WORSE" if _sev_rank(sn) < _sev_rank(so)
                   else "  better" if _sev_rank(sn) > _sev_rank(so) else ""))
        print(f"  PERSISTS   {_label(r['new_f'][nj])}  [{note}]")
    for j in r["introduced"]:
        tag = "NEW-FAIL" if r["new_f"][j]["severity"] == "fail" else "NEW"
        print(f"  {tag:9s}  {_label(r['new_f'][j])}  "
              f"[{r['new_f'][j]['severity']}]")
    if not (r["resolved"] or r["persist"] or r["introduced"]):
        print("  (no defect features in either revision)")
    print(f"summary: {len(r['resolved'])} resolved, "
          f"{len(r['persist'])} persist, {len(r['introduced'])} new"
          + (f", {len(r['worsened'])} worsened" if r["worsened"] else ""))
    blurb = {
        "IMPROVED": "the change fixed defects without introducing failures.",
        "REGRESSED": "the change introduced or worsened a failure -- "
                     "re-check the edit.",
        "CHANGED": "defects changed but no clear improvement or regression.",
        "UNCHANGED": "no change in the defect set.",
    }[r["verdict"]]
    print(f"DIFF: {r['verdict']} -- {blurb}")


def main(argv=None):
    import argparse
    import signal
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(
        description="Compare two revisions of a part: resolved / persists "
                    "/ introduced defects.")
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--profile-file", default=None)
    ap.add_argument("--auto-ex", action="store_true")
    ap.add_argument("--ex", action="append", default=[])
    ap.add_argument("--angle", type=float, default=None)
    ap.add_argument("--dz", type=float, default=None)
    a = ap.parse_args(argv)
    import dfam_profiles
    try:
        profile = dfam_profiles.resolve(a.profile, a.profile_file,
                                        angle=a.angle, dz=a.dz)
    except (KeyError, OSError, ValueError) as e:
        ap.error(str(e))
    ex = [tuple(map(float, e.split(":"))) for e in a.ex]
    r = diff_audits(a.old, a.new, profile, ex, a.auto_ex)
    print_diff(r, a.old, a.new)
    return 1 if r["regressed"] else 0


if __name__ == "__main__":
    sys.exit(main())
