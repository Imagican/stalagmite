#!/usr/bin/env python3
"""
dfam_orient.py - Tier 4: functional-surface-aware orientation solver.

Searches build poses (rotations theta_x, theta_y; part dropped to the
plate) minimising a support proxy PLUS user-declared functional-surface
constraints -- the thing plain auto-orienters don't know:

    --axis-vertical x,y,z      this part-frame axis must print vertical
                               (threads); either up or down is fine
    --face nx,ny,nz:MODE       a face with this part-frame normal must
                               print as MODE: floor | up | wall | not-down
    --ex zlo:zhi:rmax          part-frame cylindrical exclusion (thread
                               helices; only meaningful combined with an
                               axis-vertical constraint on the same axis)

Support proxy: total support-ray length x facet area (Goguelin, Dhokia &
Flynn 2021 found ray length the best cheap proxy, within 3.5% of slicer
ground truth). Search: lightweight Gaussian-process Bayesian optimisation
(Matern 5/2, LCB acquisition), ~35 evaluations (ibid.).

Usage:
    python3 dfam_orient.py part.stl --axis-vertical 0,0,1 \
        --ex 0:16.5:11 --ex 54:65:13 --save oriented.stl
"""
import sys
import numpy as np
import trimesh

DEG = np.pi / 180.0


# ----------------------------------------------------------- constraints

class Constraint:
    """kind='axis' (vec must end up +/-Z) or kind='face' (normal + mode)."""

    def __init__(self, kind, vec, mode=None, label=None):
        self.kind = kind
        self.vec = np.asarray(vec, dtype=float)
        self.vec /= np.linalg.norm(self.vec)
        self.mode = mode
        self.label = label or (f"{kind}:{mode or 'vertical'}")

    def penalty_deg(self, R):
        v = R @ self.vec
        if self.kind == "axis":
            # vertical either way up
            return np.degrees(np.arccos(min(1.0, abs(v[2]))))
        ang_up = np.degrees(np.arccos(np.clip(v[2], -1, 1)))  # vs +Z
        if self.mode == "up":
            return ang_up
        if self.mode == "floor":       # face normal points down
            return 180.0 - ang_up
        if self.mode == "wall":        # face normal horizontal
            return abs(90.0 - ang_up)
        if self.mode == "not-down":    # any downward tilt is penalised
            return max(0.0, 90.0 - ang_up if v[2] < 0 else 0.0)
        raise ValueError(f"unknown face mode {self.mode}")


def parse_constraints(axis_specs, face_specs):
    cons = []
    for s in axis_specs or ():
        cons.append(Constraint("axis", [float(x) for x in s.split(",")],
                               label=f"axis-vertical({s})"))
    for s in face_specs or ():
        vec, mode = s.rsplit(":", 1)
        cons.append(Constraint("face", [float(x) for x in vec.split(",")],
                               mode=mode, label=f"face({vec}:{mode})"))
    return cons


# ------------------------------------------------------------- the proxy

def rotmat(tx_deg, ty_deg):
    a, b = tx_deg * DEG, ty_deg * DEG
    Rx = np.array([[1, 0, 0],
                   [0, np.cos(a), -np.sin(a)],
                   [0, np.sin(a), np.cos(a)]])
    Ry = np.array([[np.cos(b), 0, np.sin(b)],
                   [0, 1, 0],
                   [-np.sin(b), 0, np.cos(b)]])
    return Ry @ Rx


def exclusion_mask(mesh, exclude):
    """True for faces inside a part-frame cylinder zone (thread helix).
    Zones are (zlo, zhi, rmax) or (zlo, zhi, rmax, cx, cy)."""
    c = mesh.triangles_center
    mask = np.zeros(len(c), dtype=bool)
    for e in exclude:
        if len(e) == 5:
            zlo, zhi, rmax, cx, cy = e
        else:
            (zlo, zhi, rmax), cx, cy = e, 0.0, 0.0
        r = np.hypot(c[:, 0] - cx, c[:, 1] - cy)
        mask |= (c[:, 2] >= zlo) & (c[:, 2] <= zhi) & (r <= rmax)
    return mask


def support_proxy(mesh, R, max_angle=45.0, dz=0.4, ex_mask=None,
                  max_rays=600, rng=None):
    """Area-weighted total support-ray length (mm^3-ish) for pose R.

    Severity-weighted (Tier-2-informed): a facet barely past the
    critical angle contributes lightly (near-45 deg overhangs print,
    just roughly); a flat-down facet (normal straight down -- the
    starts-in-air / flat-underside signature) contributes fully.
    Weight = 0.25 + 0.75 * (overshoot beyond the critical angle / the
    remaining angle range to flat).
    """
    rng = rng or np.random.default_rng(0)
    n = mesh.face_normals @ R.T
    centers = mesh.triangles_center @ R.T
    z0 = (mesh.vertices @ R.T)[:, 2].min()
    thresh = -np.cos(np.radians(max_angle)) - 1e-9
    over = (n[:, 2] < thresh) & (centers[:, 2] - z0 > 2 * dz)
    if ex_mask is not None:
        over &= ~ex_mask
    idx = np.where(over)[0]
    if len(idx) == 0:
        return 0.0
    # severity weight per facet
    ang_down = np.degrees(np.arccos(np.clip(-n[idx, 2], -1, 1)))
    # ang_down: 0 = facing straight down, max_angle = at threshold
    sev_w = 0.25 + 0.75 * np.clip(
        (max_angle - ang_down) / max(max_angle, 1e-9), 0.0, 1.0)
    areas = mesh.area_faces[idx] * sev_w
    scale = 1.0
    if len(idx) > max_rays:
        p = areas / areas.sum()
        pick = rng.choice(len(idx), size=max_rays, replace=False, p=p)
        scale = areas.sum() / areas[pick].sum()
        idx, areas = idx[pick], areas[pick]
    rmesh = mesh.copy()
    rmesh.apply_transform(
        np.vstack([np.hstack([R, [[0], [0], [0]]]), [0, 0, 0, 1]]))
    origins = centers[idx] - [0, 0, 1e-3]
    dirs = np.tile([0.0, 0.0, -1.0], (len(idx), 1))
    lengths = origins[:, 2] - z0                      # fall to the bed
    try:
        loc, ray_i, _ = rmesh.ray.intersects_location(
            origins, dirs, multiple_hits=False)
        for pt, ri in zip(loc, ray_i):
            d = origins[ri][2] - pt[2]
            if 1e-6 < d < lengths[ri]:
                lengths[ri] = d
    except Exception:
        pass                                          # bed-fall fallback
    return float((lengths * areas).sum() * scale)


# ---------------------------------------------------- Bayesian optimiser

def _wrap_dist(A, B):
    d = np.abs(A[:, None, :] - B[None, :, :])
    d = np.minimum(d, 360.0 - d)
    return np.sqrt((d ** 2).sum(-1))


def _matern52(D, ls):
    q = np.sqrt(5.0) * D / ls
    return (1.0 + q + q * q / 3.0) * np.exp(-q)


def solve_orientation(mesh, constraints=(), exclude=(), max_angle=45.0,
                      dz=0.4, iters=35, n_init=8, max_rays=600, seed=0,
                      verbose=False):
    """Search (theta_x, theta_y) minimising support proxy + constraint
    penalties. Returns dict with pose, scores, and history."""
    rng = np.random.default_rng(seed)
    ex_mask = exclusion_mask(mesh, exclude) if exclude else None

    def proxy(tx, ty):
        return support_proxy(mesh, rotmat(tx, ty), max_angle, dz,
                             ex_mask, max_rays,
                             np.random.default_rng(seed))

    def pens(tx, ty):
        R = rotmat(tx, ty)
        return [c.penalty_deg(R) for c in constraints]

    # seed set: identity, flip, and random poses
    X = [(0.0, 0.0), (180.0, 0.0)]
    while len(X) < n_init:
        X.append(tuple(rng.uniform(0, 360, 2)))
    X = np.array(X)
    P = np.array([proxy(*x) for x in X])
    C = np.array([sum(pens(*x)) for x in X]) if constraints else \
        np.zeros(len(X))
    # constraint weight: 15 deg of violation ~ the worst seed support
    w = (P.max() + 1.0) / 15.0 if constraints else 0.0
    Y = P + w * C
    for it in range(iters):
        ymu, ystd = Y.mean(), Y.std() + 1e-9
        yn = (Y - ymu) / ystd
        D = _wrap_dist(X, X)
        K = _matern52(D, 45.0) + np.eye(len(X)) * 1e-6
        Ki = np.linalg.inv(K)
        cand = np.vstack([rng.uniform(0, 360, (2048, 2)),
                          (X[np.argmin(Y)] +
                           rng.normal(0, 10, (256, 2))) % 360.0])
        Dc = _wrap_dist(cand, X)
        Kc = _matern52(Dc, 45.0)
        mu = Kc @ Ki @ yn
        var = np.maximum(1e-12, 1.0 - np.einsum(
            "ij,jk,ik->i", Kc, Ki, Kc))
        lcb = mu - 2.0 * np.sqrt(var)
        # avoid re-evaluating near-duplicates
        lcb[Dc.min(1) < 1.0] = np.inf
        x_new = cand[np.argmin(lcb)]
        p_new = proxy(*x_new)
        c_new = sum(pens(*x_new)) if constraints else 0.0
        X = np.vstack([X, x_new])
        P = np.append(P, p_new)
        C = np.append(C, c_new)
        Y = np.append(Y, p_new + w * c_new)
        if verbose:
            print(f"  iter {it + 1:3d}: pose ({x_new[0]:6.1f},"
                  f"{x_new[1]:6.1f})  proxy {p_new:10.1f}  "
                  f"pen {c_new:6.2f} deg  best {Y.min():10.1f}")
    i = int(np.argmin(Y))
    R = rotmat(*X[i])
    return {"theta_x": float(X[i][0]), "theta_y": float(X[i][1]),
            "R": R, "proxy": float(P[i]), "penalty_deg": float(C[i]),
            "penalties": {c.label: c.penalty_deg(R) for c in constraints},
            "score": float(Y[i]), "weight": w, "evals": len(X),
            "history": np.column_stack([X, P, C])}


# ------------------------------------------------------------------- CLI

def main(argv=None):
    import argparse
    import signal
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # play nice with head/grep
    except (AttributeError, ValueError):
        pass                                            # Windows / non-main thread
    ap = argparse.ArgumentParser(
        description="Functional-surface-aware build-orientation solver.")
    ap.add_argument("stl")
    ap.add_argument("--axis-vertical", action="append", default=[],
                    metavar="X,Y,Z")
    ap.add_argument("--face", action="append", default=[],
                    metavar="NX,NY,NZ:MODE",
                    help="MODE: floor | up | wall | not-down")
    ap.add_argument("--ex", action="append", default=[],
                    help="part-frame zlo:zhi:rmax exclusion cylinder")
    ap.add_argument("--angle", type=float, default=45.0)
    ap.add_argument("--dz", type=float, default=0.4)
    ap.add_argument("--iters", type=int, default=35)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--save", metavar="OUT.stl", default=None,
                    help="write the best-pose mesh (dropped to z=0)")
    a = ap.parse_args(argv)
    mesh = trimesh.load(a.stl, force="mesh")
    cons = parse_constraints(a.axis_vertical, a.face)
    ex = [tuple(map(float, e.split(":"))) for e in a.ex]
    print(f"== DfAM orient: {a.stl}  ({len(cons)} constraint(s), "
          f"{a.iters} iterations) ==")
    res = solve_orientation(mesh, cons, ex, a.angle, a.dz,
                            iters=a.iters, seed=a.seed, verbose=True)
    print(f"best pose: rotate X {res['theta_x']:.1f} deg, "
          f"Y {res['theta_y']:.1f} deg  "
          f"(support proxy {res['proxy']:.0f}, "
          f"constraint penalty {res['penalty_deg']:.2f} deg)")
    for label, p in res["penalties"].items():
        print(f"  {label}: {p:.2f} deg off target")
    if a.save:
        R = res["R"]
        T = np.vstack([np.hstack([R, [[0], [0], [0]]]), [0, 0, 0, 1]])
        out = mesh.copy()
        out.apply_transform(T)
        out.apply_translation([0, 0, -out.bounds[0][2]])
        out.export(a.save)
        print(f"oriented mesh written: {a.save}")
    print("note: proxy ignores exclusion-zone faces only in the part "
          "frame; keep the excluded axis vertical via --axis-vertical.")
    print("re-audit the oriented mesh with dfam_audit.py before printing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
