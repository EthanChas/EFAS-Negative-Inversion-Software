from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...features.lookpresets.modules import MODULES, FieldSpec, ModuleSpec, clamp, module_included
from ...theme.tokens import THEME
from .curve_editor import CurveEditor
from .slider_row import SliderRow


class _ModuleBox(QFrame):
    """One editing module: a header with an Include checkbox and the module's own controls underneath."""

    def __init__(self, spec: ModuleSpec, look: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.spec = spec
        self.setFrameShape(QFrame.Shape.StyledPanel)
        outer = QVBoxLayout(self)
        outer.setSpacing(THEME.space_sm)
        self.include = QCheckBox(spec.title)
        self.include.setStyleSheet("font-weight: bold;")
        self.include.setToolTip("Checked: this preset sets these values. Unchecked: applying it leaves this module alone.")
        outer.addWidget(self.include)
        body = QWidget()
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(THEME.space_lg, 0, 0, 0)
        self._body.setSpacing(THEME.space_sm)
        outer.addWidget(body)
        self._getters: dict[str, object] = {}
        for field in spec.fields:
            stored = clamp(field, look[field.key]) if field.key in look else None
            self._add_field(field, field.default if stored is None else stored)
        self.include.setChecked(module_included(look, spec))
        self.include.toggled.connect(body.setEnabled)
        body.setEnabled(self.include.isChecked())

    def _touched(self, *_args) -> None:
        if not self.include.isChecked():
            self.include.setChecked(True)

    def _add_field(self, field: FieldSpec, value) -> None:
        if field.kind == "float":
            widget = SliderRow(field.label, min_value=field.low, max_value=field.high, reset_value=field.default, step=field.step)
            widget.set_value(value)
            widget.value_changed.connect(self._touched)
            self._getters[field.key] = widget.value
            self._body.addWidget(widget)
        elif field.kind == "curve":
            widget = CurveEditor()
            widget.set_points(list(value))
            widget.interaction_finished.connect(self._touched)
            self._getters[field.key] = widget.points
            self._body.addWidget(widget)
        else:
            row = QHBoxLayout()
            if field.kind == "bool":
                widget = QCheckBox(field.label)
                widget.setChecked(bool(value))
                widget.toggled.connect(self._touched)
                self._getters[field.key] = widget.isChecked
                row.addWidget(widget)
            else:
                label = QLabel(field.label)
                label.setFixedWidth(80)
                row.addWidget(label)
                if field.kind == "choice":
                    widget = QComboBox()
                    for stored, text in field.choices:
                        widget.addItem(text, stored)
                    widget.setCurrentIndex(max(0, widget.findData(value)))
                    widget.currentIndexChanged.connect(self._touched)
                    self._getters[field.key] = widget.currentData
                else:
                    widget = QLineEdit(str(value))
                    widget.setMaxLength(80)
                    widget.textEdited.connect(self._touched)
                    self._getters[field.key] = widget.text
                row.addWidget(widget, 1)
            self._body.addLayout(row)

    def values(self) -> dict:
        """The module's fields as the preset stores them - empty when the module is left out."""
        if not self.include.isChecked():
            return {}
        out = {}
        for key, getter in self._getters.items():
            value = getter()
            out[key] = [list(p) for p in value] if key == "tone_curve_points" else value
        return out


class AdvancedPresetDialog(QDialog):
    """Advanced Preset Edit: every editing module of a preset on one page, with its values editable - sliders, curve, film type, sharpening
    method, watermark and so on. Modules the preset does not carry are listed too, unchecked; check one (or touch a value) to add it."""

    def __init__(self, name: str, look: dict, other_names: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Advanced Preset Edit – {name}")
        self._other = {n.casefold() for n in other_names}
        self.resize(460, 720)
        outer = QVBoxLayout(self)
        outer.setSpacing(THEME.space_md)

        form = QFormLayout()
        self._name = QLineEdit(name)
        self._name.setMaxLength(60)
        form.addRow("Preset name", self._name)
        outer.addLayout(form)

        hint = QLabel("Every module is listed. Checked modules are set by this preset; unchecked ones are left alone when it is applied.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {THEME.text_hint};")
        outer.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setSpacing(THEME.space_md)
        self._boxes = [_ModuleBox(spec, look) for spec in MODULES]
        for box in self._boxes:
            col.addWidget(box)
        col.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        row = QHBoxLayout()
        all_btn = QPushButton("Include All")
        all_btn.clicked.connect(lambda: [b.include.setChecked(True) for b in self._boxes])
        none_btn = QPushButton("Include None")
        none_btn.clicked.connect(lambda: [b.include.setChecked(False) for b in self._boxes])
        row.addWidget(all_btn)
        row.addWidget(none_btn)
        row.addStretch(1)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(self._try_accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(save)
        row.addWidget(cancel)
        outer.addLayout(row)

    def name(self) -> str:
        return " ".join(self._name.text().split())

    def look(self) -> dict:
        out: dict = {}
        for box in self._boxes:
            out.update(box.values())
        return out

    def _try_accept(self) -> None:
        name = self.name()
        if not name:
            QMessageBox.warning(self, "Preset", "Give the preset a name.")
            return
        if name.casefold() in self._other:
            QMessageBox.warning(self, "Preset", f"There is already a preset called '{name}'.")
            return
        if not self.look():
            QMessageBox.warning(self, "Preset", "Include at least one module, or the preset would do nothing.")
            return
        self.accept()
