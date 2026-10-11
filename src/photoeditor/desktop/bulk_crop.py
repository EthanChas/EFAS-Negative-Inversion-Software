"""Cropping, or un-cropping, a whole roll at once, for photos that are not open in the editor.

Auto crop does for each photo what the editor's Auto Crop & Straighten button does for the open one: it finds the picture inside the scan's border and crops to
it, straightening it first if it is slightly tilted. The photo's other edits are kept. The result is saved like any edit (the database row and the sidecar).
"""

import dataclasses
import os

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from ..features.browse.processor import forget_edited_thumbnail, save_edited_thumbnail
from ..features.geometry.autocrop import AUTO_STRAIGHTEN_MAX, AUTO_STRAIGHTEN_MIN, detect_frame
from ..features.geometry.logic import FINE_ROTATION_LIMIT
from ..features.open_image.processor import load_image_rgb, make_preview_rgb, to_uint8
from ..features.persistence import edit_store, roll_undo
from ..features.support import applog
from ..features.xmp import logic as xmp
from .export_worker import _edits_for, saved_or_default_state
from .paths import thumbnail_cache_dir
from .render import EditParams, Renderer

DONE, SKIPPED_HAS_CROP, NO_BORDER, UNCHANGED = "done", "has a crop", "no clear border found", "unchanged"


def _positive(base, params, flatfield, path: str):
    """The picture the editor shows before the crop (inverted, toned), which is what the border is looked for in: in a raw negative the border and the picture can look alike."""
    image, pre_crop, _stats, _overlay = Renderer().render(base, dataclasses.replace(params, crop_rect=None), ("bulk", path), base.shape[1], None, want_stats=False,
                                                          overlay=False, flatfield=flatfield)
    return pre_crop if pre_crop is not None else image


def auto_crop_photo(path: str, conn, replace_existing: bool = False, straighten: bool = True, ops: list | None = None) -> str:
    """Crop one photo to the picture inside its scan, as the editor's Auto Crop & Straighten does. Returns DONE, SKIPPED_HAS_CROP (it already has a crop and
    `replace_existing` is off) or NO_BORDER."""
    existing = edit_store.load_edit_state(conn, path)
    if existing is not None and existing["crop_rect"] and not replace_existing:
        return SKIPPED_HAS_CROP
    preview = make_preview_rgb(load_image_rgb(path))
    preview8 = to_uint8(preview)
    state = existing if existing is not None else saved_or_default_state(path, conn, preview8)
    if state.get("crop_rect") and not replace_existing:
        return SKIPPED_HAS_CROP
    was = {"crop_rect": state.get("crop_rect"), "fine_rotation": float(state.get("fine_rotation", 0.0))}
    state = {**state, "crop_rect": None}
    base = preview if preview.dtype == np.uint16 else preview8
    params, flatfield = _edits_for(path, conn, preview8, state)
    det = detect_frame(_positive(base, params, flatfield, path))
    if det is None:
        return NO_BORDER
    if straighten and AUTO_STRAIGHTEN_MIN <= abs(det.skew_deg) <= AUTO_STRAIGHTEN_MAX:
        state["fine_rotation"] = round(max(-FINE_ROTATION_LIMIT, min(FINE_ROTATION_LIMIT, float(state.get("fine_rotation", 0.0)) - det.skew_deg)), 2)
        params = dataclasses.replace(params, fine_rotation=state["fine_rotation"])
        again = detect_frame(_positive(base, params, flatfield, path))
        if again is not None:
            det = again
    state["crop_rect"] = tuple(int(v) for v in det.rect)
    edit_store.save_edit_state(conn, path, state)
    if ops is not None:
        ops.append(roll_undo.fields_op(path, was, {"crop_rect": state["crop_rect"], "fine_rotation": float(state.get("fine_rotation", 0.0))}))
    image, pre_crop, _stats, _overlay = Renderer().render(base, dataclasses.replace(params, crop_rect=state["crop_rect"]), ("bulk-crop", path), base.shape[1], None,
                                                          want_stats=False, overlay=False, flatfield=flatfield)
    frame = pre_crop if pre_crop is not None else image
    xmp.write_sidecar(path, state, frame.shape[:2])
    try:
        save_edited_thumbnail(thumbnail_cache_dir(), path, image)
    except Exception:
        pass
    return DONE


def reset_crop_photo(path: str, conn, ops: list | None = None) -> str:
    """Take the crop off one photo (its rotation, straightening and every other edit stay). Returns DONE or UNCHANGED."""
    state = edit_store.load_edit_state(conn, path)
    if state is None or not state["crop_rect"]:
        return UNCHANGED
    if ops is not None:
        ops.append(roll_undo.fields_op(path, {"crop_rect": state["crop_rect"]}, {"crop_rect": None}))
    state = {**state, "crop_rect": None}
    edit_store.save_edit_state(conn, path, state)
    xmp.write_sidecar(path, state, (1, 1))
    forget_edited_thumbnail(thumbnail_cache_dir(), path)
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
    summary = {"done": [], "skipped": [], "failed": [], "cancelled": False, "ops": []}
    conn = edit_store.connect(db_path)
    try:
        for i, path in enumerate(paths):
            if cancelled is not None and cancelled():
                summary["cancelled"] = True
                break
            if progress is not None:
                progress(i, len(paths), os.path.basename(path))
            try:
                result = auto_crop_photo(path, conn, replace_existing, True, summary["ops"]) if mode == "auto" else reset_crop_photo(path, conn, summary["ops"])
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
