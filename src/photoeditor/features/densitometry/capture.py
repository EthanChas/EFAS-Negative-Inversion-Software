"""Capture settings read from a file, for the calibration records (camera, lens, exposure time, ISO, aperture), and the fast linear reading the
linearity test uses. The settings are best effort: a value the file does not give is None, never a guess."""

import numpy as np

from ..metadata.source_exif import read_exif_from_file
from .processor import decode_linear_raw


def _ratio(value):
    try:
        num, den = value
        return float(num) / float(den) if den else None
    except (TypeError, ValueError):
        return None


def capture_info(path: str) -> dict:
    """Camera, lens, exposure time (seconds), ISO and f-number of a file, with None for anything it does not state."""
    out = {"camera": "", "lens": "", "exposure_time": None, "iso": None, "aperture": None}
    exif = read_exif_from_file(path)
    if not exif:
        return out
    try:
        import piexif

        zeroth, ex = exif.get("0th", {}), exif.get("Exif", {})
        make = zeroth.get(piexif.ImageIFD.Make, b"")
        model = zeroth.get(piexif.ImageIFD.Model, b"")
        names = [p.decode("utf-8", "ignore").strip("\x00 ") for p in (make, model) if isinstance(p, bytes) and p.strip(b"\x00 ")]
        out["camera"] = names[-1] if len(names) == 2 and names[-1].lower().startswith(names[0].lower()) else " ".join(names)
        lens = ex.get(piexif.ExifIFD.LensModel, b"")
        out["lens"] = lens.decode("utf-8", "ignore").strip("\x00 ") if isinstance(lens, bytes) else ""
        out["exposure_time"] = _ratio(ex.get(piexif.ExifIFD.ExposureTime))
        iso = ex.get(piexif.ExifIFD.ISOSpeedRatings)
        out["iso"] = int(iso) if isinstance(iso, int) else None
        out["aperture"] = _ratio(ex.get(piexif.ExifIFD.FNumber))
    except Exception:
        pass
    return out


def region_reading(path: str, fraction: float = 0.10) -> dict:
    """Median linear R, G, B of the central `fraction` of a RAW frame (read at half size for speed), and the share of that area that is clipped.
    The linearity test needs a static, evenly lit area, which the centre of a backlit frame normally is."""
    scan = decode_linear_raw(path, half_size=True)
    h, w = scan.rgb.shape[:2]
    dy, dx = int(h * (1 - fraction) / 2), int(w * (1 - fraction) / 2)
    patch = scan.rgb[dy:h - dy, dx:w - dx].reshape(-1, 3)
    return {"median": tuple(float(v) for v in np.median(patch, axis=0)), "clipped": float((patch >= 0.999).any(axis=1).mean()), "info": scan.info}
