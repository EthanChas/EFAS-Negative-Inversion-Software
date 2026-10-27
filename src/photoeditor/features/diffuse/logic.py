"""Diffuse or Sharpen, ported from darktable's module of that name (src/iop/diffuse.c, GPL-3.0) - numpy only, no Qt.

darktable simulates the diffusion of light with a heat-transfer model: the picture is cut into wavelet scales (an a-trous B-spline decomposition, the same as its contrast equalizer), and on
every scale, from the coarsest to the finest, a partial differential equation is solved one step - the high-frequency layer of that scale and the low-frequency layer under it are
convolved with a 3x3 anisotropic Laplacian whose shape follows the local gradient, and the result is added back. Negative speeds sharpen (a blind deconvolution), positive speeds blur, and
the anisotropy decides whether the diffusion follows edges or avoids them. The whole thing is repeated for the number of iterations.

The picture is worked in linear light, as darktable does (it is a scene-referred module): the 8-bit sRGB picture is made linear first and brought back after. Where darktable's parameters
say "radius" they are in pixels of the full-size picture, so on the smaller editing preview they are made proportionally smaller (`zoom` is the full picture's pixels per pixel of this one).

Differences from darktable, none of them in the maths: the work is done on blocks of rows on a thread pool (numpy releases the lock), a very large picture is cut into strips with an overlap,
and the noise that fills the masked highlights of "inpaint highlights" comes from numpy's generator rather than darktable's xoshiro one.
"""
import math

import numpy as np

from ..lut.strips import _POOL

KEYS = ("dif_iterations", "dif_radius_center", "dif_radius", "dif_first", "dif_second", "dif_third", "dif_fourth",
        "dif_aniso_first", "dif_aniso_second", "dif_aniso_third", "dif_aniso_fourth",
        "dif_sharpness", "dif_regularization", "dif_variance_threshold", "dif_threshold")
DEFAULTS = {"dif_iterations": 1.0, "dif_radius_center": 0.0, "dif_radius": 8.0,
            "dif_first": 0.0, "dif_second": 0.0, "dif_third": 0.0, "dif_fourth": 0.0,
            "dif_aniso_first": 0.0, "dif_aniso_second": 0.0, "dif_aniso_third": 0.0, "dif_aniso_fourth": 0.0,
            "dif_sharpness": 0.0, "dif_regularization": 0.0, "dif_variance_threshold": 0.0, "dif_threshold": 0.0}
RANGES = {"dif_iterations": (1, 500), "dif_radius_center": (0, 1024), "dif_radius": (0, 2048),
          "dif_first": (-1.0, 1.0), "dif_second": (-1.0, 1.0), "dif_third": (-1.0, 1.0), "dif_fourth": (-1.0, 1.0),
          "dif_aniso_first": (-10.0, 10.0), "dif_aniso_second": (-10.0, 10.0), "dif_aniso_third": (-10.0, 10.0), "dif_aniso_fourth": (-10.0, 10.0),
          "dif_sharpness": (-1.0, 1.0), "dif_regularization": (0.0, 4.0), "dif_variance_threshold": (-2.0, 2.0), "dif_threshold": (0.0, 8.0)}
LIVE = "diffuse"            # its name among the modules a preview may leave out: darktable's "fast" pipe does not run it while a slider is dragged either

MAX_NUM_SCALES = 10
B_SPLINE_SIGMA = 1.0553651328015339
KAPPA = 0.25                # the discretisation of the PDE: 0.25 for a spatial step of 1
ISOTROPE, ISOPHOTE, GRADIENT = 0, 1, 2
_BUDGET = 150_000_000       # floats (about 600 MB) a single pass may hold across its buffers before the picture is cut into strips
_NEUTRAL = ("dif_first", "dif_second", "dif_third", "dif_fourth", "dif_sharpness", "dif_threshold")

# darktable's own presets (init_presets in diffuse.c): name -> the parameters it sets
PRESETS: dict[str, dict] = {}


def _preset(name, iterations, radius_center, radius, speeds, anisotropy, regularization, variance_threshold, sharpness=0.0, threshold=0.0):
    PRESETS[name] = {"dif_iterations": float(iterations), "dif_radius_center": float(radius_center), "dif_radius": float(radius),
                     "dif_first": speeds[0], "dif_second": speeds[1], "dif_third": speeds[2], "dif_fourth": speeds[3],
                     "dif_aniso_first": anisotropy[0], "dif_aniso_second": anisotropy[1], "dif_aniso_third": anisotropy[2], "dif_aniso_fourth": anisotropy[3],
                     "dif_sharpness": sharpness, "dif_regularization": regularization, "dif_variance_threshold": variance_threshold, "dif_threshold": threshold}


_DEBLUR = ((-0.25, 0.125, -0.50, 0.25), (1.0, 0.0, 1.0, 0.0))
_preset("lens deblur | soft", 8, 0, 8, *_DEBLUR, 3.0, 1.0)
_preset("lens deblur | medium", 16, 0, 10, *_DEBLUR, 3.0, 1.0)
_preset("lens deblur | hard", 24, 0, 12, *_DEBLUR, 3.0, 1.0)
_DEHAZE = ((-0.20, 0.10, -0.20, 0.10), (2.0, 0.0, 2.0, 0.0))
_preset("dehaze | default", 10, 0, 512, *_DEHAZE, 2.5, 0.25)
_preset("dehaze | extra contrast", 10, 0, 512, *_DEHAZE, 1.0, 0.25, sharpness=0.007)
_preset("surface blur", 2, 0, 32, (1.0, 1.0, 1.0, 1.0), (4.0, 4.0, 4.0, 4.0), 4.0, 0.0)
_preset("sharpen demosaicing | no AA filter", 1, 0, 4, (-0.25,) * 4, (1.0,) * 4, 1.0, 0.0)
_preset("sharpen demosaicing | AA filter", 1, 0, 8, (-0.25,) * 4, (1.0,) * 4, 1.0, 0.0)
_preset("local contrast | normal", 10, 512, 384, (-0.50, 0.0, 0.0, -0.50), (-2.5, 0.0, 0.0, -2.5), 1.0, 1.0)
_preset("local contrast | fine", 5, 0, 170, (-0.15, 0.05, 0.05, -0.15), (10.0, 0.0, 0.0, 10.0), 2.0, 0.0)
_preset("inpaint highlights", 32, 0, 4, (0.0, 0.0, 0.0, 0.5), (0.0, 0.0, 0.0, 2.0), 0.0, 0.0, threshold=1.41)
_preset("sharpness | fast", 1, 0, 128, (0.0, 0.0, -0.50, 0.0), (0.0, 0.0, 5.0, 0.0), 0.25, 0.25)
_preset("sharpness | normal", 3, 0, 3, (0.0065, -0.25, -0.25, -0.2774), (1.0,) * 4, 2.94, 0.0)
_preset("sharpness | strong", 6, 0, 3, (0.0065, -0.25, -0.25, -0.2774), (1.0,) * 4, 2.15, 0.22)
_preset("local contrast | fast", 1, 512, 512, (0.0, 0.0, -0.50, 0.0), (0.0, 0.0, 5.0, 0.0), 0.01, 0.05)


def is_neutral(values: dict | None) -> bool:
    """Nothing to do: no speed, no sharpness gain, no luminance mask (darktable's defaults leave the picture as it is)."""
    v = values or {}
    return all(abs(float(v.get(k, 0.0))) <= 1e-9 for k in _NEUTRAL)


# ---------------------------------------------------------------------------------------------------------------------------------------------- scales
def equivalent_sigma_at_step(sigma: float, s: int) -> float:
    """The standard deviation of s+1 stacked blurs of the (dilated) B-spline: the first is `sigma`."""
    if s == 0:
        return sigma
    return math.sqrt(equivalent_sigma_at_step(sigma, s - 1) ** 2 + (2.0 ** s * sigma) ** 2)


def num_steps_to_reach_equivalent_sigma(sigma_filter: float, sigma_final: float) -> int:
    s = 0
    radius = sigma_filter
    while radius < sigma_final:
        s += 1
        radius = math.sqrt(radius ** 2 + ((1 << s) * sigma_filter) ** 2)
    return s + 1


def scales_for(values: dict, zoom: float) -> int:
    final_radius = (float(values["dif_radius"]) + float(values["dif_radius_center"])) * 2.0 / max(zoom, 1.0)
    return int(np.clip(num_steps_to_reach_equivalent_sigma(B_SPLINE_SIGMA, final_radius), 1, MAX_NUM_SCALES))


# ---------------------------------------------------------------------------------------------------------------------------------------------- helpers
_BLOCK_FLOATS = 24_000      # floats in one array of a block: small enough that the dozens of temporaries one block makes stay in the processor's cache


def _rows(height: int, width: int):
    """Blocks of rows for the thread pool, each small enough to stay in cache."""
    step = max(2, _BLOCK_FLOATS // max(1, width * 3))
    n = max(1, -(-height // step))
    bounds = np.linspace(0, height, n + 1).astype(int)
    return [(int(bounds[i]), int(bounds[i + 1])) for i in range(n)]


def _map_rows(fn, height: int, width: int) -> None:
    blocks = _rows(height, width)
    if len(blocks) == 1:
        fn(*blocks[0])
    else:
        list(_POOL.map(lambda b: fn(*b), blocks))


_W5 = np.float32(1.0 / 16.0), np.float32(4.0 / 16.0), np.float32(6.0 / 16.0), np.float32(4.0 / 16.0), np.float32(1.0 / 16.0)


def _decompose(src: np.ndarray, mult: int):
    """One a-trous level: (the blur of `src` by the B-spline dilated by `mult`, clipped to >= 0, and src minus it)."""
    h, w = src.shape[:2]
    pad = 2 * mult
    p = np.pad(src, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    vert = np.empty((h, w + 2 * pad, 3), dtype=np.float32)
    low = np.empty_like(src)
    high = np.empty_like(src)

    def rows(r0, r1):
        n = r1 - r0
        a = p[r0 + 0 * mult: r0 + 0 * mult + n]
        v = vert[r0:r1]
        np.multiply(a, _W5[0], out=v)
        for k in range(1, 5):
            v += p[r0 + k * mult: r0 + k * mult + n] * _W5[k]
        out = low[r0:r1]
        np.multiply(v[:, 0:w], _W5[0], out=out)
        for k in range(1, 5):
            out += v[:, k * mult: k * mult + w] * _W5[k]
        np.maximum(out, 0.0, out=out)
        np.subtract(src[r0:r1], out, out=high[r0:r1])

    _map_rows(rows, h, w)
    return low, high


def _sq(x):
    return x * x


def _pde(hf: np.ndarray, lf: np.ndarray, mask, mult: int, anisotropy, isotropy, regularization: float, variance_threshold: float,
         radius_square: float, abcd, strength: float) -> np.ndarray:
    """One heat-PDE step on one scale (heat_PDE_diffusion in diffuse.c): the new low-frequency layer from this scale's high-frequency layer and the low-frequency one under it."""
    h, w = hf.shape[:2]
    pad = mult
    hp = np.pad(hf, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    lp = np.pad(lf, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    out = np.empty_like(lf)
    regularization_factor = np.float32(regularization * radius_square / 9.0)
    f32 = np.float32

    def block(r0, r1):
        n = r1 - r0

        def nb(a, ii, jj):
            return a[r0 + ii * mult: r0 + ii * mult + n, jj * mult: jj * mult + w]

        lf9 = [nb(lp, ii, jj) for ii in range(3) for jj in range(3)]
        hf9 = [nb(hp, ii, jj) for ii in range(3) for jj in range(3)]

        def direction(nine):
            """The gradient of this layer: (its magnitude, cos, sin, cos^2, sin^2, cos*sin) of its angle."""
            g0 = (nine[7] - nine[1]) * f32(0.5)
            g1 = (nine[5] - nine[3]) * f32(0.5)
            mag = np.sqrt(g0 * g0 + g1 * g1)
            ok = mag != 0
            safe = np.where(ok, mag, f32(1.0))
            cos = np.where(ok, g0 / safe, f32(1.0))
            sin = np.where(ok, g1 / safe, f32(0.0))
            return mag, cos * cos, sin * sin, cos * sin

        need_g = any(isotropy[k] != ISOTROPE for k in (0, 2))
        need_l = any(isotropy[k] != ISOTROPE for k in (1, 3))
        dg = direction(lf9) if need_g else None
        dl = direction(hf9) if need_l else None

        def shared(nine):
            return {"corner": nine[0] + nine[8] - nine[2] - nine[6], "v": nine[1] + nine[7], "h": nine[3] + nine[5],
                    "iso": f32(0.25) * (nine[0] + nine[2] + nine[6] + nine[8]) + f32(0.5) * (nine[1] + nine[3] + nine[5] + nine[7]) - f32(3.0) * nine[4]}

        sums_l, sums_h = shared(lf9), shared(hf9)

        def derivative(k, nine, sums, direction_):
            mode = isotropy[k]
            if mode == ISOTROPE:
                return sums["iso"]
            mag, cos2, sin2, cs = direction_
            c2 = np.exp(-mag * f32(anisotropy[k]))
            if mode == ISOPHOTE:
                a00, a11, a01 = cos2 + c2 * sin2, c2 * cos2 + sin2, (c2 - f32(1.0)) * cs
            else:
                a00, a11, a01 = c2 * cos2 + sin2, cos2 + c2 * sin2, (f32(1.0) - c2) * cs
            return (a01 * f32(0.5)) * sums["corner"] + a11 * sums["v"] + a00 * sums["h"] - f32(2.0) * (a00 + a11) * nine[4]

        d0 = derivative(0, lf9, sums_l, dg)
        d1 = derivative(1, lf9, sums_l, dl)
        d2 = derivative(2, hf9, sums_h, dg if need_g else None)
        d3 = derivative(3, hf9, sums_h, dl)
        variance = hf9[0] * hf9[0]
        for k in range(1, 9):
            variance += hf9[k] * hf9[k]
        variance *= regularization_factor
        variance += f32(variance_threshold)
        acc = d0 * f32(abcd[0]) + d1 * f32(abcd[1]) + d2 * f32(abcd[2]) + d3 * f32(abcd[3])
        acc /= variance
        acc += hf[r0:r1] * f32(strength)
        acc += lf[r0:r1]
        np.maximum(acc, 0.0, out=acc)
        if mask is not None:
            m = mask[r0:r1, :, None]
            acc = np.where(m, acc, hf[r0:r1] + lf[r0:r1])
        out[r0:r1] = acc

    _map_rows(block, h, w)
    return out


def _one_pass(pixels: np.ndarray, values: dict, mask, zoom: float, scales: int) -> np.ndarray:
    """wavelets_process: decompose into `scales` wavelet scales and rebuild them from the coarsest, solving the PDE on each."""
    anisotropy = [float(values[k]) ** 2 for k in ("dif_aniso_first", "dif_aniso_second", "dif_aniso_third", "dif_aniso_fourth")]
    isotropy = [ISOTROPE if float(values[k]) == 0.0 else (ISOPHOTE if float(values[k]) > 0.0 else GRADIENT)
                for k in ("dif_aniso_first", "dif_aniso_second", "dif_aniso_third", "dif_aniso_fourth")]
    regularization = 10.0 ** float(values["dif_regularization"]) - 1.0
    variance_threshold = 10.0 ** float(values["dif_variance_threshold"])
    speeds = [float(values[k]) for k in ("dif_first", "dif_second", "dif_third", "dif_fourth")]
    radius = max(float(values["dif_radius"]), 1e-3)
    centre = float(values["dif_radius_center"])
    sharpness = float(values["dif_sharpness"])

    highs = []
    current = pixels
    for s in range(scales):
        current, high = _decompose(current, 1 << s)
        highs.append(high)
    residual = current
    for s in range(scales - 1, -1, -1):
        sigma = equivalent_sigma_at_step(B_SPLINE_SIGMA, s)
        real = sigma * zoom
        norm = math.exp(-((real - centre) ** 2) / (radius ** 2))
        abcd = [speed * KAPPA * norm for speed in speeds]
        strength = sharpness * norm + 1.0
        residual = _pde(highs[s], residual, mask, 1 << s, anisotropy, isotropy, regularization, variance_threshold, sigma ** 2, abcd, strength)
        highs[s] = None
    return residual


# ---------------------------------------------------------------------------------------------------------------------------------------------- the module
_TO_LINEAR = None
_FROM_LINEAR = None
_FROM_STEPS = 16384


def _tables():
    global _TO_LINEAR, _FROM_LINEAR
    if _TO_LINEAR is None:
        v = np.arange(256, dtype=np.float32) / 255.0
        _TO_LINEAR = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4).astype(np.float32)
        x = np.linspace(0.0, 1.0, _FROM_STEPS + 1, dtype=np.float32)
        s = np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)
        _FROM_LINEAR = np.clip(np.rint(s * 255.0), 0, 255).astype(np.uint8)
    return _TO_LINEAR, _FROM_LINEAR


def _to_linear(pixels: np.ndarray) -> np.ndarray:
    return _tables()[0][pixels]


def _from_linear(linear: np.ndarray) -> np.ndarray:
    table = _tables()[1]
    idx = np.clip(linear * np.float32(_FROM_STEPS) + np.float32(0.5), 0, _FROM_STEPS).astype(np.int32)
    return table[idx]


def _process_linear(linear: np.ndarray, values: dict, zoom: float) -> np.ndarray:
    iterations = max(int(round(float(values["dif_iterations"]))), 1)
    scales = scales_for(values, zoom)
    mask = None
    work = linear
    threshold = float(values["dif_threshold"])
    if threshold > 0:
        mask = (linear > threshold).any(axis=2)
        rng = np.random.default_rng(1337)       # init the inpainting area with noise, as darktable does
        noise = np.abs(rng.normal(loc=linear, scale=np.maximum(linear, 1e-6))).astype(np.float32)
        work = np.where(mask[:, :, None], noise, linear)
    for _ in range(iterations):
        work = _one_pass(work, values, mask, zoom, scales)
    return work


def apply_diffuse(pixels: np.ndarray, values: dict | None, zoom: float = 1.0, use_gpu: bool = True) -> np.ndarray:
    """The picture (uint8 RGB) diffused or sharpened by `values`. `zoom` is the full picture's pixels per pixel of this one (1 for the full picture, more for the editing preview). The graphics
    card does it when there is one that can take the picture (features/gpu/diffuse.py); the processor does it otherwise, and always when `use_gpu` is False."""
    if is_neutral(values):
        return pixels
    full = {**DEFAULTS, **{k: float(v) for k, v in (values or {}).items() if k in DEFAULTS}}
    zoom = max(float(zoom), 1.0)
    if use_gpu:
        from ..gpu import diffuse as gpu_diffuse

        on_card = gpu_diffuse.process(pixels, full, zoom)
        if on_card is not None:
            return on_card
    scales = scales_for(full, zoom)
    h, w = pixels.shape[:2]
    per_pixel = 3 * (scales + 7)                    # the high-frequency layer of each scale, plus the working copies
    rows = max(64, _BUDGET // max(1, w * per_pixel))
    if rows >= h:
        return _from_linear(_process_linear(_to_linear(pixels), full, zoom))
    overlap = (1 << scales) * max(1, int(round(float(full["dif_iterations"]) ** 0.5)))
    rows = max(rows, 4 * overlap)
    out = np.empty_like(pixels)
    y = 0
    while y < h:
        y1 = min(h, y + rows)
        r0, r1 = max(0, y - overlap), min(h, y1 + overlap)
        done = _from_linear(_process_linear(_to_linear(pixels[r0:r1]), full, zoom))
        out[y:y1] = done[y - r0: y - r0 + (y1 - y)]
        y = y1
    return out


APPLY = apply_diffuse                 # what the renderer calls (desktop/render.py)
