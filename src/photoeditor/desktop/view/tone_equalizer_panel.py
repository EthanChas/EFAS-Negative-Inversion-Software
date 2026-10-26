from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from ...features.toneequalizer import logic as teq
from ...theme.tokens import THEME
from .dt_graphs import ToneEqGraph
from .dt_panel import DtModulePanel


class ToneEqualizerPanel(DtModulePanel):
    """Tone Equalizer, under Exposure: darktable's module (features/toneequalizer/logic.py) with its three pages - simple (a slider for each octave from -8 EV to 0 EV), advanced (the
    curve through the nodes, with the mask's histogram behind it, and the compensation of the mask) and masking (how the luminance mask is made) - and the button that shows the mask."""

    wand_requested = pyqtSignal(str)          # "teq_exposure_boost" or "teq_contrast_boost": set it from the histogram of the mask
    mask_display_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Tone Equalizer",
            (
                "darktable's tone equalizer: it relights the picture by an exposure correction chosen for each octave of brightness, as an audio equalizer sets a gain for each octave of "
                "sound. The nine nodes are one EV apart, from -8 EV (deep shadows) to 0 EV (white); the gain between them is a smooth curve. A pixel's brightness is read from a mask that, "
                "by default, is blurred by an edge-aware guided filter, so the correction follows the light of a region and keeps the local contrast inside it. simple: a slider for each "
                "node. advanced: the curve (drag a node; double-click to reset), and the exposure and contrast compensation of the mask, which slide and spread it so that it uses all the "
                "nodes (the wands set them from the picture). masking: the luminance estimator, how the details are preserved and the size of the blur. 'display exposure mask' shows "
                "the mask. It does nothing while all nine nodes are 0. Double-click a slider to reset it."
            ),
            teq.DEFAULTS,
            parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._tabs = QTabWidget()
        body.addWidget(self._tabs)

        def page(title: str) -> QVBoxLayout:
            holder = QWidget()
            layout = QVBoxLayout(holder)
            layout.setContentsMargins(0, THEME.space_sm, 0, 0)
            layout.setSpacing(THEME.space_sm)
            self._tabs.addTab(holder, title)
            return layout

        simple = page("simple")
        for key, label in zip(teq.BANDS, teq.BAND_LABELS):
            self.add_slider(simple, key, label, f"the exposure correction for the tones near {label}", (-2.0, 2.0), decimals=2, suffix=" EV", label_width=56)

        advanced = page("advanced")
        self._graph = ToneEqGraph()
        self._graph.node_moved.connect(lambda i, v: self.set_row(teq.BANDS[i], round(v, 2)))
        self._graph.reset_requested.connect(self._reset_curve)
        advanced.addWidget(self._graph)
        self.add_slider(advanced, "teq_smoothing", "curve smoothing", "positive values will produce more progressive tone transitions but the curve might become oscillatory in some "
                        "settings. negative values will avoid oscillations and behave more robustly but may produce brutal tone transitions and damage local contrast.", (-1.0, 1.0),
                        teq.RANGES["teq_smoothing"], decimals=2)
        wand_e = self.add_slider(advanced, "teq_exposure_boost", "mask exposure comp.", "use this to slide the mask average exposure along channels for a better control of the "
                                 "exposure correction with the available nodes.", (-4.0, 4.0), teq.RANGES["teq_exposure_boost"], decimals=2, suffix=" EV")
        wand_c = self.add_slider(advanced, "teq_contrast_boost", "mask contrast comp.", "use this to counter the averaging effect of the guided filter and dilate the mask contrast "
                                 "around -4EV. this allows to spread the exposure histogram over more channels for a better control of the exposure correction.", (-2.0, 2.0),
                                 teq.RANGES["teq_contrast_boost"], decimals=2, suffix=" EV")
        for row, key, tip in ((wand_e, "teq_exposure_boost", "auto-adjust the average exposure"), (wand_c, "teq_contrast_boost", "auto-adjust the contrast")):
            wand = QPushButton("✨")
            wand.setFixedWidth(28)
            wand.setToolTip(tip)
            wand.clicked.connect(lambda _c=False, k=key: self.wand_requested.emit(k))
            row.layout().addWidget(wand)

        masking = page("masking")
        self.add_combo(masking, "teq_method", "luminance estimator", [(i, n) for i, n in enumerate(teq.METHOD_LABELS)], "preview the mask and chose the estimator that gives you the "
                       "higher contrast between areas to dodge and areas to burn")
        self.add_combo(masking, "teq_details", "preserve details", [(i, n) for i, n in enumerate(teq.DETAILS_LABELS)],
                       "'no' affects global and local contrast (safe if you only add contrast)\n'guided filter' only affects global contrast and tries to preserve local contrast\n"
                       "'averaged guided filter' is a geometric mean of 'no' and 'guided filter' methods\n'EIGF' (exposure-independent guided filter) is a guided filter that is "
                       "exposure-independent, it smooths shadows and highlights the same way (contrary to guided filter which smooths less the highlights)\n'averaged EIGF' is a "
                       "geometric mean of 'no' and 'exposure-independent guided filter' methods")
        self.add_slider(masking, "teq_iterations", "filter diffusion", "number of passes of guided filter to apply helps diffusing the edges of the filter at the expense of speed",
                        (1, 5), teq.RANGES["teq_iterations"], decimals=0, step=1)
        self.add_slider(masking, "teq_blending", "smoothing diameter", "diameter of the blur in percent of the largest image size", (1.0, 45.0), teq.RANGES["teq_blending"], decimals=2, suffix="%")
        self.add_slider(masking, "teq_feathering", "edge feathering", "precision of the feathering: higher values force the mask to follow edges more closely but may void "
                        "the effect of the smoothing. lower values give smoother gradients and better smoothing but may lead to inaccurate edges taping and halos", (0.1, 50.0),
                        teq.RANGES["teq_feathering"], decimals=2)
        self.add_slider(masking, "teq_quantization", "mask quantization", "0 disables the quantization. higher values posterize the luminance mask to help the guiding produce "
                        "piece-wise smooth areas when using high feathering values", teq.RANGES["teq_quantization"], decimals=2, suffix=" EV")

        line = QHBoxLayout()
        line.addWidget(QLabel("display exposure mask"), 1)
        self._show_mask = QPushButton("show")
        self._show_mask.setCheckable(True)
        self._show_mask.setToolTip("Show the luminance mask the correction is read from, as a grey picture, instead of the result")
        self._show_mask.toggled.connect(self.mask_display_toggled)
        line.addWidget(self._show_mask)
        body.addLayout(line)
        self._note = QLabel("")
        self._note.setProperty("role", "hint")
        self._note.setWordWrap(True)
        body.addWidget(self._note)

    def values_set(self) -> None:
        self._graph.set_values(self.values())

    def set_histogram(self, histogram) -> None:
        self._graph.set_histogram(histogram)

    def set_note(self, text: str) -> None:
        self._note.setText(text)

    def mask_displayed(self) -> bool:
        return self._show_mask.isChecked()

    def put_mask_display(self, on: bool) -> None:
        """Show the button as pressed (or not) without saying so: the picture changed (a new photo) and the controller already knows."""
        self._show_mask.blockSignals(True)
        self._show_mask.setChecked(on)
        self._show_mask.blockSignals(False)

    def _reset_curve(self) -> None:
        for key in teq.BANDS:
            row = self._rows[key]
            row.blockSignals(True)
            row.set_value(0.0)
            row.blockSignals(False)
        self._on_value_changed()
