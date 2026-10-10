"""Colour accuracy from a transmission colour target (an IT8.7/1-style slide or negative target scanned on the same set-up).

The scan of each patch, divided by the clear-light reading, is the fraction of light each channel passes. A 3x3 matrix that carries those three numbers to the
colour the target's maker measured (CIE XYZ under D50, relative to clear light) is fitted so that the clear light maps exactly to white and the error in
perceived colour (CIE Delta E 2000) is as small as possible. The error is also tested on patches the fit did not see. Numpy only, no Qt/UI imports.
"""

import re
from dataclasses import dataclass, field

import numpy as np

from .target import Patch, PatchSample, sample_patches

D50 = np.array([0.96422, 1.0, 0.82521])
SRGB_TO_XYZ_D50 = np.array([[0.4360747, 0.3850649, 0.1430804], [0.2225045, 0.7168786, 0.0606169], [0.0139322, 0.0971045, 0.7141733]])
MIN_PATCHES = 12
FOLDS = 5
EXCELLENT, ACCEPTABLE = 2.0, 5.0


class ColourTargetError(ValueError):
    """The target data cannot be used."""


# --- colour maths -------------------------------------------------------------------------------------------------------------------

def xyz_to_lab(xyz: np.ndarray, white=D50) -> np.ndarray:
    t = np.asarray(xyz, dtype=np.float64) / np.asarray(white)
    f = np.where(t > (6 / 29) ** 3, np.cbrt(np.maximum(t, 0.0)), t / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def lab_to_xyz(lab: np.ndarray, white=D50) -> np.ndarray:
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16) / 116
    fx, fz = fy + lab[..., 1] / 500, fy - lab[..., 2] / 200

    def inv(f):
        return np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29))

    return np.stack([inv(fx), inv(fy), inv(fz)], axis=-1) * np.asarray(white)


def delta_e2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIE Delta E 2000 (Sharma, Wu and Dalal's formulation) between matching rows of two Lab arrays."""
    l1, a1, b1 = (np.asarray(lab1, dtype=np.float64)[..., i] for i in range(3))
    l2, a2, b2 = (np.asarray(lab2, dtype=np.float64)[..., i] for i in range(3))
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cbar = (c1 + c2) / 2
    g = 0.5 * (1 - np.sqrt(cbar ** 7 / (cbar ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dl, dc = l2 - l1, c2p - c1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(c1p * c2p == 0, 0.0, dh)
    dhp = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh) / 2)
    lbar, cbarp = (l1 + l2) / 2, (c1p + c2p) / 2
    hsum = h1p + h2p
    hbar = np.where(c1p * c2p == 0, hsum, np.where(np.abs(h1p - h2p) <= 180, hsum / 2, np.where(hsum < 360, (hsum + 360) / 2, (hsum - 360) / 2)))
    t = 1 - 0.17 * np.cos(np.radians(hbar - 30)) + 0.24 * np.cos(np.radians(2 * hbar)) + 0.32 * np.cos(np.radians(3 * hbar + 6)) - 0.20 * np.cos(np.radians(4 * hbar - 63))
    sl = 1 + 0.015 * (lbar - 50) ** 2 / np.sqrt(20 + (lbar - 50) ** 2)
    sc, sh = 1 + 0.045 * cbarp, 1 + 0.015 * cbarp * t
    rt = -2 * np.sqrt(cbarp ** 7 / (cbarp ** 7 + 25.0 ** 7)) * np.sin(np.radians(60 * np.exp(-(((hbar - 275) / 25) ** 2))))
    return np.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhp / sh) ** 2 + rt * (dc / sc) * (dhp / sh))


# --- reference data -----------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class TargetReference:
    name: str
    ids: tuple[str, ...]
    xyz: np.ndarray
    notes: tuple[str, ...] = field(default_factory=tuple)


def _tokens(line: str) -> list[str]:
    return re.findall(r'"[^"]*"|\S+', line.replace("\t", " "))


def _columns(names: list[str]) -> tuple[int, str, list[int]]:
    low = [n.strip('"').upper() for n in names]
    ident = next((i for i, n in enumerate(low) if n in ("SAMPLE_ID", "SAMPLEID", "SAMPLE_NAME", "ID", "PATCH", "NAME")), None)
    if ident is None:
        raise ColourTargetError("The reference file has no sample id column (SAMPLE_ID).")
    for kind, wanted in (("xyz", ("XYZ_X", "XYZ_Y", "XYZ_Z")), ("xyz", ("X", "Y", "Z")), ("lab", ("LAB_L", "LAB_A", "LAB_B")), ("lab", ("L", "A", "B")), ("lab", ("L*", "A*", "B*"))):
        if all(w in low for w in wanted):
            return ident, kind, [low.index(w) for w in wanted]
    raise ColourTargetError("The reference file has no XYZ or Lab columns.")


def parse_reference(text: str, name: str = "") -> TargetReference:
    """A CGATS file (as supplied with IT8 targets) or a CSV with a header, giving a colour per patch id in XYZ or Lab (D50). XYZ is accepted as 0-1 or 0-100."""
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n")]
    rows: list[list[str]] = []
    header: list[str] | None = None
    title = name
    if any(ln.upper().startswith("BEGIN_DATA") for ln in lines):
        in_fmt = in_data = False
        fmt: list[str] = []
        for ln in lines:
            up = ln.upper()
            if up.startswith("ORIGINATOR") or up.startswith("DESCRIPTOR"):
                title = title or ln.split(None, 1)[-1].strip('"')
            if up.startswith("BEGIN_DATA_FORMAT"):
                in_fmt = True
            elif up.startswith("END_DATA_FORMAT"):
                in_fmt = False
            elif up.startswith("BEGIN_DATA"):
                in_data = True
            elif up.startswith("END_DATA"):
                in_data = False
            elif in_fmt:
                fmt += _tokens(ln)
            elif in_data and ln:
                rows.append(_tokens(ln))
        header = fmt
    else:
        for ln in lines:
            if not ln or ln.startswith("#"):
                continue
            cells = [c.strip().strip('"') for c in re.split(r"[,;\t]", ln)]
            if header is None:
                header = cells
            else:
                rows.append(cells)
    if not header or not rows:
        raise ColourTargetError("The reference file holds no patch data.")
    ident, kind, cols = _columns(header)
    ids, vals = [], []
    for r in rows:
        if len(r) <= max([ident] + cols):
            continue
        try:
            vals.append([float(r[c]) for c in cols])
        except ValueError:
            continue
        ids.append(r[ident].strip('"').upper())
    if len(ids) < MIN_PATCHES:
        raise ColourTargetError(f"The reference file has only {len(ids)} usable patches; at least {MIN_PATCHES} are needed.")
    if len(set(ids)) != len(ids):
        raise ColourTargetError("The reference file repeats a patch id.")
    arr = np.asarray(vals, dtype=np.float64)
    notes = []
    if kind == "lab":
        arr = lab_to_xyz(arr)
        notes.append("Reference colours were given as Lab and converted to XYZ (D50).")
    elif arr[:, 1].max() > 2.0:
        arr = arr / 100.0
    if not np.isfinite(arr).all() or (arr < -0.01).any():
        raise ColourTargetError("The reference colours contain values that are not valid.")
    return TargetReference(title or "colour target", tuple(ids), arr, tuple(notes))


# --- locating and reading the patches -----------------------------------------------------------------------------------------------

def grid_ids(cols: int, rows: int) -> list[str]:
    """Row-major ids for a patch array: row letters A, B, ... and column numbers 1, 2, ... (A1 ... L22 for an IT8.7)."""
    letters = [chr(ord("A") + r) for r in range(rows)]
    return [f"{letters[r]}{c + 1}" for r in range(rows) for c in range(cols)]


def grid_patches(left: float, top: float, right: float, bottom: float, cols: int, rows: int, fill: float = 0.5, max_half: int = 200) -> list[Patch]:
    """Patch squares for an array whose outer edges are the given rectangle, row by row. `fill` is the share of each cell the sampled square takes."""
    if cols < 1 or rows < 1 or cols * rows < MIN_PATCHES:
        raise ColourTargetError(f"Give a grid of at least {MIN_PATCHES} patches.")
    if right - left < cols * 4 or bottom - top < rows * 4:
        raise ColourTargetError("The grid is too small for this many patches.")
    cw, ch = (right - left) / cols, (bottom - top) / rows
    half = int(max(1, min(max_half, round(min(cw, ch) * fill / 2))))
    return [Patch(r * cols + c, left + (c + 0.5) * cw, top + (r + 0.5) * ch, half) for r in range(rows) for c in range(cols)]


@dataclass(frozen=True)
class ColourFit:
    matrix: np.ndarray
    ids: tuple[str, ...]
    de_before: np.ndarray
    de_after: np.ndarray
    de_cv: float
    skipped: tuple[tuple[str, str], ...]
    verdict: str
    notes: tuple[str, ...]

    def summary(self) -> dict:
        def stats(d):
            return {"mean": float(d.mean()), "median": float(np.median(d)), "p95": float(np.percentile(d, 95)), "max": float(d.max())}
        return {"patches": len(self.ids), "matrix": [[float(x) for x in row] for row in self.matrix], "before": stats(self.de_before), "after": stats(self.de_after),
                "held_out_mean": self.de_cv, "verdict": self.verdict}


def measure_patches(framed: np.ndarray, patches: list[Patch], ids: list[str], reference: TargetReference, clear, floor=(0.0, 0.0, 0.0)):
    """Transmittances (fraction of clear light) of the patches that have a reference colour and a clean reading -> (ids, transmittance, reference XYZ, skipped)."""
    clear = np.asarray(clear, dtype=np.float64)
    if clear.shape != (3,) or (clear <= 0).any():
        raise ColourTargetError("A clear-light sample (the light with no film) is needed to turn the scan into transmittance.")
    lookup = {i: k for k, i in enumerate(reference.ids)}
    samples: list[PatchSample] = sample_patches(framed, patches, floor)
    keep_ids, t, xyz, skipped = [], [], [], []
    for pid, s in zip(ids, samples):
        if pid not in lookup:
            continue
        if not s.valid():
            skipped.append((pid, s.reasons[0]))
            continue
        keep_ids.append(pid)
        t.append(np.asarray(s.v) / clear)
        xyz.append(reference.xyz[lookup[pid]])
    return keep_ids, np.asarray(t), np.asarray(xyz), skipped


# --- the fit --------------------------------------------------------------------------------------------------------------------------

def _matrix(p: np.ndarray) -> np.ndarray:
    """The 3x3 matrix whose rows sum to the white point, from its six free numbers (the first two columns)."""
    m = np.empty((3, 3))
    m[:, :2] = p.reshape(3, 2)
    m[:, 2] = D50 - m[:, 0] - m[:, 1]
    return m


def _errors(p: np.ndarray, t: np.ndarray, xyz: np.ndarray) -> np.ndarray:
    return delta_e2000(xyz_to_lab(t @ _matrix(p).T), xyz_to_lab(xyz))


def _start(t: np.ndarray, xyz: np.ndarray) -> np.ndarray:
    a = t[:, :2] - t[:, [2]]
    p = []
    for i in range(3):
        sol, *_ = np.linalg.lstsq(a, xyz[:, i] - D50[i] * t[:, 2], rcond=None)
        p.extend(sol)
    return np.asarray(p)


def _refine(t: np.ndarray, xyz: np.ndarray, p: np.ndarray, iterations: int = 25) -> np.ndarray:
    """Levenberg-Marquardt on the Delta E 2000 of every patch, from the least-squares start."""
    lam = 1e-2
    cur = _errors(p, t, xyz)
    cost = float(cur @ cur)
    for _ in range(iterations):
        jac = np.empty((cur.size, p.size))
        for k in range(p.size):
            q = p.copy()
            step = 1e-5 * max(1.0, abs(p[k]))
            q[k] += step
            jac[:, k] = (_errors(q, t, xyz) - cur) / step
        g, h = jac.T @ cur, jac.T @ jac
        improved = False
        for _try in range(6):
            try:
                delta = np.linalg.solve(h + lam * np.diag(np.maximum(np.diag(h), 1e-9)), -g)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            trial = _errors(p + delta, t, xyz)
            if float(trial @ trial) < cost:
                p, cur, cost, lam, improved = p + delta, trial, float(trial @ trial), max(lam / 3, 1e-9), True
                break
            lam *= 4
        if not improved or np.abs(delta).max() < 1e-7:
            break
    return p


def fit_matrix(t: np.ndarray, xyz: np.ndarray, ids=None, skipped=()) -> ColourFit:
    t, xyz = np.asarray(t, dtype=np.float64), np.asarray(xyz, dtype=np.float64)
    n = len(t)
    if n < MIN_PATCHES:
        raise ColourTargetError(f"Only {n} patches could be used; at least {MIN_PATCHES} are needed.")
    ids = tuple(ids) if ids is not None else tuple(str(i) for i in range(n))
    p = _refine(t, xyz, _start(t, xyz))
    matrix = _matrix(p)
    before = delta_e2000(xyz_to_lab(t @ SRGB_TO_XYZ_D50.T), xyz_to_lab(xyz))
    after = _errors(p, t, xyz)
    order = np.random.default_rng(0).permutation(n)
    held = np.empty(n)
    for k in range(FOLDS):
        test = order[k::FOLDS]
        train = np.setdiff1d(order, test)
        pk = _refine(t[train], xyz[train], _start(t[train], xyz[train]), iterations=12)
        held[test] = _errors(pk, t[test], xyz[test])
    cv = float(held.mean())
    notes = []
    if skipped:
        notes.append(f"{len(skipped)} patches were left out because their reading was not clean (clipped, too dark, uneven or off the picture).")
    if cv > after.mean() * 1.5 + 0.5:
        notes.append("The error on patches the fit did not see is much larger than on the ones it did, so the result may not carry over to other colours.")
    if n < 24:
        notes.append("Few patches were used. A full target gives a steadier result.")
    verdict = "excellent" if after.mean() <= EXCELLENT and cv <= ACCEPTABLE else "acceptable" if after.mean() <= ACCEPTABLE else "poor"
    if verdict == "poor":
        notes.append("The error stays large. Check the grid position, the clear-light sample, and that the target was scanned with the same light and exposure.")
    return ColourFit(matrix, ids, before, after, cv, tuple(skipped), verdict, tuple(notes))


def describe(fit: ColourFit) -> str:
    s = fit.summary()
    lines = [f"{s['patches']} patches used.",
             f"Colour error (Delta E 2000), treating the camera channels as sRGB: mean {s['before']['mean']:.1f}, worst {s['before']['max']:.1f}.",
             f"After the fitted matrix: mean {s['after']['mean']:.1f}, 95% of patches under {s['after']['p95']:.1f}, worst {s['after']['max']:.1f}.",
             f"On patches held out of the fit: mean {fit.de_cv:.1f}.",
             {"excellent": "Verdict: excellent. A Delta E under about 2 is hard to see.", "acceptable": "Verdict: acceptable. Differences are visible side by side but small.",
              "poor": "Verdict: poor. Do not rely on this matrix."}[fit.verdict]]
    lines.extend(fit.notes)
    return "\n".join(lines)


def calibration_record(fit: ColourFit, reference: TargetReference, grid: dict, date: str) -> dict:
    """What is stored with a camera set-up so the result can be audited and reproduced."""
    return {"target": reference.name, "date": date, "grid": grid, "illuminant": "D50", "reference_notes": list(reference.notes), **fit.summary(),
            "meaning": "Transmittance (scan divided by clear light) to CIE XYZ relative to D50 clear light; rows sum to the white point."}
