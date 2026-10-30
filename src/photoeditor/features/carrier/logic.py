"""Negative carrier: the black rebate frame a filed-out negative carrier prints round the picture - numpy only, no Qt.

A port of NegPy's filed carrier (negpy/features/finish: GPL-3, the same licence as EFAS). In the darkroom a negative carrier whose aperture is filed larger than the frame prints the
film's own rebate: the dark edge of the film between the picture and the filed metal, and then, past the metal, a margin of bare paper. Its edges are not clean: the film gate that
holds the film is a little uneven, the filed aperture is ragged (file strokes, nicks, rounded corners), and light flares off the bevel of the metal.

    Width    how wide the rebate prints, in mm on a 30 cm print (0 = off); it scales with the picture, so a preview and an export look the same
    Rough    how ragged the filed edge is
    Corner   how round the filed aperture's corners are
    Flare    the bright line light makes along the filed bevel (0 = none)

The picture is composited in linear light over the paper. The filed edge and the flare are exposure: the more of the paper is exposed, the darker it prints. The pattern is fixed (one filed
carrier for every frame, from a fixed seed), so the same photo always prints the same edge. It works on the finished, cropped picture (8-bit)."""
import numpy as np

KEYS = ("carrier_width", "carrier_rough", "carrier_corner", "carrier_flare")
DEFAULTS = {"carrier_width": 0.0, "carrier_rough": 0.25, "carrier_corner": 0.25, "carrier_flare": 0.5}
WIDTH_RANGE = (0.0, 5.0)
PRINT_LONG_EDGE_MM = 300.0     # the print the width is measured on: a 30 cm long edge, as NegPy's default

_SEED = 1898                    # one filed carrier per darkroom, identical every frame
SAMPLES = 2048                  # profile samples per edge
# Fractions of the rebate width (NegPy's finish.rs). The picture-side boundary is the film gate, machine-cut: JITTER * INNER_ROUGH and no slider. The paper-side one is the hand-filed aperture.
JITTER = 0.24
INNER_ROUGH = 0.2
OUTER_JITTER = 0.4
CORNER = 1.4
GATE_CORNER = 0.2
OFFSET_X = -0.2                 # the film never sits centred in the carrier
OFFSET_Y = -0.25
MARGIN = 0.7
SOFT = 0.22                     # the gate prints soft; filed metal is a hard stop, which is what reads as filed
FILED_SOFT = 0.06
FLARE_DEPTH = 0.25
FLARE_GAIN = 0.6
FLARE_BASE = 0.35
NOISE_SEED = 0x51ED270B
NOISE_CELL = 0.35
NOISE_OCTAVES = 4
NOISE_OUTER = 0.12
NOISE_INNER = 0.02

_profiles: np.ndarray | None = None


def is_neutral(values: dict | None) -> bool:
    return float((values or {}).get("carrier_width", 0.0)) <= 1e-9


def width_px(width_mm: float, long_edge_px: float) -> float:
    """The rebate's width in pixels for a picture whose longer side is this many pixels."""
    return float(width_mm) / PRINT_LONG_EDGE_MM * float(long_edge_px)


# ------------------------------------------------------------ the filed edge: fixed profiles
def _blur(rows: np.ndarray, sigma: float) -> np.ndarray:
    taps = int(np.ceil(sigma * 3.0))
    k = np.exp(-0.5 * (np.arange(-taps, taps + 1, dtype=np.float32) / sigma) ** 2)
    k /= k.sum()
    tiled = np.concatenate([rows, rows, rows], axis=1)      # circular, so a profile has no seam where an edge wraps
    return np.stack([np.convolve(row, k, mode="same") for row in tiled])[:, SAMPLES:2 * SAMPLES]


def _norm(rows: np.ndarray) -> np.ndarray:
    return rows / np.max(np.abs(rows), axis=1, keepdims=True)


def _filed_edge(rng: np.random.Generator) -> np.ndarray:
    """Straight file strokes plus nicks and spurs, crowded toward the corners."""
    i = np.arange(SAMPLES, dtype=np.float32)
    knots = np.concatenate([[0.0], np.cumsum(rng.uniform(80.0, 320.0, 24))])
    knots = knots[knots < SAMPLES]
    strokes = np.interp(i, np.append(knots, SAMPLES), rng.normal(0.0, 0.25, len(knots) + 1))
    ends = np.minimum(i, SAMPLES - 1.0 - i) / SAMPLES
    corner = 1.0 + 2.0 * np.exp(-ends / 0.05)
    marks = np.zeros(SAMPLES, dtype=np.float32)
    for _ in range(14):
        at = rng.uniform(0.0, 0.12) if rng.random() < 0.5 else rng.uniform(0.0, 0.5)
        centre = (at if rng.random() < 0.5 else 1.0 - at) * SAMPLES
        half = rng.uniform(10.0, 26.0)
        depth = rng.uniform(0.4, 1.0) * (-1.0 if rng.random() < 0.7 else 0.6)
        x = np.clip(np.abs(i - centre) / half, 0.0, 1.0)
        marks += depth * 0.5 * (1.0 + np.cos(np.pi * x))
    return ((strokes + marks) * corner).astype(np.float32)


def profiles() -> np.ndarray:
    """(8, SAMPLES) float32 in [-1, 1]: rows 0-3 the film gate's wobble, rows 4-7 the filed edge's roughness, each ordered top, bottom, left, right."""
    global _profiles
    if _profiles is None:
        rng = np.random.default_rng(_SEED)
        raw = rng.standard_normal((8, SAMPLES)).astype(np.float32)
        gate = _blur(raw[:4], 60.0)
        filed = np.stack([_filed_edge(rng) for _ in range(4)])
        _profiles = np.ascontiguousarray(_norm(np.concatenate([gate, filed])), dtype=np.float32)
    return _profiles


# ------------------------------------------------------------ 2-D value noise (the torn-metal look)
def _hash_lattice(ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):
        h = ix * np.uint32(0x27D4EB2D) ^ iy * np.uint32(0x165667B1) ^ np.uint32(NOISE_SEED)
        h ^= h >> np.uint32(15)
        h = h * np.uint32(0x2C1B3C6D)
        h ^= h >> np.uint32(13)
        h = h * np.uint32(0x297A2D39)
        h ^= h >> np.uint32(16)
    return (h >> np.uint32(8)).astype(np.float32) * np.float32(2.0 / 16777216.0) - np.float32(1.0)


def _value_noise(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    fx, fy = np.floor(x), np.floor(y)
    ux, uy = x - fx, y - fy
    ux = ux * ux * (3.0 - 2.0 * ux)
    uy = uy * uy * (3.0 - 2.0 * uy)
    i0, j0 = fx.astype(np.int64).astype(np.uint32), fy.astype(np.int64).astype(np.uint32)
    i1, j1 = i0 + np.uint32(1), j0 + np.uint32(1)
    lo = _hash_lattice(i0, j0)
    lo = lo + (_hash_lattice(i1, j0) - lo) * ux
    hi = _hash_lattice(i0, j1)
    hi = hi + (_hash_lattice(i1, j1) - hi) * ux
    return lo + (hi - lo) * uy


def noise(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Fractal value noise in [-1, 1]; x and y in noise cells."""
    total = np.zeros_like(x, dtype=np.float32)
    amp, freq, norm = 1.0, 1.0, 0.0
    for _ in range(NOISE_OCTAVES):
        total += np.float32(amp) * _value_noise(x * freq, y * freq)
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / np.float32(norm)


def _arc(r: float, at: float, end: np.ndarray) -> np.ndarray:
    """The retreat of a boundary `at` pixels from the print's edge round a corner of radius r."""
    if r <= 0.0:
        return np.zeros_like(end)
    x = np.clip(r - (end - at), 0.0, r)
    return (r - np.sqrt(np.maximum(r * r - x * x, 0.0))).astype(np.float32)


def band_px(width: float, corner: float) -> int:
    """How far in from the print's edge the carrier has any effect."""
    extent = MARGIN + CORNER * corner + 1.0 + JITTER + NOISE_OUTER + NOISE_INNER + max(abs(OFFSET_X), abs(OFFSET_Y))
    return int(np.ceil(width * extent + max(width * SOFT, 1.0))) + 1


# ------------------------------------------------------------ the carrier
def _fields(h: int, w: int, ys: np.ndarray, xs: np.ndarray, width: float, rough: float, flare: float, corner: float):
    """At the pixels (ys, xs): how much of the picture shows (`shown`, 0..1) and how exposed the paper is (`exposure`, 0 bare paper .. 1 black)."""
    prof = profiles()
    soft, soft_filed = max(width * SOFT, 1.0), max(width * FILED_SOFT, 1.0)
    margin, radius, gate_radius = width * MARGIN, width * CORNER * corner, width * GATE_CORNER
    cell, off_x, off_y, reach = max(width * NOISE_CELL, 1.0), width * OFFSET_X, width * OFFSET_Y, max(width * FLARE_DEPTH, 1.0)
    px, py = xs.astype(np.float32), ys.astype(np.float32)
    wl, hl = float(w - 1), float(h - 1)
    sx, sy = (px + 0.5) / w, (py + 0.5) / h
    end_x, end_y = np.minimum(px, wl - px), np.minimum(py, hl - py)
    qx, qy = px - off_x, py - off_y
    fend_x, fend_y = np.minimum(qx, wl - qx), np.minimum(qy, hl - qy)
    n2 = noise(px / cell, py / cell)
    wr = width * rough
    a_in = np.ones(px.shape, np.float32)
    a_out = np.ones(px.shape, np.float32)
    peaks, gates = [], []
    for e in range(4):
        s, end, fend, dist, fdist = ((sx, end_x, fend_x, py, qy), (sx, end_x, fend_x, hl - py, hl - qy), (sy, end_y, fend_y, px, qx), (sy, end_y, fend_y, wl - px, wl - qx))[e]
        i_out = np.clip(np.floor(s * SAMPLES).astype(np.int64), 0, SAMPLES - 1)
        jitter = OUTER_JITTER * prof[e + 4][i_out] + NOISE_OUTER * n2
        outer = margin + wr * jitter + _arc(radius, margin, fend)
        wobble = JITTER * INNER_ROUGH * prof[e][i_out] + NOISE_INNER * n2
        inner = margin + width * (1.0 + wobble) + _arc(gate_radius, margin + width, end)
        a_in *= np.clip((dist - inner) / soft + 0.5, 0.0, 1.0)
        a_out *= np.clip((fdist - outer) / soft_filed + 0.5, 0.0, 1.0)
        p = np.clip(1.0 - np.abs(fdist - outer) / reach, 0.0, 1.0)
        peaks.append(p * p)
        gates.append(np.clip(1.0 + (fdist - outer) / reach, 0.0, 1.0))
    lit = np.zeros(px.shape, np.float32)
    if flare > 0.0:   # the bevel spans only the aperture, so the other edges gate each edge's flare
        for e in range(4):
            g = np.ones(px.shape, np.float32)
            for k in range(4):
                if k != e:
                    g = g * gates[k]
            lit += peaks[e] * g
        lit *= np.float32(flare * FLARE_GAIN) * (FLARE_BASE + (1.0 - FLARE_BASE) * np.abs(n2))
    return a_in * a_out, np.clip(a_out + lit, 0.0, 1.0)


def _to_linear(v: np.ndarray) -> np.ndarray:
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _to_srgb(v: np.ndarray) -> np.ndarray:
    v = np.clip(v, 0.0, 1.0)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1.0 / 2.4) - 0.055)


def apply_carrier(pixels: np.ndarray, values: dict | None, paper: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> np.ndarray:
    """The 8-bit RGB picture with the filed carrier's rebate printed along its edges; a width of 0 returns it untouched. `paper` is the colour of the bare paper (sRGB, 0..1)."""
    v = values or {}
    if is_neutral(v) or pixels.ndim != 3 or pixels.shape[2] != 3:
        return pixels
    h, w = pixels.shape[:2]
    width = width_px(float(np.clip(v.get("carrier_width", 0.0), *WIDTH_RANGE)), max(h, w))
    if width <= 0.0:
        return pixels
    rough = float(np.clip(v.get("carrier_rough", DEFAULTS["carrier_rough"]), 0.0, 1.0))
    corner = float(np.clip(v.get("carrier_corner", DEFAULTS["carrier_corner"]), 0.0, 1.0))
    flare = float(np.clip(v.get("carrier_flare", DEFAULTS["carrier_flare"]), 0.0, 1.0))
    band = band_px(width, corner)
    region = np.zeros((h, w), bool)
    if 2 * band >= h or 2 * band >= w:
        region[:] = True
    else:
        region[:band] = region[h - band:] = True
        region[:, :band] = region[:, w - band:] = True
    ys, xs = np.nonzero(region)
    shown, exposure = _fields(h, w, ys, xs, width, rough, flare, corner)
    src = _to_linear(pixels[ys, xs].astype(np.float32) / 255.0)
    bare = _to_linear(np.asarray(paper, dtype=np.float32))[None, :] * (1.0 - exposure)[:, None]
    mixed = src * shown[:, None] + bare * (1.0 - shown)[:, None]
    out = pixels.copy()
    out[ys, xs] = np.clip(_to_srgb(mixed) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out
