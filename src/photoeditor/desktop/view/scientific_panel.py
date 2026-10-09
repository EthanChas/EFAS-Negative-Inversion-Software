"""Advanced Mode: the scientific panels (density, density histogram, sensitometry, calibration). They only read what the measurement engine
produced, so Simple and Advanced Mode are two views of one set of numbers (docs/scientific-inversion-design.md)."""

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ...features.densitometry import analysis, hd, profiles
from ...features.densitometry.histogram import DensityHistogram
from ...features.densitometry.linear import TRANSFER_LABELS, TRANSFERS
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel

_CHANNELS = (("R", THEME.channel_red), ("G", THEME.channel_green), ("B", THEME.channel_blue))
_LOG10_2 = 0.30103


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    return label


class _Plot(QWidget):
    """A plain plotting area: a margin for axis labels and a mapping from data to pixels."""

    LEFT, RIGHT, TOP, BOTTOM = 34, 8, 8, 34

    def __init__(self, height: int = 150, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(height)
        self._x = (0.0, 1.0)
        self._y = (0.0, 1.0)

    def _area(self) -> QRectF:
        return QRectF(self.LEFT, self.TOP, max(10, self.width() - self.LEFT - self.RIGHT), max(10, self.height() - self.TOP - self.BOTTOM))

    def _px(self, x: float, y: float) -> QPointF:
        a = self._area()
        fx = (x - self._x[0]) / max(self._x[1] - self._x[0], 1e-9)
        fy = (y - self._y[0]) / max(self._y[1] - self._y[0], 1e-9)
        return QPointF(a.left() + fx * a.width(), a.bottom() - fy * a.height())

    def _frame(self, p: QPainter, x_label: str, step_x: float, step_y: float) -> None:
        p.fillRect(self.rect(), QColor(THEME.bg_input))
        a = self._area()
        grid, text = QColor(THEME.border_color), QColor(THEME.text_muted)
        grid.setAlpha(255)
        p.setFont(QFont(THEME.font_family, 7))
        v = np.ceil(self._x[0] / step_x) * step_x
        while v <= self._x[1] + 1e-9:
            pt = self._px(v, self._y[0])
            p.setPen(QPen(QColor("#2a2a2a")))
            p.drawLine(QPointF(pt.x(), a.top()), QPointF(pt.x(), a.bottom()))
            p.setPen(text)
            p.drawText(QRectF(pt.x() - 18, a.bottom() + 2, 36, 14), Qt.AlignmentFlag.AlignCenter, f"{v:g}")
            v += step_x
        v = np.ceil(self._y[0] / step_y) * step_y
        while v <= self._y[1] + 1e-9:
            pt = self._px(self._x[0], v)
            p.setPen(QPen(QColor("#2a2a2a")))
            p.drawLine(QPointF(a.left(), pt.y()), QPointF(a.right(), pt.y()))
            p.setPen(text)
            p.drawText(QRectF(0, pt.y() - 7, self.LEFT - 4, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{v:g}")
            v += step_y
        p.setPen(QPen(grid))
        p.drawRect(a)
        p.setPen(text)
        p.drawText(QRectF(a.left(), a.bottom() + 16, a.width(), 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, x_label)


class DensityHistogramPlot(_Plot):
    """Per-channel histograms in density units, with the film-base and Dmax positions marked."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(150, parent)
        self._hist: DensityHistogram | None = None
        self._marks: list[tuple[float, str, QColor]] = []
        self._caption = "Nothing measured yet"

    def set_data(self, hist: DensityHistogram | None, marks: list[tuple[float, str, str]], caption: str) -> None:
        self._hist = hist
        self._marks = [(x, label, QColor(color)) for x, label, color in marks]
        self._caption = caption
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._hist
        if h is None or h.total == 0:
            self._x, self._y = (0.0, 4.0), (0.0, 1.0)
            self._frame(p, "density", 0.5, 0.5)
            p.setPen(QColor(THEME.text_muted))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._caption)
            return
        centres = h.centres()
        occupied = np.where(h.counts.max(axis=0) > 0)[0]
        lo = float(centres[occupied[0]]) if occupied.size else float(centres[0])
        hi = float(centres[occupied[-1]]) if occupied.size else float(centres[-1])
        for x, _label, _c in self._marks:
            lo, hi = min(lo, x), max(hi, x)
        lo, hi = lo - 0.15, max(hi + 0.15, lo + 1.0)
        kernel = np.ones(5) / 5.0
        smooth = np.stack([np.convolve(h.counts[c], kernel, mode="same") for c in range(3)])
        top = float(smooth.max()) or 1.0
        self._x, self._y = (round(lo, 2), round(hi, 2)), (0.0, 1.05)
        self._frame(p, self._caption, 0.5 if hi - lo > 2 else 0.25, 2.0)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        for c, (_name, colour) in enumerate(_CHANNELS):
            poly = QPolygonF([self._px(lo, 0.0)])
            for i, x in enumerate(centres):
                if lo <= x <= hi:
                    poly.append(self._px(float(x), float(smooth[c][i] / top)))
            poly.append(self._px(hi, 0.0))
            fill = QColor(colour)
            fill.setAlpha(70)
            p.setBrush(QBrush(fill))
            p.setPen(QPen(QColor(colour), 1.2))
            p.drawPolygon(poly)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        a = self._area()
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, (x, label, colour) in enumerate(self._marks):
            pen = QPen(colour, 1.0, Qt.PenStyle.DashLine)
            p.setPen(pen)
            pt = self._px(x, 0.0)
            p.drawLine(QPointF(pt.x(), a.top()), QPointF(pt.x(), a.bottom()))
            left_side = pt.x() > a.right() - 60
            p.drawText(QPointF(pt.x() - 58 if left_side else pt.x() + 2, a.top() + 9 + 10 * (i % 4)), label)


class SensitometryPlot(_Plot):
    """The H&D viewer: density against log exposure for curve data the user supplied and/or the model, with the photograph's density band."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(190, parent)
        self._curves: list[tuple[np.ndarray, np.ndarray, QColor, bool]] = []
        self._band: tuple[float, float] | None = None
        self._empty = "No curve to show"

    def set_data(self, curves, band, empty_text: str) -> None:
        self._curves, self._band, self._empty = curves, band, empty_text
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._curves:
            self._x, self._y = (-4.0, 1.0), (0.0, 4.0)
            self._frame(p, "log exposure (lux-seconds)", 1.0, 1.0)
            p.setPen(QColor(THEME.text_muted))
            p.drawText(self.rect().adjusted(40, 0, -10, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._empty)
            return
        xs = np.concatenate([c[0] for c in self._curves])
        ys = np.concatenate([c[1].ravel() for c in self._curves])
        self._x = (float(np.floor(xs.min())), float(np.ceil(xs.max())))
        self._y = (0.0, float(max(2.0, np.ceil(ys.max() * 2) / 2 + 0.5)))
        self._frame(p, "log exposure (lux-seconds)", 1.0, 0.5)
        a = self._area()
        if self._band is not None:
            top, bottom = self._px(self._x[0], self._band[1]), self._px(self._x[0], self._band[0])
            p.fillRect(QRectF(a.left(), top.y(), a.width(), bottom.y() - top.y()), QColor(255, 255, 255, 28))
        for x, d, colour, dashed in self._curves:
            pen = QPen(colour, 1.6, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine)
            p.setPen(pen)
            cols = d.reshape(len(x), -1)
            for c in range(cols.shape[1]):
                pen.setColor(QColor(_CHANNELS[c][1]) if cols.shape[1] == 3 and not dashed else colour)
                p.setPen(pen)
                poly = QPolygonF([self._px(float(a_), float(b_)) for a_, b_ in zip(x, cols[:, c])])
                p.drawPolyline(poly)


class AdvancedPanels(QWidget):
    """The four expandable scientific panels. Hidden until Advanced Mode is switched on."""

    probe_toggled = pyqtSignal(bool)
    clear_pick_toggled = pyqtSignal(bool)
    clear_ref_cleared = pyqtSignal()
    transfer_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._measurement = None
        self._curve: profiles.CurveSet | None = None
        self._model = hd.ModelCurve()
        self._probe_text = "Turn on Probe, then hover the raw scan."
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(THEME.space_sm)
        col.addWidget(self._density_panel())
        col.addWidget(self._histogram_panel())
        col.addWidget(self._sensitometry_panel())
        col.addWidget(self._calibration_panel())
        self.set_measurement(None, "", False, False)

    # --- Density -------------------------------------------------------------------------------------------------------------------------

    def _density_panel(self) -> CollapsiblePanel:
        panel = CollapsiblePanel(
            "Density", collapsible=True, start_expanded=True,
            help_text=("Optical density is the logarithm of how much light the film stops: 0 passes everything, 1 passes a tenth, 2 a hundredth. "
                       "Values here come from the linear RAW data, not from the picture you see on screen. Dmin is the film base (sample it with Sample "
                       "Film Base), Dmax is the densest part of the picture. 'Above base' means measured from the film base, which does not depend on "
                       "your backlight or exposure."),
        )
        body = panel.body()
        self._status = _hint("")
        body.addWidget(self._status)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(THEME.space_sm)
        self._grid.setVerticalSpacing(2)
        body.addLayout(self._grid)
        body.addWidget(_hint("Camera-band densities, not ISO Status M. Hover a row for what it means."))
        self._probe_btn = QPushButton("Probe Density")
        self._probe_btn.setCheckable(True)
        self._probe_btn.setToolTip("Show the raw scan and read the density under the cursor.")
        self._probe_btn.toggled.connect(self.probe_toggled)
        body.addWidget(self._probe_btn)
        self._probe_label = _hint(self._probe_text)
        body.addWidget(self._probe_label)
        clear_row = QHBoxLayout()
        self._clear_btn = QPushButton("Sample Clear Light")
        self._clear_btn.setCheckable(True)
        self._clear_btn.setToolTip("Click a spot with no film in it (the bare backlight), shot with the same exposure. This lets EFAS report absolute density.")
        self._clear_btn.toggled.connect(self.clear_pick_toggled)
        clear_row.addWidget(self._clear_btn, 1)
        self._clear_x = QPushButton("Clear")
        self._clear_x.clicked.connect(self.clear_ref_cleared)
        clear_row.addWidget(self._clear_x)
        body.addLayout(clear_row)
        self._density = panel
        return panel

    def set_probe_active(self, active: bool) -> None:
        self._probe_btn.blockSignals(True)
        self._probe_btn.setChecked(active)
        self._probe_btn.blockSignals(False)

    def set_clear_pick_active(self, active: bool) -> None:
        self._clear_btn.blockSignals(True)
        self._clear_btn.setChecked(active)
        self._clear_btn.blockSignals(False)

    def set_probe(self, reading: dict | None) -> None:
        if reading is None:
            self._probe_label.setText(self._probe_text)
            return
        def triple(values, digits=3):
            return "   ".join(f"{n} {v:.{digits}f}" for n, v in zip("RGB", values))
        lines = [f"Above base:  {triple(reading['above_base'])}", f"Relative to base (T):  {triple(reading['t_rel'])}", f"Camera-relative density:  {triple(reading['relative'])}"]
        if "absolute" in reading:
            lines.append(f"Absolute density:  {triple(reading['absolute'])}")
        self._probe_label.setText("\n".join(lines))

    # --- Density histogram ---------------------------------------------------------------------------------------------------------------

    def _histogram_panel(self) -> CollapsiblePanel:
        panel = CollapsiblePanel(
            "Density Histogram", collapsible=True, start_expanded=False,
            help_text=("How much of the negative sits at each density, per colour. This is the negative's density, not the brightness of the finished "
                       "positive: the thinnest parts of the negative (shadows of the scene) are at the left and the densest (highlights) at the right. "
                       "The dashed lines mark the film base (Dmin) and the densest part measured (Dmax)."),
        )
        body = panel.body()
        row = QHBoxLayout()
        self._hist_mode = QComboBox()
        self._hist_mode.addItem("Density above film base", "net")
        self._hist_mode.addItem("Camera-relative density", "rel")
        self._hist_mode.currentIndexChanged.connect(self._draw_histogram)
        row.addWidget(self._hist_mode, 1)
        body.addLayout(row)
        self._hist_plot = DensityHistogramPlot()
        body.addWidget(self._hist_plot)
        self._hist_note = _hint("")
        body.addWidget(self._hist_note)
        return panel

    def _draw_histogram(self, *_args) -> None:
        m = self._measurement
        if m is None:
            self._hist_plot.set_data(None, [], "Sample the film base and open a photo to see its density histogram.")
            self._hist_note.setText("")
            return
        net = self._hist_mode.currentData() == "net"
        if net:
            marks = [(0.0, "Dmin", "#d8d8d8")] + [(m.dmax.value[i], f"Dmax {_CHANNELS[i][0]}", _CHANNELS[i][1]) for i in range(3)]
            self._hist_plot.set_data(m.net_hist, marks, "density above the film base")
            self._hist_note.setText("Density above the film base: 0 is the film base itself. Independent of backlight level and exposure.")
        else:
            marks = [(m.dmin_rel[i], f"Dmin {_CHANNELS[i][0]}", _CHANNELS[i][1]) for i in range(3)]
            self._hist_plot.set_data(m.rel_hist, marks, "camera-relative density, -log10(sensor value)")
            self._hist_note.setText("Camera-relative density includes your backlight and exposure level, so the three channels start at different places.")

    # --- Sensitometry (H&D) --------------------------------------------------------------------------------------------------------------

    def _sensitometry_panel(self) -> CollapsiblePanel:
        panel = CollapsiblePanel(
            "Sensitometry (H&D)", collapsible=True, start_expanded=False,
            help_text=("The Hurter-Driffield (characteristic) curve plots a film's density against the logarithm of the exposure it received. It rises from "
                       "the film base (Dmin), bends through the toe, runs along a straight line whose slope is the gamma, bends again at the shoulder "
                       "and levels off at the maximum density (Dmax).\n\nA photograph records densities but not the exposures behind them, so EFAS "
                       "cannot draw this curve from your picture. Load measured or published curve data (for example from a step tablet scan), or "
                       "show the model curve to see how the parts of the curve fit together. The shaded band shows which densities your picture "
                       "uses."),
        )
        body = panel.body()
        self._curve_banner = QLabel("")
        self._curve_banner.setWordWrap(True)
        body.addWidget(self._curve_banner)
        self._hd_plot = SensitometryPlot()
        body.addWidget(self._hd_plot)
        row = QHBoxLayout()
        load = QPushButton("Load Curve Data...")
        load.setToolTip("A .json or .csv file of log exposure against R, G, B density. See docs/scientific-inversion-design.md for the format.")
        load.clicked.connect(self._load_curve)
        row.addWidget(load, 1)
        drop = QPushButton("Remove")
        drop.clicked.connect(self._remove_curve)
        row.addWidget(drop)
        body.addLayout(row)
        self._show_model = QCheckBox("Show model curve (not measured)")
        self._show_model.toggled.connect(self._model_toggled)
        body.addWidget(self._show_model)
        self._model_box = QWidget()
        form = QFormLayout(self._model_box)
        form.setContentsMargins(0, 0, 0, 0)
        self._model_spins: dict[str, QDoubleSpinBox] = {}
        for key, label, lo, hi, step in (("dmin", "Dmin", 0.0, 1.5, 0.05), ("dmax", "Dmax", 1.0, 5.0, 0.1), ("gamma", "Gamma", 0.2, 3.0, 0.05),
                                         ("toe_sharpness", "Toe sharpness", 1.0, 100.0, 1.0), ("shoulder_sharpness", "Shoulder sharpness", 1.0, 100.0, 1.0)):
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setSingleStep(step)
            spin.setDecimals(2)
            spin.setValue(getattr(self._model, key))
            spin.valueChanged.connect(self._model_changed)
            self._model_spins[key] = spin
            form.addRow(label, spin)
        self._model_box.hide()
        body.addWidget(self._model_box)
        self._hd_readout = _hint("")
        body.addWidget(self._hd_readout)
        return panel

    def _load_curve(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load curve data", "", "Curve data (*.json *.csv)")
        if not path:
            return
        try:
            self._curve = profiles.load_curve_file(path)
        except profiles.ProfileError as exc:
            QMessageBox.warning(self, "Curve data", str(exc))
            return
        self._draw_hd()

    def _remove_curve(self) -> None:
        self._curve = None
        self._draw_hd()

    def _model_toggled(self, on: bool) -> None:
        self._model_box.setVisible(on)
        self._draw_hd()

    def _model_changed(self, *_args) -> None:
        v = {k: s.value() for k, s in self._model_spins.items()}
        if v["dmax"] <= v["dmin"] + 0.2:
            v["dmax"] = v["dmin"] + 0.2
        mid = (v["dmin"] + v["dmax"]) / 2.0
        self._model = hd.ModelCurve(v["dmin"], v["dmax"], v["gamma"], x0=-1.5, d0=mid, toe_sharpness=v["toe_sharpness"], shoulder_sharpness=v["shoulder_sharpness"])
        self._draw_hd()

    def _draw_hd(self) -> None:
        curves, readout = [], []
        banner = ("No curve loaded. EFAS never draws an H&D curve from a photograph, because a photograph does not record the exposures that made "
                  "it. Load measured or published curve data, or show the model.")
        colour = THEME.text_muted
        base_dmin = None
        reference = None
        if self._curve is not None:
            c = self._curve
            curves.append((c.log_exposure, c.density, QColor("#ffffff"), False))
            banner = f"{profiles.KIND_LABELS[c.kind]}: {c.name}" + (f" - {c.source}" if c.source else "") + (f" - {c.densitometry}" if c.densitometry else "")
            colour = THEME.accent_hover if c.is_measured() else THEME.status_warning
            channel = 1 if c.channels() == 3 else 0
            a = hd.analyse_curve(c.log_exposure, c.density[:, channel])
            base_dmin, reference = a.dmin, (c.log_exposure, c.density[:, channel])
            readout.append(self._analysis_text(a, "G" if c.channels() == 3 else "grey"))
        if self._show_model.isChecked():
            x, d = hd.sample(self._model)
            curves.append((x, d, QColor("#e0b040"), True))
            if self._curve is None:
                banner = "MODEL CURVE: illustrative only, not measured from your film."
                colour = THEME.status_warning
                a = hd.analyse_curve(x, d)
                base_dmin, reference = self._model.dmin, (x, d)
                readout.append(self._analysis_text(a, "model"))
        self._curve_banner.setText(banner)
        self._curve_banner.setStyleSheet(f"color: {colour};")
        band = None
        m = self._measurement
        if m is not None and base_dmin is not None and reference is not None:
            top = float(np.mean(m.density_range()))
            band = (base_dmin, base_dmin + top)
            lo = hd.log_exposure_at(reference[0], reference[1], band[0] + hd.DEFAULT_GRADIENT_TOE_OFFSET)
            hi = hd.log_exposure_at(reference[0], reference[1], band[1])
            if np.isfinite(lo) and np.isfinite(hi):
                readout.append(f"This picture's density range ({top:.2f} above base) implies a log-exposure range of {hi - lo:.2f} "
                               f"(about {(hi - lo) / _LOG10_2:.1f} stops) on this curve, counted from 0.10 above the film base, since a curve only reaches its base asymptotically. "
                               "This assumes the curve describes your film, exposure and development.")
            else:
                readout.append("The picture's density range runs past the end of this curve, so no exposure range is implied.")
        empty = "Load curve data or show the model curve to see an H&D plot."
        self._hd_plot.set_data(curves, band, empty)
        self._hd_readout.setText("\n".join(readout))

    @staticmethod
    def _analysis_text(a: hd.CurveAnalysis, label: str) -> str:
        gamma = f"gamma {a.gamma:.2f}" if a.gamma is not None else "no clear straight-line portion"
        avg = f"average gradient {a.average_gradient:.2f} (Dmin + 0.10 to +1.30 log E)" if a.average_gradient is not None else "average gradient out of range"
        return f"{label}: Dmin {a.dmin:.2f}, Dmax {a.dmax:.2f}, {gamma}, {avg}."

    # --- Calibration and diagnostics -----------------------------------------------------------------------------------------------------

    def _calibration_panel(self) -> CollapsiblePanel:
        panel = CollapsiblePanel(
            "Calibration and Diagnostics", collapsible=True, start_expanded=False,
            help_text=("Exactly how the numbers were obtained: how the RAW data was normalised, what is assumed, and what could make a value "
                       "unreliable. Nothing here changes your picture."),
        )
        body = panel.body()
        self._calib_text = QLabel("")
        self._calib_text.setWordWrap(True)
        self._calib_text.setTextFormat(Qt.TextFormat.RichText)
        body.addWidget(self._calib_text)
        row = QHBoxLayout()
        self._transfer_label = QLabel("Picture encoding (non-RAW)")
        row.addWidget(self._transfer_label)
        self._transfer = QComboBox()
        for key in TRANSFERS:
            self._transfer.addItem(TRANSFER_LABELS[key], key)
        self._transfer.currentIndexChanged.connect(lambda _i: self.transfer_changed.emit(self._transfer.currentData()))
        row.addWidget(self._transfer, 1)
        body.addLayout(row)
        return panel

    def set_transfer(self, key: str) -> None:
        self._transfer.blockSignals(True)
        self._transfer.setCurrentIndex(max(0, self._transfer.findData(key)))
        self._transfer.blockSignals(False)

    def _draw_calibration(self, error: str) -> None:
        m = self._measurement
        if m is None:
            self._calib_text.setText(f"<p style='color:{THEME.status_warning}'>{error}</p>" if error else "<p>Nothing measured yet.</p>")
            return
        info = m.info
        html = ["<p><b>How the values were obtained</b></p><ul>"]
        html += [f"<li>{s}</li>" for s in info.steps]
        html.append("</ul>")
        if info.measured and info.black:
            html.append(f"<p>Black level {', '.join(f'{b:.0f}' for b in info.black)}; saturation {info.white:.0f}; {info.bit_depth}-bit; "
                        f"clipped pixels {info.saturated_fraction * 100:.2f}%.</p>")
        html.append("<p><b>Assumptions</b></p><ul>" + "".join(f"<li>{a}</li>" for a in analysis.assumptions(m)) + "</ul>")
        html.append("<p><b>Diagnostics</b></p><ul>")
        for d in m.diagnostics:
            tag = "Warning" if d.level == "warning" else "Note"
            colour = THEME.status_warning if d.level == "warning" else THEME.text_muted
            html.append(f"<li><span style='color:{colour}'>{tag}:</span> {d.text}</li>")
        html.append("</ul>")
        html.append(f"<p><b>Confidence in these numbers:</b> {m.confidence}</p>")
        html.append("<p><b>Inversion model (current)</b></p><p>Turning the negative into a positive still uses the existing method, unchanged: it works on "
                    "the displayed picture and stretches each colour between a low and a high density (or your sampled film base) to black and white. "
                    "It does not yet use the measurements on this page. Routing the inversion through them is planned for the next tier.</p>")
        self._calib_text.setText("".join(html))

    # --- feeding it ----------------------------------------------------------------------------------------------------------------------

    def set_measurement(self, m, error: str, busy: bool, has_photo: bool) -> None:
        self._measurement = m
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if m is None:
            if error:
                text = error
            elif busy:
                text = "Reading the RAW data for measurement..."
            elif not has_photo:
                text = "Open a photo to measure it."
            else:
                text = "Sample the film base to measure this negative."
            self._status.setText(text)
        else:
            tip_estimated = " Sample the film base (Sample Film Base) to measure it." if not m.base.measured else ""
            self._status.setText(f"Confidence: {m.confidence}. {'Film base estimated.' + tip_estimated if not m.base.measured else 'Film base measured on this roll.'}")
            for c, (name, colour) in enumerate(_CHANNELS):
                head = QLabel(name)
                head.setStyleSheet(f"color: {colour}; font-weight: bold;")
                head.setAlignment(Qt.AlignmentFlag.AlignRight)
                self._grid.addWidget(head, 0, c + 1)
            for r, row in enumerate(analysis.summary_rows(m), start=1):
                label = QLabel(row.label)
                label.setToolTip(row.tip)
                self._grid.addWidget(label, r, 0)
                for c, value in enumerate(row.values):
                    cell = QLabel(value)
                    cell.setAlignment(Qt.AlignmentFlag.AlignRight)
                    cell.setToolTip(row.tip)
                    self._grid.addWidget(cell, r, c + 1)
                status = QLabel(row.status)
                status.setProperty("role", "hint")
                status.setToolTip(row.tip)
                self._grid.addWidget(status, r, 4)
        self._draw_histogram()
        self._draw_hd()
        self._draw_calibration(error)
