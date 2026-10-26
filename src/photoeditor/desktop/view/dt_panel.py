"""The common part of the panels of the modules ported from darktable that have many controls (Diffuse or Sharpen, Tone Equalizer, Color Balance RGB): sliders and drop-down lists that
each own one field of the module, the soft range and hard range darktable gives a slider (the slider covers the soft range, the box beside it takes anything in the hard one), the
two-tier preview / full-recompute split of the other modules, and values that travel as one dict."""
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
LABEL_WIDTH = 140


class DtModulePanel(CollapsiblePanel):
    changed = pyqtSignal(object)            # the values, once a change has settled
    preview_requested = pyqtSignal(object)  # the values, while a slider is being dragged

    def __init__(self, title: str, help_text: str, defaults: dict, parent: QWidget | None = None):
        super().__init__(title, help_text=help_text, collapsible=True, start_expanded=False, parent=parent)
        self._defaults = dict(defaults)
        self._rows: dict[str, SliderRow] = {}
        self._combos: dict[str, QComboBox] = {}
        self._scale: dict[str, float] = {}
        self._pending_preview: dict | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(lambda: self.changed.emit(self.values()))

    # ------------------------------------------------------------ building
    def add_section(self, layout, text: str) -> QLabel:
        """A heading, in capitals like the other modules' (and with a thin line above it, which the window puts in front of every such heading)."""
        label = QLabel(text.upper())
        label.setProperty("role", "subtitle")
        layout.addWidget(label)
        return label

    def add_slider(self, layout, key: str, label: str, tip: str, soft: tuple, hard: tuple | None = None, decimals: int = 2, scale: float = 1.0, suffix: str = "",
                   step: float | None = None, label_width: int | None = None) -> SliderRow:
        """A slider for `key` over its soft range, with the box beside it taking the hard range. `scale` turns the stored number into the one shown (100 for darktable's "%")."""
        hard = hard or soft
        default = float(self._defaults.get(key, 0.0)) * scale
        span = (soft[1] - soft[0]) * scale
        row = SliderRow(label, min_value=soft[0] * scale, max_value=soft[1] * scale, reset_value=default, decimals=decimals,
                        step=step if step is not None else max(10.0 ** -decimals, span / 200.0), label_width=label_width or LABEL_WIDTH,
                        spin_min=hard[0] * scale, spin_max=hard[1] * scale)
        row.setToolTip(tip)
        if suffix:
            row.set_suffix(suffix)
        row.value_changed.connect(self._on_value_changed)
        self._rows[key] = row
        self._scale[key] = scale
        layout.addWidget(row)
        return row

    def add_combo(self, layout, key: str, label: str, items: list[tuple[float, str]], tip: str) -> QComboBox:
        line = QHBoxLayout()
        name = QLabel(label)
        name.setFixedWidth(LABEL_WIDTH)
        line.addWidget(name)
        box = QComboBox()
        for value, text in items:
            box.addItem(text, float(value))
        box.setToolTip(tip)
        box.activated.connect(lambda _i: self._on_combo(key))
        line.addWidget(box, 1)
        layout.addLayout(line)
        self._combos[key] = box
        return box

    # ------------------------------------------------------------ values
    def values(self) -> dict:
        out = {key: row.value() / self._scale[key] for key, row in self._rows.items()}
        out.update({key: float(box.currentData()) for key, box in self._combos.items()})
        return out

    def reset(self) -> None:
        """Back to the defaults without emitting anything - used when a new file is opened, since the controller has already reset its own state."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_values(self._defaults)

    def set_values(self, values) -> None:
        """Sync the controls without emitting anything - used by reset() and after a history revert."""
        for key, row in self._rows.items():
            row.blockSignals(True)
            row.set_value(float(values.get(key, self._defaults.get(key, 0.0))) * self._scale[key])
            row.blockSignals(False)
        for key, box in self._combos.items():
            box.blockSignals(True)
            box.setCurrentIndex(max(0, box.findData(float(values.get(key, self._defaults.get(key, 0.0))))))
            box.blockSignals(False)
        self.values_set()

    def values_set(self) -> None:
        """A hook for a panel that draws something from the values (a graph): called after set_values."""

    def set_row(self, key: str, value: float) -> None:
        """Move one control from outside (a graph's node, a wand) and apply it as a change."""
        row = self._rows[key]
        row.blockSignals(True)
        row.set_value(float(value) * self._scale[key])
        row.blockSignals(False)
        self._on_value_changed()

    # ------------------------------------------------------------ a change
    def _on_combo(self, _key: str) -> None:
        self._settle_timer.stop()
        self._pending_preview = None
        self.values_set()
        self.changed.emit(self.values())

    def _on_value_changed(self, _value=None) -> None:
        values = self.values()
        self.values_set()
        if self._preview_timer.isActive():
            self._pending_preview = values
        else:
            self.preview_requested.emit(values)
            self._preview_timer.start()
        self._settle_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview is not None:
            values, self._pending_preview = self._pending_preview, None
            self.preview_requested.emit(values)
            self._preview_timer.start()
