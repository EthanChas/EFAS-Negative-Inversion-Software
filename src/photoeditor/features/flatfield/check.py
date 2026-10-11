"""Checking a flat field: how even a picture of the bare light is, and whether it would make a good reference.

A flat field only works if the reference shows the light and nothing else, and has not clipped. This measures, on a small copy of the picture:
- the smooth shading (the falloff the correction is for) in stops, centre against corners;
- blotchiness: small, local unevenness left after the smooth shading is taken out (dust, a mark on the light, picture content, grain), which the correction would copy into every frame;
- colour shading across the field;
- how much of it is clipped white or too dark to read.
It can be run on a reference shot, on any frame (to see how even the light is there), or on a frame after the folder's flat field is applied (to see what is left). numpy + OpenCV, no Qt."""

import math
from dataclasses import dataclass, field

import numpy as np

WORK = 256
SHADING_NOTE = 1.2
SHADING_ODD = 2.0
BLOTCH_FAIR = 0.025
BLOTCH_POOR = 0.05
COLOUR_FAIR = 0.25
CLIPPED_FAIR = 0.002
CLIPPED_POOR = 0.02
DARK_LEVEL = 30
GAIN_LIMITS = (0.26, 3.9)
LIMIT_SHARE_FAIR = 0.01


@dataclass
class FlatCheck:
    level: str
    headline: str
    findings: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.level == "good"

    def text(self) -> str:
        return "\n".join([self.headline, *["- " + f for f in self.findings]])


def _shrink(rgb: np.ndarray) -> np.ndarray:
    import cv2

    h, w = rgb.shape[:2]
    k = min(1.0, WORK / max(h, w))
    return cv2.resize(rgb, (max(8, round(w * k)), max(8, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1.0 else rgb


def _stops(hi: float, lo: float) -> float:
    return float(math.log2(max(hi, 1e-6) / max(lo, 1e-6)))


def measure(rgb8: np.ndarray) -> dict:
    """The numbers behind a check, from a uint8 RGB picture."""
    import cv2

    small = _shrink(np.ascontiguousarray(rgb8))
    lin = np.power(small.astype(np.float32) / 255.0, np.float32(2.2))
    lum = lin.mean(axis=2)
    h, w = lum.shape
    smooth = cv2.GaussianBlur(lum, (0, 0), max(h, w) / 14.0)
    lo, hi = np.percentile(smooth, [1, 99])
    cy, cx, ph, pw = h // 2, w // 2, max(2, h // 10), max(2, w // 10)
    centre = float(lum[cy - ph:cy + ph, cx - pw:cx + pw].mean())
    corners = float(np.mean([lum[:ph * 2, :pw * 2].mean(), lum[:ph * 2, -pw * 2:].mean(), lum[-ph * 2:, :pw * 2].mean(), lum[-ph * 2:, -pw * 2:].mean()]))
    local = cv2.GaussianBlur(lum, (0, 0), max(h, w) / 45.0)
    resid = lum / np.maximum(local, 1e-4) - 1.0
    mad = float(np.median(np.abs(resid - np.median(resid)))) * 1.4826
    spots = float((np.abs(resid) > 0.12).mean())
    chan = [cv2.GaussianBlur(lin[..., c], (0, 0), max(h, w) / 14.0) for c in range(3)]
    ratios = []
    for c in (0, 2):
        r = np.maximum(chan[c], 1e-5) / np.maximum(chan[1], 1e-5)
        a, b = np.percentile(r, [1, 99])
        ratios.append(_stops(b, a))
    return {
        "shading_stops": _stops(hi, lo), "falloff_stops": _stops(centre, corners), "blotchiness": mad, "spot_share": spots,
        "colour_shading_stops": max(ratios), "clipped": float((small.max(axis=2) >= 252).mean()), "median_level": float(np.median(small)),
        "dark": float((small.max(axis=2) < DARK_LEVEL).mean()),
    }


def check_picture(rgb8: np.ndarray, corrected: bool = False) -> FlatCheck:
    """How even a picture of the light is. `corrected` says the folder's flat field has already been applied, which changes what the shading means."""
    m = measure(rgb8)
    findings: list[str] = []
    poor = fair = False
    if m["clipped"] > CLIPPED_POOR:
        findings.append(f"{m['clipped'] * 100:.1f}% of the picture is clipped white, so the light's falloff cannot be read there. Expose lower and shoot it again.")
        poor = True
    elif m["clipped"] > CLIPPED_FAIR:
        findings.append(f"{m['clipped'] * 100:.2f}% is clipped white. A little is tolerable, but a lower exposure is safer.")
        fair = True
    if m["median_level"] < DARK_LEVEL or m["dark"] > 0.5:
        findings.append("The picture is very dark, so noise will be copied into the correction. Expose it brighter (without clipping).")
        fair = True
    if m["blotchiness"] > BLOTCH_POOR or m["spot_share"] > 0.03:
        findings.append(f"It is blotchy ({m['blotchiness'] * 100:.1f}% local unevenness): dust, a mark on the light, grain or picture content. A correction made from it would copy those marks "
                        "into every frame. Clean the light and use a plain, out-of-focus shot of it.")
        poor = True
    elif m["blotchiness"] > BLOTCH_FAIR or m["spot_share"] > 0.01:
        findings.append(f"It is a little blotchy ({m['blotchiness'] * 100:.1f}% local unevenness). Check the light for dust and marks.")
        fair = True
    if m["colour_shading_stops"] > COLOUR_FAIR:
        findings.append(f"The colour changes across the field by {m['colour_shading_stops']:.2f} stops (a tinted light or a colour-shifting lens). The correction evens out brightness "
                        "and colour together, so this is fine for a reference, but it will show as a cast if the picture is not corrected.")
    smooth = m["shading_stops"]
    if corrected:
        if smooth > 0.35:
            findings.append(f"After the flat field is applied, {smooth:.2f} stops of shading are still left (centre to corners {m['falloff_stops']:+.2f}). The reference may not match "
                            "these scans' light (different exposure, distance or lens setting). Make a new one with the same set-up.")
            fair = True
    elif smooth > SHADING_ODD:
        findings.append(f"The shading is very strong ({smooth:.1f} stops). The correction is limited to a factor of four, so it cannot even this out fully.")
        fair = True
    elif smooth > SHADING_NOTE:
        findings.append(f"The shading is {smooth:.1f} stops (centre to corners {m['falloff_stops']:+.2f}): strong, but within what the correction can fix.")
    level = "poor" if poor else "fair" if fair else "good"
    if corrected:
        headline = {"good": f"Even after correction: {smooth:.2f} stops of shading left.", "fair": "The correction leaves some unevenness.", "poor": "The corrected picture is still uneven or damaged."}[level]
    else:
        headline = {"good": f"A good flat field: smooth shading of {smooth:.2f} stops, no clipping, no marks.", "fair": "Usable, with things to check.", "poor": "Not a good reference."}[level]
    return FlatCheck(level, headline, findings, m)


def check_gain(gain: np.ndarray) -> FlatCheck:
    """A finished gain map (what the correction multiplies by): whether it is capped, and how strong it is."""
    g = np.asarray(gain, dtype=np.float32)
    lo_share = float((g <= GAIN_LIMITS[0]).mean())
    hi_share = float((g >= GAIN_LIMITS[1]).mean())
    stops = _stops(float(np.percentile(g, 99)), float(np.percentile(g, 1)))
    findings: list[str] = []
    level = "good"
    if lo_share + hi_share > LIMIT_SHARE_FAIR:
        findings.append(f"{(lo_share + hi_share) * 100:.1f}% of the correction hits its limit (a factor of four). The light is too uneven for the correction to even out there.")
        level = "fair"
    if stops > SHADING_ODD:
        findings.append(f"The correction is strong ({stops:.1f} stops from its weakest to strongest). Frames will carry more noise at the edges.")
        level = "fair"
    headline = f"The correction ranges over {stops:.2f} stops." if level == "good" else "The correction is strong or capped."
    return FlatCheck(level, headline, findings, {"gain_stops": stops, "at_limit": lo_share + hi_share})
