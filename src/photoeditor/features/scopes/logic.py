"""Waveform, RGB parade and vectorscope: other ways to read a picture's tones and colours than the histogram. No Qt imports.

A waveform lays the picture out as it is across: each column of the graph holds the brightness values of that column of the picture, so a bright sky reads high on the left and a dark
foreground low. The parade is the same for red, green and blue side by side (a colour cast is one channel sitting above or below the others). The vectorscope plots every pixel by its
hue (the angle) and saturation (the distance from the middle).
"""

import numpy as np

SIZE = 256            # the graph's height: one row for each 8-bit value
MAX_COLUMNS = 480     # a wider picture is read at every k-th column, a taller one at every k-th row
VECTOR_SIZE = 256
# the primaries and secondaries at 75% saturation, where a colour bar test pattern puts them (Cb, Cr of BT.709)
TARGETS = {"R": (1.0, 0.0, 0.0), "Y": (1.0, 1.0, 0.0), "G": (0.0, 1.0, 0.0), "C": (0.0, 1.0, 1.0), "B": (0.0, 0.0, 1.0), "M": (1.0, 0.0, 1.0)}
SKIN_ANGLE = np.radians(123.0)       # the skin-tone line on a vectorscope (I line), measured from the +Cb axis towards +Cr


def prepare(rgb: np.ndarray, max_columns: int = MAX_COLUMNS) -> np.ndarray:
    """The picture as 8-bit RGB, thinned to at most max_columns columns and as many rows."""
    a = np.asarray(rgb)
    if a.dtype == np.uint16:
        a = (a >> 8).astype(np.uint8)
    elif a.dtype != np.uint8:
        a = np.clip(a * 255.0, 0, 255).astype(np.uint8)
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, axis=2)
    step_x = max(1, -(-a.shape[1] // max_columns))
    step_y = max(1, -(-a.shape[0] // max_columns))
    return np.ascontiguousarray(a[::step_y, ::step_x, :3])


def luma(rgb8: np.ndarray) -> np.ndarray:
    """Rec. 709 brightness (uint8) of an 8-bit picture."""
    y = 0.2126 * rgb8[..., 0] + 0.7152 * rgb8[..., 1] + 0.0722 * rgb8[..., 2]
    return np.clip(np.rint(y), 0, 255).astype(np.uint8)


def _counts(values: np.ndarray) -> np.ndarray:
    """(SIZE, W) how many pixels of each column have each value, row 0 being value 255 (the top of the graph)."""
    h, w = values.shape
    index = values.astype(np.int64) * w + np.arange(w)[None, :]
    counts = np.bincount(index.ravel(), minlength=SIZE * w).reshape(SIZE, w)
    return counts[::-1]


def _intensity(counts: np.ndarray, rows: int) -> np.ndarray:
    """Counts as brightness 0..1: a value held by about one pixel in fifty of its column is full, and the fainter ones are lifted so a thin trace still shows."""
    return np.clip(counts / max(rows * 0.02, 1.0), 0.0, 1.0) ** 0.6


def waveform(rgb: np.ndarray) -> np.ndarray:
    """The luma waveform: (SIZE, W) brightness 0..1."""
    small = prepare(rgb)
    return _intensity(_counts(luma(small)), small.shape[0])


def parade(rgb: np.ndarray) -> np.ndarray:
    """The RGB parade: (SIZE, 3W, 3) with the red, green and blue waveforms side by side, each in its own colour."""
    small = prepare(rgb)
    w = small.shape[1]
    out = np.zeros((SIZE, 3 * w, 3), dtype=np.float32)
    for c in range(3):
        out[:, c * w:(c + 1) * w, c] = _intensity(_counts(small[..., c]), small.shape[0])
    return out


def chroma(rgb8: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(Cb, Cr) of an 8-bit picture, each -0.5..0.5 (BT.709)."""
    f = rgb8.astype(np.float32) / 255.0
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    return -0.114572 * r - 0.385428 * g + 0.5 * b, 0.5 * r - 0.454153 * g - 0.045847 * b


def vector_point(color) -> tuple[float, float]:
    """Where a colour lands on the vectorscope, as fractions of the graph (x to the right, y upwards from the middle: 0..1 each)."""
    cb, cr = chroma(np.array([[[round(v * 255 * 0.75) for v in color]]], dtype=np.uint8))
    return float(cb[0, 0]) + 0.5, float(cr[0, 0]) + 0.5


def vectorscope(rgb: np.ndarray, size: int = VECTOR_SIZE) -> np.ndarray:
    """The vectorscope: (size, size) brightness 0..1, Cb to the right and Cr up, the middle (no colour) at the centre."""
    small = prepare(rgb)
    cb, cr = chroma(small)
    x = np.clip(((cb + 0.5) * (size - 1)).round().astype(np.int64), 0, size - 1)
    y = np.clip(((0.5 - cr) * (size - 1)).round().astype(np.int64), 0, size - 1)
    counts = np.bincount((y * size + x).ravel(), minlength=size * size).reshape(size, size).astype(np.float32)
    peak = max(float(np.percentile(counts[counts > 0], 99)) if (counts > 0).any() else 1.0, 1.0)
    density = np.clip(counts / peak, 0.0, 1.0) ** 0.5
    padded = np.pad(density, 1)
    return np.max([padded[dy:dy + size, dx:dx + size] for dy in range(3) for dx in range(3)], axis=0)      # (each dot a little wider, so a sparse picture still shows)


def tint(density: np.ndarray, color=(0.85, 1.0, 0.85)) -> np.ndarray:
    """A brightness picture as an 8-bit RGB one in a phosphor tint (a picture that is already RGB is only scaled to 8 bits)."""
    if density.ndim == 3:
        return np.clip(density * 255.0, 0, 255).astype(np.uint8)
    return np.clip(density[..., None] * np.array(color, dtype=np.float32) * 255.0, 0, 255).astype(np.uint8)


# --- the zone map: the picture's brightness in eleven zones (0 black to X white, a stop apart in a darkroom's way of counting), each its own colour, so what is crushed, what is a middle
# tone and what is blown shows at a glance ---
ZONE_COUNT = 11
ZONE_COLORS = ((40, 0, 70), (30, 40, 150), (30, 95, 205), (25, 155, 210), (30, 170, 150), (125, 125, 125), (165, 195, 70), (230, 205, 60), (240, 140, 40), (230, 70, 50), (255, 255, 255))
ZONE_NAMES = ("0", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")


def zones(rgb: np.ndarray) -> np.ndarray:
    """The zone (0-10) of each pixel of a picture, from its brightness: the 0-255 range cut into eleven equal bands."""
    y = luma(prepare(rgb, 1 << 20))
    return np.minimum(y.astype(np.int32) * ZONE_COUNT // 256, ZONE_COUNT - 1).astype(np.uint8)


def zone_overlay(rgb: np.ndarray) -> np.ndarray:
    """The zone map as an (h, w, 4) RGBA picture (opaque), the size of the picture."""
    a = np.asarray(rgb)
    z = zones(a)
    table = np.array(ZONE_COLORS, dtype=np.uint8)
    out = np.empty(z.shape + (4,), dtype=np.uint8)
    out[..., :3] = table[z]
    out[..., 3] = 255
    return out


def zone_shares(rgb: np.ndarray) -> list[float]:
    """The share (0-1) of the picture in each zone."""
    z = zones(rgb)
    counts = np.bincount(z.ravel(), minlength=ZONE_COUNT).astype(np.float64)
    return (counts / max(counts.sum(), 1.0)).tolist()


def zone_highlight(rgb: np.ndarray, zone: int) -> np.ndarray:
    """One zone shown alone: an (h, w, 4) RGBA picture that darkens everything outside the zone and draws a white line round the zone's regions, so the part of the picture in that zone stands out
    (hovering a zone on the scope's strip)."""
    inside = zones(rgb) == int(zone)
    padded = np.pad(inside, 1, constant_values=False)
    eroded = np.logical_and.reduce([padded[dy:dy + inside.shape[0], dx:dx + inside.shape[1]] for dy in range(3) for dx in range(3)])
    edge = inside & ~eroded
    out = np.zeros(inside.shape + (4,), dtype=np.uint8)
    out[~inside] = (0, 0, 0, 170)
    out[edge] = (255, 255, 255, 255)
    return out
