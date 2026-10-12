"""The written read-out under the histogram: exposure, tonal range, contrast, clipping and colour in words and numbers - numpy only, no Qt/UI imports.

`tonal_readout` measures a picture once (cheap: it works on the histogram sample the stats already use); the `*_text` functions turn the numbers into the
short lines the panel shows, so what is said about a picture is decided here and can be tested."""

import numpy as np

_LUMA = np.array((0.299, 0.587, 0.114), dtype=np.float32)
SHADOW_CLIP = 3
HIGHLIGHT_CLIP = 252
SHADOW_LIMIT = 64
HIGHLIGHT_LIMIT = 192


def tonal_readout(pixels: np.ndarray) -> dict:
    """Numbers describing a uint8 RGB picture: brightness percentiles, spread, how much sits in the shadows / midtones / highlights, how much is
    clipped, the average colour and how saturated it is."""
    flat = pixels.reshape(-1, 3)
    luma = flat.astype(np.float32) @ _LUMA
    total = float(luma.size)
    p1, p5, p25, p50, p75, p95, p99 = (float(v) for v in np.percentile(luma, (1, 5, 25, 50, 75, 95, 99)))
    shadows = float((luma < SHADOW_LIMIT).sum()) / total * 100.0
    highlights = float((luma >= HIGHLIGHT_LIMIT).sum()) / total * 100.0
    means = flat.mean(axis=0)
    top = flat.max(axis=1).astype(np.float32)
    low = flat.min(axis=1).astype(np.float32)
    lit = top > 12
    saturation = float(((top - low)[lit] / top[lit]).mean()) if lit.any() else 0.0
    return {
        "mean": float(luma.mean()), "median": p50, "std": float(luma.std()),
        "p1": p1, "p5": p5, "p25": p25, "p75": p75, "p95": p95, "p99": p99,
        "shadows_pct": shadows, "midtones_pct": max(0.0, 100.0 - shadows - highlights), "highlights_pct": highlights,
        "blocked_pct": float((luma <= SHADOW_CLIP).sum()) / total * 100.0, "blown_pct": float((luma >= HIGHLIGHT_CLIP).sum()) / total * 100.0,
        "r": float(means[0]), "g": float(means[1]), "b": float(means[2]), "saturation": saturation,
    }


# ---- words ----

def exposure_verdict(mean: float, p50: float | None = None) -> str:
    """Under, well or over exposed, from the average brightness (the same cut-offs the label has always used)."""
    if mean < 60:
        return "Underexposed"
    if mean > 190:
        return "Overexposed"
    return "Well exposed"


def contrast_label(r: dict) -> str:
    """Flat to harsh, from how far apart the dark and bright ends sit (the 5th to 95th percentile) and how much the tones vary."""
    spread = r["p95"] - r["p5"]
    if spread < 70:
        return "Very flat"
    if spread < 110:
        return "Flat"
    if spread < 175:
        return "Normal"
    if spread < 215:
        return "Punchy"
    return "Harsh"


def range_label(r: dict) -> str:
    """How much of the 0-255 scale the picture really uses (1st to 99th percentile)."""
    used = r["p99"] - r["p1"]
    if used >= 215:
        return "Full range"
    if used >= 150:
        return "Good range"
    return "Narrow range"


def cast_label(r: dict) -> str:
    """The average colour of the picture in words: neutral, or warm / cool and green / magenta by how far it leans. A picture of a red wall will say warm - it is a
    read on the picture, not a judgement of the white balance."""
    mean = max((r["r"] + r["g"] + r["b"]) / 3.0, 1.0)
    warmth = (r["r"] - r["b"]) / mean
    tint = (r["g"] - (r["r"] + r["b"]) / 2.0) / mean
    parts = []
    for value, plus, minus in ((warmth, "warm", "cool"), (tint, "green", "magenta")):
        size = abs(value)
        if size >= 0.04:
            parts.append(("strongly " if size >= 0.15 else "slightly " if size < 0.08 else "") + (plus if value > 0 else minus))
    return "Neutral" if not parts else ", ".join(parts).capitalize()


def saturation_label(s: float) -> str:
    if s < 0.08:
        return "Monochrome"
    if s < 0.22:
        return "Muted"
    if s < 0.5:
        return "Natural"
    if s < 0.7:
        return "Vivid"
    return "Very vivid"


def _pct(v: float) -> str:
    return f"{v:.0f}%" if v >= 9.5 or v == 0 else f"{v:.1f}%"


def exposure_lines(r: dict) -> list[tuple[str, str]]:
    return [
        ("Exposure", f"{exposure_verdict(r['mean'])}, {r['mean']:.0f}"),
        ("Median", f"{r['median']:.0f}  ({r['median'] / 255 * 100:.0f}%)"),
        ("Range", f"{range_label(r).replace(' range', '')}, {r['p1']:.0f}-{r['p99']:.0f}"),
        ("Dark / mid / light", f"{_pct(r['shadows_pct'])} / {_pct(r['midtones_pct'])} / {_pct(r['highlights_pct'])}"),
    ]


def contrast_lines(r: dict) -> list[tuple[str, str]]:
    return [
        ("Contrast", contrast_label(r)),
        ("Spread", f"{r['p95'] - r['p5']:.0f} of 255"),
        ("Deviation", f"{r['std']:.0f}"),
    ]


def clipping_lines(r: dict) -> list[tuple[str, str]]:
    return [
        ("Blocked shadows", _pct(r["blocked_pct"])),
        ("Blown highlights", _pct(r["blown_pct"])),
    ]


def colour_lines(r: dict) -> list[tuple[str, str]]:
    return [
        ("Average", cast_label(r)),
        ("Saturation", f"{saturation_label(r['saturation'])}, {r['saturation']:.2f}"),
    ]


def scan_lines(mode: str, inverted: bool, base: tuple | None, engine: str, profile_name: str, metering: str) -> list[tuple[str, str]]:
    """The negative's own grading lines - what the Negative tab reports, in one place: what it was recognised as, the film base, the inversion method and how
    it is metered."""
    kinds = {"c41": "Colour negative", "bw": "Black & white negative", "e6": "Slide"}
    what = kinds.get(mode, "")
    if what:
        what += ", inverted" if inverted and mode != "e6" else ", not inverted" if mode != "e6" else ""
    if base is None:
        base_text = "Auto-estimated"
    else:
        base_text = f"Sampled ({base[0]}, {base[1]}, {base[2]})"
    method = "Curve-informed" + (f": {profile_name}" if profile_name else "") if engine == "curve" else "Standard"
    lines = []
    if what:
        lines.append(("Type", what))
    lines += [("Film base", base_text), ("Inversion", method)]
    if metering:
        lines.append(("Metering", metering))
    return lines


def metering_text(buffer: float, rect, range_clip: float, white: float, black: float) -> str:
    """How the black and white points are read, in a few words."""
    where = "drawn region" if rect else f"whole frame less {buffer * 100:.0f}% margin"
    extras = []
    if range_clip:
        extras.append(f"range clip {range_clip:g}")
    if white or black:
        extras.append("points moved")
    return where + ("; " + ", ".join(extras) if extras else "")
