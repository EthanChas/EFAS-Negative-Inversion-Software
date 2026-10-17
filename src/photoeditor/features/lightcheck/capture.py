"""Reading a RAW capture for the light check: the sensor's own values, one plane per colour, and the camera settings it was shot with. No Qt.

The sensor values are read before any conversion (black level taken off, no demosaic, no white balance, no camera profile), so the numbers describe the light that fell on
the sensor and nothing a converter did to it. Adapted from lightdrift by David Esquivel (MIT licence), https://github.com/davidesqalv/lightdrift.
"""

import os
from datetime import datetime

import numpy as np

CHANNELS = ("R", "G", "B")
RAW_EXTS = {".arw", ".cr2", ".cr3", ".nef", ".nrw", ".raf", ".orf", ".rw2", ".dng", ".pef", ".srw", ".3fr", ".iiq", ".erf", ".rwl", ".x3f", ".raw"}
_PROGRAMS = {1: "Manual", 2: "Program AE", 3: "Aperture-priority AE", 4: "Shutter-priority AE", 5: "Creative", 6: "Action", 7: "Portrait", 8: "Landscape"}


class CaptureError(Exception):
    """A file could not be read as a standard RGB Bayer RAW capture; the text says why."""


class Cancelled(Exception):
    """The person stopped the check."""


def is_raw(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in RAW_EXTS and not os.path.basename(path).startswith(".")


def raw_files_in(folder: str) -> list[str]:
    """The RAW files directly inside a folder, one per shot: when a shot is there as the camera's RAW and as a DNG copy, the camera's RAW is used."""
    by_shot: dict[str, str] = {}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    for name in names:
        stem, ext = os.path.splitext(name)
        if ext.lower() not in RAW_EXTS or name.startswith("."):
            continue
        if stem not in by_shot or by_shot[stem].lower().endswith(".dng"):
            by_shot[stem] = name
    return sorted(os.path.join(folder, n) for n in by_shot.values())


def expand(paths: list[str]) -> list[str]:
    """Files and folders as a list of RAW files (a folder gives the RAW files in it), each once."""
    out: list[str] = []
    for p in paths:
        out += raw_files_in(p) if os.path.isdir(p) else ([p] if is_raw(p) else [])
    return list(dict.fromkeys(out))


def load_planes(path: str):
    """({'R','G','B': the plane as a fraction of the sensor's full scale}, {channel: share of its pixels at the sensor's maximum})."""
    import rawpy

    try:
        with rawpy.imread(path) as raw:
            data = raw.raw_image_visible.astype(np.float64)
            colors = raw.raw_colors_visible.copy()
            desc = raw.color_desc.decode("ascii")
            black = np.asarray(raw.black_level_per_channel, dtype=np.float64)
            white = float(raw.white_level)
    except Exception as exc:
        raise CaptureError(f"{os.path.basename(path)} could not be read as a RAW file ({exc}).") from exc
    data -= black[colors]
    pieces: dict[str, list] = {}
    clipped: dict[str, list] = {}
    for dy in (0, 1):
        for dx in (0, 1):
            ci = int(colors[dy, dx])
            name = desc[ci]
            plane = data[dy::2, dx::2]
            span = white - black[ci]
            pieces.setdefault(name, []).append(plane / span)
            clipped.setdefault(name, []).append(float(np.mean(plane >= 0.98 * span)))
    if any(c not in pieces for c in CHANNELS):
        raise CaptureError(f"{os.path.basename(path)}: the sensor layout '{desc}' is not a standard red, green, blue Bayer pattern.")
    h = min(p.shape[0] for ps in pieces.values() for p in ps)
    w = min(p.shape[1] for ps in pieces.values() for p in ps)
    planes = {c: np.mean([p[:h, :w] for p in pieces[c]], axis=0) for c in CHANNELS}
    return planes, {c: max(clipped[c]) for c in CHANNELS}


def _ratio(value):
    try:
        num, den = value
        return float(num) / float(den) if den else None
    except (TypeError, ValueError):
        return None


def _shutter_text(value) -> str:
    seconds = _ratio(value)
    if not seconds or seconds <= 0:
        return "?"
    if seconds < 1:
        return f"1/{round(1 / seconds)}"
    return f"{seconds:g}"


def _load_exif(path: str):
    import piexif

    try:
        return piexif.load(path)
    except Exception:
        pass
    try:   # a RAW format piexif cannot read (CR3, RAF, RW2...): the JPEG preview inside it carries the camera's settings
        import rawpy

        with rawpy.imread(path) as raw:
            thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            return piexif.load(bytes(thumb.data))
    except Exception:
        pass
    return None


def read_exif(path: str) -> dict:
    """{'Shutter', 'Aperture', 'ISO', 'Program', 'time'} of a capture; text ('?' for what the file does not say) and a datetime or None."""
    info = {"Shutter": "?", "Aperture": "?", "ISO": "?", "Program": "?", "time": None}
    exif = _load_exif(path)
    if not exif:
        return info
    try:
        import piexif

        ex = exif.get("Exif", {})
        info["Shutter"] = _shutter_text(ex.get(piexif.ExifIFD.ExposureTime))
        f_number = _ratio(ex.get(piexif.ExifIFD.FNumber))
        info["Aperture"] = f"{f_number:g}" if f_number else "?"
        iso = ex.get(piexif.ExifIFD.ISOSpeedRatings)
        if isinstance(iso, (tuple, list)) and iso:
            iso = iso[0]
        info["ISO"] = str(int(iso)) if isinstance(iso, int) and iso > 0 else "?"
        info["Program"] = _PROGRAMS.get(ex.get(piexif.ExifIFD.ExposureProgram), "?")
        stamp = ex.get(piexif.ExifIFD.DateTimeOriginal) or exif.get("0th", {}).get(piexif.ImageIFD.DateTime) or b""
        text = stamp.decode("ascii", "ignore").strip("\x00 ") if isinstance(stamp, bytes) else str(stamp)
        when = datetime.strptime(text[:19], "%Y:%m:%d %H:%M:%S")
        sub = ex.get(piexif.ExifIFD.SubSecTimeOriginal, b"")
        sub = sub.decode("ascii", "ignore").strip("\x00 ") if isinstance(sub, bytes) else str(sub)
        if sub.isdigit():
            when = when.replace(microsecond=int(float("0." + sub) * 1e6))
        info["time"] = when
    except Exception:
        pass
    return info
