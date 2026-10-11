"""Cropping, or un-cropping, a whole roll at once, for photos that are not open in the editor.

Auto crop does for each photo what the editor's Auto Crop & Straighten button does for the open one: it finds the picture inside the scan's border and crops to
it, straightening it first if it is slightly tilted. The photo's other edits are kept. The result is saved like any edit (the database row and the sidecar).
"""

import os

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.geometry.autocrop import AUTO_STRAIGHTEN_MAX, AUTO_STRAIGHTEN_MIN, detect_frame
from ..features.geometry.logic import FINE_ROTATION_LIMIT
from ..features.open_image.processor import load_image_rgb, make_preview_rgb, to_uint8
from ..features.persistence import edit_store
from ..features.support import applog
from ..features.xmp import logic as xmp
from .export_worker import saved_or_default_state
from .render import EditParams, Renderer

DONE, SKIPPED_HAS_CROP, NO_BORDER, UNCHANGED = "done", "has a crop", "no clear border found", "unchanged"


def auto_crop_photo(path: str, conn, replace_existing: bool = False, straighten: bool = True) -> str:
    """Crop one photo to the picture inside its scan. Returns DONE, SKIPPED_HAS_CROP (it already has a crop and `replace_existing` is off) or NO_BORDER."""
    existing = edit_store.load_edit_state(conn, path)
    if existing is not None and existing["crop_rect"] and not replace_existing:
        return SKIPPED_HAS_CROP
    preview = to_uint8(make_preview_rgb(load_image_rgb(path)))
    state = existing if existing is not None else saved_or_default_state(path, conn, preview)
    if state.get("crop_rect") and not replace_existing:
        return SKIPPED_HAS_CROP
    state = {**state, "crop_rect": None}

    def framed(s: dict):
        return Renderer._geometry(preview, EditParams.from_dict(s))

    frame = framed(state)
    det = detect_frame(frame)
    if det is None:
        return NO_BORDER
    if straighten and AUTO_STRAIGHTEN_MIN <= abs(det.skew_deg) <= AUTO_STRAIGHTEN_MAX:
        state["fine_rotation"] = round(max(-FINE_ROTATION_LIMIT, min(FINE_ROTATION_LIMIT, float(state.get("fine_rotation", 0.0)) - det.skew_deg)), 2)
        frame = framed(state)
        again = detect_frame(frame)
        if again is not None:
            det = again
    state["crop_rect"] = tuple(int(v) for v in det.rect)
    edit_store.save_edit_state(conn, path, state)
    xmp.write_sidecar(path, state, frame.shape[:2])
    return DONE


def reset_crop_photo(path: str, conn) -> str:
    """Take the crop off one photo (its rotation, straightening and every other edit stay). Returns DONE or UNCHANGED."""
    state = edit_store.load_edit_state(conn, path)
    if state is None or not state["crop_rect"]:
        return UNCHANGED
    state = {**state, "crop_rect": None}
    edit_store.save_edit_state(conn, path, state)
    xmp.write_sidecar(path, state, (1, 1))
    return DONE


def count_cropped(conn, paths: list[str]) -> int:
    """How many of these photos have a crop saved."""
    n = 0
    for p in paths:
        state = edit_store.load_edit_state(conn, p)
        if state is not None and state["crop_rect"]:
            n += 1
    return n


def run(mode: str, paths: list[str], db_path: str, replace_existing: bool = False, progress=None, cancelled=None) -> dict:
    """`mode` is 'auto' or 'reset'. Returns {'done': [...], 'skipped': [(path, why)], 'failed': [(path, reason)], 'cancelled': bool}."""
    summary = {"done": [], "skipped": [], "failed": [], "cancelled": False}
    conn = edit_store.connect(db_path)
    try:
        for i, path in enumerate(paths):
            if cancelled is not None and cancelled():
                summary["cancelled"] = True
                break
            if progress is not None:
                progress(i, len(paths), os.path.basename(path))
            try:
                result = auto_crop_photo(path, conn, replace_existing) if mode == "auto" else reset_crop_photo(path, conn)
            except Exception as exc:
                summary["failed"].append((path, f"{type(exc).__name__}: {exc}"))
                applog.logger().warning("Bulk crop failed for %s: %s", os.path.basename(path), exc)
                continue
            (summary["done"] if result == DONE else summary["skipped"]).append(path if result == DONE else (path, result))
    finally:
        conn.close()
    return summary


class BulkCropWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_all = pyqtSignal(object)

    def __init__(self, mode: str, paths: list[str], db_path: str, replace_existing: bool = False):
        super().__init__()
        self._args = (mode, list(paths), db_path, replace_existing)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        mode, paths, db_path, replace = self._args
        self.finished_all.emit(run(mode, paths, db_path, replace, self.progress.emit, lambda: self._cancel))
