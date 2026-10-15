"""A forward model of colour negative film and a camera scan of it - numpy only, no Qt.

It exists so the conversions can be measured instead of judged by eye: a known picture is exposed onto a modelled negative, scanned, and handed to a conversion, and the
result is compared with the picture it started from. The model is the usual sensitometric one. Each dye layer turns the log of its exposure into density through an S-shaped
characteristic (H&D) curve that rises from the layer's base density (the orange mask) to its maximum; the three layers' dyes also absorb in each other's bands (crosstalk),
which mixes their densities; the scanner reads the light that gets through, 10^-D, in its own three channels.

The curve is a logistic in log exposure: density = Dmin + R / (1 + 10^(-s (logH - h0))), with s = 4 gamma / (R ln 10) so that its slope at the middle is gamma."""

from dataclasses import dataclass, field

import numpy as np

_LN10 = float(np.log(10.0))


@dataclass(frozen=True)
class Film:
    d_min: tuple[float, float, float] = (0.28, 0.62, 0.92)          # base + mask density per channel (red, green, blue)
    d_range: tuple[float, float, float] = (2.4, 2.5, 2.7)           # density gained from base to the layer's maximum
    gamma: tuple[float, float, float] = (0.62, 0.60, 0.66)          # slope of each layer's curve at its middle
    crosstalk: tuple = ((1.00, 0.06, 0.01), (0.14, 1.00, 0.05), (0.04, 0.18, 1.00))  # measured density = M @ dye density
    mid_exposure: float = 0.18                                      # scene value that lands on the middle of the curve
    speed: tuple[float, float, float] = (1.0, 1.0, 1.0)             # relative sensitivity of each layer (a colour balance error of the exposure)


PORTRA_LIKE = Film()
FLAT_FILM = Film(d_range=(2.0, 2.1, 2.2), gamma=(0.5, 0.48, 0.52), crosstalk=((1.0, 0.04, 0.0), (0.09, 1.0, 0.03), (0.03, 0.12, 1.0)))
CONTRASTY_FILM = Film(d_range=(2.8, 2.9, 3.1), gamma=(0.78, 0.74, 0.8), crosstalk=((1.0, 0.09, 0.02), (0.2, 1.0, 0.07), (0.06, 0.24, 1.0)))
FILMS = {"standard": PORTRA_LIKE, "flat": FLAT_FILM, "contrasty": CONTRASTY_FILM}


def expose(scene: np.ndarray, film: Film = PORTRA_LIKE, stops: float = 0.0, light: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> np.ndarray:
    """The density the developed negative has measured through each scanner channel, for linear scene values (h, w, 3) and an exposure error in stops.
    `light` is the colour of the scene's light as the layers see it (a tungsten scene is (1.6, 1.0, 0.55), say)."""
    e = np.clip(np.asarray(scene, dtype=np.float64), 1e-6, None) * (2.0 ** stops) * np.asarray(light) * np.asarray(film.speed)
    log_h = np.log10(e / film.mid_exposure)
    d_min, rng, gamma = (np.asarray(v, dtype=np.float64) for v in (film.d_min, film.d_range, film.gamma))
    s = 4.0 * gamma / (rng * _LN10)
    dye = rng / (1.0 + np.power(10.0, -s * log_h))
    dye = dye + 0.0  # dye density above the base, per layer
    mix = np.asarray(film.crosstalk, dtype=np.float64)
    return d_min + dye @ mix.T


def scan(density: np.ndarray, white: float = 0.92, noise: float = 0.0, seed: int = 0, encode: str = "linear") -> np.ndarray:
    """What a camera records of the negative lit from behind: transmittance, 16-bit. `white` is where clear light sits on the sensor's scale
    (the exposure of the scan); `encode` is "linear" or "srgb" (a display-encoded picture)."""
    t = np.power(10.0, -np.asarray(density, dtype=np.float64)) * white
    if noise > 0.0:
        t = t + np.random.default_rng(seed).normal(0.0, noise, t.shape) * np.sqrt(np.clip(t, 1e-6, None))
    t = np.clip(t, 0.0, 1.0)
    if encode == "srgb":
        t = np.where(t <= 0.0031308, t * 12.92, 1.055 * np.power(t, 1 / 2.4) - 0.055)
    return np.clip(np.rint(t * 65535.0), 0, 65535).astype(np.uint16)


def srgb_to_linear(rgb8: np.ndarray) -> np.ndarray:
    c = np.asarray(rgb8, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, np.power((c + 0.055) / 1.055, 2.4))


def linear_to_srgb8(lin: np.ndarray) -> np.ndarray:
    c = np.clip(lin, 0.0, 1.0)
    return np.clip(np.rint(np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055) * 255.0), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- measuring a conversion against the picture it started from
_XYZ = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
_WHITE = _XYZ @ np.ones(3)


def to_lab(rgb8: np.ndarray) -> np.ndarray:
    xyz = (srgb_to_linear(rgb8) @ _XYZ.T) / _WHITE
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


@dataclass(frozen=True)
class Score:
    chroma_error: float     # mean distance in (a, b) from the original: colour casts and wrong saturation
    tone_error: float       # mean lightness error after the best straight-line fit of lightness (a conversion may choose its own exposure and contrast)
    cast: float             # distance of the average colour from the original's, in (a, b): a pure colour balance error
    clipped: float          # share of pixels at pure black or white that the original does not have there

    def total(self) -> float:
        return self.chroma_error + 0.5 * self.tone_error


def score(result8: np.ndarray, original8: np.ndarray) -> Score:
    """How close a conversion's 8-bit result is to the picture the negative was made from."""
    a, b = to_lab(result8), to_lab(original8)
    la, lb = a[..., 0].ravel(), b[..., 0].ravel()
    coef = np.polyfit(la, lb, 1)
    tone = float(np.mean(np.abs(np.polyval(coef, la) - lb)))
    chroma = float(np.mean(np.hypot(a[..., 1] - b[..., 1], a[..., 2] - b[..., 2])))
    cast = float(np.hypot(*(a[..., 1:].reshape(-1, 2).mean(axis=0) - b[..., 1:].reshape(-1, 2).mean(axis=0))))
    ra, rb = result8.reshape(-1, 3), original8.reshape(-1, 3)
    extreme = (ra.max(axis=1) >= 254) | (ra.min(axis=1) <= 1)
    original_extreme = (rb.max(axis=1) >= 254) | (rb.min(axis=1) <= 1)
    return Score(chroma, tone, cast, float(np.mean(extreme & ~original_extreme)))
