"""File > Grade Sharpness: how sharp each frame of the open folder is (features/sharpgrade), graded in the background and kept, with the score on the filmstrip's tiles and an overlay that shows
which part of a frame was measured. Nothing about the photos is changed, and none is rejected or flagged for you."""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ...features.persistence import edit_store
from ...features.sharpgrade import logic
from ...features.sharpgrade.processor import load_for_grading
from ...theme.tokens import THEME
from ..sharpness_worker import SharpnessWorker


def severity_colour(severity: str) -> str:
    return {logic.GOOD: THEME.status_success, logic.WARNING: THEME.status_warning, logic.CRITICAL: THEME.status_critical}.get(severity, THEME.text_hint)


def _pixmap(rgb) -> QPixmap:
    h, w = rgb.shape[:2]
    return QPixmap.fromImage(QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy())


class _OverlayView(QLabel):
    """The overlay picture with a readout of the measured value under the pointer: the number the colour stands for, so a spot that is hard to judge by eye is exact on hover."""

    def __init__(self, norm):
        super().__init__()
        self._norm = norm
        self.setMouseTracking(True)
        self._readout = QLabel(self)
        self._readout.setStyleSheet("background: rgba(18, 16, 17, 230); color: white; padding: 2px 8px; border-radius: 3px;")
        self._readout.hide()

    def mouseMoveEvent(self, event) -> None:
        x, y = int(event.position().x()), int(event.position().y())
        h, w = self._norm.shape[:2]
        if 0 <= x < w and 0 <= y < h:
            raw = float(self._norm[y, x])
            self._readout.setText("Not judged" if raw != raw else f"Sharpness: {round(raw * 100)}%")
            self._readout.adjustSize()
            self._readout.move(min(x + 14, max(0, w - self._readout.width() - 2)), max(y - self._readout.height() - 6, 0))
            self._readout.show()
            self._readout.raise_()
        else:
            self._readout.hide()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._readout.hide()
        super().leaveEvent(event)


class SharpnessOverlayDialog(QDialog):
    """One frame with the grade laid over it: red (soft) through amber to green (sharp), only where an edge was found to measure; everywhere else stays plain gray, as no verdict was reached there."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{os.path.basename(path)}: where the sharpness was measured")
        pixels = load_for_grading(path)                                         # the full-resolution frame
        result = logic.grade_sharpness(pixels)                                  # the grade, at the size its thresholds were found at
        detail = logic.grade_sharpness(pixels, max_dim=logic.OVERLAY_MAX_DIM)   # where it was measured, at a fine size: the colours and the hover readout
        gray = logic.gray_frame(pixels)
        norm = logic.overlay_norm(gray, detail.preview)
        self._plain, self._tinted = _pixmap(logic.plain_rgb(gray)), _pixmap(logic.tinted_rgb(gray, norm))
        col = QVBoxLayout(self)
        head = QLabel(f"{logic.WORDS[result.severity]}: {round(result.score)}/100. {result.detail}")
        head.setWordWrap(True)
        head.setStyleSheet(f"font-weight: bold; color: {severity_colour(result.severity)};")
        col.addWidget(head)
        self.toggle = QPushButton("Show Original")
        self.toggle.setCheckable(True)
        self.toggle.setToolTip("Switch the colours off to see the frame as it is")
        self.toggle.toggled.connect(self._toggled)
        col.addWidget(self.toggle)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.view = _OverlayView(norm)
        self.view.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)     # the picture starts at the label's corner, so the pointer's position is the picture's
        self.view.setPixmap(self._tinted)
        scroll.setWidget(self.view)
        col.addWidget(scroll, 1)
        col.addWidget(QLabel("Hover for the exact value. The colours are stretched over this frame's own range, so they say which parts are sharper than the rest of it."))
        self.resize(min(self._tinted.width() + 40, 1200), min(self._tinted.height() + 140, 900))

    def _toggled(self, plain: bool) -> None:
        self.view.setPixmap(self._plain if plain else self._tinted)
        self.toggle.setText("Show Overlay" if plain else "Show Original")


class SharpnessDialog(QDialog):
    """Grades the frames of `paths` (the open folder) and lists them. `db` keeps the grades between sessions; `on_graded(path, severity, score)` is told of each, so the filmstrip shows it."""

    def __init__(self, paths: list[str], db, parent=None, current: str = "", on_graded=None, open_frame=None):
        super().__init__(parent)
        self.setWindowTitle("Grade Sharpness")
        self.resize(760, 560)
        self._paths = list(paths)
        self._db = db
        self._current = current
        self._on_graded = on_graded
        self._open_frame = open_frame
        self._worker: SharpnessWorker | None = None
        self._grades: dict[str, tuple[str, float]] = edit_store.get_sharpness_grades(db, self._paths) if db is not None else {}
        self._rows = {p: i for i, p in enumerate(self._paths)}
        col = QVBoxLayout(self)
        self.headline = QLabel("")
        self.headline.setStyleSheet("font-weight: bold; font-size: 14px;")
        col.addWidget(self.headline)
        about = QLabel("Grades whether what you focused on is in focus (the shot, not the scan): the frame is blurred a second time and the edges that matter are checked for how much of their contrast "
                       "survives. A sharp frame changes a lot, an already soft one hardly at all, so it means the same for different scenes. Each frame gets a score from 0 to 100; below 60 is Soft, "
                       "below 38 Blurred. Nothing is changed and nothing is rejected for you.")
        about.setWordWrap(True)
        about.setProperty("role", "hint")
        col.addWidget(about)
        self.table = QTableWidget(len(self._paths), 3)
        self.table.setHorizontalHeaderLabels(["Frame", "Result", "Score (0-100)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(1, 140)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        col.addWidget(self.table, 1)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        col.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        col.addWidget(self.status)
        row = QHBoxLayout()
        self.roll_button = QPushButton("Grade Entire Roll")
        self.roll_button.setToolTip("Grade every frame that is not graded yet, one at a time, and mark each tile of the filmstrip with its score. Each frame is read in turn, so a long roll takes a while.")
        self.roll_button.clicked.connect(self.grade_roll)
        row.addWidget(self.roll_button)
        self.again_button = QPushButton("Grade All Again")
        self.again_button.setToolTip("Throw the grades away and grade every frame afresh")
        self.again_button.clicked.connect(lambda: self.grade_roll(everything=True))
        row.addWidget(self.again_button)
        self.open_button = QPushButton("Grade the Open Frame")
        self.open_button.setToolTip("Grade just the photo open in the editor, again")
        self.open_button.clicked.connect(self.grade_open_frame)
        row.addWidget(self.open_button)
        self.preview_button = QPushButton("Show Where It Was Measured...")
        self.preview_button.setToolTip("Open the selected frame with red to green laid over the parts that were judged")
        self.preview_button.clicked.connect(self.preview_selected)
        row.addWidget(self.preview_button)
        row.addStretch(1)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.stop_button)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        col.addLayout(row)
        for path in self._paths:
            self._fill_row(path)
        self._sync_buttons()
        self._headline()

    # ------------------------------------------------------------ the list
    def _fill_row(self, path: str) -> None:
        r = self._rows[path]
        name = QTableWidgetItem(os.path.basename(path))
        name.setData(Qt.ItemDataRole.UserRole, path)
        name.setToolTip(path)
        self.table.setItem(r, 0, name)
        grade = self._grades.get(path)
        verdict = QTableWidgetItem(logic.WORDS[grade[0]] if grade else "")
        if grade:
            verdict.setForeground(QColor(severity_colour(grade[0])))
        self.table.setItem(r, 1, verdict)
        self.table.setItem(r, 2, QTableWidgetItem(f"{grade[1]:.0f}" if grade else ""))

    def _headline(self) -> None:
        self.headline.setText(logic.summary(self._grades) if self._grades else f"{len(self._paths)} frames, none graded yet.")

    def _selected_path(self) -> str:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else ""

    def _sync_buttons(self) -> None:
        busy = self._worker is not None and self._worker.isRunning()
        self.roll_button.setEnabled(not busy and bool(self._paths))
        self.again_button.setEnabled(not busy and bool(self._paths))
        self.open_button.setEnabled(not busy and bool(self._current) and self._current in self._rows)
        self.preview_button.setEnabled(not busy and bool(self._selected_path()))
        self.stop_button.setEnabled(busy)

    def _open_row(self, row: int, _column: int) -> None:
        path = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if self._open_frame is not None and path:
            self._open_frame(path)
            self.accept()

    # ------------------------------------------------------------ grading
    def grade_roll(self, everything: bool = False) -> None:
        """Grade the frames that have no grade (or every frame, when `everything`)."""
        if self._worker is not None and self._worker.isRunning():
            return
        if everything:
            if self._db is not None:
                edit_store.forget_sharpness_grades(self._db, self._paths)
            self._grades.clear()
            for path in self._paths:
                self._fill_row(path)
            self._notify_all()
        todo = [p for p in self._paths if p not in self._grades]
        if not todo:
            self.status.setText("Every frame is already graded.")
            return
        self._start(todo)

    def grade_open_frame(self) -> None:
        if self._current and self._current in self._rows and not (self._worker is not None and self._worker.isRunning()):
            self._grades.pop(self._current, None)
            self._start([self._current])

    def _start(self, paths: list[str]) -> None:
        self.status.setText("")
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.progress.setFormat("Grading... %v of %m")
        self.progress.setVisible(True)
        worker = SharpnessWorker(paths)
        worker.progress.connect(lambda done, total, name: (self.progress.setValue(done), self.progress.setToolTip(name)))
        worker.graded.connect(self._graded)
        worker.frame_failed.connect(lambda path, why: self.status.setText(f"{os.path.basename(path)} could not be read: {why}"))
        worker.all_done.connect(self._finished)
        self._worker = worker
        worker.start()
        self._sync_buttons()

    def _graded(self, path: str, severity: str, score: float) -> None:
        self._grades[path] = (severity, score)
        if self._db is not None:
            edit_store.set_sharpness_grade(self._db, path, severity, score)
        if path in self._rows:
            self._fill_row(path)
            self.table.scrollToItem(self.table.item(self._rows[path], 0))
        if self._on_graded is not None:
            self._on_graded(path, severity, score)
        self._headline()

    def _finished(self, stopped: bool) -> None:
        self.progress.setVisible(False)
        if not self.status.text():
            self.status.setText("Stopped." if stopped else "Finished grading.")
        self._sync_buttons()

    def _notify_all(self) -> None:
        if self._on_graded is not None:
            for path in self._paths:
                self._on_graded(path, "", 0.0)      # (an empty severity: take the mark off the tile)

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()

    def preview_selected(self) -> None:
        path = self._selected_path()
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            dialog = SharpnessOverlayDialog(path, self)
        except Exception as exc:
            self.status.setText(f"{os.path.basename(path)} could not be read: {type(exc).__name__}: {exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        dialog.exec()

    def grades(self) -> dict:
        return dict(self._grades)

    def done(self, result: int) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker.wait(15000)       # a thread dropped while it runs aborts the program
        super().done(result)
