"""AI dust detection - runs the FilmDefectNet model (a small U-Net, exported to ONNX) over a film scan and turns its per-pixel defect
probability into a mask for the repair step. No Qt imports.

The model finds dust, hairs/fibres and scratches (bright and dark) and only detects; the same repair that fixes everything else
fills what it marks, so grain and detail elsewhere stay untouched. It was trained on positive-looking sRGB pictures, so a negative is
shown to it as an inverted positive (positive_view); the mask it gives is in the scan's own frame, where the repair runs.

The model sees the picture at native resolution (dust specks are a few pixels there), tile by tile so memory stays flat: about 1.4 s per
megapixel on a CPU. The probability map is cached on disk, so a photo is analysed once. Model: assets/models/defectnet.onnx
(FilmDefectNet, run2). Its README's advice is followed: threshold 0.3, then grow the mask a pixel or two."""

import hashlib
import os
import threading
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from ..datadir import app_data_dir
from ..lut.logic import apply_channel_lut
from ..negative.logic import compute_invert_lut

MODEL_FILE = Path(__file__).resolve().parents[2] / "assets" / "models" / "defectnet.onnx"
TILE = 1024
OVERLAP = 64
DEFAULT_THRESHOLD = 0.3
DEFAULT_GROW = 1
THRESHOLD_RANGE = (0.05, 0.95)
GROW_RANGE = (0, 4)
_CACHE_KEEP = 400  # analyses kept on disk; the oldest go first

_session = None
_session_lock = threading.Lock()


def available() -> bool:
    """True when the model file is there and onnxruntime can be imported."""
    if not MODEL_FILE.is_file():
        return False
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def _get_session():
    global _session
    with _session_lock:
        if _session is None:
            import onnxruntime as ort

            _session = ort.InferenceSession(str(MODEL_FILE), providers=["CPUExecutionProvider"])
        return _session


def positive_view(raw: np.ndarray, inverted: bool, mono: bool = False) -> np.ndarray:
    """The scan as a positive-looking picture for the model: a negative inverted with its own levels (the same inversion the editor does), a
    positive left as it is. mono makes a black-and-white scan grey first, like the editor does before inverting."""
    pixels = raw
    if mono:
        gray = (0.299 * pixels[..., 0] + 0.587 * pixels[..., 1] + 0.114 * pixels[..., 2]).astype(np.uint8)
        pixels = np.repeat(gray[..., None], 3, axis=2)
    if not inverted:
        return np.ascontiguousarray(pixels)
    return apply_channel_lut(pixels, compute_invert_lut(pixels, None))


def predict(rgb: np.ndarray, progress: Optional[Callable[[int, int], None]] = None, cancelled: Optional[Callable[[], bool]] = None) -> Optional[np.ndarray]:
    """The defect probability of every pixel, uint8 0-255, same size as rgb (uint8 HxWx3). None if cancelled."""
    session = _get_session()
    h, w = rgb.shape[:2]
    prob = np.zeros((h, w), dtype=np.uint8)
    tiles = [(y, x) for y in range(0, h, TILE) for x in range(0, w, TILE)]
    for n, (y, x) in enumerate(tiles):
        if cancelled is not None and cancelled():
            return None
        y1, x1 = min(y + TILE, h), min(x + TILE, w)
        ey0, ex0, ey1, ex1 = max(0, y - OVERLAP), max(0, x - OVERLAP), min(h, y1 + OVERLAP), min(w, x1 + OVERLAP)
        crop = rgb[ey0:ey1, ex0:ex1]
        ch, cw = crop.shape[:2]
        pad_h, pad_w = (8 - ch % 8) % 8, (8 - cw % 8) % 8  # the network needs sides that are multiples of 8
        tensor = np.ascontiguousarray(crop.transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
        if pad_h or pad_w:
            tensor = np.pad(tensor, ((0, 0), (0, 0), (0, pad_h), (0, pad_w)), mode="reflect")
        out = session.run(None, {"image": tensor})[0][0, 0, :ch, :cw]
        piece = out[y - ey0: y1 - ey0, x - ex0: x1 - ex0]
        prob[y:y1, x:x1] = np.clip(piece * 255.0 + 0.5, 0, 255).astype(np.uint8)
        if progress is not None:
            progress(n + 1, len(tiles))
    return prob


def mask_from_prob(prob: np.ndarray, threshold: float, grow: int) -> np.ndarray:
    """uint8 mask (1 = defect) of the pixels at or above threshold, grown by grow pixels so the repair covers each defect's edge."""
    mask = (prob >= int(round(threshold * 255.0))).astype(np.uint8)
    if grow > 0 and mask.any():
        size = 2 * int(grow) + 1
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    return mask


def mask_for_source(prob: np.ndarray, shape: tuple[int, int], threshold: float, grow: int) -> np.ndarray:
    """The mask at a source's own size (h, w). A source smaller than the analysed picture (the editor's preview) gets the mask shrunk so
    that any flagged pixel under a new pixel flags it - a small speck must not vanish in the shrinking."""
    mask = mask_from_prob(prob, threshold, grow)
    if mask.shape == tuple(shape):
        return mask
    h, w = shape
    return (cv2.resize(mask.astype(np.float32), (w, h), interpolation=cv2.INTER_AREA) > 0).astype(np.uint8)


# ---- the on-disk cache of analyses ----
def _model_signature() -> str:
    try:
        st = MODEL_FILE.stat()
        return f"{st.st_size}-{int(st.st_mtime)}"
    except OSError:
        return "none"


def _cache_dir() -> str:
    return os.path.join(app_data_dir(), "ai_dust_cache")


def cache_file(path: str, inverted: bool, mono: bool) -> str:
    """Where the analysis of one photo (as it is shown to the model) is kept; changes when the file or the model changes."""
    try:
        st = os.stat(path)
        sig = f"{st.st_size}-{st.st_mtime_ns}"
    except OSError:
        sig = "gone"
    key = f"{os.path.normcase(os.path.abspath(path))}|{sig}|{int(inverted)}|{int(mono)}|{_model_signature()}"
    return os.path.join(_cache_dir(), hashlib.sha1(key.encode("utf-8")).hexdigest() + ".npz")


def load_cached(path: str, inverted: bool, mono: bool) -> Optional[np.ndarray]:
    try:
        with np.load(cache_file(path, inverted, mono)) as data:
            return data["prob"]
    except (OSError, ValueError, KeyError):
        return None


def save_cached(path: str, inverted: bool, mono: bool, prob: np.ndarray) -> None:
    try:
        os.makedirs(_cache_dir(), exist_ok=True)
        target = cache_file(path, inverted, mono)
        tmp = target + ".part"
        with open(tmp, "wb") as f:
            np.savez_compressed(f, prob=prob)
        os.replace(tmp, target)
        files = sorted((os.path.join(_cache_dir(), n) for n in os.listdir(_cache_dir()) if n.endswith(".npz")), key=os.path.getmtime)
        for old in files[:-_CACHE_KEEP]:
            os.remove(old)
    except OSError:
        pass  # a cache that cannot be written only costs a re-analysis


def probability(path: str, raw: np.ndarray, inverted: bool, mono: bool,
                progress: Optional[Callable[[int, int], None]] = None, cancelled: Optional[Callable[[], bool]] = None) -> Optional[np.ndarray]:
    """The analysis of a photo: from the cache when it has been done, else computed (and cached). raw is the full-resolution scan."""
    cached = load_cached(path, inverted, mono)
    if cached is not None and cached.shape == raw.shape[:2]:
        return cached
    prob = predict(positive_view(raw, inverted, mono), progress, cancelled)
    if prob is not None:
        save_cached(path, inverted, mono, prob)
    return prob
