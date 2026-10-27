from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from ...features.lookpresets.modules import MODULES, FieldSpec, clamp
from ...theme.tokens import THEME

_SKIPPED_KINDS = ("curve",)     # a curve is set by drawing it, not by typing a value


class _Row(QWidget):
    """One setting: a checkbox that says whether it is to be set, and the value to set it to (greyed out until it is ticked)."""

    def __init__(self, field: FieldSpec, parent: QWidget | None = None):
        super().__init__(parent)
        self.field = field
        row = QHBoxLayout(self)
        row.setContentsMargins(THEME.space_lg, 0, 0, 0)
        self.use = QCheckBox(field.label)
        self.use.setMinimumWidth(170)
        row.addWidget(self.use)
        if field.kind == "float":
            self.widget = QDoubleSpinBox()
            self.widget.setRange(field.low, field.high)
            self.widget.setDecimals(3 if field.step < 0.1 else 1)
            self.widget.setSingleStep(field.step)
            self.widget.setValue(field.default)
            self._get = self.widget.value
        elif field.kind == "bool":
            self.widget = QComboBox()
            self.widget.addItem("On", True)
            self.widget.addItem("Off", False)
            self.widget.setCurrentIndex(0 if field.default else 1)
            self._get = self.widget.currentData
        elif field.kind == "choice":
            self.widget = QComboBox()
            for stored, text in field.choices:
                self.widget.addItem(text, stored)
            self.widget.setCurrentIndex(max(0, self.widget.findData(field.default)))
            self._get = self.widget.currentData
        else:
            self.widget = QLineEdit(str(field.default))
            self.widget.setMaxLength(80)
            self._get = self.widget.text
        self.widget.setEnabled(False)
        self.use.toggled.connect(self.widget.setEnabled)
        row.addWidget(self.widget, 1)

    def value(self):
        return clamp(self.field, self._get())


class BatchSettingsDialog(QDialog):
    """Set chosen settings on several photos at once: tick the ones to set and give each a value; everything left unticked stays as each photo has it."""

    def __init__(self, count: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Set Settings for {count} Photo{'s' if count != 1 else ''}")
        self.resize(460, 640)
        outer = QVBoxLayout(self)
        outer.setSpacing(THEME.space_md)
        hint = QLabel(f"Tick each setting to set on the {count} selected photo{'s' if count != 1 else ''} and choose its value. Settings left unticked stay as each photo has them, "
                      "and each photo keeps its own crop, rotation and dust repairs. Film type is first: use it to mark photos the auto-detection got wrong.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {THEME.text_hint};")
        outer.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setSpacing(THEME.space_sm)
        self._rows: list[_Row] = []
        for spec in MODULES:
            fields = [f for f in spec.fields if f.kind not in _SKIPPED_KINDS]
            if not fields:
                continue
            title = QLabel(spec.title)
            title.setStyleSheet("font-weight: bold;")
            col.addWidget(title)
            for field in fields:
                row = _Row(field)
                self._rows.append(row)
                col.addWidget(row)
        col.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        clear = QPushButton("Untick All")
        clear.clicked.connect(lambda: [r.use.setChecked(False) for r in self._rows])
        buttons.addWidget(clear)
        buttons.addStretch(1)
        self._apply = QPushButton("Apply")
        self._apply.setDefault(True)
        self._apply.clicked.connect(self._try_accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self._apply)
        buttons.addWidget(cancel)
        outer.addLayout(buttons)

    def set_film_type(self, film_type: str) -> None:
        """Tick Film type and choose a value (the quick case: a roll the auto-detection gets wrong)."""
        for row in self._rows:
            if row.field.key == "film_type":
                row.use.setChecked(True)
                row.widget.setCurrentIndex(max(0, row.widget.findData(film_type)))

    def values(self) -> dict:
        """{setting: value} for every ticked row."""
        return {r.field.key: r.value() for r in self._rows if r.use.isChecked() and r.value() is not None}

    def _try_accept(self) -> None:
        if not self.values():
            QMessageBox.information(self, "Set Settings", "Tick at least one setting, or there is nothing to set.")
            return
        self.accept()
