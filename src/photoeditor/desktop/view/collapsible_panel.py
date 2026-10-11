from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QLinearGradient, QPainter, QPaintEvent
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from ...theme.tokens import THEME
from .bevel_widgets import BevelPanel, CaptionButton
from .module_style import AUTOMATIC, NAMED, PLAIN, STYLE

_NO_MAX = 16777215
HOVER_OPEN_MS = 220
HOVER_CLOSE_MS = 400


class _CollapsibleHeader(QWidget):
    """A flat gray header bar - the same look as EthanDailyClocker's DATE
    panel header (Win98's inactive-title-bar gray, black text), but with a
    collapse arrow added on the left. Clicking anywhere on the bar (not just
    the arrow button) toggles it, the way a real accordion header works."""

    clicked = pyqtSignal()

    def __init__(self, title: str, collapsible: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self._title = title
        self.setFixedHeight(THEME.font_size_header + THEME.space_lg)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._colour_menu)

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
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.preset_label = QLabel("")
        self.preset_label.setStyleSheet(f"color: {THEME.text_muted}; font-size: {THEME.font_size_small}pt;")
        self.preset_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.preset_label.hide()
        row.addWidget(self.preset_label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)

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
        colours = STYLE.gradient(self._title)
        if colours is None:
            painter.fillRect(self.rect(), QColor(THEME.border_color))
            return
        gradient = QLinearGradient(QPointF(0, 0), QPointF(self.width(), 0))
        gradient.setColorAt(0.0, colours[0])
        gradient.setColorAt(1.0, colours[1])
        painter.fillRect(self.rect(), gradient)

    def build_colour_menu(self) -> QMenu:
        """The right-click menu: this module's colour is automatic (its own assigned gradient), one of the named colours, or plain."""
        menu = QMenu(self)
        menu.setTitle(f"Colour of {self._title}")
        group = QActionGroup(menu)
        current = STYLE.choice(self._title)
        for label, value in [("Automatic", AUTOMATIC), *[(n, n) for n in NAMED], ("None (plain)", PLAIN)]:
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(current == value)
            action.triggered.connect(lambda _checked=False, v=value: STYLE.set_choice(self._title, v))
            group.addAction(action)
            menu.addAction(action)
        return menu

    def _colour_menu(self, pos) -> None:
        if STYLE.colours:
            self.build_colour_menu().exec(self.mapToGlobal(pos))

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

    toggled = pyqtSignal(bool)

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

        # opening on hover (a General setting): `pinned` panels were opened by a click and stay; the others close when the mouse leaves
        self._pinned = False
        self._inside = False
        self._open_timer = QTimer(self)
        self._open_timer.setSingleShot(True)
        self._open_timer.setInterval(HOVER_OPEN_MS)
        self._open_timer.timeout.connect(self._hover_open)
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.setInterval(HOVER_CLOSE_MS)
        self._close_timer.timeout.connect(self._hover_close)
        STYLE.changed.connect(self._header.update)
        STYLE.hover_changed.connect(self._on_hover_mode)

    def body(self) -> QVBoxLayout:
        return self._body_layout

    def enable_module_buttons(self) -> None:
        """Show a Reset button and a Presets (menu) button in the header, next to the help button."""
        self._header.reset_button.show()
        self._header.presets_button.show()
        if self._module_update_button is None:
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
        """A click on the header. With hover-open on, a click pins a hover-opened module open, and a second click closes it."""
        if STYLE.hover and self._collapsible:
            self._open_timer.stop()
            self._close_timer.stop()
            if self._expanded and self._pinned:
                self._pinned = False
                self.set_expanded(False)
            elif self._expanded:
                self._pinned = True
            else:
                self._pinned = True
                self.set_expanded(True)
            return
        self.set_expanded(not self._expanded)

    def is_pinned(self) -> bool:
        return self._pinned

    def _on_hover_mode(self, on: bool) -> None:
        """Turning hover-open on: whatever is open now was opened by the person, so it stays open until clicked."""
        self._open_timer.stop()
        self._close_timer.stop()
        if on:
            self._pinned = self._expanded

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._inside = True
        if STYLE.hover and self._collapsible:
            self._close_timer.stop()
            if not self._expanded:
                self._open_timer.start()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._inside = False
        self._open_timer.stop()
        if STYLE.hover and self._collapsible and self._expanded and not self._pinned:
            self._close_timer.start()

    def _hover_open(self) -> None:
        if STYLE.hover and self._inside and not self._expanded:
            self._pinned = False
            self.set_expanded(True)

    def _busy(self) -> bool:
        """Things that must not be interrupted by closing the module: a held mouse button (dragging a slider out of it), a drop-down list, typing in it."""
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton or QApplication.activePopupWidget() is not None:
            return True
        focus = QApplication.focusWidget()
        return bool(focus is not None and self.isAncestorOf(focus) and isinstance(focus, (QLineEdit, QAbstractSpinBox, QPlainTextEdit, QTextEdit)))

    def _hover_close(self) -> None:
        if not (STYLE.hover and self._expanded and not self._pinned) or self._inside:
            return
        if self._busy():
            self._close_timer.start()
            return
        self.set_expanded(False)

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
        if self._expanded:
            self._body_container.setMaximumHeight(_NO_MAX)

    def _show_help(self) -> None:
        if self._help_text:
            QMessageBox.information(self, self._title, self._help_text)
