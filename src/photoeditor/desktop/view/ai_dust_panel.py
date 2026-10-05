from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QLabel, QProgressBar, QPushButton, QWidget

from ...features.aidust.logic import DEFAULT_GROW, DEFAULT_THRESHOLD, GROW_RANGE, THRESHOLD_RANGE
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_SETTLE_DEBOUNCE_MS = 350  # the repair is slow, so a slider settles before it is applied


class AiDustPanel(CollapsiblePanel):
    """AI Dust Detection: a small neural network (FilmDefectNet, features/aidust/logic.py) finds dust, hairs and scratches in the scan, and
    the usual repair fills what it marks. The photo is analysed once at full resolution - seconds to a minute, in the background, with
    progress - and the result is kept on disk. Threshold and Grow then change what is repaired without a new analysis."""

    changed = pyqtSignal(bool, float, int)  # on, threshold, grow - settled
    cancel_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "AI Dust Detection",
            help_text=(
                "A small neural network (FilmDefectNet) looks for dust, hairs and scratches - bright and dark - in the scan, and the "
                "same repair as the other dust tools fills only what it marks, so grain and detail everywhere else stay untouched. "
                "The photo is analysed once, at full resolution (it takes a few seconds per megapixel, in the background), and the "
                "result is remembered. Threshold: lower marks fainter specks but may take grain for dust; higher is more cautious. "
                "Grow: how many pixels each marked spot is widened so its edge is repaired too. Turn on Show Detections in Dust & "
                "Scratches to see what is marked (amber). Works together with Auto Dust Removal and the manual tools."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._enable = QPushButton("AI Dust Removal")
        self._enable.setCheckable(True)
        self._enable.toggled.connect(self._emit_now)
        body.addWidget(self._enable)

        self._threshold = SliderRow("Threshold", min_value=THRESHOLD_RANGE[0], max_value=THRESHOLD_RANGE[1], reset_value=DEFAULT_THRESHOLD)
        self._threshold.set_value(DEFAULT_THRESHOLD)
        self._threshold.setToolTip("How sure the model must be before a pixel is repaired. Lower finds fainter specks; higher is more cautious.")
        self._threshold.value_changed.connect(self._on_slider)
        body.addWidget(self._threshold)
        self._grow = SliderRow("Grow", min_value=GROW_RANGE[0], max_value=GROW_RANGE[1], reset_value=DEFAULT_GROW, decimals=0, step=1.0)
        self._grow.set_value(DEFAULT_GROW)
        self._grow.setToolTip("Pixels each marked spot is widened by, so the repair covers its edge.")
        self._grow.value_changed.connect(self._on_slider)
        body.addWidget(self._grow)

        self._status = QLabel("")
        self._status.setProperty("role", "hint")
        self._status.setWordWrap(True)
        body.addWidget(self._status)
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        self._progress.hide()
        body.addWidget(self._progress)
        self._cancel = QPushButton("Cancel Analysis")
        self._cancel.clicked.connect(self.cancel_requested)
        self._cancel.hide()
        body.addWidget(self._cancel)

        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle.timeout.connect(self._emit_now)
        self.set_info({"state": "off"})

    def values(self) -> tuple[bool, float, int]:
        return self._enable.isChecked(), self._threshold.value(), int(round(self._grow.value()))

    def set_values(self, on: bool, threshold: float, grow: int) -> None:
        """Show these settings without emitting anything - a new photo, or a history step."""
        self._settle.stop()
        for w in (self._enable, self._threshold, self._grow):
            w.blockSignals(True)
        self._enable.setChecked(on)
        self._threshold.set_value(threshold)
        self._grow.set_value(float(grow))
        for w in (self._enable, self._threshold, self._grow):
            w.blockSignals(False)

    def reset(self) -> None:
        self.set_values(False, DEFAULT_THRESHOLD, DEFAULT_GROW)
        self.set_info({"state": "off"})

    def _on_slider(self, _value: float) -> None:
        self._settle.start()

    def _emit_now(self, *_args) -> None:
        self._settle.stop()
        self.changed.emit(*self.values())

    def set_info(self, info: dict) -> None:
        """What the controller reports: state "off", "missing", "error", "waiting", "running" or "ready"."""
        state = info.get("state", "off")
        running = state == "running"
        self._progress.setVisible(running)
        self._cancel.setVisible(running)
        if running:
            total = max(1, int(info.get("total", 0)))
            self._progress.setRange(0, total)
            self._progress.setValue(int(info.get("done", 0)))
        usable = state != "missing"
        self._enable.setEnabled(usable)
        self._threshold.setEnabled(usable)
        self._grow.setEnabled(usable)
        self._status.setText({
            "off": "Off. Switch it on to find dust, hairs and scratches with the model.",
            "missing": "The AI model could not be loaded (onnxruntime or the model file is missing).",
            "error": f"The analysis failed: {info.get('error', '')}",
            "waiting": "Waiting for the analysis...",
            "running": f"Analysing the photo... {info.get('done', 0)} of {info.get('total', 0)} parts",
            "ready": f"Ready: {float(info.get('flagged', 0.0)) * 100:.2f}% of the frame is marked. Show Detections (Dust & Scratches) shows where.",
        }.get(state, ""))
