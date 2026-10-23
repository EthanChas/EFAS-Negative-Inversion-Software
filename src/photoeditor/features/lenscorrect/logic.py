"""Quick lens corrections from the Lensfun database (through lensfunpy) - numpy + OpenCV, no Qt.

The lens the photo was taken with is found in the database from its EXIF (camera, lens name, focal length, aperture); the profile then gives three things:

- the lens's **lateral chromatic aberration** (colour fringes: red and blue are imaged a little larger or smaller than green), corrected by moving each colour back,
- its **vignetting** (dark corners), as a gain map that is applied the way the flat field's is (in linear light); a flat field made through the same lens already contains it, so the two are
  never both applied,
- its **distortion**, fitted to the one number the Distortion slider has (a radial k1), so the slider can start from the profile.

Everything is worked out on a small grid (the corrections are smooth) and brought up to the picture's size a strip at a time, so a 30-megapixel scan needs no huge coordinate maps. The database
is Lensfun's (lensfun.github.io; the data CC BY-SA, the library LGPL). A profile is for ordinary shooting distances: close up, as on a copy stand, it is an approximation, which is why this is
off by default and the distance can be set. lensfunpy is optional: without it everything here reports that it is not available and the photo is left alone.
"""

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

GRID = 256               # the long side of the grid the corrections are worked out on
STRIP_ROWS = 256         # the rows of the picture corrected at a time
DEFAULT_DISTANCE = 0.4   # metres: about right for a copy stand with a 100 mm macro lens at 1:1 on a full frame camera
NEGLIGIBLE_PX = 0.02     # a colour that would move less than this (in picture pixels, at most) is left alone

_REASONS = {
    "off": "",
    "unavailable": "The lens database is not installed (the optional lensfunpy package).",
    "no_exif": "The photo has no camera, lens, focal length and aperture in its EXIF.",
    "no_camera": "That camera is not in the lens database.",
    "no_lens": "That lens is not in the lens database.",
}


def available() -> bool:
    try:
        import lensfunpy  # noqa: F401
    except Exception:
        return False
    return True


@lru_cache(maxsize=1)
def _database():
    import lensfunpy

    return lensfunpy.Database()


@dataclass(frozen=True)
class Profile:
    """A camera and lens found in the database."""

    camera: object
    lens: object

    @property
    def title(self) -> str:
        return f"{self.lens.model} on {self.camera.model}"


@lru_cache(maxsize=64)
def find(camera_make: str, camera_model: str, lens_make: str, lens_model: str) -> tuple[Profile | None, str]:
    """(the profile, "") or (None, the reason: a key of _REASONS) for the camera and lens an EXIF names."""
    if not available():
        return None, "unavailable"
    if not (camera_model.strip() and lens_model.strip()):
        return None, "no_exif"
    db = _database()
    try:
        cameras = db.find_cameras(camera_make.strip() or None, camera_model.strip()) or db.find_cameras(None, camera_model.strip())
    except Exception:
        cameras = []
    if not cameras:
        return None, "no_camera"
    camera = cameras[0]
    for maker in (lens_make.strip() or None, camera_make.strip() or None, None):
        try:
            lenses = db.find_lenses(camera, maker, lens_model.strip())
        except Exception:
            lenses = []
        if lenses:
            return Profile(camera, lenses[0]), ""
    return None, "no_lens"


def reason_text(key: str) -> str:
    return _REASONS.get(key, key)


@dataclass(frozen=True)
class Shot:
    """What the EXIF says about how the photo was taken."""

    camera_make: str = ""
    camera_model: str = ""
    lens_make: str = ""
    lens_model: str = ""
    focal_mm: float = 0.0
    aperture: float = 0.0

    def complete(self) -> bool:
        return bool(self.camera_model.strip() and self.lens_model.strip() and self.focal_mm > 0 and self.aperture > 0)

    def as_tuple(self) -> tuple:
        return (self.camera_make, self.camera_model, self.lens_make, self.lens_model, round(self.focal_mm, 2), round(self.aperture, 2))


def shot_from_exif(source_exif: dict | None) -> Shot:
    """The Shot of a piexif-format EXIF dict (features/metadata/source_exif)."""
    from ..metadata.exif_read import extract_scan_from_exif

    scan = extract_scan_from_exif(source_exif)
    return Shot(scan.camera_make, scan.camera_model, scan.lens_make, scan.lens_model, float(scan.focal_length_mm or 0.0), float(scan.aperture or 0.0))


def profile_of(shot: Shot) -> tuple[Profile | None, str]:
    if not shot.complete():
        return None, "no_exif"
    return find(shot.camera_make, shot.camera_model, shot.lens_make, shot.lens_model)


def clean_corr(corr) -> dict:
    """What is kept of a photo's lens corrections: only what is switched on, and the distance only when it is not the default. {} for none."""
    if not isinstance(corr, dict):
        return {}
    out: dict = {}
    for key in ("tca", "vignetting"):
        if corr.get(key):
            out[key] = True
    try:
        distance = float(corr.get("distance") or DEFAULT_DISTANCE)
    except (TypeError, ValueError):
        distance = DEFAULT_DISTANCE
    distance = min(max(distance, 0.05), 1000.0)
    if out and abs(distance - DEFAULT_DISTANCE) > 1e-9:
        out["distance"] = distance
    return out


# ---------------------------------------------------------------- what the renderer is handed
def spec(corr: dict | None, shot_tuple) -> tuple:
    """The frozen description of the corrections to apply to a photo, or () for none: (tca, vignetting, distance, camera make, camera model, lens make, lens model, focal, aperture)."""
    corr = corr or {}
    tca, vig = bool(corr.get("tca")), bool(corr.get("vignetting"))
    if not (tca or vig) or not shot_tuple or len(shot_tuple) != 6 or not (shot_tuple[1] and shot_tuple[3] and shot_tuple[4] and shot_tuple[5]):
        return ()
    return (tca, vig, float(corr.get("distance") or DEFAULT_DISTANCE)) + tuple(shot_tuple)


def _modifier(profile: Profile, shot_tuple: tuple, distance: float, w: int, h: int):
    import lensfunpy

    mod = lensfunpy.Modifier(profile.lens, profile.camera.crop_factor, w, h)
    mod.initialize(float(shot_tuple[4]), float(shot_tuple[5]), float(distance), pixel_format=np.float32)
    return mod


def _grid(w: int, h: int) -> tuple[int, int]:
    k = min(1.0, GRID / max(w, h))
    return max(8, round(w * k)), max(8, round(h * k))


def vignetting_gain(profile: Profile, shot_tuple: tuple, distance: float, w: int, h: int) -> np.ndarray | None:
    """The gain (in linear light, per colour, on a small grid) that brightens the corners back; None when the profile has no vignetting data for this focal length and aperture."""
    gw, gh = _grid(w, h)
    ones = np.ones((gh, gw, 3), dtype=np.float32)
    if not _modifier(profile, shot_tuple, distance, gw, gh).apply_color_modification(ones):
        return None
    gain = np.clip(ones, 0.25, 4.0).astype(np.float32)
    return gain if float(np.abs(gain - 1.0).max()) > 1e-3 else None


def tca_fields(profile: Profile, shot_tuple: tuple, distance: float, w: int, h: int) -> list[np.ndarray | None]:
    """For each colour (R, G, B): how far, in the picture's own pixels, each point of the corrected picture is to be read from (dx, dy on a small grid), or None when it is negligible."""
    gw, gh = _grid(w, h)
    coords = _modifier(profile, shot_tuple, distance, gw, gh).apply_subpixel_distortion()
    if coords is None:
        return [None, None, None]
    xs, ys = np.meshgrid(np.arange(gw, dtype=np.float32), np.arange(gh, dtype=np.float32))
    fields: list[np.ndarray | None] = []
    for c in range(3):
        d = np.stack([coords[:, :, c, 0] - xs, coords[:, :, c, 1] - ys], axis=-1).astype(np.float32)
        d[..., 0] *= w / gw
        d[..., 1] *= h / gh
        fields.append(d if float(np.abs(d).max()) > NEGLIGIBLE_PX else None)
    return fields


def apply_tca(pixels: np.ndarray, fields: list[np.ndarray | None]) -> np.ndarray:
    """Move each colour of `pixels` (HxWx3, uint8, uint16 or float) by its field, a strip of rows at a time. The picture keeps its size and depth; a colour with no field is untouched."""
    import cv2

    if all(f is None for f in fields):
        return pixels
    h, w = pixels.shape[:2]
    out = np.ascontiguousarray(pixels).copy()
    gh, gw = next(f for f in fields if f is not None).shape[:2]
    xs = np.arange(w, dtype=np.float32)
    for y0 in range(0, h, STRIP_ROWS):
        y1 = min(h, y0 + STRIP_ROWS)
        ys = np.arange(y0, y1, dtype=np.float32)
        gx = np.broadcast_to(((xs + 0.5) * (gw / w) - 0.5)[None, :], (y1 - y0, w)).astype(np.float32)
        gy = np.broadcast_to((((ys + 0.5) * (gh / h) - 0.5))[:, None], (y1 - y0, w)).astype(np.float32)
        px = np.broadcast_to(xs[None, :], (y1 - y0, w))
        py = np.broadcast_to(ys[:, None], (y1 - y0, w))
        for c, field in enumerate(fields):
            if field is None:
                continue
            dx = cv2.remap(np.ascontiguousarray(field[..., 0]), gx, gy, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            dy = cv2.remap(np.ascontiguousarray(field[..., 1]), gx, gy, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            out[y0:y1, :, c] = cv2.remap(np.ascontiguousarray(pixels[:, :, c]), (px + dx).astype(np.float32), (py + dy).astype(np.float32),
                                         interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return out


def correct(pixels: np.ndarray, lens_spec: tuple, flat_field_active: bool = False) -> np.ndarray:
    """The corrections of `lens_spec` (see spec) applied to a picture: colour fringes first, then vignetting (left out when a flat field is on, which has the vignetting in it already)."""
    if not lens_spec:
        return pixels
    tca, vig, distance = lens_spec[0], lens_spec[1], lens_spec[2]
    shot = lens_spec[3:]
    profile, _why = find(shot[0], shot[1], shot[2], shot[3])
    if profile is None:
        return pixels
    h, w = pixels.shape[:2]
    out = pixels
    if tca:
        out = apply_tca(out, tca_fields(profile, shot, distance, w, h))
    if vig and not flat_field_active:
        gain = vignetting_gain(profile, shot, distance, w, h)
        if gain is not None:
            from ..flatfield.logic import apply_flatfield

            out = apply_flatfield(out, gain)
    return out


# ---------------------------------------------------------------- the Distortion slider
def distortion_k1(profile: Profile, shot_tuple: tuple, distance: float, w: int = 600, h: int = 400) -> float | None:
    """The slider's radial k1 (features/geometry: positive corrects barrel) that best matches the profile's distortion, fitted to how far the profile reads each point of the corrected picture from
    the middle. A profile is not purely radial-quadratic, so this is an approximation; None when the profile has no distortion model for this focal length."""
    from ..geometry.logic import DISTORTION_LIMIT, distortion_scale

    gw, gh = _grid(w, h)
    coords = _modifier(profile, shot_tuple, distance, gw, gh).apply_geometry_distortion()
    if coords is None:
        return None
    cx, cy = (gw - 1) * 0.5, (gh - 1) * 0.5
    ys, xs = np.mgrid[0:gh, 0:gw].astype(np.float64)
    r_dst = np.hypot(xs - cx, ys - cy).ravel()
    r_src = np.hypot(coords[..., 0] - cx, coords[..., 1] - cy).astype(np.float64).ravel()
    keep = r_dst > 1.0
    ratio, t = r_src[keep] / r_dst[keep], (r_dst[keep] / (0.5 * math.hypot(gw, gh))) ** 2
    design = np.stack([np.ones_like(t), t], axis=1)
    (a, ab), *_ = np.linalg.lstsq(design, ratio, rcond=None)
    if abs(a) < 1e-6:
        return None
    shape = ab / a                 # the share by which the edge reads farther (or nearer) than the middle, at the corner
    k1 = shape
    for _ in range(6):             # the slider's own scale-to-fill makes its effective term k1 * s^2
        s = distortion_scale(k1, w, h)
        k1 = shape / (s * s)
    if not math.isfinite(k1):
        return None
    return float(min(max(k1, -DISTORTION_LIMIT), DISTORTION_LIMIT))
