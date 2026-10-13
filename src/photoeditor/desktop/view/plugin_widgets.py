"""The controls a plugin's module can show, built from the plain "spec" dicts the plugin API produces (plugins/api.py). Each build returns a *view*: a small
adapter with get_value / set_value / set_text / set_enabled / set_visible / set_options / set_range that the API's WidgetHandle calls. A plugin's own callback
(already wrapped to run safely) is called from the control's signal."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PROGRESS_STEPS = 1000


class WidgetView:
    """The common part: the Qt widget, and what a control that does not support a call says."""

    def __init__(self, widget: QWidget):
        self.widget = widget

    def get_value(self):
        return None

    def set_value(self, value) -> None:
        pass

    def set_text(self, text: str) -> None:
        pass

    def set_enabled(self, enabled: bool) -> None:
        self.widget.setEnabled(enabled)

    def set_visible(self, visible: bool) -> None:
        self.widget.setVisible(visible)

    def set_options(self, options, current) -> None:
        pass

    def set_range(self, low, high) -> None:
        pass


class LabelView(WidgetView):
    def __init__(self, spec):
        label = QLabel(spec.get("text", ""))
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        super().__init__(label)

    def get_value(self):
        return self.widget.text()

    def set_value(self, value) -> None:
        self.widget.setText(value)

    set_text = set_value


class ButtonView(WidgetView):
    def __init__(self, spec):
        button = QPushButton(spec.get("label", ""))
        callback = spec.get("callback")
        if callback:
            button.clicked.connect(lambda _checked=False: callback())
        super().__init__(button)

    def set_text(self, text: str) -> None:
        self.widget.setText(text)


class CheckboxView(WidgetView):
    def __init__(self, spec):
        box = QCheckBox(spec.get("label", ""))
        box.setChecked(bool(spec.get("checked")))
        callback = spec.get("callback")
        if callback:
            box.toggled.connect(lambda checked: callback(bool(checked)))
        super().__init__(box)

    def get_value(self):
        return self.widget.isChecked()

    def set_value(self, value) -> None:
        self.widget.blockSignals(True)
        self.widget.setChecked(bool(value))
        self.widget.blockSignals(False)

    def set_text(self, text: str) -> None:
        self.widget.setText(text)


class SliderView(WidgetView):
    def __init__(self, spec):
        row = SliderRow(spec.get("label", ""), min_value=spec["min"], max_value=spec["max"], reset_value=spec["value"],
                        decimals=spec.get("decimals", 2), step=spec.get("step", 0.01))
        row.set_value(spec["value"])
        callback = spec.get("callback")
        if callback:
            row.value_changed.connect(lambda value: callback(float(value)))
        super().__init__(row)

    def get_value(self):
        return float(self.widget.value())

    def set_value(self, value) -> None:
        self.widget.set_value(max(self.widget._min, min(self.widget._max, float(value))))

    def set_range(self, low, high) -> None:
        row = self.widget
        value = row.value()
        row._min, row._max = low, high
        row._spin.blockSignals(True)
        row._spin.setRange(low, high)
        row._spin.blockSignals(False)
        row.set_value(max(low, min(high, value)))


class ComboView(WidgetView):
    def __init__(self, spec):
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(THEME.space_sm)
        self.caption = QLabel(spec.get("label", ""))
        row.addWidget(self.caption)
        self.combo = QComboBox()
        self.combo.addItems(spec["options"])
        self.combo.setCurrentText(spec.get("current", spec["options"][0]))
        row.addWidget(self.combo, 1)
        callback = spec.get("callback")
        if callback:
            self.combo.currentTextChanged.connect(lambda text: callback(text))
        super().__init__(holder)

    def get_value(self):
        return self.combo.currentText()

    def set_value(self, value) -> None:
        index = self.combo.findText(value)
        if index >= 0:
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(index)
            self.combo.blockSignals(False)

    def set_text(self, text: str) -> None:
        self.caption.setText(text)

    def set_options(self, options, current) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(options)
        self.combo.setCurrentText(current if current in options else options[0])
        self.combo.blockSignals(False)


class TextView(WidgetView):
    def __init__(self, spec):
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(THEME.space_sm)
        self.caption = QLabel(spec.get("label", ""))
        row.addWidget(self.caption)
        self.edit = QLineEdit(spec.get("text", ""))
        row.addWidget(self.edit, 1)
        callback = spec.get("callback")
        if callback:
            self.edit.editingFinished.connect(lambda: callback(self.edit.text()))
        super().__init__(holder)

    def get_value(self):
        return self.edit.text()

    def set_value(self, value) -> None:
        self.edit.blockSignals(True)
        self.edit.setText(value)
        self.edit.blockSignals(False)

    def set_text(self, text: str) -> None:
        self.set_value(text)


class SeparatorView(WidgetView):
    def __init__(self, spec):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        super().__init__(line)


class ProgressView(WidgetView):
    def __init__(self, spec):
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        self.caption = QLabel(spec.get("label", ""))
        self.caption.setVisible(bool(spec.get("label")))
        column.addWidget(self.caption)
        self.bar = QProgressBar()
        self.bar.setRange(0, _PROGRESS_STEPS)
        self.bar.setTextVisible(False)
        self.bar.setValue(round(spec.get("value", 0.0) * _PROGRESS_STEPS))
        column.addWidget(self.bar)
        super().__init__(holder)

    def get_value(self):
        return self.bar.value() / _PROGRESS_STEPS

    def set_value(self, value) -> None:
        self.bar.setValue(round(max(0.0, min(1.0, float(value))) * _PROGRESS_STEPS))

    def set_text(self, text: str) -> None:
        self.caption.setText(text)
        self.caption.setVisible(bool(text))


class QtView(WidgetView):
    def __init__(self, spec):
        super().__init__(spec["widget"])


_BUILDERS = {
    "label": LabelView, "button": ButtonView, "checkbox": CheckboxView, "slider": SliderView, "combo": ComboView, "text": TextView, "separator": SeparatorView,
    "progress": ProgressView, "qt": QtView,
}


class ModuleView:
    """A plugin's module in a tool tab: a collapsible panel (the same as EFAS's own modules) holding the plugin's controls."""

    def __init__(self, panel: CollapsiblePanel, on_removed):
        self.panel = panel
        self._on_removed = on_removed
        self._views: list[WidgetView] = []

    def add_widget(self, spec: dict) -> WidgetView:
        view = _BUILDERS[spec["type"]](spec)
        self.panel.body().addWidget(view.widget)
        self._views.append(view)
        return view

    def set_title(self, title: str) -> None:
        self.panel._title = title
        self.panel._header.findChild(QLabel).setText(title)

    def clear(self) -> None:
        for view in self._views:
            self.panel.body().removeWidget(view.widget)
            view.widget.setParent(None)
            view.widget.deleteLater()
        self._views.clear()

    def expand(self) -> None:
        self.panel.set_expanded(True)

    def collapse(self) -> None:
        self.panel.collapse_now()

    def remove(self) -> None:
        self.clear()
        self._on_removed(self)
        self.panel.setParent(None)
        self.panel.deleteLater()
