"""The tether window's flat-field profile: a picture of the bare light taken through the live view, kept between sessions, and turned into the gain map that evens out the preview. No Qt.

It is the same kind of gain map as EFAS's flat field (features/flatfield), made from the live picture instead of a scan. The live picture is an 8-bit JPEG, so a smooth falloff arrives as steps
of one level, and a gain made by blurring them keeps the steps (they show as rings, a different set in each colour). A smooth surface fitted to the light has no steps to keep. Only the preview
uses it; the shots the camera saves are corrected by the flat field in the editor, as before.
"""

import os

import cv2
import numpy as np

from .. import datadir
from ..flatfield import logic as ff

FRAMES = 8              # live pictures of the light that are averaged (one is noisy)
FRAME_WIDTH = 640       # each is made this wide before it is kept: the gain map is smooth and small anyway
TOO_DARK = 20           # an average camera value below this is not the light
BLOWN_OUT = 250         # at or above this the light is clipped and its falloff cannot be seen
DEGREE = 5              # the surface fitted to the light is a polynomial of this degree in x and y: smooth, so it can hold a vignette or a lamp's hot spot but not a step or a speck
MAX_UNEVEN = 0.08       # what is left of the light after the fit, as a share of it (its spread): more than this is not bare light (film or a holder in the way)


def path() -> str:
    return os.path.join(datadir.app_data_dir(), datadir.TETHER_FLATFIELD_FILE)


def shrink(rgb: np.ndarray) -> np.ndarray:
    h, w = rgb.shape[:2]
    return rgb if w <= FRAME_WIDTH else cv2.resize(rgb, (FRAME_WIDTH, max(1, round(h * FRAME_WIDTH / w))), interpolation=cv2.INTER_AREA)


def problem_with(frames: list[np.ndarray]) -> str:
    """Why these pictures cannot be the bare light ("" when they can)."""
    level = float(np.mean([f.mean() for f in frames]))
    if level < TOO_DARK:
        return "The picture is too dark to be the light. Show the camera the bare light (no film), and open the exposure until it is bright but not white."
    if level >= BLOWN_OUT:
        return "The light is blown out, so its falloff cannot be measured. Shorten the exposure or close the aperture until it is bright but not white."
    return ""


def reference_from_frames(frames: list[np.ndarray]) -> np.ndarray:
    """The small linear reference map of the average of these (small, uint8, same size) pictures of the light."""
    mean = np.mean(np.stack(frames).astype(np.float32), axis=0)
    return ff.reference_map(np.clip(np.rint(mean), 0, 255).astype(np.uint8))


def _terms(h: int, w: int) -> np.ndarray:
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    x, y = xs / max(1, w - 1) * 2 - 1, ys / max(1, h - 1) * 2 - 1
    return np.stack([x ** i * y ** j for i in range(DEGREE + 1) for j in range(DEGREE + 1 - i)], axis=-1)


def fit(reference: np.ndarray) -> tuple[np.ndarray, float]:
    """(the gain map, how uneven what is left is): a smooth surface fitted to each colour of the light, and the gain that makes it flat. The second number is the spread of the light round that
    surface after dust is filtered out; a large one means the picture is not bare light."""
    ref = np.ascontiguousarray(reference, dtype=np.float32)
    h, w = ref.shape[:2]
    terms = _terms(h, w)
    design = terms.reshape(-1, terms.shape[-1])
    filtered = cv2.medianBlur(ref, 5) if min(h, w) >= 8 else ref
    surface = np.empty_like(ref)
    spread = 0.0
    for c in range(3):
        values = filtered[..., c].reshape(-1)
        coef, *_ = np.linalg.lstsq(design[::3], values[::3], rcond=None)
        fitted = np.maximum(design @ coef, float(values.max()) * 0.02 + 1e-6)
        surface[..., c] = fitted.reshape(h, w)
        spread = max(spread, float(np.std(values / fitted - 1.0)))
    gain = surface.reshape(-1, 3).mean(axis=0)[None, None, :] / surface
    return np.clip(gain, 0.25, 4.0).astype(np.float32), spread


def gain_of(reference: np.ndarray) -> np.ndarray:
    return fit(reference)[0]


def save(reference: np.ndarray) -> None:
    target = path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temp = target[:-4] + ".tmp.npz"
    np.savez(temp, reference=np.ascontiguousarray(reference, dtype=np.float32))
    os.replace(temp, target)


def load() -> np.ndarray | None:
    """The kept reference map, or None when there is none (or the file is not one)."""
    try:
        with np.load(path()) as data:
            ref = np.asarray(data["reference"], dtype=np.float32)
    except (OSError, ValueError, KeyError):
        return None
    return ref if ref.ndim == 3 and ref.shape[2] == 3 and min(ref.shape[:2]) >= 2 else None


def forget() -> None:
    try:
        os.remove(path())
    except OSError:
        pass
