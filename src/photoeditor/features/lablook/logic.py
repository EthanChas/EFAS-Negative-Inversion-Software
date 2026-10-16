"""Lab Look: the character a lab's scanner adds to a print - a soft black, compressed highlights and a warm or cool cast that differs between shadows, midtones and highlights -
numpy only, no Qt. What a lab look is, from published sources, is in docs/lab-look-research.md.

All three are curves of the tone ramp, so they cost nothing per picture and keep the 16-bit tone chain. Fade compresses (+) or expands (-) the tonality of the shadows and Glow
compresses (+) or expands (-) the tonality of the highlights, as the program the presets were converted from describes its own sliders; the curve shapes were measured from that
program's output at the ends of its sliders (docs/presets.md). Glow is not a blur: with the black and the top held, squeezing the highlights lifts the midtones to make room.
Both sliders run -1 to +1, which is that program's -50 to +50."""

import numpy as np

from ..color.logic import _TEMP_TINT_STRENGTH

KEYS = ("lab_fade", "lab_glow", "lab_by_shadows", "lab_by_mids", "lab_by_highs", "lab_gm_shadows", "lab_gm_mids", "lab_gm_highs")
DEFAULTS = {key: 0.0 for key in KEYS}
RESPONSE_KEYS = ("lab_response", "lab_response_amount")   # the scanner colour response (features/colormix/logic.py) and how much of it
ALL_KEYS = KEYS + RESPONSE_KEYS
ALL_DEFAULTS = {**DEFAULTS, "lab_response": "none", "lab_response_amount": 1.0}
FADE_RANGE = (-1.0, 1.0)   # + compresses the shadows (a lifted, matte black), - expands them (a deeper black, more shadow contrast)
GLOW_RANGE = (-1.0, 1.0)   # + compresses the highlights (the midtones rise to make room), - expands them (a starker look); the black and the top stay
BALANCE_RANGE = (-1.0, 1.0)
FADE_LIFT = 50.0           # display levels the black rises by at Fade = +1
FADE_LIFT_POWER = 5.0      # how quickly the lift dies away with brightness (kept low enough that tones never reverse: lift x power < 255)
FADE_BRIGHTEN = 36.0       # display levels the lower midtones rise by at Fade = -1
FADE_SINK = 12.0           # display levels the very darkest tones drop by at Fade = -1
GLOW_LIFT = 25.0           # display levels the midtones move by at Glow = +/-1


def is_neutral(values: dict | tuple | None = None, **kw) -> bool:
    """True when every Lab Look value is at its default (the ramp and the picture are then returned untouched)."""
    if isinstance(values, dict):
        return all(abs(float(values.get(k, 0.0))) < 1e-9 for k in KEYS)
    if values is not None:
        return all(abs(float(v)) < 1e-9 for v in values)
    return all(abs(float(kw.get(k, 0.0))) < 1e-9 for k in KEYS)


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def tone_weights(tone: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """How much each of the three tonal ranges counts at a tone (0-1): smooth overlapping ranges, shadows and highlights at the ends and the midtones between."""
    shadows = 1.0 - _smoothstep(0.15, 0.60, tone)
    highs = _smoothstep(0.40, 0.85, tone)
    mids = np.clip(1.0 - shadows - highs, 0.0, 1.0)
    return shadows, mids, highs


def _bump(x: np.ndarray, rise: tuple[float, float], fall: tuple[float, float] | None = None) -> np.ndarray:
    out = _smoothstep(rise[0], rise[1], x)
    return out if fall is None else out * (1.0 - _smoothstep(fall[0], fall[1], x))


def apply_lab_tone(display: np.ndarray, fade: float, by: tuple[float, float, float], gm: tuple[float, float, float], glow: float = 0.0) -> np.ndarray:
    """`display`: tone values on the 0..255 display scale, last axis the three channels (a ramp or a picture) -> the same scale with the lab look laid in: the colour balance by
    tone (`by`, `gm`: blue-yellow, + warmer, and green-magenta, + toward magenta, each as (shadows, mids, highlights)), then Glow, then Fade. Neutral values return the input
    untouched."""
    if fade == 0.0 and glow == 0.0 and not any(by) and not any(gm):
        return display
    out = np.asarray(display, dtype=np.float32).copy()
    if any(by) or any(gm):
        tone = np.clip(out.mean(axis=-1, keepdims=True) / 255.0, 0.0, 1.0)
        ws, wm, wh = tone_weights(tone)
        temp = by[0] * ws + by[1] * wm + by[2] * wh
        tint = gm[0] * ws + gm[1] * wm + gm[2] * wh
        s = np.float32(_TEMP_TINT_STRENGTH)
        out[..., 0] += (temp * s + tint * s * 0.5)[..., 0]
        out[..., 1] -= (tint * s)[..., 0]
        out[..., 2] += (-temp * s + tint * s * 0.5)[..., 0]
    x = np.clip(out / 255.0, 0.0, 1.0)
    if glow != 0.0:
        out = out + float(np.clip(glow, -1.0, 1.0)) * GLOW_LIFT * _bump(x, (0.12, 0.40), (0.55, 0.80))
        x = np.clip(out / 255.0, 0.0, 1.0)
    if fade > 0.0:
        out = out + min(fade, 1.0) * FADE_LIFT * np.power(1.0 - x, FADE_LIFT_POWER)
    elif fade < 0.0:
        g = min(-fade, 1.0)
        out = out + g * (FADE_BRIGHTEN * _bump(x, (0.10, 0.40)) * (1.0 - 0.35 * _smoothstep(0.45, 1.0, x)) - FADE_SINK * (1.0 - _smoothstep(0.0, 0.14, x)))
    out = np.clip(out, 0.0, 255.0)
    return np.rint(out).astype(np.uint8) if np.asarray(display).dtype == np.uint8 else out.astype(np.float32)
