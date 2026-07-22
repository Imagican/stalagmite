#!/usr/bin/env python3
"""
dfam_autofix.py - Stage C of "doing": fix the DESIGN, not the mesh.

    stalagmite-autofix my_design.py -o best.stl

Stage B (stalagmite-fix) welds repair geometry onto a finished mesh.
Stage C goes one level up: you hand it your parametric build function
and the knobs you are willing to move, and it searches the parameter
space for the SMALLEST move away from your nominal design that makes
the part printable -- each candidate is rebuilt from source and put
through the full physics audit. The winner is rebuilt once more and
re-audited before anything is written, so the answer is proven, never
asserted.

A design file is plain Python:

    PARAMS  = {"shelf_len": (2.0, 10.0), "gusset": (0.0, 1.0)}
    NOMINAL = {"shelf_len": 10.0, "gusset": 0.0}   # optional

    def build(shelf_len, gusset):
        ...return anything stalagmite.check accepts
        (CadQuery object, trimesh, or (vertices, faces))

Search: the same lightweight numpy-only Gaussian-process Bayesian
optimisation used by stalagmite-orient (Matern 5/2, LCB acquisition),
over the unit-normalised parameter box. The objective is audit badness
(fails dominate) plus a small distance-from-nominal term, so among
printable designs the search prefers the one that changes your intent
least.

Verdicts:

    NOTHING_TO_DO   the nominal design already audits printable
    FOUND           a printable parameter set was found & proven
    NONE_FOUND      nothing printable within budget -- best attempt is
                    reported but NOT written (never-worse guarantee;
                    --force overrides)

Exit codes: 0 = printable design in hand, 1 = NONE_FOUND, 2 = could
not run (bad design file, build errors on nominal, unusable geometry).
"""
import os
import sys
import json

import numpy as np

from dfam_audit import (audit_mesh, aggregate, overall_status,
                        detect_helix_zones, suggest_repairs,
                        mesh_health, STATUS_EXIT, _ex_parts)
from dfam_orient import _matern52

AUTOFIX_BLURB = {
    "NOTHING_TO_DO": "the nominal design already audits printable -- "
                     "no parameter change needed.",
    "FOUND": "a printable parameter set was found, rebuilt and proven "
             "by re-audit.",
    "NONE_FOUND": "no printable parameter set within the search budget "
                  "-- consider widening PARAMS ranges or a larger "
                  "--budget. Output withheld (use --force).",
}

# cost weights: a single fail must always outweigh any distance penalty
W_FAIL, W_JUDGE, W_TOL, W_DIST = 10.0, 0.5, 0.05, 1.0
COST_BUILD_ERROR = 250.0


# -------------------------------------------------------- parameter box

def _check_space(space):
    if not space or not isinstance(space, dict):
        raise ValueError("PARAMS must be a non-empty dict "
                         "{name: (lo, hi)}")
    out = {}
    for k, v in space.items():
        lo, hi = float(v[0]), float(v[1])
        if not hi > lo:
            raise ValueError(f"PARAMS[{k!r}]: hi must exceed lo "
                             f"(got {lo}..{hi})")
        out[str(k)] = (lo, hi)
    return out


def _norm(params, space):
    return np.array([(params[k] - lo) / (hi - lo)
                     for k, (lo, hi) in space.items()])


def _denorm(x, space):
    return {k: float(np.clip(x[i], 0, 1)) * (hi - lo) + lo
            for i, (k, (lo, hi)) in enumerate(space.items())}


def _dist(u, v):
    """Normalised RMS distance between two points in the unit box --
    'how far did the design move', 0 = untouched, 1 = every knob swept
    its full range."""
    u, v = np.asarray(u, float), np.asarray(v, float)
    return float(np.sqrt(((u - v) ** 2).mean()))


# ----------------------------------------------------------- evaluation

def _evaluate(build, params, profile, exclude, auto_ex):
    """Build + audit one candidate. Never raises on a bad candidate --
    a build error becomes a high-cost trial the GP learns to avoid."""
    from stalagmite import to_mesh                 # lazy: no import cycle
    try:
        mesh = to_mesh(build(**params))
    except Exception as e:                         # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}", "status": None,
                "printable": False, "fails": -1, "base_cost":
                COST_BUILD_ERROR, "mesh": None, "feats": None,
                "exclude": list(exclude)}
    ex = list(exclude)
    if auto_ex:
        _, p1 = audit_mesh(mesh, profile.angle, profile.dz, ex,
                           profile.ledge_max, profile.bridge_max)
        for zn in detect_helix_zones(p1, profile.dz):
            ex.append((zn["zlo"], zn["zhi"], zn["rmax"],
                       zn["cx"], zn["cy"]))
    _, viol = audit_mesh(mesh, profile.angle, profile.dz, ex,
                         profile.ledge_max, profile.bridge_max)
    feats = aggregate(viol, profile.dz)
    status = overall_status(feats)
    n = {s: sum(1 for f in feats if f["severity"] == s)
         for s in ("fail", "judge", "tolerable")}
    base = (W_FAIL * n["fail"] + W_JUDGE * n["judge"]
            + W_TOL * n["tolerable"])
    return {"error": None, "status": status,
            "printable": status != "FAIL", "fails": n["fail"],
            "judge": n["judge"], "base_cost": base, "mesh": mesh,
            "feats": feats, "exclude": ex}


# --------------------------------------------------------------- result

class AutofixResult:
    """What the search learned: the verdict, the winning parameters,
    how far they sit from nominal, and the full trial history."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    @property
    def ok_to_write(self):
        return self.verdict in ("FOUND", "NOTHING_TO_DO")

    @property
    def exit_code(self):
        if self.verdict == "NONE_FOUND":
            return 1
        return STATUS_EXIT.get(self.status_after, 1)

    @property
    def moves(self):
        out = []
        for k, (lo, hi) in self.space.items():
            a, b = self.params_nominal[k], self.params_best[k]
            if abs(b - a) > 1e-9 * max(1.0, hi - lo):
                out.append({"param": k, "from": a, "to": b,
                            "delta": b - a})
        return out

    def write(self, path):
        self.mesh_best.export(path)
        return path

    def to_dict(self):
        return {
            "verdict": self.verdict,
            "blurb": AUTOFIX_BLURB[self.verdict],
            "status_before": self.status_before,
            "status_after": self.status_after,
            "fails_before": self.fails_before,
            "fails_after": self.fails_after,
            "params_nominal": self.params_nominal,
            "params_best": self.params_best,
            "moves": self.moves,
            "distance": self.distance,
            "evals": self.evals,
            "exit_code": self.exit_code,
            "space": {k: list(v) for k, v in self.space.items()},
            "trials": self.trials,
        }


# --------------------------------------------------------------- search

def autofix(build, space, nominal=None, profile=None, exclude=(),
            auto_ex=False, budget=32, seed=0, say=lambda *a: None):
    """Search `space` for the printable design closest to `nominal`.

    build   : callable(**params) -> anything stalagmite.check accepts
    space   : {name: (lo, hi)} -- the knobs you allow to move
    nominal : {name: value} -- your intended design (default: box centre)
    budget  : total design evaluations, nominal included
    Returns an AutofixResult. Raises ValueError if the NOMINAL design
    itself cannot be built or audited (that is a broken design file,
    not an unprintable one).
    """
    if profile is None:
        import dfam_profiles
        profile = dfam_profiles.resolve()
    space = _check_space(space)
    names = list(space)
    d = len(names)
    if nominal is None:
        nominal = {k: (lo + hi) / 2.0 for k, (lo, hi) in space.items()}
    nominal = {k: float(np.clip(nominal[k], *space[k])) for k in names}
    x0 = _norm(nominal, space)
    rng = np.random.default_rng(seed)

    trials = []                        # JSON-safe history
    X, Y = [], []                      # GP training data

    def record(x, ev):
        dist = _dist(x, x0)
        cost = ev["base_cost"] + W_DIST * dist
        p = _denorm(x, space)
        trials.append({"params": {k: round(p[k], 6) for k in names},
                       "status": ev["status"], "fails": ev["fails"],
                       "printable": ev["printable"],
                       "dist": round(dist, 4), "cost": round(cost, 4),
                       "error": ev["error"]})
        X.append(x)
        Y.append(cost)
        return dist, cost

    # -- the nominal design first ---------------------------------------
    ev0 = _evaluate(build, nominal, profile, exclude, auto_ex)
    if ev0["error"]:
        raise ValueError(f"nominal design does not build: {ev0['error']}")
    record(x0, ev0)
    say(f"nominal: {ev0['status']} ({ev0['fails']} fail)")
    if ev0["printable"]:
        return AutofixResult(
            verdict="NOTHING_TO_DO", space=space,
            params_nominal=nominal, params_best=nominal,
            status_before=ev0["status"], status_after=ev0["status"],
            fails_before=ev0["fails"], fails_after=ev0["fails"],
            distance=0.0, evals=1, trials=trials,
            mesh_best=ev0["mesh"], feats_best=ev0["feats"],
            exclude_best=ev0["exclude"], profile=profile)

    best = None                        # (dist, x, ev) among printable
    fallback = (ev0["base_cost"], x0, ev0)   # least-bad if none printable

    def consider(x, ev, dist):
        nonlocal best, fallback
        if ev["printable"] and (best is None or dist < best[0]):
            best = (dist, x.copy(), ev)
            return True
        if not ev["printable"] and ev["base_cost"] < fallback[0]:
            fallback = (ev["base_cost"], x.copy(), ev)
        return False

    # -- initial space-filling sample ------------------------------------
    n_init = int(min(max(4, 2 * d + 2), max(0, budget - 1)))
    for i in range(n_init):
        x = rng.uniform(0, 1, d)
        ev = _evaluate(build, _denorm(x, space), profile, exclude,
                       auto_ex)
        dist, _ = record(x, ev)
        star = " <- new best" if consider(x, ev, dist) else ""
        say(f"eval {len(trials):3d}/{budget}: "
            f"{_fmt(_denorm(x, space))}  {ev['status'] or 'ERROR'} "
            f"dist {dist:.3f}{star}")

    # -- GP / LCB refinement ---------------------------------------------
    n_line = min(4 * d + 2, budget // 3)   # reserved for the homing pass
    while len(trials) < budget and (best is None
                                    or len(trials) < budget - n_line):
        A = np.asarray(X)
        y = np.asarray(Y)
        ymu, ystd = y.mean(), y.std() + 1e-9
        yn = (y - ymu) / ystd
        D = np.linalg.norm(A[:, None, :] - A[None, :, :], axis=-1)
        K = _matern52(D, 0.35) + np.eye(len(A)) * 1e-6
        Ki = np.linalg.inv(K)
        cand = np.vstack([
            rng.uniform(0, 1, (1024, d)),
            np.clip((best[1] if best else A[np.argmin(y)])
                    + rng.normal(0, 0.07, (256, d)), 0, 1),
            np.clip(x0 + rng.normal(0, 0.15, (256, d)), 0, 1),
        ])
        Dc = np.linalg.norm(cand[:, None, :] - A[None, :, :], axis=-1)
        Kc = _matern52(Dc, 0.35)
        mu = Kc @ Ki @ yn
        var = np.maximum(1e-12,
                         1.0 - np.einsum("ij,jk,ik->i", Kc, Ki, Kc))
        lcb = mu - 2.0 * np.sqrt(var)
        lcb[Dc.min(1) < 0.02] = np.inf          # no near-duplicates
        x = cand[int(np.argmin(lcb))]
        ev = _evaluate(build, _denorm(x, space), profile, exclude,
                       auto_ex)
        dist, _ = record(x, ev)
        star = " <- new best" if consider(x, ev, dist) else ""
        say(f"eval {len(trials):3d}/{budget}: "
            f"{_fmt(_denorm(x, space))}  {ev['status'] or 'ERROR'} "
            f"dist {dist:.3f}{star}")

    # -- homing pass: pull each knob individually back toward its nominal
    #    value (largest deviation first), shaving off every bit of design
    #    change the physics does not actually demand ------------------------
    def home_eval(x):
        ev = _evaluate(build, _denorm(x, space), profile, exclude,
                       auto_ex)
        dist, _ = record(x, ev)
        if ev["printable"]:
            consider(x, ev, dist)
        say(f"home {len(trials):3d}/{budget}: "
            f"{_fmt(_denorm(x, space))}  {ev['status'] or 'ERROR'} "
            f"dist {dist:.3f}")
        return ev["printable"]

    improved = best is not None
    while improved and len(trials) < budget:
        improved = False
        for i in np.argsort(-np.abs(best[1] - x0)):
            if len(trials) >= budget:
                break
            xa = best[1].copy()
            v0, vn = xa[i], x0[i]
            if abs(v0 - vn) < 5e-3:
                continue
            xa[i] = vn                     # try the full restore first
            if home_eval(xa):
                improved = True
                continue
            lo_t, hi_t = 0.0, 1.0          # t=0 printable, t=1 nominal
            while len(trials) < budget and hi_t - lo_t > 0.08:
                t = (lo_t + hi_t) / 2.0
                xa[i] = v0 + t * (vn - v0)
                if home_eval(xa):
                    lo_t = t
                    improved = True
                else:
                    hi_t = t

    # -- prove the winner (fresh rebuild + fresh audit) -------------------
    if best is not None:
        xb = best[1]
        pb = _denorm(xb, space)
        ev = _evaluate(build, pb, profile, exclude, auto_ex)
        if ev["printable"]:
            say("winner rebuilt and re-audited: proven "
                f"{ev['status']}")
            return AutofixResult(
                verdict="FOUND", space=space, params_nominal=nominal,
                params_best=pb, status_before=ev0["status"],
                status_after=ev["status"], fails_before=ev0["fails"],
                fails_after=ev["fails"], distance=_dist(xb, x0),
                evals=len(trials) + 1, trials=trials,
                mesh_best=ev["mesh"], feats_best=ev["feats"],
                exclude_best=ev["exclude"], profile=profile)
        say("winner FAILED its verification rebuild "
            "(non-deterministic build fn?) -- reporting NONE_FOUND")

    _, xf, evf = fallback
    return AutofixResult(
        verdict="NONE_FOUND", space=space, params_nominal=nominal,
        params_best=_denorm(xf, space), status_before=ev0["status"],
        status_after=evf["status"], fails_before=ev0["fails"],
        fails_after=evf["fails"], distance=_dist(xf, x0),
        evals=len(trials), trials=trials, mesh_best=evf["mesh"],
        feats_best=evf["feats"], exclude_best=evf["exclude"],
        profile=profile)


def _fmt(params):
    return " ".join(f"{k}={v:.3g}" for k, v in params.items())


# ------------------------------------------------------------------ CLI

def load_design(path):
    """Import a design file: build(**params) + PARAMS, optional NOMINAL."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("stalagmite_design",
                                                  path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import design file: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                    # may raise -- caller
    build = getattr(mod, "build", None)
    if not callable(build):
        raise ValueError("design file must define build(**params)")
    space = getattr(mod, "PARAMS", None)
    if not isinstance(space, dict):
        raise ValueError("design file must define PARAMS = "
                         "{name: (lo, hi)}")
    return build, space, getattr(mod, "NOMINAL", None)


def print_autofix(r):
    d = r.to_dict()
    print(f"before: {d['status_before']} ({d['fails_before']} fail)  "
          f"->  after: {d['status_after']} ({d['fails_after']} fail)")
    if d["moves"]:
        print(f"design moved {d['distance']:.3f} "
              f"(0 = untouched, 1 = every knob full range):")
        for m in d["moves"]:
            print(f"  {m['param']}: {m['from']:g} -> {m['to']:g}  "
                  f"({m['delta']:+g})")
    print(f"AUTOFIX: {d['verdict']} -- {d['blurb']}")


def main(argv=None):
    import argparse
    import signal
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(
        description="Search a parametric design's parameter space for "
                    "the closest-to-nominal printable design, proven "
                    "by re-audit.")
    ap.add_argument("design", help="Python file with build() + PARAMS "
                                   "(+ optional NOMINAL)")
    ap.add_argument("-o", "--out", default=None,
                    help="output STL (default: <design>_best.stl)")
    ap.add_argument("--budget", type=int, default=32,
                    help="design evaluations, nominal included")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--profile", default=None)
    ap.add_argument("--profile-file", default=None)
    ap.add_argument("--ex", action="append", default=[])
    ap.add_argument("--auto-ex", action="store_true")
    ap.add_argument("--report", metavar="OUT.html", default=None,
                    help="interactive report of the winning design")
    ap.add_argument("--force", action="store_true",
                    help="write the best attempt even on NONE_FOUND")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    import dfam_profiles
    try:
        prof = dfam_profiles.resolve(a.profile, a.profile_file)
    except (KeyError, OSError, ValueError) as e:
        ap.error(str(e))
    say = (lambda *x: None) if a.json else print
    try:
        build, space, nominal = load_design(a.design)
        ex = [tuple(map(float, e.split(":"))) for e in a.ex]
        say(f"== stalagmite autofix: {a.design} ==")
        say(f"   {prof.summary_line()}")
        r = autofix(build, space, nominal, prof, ex, a.auto_ex,
                    a.budget, a.seed, say)
    except Exception as e:                          # design-file errors
        if a.json:
            print(json.dumps({"verdict": "ERROR", "error": str(e),
                              "exit_code": 2}))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 2
    out = a.out or (os.path.splitext(a.design)[0] + "_best.stl")
    wrote = None
    if (r.ok_to_write or a.force) and r.mesh_best is not None:
        r.write(out)
        wrote = out
    if a.report and wrote:
        from dfam_report import write_report
        suggest_repairs(r.mesh_best, r.feats_best, prof.dz, prof.angle)
        write_report(r.mesh_best,
                     [v for f in r.feats_best for v in f["layers"]],
                     r.feats_best, a.report,
                     meta={"part": os.path.basename(wrote),
                           "angle": prof.angle, "dz": prof.dz,
                           "status": r.status_after,
                           "profile": prof.name,
                           "health": mesh_health(r.mesh_best, prof.dz),
                           "zones": [list(_ex_parts(e))
                                     for e in r.exclude_best]})
        say(f"winning-design report written: {a.report}")
    if a.json:
        d = r.to_dict()
        d["wrote"] = wrote
        print(json.dumps(d))
    else:
        print_autofix(r)
        if wrote:
            print(f"best design written: {wrote}")
        elif r.verdict == "NONE_FOUND":
            print("output withheld (never-worse guarantee); use "
                  "--force to write the best attempt anyway")
    return r.exit_code


if __name__ == "__main__":
    sys.exit(main())
