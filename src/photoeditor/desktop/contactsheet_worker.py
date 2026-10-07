"""Builds a roll's contact sheet PDF on a worker thread: each photo is rendered with its saved edits at thumbnail size, then the pages are
drawn and written (the drawing itself is features/contactsheet/logic.py)."""

import os

from PyQt6.QtCore import QThread, pyqtSignal

from ..features.contactsheet.logic import SheetFrame, SheetOptions, draw_pages, header_text, save_pdf
from ..features.persistence import edit_store
from .export_worker import load_roll, render_edited_thumbnail

_THUMB_DIM = 900


class ContactSheetWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_all = pyqtSignal(object)

    def __init__(self, paths: list[str], options: SheetOptions, out_path: str, db_path: str):
        super().__init__()
        self._paths = list(paths)
        self._options = options
        self._out_path = out_path
        self._db_path = db_path
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        summary = {"path": None, "frames": 0, "failed": [], "cancelled": False, "error": ""}
        conn = edit_store.connect(self._db_path)
        try:
            flags = edit_store.get_flags(conn, self._paths)
            ratings = edit_store.get_ratings(conn, self._paths)
            wanted = [(i + 1, p) for i, p in enumerate(self._paths)
                      if self._options.include_rejected or flags.get(p) != edit_store.FLAG_REJECTED]
            frames: list[SheetFrame] = []
            for done, (number, path) in enumerate(wanted):
                if self._cancel:
                    summary["cancelled"] = True
                    break
                try:
                    image = render_edited_thumbnail(path, conn, _THUMB_DIM)
                    flag = flags.get(path)
                    frames.append(SheetFrame(image=_to_pil(image), number=number, rating=int(ratings.get(path, 0)), flag=flag, name=os.path.splitext(os.path.basename(path))[0]))
                except Exception as exc:
                    summary["failed"].append((path, f"{type(exc).__name__}: {exc}"))
                self.progress.emit(done + 1, len(wanted), os.path.basename(path))
            if not summary["cancelled"] and frames:
                roll = load_roll(self._paths[0], conn)
                title, lines = header_text(roll, os.path.basename(os.path.dirname(self._paths[0])), len(frames))
                pages = draw_pages(frames, self._options, title, lines)
                save_pdf(pages, self._out_path, self._options.dpi)
                summary["path"] = self._out_path
                summary["frames"] = len(frames)
            elif not summary["cancelled"]:
                summary["error"] = "There was nothing to put on the sheet."
        except Exception as exc:
            summary["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            conn.close()
        self.finished_all.emit(summary)


def _to_pil(pixels):
    from PIL import Image

    return Image.fromarray(pixels)
