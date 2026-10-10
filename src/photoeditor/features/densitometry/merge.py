"""Merging several scans of one frame into one measurement-grade linear scan: a bracket of exposure times (to reach denser areas than one exposure can), or three
scans lit by separate red, green and blue light (one clean channel from each). Numpy and OpenCV only, no Qt/UI.

Bracket maths: each frame i gives v_i = k t_i T + noise (clipped at the sensor's top). In the reference frame's units the estimate from frame i is v_i t_ref / t_i with
variance (t_ref / t_i)^2 (sigma_i^2 + s v_i), so a longer exposure is far less noisy in the dark parts of the negative. The merge is the inverse-variance weighted
average over the frames in which the pixel is neither clipped nor at the noise floor. Frames are aligned by translation only (a tripod is assumed).
"""

import json
import os
from dataclasses import dataclass, field

import numpy as np

from .linear import LinearScan, ScanInfo

CLIP_LEVEL = 0.95
FLOOR_FACTOR = 1.5
SHOT_TERM = 2e-5
MIN_TIME_RATIO = 1.05
MAX_SHIFT = 25.0
MIN_RESPONSE = 0.15
FILL_SIGMA = 10
RATIO_WARN = 0.02
TARGET_TOP = 0.92
SIDECAR_SUFFIX = ".efas-merge.json"
SIDECAR_FORMAT = "efas-merged-scan"
SIDECAR_VERSION = 1


class MergeError(ValueError):
    """The scans cannot be merged, with the reason."""


@dataclass(frozen=True)
class MergeResult:
    scan: LinearScan
    kind: str
    sources: tuple[str, ...]
    times: tuple[float, ...]
    shifts: tuple[tuple[float, float], ...]
    ratios: tuple[float, ...]
    contribution: tuple[float, ...]
    lost_fraction: float
    noise_gain: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


# --- alignment ----------------------------------------------------------------------------------------------------------------------

def estimate_shift(ref: np.ndarray, img: np.ndarray, max_dim: int = 800) -> tuple[float, float, float]:
    """How far `img` has moved relative to `ref`, as (dx, dy, response), by phase correlation of two single-channel pictures (response ~1 is a clean match)."""
    import cv2

    h, w = ref.shape
    scale = min(1.0, max_dim / max(h, w))
    a, b = np.ascontiguousarray(ref, dtype=np.float32), np.ascontiguousarray(img, dtype=np.float32)
    if scale < 1.0:
        size = (max(16, round(w * scale)), max(16, round(h * scale)))
        a, b = cv2.resize(a, size, interpolation=cv2.INTER_AREA), cv2.resize(b, size, interpolation=cv2.INTER_AREA)
    a, b = a - a.mean(), b - b.mean()
    window = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a, b, window)
    dx, dy = _refine_shift(a, b, float(dx), float(dy))
    return float(dx / scale), float(dy / scale), float(response)


def _refine_shift(a: np.ndarray, b: np.ndarray, dx: float, dy: float) -> tuple[float, float]:
    """Sharpen the phase-correlation estimate to a fraction of a pixel by enhanced correlation on the high-passed pictures; keeps the estimate when that does not converge."""
    import cv2

    a, b = a - cv2.GaussianBlur(a, (0, 0), 8), b - cv2.GaussianBlur(b, (0, 0), 8)
    warp = np.float32([[1, 0, dx], [0, 1, dy]])
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6)
    try:
        _cc, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_TRANSLATION, criteria, None, 5)
    except cv2.error:
        return dx, dy
    rx, ry = float(warp[0, 2]), float(warp[1, 2])
    if not (np.isfinite(rx) and np.isfinite(ry)) or abs(rx - dx) > 3.0 or abs(ry - dy) > 3.0:
        return dx, dy
    return rx, ry


def shift_image(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """`img` moved by (-dx, -dy), undoing a measured shift (bilinear, edges replicated)."""
    import cv2

    if abs(dx) < 1e-3 and abs(dy) < 1e-3:
        return img
    m = np.float32([[1, 0, -dx], [0, 1, -dy]])
    return cv2.warpAffine(np.ascontiguousarray(img), m, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _structure(v: np.ndarray, valid: np.ndarray | None = None) -> np.ndarray:
    """A picture of the negative's structure that does not depend on exposure or colour: log density, with blown or empty places filled smoothly from their surroundings (a flat patch would stay put while the picture moves and bias the alignment)."""
    import cv2

    g = np.log(np.maximum(v, 1e-6)).astype(np.float32)
    if valid is not None and valid.any() and not valid.all():
        m = valid.astype(np.float32)
        weight = cv2.GaussianBlur(m, (0, 0), FILL_SIGMA)
        fill = cv2.GaussianBlur(g * m, (0, 0), FILL_SIGMA) / np.maximum(weight, 1e-4)
        g = np.where(valid, g, np.where(weight > 1e-3, fill, np.median(g[valid])))
    return g


# --- exposure brackets --------------------------------------------------------------------------------------------------------------

def merge_exposures(scans: list[LinearScan], times: list[float], labels: list[str] | None = None, align: bool = True, calibrate_times: bool = False) -> MergeResult:
    """Merge scans of one frame taken with different exposure times. Output is in the units of the shortest exposure (whose film base should not be clipped)."""
    if len(scans) < 2 or len(scans) != len(times):
        raise MergeError("Give at least two scans, each with its exposure time.")
    t = np.asarray(times, dtype=np.float64)
    if (t <= 0).any() or not np.isfinite(t).all():
        raise MergeError("Exposure times must be positive numbers.")
    order = np.argsort(t, kind="stable")
    scans = [scans[i] for i in order]
    labels = [(labels or [f"frame {i + 1}" for i in range(len(scans))])[i] for i in order]
    t = t[order]
    if (np.diff(t) / t[:-1] < MIN_TIME_RATIO - 1).any():
        raise MergeError("Two exposures are nearly the same length, so the second adds nothing. Use clearly different exposure times.")
    shape = scans[0].rgb.shape
    if any(s.rgb.shape != shape for s in scans):
        raise MergeError("The scans are not the same size.")
    warnings: list[str] = []
    ref_t = t[0]
    rgb = [s.rgb.astype(np.float32) for s in scans]
    floors = [np.asarray(s.info.floor(), dtype=np.float64) for s in scans]
    shifts = [(0.0, 0.0)]
    if align:
        base_g = _structure(rgb[0][..., 1] / ref_t, rgb[0][..., 1] < CLIP_LEVEL)
        for i in range(1, len(rgb)):
            g = _structure(rgb[i][..., 1] / t[i], rgb[i][..., 1] < CLIP_LEVEL)
            dx, dy, resp = estimate_shift(base_g, g)
            if resp < MIN_RESPONSE:
                warnings.append(f"{labels[i]}: the match to the first frame was weak, so it was not shifted. Check that the frames show the same area.")
                shifts.append((0.0, 0.0))
            elif max(abs(dx), abs(dy)) > MAX_SHIFT:
                warnings.append(f"{labels[i]}: it moved {max(abs(dx), abs(dy)):.0f} pixels from the first frame, more than a steady tripod would allow, so it was not shifted.")
                shifts.append((0.0, 0.0))
            else:
                rgb[i] = np.stack([shift_image(rgb[i][..., c], dx, dy) for c in range(3)], axis=-1)
                shifts.append((dx, dy))
                if max(abs(dx), abs(dy)) > 2.0:
                    warnings.append(f"{labels[i]} was shifted by about {max(abs(dx), abs(dy)):.1f} pixels. A tripod gives a cleaner merge.")
    else:
        shifts = [(0.0, 0.0)] * len(rgb)
    ratios = [1.0]
    eff = t.copy()
    mid = (rgb[0] > 0.05) & (rgb[0] < 0.5)
    for i in range(1, len(rgb)):
        both = mid & (rgb[i] < CLIP_LEVEL) & (rgb[i] > 0.02)
        if both.sum() < 1000:
            ratios.append(float("nan"))
            warnings.append(f"{labels[i]}: too few pixels in common with the first frame to check its exposure time.")
            continue
        r = float(np.median((rgb[i][both] / rgb[0][both]) * (ref_t / t[i])))
        ratios.append(r)
        if abs(r - 1.0) > RATIO_WARN:
            warnings.append(f"{labels[i]}: its signal is {abs(r - 1) * 100:.1f}% {'higher' if r > 1 else 'lower'} than its exposure time predicts. The time may be rounded, the light may "
                            "flicker or fade, or the sensor may not be linear here.")
            if calibrate_times:
                eff[i] = t[i] * r
    num = np.zeros(shape, dtype=np.float64)
    den = np.zeros(shape, dtype=np.float64)
    used = []
    for i in range(len(rgb)):
        v = rgb[i].astype(np.float64)
        valid = (v < CLIP_LEVEL) & (v > floors[i] * FLOOR_FACTOR)
        gain = ref_t / eff[i]
        sigma = np.asarray(scans[i].info.noise_sigma or (1e-4,) * 3, dtype=np.float64)
        var = (gain ** 2) * (sigma ** 2 + SHOT_TERM * np.maximum(v, 0.0))
        w = np.where(valid, 1.0 / var, 0.0)
        num += w * v * gain
        den += w
        used.append(w)
    fallback = den <= 0
    merged = np.where(fallback, rgb[0].astype(np.float64), num / np.where(fallback, 1.0, den))
    total = np.maximum(np.sum(used, axis=0), 1e-30)
    contribution = tuple(float(np.mean(w / total)) for w in used)
    lost = float(fallback.any(axis=2).mean())
    sig0 = np.asarray(scans[0].info.noise_sigma or (1e-4,) * 3, dtype=np.float64)
    inv_var = sum(((eff[i] / eff[0]) ** 2) / np.asarray(scans[i].info.noise_sigma or (1e-4,) * 3, dtype=np.float64) ** 2 for i in range(len(rgb)))
    sigma_eff = 1.0 / np.sqrt(inv_var)
    gain_x = float(np.mean(sig0 / sigma_eff))
    if lost > 0.001:
        warnings.append(f"{lost * 100:.1f}% of the picture was clipped or at the noise floor in every frame. Add a longer or a shorter exposure to cover it.")
    first = scans[0].info
    info = ScanInfo(
        measured=True, encoding="merged-linear", bit_depth=first.bit_depth, white=1.0, black=(), quantisation=min(s.info.quantisation * ref_t / eff[i] for i, s in enumerate(scans)),
        noise_sigma=tuple(float(x) for x in sigma_eff), saturated_fraction=lost, camera=first.camera,
        steps=(f"Merged {len(scans)} exposures ({', '.join(f'{x:g} s' for x in t)}) in linear light, in the units of the {t[0]:g} s frame",
               "Each pixel is the inverse-variance weighted average over the frames where it was neither clipped nor at the noise floor",
               f"Effective read noise {gain_x:.1f} times lower than the {t[0]:g} s frame alone") + tuple(first.steps[:1]),
    )
    return MergeResult(LinearScan(merged.astype(np.float32), info), "bracket", tuple(labels), tuple(float(x) for x in t), tuple(shifts), tuple(ratios), contribution, lost,
                       gain_x, tuple(warnings))


# --- one light per channel ----------------------------------------------------------------------------------------------------------

def merge_channels(red: LinearScan, green: LinearScan, blue: LinearScan, labels: list[str] | None = None, align: bool = True) -> MergeResult:
    """Three scans, each lit by one colour of light: take the red channel of the red-lit scan, the green of the green-lit one, the blue of the blue-lit one."""
    scans = [red, green, blue]
    shape = red.rgb.shape
    if any(s.rgb.shape != shape for s in scans):
        raise MergeError("The three scans are not the same size.")
    labels = labels or ["red light", "green light", "blue light"]
    warnings: list[str] = []
    planes = [s.rgb[..., c].astype(np.float32) for c, s in enumerate(scans)]
    shifts = [(0.0, 0.0)]
    if align:
        ref = _structure(planes[1], planes[1] < CLIP_LEVEL)
        shifts = []
        for i in (0, 1, 2):
            if i == 1:
                shifts.append((0.0, 0.0))
                continue
            g = _structure(planes[i], planes[i] < CLIP_LEVEL)
            dx, dy, resp = estimate_shift(ref, g)
            if resp < MIN_RESPONSE or max(abs(dx), abs(dy)) > MAX_SHIFT:
                warnings.append(f"{labels[i]}: it could not be matched to the green-lit scan, so it was not shifted.")
                shifts.append((0.0, 0.0))
            else:
                planes[i] = shift_image(planes[i], dx, dy)
                shifts.append((dx, dy))
    else:
        shifts = [(0.0, 0.0)] * 3
    for i, p in enumerate(planes):
        clipped = float((p >= CLIP_LEVEL).mean())
        if clipped > 0.005:
            warnings.append(f"{labels[i]}: {clipped * 100:.1f}% of its channel is clipped. Use less light for that colour.")
        if float(np.percentile(p, 99.5)) < 0.1:
            warnings.append(f"{labels[i]}: its channel is very dim (the film base reads under 10% of the sensor's range). More light would reduce the noise.")
    merged = np.stack(planes, axis=-1)
    sig = tuple(float((s.info.noise_sigma or (1e-4,) * 3)[c]) for c, s in enumerate(scans))
    info = ScanInfo(
        measured=True, encoding="merged-linear", bit_depth=red.info.bit_depth, white=1.0, black=(), quantisation=max(s.info.quantisation for s in scans), noise_sigma=sig,
        saturated_fraction=float((merged >= CLIP_LEVEL).any(axis=2).mean()), camera=red.info.camera,
        steps=("Merged three scans lit by separate red, green and blue light: each colour comes from the scan lit by it, which avoids crosstalk between the colour channels",
               "Each channel is normalised to its own scan's sensor range; the film base is measured per channel",),
    )
    return MergeResult(LinearScan(merged, info), "channels", tuple(labels), (), tuple(shifts), (), (1 / 3, 1 / 3, 1 / 3), 0.0, 1.0, tuple(warnings))


# --- the merged file ----------------------------------------------------------------------------------------------------------------

def sidecar_path(tiff_path: str) -> str:
    return tiff_path + SIDECAR_SUFFIX


def is_merged_scan(path: str) -> bool:
    return os.path.isfile(sidecar_path(path))


def save_merged(result: MergeResult, tiff_path: str) -> str:
    """Write the merged scan as a 16-bit linear TIFF plus a sidecar that says how to read it back (scale, noise, sources, warnings). Returns the sidecar path."""
    import cv2

    v = result.scan.rgb
    top = min(float(v.max()), 1.25 * float(np.percentile(v, 99.9)))
    scale = TARGET_TOP / top if top > 0 else 1.0
    codes = np.round(np.clip(v * scale, 0.0, 1.0) * 65535.0).astype(np.uint16)
    os.makedirs(os.path.dirname(tiff_path) or ".", exist_ok=True)
    tmp = tiff_path + ".part.tif"
    try:
        if not cv2.imwrite(tmp, np.ascontiguousarray(codes[..., ::-1]), [cv2.IMWRITE_TIFF_COMPRESSION, 5]):
            raise OSError("the merged TIFF could not be written")
        os.replace(tmp, tiff_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    info = result.scan.info
    side = {
        "format": SIDECAR_FORMAT, "version": SIDECAR_VERSION, "kind": result.kind, "code_to_value_scale": 1.0 / scale, "shape": [int(v.shape[0]), int(v.shape[1])],
        "noise_sigma": list(info.noise_sigma) if info.noise_sigma else None, "quantisation": 1.0 / scale / 65535.0, "saturated_fraction": info.saturated_fraction,
        "bit_depth": info.bit_depth, "sources": list(result.sources), "times": list(result.times), "shifts": [list(s) for s in result.shifts],
        "ratios": [None if not np.isfinite(r) else r for r in result.ratios], "warnings": list(result.warnings), "steps": list(info.steps),
        "noise_gain": result.noise_gain, "camera": info.camera,
    }
    path = sidecar_path(tiff_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(side, f, indent=2)
    return path


def load_merged(tiff_path: str) -> LinearScan | None:
    """The merged scan saved beside `tiff_path`, as linear values with their noise estimate; None when there is no valid sidecar for this exact file."""
    import cv2

    side_file = sidecar_path(tiff_path)
    if not os.path.isfile(side_file):
        return None
    try:
        with open(side_file, "r", encoding="utf-8") as f:
            side = json.load(f)
        if side.get("format") != SIDECAR_FORMAT or int(side.get("version", 0)) > SIDECAR_VERSION:
            return None
        codes = cv2.imread(tiff_path, cv2.IMREAD_UNCHANGED | cv2.IMREAD_ANYDEPTH | cv2.IMREAD_ANYCOLOR)
        if codes is None or codes.dtype != np.uint16 or list(codes.shape[:2]) != side["shape"] or codes.ndim != 3:
            return None
        scale = float(side["code_to_value_scale"])
        rgb = (codes[..., :3][..., ::-1].astype(np.float32) / 65535.0) * np.float32(scale)
        sigma = tuple(float(x) for x in side["noise_sigma"]) if side.get("noise_sigma") else None
        info = ScanInfo(True, "merged-linear", int(side.get("bit_depth", 14)), 1.0, (), float(side["quantisation"]), sigma, float(side.get("saturated_fraction", 0.0)),
                        str(side.get("camera", "")), tuple(str(s) for s in side.get("steps", ())))
        return LinearScan(rgb, info)
    except (OSError, ValueError, KeyError, TypeError):
        return None
