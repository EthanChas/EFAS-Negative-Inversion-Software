"""The grain report: how much of a film's real grain a scan resolves, and whether the edits keep it - numpy and OpenCV only, no Qt.

EFAS never adds grain (a scan of film already has its own). What it can do is tell you two true things:

1. **What the capture resolves.** Film grain is a texture a few micrometres across. A scan whose pixels are about as big as the grain (or whose focus is soft) cannot show it: the "grain" it
   shows is then mostly sensor noise, and the picture is limited by the capture, not by the film. The report finds flat, mid-tone patches of the scan, takes out the slow variation under
   them, and measures what is left: how strong it is (the standard deviation relative to the brightness) and how wide it is (the lag at which it stops resembling itself: the correlation
   width, in pixels). A width near one pixel means the texture is at the pixel level and is not resolved.
2. **Whether the edits keep it.** Sharpening raises fine texture, chroma denoise and local contrast change it. The report converts the same patches at the scan's own resolution with and
   without those modules and compares the fine texture (what a one-pixel blur removes) in the result.

Both are measurements of the patches it picked, said in plain words with their limits (the camera's demosaicing makes noise about a pixel wide even when the film's grain is far finer)."""
from dataclasses import dataclass, field

import numpy as np

PATCH = 256                 # the size of a patch, in pixels
MAX_PATCHES = 4
MARGIN = 0.04               # share of each side kept clear of the picture's edge (film borders, holder, vignetting)
BRIGHTNESS = (0.12, 0.88)   # patches must be this bright, as a share of the range: dark ones are sensor noise, bright ones may clip
MAX_STRUCTURE = 0.06        # a patch whose slow variation (a gradient, an edge, a detail) is more than this share of its brightness is not flat enough
CORRELATION_LAGS = 24
UNRESOLVED_BELOW = 1.0      # correlation width (pixels): under this the texture is at the pixel level
RESOLVED_FROM = 2.0         # and from here the grain is spread over several pixels
KEEP_BAND = (0.85, 1.20)    # the fine texture ratio (edited over unedited) that counts as "kept"
FRAME_WIDTH_MM = {"35mm": 36.0}   # the frame's width on the film, for the size of a pixel on it; other formats vary too much to guess


@dataclass
class Patch:
    y: int
    x: int
    mean: float            # of the patch, as a share of the range (0..1)
    structure: float       # slow variation, as a share of the brightness: lower is flatter


@dataclass
class GrainReading:
    patches: list[Patch] = field(default_factory=list)
    strength: float = 0.0             # relative standard deviation of the texture, in percent of the brightness
    width: float = 0.0                # correlation width, pixels
    channels: dict[str, float] = field(default_factory=dict)   # strength per channel (R, G, B), percent
    notes: list[str] = field(default_factory=list)


@dataclass
class DetailEffect:
    ratio: float = 1.0                                   # fine texture of the edited result over the unedited, all the detail modules together
    by_module: dict[str, float] = field(default_factory=dict)   # the same for each module alone


def _range_of(plane: np.ndarray) -> float:
    return 65535.0 if plane.dtype == np.uint16 else 255.0 if plane.dtype == np.uint8 else max(1.0, float(plane.max()))


def flat_patches(plane: np.ndarray, size: int = PATCH, want: int = MAX_PATCHES) -> list[Patch]:
    """The flattest, mid-tone patches of a scan's plane (2-D), best first, no two touching: where grain can be measured without picture detail getting in the way."""
    import cv2

    h, w = plane.shape[:2]
    if h < size or w < size:
        return []
    top = _range_of(plane)
    x = plane.astype(np.float32) / top
    my, mx = int(h * MARGIN), int(w * MARGIN)
    found: list[Patch] = []
    for y0 in range(my, h - my - size + 1, size):
        for x0 in range(mx, w - mx - size + 1, size):
            tile = x[y0:y0 + size, x0:x0 + size]
            mean = float(tile.mean())
            if not BRIGHTNESS[0] <= mean <= BRIGHTNESS[1] or float(tile.max()) >= 0.995 or float(tile.min()) <= 0.002:
                continue
            slow = cv2.GaussianBlur(tile, (0, 0), size / 16.0)
            structure = float(slow.std()) / mean
            if structure <= MAX_STRUCTURE:
                found.append(Patch(y0, x0, mean, structure))
    found.sort(key=lambda p: p.structure)
    picked: list[Patch] = []
    for p in found:
        if all(abs(p.y - q.y) >= size or abs(p.x - q.x) >= size for q in picked):
            picked.append(p)
        if len(picked) == want:
            break
    return picked


def residual(tile: np.ndarray) -> np.ndarray:
    """The texture of a patch: the patch with its slow variation (its gradient, the film's unevenness) taken out."""
    import cv2

    t = tile.astype(np.float32)
    return t - cv2.GaussianBlur(t, (0, 0), tile.shape[0] / 16.0)


def correlation_width(res: np.ndarray) -> float:
    """The lag, in pixels, at which the texture's autocorrelation falls to a half (along rows and columns, averaged), by linear interpolation. White noise is about 0.5; a soft texture is wider."""
    f = np.fft.rfft2(res - res.mean())
    ac = np.fft.irfft2(np.abs(f) ** 2, s=res.shape)
    ac = ac / max(float(ac[0, 0]), 1e-12)
    curve = 0.5 * (ac[0, :CORRELATION_LAGS] + ac[:CORRELATION_LAGS, 0])
    for lag in range(1, len(curve)):
        if curve[lag] <= 0.5:
            before = curve[lag - 1]
            return float(lag - 1 + (before - 0.5) / max(before - curve[lag], 1e-9))
    return float(CORRELATION_LAGS)


def measure(scan: np.ndarray, patches: list[Patch] | None = None, size: int = PATCH) -> GrainReading:
    """The grain of a scan (HxW, or HxWx3 with the green channel used for the width): strength and correlation width over its flat patches. Nothing is claimed when there are none."""
    plane = scan[..., 1] if scan.ndim == 3 and scan.shape[2] >= 2 else (scan[..., 0] if scan.ndim == 3 else scan)
    picked = patches if patches is not None else flat_patches(plane, size)
    reading = GrainReading(patches=list(picked))
    if not picked:
        reading.notes.append("No flat, mid-tone area was found to measure: the picture has detail or clipping everywhere, or is smaller than a patch.")
        return reading
    top = _range_of(plane)
    widths, strengths = [], []
    per_channel: dict[str, list[float]] = {"R": [], "G": [], "B": []}
    for p in picked:
        tile = plane[p.y:p.y + size, p.x:p.x + size].astype(np.float32) / top
        res = residual(tile)
        widths.append(correlation_width(res))
        strengths.append(float(res.std()) / max(p.mean, 1e-6))
        if scan.ndim == 3 and scan.shape[2] >= 3:
            for i, name in enumerate("RGB"):
                ct = scan[p.y:p.y + size, p.x:p.x + size, i].astype(np.float32) / top
                per_channel[name].append(float(residual(ct).std()) / max(float(ct.mean()), 1e-6))
    reading.width = float(np.median(widths))
    reading.strength = float(np.median(strengths)) * 100.0
    reading.channels = {k: float(np.median(v)) * 100.0 for k, v in per_channel.items() if v}
    return reading


def resolution_verdict(width: float) -> tuple[str, str]:
    """(a short word, a sentence of advice) for a correlation width."""
    if width < UNRESOLVED_BELOW:
        return "not resolved", ("The texture is at the pixel level, so this scan does not show the film's grain: most of what looks like grain is sensor noise, and the sharpness is limited by the "
                                "capture (focus, the lens's best aperture, or too few pixels across the frame), not by the film. A closer capture, a sharper aperture and a lower ISO would show more.")
    if width < RESOLVED_FROM:
        return "partly resolved", ("The texture is a little wider than a pixel, so the scan shows some of the grain but not its detail. Careful focus and a closer capture would resolve more. "
                                   "Sharpening here mostly raises noise.")
    return "resolved", "The texture is spread over several pixels, so the scan shows the film's grain. The capture is not what limits it; how you sharpen and denoise decides how much of it you keep."


def pixel_pitch_um(frame_format: str, image_width_px: int) -> float | None:
    """How many micrometres of film one pixel covers, if the frame fills the picture's width (35 mm is 36 mm wide); None for a format this does not know."""
    mm = FRAME_WIDTH_MM.get(frame_format)
    return mm * 1000.0 / image_width_px if mm and image_width_px > 0 else None


def fine_texture(positive: np.ndarray) -> float:
    """How much texture a picture has at the scale of a pixel: the standard deviation of what a one-pixel blur removes, of its luminance (0..255 scale)."""
    import cv2

    x = positive.astype(np.float32)
    if x.ndim == 3:
        x = x @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    if positive.dtype == np.uint16:
        x = x / 257.0
    border = 8   # a convolved picture's edges are not its texture
    hp = (x - cv2.GaussianBlur(x, (0, 0), 1.0))[border:-border, border:-border]
    return float(hp.std())


def detail_ratio(edited: list[np.ndarray], plain: list[np.ndarray]) -> float:
    """The fine texture of the edited patches over that of the unedited ones (the median over the patches); 1 is unchanged."""
    ratios = [fine_texture(e) / fine_texture(p) for e, p in zip(edited, plain) if fine_texture(p) > 1e-6]
    return float(np.median(ratios)) if ratios else 1.0


GRAIN_MODULE = "grain"   # the key of Grain Sharpening among the modules compared: raising the grain is what it is for


def top_module(effect: DetailEffect) -> tuple[str, float] | None:
    """(the module that moved the fine texture most, its ratio on its own), or None when no one stands out."""
    if not effect.by_module:
        return None
    key = max(effect.by_module, key=lambda k: abs(np.log(max(effect.by_module[k], 1e-6))))
    m = effect.by_module[key]
    return (key, m) if abs(np.log(max(m, 1e-6))) > 0.05 else None


def effect_sentence(effect: DetailEffect, names: dict[str, str]) -> str:
    """What the edits did to the fine texture, in words, naming the module that did most when one stands out."""
    r = effect.ratio
    top = top_module(effect)
    if r > KEEP_BAND[1] and top is not None and top[0] == GRAIN_MODULE:
        return f"Your edits raise the fine texture to {r:.2f} times the unedited conversion's, mostly {names.get(GRAIN_MODULE, GRAIN_MODULE)} ({top[1]:.2f}x on its own): the grain is crisper, which is what it is for."
    if KEEP_BAND[0] <= r <= KEEP_BAND[1]:
        head = f"Your edits keep the fine grain texture (it is {r:.2f} times the unedited conversion's)."
    elif r < KEEP_BAND[0]:
        head = f"Your edits remove about {round((1.0 - r) * 100)}% of the fine grain texture (it is {r:.2f} times the unedited conversion's)."
    else:
        head = f"Your edits raise the fine texture to {r:.2f} times the unedited conversion's: sharpening is making the grain (and the noise) stronger."
    if top is not None:
        head += f" Most of that is {names.get(top[0], top[0])} ({top[1]:.2f}x on its own)."
    return head
