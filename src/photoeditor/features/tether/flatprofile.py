"""The tether window's flat-field profile: a picture of the bare light taken through the live view, kept between sessions, and turned into the gain map that evens out the preview. No Qt.

It is EFAS's own flat field (features/flatfield) made from the live picture instead of a scan: the same smoothing methods, the same gain map. Only the preview uses it; the shots the camera
saves are corrected by the flat field in the editor, as before.
"""

import os

import cv2
import numpy as np

from .. import datadir
from ..flatfield import logic as ff
from ..settings import logic as app_settings

FRAMES = 8              # live pictures of the light that are averaged (one is noisy)
FRAME_WIDTH = 640       # each is made this wide before it is kept: the gain map is smooth and small anyway
TOO_DARK = 20           # an average camera value below this is not the light
BLOWN_OUT = 250         # at or above this the light is clipped and its falloff cannot be seen


def path() -> str:
    return os.path.join(datadir.app_data_dir(), datadir.TETHER_FLATFIELD_FILE)


def method() -> str:
    """The flat-field method set in EFAS (Flat Field panel), so the preview is evened out the way the scans are."""
    chosen = app_settings.get("flatfield_method")
    return chosen if chosen in ff.METHODS else ff.METHOD_DEFAULT


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


def gain_of(reference: np.ndarray, chosen: str | None = None) -> np.ndarray:
    return ff.gain_from_map(reference, chosen or method())


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
