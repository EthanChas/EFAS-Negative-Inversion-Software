"""What the tether window does with each live picture from the camera: decode it, turn the negative into a positive, mark what is in focus, and measure how sharp it is. No Qt.

The positive is EFAS's own Modern conversion (features/negative/printengine.py), not a plain flip: a plain flip keeps the orange mask and comes out cyan. The conversion's lookup
table is made from the picture and then reused for about half a second, so most pictures cost only a table lookup. Focus peaking is EFAS's own too (features/focuspeaking).
Sharpness is a gated edge-energy number: gradients below the picture's noise floor count for nothing, because the sum of many tiny noise gradients would otherwise score a
blurred picture as high as a sharp one.
"""

import time
from dataclasses import dataclass

import cv2
import numpy as np

from ..focuspeaking import logic as peaking
from ..negative import printengine as engine

WORK_WIDTH = 1620         # the positive and the picture shown are made at most this wide (a Canon live picture is 960 to 1620 wide: all of them are kept whole, not made smaller than the camera sent)
PEAK_WIDTH = 960          # peaking is worked out at most this wide, and stretched over the picture
METER_WIDTH = 800         # the conversion's table is made from a picture this wide (as it always was) and applied to the full one, so the colours do not change with the size shown
PEAK_EVERY = 3            # peaking is worked out for one frame in this many and kept for the others: focus changes slowly, and it is the dearest step
RELEARN_S = 0.6           # how long a conversion table is reused before it is made again from a newer picture
NOISE_FLOOR = 6.0         # edge strength (grey levels per pixel) below this counts for nothing
CLIP_LEVEL = 250          # a camera value this high is blown out
HOLDER_LEVEL = 12         # a pixel whose brightest colour is below this is the holder or black surround: it sends almost no light, so it says nothing about the film
METERING = (("wide", "Whole picture (holder ignored)"), ("middle", "Middle of the picture"), ("hold", "Hold the current conversion"))
LOUPE_PIXELS = 96         # the side of the camera-pixel square the loupe enlarges
LOUPE_SCALE = 4
SETTINGS = engine.Settings(transfer="srgb")   # the camera's live picture is an ordinary sRGB JPEG


_DENSITY_OF_VALUE = engine.density_table(np.dtype(np.uint8), SETTINGS.transfer).astype(np.float32)   # the density of each of the 256 values of an 8-bit colour
_MIX = engine.mixing_matrix(SETTINGS.unmix_matrix, SETTINGS.unmix_strength).astype(np.float32)           # the dyes' crosstalk taken out
_MIXES = not np.allclose(_MIX, np.eye(3), atol=1e-6)


@dataclass(frozen=True)
class View:
    """What the person has asked to see."""

    positive: bool = True
    peaking: bool = False
    peaking_sensitivity: float = 0.5            # 0 marks only the very sharpest, 1 marks every sharp spot (focuspeaking.scale_for_sensitivity)
    base_rgb: tuple | None = None               # the colour of the clear film as the camera shows it, when it was sampled
    region: tuple = (0.5, 0.5, 0.25)            # where sharpness is measured: centre x, centre y, side (all as fractions of the picture)
    flatfield: bool = True                      # even the picture out with the pipeline's flat field, when it has one
    metering: str = "wide"                      # what the positive's tones are worked out from: "wide" (the whole picture less the holder and what is blown out), "middle", or "hold" (do not change them)


@dataclass
class LiveFrame:
    image: np.ndarray       # the picture to show: RGB, uint8
    rgb: np.ndarray         # the camera's picture as it came, decoded (RGB, uint8)
    sharpness: float
    clipped: dict           # per cent of the picture blown out in R, G, B


def decode(jpeg: bytes) -> np.ndarray | None:
    """RGB, uint8, or None when the bytes are not a picture (a damaged frame is skipped, never fatal)."""
    if not jpeg:
        return None
    bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    return None if bgr is None else cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def edge_strength(grey: np.ndarray) -> np.ndarray:
    """Edge strength per pixel in grey levels per pixel (Scharr: the most accurate 3x3 gradient, which suits fine, directionless film grain)."""
    g = grey.astype(np.float32)
    return np.hypot(cv2.Scharr(g, cv2.CV_32F, 1, 0), cv2.Scharr(g, cv2.CV_32F, 0, 1)) / 16.0


def region_box(shape, cx: float, cy: float, size: float) -> tuple:
    """(x0, y0, x1, y1) of a square region `size` (a fraction of the picture's width) across, slid inward at an edge and not shrunk, so a region near the edge still measures as
    many pixels as one in the middle."""
    h, w = shape[:2]
    half = max(8, int(w * min(max(size, 0.02), 1.0) / 2))
    half_h = min(half, h // 2)
    x0 = int(min(max(cx * w - half, 0), w - 2 * half))
    y0 = int(min(max(cy * h - half_h, 0), h - 2 * half_h))
    return x0, y0, x0 + 2 * half, y0 + 2 * half_h


def sharpness(rgb: np.ndarray, region: tuple | None = None) -> float:
    """How sharp the picture (or the region of it) is, as a number that only means something compared with itself in one session: it depends on the subject, the light and how
    big the region is. Higher is sharper."""
    if region is not None:
        x0, y0, x1, y1 = region_box(rgb.shape, *region)
        rgb = rgb[y0:y1, x0:x1]
    strength = edge_strength(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
    gated = np.where(strength >= NOISE_FLOOR, strength, 0.0).astype(np.float64)
    return float((gated ** 2).mean() / 10.0)


GRADES = ((0.97, "Sharpest"), (0.85, "Sharp"), (0.6, "Nearly there"), (0.3, "Soft"), (0.0, "Blurred"))


def grade(latest: float, best: float) -> tuple[str, float]:
    """(a word for how sharp the picture is, and the share 0 to 1 of the best seen so far). Sharpness only means something against itself, so the grade is against the best reading of
    the session: Sharpest (within 3%), Sharp, Nearly there, Soft, Blurred. With no reading yet there is nothing to grade against."""
    if best <= 1e-9:
        return "", 0.0
    share = max(0.0, min(1.0, latest / best))
    return next(word for floor, word in GRADES if share >= floor), share


def corner_sharpness(rgb: np.ndarray, size: float = 0.18) -> dict:
    """Sharpness at the middle and in each corner. A camera that is not parallel to the film shows corners that differ from each other."""
    inset = size / 2 + 0.02
    spots = {"centre": (0.5, 0.5), "top left": (inset, inset), "top right": (1 - inset, inset), "bottom left": (inset, 1 - inset), "bottom right": (1 - inset, 1 - inset)}
    return {name: sharpness(rgb, (x, y, size)) for name, (x, y) in spots.items()}


def clipped_percent(rgb: np.ndarray) -> dict:
    """The per cent of the picture at or above the blown-out level, in each colour."""
    return {c: cv2.countNonZero(cv2.compare(np.ascontiguousarray(rgb[..., i]), CLIP_LEVEL - 1, cv2.CMP_GT)) * 100.0 / (rgb.shape[0] * rgb.shape[1]) for i, c in enumerate("RGB")}


def sample_colour(rgb: np.ndarray, x: float, y: float, radius: int = 5) -> tuple:
    """The average colour round a point (x and y as fractions of the picture): what a click on the clear film measures."""
    h, w = rgb.shape[:2]
    cx, cy = int(min(max(x, 0.0), 1.0) * (w - 1)), int(min(max(y, 0.0), 1.0) * (h - 1))
    patch = rgb[max(0, cy - radius):cy + radius + 1, max(0, cx - radius):cx + radius + 1].reshape(-1, 3)
    return tuple(float(v) for v in patch.mean(axis=0))


class Pipeline:
    """Makes the picture to show from each live frame. One at a time: it keeps the conversion table between frames."""

    def __init__(self):
        self._lut = None
        self._lut_key = None
        self._lut_at = 0.0
        self._lut_mode = None
        self._peak = None          # (the sensitivity it was made for, the size of the picture, where it marks, the colour of each mark)
        self._peak_age = 0
        self._lut8 = None          # (the table it was made from, that table rounded to 8 bits)
        self._flat = None          # (the flat field's gain map, {(width, height): the multiplier for a picture that size}) or None

    def set_flatfield(self, gain: np.ndarray | None) -> None:
        """Even out every picture from now on with this gain map (the flat field of features/flatfield; None for none). The conversion's table is made again from the corrected picture."""
        self._flat = None if gain is None else (np.ascontiguousarray(gain, dtype=np.float32), {})
        self._lut = None

    @property
    def has_flatfield(self) -> bool:
        return self._flat is not None

    @staticmethod
    def _multiplier(flat, width: int, height: int) -> np.ndarray:
        """What a camera value is multiplied by to apply the gain: the gain works in linear light, and (v^2.2 x g)^(1/2.2) is v x g^(1/2.2), so a plain multiplication does it."""
        gain, made = flat
        key = (width, height)
        if key not in made:
            if len(made) > 3:
                made.clear()
            made[key] = np.ascontiguousarray(np.power(cv2.resize(gain, (width, height), interpolation=cv2.INTER_LINEAR), np.float32(1.0 / 2.2)), dtype=np.float32)
        return made[key]

    def _flatten(self, rgb: np.ndarray, flat) -> np.ndarray:
        out = rgb.astype(np.float32)
        out *= self._multiplier(flat, rgb.shape[1], rgb.shape[0])
        out += 0.5
        np.clip(out, 0, 255, out=out)
        return out.astype(np.uint8)

    def flat_colour(self, colour: tuple, x: float, y: float, shape, view: View) -> tuple:
        """A colour measured on the camera's own picture (a click on the clear film), as it reads once the flat field has evened the picture out."""
        flat = self._flat
        if flat is None or not view.flatfield:
            return colour
        h, w = shape[:2]
        k = self._multiplier(flat, w, h)[int(min(max(y, 0.0), 1.0) * (h - 1)), int(min(max(x, 0.0), 1.0) * (w - 1))]
        return tuple(min(255.0, float(c) * float(m)) for c, m in zip(colour, k))

    @staticmethod
    def _metered(meter: np.ndarray, codes: np.ndarray, mode: str) -> np.ndarray:
        """The density codes the tones are worked out from. "middle": the middle of the picture (the edges are the holder, the clear film and the sprocket holes). Otherwise: nearly the whole
        picture, less what says nothing about the film: the holder (almost no light) and anything blown out (the clear film, which is clipped). What the tones were not worked out from and
        is brighter than the rest comes out white, so the picture's edges are in."""
        h, w = codes.shape[:2]
        if mode != "middle":
            my, mx = int(h * 0.03), int(w * 0.03)
            part, raw = codes[my:h - my, mx:w - mx], meter[my:h - my, mx:w - mx]
            brightest = raw.max(axis=2)
            kept = part[(brightest > HOLDER_LEVEL) & (brightest < CLIP_LEVEL)]
            if kept.shape[0] >= 500:
                return kept[::max(1, kept.shape[0] // 60000)][None, :, :]
        middle = codes[int(h * 0.2):int(h * 0.8), int(w * 0.15):int(w * 0.85)]
        return engine.analysis_block(middle)

    def _table(self, small: np.ndarray, view: View):
        base = tuple(round(v) for v in view.base_rgb) if view.base_rgb else None
        now = time.monotonic()
        hold = view.metering == "hold"
        stale = self._lut is None or base != self._lut_key or (not hold and (view.metering != self._lut_mode or now - self._lut_at > RELEARN_S))
        if stale:
            w = small.shape[1]
            meter = small if w <= METER_WIDTH else cv2.resize(small, (METER_WIDTH, round(small.shape[0] * METER_WIDTH / w)), interpolation=cv2.INTER_AREA)
            codes = engine.density_codes(meter, SETTINGS)
            dens = engine.base_density(base, SETTINGS, 255.0) if base else None
            self._lut = engine.build_lut(self._metered(meter, codes, "middle" if hold else view.metering), SETTINGS, dens)
            self._lut_key, self._lut_at = base, now
        if stale or hold:
            self._lut_mode = view.metering
        return self._lut

    def process(self, jpeg: bytes, view: View) -> LiveFrame | None:
        rgb = decode(jpeg)
        if rgb is None:
            return None
        h, w = rgb.shape[:2]
        small = rgb if w <= WORK_WIDTH else cv2.resize(rgb, (WORK_WIDTH, round(h * WORK_WIDTH / w)), interpolation=cv2.INTER_AREA)
        flat = self._flat
        if flat is not None and view.flatfield:
            small = self._flatten(small, flat)
        shown = self._positive(small, view) if view.positive else small
        if view.peaking:
            shown = self._with_peaking(shown, small, view.peaking_sensitivity)
        else:
            self._peak = None
        return LiveFrame(np.ascontiguousarray(shown), rgb, sharpness(rgb, view.region), clipped_percent(rgb))

    def _positive(self, small: np.ndarray, view: View) -> np.ndarray:
        """The conversion of a whole live picture. The same two steps as engine.density_codes and engine.apply_lut (to within one density code in 13000 and one level in 255), written with
        OpenCV's lookup and matrix routines and an 8-bit table, which is about twice as fast: it has to be done for every picture, 30 a second."""
        lut = self._table(small, view)
        if self._lut8 is None or self._lut8[0] is not lut:
            self._lut8 = (lut, np.clip(np.rint(lut), 0, 255).astype(np.uint8))
        density = cv2.LUT(small, _DENSITY_OF_VALUE)
        if _MIXES:
            density = cv2.transform(density, _MIX)
        density *= engine.DENSITY_SCALE
        density += 0.5
        np.clip(density, 0, 65535, out=density)
        codes = density.astype(np.uint16)
        out = np.empty(codes.shape, dtype=np.uint8)
        for c in range(3):
            np.take(self._lut8[1][c], codes[..., c], out=out[..., c])
        return out

    def _with_peaking(self, shown: np.ndarray, small: np.ndarray, sensitivity: float) -> np.ndarray:
        level = round(max(0.0, min(1.0, float(sensitivity))), 3)
        h, w = small.shape[:2]
        size = (shown.shape[1], shown.shape[0])
        stale = self._peak is None or self._peak[0] != level or self._peak[1] != size or self._peak_age >= PEAK_EVERY
        if stale:
            k = min(1.0, PEAK_WIDTH / w)
            peak_src = small if k >= 1.0 else cv2.resize(small, (round(w * k), round(h * k)), interpolation=cv2.INTER_AREA)
            overlay = peaking.overlay_from_levels(peaking.level_map(peak_src, peaking.scale_for_sensitivity(level)), 0)
            if overlay is None:
                self._peak, self._peak_age = (level, size, None, None), 0
            else:
                overlay = cv2.resize(overlay, size, interpolation=cv2.INTER_NEAREST)
                mask = overlay[..., 3] > 0
                self._peak, self._peak_age = (level, size, mask, overlay[..., :3][mask]), 0
        else:
            self._peak_age += 1
        _level, _size, mask, colours = self._peak
        if mask is None:
            return shown
        out = shown.copy()
        out[mask] = colours   # the marks are very nearly opaque, so they replace the picture where they are
        return out

    def loupe(self, frame: LiveFrame, x: float, y: float, view: View) -> np.ndarray:
        """The camera's own pixels round a point, enlarged: made from the full-size picture, not the smaller one on screen, so it shows detail the screen picture has lost."""
        h, w = frame.rgb.shape[:2]
        half = LOUPE_PIXELS // 2
        cx, cy = int(min(max(x, 0.0), 1.0) * w), int(min(max(y, 0.0), 1.0) * h)
        x0, y0 = min(max(cx - half, 0), max(0, w - LOUPE_PIXELS)), min(max(cy - half, 0), max(0, h - LOUPE_PIXELS))
        crop = frame.rgb[y0:y0 + LOUPE_PIXELS, x0:x0 + LOUPE_PIXELS]
        flat = self._flat
        if flat is not None and view.flatfield:
            crop = np.clip(crop * self._multiplier(flat, w, h)[y0:y0 + LOUPE_PIXELS, x0:x0 + LOUPE_PIXELS] + 0.5, 0, 255).astype(np.uint8)
        if view.positive and self._lut is not None:
            crop = engine.apply_lut(engine.density_codes(crop, SETTINGS), self._lut)
        return cv2.resize(crop, (crop.shape[1] * LOUPE_SCALE, crop.shape[0] * LOUPE_SCALE), interpolation=cv2.INTER_NEAREST)
