"""Fitting a colour matrix from a scanned transmission colour target: load the maker's reference file, mark where the patch array is, fit, and keep the result with a camera set-up."""

import datetime as dt
import os

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
)

from ...features.densitometry import colourtarget as ct
from ...features.densitometry import film_profile as fp
from ...features.lut.logic import to_uint8


class ColourTargetDialog(QDialog):
    """Nothing about the standard conversion changes: the fitted matrix is stored in the chosen camera set-up as a measured record of its colour accuracy."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.c = controller
        self.setWindowTitle("Colour Target")
        self.resize(860, 760)
        self.reference = None
        self.fit = None
        self._inputs = controller.colour_target_inputs()
        col = QVBoxLayout(self)
        intro = QLabel("Scan a transmission colour target (an IT8.7/1 slide or negative target) with the same light and exposure as your film, open that scan, sample the clear "
                       "light, then load the maker's reference file and mark the patch array. EFAS fits a matrix from the camera's colours to the target's and reports how "
                       "accurate it is.")
        intro.setWordWrap(True)
        col.addWidget(intro)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumHeight(280)
        col.addWidget(self.image, 1)
        row = QHBoxLayout()
        self.ref_label = QLabel("No reference file loaded")
        load = QPushButton("Load Reference File...")
        load.clicked.connect(self._load_reference)
        row.addWidget(load)
        row.addWidget(self.ref_label, 1)
        col.addLayout(row)
        grid = QHBoxLayout()
        self.cols = self._spin(22, 1, 60, "Columns")
        self.rows = self._spin(12, 1, 40, "Rows")
        self.edges = {}
        for key, default in (("Left", 4.0), ("Top", 8.0), ("Right", 96.0), ("Bottom", 80.0)):
            s = QDoubleSpinBox()
            s.setRange(0.0, 100.0)
            s.setDecimals(1)
            s.setSuffix(" %")
            s.setValue(default)
            s.valueChanged.connect(self._redraw)
            self.edges[key] = s
        for label, w in (("Columns", self.cols), ("Rows", self.rows), *self.edges.items()):
            grid.addWidget(QLabel(label))
            grid.addWidget(w)
        col.addLayout(grid)
        col.addWidget(QLabel("Left, Top, Right and Bottom are the outer edges of the patch array, as a share of the picture. Rows are lettered A, B, C... and columns numbered 1, 2, 3..."))
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(150)
        col.addWidget(self.report)
        buttons = QHBoxLayout()
        self.fit_button = QPushButton("Fit Colour Matrix")
        self.fit_button.clicked.connect(self._fit)
        self.setup_box = QComboBox()
        for s in controller.setup_store().list():
            self.setup_box.addItem(s["name"], s["id"])
        self.setup_box.addItem("New camera set-up...", "")
        self.save_button = QPushButton("Save to Camera Set-up")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(self.fit_button)
        buttons.addStretch(1)
        buttons.addWidget(self.setup_box)
        buttons.addWidget(self.save_button)
        buttons.addWidget(close)
        col.addLayout(buttons)
        if "error" in self._inputs:
            self.report.setPlainText(self._inputs["error"])
            self.fit_button.setEnabled(False)
        self._redraw()

    def _spin(self, value: int, lo: int, hi: int, tip: str) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(value)
        s.setToolTip(tip)
        s.valueChanged.connect(self._redraw)
        return s

    def _rect(self) -> tuple[float, float, float, float] | None:
        if "framed" not in self._inputs:
            return None
        h, w = self._inputs["framed"].shape[:2]
        e = {k: v.value() / 100.0 for k, v in self.edges.items()}
        return e["Left"] * w, e["Top"] * h, e["Right"] * w, e["Bottom"] * h

    def _patches(self):
        return ct.grid_patches(*self._rect(), self.cols.value(), self.rows.value())

    def _redraw(self, *_a) -> None:
        if "raw" not in self._inputs:
            return
        a = np.ascontiguousarray(to_uint8(self._inputs["raw"]))
        h, w = a.shape[:2]
        pm = QPixmap.fromImage(QImage(a.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy())
        painter = QPainter(pm)
        painter.setPen(QPen(Qt.GlobalColor.green, max(1, w // 700)))
        try:
            for p in self._patches():
                painter.drawRect(int(p.cx - p.half), int(p.cy - p.half), 2 * p.half, 2 * p.half)
        except ct.ColourTargetError:
            pass
        painter.end()
        self.image.setPixmap(pm.scaled(820, 320, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _load_reference(self) -> None:
        path, _f = QFileDialog.getOpenFileName(self, "Colour target reference file", "", "Reference data (*.txt *.cgats *.csv);;All files (*)")
        if path:
            self.load_reference(path)

    def load_reference(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                self.reference = ct.parse_reference(f.read(), os.path.splitext(os.path.basename(path))[0])
        except (OSError, ct.ColourTargetError) as exc:
            self.reference = None
            self.ref_label.setText("The file could not be used.")
            self.report.setPlainText(str(exc))
            return
        self.ref_label.setText(f"{self.reference.name}: {len(self.reference.ids)} patches")
        self.report.setPlainText("Reference loaded. Mark the patch array, then fit.")

    def _fit(self) -> None:
        if self.reference is None:
            self.report.setPlainText("Load the reference file first.")
            return
        inp = self._inputs
        try:
            ids = ct.grid_ids(self.cols.value(), self.rows.value())
            got_ids, t, xyz, skipped = ct.measure_patches(inp["framed"], self._patches(), ids, self.reference, inp["clear"], inp["floor"])
            self.fit = ct.fit_matrix(t, xyz, got_ids, skipped)
        except ct.ColourTargetError as exc:
            self.fit = None
            self.save_button.setEnabled(False)
            self.report.setPlainText(str(exc))
            return
        self.report.setPlainText(ct.describe(self.fit))
        self.save_button.setEnabled(True)

    def _save(self) -> None:
        if self.fit is None:
            return
        store = self.c.setup_store()
        ident = self.setup_box.currentData()
        if ident:
            setup = store.load(ident)
        else:
            name, ok = QInputDialog.getText(self, "New camera set-up", "Name:")
            if not ok or not name.strip():
                return
            setup = fp.new_setup(name.strip())
        grid = {"columns": self.cols.value(), "rows": self.rows.value(), **{k.lower(): v.value() for k, v in self.edges.items()}}
        setup.calibration = {**setup.calibration, "colour": ct.calibration_record(self.fit, self.reference, grid, dt.date.today().isoformat())}
        store.save(setup)
        QMessageBox.information(self, "Colour Target", f"Saved to the camera set-up '{setup.name}'. The standard conversion is unchanged.")
        self.accept()
