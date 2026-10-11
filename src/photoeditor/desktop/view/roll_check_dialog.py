"""Whether the frames of a roll were scanned consistently: one row per frame with how its film base differs from the roll's."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
import os

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from ...features.densitometry.roll_job import measurable_paths
from .. import roll_even
from ..roll_worker import RollCheckWorker

_LEVEL_COLOURS = {"ok": "#6bdc6b", "note": "#e6c34a", "warning": "#ec7b6b", "unknown": "#9aa0a6"}
_LEVEL_WORDS = {"ok": "Consistent", "note": "Slight difference", "warning": "Differs"}


class RollCheckDialog(QDialog):
    """Reads the RAW scans in the open folder in the background and lists any that were scanned differently from the rest. Nothing is changed."""

    def __init__(self, paths: list[str], reference=None, parent=None, controller=None, on_changed=None):
        super().__init__(parent)
        self._controller = controller
        self._on_changed = on_changed
        self._even_worker = None
        self._candidates: list = []
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
        self.status = QLabel("")
        self.status.setWordWrap(True)
        col.addWidget(self.status)
        row = QHBoxLayout()
        self.even_button = QPushButton("Even Out Differing Frames...")
        self.even_button.setToolTip("Convert each frame the check found different against its own film base (its clear border) instead of the roll's. Undo is above the filmstrip.")
        self.even_button.setEnabled(False)
        self.even_button.clicked.connect(self.even_out)
        self.clear_button = QPushButton("Use the Roll's Film Base Again...")
        self.clear_button.setToolTip("Take away every frame's own film base, so the whole roll is converted against the roll's film base again.")
        self.clear_button.setEnabled(False)
        self.clear_button.clicked.connect(self.use_roll_base_again)
        if controller is None:
            self.even_button.hide()
            self.clear_button.hide()
        row.addWidget(self.even_button)
        row.addWidget(self.clear_button)
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
        self._candidates = roll_even.candidates(report)
        unsure = sum(1 for c in report.frames if c.level == "warning" and c not in [] and not any(x.path == c.path for x in self._candidates))
        self.even_button.setEnabled(bool(self._candidates) and self._even_worker is None)
        if self._controller is not None:
            self.clear_button.setEnabled(any(self._controller.has_own_film_base(c.path) for c in report.frames if c.path))
            if self._candidates:
                self.status.setText(f"{len(self._candidates)} differing frame{'s have' if len(self._candidates) != 1 else ' has'} a clear border EFAS is sure about and can be evened out."
                                    + (f" {unsure} more differ but have no sure border, so they cannot be." if unsure else ""))
            elif unsure:
                self.status.setText(f"{unsure} frame{'s differ' if unsure != 1 else ' differs'}, but none has a clear border EFAS is sure about, so there is nothing safe to even out automatically.")

    def _ask(self, title: str, text: str, info: str, ok_label: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(title)
        box.setText(text)
        box.setInformativeText(info)
        go = box.addButton(ok_label, QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is go

    def even_out(self) -> None:
        n = len(self._candidates)
        if not n or self._controller is None or not self._ask(
                "Even Out Roll", f"Even out {n} frame{'s' if n != 1 else ''}?",
                "Each of these frames will be converted against its own film base (its clear border) instead of the roll's, so it matches the rest. The roll's film base and your "
                "other edits are not changed. You can undo it with the Undo button above the filmstrip, or with Use the Roll's Film Base Again.", f"Even Out {n} Frame{'s' if n != 1 else ''}"):
            return
        self.even_button.setEnabled(False)
        self.status.setText("Measuring each frame's border...")
        self._even_worker = roll_even.EvenOutWorker(self._candidates, self._controller.db_path)
        self._even_worker.progress.connect(lambda i, total, name: self.status.setText(f"Measuring {name} ({i + 1} of {total})"))
        self._even_worker.finished_all.connect(self._even_done)
        self._even_worker.start()

    def _even_done(self, summary: dict) -> None:
        self._even_worker = None
        folder = os.path.dirname(self._paths[0]) if self._paths else ""
        if summary["ops"]:
            self._controller.record_roll_action(folder, "Even Out Roll", summary["ops"])
        self._controller.refresh_film_base()
        if self._on_changed and summary["done"]:
            self._on_changed(summary["done"])
        lines = [f"Evened out {len(summary['done'])} frame{'s' if len(summary['done']) != 1 else ''}."]
        if summary["skipped"]:
            lines.append(f"{len(summary['skipped'])} left as they were: " + "; ".join(f"{os.path.basename(p)} ({why})" for p, why in summary["skipped"][:4]) + ("..." if len(summary["skipped"]) > 4 else ""))
        self.status.setText(" ".join(lines) + " Undo is the Undo button above the filmstrip.")
        self.clear_button.setEnabled(True)
        self.even_button.setEnabled(False)

    def use_roll_base_again(self) -> None:
        if self._controller is None or not self._ask("Roll film base", "Put every frame back on the roll's film base?",
                                                      "Frames that were evened out go back to being converted against the roll's film base.", "Use the Roll's Film Base"):
            return
        summary = roll_even.clear_own_bases([c.path for c in (self.report.frames if self.report else []) if c.path], self._controller.db_path)
        folder = os.path.dirname(self._paths[0]) if self._paths else ""
        if summary["ops"]:
            self._controller.record_roll_action(folder, "Roll Film Base", summary["ops"])
        self._controller.refresh_film_base()
        if self._on_changed and summary["done"]:
            self._on_changed(summary["done"])
        self.status.setText(f"{len(summary['done'])} frame{'s are' if len(summary['done']) != 1 else ' is'} back on the roll's film base.")
        self.clear_button.setEnabled(False)

    def wait(self, msecs: int = 120000) -> None:
        if self._worker is not None:
            self._worker.wait(msecs)
        if self._even_worker is not None:
            self._even_worker.wait(msecs)

    def done(self, code: int) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(120000)
        super().done(code)
