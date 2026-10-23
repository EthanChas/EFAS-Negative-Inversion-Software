from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QWidget

from ...features.instances import logic as inst
from ...features.lookpresets.modules import PANEL_MODULES
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 110


class InstancePanel(CollapsiblePanel):
    """A copy of a module (darktable's multiple instances): a panel with the module's colour and icon, the module's own controls drawn from its fields (a slider for each number, a box for each
    choice), its own Mask box at the foot, and its own on/off light. Its title is the module's with the copy's number and name; the menu button in the header renames, duplicates and deletes it.

    values_changed(changes, preview) says what was set (preview: a drag still going on)."""

    values_changed = pyqtSignal(dict, bool)

    def __init__(self, key: str, instance_id: int, title: str, values: dict, expanded: bool = False, parent: QWidget | None = None):
        super().__init__(PANEL_MODULES[key][0], help_text=f"A copy of {PANEL_MODULES[key][0]}: it has its own settings, its own Mask box and its own on/off light, and acts after the module it was copied from (and after the copies before it). "
                                                          "Use the menu button in the header to rename, duplicate or delete it.", collapsible=True, start_expanded=expanded, parent=parent)
        self.key, self.instance_id = key, instance_id
        self.set_display_title(title)
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._building = True
        self._rows: dict[str, SliderRow] = {}
        self._boxes: dict[str, QComboBox] = {}
        self._checks: dict[str, QCheckBox] = {}
        for spec in inst.fields_of(key):
            if spec.kind == "float":
                row = SliderRow(spec.label, min_value=spec.low, max_value=spec.high, reset_value=spec.default, decimals=2, step=spec.step, label_width=_LABEL_WIDTH)
                row.value_changed.connect(lambda v, k=spec.key: self._moved(k, v))
                self._rows[spec.key] = row
                body.addWidget(row)
            elif spec.kind == "choice":
                line = QHBoxLayout()
                line.addWidget(QLabel(spec.label))
                box = QComboBox()
                for value, label in spec.choices:
                    box.addItem(label, value)
                box.activated.connect(lambda _i, k=spec.key, b=box: self.values_changed.emit({k: b.currentData()}, False))
                self._boxes[spec.key] = box
                line.addWidget(box, 1)
                body.addLayout(line)
            elif spec.kind == "bool":
                check = QCheckBox(spec.label)
                check.toggled.connect(lambda on, k=spec.key: None if self._building else self.values_changed.emit({k: bool(on)}, False))
                self._checks[spec.key] = check
                body.addWidget(check)
        self._pending: tuple | None = None
        self._settle_args: tuple | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(self._settle)
        self.set_values(values)
        self._building = False

    def set_values(self, values: dict) -> None:
        """Show these settings without announcing them (the photo changed, or an undo)."""
        was, self._building = self._building, True
        for key, row in self._rows.items():
            if key in values:
                row.set_value(float(values[key]))
        for key, box in self._boxes.items():
            if key in values:
                box.setCurrentIndex(max(0, box.findData(values[key])))
        for key, check in self._checks.items():
            if key in values:
                check.setChecked(bool(values[key]))
        self._building = was

    def values(self) -> dict:
        out = {k: r.value() for k, r in self._rows.items()}
        out.update({k: b.currentData() for k, b in self._boxes.items()})
        out.update({k: c.isChecked() for k, c in self._checks.items()})
        return out

    def _moved(self, key: str, value: float) -> None:
        if self._building:
            return
        self._settle_args = ({key: value},)
        if self._preview_timer.isActive():
            self._pending = ({key: value},)
        else:
            self.values_changed.emit({key: value}, True)
            self._preview_timer.start()
        self._settle_timer.start()

    def _flush(self) -> None:
        if self._pending is not None:
            (changes,), self._pending = self._pending, None
            self.values_changed.emit(changes, True)
            self._preview_timer.start()

    def _settle(self) -> None:
        if self._settle_args is not None:
            (changes,), self._settle_args, self._pending = self._settle_args, None, None
            self.values_changed.emit(changes, False)
