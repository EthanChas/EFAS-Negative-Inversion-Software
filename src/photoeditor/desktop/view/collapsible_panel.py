from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPaintEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from ...theme.tokens import THEME
from .bevel_widgets import BevelPanel, CaptionButton

_NO_MAX = 16777215  # Qt's own QWIDGETSIZE_MAX - "no cap" for maximumHeight


class _CollapsibleHeader(QWidget):
    """A flat gray header bar - the same look as EthanDailyClocker's DATE
    panel header (Win98's inactive-title-bar gray, black text), but with a
    collapse arrow added on the left. Clicking anywhere on the bar (not just
    the arrow button) toggles it, the way a real accordion header works."""

    clicked = pyqtSignal()

    def __init__(self, title: str, collapsible: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(THEME.font_size_header + THEME.space_lg)

        row = QHBoxLayout(self)
        row.setContentsMargins(THEME.space_sm, 0, THEME.space_sm, 0)
        row.setSpacing(THEME.space_sm)

        self.arrow_button: CaptionButton | None = None
        if collapsible:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.arrow_button = CaptionButton("collapse")
            row.addWidget(self.arrow_button, 0, Qt.AlignmentFlag.AlignVCenter)

        label = QLabel(title)
        label.setProperty("role", "mini_header_text")
        # So a click on the title still reaches this widget's own
        # mousePressEvent below, instead of being swallowed by the label.
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

        # "PRESET: name" in small grey beside the title while a module preset is applied; nothing at all otherwise
        self.preset_label = QLabel("")
        self.preset_label.setStyleSheet(f"color: {THEME.text_muted}; font-size: {THEME.font_size_small}pt;")
        self.preset_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.preset_label.hide()
        row.addWidget(self.preset_label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)

        # Reset and Presets: shown only on the panels that opt in (see CollapsiblePanel.enable_module_buttons)
        self.reset_button = CaptionButton("refresh")
        self.reset_button.setToolTip("Reset this module to its defaults")
        self.presets_button = CaptionButton("menu")
        self.presets_button.setToolTip("Presets for this module: load one, store the current settings as a new one")
        for button in (self.reset_button, self.presets_button):
            button.hide()
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.help_button = CaptionButton("help")
        row.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_preset_name(self, name: str | None) -> None:
        if not name:
            self.preset_label.hide()
            self.preset_label.setToolTip("")
            return
        shown = name if len(name) <= 16 else name[:15] + "..."
        self.preset_label.setText(f"PRESET: {shown}")
        self.preset_label.setToolTip(f"The preset '{name}' is applied to this module")
        self.preset_label.show()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(THEME.border_color))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class CollapsiblePanel(BevelPanel):
    """A raised-bevel "mini application window" (EthanDailyClocker's
    MiniAppPanel look) whose body slides open/closed under its header -
    click the arrow, the "?", or anywhere else on the header bar. Add
    content via `.body()`, not `.layout()` (that's the outer frame's own
    layout, already spoken for by the header)."""

    toggled = pyqtSignal(bool)  # True = expanded

    def __init__(
        self,
        title: str,
        help_text: str = "",
        start_expanded: bool = True,
        collapsible: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(sunken=False, bg=THEME.bg_app, thickness=THEME.border_width, parent=parent)
        self._title = title
        self._help_text = help_text
        self._collapsible = collapsible
        self._expanded = start_expanded
        self._module_update_button: QPushButton | None = None

        self._header = _CollapsibleHeader(title, collapsible=collapsible)
        if collapsible:
            self._header.arrow_button.set_expanded(start_expanded)
            self._header.arrow_button.clicked.connect(self.toggle)
            self._header.clicked.connect(self.toggle)
        self._header.help_button.clicked.connect(self._show_help)
        self.layout().addWidget(self._header)

        self._body_container = QWidget()
        self._body_layout = QVBoxLayout(self._body_container)
        self._body_layout.setContentsMargins(
            THEME.space_sm, THEME.space_sm, THEME.space_sm, THEME.space_sm
        )
        self.layout().addWidget(self._body_container)
        if collapsible and not start_expanded:
            self._body_container.setMaximumHeight(0)

        self._animation = QPropertyAnimation(self._body_container, b"maximumHeight", self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._animation.finished.connect(self._on_animation_finished)

    def body(self) -> QVBoxLayout:
        return self._body_layout

    def enable_module_buttons(self) -> None:
        """Show a Reset button and a Presets (menu) button in the header, next to the help button. The panel only provides the buttons;
        whoever uses it connects reset_button.clicked and presets_button.clicked."""
        self._header.reset_button.show()
        self._header.presets_button.show()
        if self._module_update_button is None:  # at the top of the body, shown only while the loaded preset has been changed
            self._module_update_button = QPushButton("Update Preset")
            self._module_update_button.hide()
            self._body_layout.insertWidget(0, self._module_update_button)

    def enable_reset_button(self, tooltip: str) -> CaptionButton:
        """Show just the Reset button in the header (no presets), for panels that only need to put their own controls back to default."""
        self._header.reset_button.setToolTip(tooltip)
        self._header.reset_button.show()
        return self._header.reset_button

    @property
    def update_preset_button(self) -> QPushButton | None:
        return self._module_update_button

    def set_preset_status(self, name: str | None, modified: bool) -> None:
        """name is the preset loaded on this module (or None); the Update Preset button shows only while its values have been changed."""
        self._header.set_preset_name(name)
        button = self._module_update_button
        if button is None:
            return
        button.setVisible(bool(name) and modified)
        if name:
            button.setToolTip(f"Save the current settings over the preset '{name}'")
            button.setText(f"Update Preset  ({name})" if len(name) <= 18 else "Update Preset")

    @property
    def reset_button(self) -> CaptionButton:
        return self._header.reset_button

    @property
    def presets_button(self) -> CaptionButton:
        return self._header.presets_button

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        if not self._collapsible or expanded == self._expanded:
            return
        self._expanded = expanded
        self._header.arrow_button.set_expanded(expanded)

        target = self._body_container.sizeHint().height() if expanded else 0
        self._animation.stop()
        self._animation.setStartValue(self._body_container.height())
        self._animation.setEndValue(target)
        self._animation.start()
        self.toggled.emit(expanded)

    def _on_animation_finished(self) -> None:
        # Release the cap once fully open, so later content changes (e.g.
        # stats text wrapping to another line) aren't clipped at whatever
        # height happened to be current when the panel was last opened.
        if self._expanded:
            self._body_container.setMaximumHeight(_NO_MAX)

    def _show_help(self) -> None:
        if self._help_text:
            QMessageBox.information(self, self._title, self._help_text)
