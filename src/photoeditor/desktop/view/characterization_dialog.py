"""The guided Film Characterization workflow (docs/sensitometry-tier2-design.md, sections 3 and 8): sample the patches of a step target on the raw scan, check
them, then calibrate the camera against a calibrated tablet, fit the curves of a film strip exposed through one, or test the sensor's linearity.

The dialog shows the limits of each procedure where they apply and never builds a measured curve without confirmed known exposures.
"""

import os

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ...features.densitometry import capture, characterize, film_profile as fp, scanner, target, view_model
from ...features.lut.logic import to_uint8
from ...theme.tokens import THEME
from .fit_plots import FitPlot, GradientPlot, ResidualPlot

_VALID, _INVALID = QColor("#6bdc6b"), QColor("#e0a040")
_TAB_SCANNER, _TAB_FILM, _TAB_LINEARITY = 0, 1, 2


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    return label


class ScanCanvas(QWidget):
    """The raw scan, scaled to fit, where the first and last patch are clicked; the patch boxes are drawn over it."""

    picked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 300)
        self._image: QImage | None = None
        self._size = (0, 0)
        self._points: list[tuple[float, float]] = []
        self._patches: list = []
        self._valid: list[bool] = []
        self._picking = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_array(self, arr: np.ndarray | None) -> None:
        if arr is None:
            self._image, self._size = None, (0, 0)
        else:
            a = np.ascontiguousarray(to_uint8(arr))
            h, w = a.shape[:2]
            self._image = QImage(a.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
            self._size = (w, h)
        self.update()

    def begin_pick(self) -> None:
        self._points, self._patches, self._valid, self._picking = [], [], [], True
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def points(self) -> list[tuple[float, float]]:
        return list(self._points)

    def set_patches(self, patches, valid) -> None:
        self._patches, self._valid = list(patches), list(valid)
        self.update()

    def _layout(self):
        w, h = self._size
        if not w or not h:
            return 0.0, 0.0, 1.0
        scale = min(self.width() / w, self.height() / h)
        return (self.width() - w * scale) / 2.0, (self.height() - h * scale) / 2.0, scale

    def mousePressEvent(self, event) -> None:
        if not self._picking or self._image is None or event.button() != Qt.MouseButton.LeftButton:
            return
        ox, oy, s = self._layout()
        x, y = (event.position().x() - ox) / s, (event.position().y() - oy) / s
        if 0 <= x < self._size[0] and 0 <= y < self._size[1]:
            self._points.append((float(x), float(y)))
            if len(self._points) == 2:
                self._picking = False
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.picked.emit()
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(THEME.bg_input))
        if self._image is None:
            p.setPen(QColor(THEME.text_muted))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Open the photo of the target first.")
            return
        ox, oy, s = self._layout()
        p.drawImage(QRectF(ox, oy, self._size[0] * s, self._size[1] * s), self._image)
        p.setFont(QFont(THEME.font_family, 8))
        for i, pt in enumerate(self._patches):
            ok = self._valid[i] if i < len(self._valid) else True
            p.setPen(QPen(_VALID if ok else _INVALID, 1.6))
            p.drawRect(QRectF(ox + (pt.cx - pt.half) * s, oy + (pt.cy - pt.half) * s, (2 * pt.half + 1) * s, (2 * pt.half + 1) * s))
            p.drawText(QPointF(ox + (pt.cx - pt.half) * s, oy + (pt.cy - pt.half) * s - 2), str(i + 1))
        p.setPen(QPen(QColor("#ff4040"), 2))
        for x, y in self._points:
            p.drawEllipse(QPointF(ox + x * s, oy + y * s), 5, 5)
        if self._picking:
            p.setPen(QColor("#ffffff"))
            p.drawText(8, 16, "Click the centre of patch 1, then the centre of the last patch." if not self._points else "Now click the centre of the last patch.")


def _ask(parent, title: str, fields: list[tuple[str, str]]) -> list[str] | None:
    """A small form of text fields; None when cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    form = QFormLayout(dlg)
    edits = []
    for label, default in fields:
        e = QLineEdit(default)
        edits.append(e)
        form.addRow(label, e)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    form.addRow(buttons)
    return [e.text().strip() for e in edits] if dlg.exec() else None


class CharacterizationDialog(QDialog):
    profile_saved = pyqtSignal(str)
    setup_saved = pyqtSignal(str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Film Characterization")
        self.resize(1180, 760)
        self.c = controller
        self._samples: list = []
        self._patches: list = []
        self._calibration: dict | None = None
        self._film = None
        self._profile = None
        self._linearity: dict | None = None
        self._lin_rows: list[dict] = []
        outer = QHBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split)
        self.canvas = ScanCanvas()
        self.canvas.picked.connect(self._on_picked)
        left = QWidget()
        lcol = QVBoxLayout(left)
        lcol.setContentsMargins(0, 0, 0, 0)
        lcol.addWidget(self.canvas, 1)
        self._status = _note("")
        lcol.addWidget(self._status)
        split.addWidget(left)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(430)
        right = QWidget()
        self._rcol = QVBoxLayout(right)
        scroll.setWidget(right)
        split.addWidget(scroll)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self._build_target_box()
        self.tabs = QTabWidget()
        self.tabs.addTab(self._scanner_tab(), "Scanner calibration")
        self.tabs.addTab(self._film_tab(), "Film characterization")
        self.tabs.addTab(self._linearity_tab(), "Linearity test")
        self.tabs.currentChanged.connect(self._tab_changed)
        self._rcol.addWidget(self.tabs)
        self._rcol.addStretch(1)
        self._load_scan()
        self._tab_changed(0)

    # --- the scan and the target ----------------------------------------------------------------------------------------------------------

    def _load_scan(self) -> None:
        raw = self.c.render_raw_scan()
        self.canvas.set_array(raw)
        if raw is None:
            self._status.setText("Open the photo of the step tablet (or of the developed exposure strip) in the editor first.")
        else:
            self._status.setText("The raw scan is shown. Set the target below, then pick the first and last patch.")

    def _build_target_box(self) -> None:
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(0, 0, 0, 0)
        self.t_name = QLineEdit("Kodak step tablet")
        self.t_steps = QSpinBox()
        self.t_steps.setRange(3, 60)
        self.t_steps.setValue(21)
        self.t_start = QDoubleSpinBox()
        self.t_start.setRange(0.0, 4.0)
        self.t_start.setDecimals(3)
        self.t_start.setSingleStep(0.01)
        self.t_start.setValue(0.05)
        self.t_inc = QDoubleSpinBox()
        self.t_inc.setRange(0.01, 1.0)
        self.t_inc.setDecimals(3)
        self.t_inc.setSingleStep(0.005)
        self.t_inc.setValue(0.15)
        self.t_list = QPlainTextEdit()
        self.t_list.setPlaceholderText("Optional: the tablet's calibrated (actual) step densities from its certificate, separated by spaces or commas")
        self.t_list.setMaximumHeight(60)
        self.t_first = QComboBox()
        self.t_first.addItem("the lowest-density (clearest) step", False)
        self.t_first.addItem("the highest-density (densest) step", True)
        self.t_fill = QSpinBox()
        self.t_fill.setRange(20, 90)
        self.t_fill.setValue(50)
        self.t_fill.setSuffix(" % of the spacing")
        form.addRow("Target name", self.t_name)
        form.addRow("Steps", self.t_steps)
        form.addRow("First step density", self.t_start)
        form.addRow("Step increment", self.t_inc)
        form.addRow("Actual densities", self.t_list)
        form.addRow("The first patch is", self.t_first)
        form.addRow("Patch size", self.t_fill)
        row = QHBoxLayout()
        pick = QPushButton("Pick Patches on the Scan")
        pick.clicked.connect(self._begin_pick)
        sample = QPushButton("Sample Patches")
        sample.clicked.connect(self._sample)
        row.addWidget(pick)
        row.addWidget(sample)
        form.addRow(row)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Use", "Tablet D", "R", "G", "B", "Status"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(190)
        self.table.itemChanged.connect(self._clear_results)
        self._target_box = box
        self._rcol.addWidget(box)
        self._rcol.addWidget(_note("Tablet densities are the light-stopping power of each step. A sensitometric exposure through a tablet gives the film steps of known relative "
                                   "exposure: log H = log H0 - D."))
        self._rcol.addWidget(self.table)
        self._tolerance = _note("")
        self._rcol.addWidget(self._tolerance)

    def _target(self) -> target.StepTarget:
        text = self.t_list.toPlainText().strip()
        reverse = bool(self.t_first.currentData())
        if text:
            values = target.parse_density_list(text)
            return target.StepTarget(steps=len(values), start=values[0], increment=self.t_inc.value(), densities=values, name=self.t_name.text().strip(), reverse=reverse)
        return target.StepTarget(steps=self.t_steps.value(), start=self.t_start.value(), increment=self.t_inc.value(), name=self.t_name.text().strip(), reverse=reverse)

    def _begin_pick(self) -> None:
        if self.c.render_raw_scan() is None:
            QMessageBox.information(self, "Film Characterization", "Open a photo first.")
            return
        self.canvas.begin_pick()
        self._clear_results()
        self._status.setText("Click the centre of the first patch, then the centre of the last patch.")

    def _on_picked(self) -> None:
        self._layout_patches()

    def _layout_patches(self) -> bool:
        pts = self.canvas.points()
        if len(pts) != 2:
            return False
        try:
            tgt = self._target()
            self._patches = target.layout_patches(pts[0], pts[1], tgt.steps, self.t_fill.value() / 100.0)
        except (target.TargetError, ValueError) as exc:
            QMessageBox.warning(self, "Film Characterization", str(exc))
            return False
        self.canvas.set_patches(self._patches, [True] * len(self._patches))
        self._status.setText(f"{len(self._patches)} patches laid out. Press Sample Patches.")
        return True

    def _sample(self) -> None:
        if not self.canvas.points() or len(self.canvas.points()) != 2:
            QMessageBox.information(self, "Film Characterization", "Pick the first and last patch on the scan first.")
            return
        if not self._layout_patches():
            return
        if not self.c.ensure_linear():
            QMessageBox.warning(self, "Film Characterization", f"The scan could not be read for measurement: {self.c.linear_error()}")
            return
        framed, info = self.c.framed_linear(), self.c.linear_info()
        self._samples = target.sample_patches(framed, self._patches, info.floor())
        self._fill_table()
        self._clear_results()
        valid = [s.valid() for s in self._samples]
        self.canvas.set_patches(self._patches, valid)
        self._status.setText(f"{sum(valid)} of {len(valid)} patches are usable. Orange boxes are not; the table says why.")

    def _fill_table(self) -> None:
        tgt = self._target()
        d = tgt.values()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._samples))
        for i, s in enumerate(self._samples):
            use = QTableWidgetItem(str(i + 1))
            use.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            use.setCheckState(Qt.CheckState.Checked if s.valid() else Qt.CheckState.Unchecked)
            self.table.setItem(i, 0, use)
            self.table.setItem(i, 1, QTableWidgetItem(f"{d[i]:.3f}"))
            for c in range(3):
                self.table.setItem(i, 2 + c, QTableWidgetItem(f"{s.v[c]:.5f}"))
            status = QTableWidgetItem("ok" if s.valid() else "; ".join(s.reasons))
            status.setForeground(_VALID if s.valid() else _INVALID)
            self.table.setItem(i, 5, status)
            for col in range(1, 6):
                self.table.item(i, col).setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.blockSignals(False)
        if tgt.actual():
            warnings = target.tolerance_warnings(d, tgt.increment)
            text = " ".join(warnings) if warnings else "Actual densities entered: within the RP 14 tolerances."
        else:
            text = "Nominal densities are in use. Real tablets differ; enter the calibrated values if you have them."
        self._tolerance.setText(text)

    def _used(self) -> np.ndarray:
        return np.array([self.table.item(i, 0).checkState() == Qt.CheckState.Checked and self._samples[i].valid() for i in range(self.table.rowCount())], dtype=bool)

    def _clear_results(self, *_a) -> None:
        self._calibration = None
        if hasattr(self, "scan_result"):
            self.scan_result.setPlainText("")
            self.save_setup_btn.setEnabled(False)
            self.film_result.setPlainText("")
            self.save_profile_btn.setEnabled(False)
            self._show_views([])

    def _tab_changed(self, index: int) -> None:
        self._target_box.setVisible(index != _TAB_LINEARITY)
        self.table.setVisible(index != _TAB_LINEARITY)
        self._tolerance.setVisible(index != _TAB_LINEARITY)

    # --- scanner calibration -----------------------------------------------------------------------------------------------------------------

    def _scanner_tab(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.addWidget(_note("Photograph a calibrated transmission step tablet on your light table, in the same set-up you use for film, and open that photo. EFAS fits "
                            "v = k x 10^-D + f to each channel against the tablet's actual densities. f is the offset from flare and black-level error; f/k is the flare "
                            "fraction. This calibrates the camera as a densitometer in its own bands. It does not make a film curve, and it is not Status M."))
        run = QPushButton("Calibrate the Camera")
        run.clicked.connect(self._run_scanner)
        col.addWidget(run)
        self.scan_result = QPlainTextEdit()
        self.scan_result.setReadOnly(True)
        self.scan_result.setMinimumHeight(190)
        col.addWidget(self.scan_result)
        self.save_setup_btn = QPushButton("Save as a Camera Set-up...")
        self.save_setup_btn.setEnabled(False)
        self.save_setup_btn.clicked.connect(self._save_setup)
        col.addWidget(self.save_setup_btn)
        return w

    def _run_scanner(self) -> None:
        if not self._samples:
            QMessageBox.information(self, "Film Characterization", "Sample the patches first.")
            return
        tgt = self._target()
        info = self.c.linear_info()
        v = np.array([s.v for s in self._samples])
        used = self._used()
        order = target.order_violations(v[used].mean(axis=1), tgt.values()[used])
        lines = []
        try:
            cal = scanner.calibrate(tgt.values(), v, info.floor(), used=used)
        except scanner.CalibrationError as exc:
            self.scan_result.setPlainText(f"The calibration could not be done: {exc}")
            return
        self._calibration = {"fit": cal, "target": tgt, "used": used, "info": info}
        for ch, r in cal.items():
            lines.append(f"{ch}: gain k {r.k:.4f} +/- {r.k_se:.4f}; offset f {r.f:.5f} +/- {r.f_se:.5f}; flare fraction {r.flare_fraction * 100:.3f}% +/- {r.flare_fraction_se * 100:.3f}%")
            lines.append(f"    usable up to density {r.usable_max_density:.2f} (limited by {r.limit}); RMS density error {r.rms_density:.3f}; quality {r.quality}; {r.used} steps used")
            lines += [f"    - {x}" for x in r.reasons]
        if order:
            lines.append("Some steps do not get darker as the tablet density rises: check the patch order.")
        warnings = target.tolerance_warnings(tgt.values(), tgt.increment) if tgt.actual() else ["The tablet's nominal densities were used."]
        lines += warnings
        lines.append("Camera-band densities, calibrated against this tablet. Not Status M, and not a laboratory instrument.")
        self.scan_result.setPlainText("\n".join(lines))
        self.save_setup_btn.setEnabled(True)

    def _save_setup(self) -> None:
        if not self._calibration:
            return
        cap = capture.capture_info(self.c.state.image_path)
        vals = _ask(self, "Save camera set-up", [("Name", f"{cap['camera'] or 'Camera'} light table"), ("Camera", cap["camera"]), ("Lens", cap["lens"]),
                                                 ("Light source", ""), ("Notes", "")])
        if vals is None:
            return
        cal, info, tgt = self._calibration["fit"], self._calibration["info"], self._calibration["target"]
        g = cal["G"]
        setup = fp.new_setup(
            vals[0] or "Camera set-up", camera=vals[1], lens=vals[2], light_source=vals[3], notes=vals[4],
            settings={"iso": cap["iso"], "aperture": cap["aperture"], "shutter_s": cap["exposure_time"]},
            black=list(info.black), saturation=[info.white], noise_sigma=list(info.noise_sigma or []),
            flare_fraction=float(min(max(g.flare_fraction, 0.0), 0.999)), flare_fraction_se=float(g.flare_fraction_se),
            usable_density_max=[cal[c].usable_max_density for c in "RGB"],
            calibration={
                "target_type": "transmission step tablet scanned with the camera", "tablet": {"name": tgt.name, "densities": [float(x) for x in tgt.values()],
                "densities_are_actual": tgt.actual()}, "channels": {c: {"k": r.k, "f": r.f, "flare_fraction": r.flare_fraction, "rms_density": r.rms_density,
                "quality": r.quality, "limit": r.limit} for c, r in cal.items()}, "date": fp.now_iso()[:10],
                "linearity": self._linearity or {},
            },
        )
        if self._linearity:
            setup.linearity_error_percent = self._linearity.get("error_percent")
        self.c.setup_store().save(setup)
        self.setup_saved.emit(setup.id)
        QMessageBox.information(self, "Film Characterization", f"Saved the camera set-up '{setup.name}'.")

    # --- film characterization ---------------------------------------------------------------------------------------------------------------

    def _film_tab(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.addWidget(_note("For a developed film strip that was exposed through a step tablet (the film touching the tablet, or in a sensitometer), scanned and open here. The "
                            "tablet gives the exposure steps; the scan gives each step's density. Without known exposures these are only densities in an image, and EFAS will "
                            "not call the result a characteristic curve. Needs the film base sampled on this roll."))
        self.base_status = _note("")
        col.addWidget(self.base_status)
        self.confirm = QCheckBox("This film was exposed through this tablet, and I know the exposure steps")
        self.confirm.toggled.connect(self._clear_results)
        col.addWidget(self.confirm)
        form = QFormLayout()
        self.f_method = QComboBox()
        for m in characterize.EXPOSURE_METHODS:
            self.f_method.addItem(m)
        self.f_abs = QCheckBox("I know the exposure through the clear aperture (lux-seconds)")
        self.f_logh0 = QDoubleSpinBox()
        self.f_logh0.setRange(-8.0, 8.0)
        self.f_logh0.setDecimals(3)
        self.f_logh0.setValue(-1.0)
        self.f_logh0.setPrefix("log10 H0 = ")
        self.f_logh0.setEnabled(False)
        self.f_abs.toggled.connect(self.f_logh0.setEnabled)
        self.f_light = QLineEdit()
        self.f_proc = QLineEdit()
        self.f_stock = QLineEdit()
        self.f_process = QLineEdit("C-41")
        self.f_name = QLineEdit("Film profile")
        self.f_notes = QLineEdit()
        form.addRow("Exposure method", self.f_method)
        form.addRow(self.f_abs)
        form.addRow("", self.f_logh0)
        form.addRow("Light source", self.f_light)
        form.addRow("Processing", self.f_proc)
        form.addRow("Film stock (optional)", self.f_stock)
        form.addRow("Process (optional)", self.f_process)
        form.addRow("Profile name", self.f_name)
        form.addRow("Notes", self.f_notes)
        col.addLayout(form)
        run = QPushButton("Fit the Curves")
        run.clicked.connect(self._run_film)
        col.addWidget(run)
        self.film_result = QPlainTextEdit()
        self.film_result.setReadOnly(True)
        self.film_result.setMinimumHeight(130)
        col.addWidget(self.film_result)
        self.fit_plot, self.resid_plot, self.grad_plot = FitPlot(), ResidualPlot(), GradientPlot()
        for plot in (self.fit_plot, self.resid_plot, self.grad_plot):
            col.addWidget(plot)
        self.save_profile_btn = QPushButton("Save as a Film Profile")
        self.save_profile_btn.setEnabled(False)
        self.save_profile_btn.clicked.connect(self._save_profile)
        col.addWidget(self.save_profile_btn)
        self._refresh_base_status()
        return w

    def _refresh_base_status(self) -> None:
        if self.c.state.linear_base is None:
            self.base_status.setText("No film base has been sampled on this roll yet. Close this window and use Sample Film Base (Negative tab) on the strip's clear border.")
        else:
            self.base_status.setText("Film base sampled on this roll: it is the zero of the density above base measured here.")

    def _show_views(self, views: list) -> None:
        self.fit_plot.set_views(views, "log exposure (relative)" if not self.f_abs.isChecked() else "log exposure (lux-seconds)", "Fit the curves to see them here.")
        self.resid_plot.set_views(views)
        self.grad_plot.set_views(views)

    def _film_args(self):
        tgt = self._target()
        info = self.c.linear_info()
        return tgt, info

    def _run_film(self) -> None:
        if not self._samples:
            QMessageBox.information(self, "Film Characterization", "Sample the patches first.")
            return
        base = self.c.state.linear_base
        if base is None:
            self._refresh_base_status()
            QMessageBox.information(self, "Film Characterization", "Sample the film base on this roll first.")
            return
        tgt, info = self._film_args()
        try:
            self._film = characterize.characterize_film(
                tgt, self._samples, base[0], info.floor(), self.confirm.isChecked(), self.f_logh0.value() if self.f_abs.isChecked() else None, used=self._used()
            )
        except characterize.CharacterizationError as exc:
            self.film_result.setPlainText(str(exc))
            self._show_views([])
            self.save_profile_btn.setEnabled(False)
            return
        except Exception as exc:
            self.film_result.setPlainText(f"The curves could not be fitted: {exc}")
            return
        self._profile = self._make_profile()
        views = [view_model.channel_view(ch, self._profile.curves[ch]) for ch in "RGB"]
        self._show_views(views)
        lines = [f"Exposure scale: {self._film.scale}."]
        for v in views:
            lines.append(f"{v.channel}: " + view_model.quality_text(v))
            if v.gamma is not None:
                lines.append(f"    gamma {v.gamma:.2f} over log exposure {v.gamma_interval[0]:.2f} to {v.gamma_interval[1]:.2f}; measured range {v.support[0]:.2f} to {v.support[1]:.2f}")
        lines += list(self._film.warnings)
        g = view_model.guidance_for(self._profile)
        if g is not None:
            lines += [g.shadow, g.midtone, g.highlight, g.note]
        lines.append("Camera-band densities. A curve describes this roll, exposure and processing.")
        self.film_result.setPlainText("\n".join(lines))
        self.save_profile_btn.setEnabled(True)

    def _make_profile(self):
        tgt, info = self._film_args()
        cap = capture.capture_info(self.c.state.image_path)
        scan = dict(cap)
        scan.update({"black": list(info.black), "saturation": info.white, "bit_depth": info.bit_depth, "encoding": info.encoding})
        exposure = {"method": self.f_method.currentText(), "absolute": self.f_abs.isChecked(), "log_h0": self.f_logh0.value() if self.f_abs.isChecked() else None}
        return characterize.build_profile(
            self.f_name.text().strip() or "Film profile", self._film, self.c.state.linear_base[0], tgt, film_stock=self.f_stock.text().strip(),
            process=self.f_process.text().strip(), notes=self.f_notes.text().strip(), exposure=exposure, processing=self.f_proc.text().strip(), scan=scan,
            light_source=self.f_light.text().strip(),
        )

    def _save_profile(self) -> None:
        if self._film is None:
            return
        self._profile = self._make_profile()
        try:
            self.c.profile_store().save(self._profile)
        except (OSError, fp.ProfileError) as exc:
            QMessageBox.warning(self, "Film Characterization", f"The profile could not be saved: {exc}")
            return
        self.profile_saved.emit(self._profile.id)
        QMessageBox.information(self, "Film Characterization", f"Saved the film profile '{self._profile.name}'.")

    # --- linearity ----------------------------------------------------------------------------------------------------------------------------

    def _linearity_tab(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.addWidget(_note("Take several RAW photos of the same evenly lit, static backlit area (no film), changing only the exposure time, with some frames between 5% and 95% of "
                            "full scale. EFAS reads the centre of each frame and fits signal against exposure time. A steady, flicker-free light is assumed; a pulsing LED backlight "
                            "will show up as non-linearity that is not the camera's."))
        add = QPushButton("Add RAW Files...")
        add.clicked.connect(self._add_linearity_files)
        col.addWidget(add)
        self.lin_table = QTableWidget(0, 6)
        self.lin_table.setHorizontalHeaderLabels(["File", "Time (s)", "R", "G", "B", "Clipped"])
        self.lin_table.horizontalHeader().setStretchLastSection(True)
        self.lin_table.setMinimumHeight(150)
        col.addWidget(self.lin_table)
        run = QPushButton("Run the Linearity Test")
        run.clicked.connect(self._run_linearity)
        col.addWidget(run)
        self.lin_result = QPlainTextEdit()
        self.lin_result.setReadOnly(True)
        self.lin_result.setMinimumHeight(120)
        col.addWidget(self.lin_result)
        return w

    def _add_linearity_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Exposure series (RAW)", "", "RAW files (*.cr2 *.cr3 *.nef *.arw *.dng *.raf *.orf *.rw2 *.pef);;All files (*)")
        for path in paths:
            try:
                reading = capture.region_reading(path)
                info = capture.capture_info(path)
            except Exception as exc:
                QMessageBox.warning(self, "Film Characterization", f"{os.path.basename(path)} could not be read: {exc}")
                continue
            self._lin_rows.append({"path": path, "time": info["exposure_time"], "median": reading["median"], "clipped": reading["clipped"]})
        self._fill_linearity()

    def _fill_linearity(self) -> None:
        self.lin_table.blockSignals(True)
        self.lin_table.setRowCount(len(self._lin_rows))
        for i, r in enumerate(self._lin_rows):
            self.lin_table.setItem(i, 0, QTableWidgetItem(os.path.basename(r["path"])))
            t = QTableWidgetItem("" if r["time"] is None else f"{r['time']:g}")
            self.lin_table.setItem(i, 1, t)
            for c in range(3):
                self.lin_table.setItem(i, 2 + c, QTableWidgetItem(f"{r['median'][c]:.5f}"))
            self.lin_table.setItem(i, 5, QTableWidgetItem(f"{r['clipped'] * 100:.1f}%"))
            for col in (0, 2, 3, 4, 5):
                self.lin_table.item(i, col).setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.lin_table.blockSignals(False)

    def _run_linearity(self) -> None:
        times = []
        for i in range(self.lin_table.rowCount()):
            try:
                times.append(float(self.lin_table.item(i, 1).text()))
            except (ValueError, AttributeError):
                self.lin_result.setPlainText(f"Row {i + 1} has no exposure time. Type it in the Time column.")
                return
        lines = []
        out = {}
        for c, ch in enumerate("RGB"):
            sig = [r["median"][c] for r in self._lin_rows]
            try:
                res = scanner.linearity_error(times, sig)
            except scanner.CalibrationError as exc:
                lines.append(f"{ch}: {exc}")
                continue
            out[ch] = res
            lines.append(f"{ch}: linearity error {res.error_percent:.2f}% (largest + {res.max_positive_percent:.2f}%, largest {res.max_negative_percent:.2f}%), {res.used} frames used, "
                         f"{res.range_fraction[0] * 100:.0f}% to {res.range_fraction[1] * 100:.0f}% of saturation: {res.verdict}")
        if out:
            g = out.get("G") or next(iter(out.values()))
            self._linearity = {"error_percent": g.error_percent, "verdict": g.verdict, "frames": g.used, "date": fp.now_iso()[:10]}
            lines.append("EFAS's own statistic (after EMVA 1288); the standard's exact normalisation was not verified.")
        self.lin_result.setPlainText("\n".join(lines))
