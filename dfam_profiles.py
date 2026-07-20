#!/usr/bin/env python3
"""
dfam_profiles.py - versioned printer / process profiles for stalagmite.

There are NO universal thresholds. The slice-containment *principle* is
universal (a deposited layer needs material beneath it); the *numbers* --
how far a layer may overhang, how long a bridge may span, how thin a wall
may be -- depend on nozzle, layer height, material, cooling and machine.

A profile bundles those numbers under a name, with provenance for each,
so advice can be as conservative or as machine-specific as the user wants:

  1. Conservative Generic FDM  -- the default; safe, well-documented
     assumptions. Always available, no printer required.
  2. Named printer/material    -- e.g. a calibrated Bambu X1C PETG profile
     loaded from JSON via --profile-file.
  3. Custom                     -- individual --angle/--ledge/... flags
     override any profile value.

Resolution order (last wins): built-in default -> named/file profile ->
explicit CLI flags.
"""
import json
import os

# ---- threshold keys the audit understands (internal names) -------------
# angle      : max self-support angle, deg
# dz         : layer height, mm
# ledge_max  : max unsupported flat cantilever ledge, mm
# bridge_max : max unsupported bridge span, mm
# min_wall   : min in-plane wall/feature, mm (None = don't lint)
# warn_angle : surface-quality warn angle, deg (None = don't lint)

_DEFAULT_PROV = {
    "angle": "FFF community 45-deg self-support rule; Langelaar AM filter",
    "ledge_max": "Adam & Zimmer 2014 (Fortus/Ultem, 0.25mm): OK<=1.8mm, "
                 "destroyed at 2.0mm",
    "bridge_max": "Hinchy 2019 after Redwood et al. 2017: <=10mm rough "
                  "downskin",
    "min_wall": "Hinchy FFF minimum 0.8mm; Gibson: wall >= 2x nozzle dia",
    "warn_angle": "Saunders 2017 traffic-light: past this angle prints but "
                  "downskin degrades",
}

BUILTIN = {
    "generic-fdm": {
        "name": "generic-fdm",
        "description": "Conservative Generic FDM - safe defaults, "
                       "no specific printer assumed.",
        "nozzle_mm": 0.4,
        "material": "generic",
        "layer_height_mm": 0.4,
        "thresholds": {
            "angle": 45.0, "dz": 0.4, "ledge_max": 1.8,
            "bridge_max": 10.0, "min_wall": 0.8, "warn_angle": 30.0,
        },
        "provenance": dict(_DEFAULT_PROV),
    },
    "generic-fdm-fine": {
        "name": "generic-fdm-fine",
        "description": "Conservative Generic FDM at a fine 0.2mm layer "
                       "height (crisper detail, same physics).",
        "nozzle_mm": 0.4,
        "material": "generic",
        "layer_height_mm": 0.2,
        "thresholds": {
            "angle": 45.0, "dz": 0.2, "ledge_max": 1.8,
            "bridge_max": 10.0, "min_wall": 0.8, "warn_angle": 30.0,
        },
        "provenance": dict(_DEFAULT_PROV),
    },
}

DEFAULT_PROFILE = "generic-fdm"
_THRESH_KEYS = ("angle", "dz", "ledge_max", "bridge_max",
                "min_wall", "warn_angle")


def _from_file(path):
    """Load and normalise a profile JSON file. Accepts either internal
    threshold keys or the friendlier *_mm / *_deg aliases."""
    with open(path) as fh:
        raw = json.load(fh)
    th = dict(raw.get("thresholds", {}))
    alias = {"angle_deg": "angle", "layer_height_mm": "dz", "dz_mm": "dz",
             "ledge_max_mm": "ledge_max", "bridge_max_mm": "bridge_max",
             "min_wall_mm": "min_wall", "warn_angle_deg": "warn_angle"}
    for a, k in alias.items():
        if a in th and k not in th:
            th[k] = th[a]
    if "dz" not in th and "layer_height_mm" in raw:
        th["dz"] = raw["layer_height_mm"]
    return {
        "name": raw.get("name", os.path.basename(path)),
        "description": raw.get("description", ""),
        "nozzle_mm": raw.get("nozzle_mm"),
        "material": raw.get("material"),
        "layer_height_mm": raw.get("layer_height_mm", th.get("dz")),
        "thresholds": {k: th.get(k) for k in _THRESH_KEYS if k in th},
        "provenance": raw.get("provenance", {}),
    }


class ResolvedProfile:
    """Flat, ready-to-use threshold set plus its metadata and audit trail
    of where each value came from."""

    def __init__(self, base, name, source):
        self.name = name
        self.source = source          # 'builtin' | 'file:...'
        self.meta = base
        th = dict(base.get("thresholds", {}))
        self.angle = th.get("angle", 45.0)
        self.dz = th.get("dz", 0.4)
        self.ledge_max = th.get("ledge_max", 1.8)
        self.bridge_max = th.get("bridge_max", 10.0)
        self.min_wall = th.get("min_wall")       # may be None
        self.warn_angle = th.get("warn_angle")   # may be None
        self.provenance = base.get("provenance", {})
        self.overridden = []

    def apply_overrides(self, **kw):
        """CLI flags win. Pass only the flags the user actually set."""
        for k, v in kw.items():
            if v is not None and hasattr(self, k):
                setattr(self, k, v)
                self.overridden.append(k)
        return self

    def summary_line(self):
        bits = [f"profile: {self.name}"]
        if self.meta.get("material") and self.meta["material"] != "generic":
            bits.append(str(self.meta["material"]))
        bits.append(f"{self.angle:.0f}deg / {self.dz}mm layer / "
                    f"ledge<={self.ledge_max}mm / bridge<={self.bridge_max}mm")
        if self.overridden:
            bits.append("overrides: " + ",".join(sorted(set(self.overridden))))
        return "  |  ".join(bits)


def resolve(name=None, path=None, **overrides):
    """Resolve a profile by name or file, then apply CLI overrides.

    overrides: angle, dz, ledge_max, bridge_max, min_wall, warn_angle
    (only pass values the user explicitly set; None = leave profile value).
    """
    if path:
        base = _from_file(path)
        rp = ResolvedProfile(base, base["name"], f"file:{path}")
    else:
        key = name or DEFAULT_PROFILE
        if key not in BUILTIN:
            raise KeyError(
                f"unknown profile '{key}'. Built-in: "
                f"{', '.join(sorted(BUILTIN))}. Or use --profile-file.")
        rp = ResolvedProfile(BUILTIN[key], key, "builtin")
    return rp.apply_overrides(**overrides)


def list_profiles():
    return sorted(BUILTIN)
