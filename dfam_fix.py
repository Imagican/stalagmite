#!/usr/bin/env python3
"""
dfam_fix.py - Stage B of "doing": APPLY the generated repairs and PROVE
the result.

    stalagmite-fix part.stl -o part_fixed.stl --auto-ex

Pipeline: audit -> generate repair bodies from real slice contours
(dfam_repair) -> boolean-union them into the part -> re-audit under the
same profile -> match features before/after and issue a verdict:

    NOTHING_TO_FIX  no fail features to begin with (input copied out)
    VERIFIED        every fail resolved, nothing regressed
    PARTIAL         fails reduced but some remain
    NOT_IMPROVED    the fix did not help (output NOT written unless
                    --force -- the never-worse guarantee)

The verdict is computed by the same feature-matching used by
stalagmite-diff, so "fixed" always means "provably fixed under the
audit", never "we unioned something and hope".

Union engines are tried in order of trustworthiness: manifold3d (a
proper boolean), any default trimesh boolean engine, and finally a
plain shell concatenation (flagged in the notes -- overlapping shells
slice correctly in mainstream slicers, but it is not a true solid).

Exit codes match the audit contract: 0 = final part printable,
1 = still FAIL (or not improved), 2 = could not process.
"""
import os
import sys
import json

import numpy as np
import trimesh

from dfam_audit import (audit_mesh, aggregate, overall_status,
                        detect_helix_zones, suggest_repairs, load_mesh,
                        mesh_health, STATUS_EXIT, _ex_parts)
from dfam_diff import match_features, _label, _sev_rank
from dfam_repair import make_repair_specs, build_body

VERDICT_BLURB = {
    "NOTHING_TO_FIX": "no fail-severity defects -- nothing to repair.",
    "VERIFIED": "every fail defect resolved; nothing regressed. "
                "Re-audited and proven.",
    "PARTIAL": "fail defects reduced but some remain -- consider "
               "reorienting (stalagmite-orient) or a design change.",
    "NOT_IMPROVED": "the generated repairs did not improve the audit -- "
                    "output withheld (use --force to write anyway).",
}


# ------------------------------------------------------------- unioning

def _try_union(base, body, engine):
    if engine == "concat":
        return trimesh.util.concatenate([base, body])
    if engine is None:
        return trimesh.boolean.union([base, body])
    return trimesh.boolean.union([base, body], engine=engine)


def union_bodies(mesh, bodies, say=lambda *a: None):
    """Union repair bodies into the mesh, most-trustworthy engine first,
    degrading per-body rather than aborting the whole fix. Returns
    (fixed_mesh, engine_used, notes)."""
    engines = []
    try:
        import manifold3d                        # noqa: F401
        engines.append("manifold")
    except ImportError:
        pass
    engines += [None, "concat"]                  # None = trimesh default
    notes = []
    fixed = mesh.copy()
    used = set()
    for i, body in enumerate(bodies):
        applied = False
        for eng in engines:
            try:
                cand = _try_union(fixed, body, eng)
                if cand is None or len(cand.faces) == 0:
                    raise ValueError("empty boolean result")
                fixed = cand
                used.add(eng or "trimesh-default")
                applied = True
                if eng == "concat":
                    notes.append(f"body {i}: fell back to shell "
                                 f"concatenation (not a true boolean; "
                                 f"slicers handle overlapping shells)")
                break
            except Exception as e:
                say(f"  union engine {eng or 'default'} failed on body "
                    f"{i}: {type(e).__name__}")
                continue
        if not applied:
            notes.append(f"body {i}: could not be merged -- skipped")
    engine_used = "+".join(sorted(used)) if used else "none"
    return fixed, engine_used, notes


# ------------------------------------------------------------- verdicts

def decide_verdict(before_feats, after_feats):
    """Pure verdict logic (unit-testable). Returns (verdict, detail dict
    with resolved/persist/introduced/worsened index structures)."""
    fails_before = [f for f in before_feats if f["severity"] == "fail"]
    resolved, persist, introduced = match_features(before_feats,
                                                   after_feats)
    worsened = [(i, j) for i, j in persist
                if _sev_rank(after_feats[j]["severity"])
                < _sev_rank(before_feats[i]["severity"])]
    new_fails = [j for j in introduced
                 if after_feats[j]["severity"] == "fail"]
    fails_after = [f for f in after_feats if f["severity"] == "fail"]
    if not fails_before:
        verdict = "NOTHING_TO_FIX"
    elif not fails_after and not new_fails and not worsened:
        verdict = "VERIFIED"
    elif len(fails_after) < len(fails_before) and not new_fails:
        verdict = "PARTIAL"
    else:
        verdict = "NOT_IMPROVED"
    return verdict, {"resolved": resolved, "persist": persist,
                     "introduced": introduced, "worsened": worsened,
                     "new_fails": new_fails,
                     "fails_before": len(fails_before),
                     "fails_after": len(fails_after)}


# ------------------------------------------------------------------ fix

class FixResult:
    """Everything stalagmite-fix learned: before/after audits, the fixed
    mesh, the verdict and its evidence."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    @property
    def ok_to_write(self):
        return self.verdict in ("VERIFIED", "PARTIAL", "NOTHING_TO_FIX")

    @property
    def exit_code(self):
        if self.verdict == "NOT_IMPROVED":
            return 1
        return STATUS_EXIT.get(self.status_after, 1)

    def write(self, path):
        self.mesh_fixed.export(path)
        return path

    def to_dict(self):
        d = self.detail
        bf, af = self.feats_before, self.feats_after
        return {
            "verdict": self.verdict,
            "blurb": VERDICT_BLURB[self.verdict],
            "status_before": self.status_before,
            "status_after": self.status_after,
            "exit_code": self.exit_code,
            "bodies": self.n_bodies,
            "engine": self.engine,
            "notes": self.notes,
            "fails_before": d["fails_before"],
            "fails_after": d["fails_after"],
            "resolved": [_label(bf[i]) for i in d["resolved"]],
            "persist": [{"feature": _label(af[j]),
                         "from": bf[i]["severity"],
                         "to": af[j]["severity"]}
                        for i, j in d["persist"]],
            "introduced": [{"feature": _label(af[j]),
                            "severity": af[j]["severity"]}
                           for j in d["introduced"]],
        }


def _audit(mesh, profile, exclude):
    _, v = audit_mesh(mesh, profile.angle, profile.dz, exclude,
                      profile.ledge_max, profile.bridge_max)
    feats = aggregate(v, profile.dz)
    return v, feats


def apply_fixes(mesh, profile=None, exclude=(), auto_ex=False,
                height=None, easing=1.0, flare=1.0,
                say=lambda *a: None, keep=(), sculpt=None):
    """The Stage-B engine: audit, build repairs, union, re-audit, judge.
    Returns a FixResult. Never raises on union trouble (degrades and
    records notes); raises ValueError only on unusable input.

    `keep` = design-intent keep-clear zones (dfam_intent): no repair
    body may touch them. Blocked repairs are dropped with a note; if
    that leaves fails unfixed the verdict says so honestly.

    `sculpt` = per-defect settings from the report sculptor: a list of
    {cls, zlo, zhi, cx, cy, optional, height?, easing?, flare?}. Each
    entry is matched to a before-audit feature (class + z + centroid);
    its settings drive that repair's body, and matched OPTIONAL
    (tolerable/judge) repairs are included in the fix -- the sculpted
    part comes back unioned, vent-drilled, and re-audit-proven."""
    if profile is None:
        import dfam_profiles
        profile = dfam_profiles.resolve()
    exclude = list(exclude)
    if auto_ex:
        _, p1 = audit_mesh(mesh, profile.angle, profile.dz, exclude,
                           profile.ledge_max, profile.bridge_max)
        for zn in detect_helix_zones(p1, profile.dz):
            exclude.append((zn["zlo"], zn["zhi"], zn["rmax"],
                            zn["cx"], zn["cy"]))
    viol_b, feats_b = _audit(mesh, profile, exclude)
    status_b = overall_status(feats_b)
    say(f"before: {status_b} "
        f"({sum(1 for f in feats_b if f['severity'] == 'fail')} fail)")
    if keep:
        from dfam_intent import annotate_features
        n_hit = annotate_features(feats_b, keep)
        if n_hit:
            say(f"{n_hit} defect(s) touch keep-clear zone(s)")

    sculpt = list(sculpt or [])
    severities = (("fail", "judge", "tolerable") if sculpt
                  else ("fail",))
    specs = make_repair_specs(mesh, feats_b, profile.dz, profile.angle,
                              keep, avoid=exclude,
                              ledge_max=profile.ledge_max,
                              severities=severities)
    blocked_notes = [f["repair_blocked"] for f in feats_b
                     if f.get("repair_blocked")]
    for note in blocked_notes:
        say(f"  {note}")

    # match sculptor entries to before-audit features. Class + z +
    # centroid alone is AMBIGUOUS for concentric same-class defects
    # (a ring's centroid sits at the part centre -- flat_roof's fail
    # and tolerable share all three keys), so the optional flag gates
    # severity, and the report's feature id is tried first.
    def _compatible(f, e):
        return (f.get("repair_spec") is not None
                and f["cls"] == e.get("cls")
                and (f["severity"] != "fail") == bool(e.get("optional"))
                and abs(f["zlo"] - float(e.get("zlo", 1e9)))
                <= 2 * profile.dz + 0.6)

    def _match_entry(e):
        idx = e.get("id")
        if isinstance(idx, int) and 0 <= idx < len(feats_b) \
                and _compatible(feats_b[idx], e):
            return idx
        best, bd = None, 5.0
        for i, f in enumerate(feats_b):
            if not _compatible(f, e):
                continue
            g = f.get("geom")
            if g is None or g.is_empty:
                continue
            d = ((g.centroid.x - float(e.get("cx", 1e9))) ** 2
                 + (g.centroid.y - float(e.get("cy", 1e9))) ** 2) ** 0.5
            if d < bd:
                bd, best = d, i
        return best

    params = {}                          # feature idx -> (H, ease, flare)
    wanted_optional = set()
    for e in sculpt:
        i = _match_entry(e)
        if i is None:
            blocked_notes.append(
                f"sculpted entry ({e.get('cls')} z {e.get('zlo')}) did "
                f"not match any repairable defect -- skipped")
            continue
        if e.get("height") is not None:
            params[i] = (float(e["height"]),
                         float(e.get("easing", 1.0)),
                         float(e.get("flare", 1.0)))
        if feats_b[i]["severity"] != "fail":
            wanted_optional.add(i)
    # optional repairs join the fix ONLY when the sculptor opted them in
    specs = [s for s in specs
             if not s.get("optional") or s["feature"] in wanted_optional]
    if params:
        say(f"applying your sculpted parameters to {len(params)} "
            f"repair(s)")
    if not specs:
        verdict, detail = decide_verdict(feats_b, feats_b)
        return FixResult(mesh_fixed=mesh, status_before=status_b,
                         status_after=status_b, feats_before=feats_b,
                         feats_after=feats_b, verdict=verdict,
                         detail=detail, n_bodies=0, engine="none",
                         notes=blocked_notes, specs=[], exclude=exclude,
                         profile=profile)

    bodies = [build_body(s, *params.get(s["feature"],
                                        (height, easing, flare)))
              for s in specs]
    say(f"built {len(bodies)} repair body(ies) from slice contours")
    intent_notes0 = list(blocked_notes)
    for s, b in zip(specs, bodies):
        nv = (b.metadata or {}).get("vents", 0)
        nd = (b.metadata or {}).get("vents_drilled", 0)
        if nv and nd == nv:
            intent_notes0.append(
                f"{nd} vent shaft(s) drilled through the roof chamfer "
                f"-- secondary roof holes stay continuous")
        elif nv:
            intent_notes0.append(
                f"{nv - nd} of {nv} vent shaft(s) could NOT be drilled "
                f"(boolean engine unavailable?) -- re-drill manually if "
                f"functional")
    for s in specs:
        if s.get("kind") == "roofcone":
            say("  roof chamfer: closing the internal ceiling as a "
                "corbelled cone (cavity stays hollow, bore stays open)")
            if s.get("clamped_above"):
                zlo_c, zhi_c, _ = s["clamped_above"]
                if s.get("over_allowance"):
                    tail = (f"; partial closure leaves a "
                            f"{s['residual_ledge']:g}mm annular ledge "
                            f"BEYOND the straight-ledge allowance -- "
                            f"the re-audit is the judge")
                elif s.get("residual_ledge"):
                    tail = (f"; partial closure leaves a "
                            f"{s['residual_ledge']:g}mm ledge within "
                            f"allowance")
                else:
                    tail = ""
                intent_notes0.append(
                    f"roof chamfer clamped above the functional zone at "
                    f"z {zlo_c:g}-{zhi_c:g} (threads stay untouched)"
                    + tail)
    intent_notes = list(intent_notes0)
    if keep:
        from dfam_intent import body_blocked
        kept = []
        for s, b in zip(specs, bodies):
            if body_blocked(b, keep):
                intent_notes.append(
                    f"repair at z {s['z_bot']:g}-{s['z_top']:g} blocked "
                    f"by keep-clear zone (functional surface) -- "
                    f"not applied")
            else:
                kept.append(b)
        bodies = kept
        for note in intent_notes:
            say(f"  {note}")
        if not bodies:
            say("every repair blocked by intent -- part left untouched")
            verdict, detail = decide_verdict(feats_b, feats_b)
            return FixResult(mesh_fixed=mesh, status_before=status_b,
                             status_after=status_b, feats_before=feats_b,
                             feats_after=feats_b, verdict=verdict,
                             detail=detail, n_bodies=0, engine="none",
                             notes=intent_notes, specs=specs,
                             exclude=exclude, profile=profile)
    fixed, engine, notes = union_bodies(mesh, bodies, say)
    notes = intent_notes + notes
    say(f"union engine: {engine}")

    viol_a, feats_a = _audit(fixed, profile, exclude)
    status_a = overall_status(feats_a)
    say(f"after:  {status_a} "
        f"({sum(1 for f in feats_a if f['severity'] == 'fail')} fail)")
    verdict, detail = decide_verdict(feats_b, feats_a)
    return FixResult(mesh_fixed=fixed, status_before=status_b,
                     status_after=status_a, feats_before=feats_b,
                     feats_after=feats_a, verdict=verdict, detail=detail,
                     n_bodies=len(bodies), engine=engine, notes=notes,
                     specs=specs, exclude=exclude, profile=profile)


# ------------------------------------------------------------------ CLI

def print_fix(r):
    d = r.to_dict()
    print(f"before: {d['status_before']}  ->  after: {d['status_after']}")
    for lbl in d["resolved"]:
        print(f"  RESOLVED   {lbl}")
    for p in d["persist"]:
        print(f"  PERSISTS   {p['feature']}  [{p['from']} -> {p['to']}]")
    for n in d["introduced"]:
        print(f"  NEW        {n['feature']}  [{n['severity']}]")
    for note in d["notes"]:
        print(f"  note: {note}")
    print(f"FIX: {d['verdict']} -- {d['blurb']}")


def main(argv=None):
    import argparse
    import signal
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(
        description="Apply stalagmite's generated repairs to a part and "
                    "verify the result by re-audit.")
    ap.add_argument("stl")
    ap.add_argument("-o", "--out", default=None,
                    help="output path (default: <name>_fixed.stl)")
    ap.add_argument("--profile", default=None)
    ap.add_argument("--profile-file", default=None)
    ap.add_argument("--auto-ex", action="store_true")
    ap.add_argument("--ex", action="append", default=[])
    ap.add_argument("--keep", action="append", default=[],
                    metavar="ZLO:ZHI:RMAX[:CX:CY]",
                    help="design-intent keep-clear zone: no repair may "
                         "touch it (functional surface / bore / seal)")
    ap.add_argument("--height", type=float, default=None,
                    help="repair loft height (default: physics minimum)")
    ap.add_argument("--easing", type=float, default=1.0,
                    help="1 = chamfer, up to 2.5 = concave fillet")
    ap.add_argument("--flare", type=float, default=1.0)
    ap.add_argument("--report", metavar="OUT.html", default=None,
                    help="write an interactive report of the FIXED part")
    ap.add_argument("--force", action="store_true",
                    help="write output even if the fix did not improve "
                         "the audit")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    import dfam_profiles
    try:
        profile = dfam_profiles.resolve(a.profile, a.profile_file)
    except (KeyError, OSError, ValueError) as e:
        ap.error(str(e))
    out = a.out or (os.path.splitext(a.stl)[0] + "_fixed.stl")
    say = (lambda *x: None) if a.json else print
    try:
        mesh = load_mesh(a.stl)
        say(f"== stalagmite fix: {a.stl} ==")
        say(f"   {profile.summary_line()}")
        ex = [tuple(map(float, e.split(":"))) for e in a.ex]
        from dfam_intent import parse_keep
        keep = parse_keep(a.keep)
        r = apply_fixes(mesh, profile, ex, a.auto_ex,
                        a.height, a.easing, a.flare, say, keep)
    except (ValueError, OSError) as e:
        if a.json:
            print(json.dumps({"verdict": "ERROR", "error": str(e),
                              "exit_code": 2}))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 2
    wrote = None
    if r.verdict == "NOTHING_TO_FIX":
        pass                                    # nothing to write
    elif r.ok_to_write or a.force:
        r.write(out)
        wrote = out
    if a.report and (wrote or r.verdict == "NOTHING_TO_FIX"):
        from dfam_report import write_report
        suggest_repairs(r.mesh_fixed, r.feats_after, profile.dz,
                        profile.angle)
        write_report(r.mesh_fixed, [v for f in r.feats_after
                                    for v in f["layers"]],
                     r.feats_after, a.report,
                     meta={"part": os.path.basename(wrote or a.stl),
                           "angle": profile.angle, "dz": profile.dz,
                           "status": r.status_after,
                           "profile": profile.name,
                           "health": mesh_health(r.mesh_fixed, profile.dz),
                           "zones": [list(_ex_parts(e))
                                     for e in r.exclude]})
        say(f"fixed-part report written: {a.report}")
    if a.json:
        d = r.to_dict()
        d["wrote"] = wrote
        print(json.dumps(d))
    else:
        print_fix(r)
        if wrote:
            print(f"fixed part written: {wrote}")
        elif r.verdict == "NOT_IMPROVED":
            print("output withheld (never-worse guarantee); use --force "
                  "to write anyway")
    return r.exit_code


if __name__ == "__main__":
    sys.exit(main())
