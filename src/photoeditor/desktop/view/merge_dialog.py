"""Merge several scans of one frame into one: an exposure bracket (shadow detail without clipping the highlights) or three scans lit by red, green and blue light."""

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...features.densitometry import merge_job
from ...features.open_image.logic import file_dialog_filter
from ..merge_worker import MergeWorker

_CHANNELS = ("Red-lit scan", "Green-lit scan", "Blue-lit scan")


class MergeDialog(QDialog):
    """Nothing is changed in the source scans: the merged scan is a new 16-bit TIFF with a small sidecar file that lets EFAS read its exact linear values."""

    open_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merge Scans")
        self.resize(760, 640)
        self._worker = None
        self._output_touched = False
        col = QVBoxLayout(self)
        intro = QLabel("Combine several RAW scans of the same frame into one measured scan. Keep the camera and film still between scans (a tripod helps); EFAS corrects "
                       "small movements.")
        intro.setWordWrap(True)
        col.addWidget(intro)
        self.mode = QComboBox()
        self.mode.addItem("Exposure bracket: same light, different exposure times", "bracket")
        self.mode.addItem("One light per colour: a red, a green and a blue lit scan", "channels")
        self.mode.currentIndexChanged.connect(self._mode_changed)
        col.addWidget(self.mode)
        self._stack = QStackedWidget()
        col.addWidget(self._stack, 1)

        bracket = QWidget()
        bl = QVBoxLayout(bracket)
        bl.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Scan", "Exposure time (s)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 440)
        bl.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("Add Scans...")
        add.clicked.connect(self._add_scans)
        remove = QPushButton("Remove Selected")
        remove.clicked.connect(self._remove_selected)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        bl.addLayout(row)
        hint = QLabel("Exposure times are read from the files. Check them: a wrong time would make the merge wrong. The merged scan is in the units of the shortest exposure.")
        hint.setWordWrap(True)
        bl.addWidget(hint)
        self._stack.addWidget(bracket)

        channels = QWidget()
        cl = QVBoxLayout(channels)
        cl.setContentsMargins(0, 0, 0, 0)
        self.channel_edits = []
        for name in _CHANNELS:
            r = QHBoxLayout()
            label = QLabel(name)
            label.setMinimumWidth(110)
            edit = QLineEdit()
            edit.setPlaceholderText("Choose a RAW file")
            edit.textChanged.connect(self._paths_changed)
            btn = QPushButton("Browse...")
            btn.clicked.connect(lambda _=False, e=edit: self._pick_channel(e))
            r.addWidget(label)
            r.addWidget(edit, 1)
            r.addWidget(btn)
            cl.addLayout(r)
            self.channel_edits.append(edit)
        note = QLabel("The red channel is taken from the red-lit scan, green from the green-lit one and blue from the blue-lit one, so each colour is exposed to suit "
                      "its own film layer.")
        note.setWordWrap(True)
        cl.addWidget(note)
        cl.addStretch(1)
        self._stack.addWidget(channels)

        self.align = QCheckBox("Correct small movements between scans")
        self.align.setChecked(True)
        col.addWidget(self.align)
        out = QHBoxLayout()
        out.addWidget(QLabel("Save as"))
        self.output = QLineEdit()
        self.output.textEdited.connect(lambda _t: setattr(self, "_output_touched", True))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._pick_output)
        out.addWidget(self.output, 1)
        out.addWidget(browse)
        col.addLayout(out)
        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setMaximumHeight(130)
        col.addWidget(self.status)
        buttons = QHBoxLayout()
        self.merge_button = QPushButton("Merge")
        self.merge_button.setDefault(True)
        self.merge_button.clicked.connect(self._start)
        self.open_button = QPushButton("Open Merged Scan")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_result)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(self.merge_button)
        buttons.addWidget(self.open_button)
        buttons.addWidget(close)
        col.addLayout(buttons)
        self._result_path = ""

    def _mode_changed(self) -> None:
        self._stack.setCurrentIndex(0 if self.mode.currentData() == "bracket" else 1)
        self._paths_changed()

    def _add_scans(self) -> None:
        files, _f = QFileDialog.getOpenFileNames(self, "Choose the scans of one frame", "", file_dialog_filter())
        self.add_paths(files)

    def add_paths(self, files: list[str]) -> None:
        times = merge_job.read_times(files)
        for path, t in zip(files, times):
            r = self.table.rowCount()
            self.table.insertRow(r)
            item = QTableWidgetItem(path)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 0, item)
            spin = QDoubleSpinBox()
            spin.setDecimals(6)
            spin.setRange(0.0, 3600.0)
            spin.setSingleStep(0.001)
            spin.setValue(t or 0.0)
            spin.setSpecialValueText("not stated")
            self.table.setCellWidget(r, 1, spin)
        self._paths_changed()

    def _remove_selected(self) -> None:
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
        self._paths_changed()

    def _pick_channel(self, edit: QLineEdit) -> None:
        f, _f = QFileDialog.getOpenFileName(self, "Choose a RAW scan", "", file_dialog_filter())
        if f:
            edit.setText(f)

    def _pick_output(self) -> None:
        f, _f = QFileDialog.getSaveFileName(self, "Save merged scan", self.output.text(), "TIFF (*.tif)")
        if f:
            self.output.setText(f if f.lower().endswith((".tif", ".tiff")) else f + ".tif")
            self._output_touched = True

    def paths(self) -> list[str]:
        if self.mode.currentData() == "bracket":
            return [self.table.item(r, 0).text() for r in range(self.table.rowCount())]
        return [e.text().strip() for e in self.channel_edits]

    def times(self) -> list[float | None]:
        out = []
        for r in range(self.table.rowCount()):
            v = self.table.cellWidget(r, 1).value()
            out.append(v if v > 0 else None)
        return out

    def _paths_changed(self) -> None:
        paths = [p for p in self.paths() if p]
        if paths and not self._output_touched:
            self.output.setText(merge_job.suggested_output(paths[0], self.mode.currentData()))

    def _start(self) -> None:
        mode = self.mode.currentData()
        out = self.output.text().strip()
        if not out:
            self.status.setPlainText("Choose where to save the merged scan.")
            return
        if os.path.exists(out) and not os.path.exists(out + ".efas-merge.json"):
            self.status.setPlainText("A file with that name already exists and was not made by a merge. Choose another name so it is not overwritten.")
            return
        self.merge_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.status.setPlainText("Working...")
        self._worker = MergeWorker(mode, self.paths(), self.times() if mode == "bracket" else None, out, self.align.isChecked())
        self._worker.progress.connect(lambda i, n, msg: self.status.setPlainText(f"{msg} ({i + 1} of {n})"))
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, info: dict) -> None:
        self._result_path = info["path"]
        self.status.setPlainText(info["summary"] + f"\n\nSaved to {info['path']}")
        self.merge_button.setEnabled(True)
        self.open_button.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self.status.setPlainText(message)
        self.merge_button.setEnabled(True)

    def _open_result(self) -> None:
        if self._result_path:
            self.open_requested.emit(self._result_path)
            self.accept()

    def wait(self, msecs: int = 60000) -> None:
        if self._worker is not None:
            self._worker.wait(msecs)

    def done(self, code: int) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(60000)
        super().done(code)
