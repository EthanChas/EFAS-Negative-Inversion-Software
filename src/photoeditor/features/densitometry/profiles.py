"""Characteristic-curve data the user supplies (JSON or CSV): log exposure against R, G, B density. EFAS ships no curves of its own.

Numpy and the standard library only, no Qt/UI imports.
"""

import csv
import json
from dataclasses import dataclass

import numpy as np

KINDS = ("measured", "published", "supplied")
KIND_LABELS = {
    "measured": "Measured by you (step tablet scan)",
    "published": "Digitised from a published curve",
    "supplied": "Supplied by you (not verified by EFAS)",
}
MAX_DENSITY = 6.0
MIN_POINTS = 4


class ProfileError(ValueError):
    """The curve data cannot be used."""


@dataclass(frozen=True)
class CurveSet:
    name: str
    kind: str
    source: str
    densitometry: str
    log_exposure: np.ndarray
    density: np.ndarray

    def channels(self) -> int:
        return self.density.shape[1]

    def is_measured(self) -> bool:
        return self.kind == "measured"


def _clean(name, kind, source, densitometry, log_exposure, density) -> CurveSet:
    x = np.asarray(log_exposure, dtype=np.float64)
    d = np.asarray(density, dtype=np.float64)
    if d.ndim == 1:
        d = d[:, None]
    if x.ndim != 1 or d.shape[0] != x.shape[0] or d.shape[1] not in (1, 3):
        raise ProfileError("The curve needs one log-exposure value per row and one (grey) or three (R, G, B) density columns.")
    if x.size < MIN_POINTS:
        raise ProfileError(f"A curve needs at least {MIN_POINTS} points.")
    if not (np.isfinite(x).all() and np.isfinite(d).all()):
        raise ProfileError("The curve contains values that are not numbers.")
    if (d < 0).any() or (d > MAX_DENSITY).any():
        raise ProfileError(f"Densities must lie between 0 and {MAX_DENSITY:g}.")
    order = np.argsort(x, kind="stable")
    x, d = x[order], d[order]
    if (np.diff(x) <= 0).any():
        raise ProfileError("Two rows have the same log exposure.")
    if kind not in KINDS:
        raise ProfileError(f"kind must be one of: {', '.join(KINDS)}.")
    return CurveSet(str(name or "Curve"), kind, str(source or ""), str(densitometry or ""), x, d)


def parse_curve_data(data) -> CurveSet:
    """From a decoded JSON object: {name, kind, source, densitometry, points: [[logE, R, G, B], ...]} (or [logE, D] for grey)."""
    if not isinstance(data, dict) or not isinstance(data.get("points"), list):
        raise ProfileError("The file must hold an object with a 'points' list.")
    rows = data["points"]
    try:
        width = {len(r) for r in rows}
        if width not in ({2}, {4}):
            raise ProfileError("Each point is [log exposure, density] or [log exposure, R, G, B].")
        arr = np.asarray(rows, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ProfileError("The points must be numbers.") from exc
    return _clean(data.get("name"), data.get("kind", "supplied"), data.get("source"), data.get("densitometry"), arr[:, 0], arr[:, 1:])


def load_curve_file(path: str) -> CurveSet:
    """A .json curve file, or a .csv with columns log_exposure,R,G,B (or log_exposure,D); a header row is allowed."""
    try:
        if path.lower().endswith(".json"):
            with open(path, "r", encoding="utf-8") as f:
                return parse_curve_data(json.load(f))
        rows = []
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                row = [c.strip() for c in row if c.strip() != ""]
                if not row:
                    continue
                try:
                    rows.append([float(c) for c in row])
                except ValueError:
                    if rows:
                        raise ProfileError("A row of the CSV is not made of numbers.")
        name = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
        return parse_curve_data({"name": name, "kind": "supplied", "points": rows})
    except OSError as exc:
        raise ProfileError(f"The file could not be read: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError("The file is not valid JSON.") from exc
