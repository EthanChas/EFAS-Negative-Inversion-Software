"""Fit EFAS's Print Response (Snap, Toe, Shoulder and their widths) to NegPy's darkroom paper profiles.

NegPy (GPL-3.0, https://github.com/marcinz606/NegPy) describes a paper by a few constants of its characteristic curve (d_max, d_min, how sharp the toe and the shoulder are, the midtone gamma).
EFAS's Print Response reshapes the finished tones with five sliders instead. This tool finds the five slider values that make EFAS's neutral picture look like the same picture printed
on each NegPy paper: for the same range of negative exposures it takes NegPy's neutral paper and NegPy's paper (both through its own CharacteristicCurve, at NegPy's default grade, pivot,
black point compensation and Paper White off), turns each into display tones, and fits EFAS's apply_print_response to the way the first becomes the second.

Only the tone curve is carried over: NegPy's colour terms (the RA4 papers' channel gamma, dye matrix and base tint, and every paper's lith colour path) have no place in Print Response.

Usage:  python tools/fit_negpy_papers.py <the folder of NegPy's source, with negpy/ in it>      (prints the presets as JSON and each fit's error)
"""
import json
import sys

import numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, "src")

from photoeditor.features.printresponse import logic as pr  # noqa: E402

PAPERS = ("ilford_mg_rc", "ilford_fb_classic", "foma_fomatone", "foma_fomabrom", "kodak_endura", "fuji_crystal")
LOW, HIGH = (-0.5, -1.0, 0.1, -1.0, 0.1), (0.5, 1.0, 5.0, 1.0, 5.0)


def negpy_tones(root: str) -> dict:
    """{paper key: (neutral display tones, the paper's display tones)} over the same exposures, from NegPy's own code, in 0..255."""
    sys.path.insert(0, root)
    from negpy.features.exposure.logic import CharacteristicCurve, grade_to_slope
    from negpy.features.exposure.models import EXPOSURE_CONSTANTS, ExposureConfig
    from negpy.features.exposure.papers import PAPER_PROFILES
    from negpy.kernel.image.logic import working_oetf_encode

    slope = grade_to_slope(ExposureConfig().grade, None)
    pivot = float(EXPOSURE_CONSTANTS["assumed_anchor"])
    x = np.linspace(0.0, 1.0, 801, dtype=np.float32)

    def tones(profile) -> np.ndarray:
        curve = CharacteristicCurve(contrast=slope, pivot=pivot, d_min=0.0, paper=profile, bpc=True)
        density = np.asarray(curve(x))
        return np.asarray(working_oetf_encode(np.power(10.0, -density).astype(np.float32))).reshape(-1).astype(np.float64) * 255.0

    neutral = tones(PAPER_PROFILES["neutral"])
    return {key: (neutral, tones(PAPER_PROFILES[key])) for key in PAPERS}, {key: PAPER_PROFILES[key].label for key in PAPERS}


def fit(neutral: np.ndarray, paper: np.ndarray):
    def residual(p):
        return (pr.apply_print_response(neutral, p[0], p[1], p[2], p[3], p[4]) - paper) / 255.0

    best = None
    rng = np.random.default_rng(0)
    for start in [pr.DEFAULTS_VECTOR if hasattr(pr, "DEFAULTS_VECTOR") else (0.0, 0.0, 2.5, 0.0, 2.5)] + [tuple(rng.uniform(LOW, HIGH)) for _ in range(24)]:
        try:
            r = least_squares(residual, start, bounds=(LOW, HIGH))
        except Exception:
            continue
        if best is None or r.cost < best.cost:
            best = r
    p = best.x
    err = np.abs(residual(p)) * 255.0
    return p, float(np.sqrt(np.mean(err ** 2))), float(err.max())


def main() -> None:
    all_tones, labels = negpy_tones(sys.argv[1])
    out = []
    for key in PAPERS:
        neutral, paper = all_tones[key]
        base_gap = float(np.sqrt(np.mean((neutral - paper) ** 2)))
        p, rms, worst = fit(neutral, paper)
        print(f"{labels[key]:32s} paper differs from neutral by {base_gap:5.2f} (rms levels); after the fit {rms:5.2f} rms, {worst:5.2f} worst; "
              f"snap {p[0]:+.3f} toe {p[1]:+.3f} w {p[2]:.2f} shoulder {p[3]:+.3f} w {p[4]:.2f}", file=sys.stderr)
        out.append({"key": key, "label": labels[key], "print_snap": round(float(p[0]), 3), "print_toe": round(float(p[1]), 3), "print_toe_width": round(float(p[2]), 2),
                    "print_shoulder": round(float(p[3]), 3), "print_shoulder_width": round(float(p[4]), 2), "rms": round(rms, 2), "gap": round(base_gap, 2)})
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
