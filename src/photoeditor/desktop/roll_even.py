"""Evening out a roll: frames the consistency check found scanned differently from the rest are converted against their own film base instead of the roll's.

The film base is what the inversion measures the picture against, so if the light or the colour drifted for one frame, the roll's single film base no longer fits it. Each frame
whose clear border EFAS is sure about gets that border, as it looks in the picture, as its own film base. Frames without a sure border are never touched. Every change is recorded
in the whole-roll undo journal, and the roll's film base itself is not changed."""

import os
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from ..features.densitometry.rollcheck import RollReport
from ..features.open_image.processor import load_image_rgb, make_preview_rgb, to_uint8
from ..features.persistence import edit_store, roll_undo
from ..features.support import applog

MAX_SPREAD = 10.0


@dataclass(frozen=True)
class Candidate:
    path: str
    label: str
    rect_frac: tuple
    stops: float
    level: str


def candidates(report: RollReport, include_notes: bool = False) -> list[Candidate]:
    """Frames worth evening out: those that differ (or, if asked, differ slightly) and whose border is a high-confidence one."""
    wanted = {"warning", "note"} if include_notes else {"warning"}
    return [Candidate(c.path, c.label, c.rect_frac, c.light_stops, c.level) for c in report.frames
            if c.source == "border" and c.confidence == "high" and c.rect_frac and c.path and c.level in wanted]


def measure_display_base(path: str, rect_frac: tuple) -> tuple[tuple[int, int, int], float]:
    """The border's colour as it looks in the picture (the same 8-bit values the film-base picker reads), and how uneven it is."""
    preview = to_uint8(make_preview_rgb(load_image_rgb(path)))
    h, w = preview.shape[:2]
    x1, y1, x2, y2 = rect_frac
    patch = preview[int(y1 * h):max(int(y1 * h) + 1, int(y2 * h)), int(x1 * w):max(int(x1 * w) + 1, int(x2 * w))].reshape(-1, 3).astype(np.float64)
    med = np.median(patch, axis=0)
    spread = float(np.median(np.abs(patch - med), axis=0).max() * 1.4826)
    rgb = tuple(int(max(1, min(254, round(v)))) for v in med)
    return rgb, spread


def run(cands: list[Candidate], db_path: str, progress=None, cancelled=None) -> dict:
    """Give each candidate its own film base. Returns {'done': [paths], 'skipped': [(path, why)], 'ops': [...], 'cancelled': bool}."""
    summary = {"done": [], "skipped": [], "ops": [], "cancelled": False}
    conn = edit_store.connect(db_path)
    try:
        for i, c in enumerate(cands):
            if cancelled is not None and cancelled():
                summary["cancelled"] = True
                break
            if progress is not None:
                progress(i, len(cands), os.path.basename(c.path))
            try:
                rgb, spread = measure_display_base(c.path, c.rect_frac)
            except Exception as exc:
                summary["skipped"].append((c.path, f"could not be read ({type(exc).__name__})"))
                applog.logger().warning("Even out roll: %s: %s", os.path.basename(c.path), exc)
                continue
            if spread > MAX_SPREAD:
                summary["skipped"].append((c.path, "its border is not a uniform patch in the picture, so it is not a safe film base"))
                continue
            before = edit_store.get_photo_film_base(conn, c.path)
            if before == rgb:
                summary["skipped"].append((c.path, "already uses this film base"))
                continue
            edit_store.set_photo_film_base(conn, c.path, rgb)
            summary["ops"].append(roll_undo.film_base_op(c.path, before, rgb))
            summary["done"].append(c.path)
    finally:
        conn.close()
    return summary


def clear_own_bases(paths: list[str], db_path: str) -> dict:
    """Put every photo back on its roll's film base."""
    summary = {"done": [], "ops": []}
    conn = edit_store.connect(db_path)
    try:
        for p in paths:
            before = edit_store.get_photo_film_base(conn, p)
            if before is not None:
                edit_store.set_photo_film_base(conn, p, None)
                summary["ops"].append(roll_undo.film_base_op(p, before, None))
                summary["done"].append(p)
    finally:
        conn.close()
    return summary


class EvenOutWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_all = pyqtSignal(object)

    def __init__(self, cands: list[Candidate], db_path: str):
        super().__init__()
        self._args = (list(cands), db_path)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        self.finished_all.emit(run(self._args[0], self._args[1], self.progress.emit, lambda: self._cancel))
