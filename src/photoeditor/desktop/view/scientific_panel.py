"""Advanced Mode: the scientific panels (density, density histogram, sensitometry, calibration). They only read what the measurement engine
produced, so Simple and Advanced Mode are two views of one set of numbers (docs/scientific-inversion-design.md)."""

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ...features.densitometry import analysis, film_profile, fit, hd, profiles, view_model
from ...features.densitometry import diagnostics as diagnostics_mod
from ...features.densitometry.histogram import DensityHistogram
from ...features.densitometry.linear import TRANSFER_LABELS, TRANSFERS
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .fit_plots import FitPlot, GradientPlot, ResidualPlot
from .plot_base import _Plot

_CHANNELS = (("R", THEME.channel_red), ("G", THEME.channel_green), ("B", THEME.channel_blue))
_LOG10_2 = 0.30103


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    return label


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


class AdvancedPanels(QWidget):
    """The four expandable scientific panels. Hidden until Advanced Mode is switched on."""

    probe_toggled = pyqtSignal(bool)
    clear_pick_toggled = pyqtSignal(bool)
    clear_ref_cleared = pyqtSignal()
    transfer_changed = pyqtSignal(str)
    characterize_requested = pyqtSignal()
    profiles_requested = pyqtSignal()
    setups_requested = pyqtSignal()
    profile_chosen = pyqtSignal(str)
    profile_imported = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._measurement = None
        self._profile = None
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
                       "the film base, bends through the toe, runs along a straight line whose slope is the gamma, bends again at the shoulder and "
                       "levels off at the maximum density.\n\nA photograph records densities but not the exposures behind them, so EFAS cannot draw "
                       "this curve from your picture. A curve here comes from a film profile: one you measured with Film Characterization (a strip "
                       "exposed through a step tablet), or one you supplied. Points are the measurements with their uncertainty, the line is the fit, "
                       "the lighter band its 95% range, and the shaded zones at the sides are beyond what was measured. The strip below shows what the "
                       "fit missed, and the lower plot the gradient (the film's contrast) along the curve."),
        )
        body = panel.body()
        self._profile_combo = QComboBox()
        self._profile_combo.currentIndexChanged.connect(self._profile_picked)
        body.addWidget(self._profile_combo)
        characterize = QPushButton("Film Characterization...")
        characterize.setToolTip("Calibrate the camera with a step tablet, fit a film's curves from an exposed strip, or test the sensor's linearity.")
        characterize.clicked.connect(self.characterize_requested)
        body.addWidget(characterize)
        manage = QPushButton("Film Profiles...")
        manage.setToolTip("List, duplicate, edit, import, export, compare and apply film profiles.")
        manage.clicked.connect(self.profiles_requested)
        body.addWidget(manage)
        self._curve_banner = QLabel("")
        self._curve_banner.setWordWrap(True)
        body.addWidget(self._curve_banner)
        self._fit_plot = FitPlot()
        self._resid_plot = ResidualPlot()
        self._grad_plot = GradientPlot()
        body.addWidget(self._fit_plot)
        body.addWidget(self._resid_plot)
        body.addWidget(self._grad_plot)
        load = QPushButton("Import Curve File...")
        load.setToolTip("A .json or .csv file of log exposure against R, G, B density. It becomes a 'supplied' profile, which EFAS does not verify.")
        load.clicked.connect(self._load_curve)
        body.addWidget(load)
        self._show_model = QCheckBox("Show a model curve")
        self._show_model.setToolTip("An illustrative curve, not measured from any film.")
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

    def set_profiles(self, rows: list[dict], selected: str = "") -> None:
        """The film profiles on offer in the viewer (name, film, kind), with the one to show chosen."""
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        self._profile_combo.addItem("No profile", "")
        for r in rows:
            self._profile_combo.addItem(f"{r['name']} ({r['film']})", r["id"])
        self._profile_combo.setCurrentIndex(max(0, self._profile_combo.findData(selected)))
        self._profile_combo.blockSignals(False)

    def set_profile(self, profile) -> None:
        self._profile = profile
        self._draw_hd()

    def _profile_picked(self, _index: int) -> None:
        self.profile_chosen.emit(self._profile_combo.currentData() or "")

    def _load_curve(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import curve data", "", "Curve data (*.json *.csv)")
        if not path:
            return
        try:
            profile = film_profile.from_curve_set(profiles.load_curve_file(path))
        except (profiles.ProfileError, fit.FitError, film_profile.ProfileError) as exc:
            QMessageBox.warning(self, "Curve data", str(exc))
            return
        self.profile_imported.emit(profile)

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

    def _model_curve(self):
        m = self._model
        return fit.SoftplusCurve(gamma=m.gamma, x0=m.x0, dmax=max(m.dmax - m.dmin, 0.2), toe=m.toe_sharpness, shoulder=m.shoulder_sharpness)

    def _draw_hd(self) -> None:
        views: list = []
        readout: list[str] = []
        banner = ("No film profile selected. EFAS never draws an H&D curve from a photograph, because a photograph does not record the exposures that made "
                  "it. Choose a profile, make one with Film Characterization, or show the model.")
        colour = THEME.text_muted
        label = "log exposure"
        p = self._profile
        if p is not None:
            try:
                views = [view_model.channel_view(ch, p.curves[ch]) for ch in ("R", "G", "B", "K") if ch in p.curves]
            except (film_profile.ProfileError, fit.FitError, ValueError) as exc:
                views = []
                banner = f"This profile's curves could not be drawn: {exc}"
            else:
                banner = f"{film_profile.KIND_LABELS[p.kind]}: {p.name} ({p.identity_text()})"
                colour = THEME.accent_hover if p.kind == "measured" else THEME.status_warning
                scales = {cc.scale for cc in p.curves.values()}
                label = "log exposure (lux-seconds)" if scales == {"absolute"} else "log exposure (relative)"
                for v in views:
                    readout.append(f"{v.channel}: " + view_model.quality_text(v))
                    if v.gamma is not None:
                        readout.append(f"    gradient peaks at {v.gamma:.2f} (gamma), log exposure {v.gamma_interval[0]:.2f} to {v.gamma_interval[1]:.2f}; measured range "
                                       f"{v.support[0]:.2f} to {v.support[1]:.2f}")
                    if v.average is not None:
                        a = v.average
                        readout.append(f"    average gradient {a['gradient']:.2f} over log exposure {a['interval'][0]:.2f} to {a['interval'][1]:.2f} (the middle of the measured range)")
                    iso = v.iso6
                    if iso.get("available") and p.kind in ("measured", "supplied") and len(views) == 1:
                        readout.append(f"    ISO 6 geometry (black-and-white negatives only): density rise {iso['rise']:.2f} over 1.30 log H (the criterion is 0.80)")
                g = view_model.guidance_for(p)
                if g is not None:
                    readout += [g.shadow, g.midtone, g.highlight, g.note]
        elif self._show_model.isChecked():
            views = [view_model.model_view(self._model_curve())]
            banner = "MODEL CURVE: illustrative only, not measured from your film."
            colour = THEME.status_warning
            readout.append(f"model: gamma about {views[0].gamma:.2f}." if views[0].gamma else "model")
        self._curve_banner.setText(banner)
        self._curve_banner.setStyleSheet(f"color: {colour};")
        band = None
        m = self._measurement
        if m is not None and views:
            top = float(np.mean(m.density_range()))
            band = (0.0, top)
            ref = next((v for v in views if v.channel in ("G", "K")), views[0])
            lo = hd.log_exposure_at(ref.grid, ref.curve, hd.DEFAULT_GRADIENT_TOE_OFFSET)
            hi = hd.log_exposure_at(ref.grid, ref.curve, top)
            if np.isfinite(lo) and np.isfinite(hi):
                beyond = hi > ref.support[1] or lo < ref.support[0]
                readout.append(f"This picture's density range ({top:.2f} above base) implies a log-exposure range of {hi - lo:.2f} (about {(hi - lo) / _LOG10_2:.1f} stops) on this curve, "
                               "counted from 0.10 above the film base, since a curve only reaches its base asymptotically. "
                               + ("Part of that lies beyond the measured range, so it is extrapolated. " if beyond and ref.representation != "model" else "")
                               + "This assumes the curve describes your film, exposure and development.")
            else:
                readout.append("The picture's density range runs past the end of this curve, so no exposure range is implied.")
        self._fit_plot.set_views(views, label, "Choose a film profile or show the model curve to see an H&D plot.", band)
        self._resid_plot.set_views(views)
        self._grad_plot.set_views(views)
        self._hd_readout.setText("\n".join(readout))

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
        self._transfer_label = QLabel("Picture encoding (non-RAW files)")
        self._transfer_label.setWordWrap(True)
        body.addWidget(self._transfer_label)
        self._transfer = QComboBox()
        for key in TRANSFERS:
            self._transfer.addItem(TRANSFER_LABELS[key], key)
        self._transfer.currentIndexChanged.connect(lambda _i: self.transfer_changed.emit(self._transfer.currentData()))
        body.addWidget(self._transfer)
        setups = QPushButton("Camera Set-ups...")
        setups.setToolTip("Saved calibrations of your camera and backlight, made in Film Characterization.")
        setups.clicked.connect(self.setups_requested)
        body.addWidget(setups)
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
        d = m.diagnosis
        if d is not None:
            html.append("<p><b>Where the measurement can be trusted</b></p><table cellpadding='2'>")
            for key in diagnostics_mod.CATEGORIES:
                share = d.any_channel.get(key, 0.0)
                html.append(f"<tr><td>{diagnostics_mod.CATEGORY_LABELS[key]}</td><td align='right'>{share * 100:.1f}%</td><td style='color:{THEME.text_muted}'>&nbsp;{d.evidence[key]}</td></tr>")
            html.append("</table>")
            if d.headroom_stops is not None:
                html.append(f"<p>The film base reads well below the sensor's top: about {d.headroom_stops:.1f} stops more light would still keep it unclipped "
                            f"and reach about {d.headroom_density:.2f} more density.</p>")
            lo_hi = ", ".join(f"{('R', 'G', 'B')[i]} {iv.value:.2f} ({iv.low:.2f} to {iv.high:.2f})" for i, iv in enumerate(d.dmax))
            html.append(f"<p>Dmax above base with a 95% range: {lo_hi}.</p>")
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
                head.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._grid.addWidget(head, 0, c)
            for c in range(3):
                self._grid.setColumnStretch(c, 1)
                self._grid.setColumnMinimumWidth(c, 0)
            line = 1
            for row in analysis.summary_rows(m):
                label = QLabel(f"{row.label} <span style='color:{THEME.text_muted}'>({row.status})</span>")
                label.setTextFormat(Qt.TextFormat.RichText)
                label.setWordWrap(True)
                label.setToolTip(row.tip)
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
                self._grid.addWidget(label, line, 0, 1, 3)
                for c, value in enumerate(row.values):
                    cell = QLabel(value)
                    cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    cell.setToolTip(row.tip)
                    cell.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
                    self._grid.addWidget(cell, line + 1, c)
                line += 2
        self._draw_histogram()
        self._draw_hd()
        self._draw_calibration(error)
