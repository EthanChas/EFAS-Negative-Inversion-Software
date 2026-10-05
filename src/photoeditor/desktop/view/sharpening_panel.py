from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...features.sharpening.logic import DEFAULT_METHOD, METHOD_LABELS, SharpenMethod
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33  # ~30fps cap for the cheap image-only preview, same as Exposure
_SETTLE_DEBOUNCE_MS = 200


class SharpeningToolPanel(CollapsiblePanel):
    """Sharpening under the Negative tab, ported from NegPy's four methods
    (features/sharpening/logic.py). Same two-tier preview/full-recompute
    split as the other tools, carrying every value in one signal pair.

    Amount/Radius/Masking aren't centered on 0 like the other tools' -1..+1
    sliders, so each SliderRow here is built with its own min/max/reset -
    this is what the value_range/min_value/max_value/reset_value
    generalization of SliderRow (previously just a symmetric -range..+range)
    was added for."""

    changed = pyqtSignal(float, float, float, str)  # amount, radius, masking, method
    preview_requested = pyqtSignal(float, float, float, str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Sharpening",
            help_text=(
                "Method: Unsharp Mask is the all-purpose default; Deconvolution "
                "reverses scanner/lens blur (set Radius to the blur width); Surface "
                "Blur keeps skin and smooth gradients clean; Wavelet sharpens "
                "structure while leaving grain alone. Deconvolution applies when you "
                "release the slider. "
                "Amount: strength of the sharpening effect, 0 is off. "
                "Radius: size in pixels of the detail being sharpened - "
                "larger values sharpen broader detail. Masking: protects "
                "flat or noisy areas from being sharpened; 0 sharpens "
                "everywhere equally. Double-click a slider to reset it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)

        rows = QVBoxLayout()
        rows.setSpacing(THEME.space_sm)

        # Default amount is 0 (off), unlike NegPy's own 0.25 default - every
        # other tool in this app starts at a true no-op until the user
        # opts in, and Sharpening follows the same convention.
        method_row = QHBoxLayout()
        method_row.setSpacing(THEME.space_sm)
        method_label = QLabel("Method")
        method_label.setFixedWidth(80)
        method_row.addWidget(method_label)
        self._method = QComboBox()
        for method in SharpenMethod:
            self._method.addItem(METHOD_LABELS[method], method.value)
        self._method.currentIndexChanged.connect(self._on_value_changed)
        method_row.addWidget(self._method, 1)
        rows.addLayout(method_row)

        self._amount = SliderRow("Amount", min_value=0.0, max_value=1.0, reset_value=0.0)
        self._amount.value_changed.connect(self._on_value_changed)
        rows.addWidget(self._amount)

        self._radius = SliderRow("Radius", min_value=0.5, max_value=3.0, reset_value=1.0)
        self._radius.value_changed.connect(self._on_value_changed)
        rows.addWidget(self._radius)

        self._masking = SliderRow("Masking", min_value=0.0, max_value=1.0, reset_value=0.0)
        self._masking.value_changed.connect(self._on_value_changed)
        rows.addWidget(self._masking)

        body.addLayout(rows)

        self._pending_preview: tuple[float, float, float, str] | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)

        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(self._on_settled)

    def _current(self) -> tuple[float, float, float, str]:
        return (self._amount.value(), self._radius.value(), self._masking.value(), self._method.currentData())

    def reset(self) -> None:
        """Back to the no-op defaults without emitting anything - used
        when a new file is opened, since the controller has already reset
        its own sharpening state as part of that load."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_values(0.0, 1.0, 0.0, DEFAULT_METHOD)

    def set_values(self, amount: float, radius: float, masking: float, method: str) -> None:
        """Sync every control without emitting anything - used by reset()
        and after a history revert."""
        self._method.blockSignals(True)
        self._method.setCurrentIndex(max(0, self._method.findData(method)))
        self._method.blockSignals(False)
        self._amount.set_value(amount)
        self._radius.set_value(radius)
        self._masking.set_value(masking)

    def _on_value_changed(self, _value=None) -> None:
        values = self._current()
        self._request_preview(values)
        self._settle_timer.start()

    def _request_preview(self, values: tuple[float, float, float, str]) -> None:
        if self._preview_timer.isActive():
            self._pending_preview = values
            return
        self.preview_requested.emit(*values)
        self._preview_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview is not None:
            values, self._pending_preview = self._pending_preview, None
            self.preview_requested.emit(*values)
            self._preview_timer.start()

    def _on_settled(self) -> None:
        self.changed.emit(*self._current())
