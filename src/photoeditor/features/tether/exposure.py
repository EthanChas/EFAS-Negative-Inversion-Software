"""The camera's exposure settings (ISO, aperture, shutter speed, exposure compensation) as people read them, and an auto exposure that works from the live picture. No Qt.

Canon's SDK gives each setting as a one-byte code, in steps of an eighth of a stop: the shutter code 0x38 is 1 second and every 8 less is a stop longer, the aperture code 0x08 is
f/1.0 and every 8 more is a stop smaller, the ISO code 0x48 is ISO 100 and every 8 more doubles it, and compensation is a signed byte in eighths of a stop. Those sums give the number
behind a code; the name shown is the nearest of the numbers a camera prints (1/60, f/5.6, ISO 640), so a code the table has never seen still gets a sensible name.

Auto exposure is for the copy stand. It meters the film (not the black holder, and not the bare light of the sprocket holes), finds how bright the brightest colour of the film gets, and
moves the shutter speed, which leaves the aperture at the lens's sharp setting and the ISO at its quiet one, until that sits just short of clipping. On a negative the brightest film is
the clear base between and around the frames, so that is what is kept from clipping: the conversion needs the base's colour to take the orange mask out, and the picture, which is denser
than the base, comes out as bright as it can be without that.
"""

import math
from dataclasses import dataclass

import numpy as np

KEYS = ("iso", "av", "tv", "comp")
TITLES = {"iso": "ISO", "av": "Aperture", "tv": "Shutter speed", "comp": "Exposure compensation"}
ISO_AUTO = 0x00
TV_BULB = 0x0C
MODES = {0: "P", 1: "Tv", 2: "Av", 3: "M", 4: "Bulb", 5: "A-DEP", 6: "DEP", 7: "Custom", 8: "Lock", 9: "Green", 10: "Night", 11: "Sports", 12: "Portrait", 13: "Landscape",
         14: "Closeup", 15: "Flash off", 19: "Creative auto", 22: "Scene intelligent auto", 80: "Movie"}

_ISO_NOMINAL = (6, 12, 25, 50, 100, 125, 160, 200, 250, 320, 400, 500, 640, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000, 6400, 8000, 10000, 12800, 16000, 20000, 25600,
                32000, 40000, 51200, 64000, 80000, 102400)
_AV_NOMINAL = (1.0, 1.1, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.5, 2.8, 3.2, 3.5, 4.0, 4.5, 5.0, 5.6, 6.3, 7.1, 8, 9, 10, 11, 13, 14, 16, 18, 20, 22, 25, 29, 32, 36, 40, 45, 51, 57, 64, 72, 80, 91)
_TV_NOMINAL = (30, 25, 20, 15, 13, 10, 8, 6, 5, 4, 3.2, 2.5, 2, 1.6, 1.3, 1, 0.8, 0.6, 0.5, 0.4, 0.3, 1 / 4, 1 / 5, 1 / 6, 1 / 8, 1 / 10, 1 / 13, 1 / 15, 1 / 20, 1 / 25, 1 / 30, 1 / 40,
               1 / 50, 1 / 60, 1 / 80, 1 / 100, 1 / 125, 1 / 160, 1 / 200, 1 / 250, 1 / 320, 1 / 400, 1 / 500, 1 / 640, 1 / 800, 1 / 1000, 1 / 1250, 1 / 1600, 1 / 2000, 1 / 2500,
               1 / 3200, 1 / 4000, 1 / 5000, 1 / 6400, 1 / 8000)

TARGET = 235.0            # the brightest colour of the metered area, as a live-picture value, that auto exposure aims for: bright, and short of clipping
CLIP_VALUE = 252.0        # a metered level this high is clipped: how far over it is cannot be read, so it is only known to be too bright
TOLERANCE_STOPS = 0.15    # closer than this to the target counts as right
MAX_ROUND_STOPS = 3.0     # one round never moves more than this: a first guess from a picture that is clipped or nearly black is only a direction
MAX_ROUNDS = 6
METER_BOX = (0.04, 0.1, 0.96, 0.9)   # x0, y0, x1, y1 as fractions of the picture: the film and its clear border, inside the holder
BARE_LIGHT = 230          # a pixel whose dimmest colour is this bright is white: the light itself, through a sprocket hole or past the film. It always clips and is not metered
METER_PERCENTILE = 99.5


def signed8(code: int) -> int:
    code &= 0xFF
    return code - 256 if code >= 128 else code


def value_of(key: str, code: int) -> float | None:
    """The number a code stands for: ISO, the f-number, the time in seconds, or compensation in stops. None for Auto ISO and Bulb."""
    if key == "iso":
        return None if code == ISO_AUTO else 100.0 * 2.0 ** ((code - 0x48) / 8.0)
    if key == "av":
        return 2.0 ** (((code - 0x08) / 8.0) / 2.0)
    if key == "tv":
        return None if code == TV_BULB else 2.0 ** ((0x38 - code) / 8.0)
    if key == "comp":
        return signed8(code) / 8.0
    raise KeyError(key)


def _nearest(value: float, series) -> float:
    return min(series, key=lambda n: abs(math.log(n) - math.log(value)))


def label(key: str, code: int) -> str:
    """The setting as a camera shows it: ISO 400, f/5.6, 1/60 s, +1/3."""
    value = value_of(key, code)
    if key == "iso":
        return "Auto" if value is None else f"{_nearest(value, _ISO_NOMINAL):g}"
    if key == "av":
        n = _nearest(value, _AV_NOMINAL)
        return f"f/{n:g}"
    if key == "tv":
        if value is None:
            return "Bulb"
        t = _nearest(value, _TV_NOMINAL)
        return f"{t:g} s" if t >= 0.3 else f"1/{round(1 / t)} s"
    thirds = round(value * 3)
    if thirds == 0:
        return "0"
    whole, rest = divmod(abs(thirds), 3)
    text = (f"{whole} " if whole else "") + (f"{rest}/3" if rest else "")
    return ("+" if thirds > 0 else "-") + text.strip()


def stops_of(key: str, code: int) -> float:
    """How much light the setting lets in, in stops, against ISO 100, f/1 and 1 second (so settings can be added up). Compensation is not part of the sum."""
    value = value_of(key, code)
    if key == "iso":
        return 0.0 if value is None else math.log2(value / 100.0)
    if key == "av":
        return -2.0 * math.log2(value)
    if key == "tv":
        return 0.0 if value is None else math.log2(value)
    return 0.0


def third_codes(low: int, high: int) -> list[int]:
    """Every third-stop code from `low` to `high` (a stop is 8, and its thirds are at 0, 3 and 5), the way a camera offers them."""
    out = []
    for base in range(low - low % 8, high + 8, 8):
        for step in (0, 3, 5):
            if low <= base + step <= high:
                out.append(base + step)
    return out


def comp_codes(limit_stops: int = 3) -> list[int]:
    """The compensation codes from -limit to +limit stops in thirds, in order."""
    return [round(k * 8 / 3) & 0xFF for k in range(-3 * limit_stops, 3 * limit_stops + 1)]


@dataclass(frozen=True)
class ExposureState:
    """What the camera is set to. `choices` is, for each setting, the codes the camera will take just now (empty when it will not take a change: the dial is on a mode that sets it itself)."""

    mode: str
    values: dict
    choices: dict

    def can_set(self, key: str) -> bool:
        return bool(self.choices.get(key))


def mode_name(code: int | None) -> str:
    return "?" if code is None else MODES.get(code, f"mode {code}")


# ------------------------------------------------------------ auto exposure
def metered_level(rgb: np.ndarray) -> float:
    """The brightness, 0 to 255, that the brightest colour of the film reaches in the live picture: the 99.5th percentile of the brightest colour over the film's area, leaving out the bare
    light (white pixels), so a few stray pixels do not decide and a sprocket hole does not make every picture look clipped."""
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = METER_BOX
    area = rgb[int(h * y0):max(int(h * y0) + 1, int(h * y1)), int(w * x0):max(int(w * x0) + 1, int(w * x1))]
    brightest = area.max(axis=2)
    film = brightest[area.min(axis=2) < BARE_LIGHT]
    return float(np.percentile(film if film.size >= 100 else brightest, METER_PERCENTILE))


def stops_to_target(level: float, target: float = TARGET) -> float:
    """How many stops more light (positive) or less (negative) bring `level` to the target, from the live picture's tone curve (about gamma 2.2). A clipped level cannot say how far over
    it is, so it is only told to come down; no round moves more than MAX_ROUND_STOPS."""
    if level >= CLIP_VALUE:
        return -1.5
    lin = lambda v: (max(v, 1.0) / 255.0) ** 2.2
    return max(-MAX_ROUND_STOPS, min(MAX_ROUND_STOPS, math.log2(lin(target) / lin(level))))


def next_shutter(code: int, stops: float, choices) -> int | None:
    """The shutter code `stops` more light away (a longer time is a lower code), taken from what the camera offers; None when that is no change (right already, or at the end of its range)."""
    usable = sorted(c for c in choices if c != TV_BULB)
    if not usable:
        return None
    want = code - round(stops * 8)
    best = min(usable, key=lambda c: (abs(c - want), abs(c - code)))
    return None if best == code else best


def at_limit(code: int, stops: float, choices) -> bool:
    """True when the camera has no shutter speed further in the direction `stops` asks for (more light is a lower code): the end of its range, not just a step too small to matter."""
    usable = [c for c in choices if c != TV_BULB]
    return not any(c < code if stops > 0 else c > code for c in usable)


@dataclass(frozen=True)
class AutoResult:
    ok: bool            # the picture is as bright as it can be without clipping
    message: str
    rounds: int = 0
