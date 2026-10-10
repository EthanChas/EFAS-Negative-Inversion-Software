"""Whether the frames of a roll were scanned consistently: one row per frame with how its film base differs from the roll's."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from ...features.densitometry.roll_job import measurable_paths
from ..roll_worker import RollCheckWorker

_LEVEL_COLOURS = {"ok": "#6bdc6b", "note": "#e6c34a", "warning": "#ec7b6b", "unknown": "#9aa0a6"}
_LEVEL_WORDS = {"ok": "Consistent", "note": "Slight difference", "warning": "Differs"}


class RollCheckDialog(QDialog):
    """Reads the RAW scans in the open folder in the background and lists any that were scanned differently from the rest. Nothing is changed."""

    def __init__(self, paths: list[str], reference=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Roll Consistency")
        self.resize(900, 560)
        self._paths = measurable_paths(paths)
        col = QVBoxLayout(self)
        self.headline = QLabel("Checking the roll...")
        self.headline.setStyleSheet("font-weight: bold; font-size: 14px;")
        col.addWidget(self.headline)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        col.addWidget(self.detail)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Frame", "Result", "Light vs roll (stops)", "Colour vs roll (R / B)", "Notes"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 140)
        self.table.setColumnWidth(3, 150)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        col.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        col.addLayout(row)
        self.report = None
        if not self._paths:
            self.headline.setText("No RAW scans in this folder")
            self.detail.setText("The check reads the film base from RAW files, so it needs the roll's RAW scans.")
            self._worker = None
            return
        self._worker = RollCheckWorker(self._paths, reference)
        self._worker.progress.connect(lambda i, n, name: self.detail.setText(f"Reading {name} ({i + 1} of {n})"))
        self._worker.done.connect(self._show)
        self._worker.failed.connect(lambda m: (self.headline.setText("The check failed"), self.detail.setText(m)))
        self._worker.start()

    def _show(self, report) -> None:
        self.report = report
        self.headline.setText(report.headline)
        self.headline.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {_LEVEL_COLOURS[report.level]};")
        self.detail.setText(report.detail)
        self.table.setRowCount(len(report.frames))
        for r, c in enumerate(report.frames):
            cells = [c.label, _LEVEL_WORDS[c.level] + ("" if c.source == "border" else " (estimated)" if c.level != "ok" else ""), f"{c.light_stops:+.2f}",
                     f"{c.tint_r:+.2f} / {c.tint_b:+.2f}", " ".join(c.notes)]
            for k, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if k == 1:
                    item.setForeground(QColor(_LEVEL_COLOURS[c.level]))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, k, item)
        self.table.resizeRowsToContents()

    def wait(self, msecs: int = 120000) -> None:
        if self._worker is not None:
            self._worker.wait(msecs)

    def done(self, code: int) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(120000)
        super().done(code)
