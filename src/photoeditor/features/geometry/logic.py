"""Pure crop/rotate/flip geometry - numpy (and OpenCV for fine rotation), no Qt/UI imports."""

import math

import numpy as np

Rect = tuple[int, int, int, int]


def rotate_left(pixels: np.ndarray) -> np.ndarray:
    """Rotate 90 degrees counter-clockwise."""
    return np.ascontiguousarray(np.rot90(pixels, k=1))


def rotate_right(pixels: np.ndarray) -> np.ndarray:
    """Rotate 90 degrees clockwise."""
    return np.ascontiguousarray(np.rot90(pixels, k=-1))


def rotate_quarter_turns(pixels: np.ndarray, turns: int) -> np.ndarray:
    """turns is a count of 90-degree clockwise rotations (negative values
    rotate counter-clockwise); only turns % 4 matters."""
    if turns % 4 == 0:
        return pixels
    return np.ascontiguousarray(np.rot90(pixels, k=-turns))


def flip_horizontal(pixels: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.fliplr(pixels))


def flip_vertical(pixels: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.flipud(pixels))


def apply_crop(pixels: np.ndarray, rect: Rect | None) -> np.ndarray:
    """rect is in this exact array's own pixel coordinates - the caller
    (AppController) is responsible for carrying the rect through
    transform_rect_rotate_left/_right/transform_rect_flip_h/_v whenever a
    rotation/flip changes the array's dimensions ahead of this step."""
    if rect is None:
        return pixels
    h, w = pixels.shape[:2]
    x1, x2 = sorted((max(0, min(rect[0], w)), max(0, min(rect[2], w))))
    y1, y2 = sorted((max(0, min(rect[1], h)), max(0, min(rect[3], h))))
    if x2 - x1 < 1 or y2 - y1 < 1:
        return pixels
    return np.ascontiguousarray(pixels[y1:y2, x1:x2])


def transform_rect_rotate_right(rect: Rect, height: int) -> Rect:
    """Carries a crop rect through rotate_right: a rect in a frame of this
    height maps to the equivalent rect in that frame rotated 90 degrees
    clockwise (now width=height, height=old width)."""
    x1, y1, x2, y2 = rect
    return (height - y2, x1, height - y1, x2)


def transform_rect_rotate_left(rect: Rect, width: int) -> Rect:
    """Carries a crop rect through rotate_left: a rect in a frame of this
    width maps to the equivalent rect in that frame rotated 90 degrees
    counter-clockwise (now width=old height, height=width)."""
    x1, y1, x2, y2 = rect
    return (y1, width - x2, y2, width - x1)


def transform_rect_flip_h(rect: Rect, width: int) -> Rect:
    """Carries a crop rect through flip_horizontal on a frame of this width."""
    x1, y1, x2, y2 = rect
    return (width - x2, y1, width - x1, y2)


def transform_rect_flip_v(rect: Rect, height: int) -> Rect:
    """Carries a crop rect through flip_vertical on a frame of this height."""
    x1, y1, x2, y2 = rect
    return (x1, height - y2, x2, height - y1)


FINE_ROTATION_LIMIT = 45.0


def _fine_matrix(degrees: float, w: int, h: int) -> np.ndarray:
    """The 2x3 affine matrix of a fine rotation: clockwise by `degrees` about
    the center, scaled up just enough that the rotated picture still covers
    the whole frame (no blank corners), so the frame keeps its size and
    everything downstream (the crop rect, a later quarter turn) is unaffected."""
    theta = math.radians(abs(degrees))
    cos, sin = math.cos(theta), math.sin(theta)
    scale = max((w * cos + h * sin) / w, (w * sin + h * cos) / h)
    alpha = math.radians(-degrees)
    a, b = scale * math.cos(alpha), scale * math.sin(alpha)
    cx, cy = w / 2.0, h / 2.0
    return np.array([[a, b, (1 - a) * cx - b * cy], [-b, a, b * cx + (1 - a) * cy]], dtype=np.float64)


def fine_rotate(pixels: np.ndarray, degrees: float, nearest: bool = False) -> np.ndarray:
    """Straighten by an arbitrary small angle (positive = clockwise)."""
    if abs(degrees) < 1e-3:
        return pixels
    import cv2

    h, w = pixels.shape[:2]
    matrix = _fine_matrix(degrees, w, h)
    flags = cv2.INTER_NEAREST if nearest else cv2.INTER_LINEAR
    return cv2.warpAffine(np.ascontiguousarray(pixels), matrix, (w, h), flags=flags, borderMode=cv2.BORDER_REPLICATE)


def unfine_rotate_point(px: float, py: float, degrees: float, w: int, h: int) -> tuple[float, float]:
    """Undo fine_rotate for a point given as 0..1 fractions of a w x h frame."""
    if abs(degrees) < 1e-3:
        return px, py
    forward = np.vstack([_fine_matrix(degrees, w, h), [0.0, 0.0, 1.0]])
    x, y, _ = np.linalg.inv(forward) @ np.array([px * w, py * h, 1.0])
    return float(x / w), float(y / h)


DISTORTION_LIMIT = 0.10
_DISTORT_EPS = 1e-6
_distort_cache: dict = {}


def _radial_center(w: int, h: int) -> tuple[float, float, float]:
    return (w - 1) * 0.5, (h - 1) * 0.5, 0.5 * math.hypot(w, h)


def distortion_scale(k1: float, w: int, h: int, samples: int = 128) -> float:
    """The largest scale at which the corrected frame still maps fully inside
    the source - fills the frame with no empty or smeared border. Numeric,
    so it works for barrel and pincushion alike."""
    if abs(k1) < 1e-9:
        return 1.0
    cx, cy, halfdiag = _radial_center(w, h)
    t = np.arange(max(1, samples // 4), dtype=np.float64) / max(1, samples // 4)
    xs, ys = -cx + 2 * cx * t, -cy + 2 * cy * t
    pts = np.concatenate([
        np.stack([xs, np.full_like(xs, -cy)], 1), np.stack([xs, np.full_like(xs, cy)], 1),
        np.stack([np.full_like(ys, -cx), ys], 1), np.stack([np.full_like(ys, cx), ys], 1),
    ])
    inv_hd2 = 1.0 / (halfdiag * halfdiag)

    def max_ratio(scale: float) -> float:
        px, py = pts[:, 0] * scale, pts[:, 1] * scale
        f = 1.0 + k1 * (px * px + py * py) * inv_hd2
        if (f <= 0).any():
            return math.inf
        return float(max((np.abs(px * f) / max(cx, 1e-9)).max(), (np.abs(py * f) / max(cy, 1e-9)).max()))

    lo, hi = 1e-3, 1.0
    while max_ratio(hi) < 1.0 and hi < 1e3:
        hi *= 2.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if max_ratio(mid) < 1.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _radial_maps(k1: float, w: int, h: int):
    key = (round(k1, 9), w, h)
    cached = _distort_cache.get("last")
    if cached is not None and cached[0] == key:
        return cached[1]
    cx, cy, halfdiag = _radial_center(w, h)
    s = distortion_scale(k1, w, h)
    ys, xs = np.meshgrid(np.arange(h, dtype=np.float32), np.arange(w, dtype=np.float32), indexing="ij")
    px, py = (xs - cx) * np.float32(s), (ys - cy) * np.float32(s)
    f = 1.0 + np.float32(k1) * (px * px + py * py) * np.float32(1.0 / (halfdiag * halfdiag))
    maps = ((cx + px * f).astype(np.float32), (cy + py * f).astype(np.float32))
    if w * h <= 4_000_000:
        _distort_cache["last"] = (key, maps)
    return maps


def radial_distort(pixels: np.ndarray, k1: float, nearest: bool = False) -> np.ndarray:
    """Radial lens-distortion correction (positive k1 corrects barrel,
    negative pincushion), via a coordinate remap - it only moves pixels, so
    brightness is untouched. The frame keeps its size, scaled to fill."""
    if abs(k1) < _DISTORT_EPS:
        return pixels
    import cv2

    h, w = pixels.shape[:2]
    map_x, map_y = _radial_maps(k1, w, h)
    flags = cv2.INTER_NEAREST if nearest else cv2.INTER_LINEAR
    return cv2.remap(np.ascontiguousarray(pixels), map_x, map_y, interpolation=flags, borderMode=cv2.BORDER_REPLICATE)


def undistort_point(px: float, py: float, k1: float, w: int, h: int) -> tuple[float, float]:
    """A point in the corrected frame (0..1 fractions) -> where it came from in the uncorrected one."""
    if abs(k1) < _DISTORT_EPS:
        return px, py
    cx, cy, halfdiag = _radial_center(w, h)
    s = distortion_scale(k1, w, h)
    x, y = (px * (w - 1) - cx) * s, (py * (h - 1) - cy) * s
    f = 1.0 + k1 * (x * x + y * y) / (halfdiag * halfdiag)
    return (cx + x * f) / (w - 1), (cy + y * f) / (h - 1)


def map_display_to_raw(
    u: float,
    v: float,
    crop_rect: tuple[int, int, int, int] | None,
    frame_size: tuple[int, int],
    rotation_quarter_turns: int,
    flip_h: bool,
    flip_v: bool,
    fine_rotation: float = 0.0,
    distortion: float = 0.0,
) -> tuple[float, float]:
    """A point in the displayed (cropped, rotated, flipped) image, as 0..1
    fractions (u, v), -> the same point in the untouched raw scan's own 0..1
    frame. frame_size is (height, width) of the pre-crop frame crop_rect is
    expressed in. Undoes the pipeline in reverse: crop, flips, quarter turns,
    then the fine rotation."""
    h, w = frame_size
    if crop_rect is not None:
        x1, y1, x2, y2 = crop_rect
        px, py = (x1 + u * (x2 - x1)) / w, (y1 + v * (y2 - y1)) / h
    else:
        px, py = u, v
    if flip_v:
        py = 1.0 - py
    if flip_h:
        px = 1.0 - px
    for _ in range(rotation_quarter_turns % 4):
        px, py = py, 1.0 - px
    raw_h, raw_w = (w, h) if rotation_quarter_turns % 2 else (h, w)
    if distortion:
        px, py = undistort_point(px, py, distortion, raw_w, raw_h)
    if fine_rotation:
        px, py = unfine_rotate_point(px, py, fine_rotation, raw_w, raw_h)
    return px, py
