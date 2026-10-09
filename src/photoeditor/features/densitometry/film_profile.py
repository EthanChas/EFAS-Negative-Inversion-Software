"""Versioned film sensitometry profiles and camera set-up profiles, and the folders they are kept in (docs/sensitometry-tier2-design.md, section 6).

A film profile holds measured or supplied characteristic-curve samples, the fits made to them with their uncertainty and supported range, and where
the data came from. It never says that all rolls of a film stock behave alike, and film identity is optional. Standard library and numpy only.
"""

import copy
import datetime as dt
import json
import os
import uuid
from dataclasses import dataclass, field

import numpy as np

from . import fit, gradient
from .profiles import CurveSet

FORMAT = "efas-film-profile"
SETUP_FORMAT = "efas-camera-setup"
VERSION = 1
KINDS = ("measured", "supplied", "estimated", "generic")
KIND_LABELS = {
    "measured": "Measured from a sensitometric exposure",
    "supplied": "Supplied by you (not verified by EFAS)",
    "estimated": "Estimated (not measured)",
    "generic": "Generic preset (not measured from your film)",
}
INVERSION_KINDS = ("measured", "supplied")
CHANNELS = ("R", "G", "B", "K")
SCALES = ("relative", "absolute")
LIMIT_REMINDER = "A profile describes the roll, exposure and processing it was made from. Other rolls of the same film can behave differently."


class ProfileError(ValueError):
    """The profile data cannot be used."""


def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def _floats(values) -> list[float]:
    return [float(v) for v in np.asarray(values, dtype=np.float64).ravel()]


@dataclass
class ChannelCurve:
    """One channel's curve: the measured points, the exposure scale they are on, and the fits made to them."""

    x: list[float]
    y: list[float]
    sigma: list[float]
    used: list[bool]
    scale: str = "relative"
    unit: str = ""
    fits: dict = field(default_factory=dict)
    chosen: str = "pchip"
    support: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def samples(self) -> fit.Samples:
        keep = np.array(self.used, dtype=bool)
        if keep.sum() < 3:
            raise ProfileError("a curve needs at least 3 used points")
        return fit.make_samples(np.array(self.x)[keep], np.array(self.y)[keep], np.array(self.sigma)[keep])

    def curve(self):
        """The callable curve this channel's record describes: the chosen fit rebuilt from its stored parameters, or the interpolated points."""
        if self.chosen in fit.MODELS and self.chosen in self.fits:
            return fit.MODELS[self.chosen](**self.fits[self.chosen]["params"])
        s = self.samples()
        ys = fit.isotonic(s.y, 1.0 / s.sigma ** 2) if (np.diff(s.y) < 0).any() else s.y
        return fit.Pchip(s.x, ys)

    def supported(self) -> tuple[float, float]:
        if len(self.support) == 2:
            return float(self.support[0]), float(self.support[1])
        keep = np.array(self.used, dtype=bool)
        xs = np.array(self.x)[keep]
        return float(xs.min()), float(xs.max())

    def to_dict(self) -> dict:
        return {
            "x": self.x, "y": self.y, "sigma": self.sigma, "used": self.used, "scale": self.scale, "unit": self.unit,
            "fits": self.fits, "chosen": self.chosen, "support": self.support, "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChannelCurve":
        if not isinstance(d, dict):
            raise ProfileError("a curve must be an object")
        try:
            x, y = _floats(d["x"]), _floats(d["y"])
            sigma = _floats(d.get("sigma") or [fit.DEFAULT_SIGMA] * len(x))
            used = [bool(u) for u in (d.get("used") or [True] * len(x))]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProfileError("a curve needs numeric x and y lists") from exc
        if not (len(x) == len(y) == len(sigma) == len(used)):
            raise ProfileError("a curve's lists must all have the same length")
        if not (np.isfinite(x).all() and np.isfinite(y).all() and np.isfinite(sigma).all()):
            raise ProfileError("a curve contains values that are not numbers")
        scale = d.get("scale", "relative")
        if scale not in SCALES:
            raise ProfileError(f"the exposure scale must be one of: {', '.join(SCALES)}")
        fits = d.get("fits") or {}
        chosen = d.get("chosen", "pchip")
        if chosen != "pchip" and chosen not in fits:
            raise ProfileError(f"the chosen representation '{chosen}' has no stored fit")
        for name, f in fits.items():
            if name not in fit.MODELS or not isinstance(f, dict) or not isinstance(f.get("params"), dict) or set(f["params"]) != set(fit.MODELS[name].params):
                raise ProfileError(f"the stored {name} fit is not valid")
        return cls(x, y, sigma, used, scale, str(d.get("unit", "")), copy.deepcopy(fits), chosen, _floats(d.get("support") or []), [str(n) for n in d.get("notes", [])])


def curve_from_report(report: fit.FitReport, scale: str = "relative", unit: str = "", used=None) -> ChannelCurve:
    """Store a fit report: the points, and each parametric fit's parameters, uncertainty and quality."""
    s = report.samples
    fits = {
        name: {
            "params": {k: float(v) for k, v in f.params.items()}, "std_errors": {k: float(v) for k, v in f.std_errors.items()}, "quality": f.quality,
            "rms": float(f.rms), "max_abs": float(f.max_abs), "chi2_red": float(f.chi2_red), "runs_p": float(f.runs_p), "loo_rms": float(f.loo_rms),
            "dof": int(f.dof), "reasons": list(f.reasons),
        }
        for name, f in report.fits.items()
    }
    return ChannelCurve(_floats(s.x), _floats(s.y), _floats(s.sigma), list(used) if used is not None else [True] * len(s), scale, unit, fits, report.chosen,
                        list(report.support), list(report.notes))


@dataclass
class FilmProfile:
    id: str
    name: str
    kind: str
    film_stock: str = ""
    process: str = ""
    notes: str = ""
    created: str = ""
    modified: str = ""
    derived_from: str = ""
    base: dict = field(default_factory=dict)
    curves: dict = field(default_factory=dict)
    calibration: dict = field(default_factory=dict)
    conditions: dict = field(default_factory=dict)
    validity: dict = field(default_factory=dict)
    uncertainty: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    def usable_for_inversion(self) -> bool:
        """Only measured or supplied curves can drive an inversion, and a colour inversion needs all of R, G and B (a black-and-white one needs K)."""
        if self.kind not in INVERSION_KINDS:
            return False
        if not ({"R", "G", "B"} <= set(self.curves) or "K" in self.curves):
            return False
        try:
            return all(c.curve() is not None for c in self.curves.values())
        except (ProfileError, fit.FitError, ValueError):
            return False

    def identity_text(self) -> str:
        parts = [p for p in (self.film_stock, self.process) if p]
        return " / ".join(parts) if parts else "Film not identified"

    def channel_curves(self) -> dict:
        return {k: c.curve() for k, c in self.curves.items()}

    def gradients(self) -> dict:
        out = {}
        for ch, cc in self.curves.items():
            support = cc.supported()
            curve = cc.curve()
            g = gradient.gamma(curve, support)
            out[ch] = {
                "support": list(support), "gamma": g.gamma if g else None, "gamma_interval": list(g.interval) if g else None,
                "iso6": gradient.iso6_geometry(curve, support), "top_density": float(curve(support[1])),
            }
        return out

    def to_dict(self) -> dict:
        d = {
            "format": FORMAT, "version": VERSION, "identity": {
                "id": self.id, "name": self.name, "film_stock": self.film_stock, "process": self.process, "notes": self.notes,
                "created": self.created, "modified": self.modified, "derived_from": self.derived_from,
            },
            "kind": self.kind, "base": self.base, "curves": {k: c.to_dict() for k, c in self.curves.items()}, "calibration": self.calibration,
            "conditions": self.conditions, "validity": self.validity, "uncertainty": self.uncertainty, "limits": LIMIT_REMINDER,
        }
        for k, v in self.extras.items():
            d.setdefault(k, v)
        return d

    @classmethod
    def from_dict(cls, d) -> "FilmProfile":
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            raise ProfileError("This is not an EFAS film profile.")
        version = d.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ProfileError("The profile has no valid version.")
        if version > VERSION:
            raise ProfileError(f"This profile is version {version}; this copy of EFAS reads up to version {VERSION}. Update EFAS to open it.")
        ident = d.get("identity")
        if not isinstance(ident, dict) or not str(ident.get("id", "")).strip():
            raise ProfileError("The profile has no id.")
        kind = d.get("kind")
        if kind not in KINDS:
            raise ProfileError(f"The profile kind must be one of: {', '.join(KINDS)}.")
        raw_curves = d.get("curves") or {}
        if not isinstance(raw_curves, dict) or any(k not in CHANNELS for k in raw_curves):
            raise ProfileError("Curves must be stored under the channels R, G, B or K.")
        curves = {k: ChannelCurve.from_dict(v) for k, v in raw_curves.items()}
        if kind in INVERSION_KINDS and not curves:
            raise ProfileError("A measured or supplied profile needs at least one curve.")
        known = {"format", "version", "identity", "kind", "base", "curves", "calibration", "conditions", "validity", "uncertainty", "limits"}
        return cls(
            id=str(ident["id"]), name=str(ident.get("name") or "Unnamed profile"), kind=kind, film_stock=str(ident.get("film_stock", "")),
            process=str(ident.get("process", "")), notes=str(ident.get("notes", "")), created=str(ident.get("created", "")),
            modified=str(ident.get("modified", "")), derived_from=str(ident.get("derived_from", "")), base=copy.deepcopy(d.get("base") or {}),
            curves=curves, calibration=copy.deepcopy(d.get("calibration") or {}), conditions=copy.deepcopy(d.get("conditions") or {}),
            validity=copy.deepcopy(d.get("validity") or {}), uncertainty=copy.deepcopy(d.get("uncertainty") or {}),
            extras={k: copy.deepcopy(v) for k, v in d.items() if k not in known},
        )


def new_profile(name: str, kind: str, curves: dict | None = None, **fields) -> FilmProfile:
    if kind not in KINDS:
        raise ProfileError(f"kind must be one of: {', '.join(KINDS)}")
    stamp = now_iso()
    return FilmProfile(id=uuid.uuid4().hex, name=name or "Unnamed profile", kind=kind, created=stamp, modified=stamp, curves=curves or {}, **fields)


def from_curve_set(cs: CurveSet, name: str | None = None) -> FilmProfile:
    """Convert a Tier 1 curve file. Its densities are taken as density above the film base after subtracting each channel's lowest value."""
    curves = {}
    chans = ("R", "G", "B") if cs.channels() == 3 else ("K",)
    for i, ch in enumerate(chans):
        y = cs.density[:, i]
        report = fit.fit_curve(cs.log_exposure, y - y.min(), sigma=None)
        curves[ch] = curve_from_report(report, scale="absolute" if cs.is_measured() else "relative", unit="lux-seconds" if cs.is_measured() else "")
    kind = "measured" if cs.is_measured() else "supplied"
    p = new_profile(name or cs.name, kind, curves, notes=f"Converted from a curve file. {cs.source}".strip(), conditions={"densitometry": cs.densitometry})
    p.calibration = {"origin": "tier1 curve file", "kind_declared": cs.kind, "source": cs.source}
    p.base = {"dmin_from_curve": [float(v) for v in cs.density.min(axis=0)]}
    return p


def duplicate(profile: FilmProfile, name: str | None = None) -> FilmProfile:
    twin = FilmProfile.from_dict(profile.to_dict())
    twin.id = uuid.uuid4().hex
    twin.name = name or f"{profile.name} (copy)"
    twin.derived_from = profile.id
    twin.created = twin.modified = now_iso()
    return twin


def compare(a: FilmProfile, b: FilmProfile) -> list[dict]:
    """A side-by-side of the numbers that matter, with the difference where both have a value."""
    rows = []

    def add(label, va, vb):
        diff = (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
        rows.append({"label": label, "a": va, "b": vb, "difference": diff})

    add("Kind", a.kind, b.kind)
    add("Film", a.identity_text(), b.identity_text())
    ga, gb = a.gradients(), b.gradients()
    for ch in CHANNELS:
        if ch in ga or ch in gb:
            ca, cb = ga.get(ch), gb.get(ch)
            add(f"{ch} gamma", ca["gamma"] if ca else None, cb["gamma"] if cb else None)
            add(f"{ch} density range measured", ca["top_density"] if ca else None, cb["top_density"] if cb else None)
            add(f"{ch} supported log exposure", f"{ca['support'][0]:.2f} to {ca['support'][1]:.2f}" if ca else None, f"{cb['support'][0]:.2f} to {cb['support'][1]:.2f}" if cb else None)
            qa = a.curves[ch].fits.get(a.curves[ch].chosen, {}).get("quality", "interpolated") if ch in a.curves else None
            qb = b.curves[ch].fits.get(b.curves[ch].chosen, {}).get("quality", "interpolated") if ch in b.curves else None
            add(f"{ch} fit quality", qa, qb)
    return rows


class _JsonStore:
    """A folder of .json files, one per record, written atomically."""

    def __init__(self, folder: str):
        self.folder = folder

    def _path(self, ident: str) -> str:
        if not ident or any(c in ident for c in "/\\:") or ident.startswith("."):
            raise ProfileError("invalid profile id")
        return os.path.join(self.folder, f"{ident}.json")

    def _write(self, ident: str, data: dict) -> None:
        os.makedirs(self.folder, exist_ok=True)
        path = self._path(ident)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    def _read(self, path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except OSError as exc:
            raise ProfileError(f"The file could not be read: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProfileError("The file is not valid JSON.") from exc

    def delete(self, ident: str) -> None:
        try:
            os.remove(self._path(ident))
        except FileNotFoundError:
            pass

    def ids(self) -> list[str]:
        if not os.path.isdir(self.folder):
            return []
        return sorted(f[:-5] for f in os.listdir(self.folder) if f.endswith(".json"))


class ProfileStore(_JsonStore):
    """The film profiles in the data folder."""

    def save(self, profile: FilmProfile) -> None:
        profile.modified = now_iso()
        self._write(profile.id, profile.to_dict())

    def load(self, ident: str) -> FilmProfile:
        return FilmProfile.from_dict(self._read(self._path(ident)))

    def exists(self, ident: str) -> bool:
        return os.path.isfile(self._path(ident))

    def list(self) -> list[dict]:
        """A summary of every readable profile (unreadable ones are skipped, not fatal)."""
        out = []
        for ident in self.ids():
            try:
                p = self.load(ident)
            except ProfileError:
                continue
            out.append({"id": p.id, "name": p.name, "kind": p.kind, "film": p.identity_text(), "modified": p.modified, "usable": p.usable_for_inversion()})
        return sorted(out, key=lambda r: (r["name"].lower(), r["id"]))

    def duplicate(self, ident: str, name: str | None = None) -> FilmProfile:
        twin = duplicate(self.load(ident), name)
        self.save(twin)
        return twin

    def import_file(self, path: str) -> FilmProfile:
        """Add a profile from a file. An id already in use gets a fresh one so nothing is overwritten."""
        p = FilmProfile.from_dict(self._read(path))
        if self.exists(p.id):
            p.derived_from = p.derived_from or p.id
            p.id = uuid.uuid4().hex
        self.save(p)
        return p

    def export(self, ident: str, path: str) -> None:
        p = self.load(ident)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(p.to_dict(), f, indent=2, ensure_ascii=False)


@dataclass
class CameraSetup:
    """A camera and backlight set-up and what was learned about it as a measuring instrument."""

    id: str
    name: str
    camera: str = ""
    lens: str = ""
    light_source: str = ""
    settings: dict = field(default_factory=dict)
    black: list = field(default_factory=list)
    saturation: list = field(default_factory=list)
    noise_sigma: list = field(default_factory=list)
    linearity_error_percent: float | None = None
    flare_fraction: float | None = None
    flare_fraction_se: float | None = None
    usable_density_max: list = field(default_factory=list)
    calibration: dict = field(default_factory=dict)
    notes: str = ""
    created: str = ""
    modified: str = ""
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "format": SETUP_FORMAT, "version": VERSION, "id": self.id, "name": self.name, "camera": self.camera, "lens": self.lens,
            "light_source": self.light_source, "settings": self.settings, "black": self.black, "saturation": self.saturation, "noise_sigma": self.noise_sigma,
            "linearity_error_percent": self.linearity_error_percent, "flare_fraction": self.flare_fraction, "flare_fraction_se": self.flare_fraction_se,
            "usable_density_max": self.usable_density_max, "calibration": self.calibration, "notes": self.notes, "created": self.created,
            "modified": self.modified,
        }
        for k, v in self.extras.items():
            d.setdefault(k, v)
        return d

    @classmethod
    def from_dict(cls, d) -> "CameraSetup":
        if not isinstance(d, dict) or d.get("format") != SETUP_FORMAT:
            raise ProfileError("This is not an EFAS camera set-up file.")
        version = d.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ProfileError("The set-up has no valid version.")
        if version > VERSION:
            raise ProfileError(f"This set-up is version {version}; this copy of EFAS reads up to version {VERSION}.")
        if not str(d.get("id", "")).strip():
            raise ProfileError("The set-up has no id.")
        phi = d.get("flare_fraction")
        if phi is not None and (not isinstance(phi, (int, float)) or isinstance(phi, bool) or not (0.0 <= phi < 1.0)):
            raise ProfileError("The flare fraction must be a number from 0 up to (not including) 1.")
        known = {"format", "version", "id", "name", "camera", "lens", "light_source", "settings", "black", "saturation", "noise_sigma", "linearity_error_percent",
                 "flare_fraction", "flare_fraction_se", "usable_density_max", "calibration", "notes", "created", "modified"}
        return cls(
            id=str(d["id"]), name=str(d.get("name") or "Unnamed set-up"), camera=str(d.get("camera", "")), lens=str(d.get("lens", "")),
            light_source=str(d.get("light_source", "")), settings=copy.deepcopy(d.get("settings") or {}), black=list(d.get("black") or []),
            saturation=list(d.get("saturation") or []), noise_sigma=list(d.get("noise_sigma") or []), linearity_error_percent=d.get("linearity_error_percent"),
            flare_fraction=phi, flare_fraction_se=d.get("flare_fraction_se"), usable_density_max=list(d.get("usable_density_max") or []),
            calibration=copy.deepcopy(d.get("calibration") or {}), notes=str(d.get("notes", "")), created=str(d.get("created", "")),
            modified=str(d.get("modified", "")), extras={k: copy.deepcopy(v) for k, v in d.items() if k not in known},
        )


def new_setup(name: str, **fields) -> CameraSetup:
    stamp = now_iso()
    return CameraSetup(id=uuid.uuid4().hex, name=name or "Unnamed set-up", created=stamp, modified=stamp, **fields)


class SetupStore(_JsonStore):
    """The camera set-ups in the data folder."""

    def save(self, setup: CameraSetup) -> None:
        setup.modified = now_iso()
        self._write(setup.id, setup.to_dict())

    def load(self, ident: str) -> CameraSetup:
        return CameraSetup.from_dict(self._read(self._path(ident)))

    def list(self) -> list[dict]:
        out = []
        for ident in self.ids():
            try:
                s = self.load(ident)
            except ProfileError:
                continue
            out.append({"id": s.id, "name": s.name, "camera": s.camera, "modified": s.modified, "flare_fraction": s.flare_fraction})
        return sorted(out, key=lambda r: (r["name"].lower(), r["id"]))


def profiles_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "film_profiles")


def setups_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "camera_setups")
