"""Noritsu LS-600 "FULL...RAW" scan frames, as noritsu-tool reads them (github.com/rohanpandula/noritsu-tool, MIT, "noritsu-tool contributors"; the licence is in assets/noritsu/LICENSE).

The layout, as recovered by noritsu-tool from LS-600 dumps: a headerless raster of 3 x uint16 little-endian per pixel (blue, green, red slots), 12-bit scanner data (0..4095) in the
low bits, linear (no gamma, no white balance), and no dimensions anywhere in the file: a full frame is 4042 x 6391 (a portrait raster: the CCD line is the width, the film's transport the
height) and other sizes are recovered from the byte count alone. EFAS opens such a file as a linear 16-bit scan in landscape: `load_rgb16`. The scan is encoded "linear" (see
`logic.source_encoding`), so the conversion reads its density from the light as it is."""
import os

import numpy as np

WIDTH = 4042
HEIGHT = 6391
KNOWN_DIMS = [(4042, 6391)]       # (width, height) pairs confirmed against real dumps; width is the CCD-line axis (fixed by the hardware), height the film-transport axis
_BYTES_PER_PIXEL = 6              # 3 channels x uint16
_MIN_DIM = 2000                   # bounds for the blind factorization: both axes must look like a film scanner raster, and a 35 mm frame never gets longer than about 4.5:1
_MAX_DIM = 16000
_MAX_ASPECT = 4.5


def detect_dims(size: int) -> tuple[int, int] | None:
    """The (width, height) of a headerless dump from its byte count alone. Three tiers, strictest first; a tier answers only when exactly one candidate survives it:
    an exact match against KNOWN_DIMS; one axis that matches a known width or height (kept in its role) with a byte count that divides cleanly; a blind factorization within
    scanner-plausible bounds, oriented portrait (width < height) because that is how the transport writes every frame seen. None when the size is ambiguous or not a raster."""
    if size <= 0 or size % _BYTES_PER_PIXEL:
        return None
    px = size // _BYTES_PER_PIXEL
    for w, h in KNOWN_DIMS:
        if w * h == px:
            return (w, h)
    cands = set()
    for w, h in KNOWN_DIMS:
        if px % w == 0 and 1000 <= px // w <= 65535:
            cands.add((w, px // w))
        if px % h == 0 and 1000 <= px // h <= 65535:
            cands.add((px // h, h))
    if len(cands) == 1:
        return cands.pop()
    pairs = set()
    for a in range(_MIN_DIM, int(px ** 0.5) + 1):
        if px % a:
            continue
        b = px // a
        if b > _MAX_DIM or b / a > _MAX_ASPECT:
            continue
        pairs.add((a, b))
    return pairs.pop() if len(pairs) == 1 else None


def is_ls600_raw(path: str) -> bool:
    """Whether `path` looks like a headerless LS-600 dump: a .raw file whose size is a raster of 3 x uint16 pixels in a scanner's proportions."""
    if os.path.splitext(str(path))[1].lower() != ".raw":
        return False
    try:
        return detect_dims(os.path.getsize(str(path))) is not None
    except OSError:
        return False


def load_ls600_raw(path: str, width: int | None = None, height: int | None = None, maxv: float | None = None) -> np.ndarray:
    """A dump as float32 (H, W, 3) BGR in 0..1, linear, as the scanner wrote it (portrait). The size comes from `detect_dims` and the container's depth is sensed from the data
    (12-bit unless any sample is over 4095); pass width, height or maxv to override."""
    if width is None or height is None:
        dims = detect_dims(os.path.getsize(str(path)))
        if dims is None:
            raise ValueError(f"cannot infer the dimensions of {path} from its size")
        width, height = dims
    data = np.fromfile(path, dtype="<u2")
    need = width * height * 3
    if data.size < need:
        raise ValueError(f"{path}: expected {need} uint16 samples for {width}x{height}, found {data.size}")
    arr = data[:need].reshape(height, width, 3).astype(np.float32)
    if maxv is None:
        maxv = 4095.0 if arr.max() <= 4095 else 65535.0
    return np.clip(arr / maxv, 0, 1).astype(np.float32)


def load_rgb16(path: str) -> np.ndarray:
    """What EFAS opens a dump as: an HxWx3 uint16 RGB array of the linear light across the full 16-bit range, turned to landscape (the frame the film holder presents)."""
    bgr = load_ls600_raw(path)
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    if rgb.shape[0] > rgb.shape[1]:
        rgb = np.ascontiguousarray(np.rot90(rgb, 3))      # noritsu-tool's own turn (a clockwise quarter turn), which its machine-geometry crop assumes
    return np.clip(np.rint(rgb * 65535.0), 0, 65535).astype(np.uint16)


# --- LS-600 machine geometry transform (noritsu-tool: verified against real machine TIFFs) ---
# The LS-600 crops the 6391 x 4042 portrait raw to a sub-rect, then resamples it to 6048 x 4011. Derived from the TrzCorFile UsImRct and the thumbnail (about 1/16 of the full frame).
CROP_Y0, CROP_X0, CROP_H, CROP_W = 16, 168, 4008, 6048
TIF_H, TIF_W = 4011, 6048


def align_to_machine(landscape: np.ndarray) -> np.ndarray:
    """Crop and resize a landscape LS-600 frame (as `load_rgb16` returns it, any depth) to the geometry of the machine's own TIFF output, for fitting a profile against one."""
    import cv2

    cropped = landscape[CROP_Y0:CROP_Y0 + CROP_H, CROP_X0:CROP_X0 + CROP_W, :]
    return cv2.resize(np.ascontiguousarray(cropped), (TIF_W, TIF_H), interpolation=cv2.INTER_AREA)
