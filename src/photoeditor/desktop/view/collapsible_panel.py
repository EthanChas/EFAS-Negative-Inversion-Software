from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QLinearGradient, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from ...theme.tokens import THEME
from . import module_origin
from .bevel_widgets import BevelPanel, CaptionButton
from . import panel_icons
from .module_style import AUTOMATIC, NAMED, PLAIN, STYLE
from .slide import Slide

HOVER_OPEN_MS = 220
HOVER_CLOSE_MS = 400


class _PowerLight(QWidget):
    """The on/off light beside a module's name: green is on, red is off. A square in the Classic theme, a circle with a grey border in the others."""

    clicked = pyqtSignal()
    ON, OFF = "#2fb344", "#d63939"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._on = True
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()
        STYLE.changed.connect(self.update)
        self._tip()

    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool) -> None:
        if on != self._on:
            self._on = on
            self._tip()
            self.update()

    def _tip(self) -> None:
        self.setToolTip("On: this module is applied to the picture. Click to switch it off (its settings are kept)." if self._on
                        else "Off: the picture is made without this module, and its controls are greyed out. Click to switch it back on.")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        event.accept()  # not the header's: clicking the light must not open or close the module

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        colour = QColor(self.ON if self._on else self.OFF)
        if THEME.style == "classic":
            painter.fillRect(2, 2, 12, 12, QColor(0, 0, 0))
            painter.fillRect(3, 3, 10, 10, colour)
        else:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setBrush(colour)
            painter.setPen(QPen(QColor("#8a8f98"), 1.5))
            painter.drawEllipse(QRectF(2.0, 2.0, 12.0, 12.0))
        painter.end()


class _CollapsibleHeader(QWidget):
    """A flat gray header bar - the same look as EthanDailyClocker's DATE
    panel header (Win98's inactive-title-bar gray, black text), but with a
    collapse arrow added on the left. Clicking anywhere on the bar (not just
    the arrow button) toggles it, the way a real accordion header works."""

    clicked = pyqtSignal()

    def __init__(self, title: str, collapsible: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self._title = title
        self._hovered = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.apply_theme()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._colour_menu)

        self._row = row = QHBoxLayout(self)
        self._collapsible = collapsible
        self._set_margins()
        row.setSpacing(THEME.space_sm)

        self.arrow_button: CaptionButton | None = None
        if collapsible:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.arrow_button = CaptionButton("collapse")
            row.addWidget(self.arrow_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.power_light = _PowerLight()
        row.addWidget(self.power_light, 0, Qt.AlignmentFlag.AlignVCenter)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(16, 16)
        self._icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self._show_icon()

        label = QLabel(module_origin.display_title(title))
        label.setToolTip(module_origin.tooltip(title))
        label.setProperty("role", "mini_header_text")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._title_label = label
        label.setSizePolicy(QSizePolicy.Policy.Ignored, label.sizePolicy().verticalPolicy())      # (the title gives way when the panel is narrow: its buttons stay in view, and the title is cut, not the buttons)
        row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.changed_star = QLabel(self._MARKS["star"])      # a red star beside the name while something in the module is not at its default
        self._restyle_star()
        self.changed_star.setToolTip("Something in this module has been changed from its defaults")
        self.changed_star.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.changed_star.hide()
        row.addWidget(self.changed_star, 0, Qt.AlignmentFlag.AlignTop)

        self.preset_label = QLabel("")
        self.preset_label.setStyleSheet(f"color: {THEME.text_muted}; font-size: {THEME.font_size_small}pt;")
        self.preset_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.preset_label.hide()
        row.addWidget(self.preset_label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)

        self.instances_button = CaptionButton("instances")
        self.instances_button.setToolTip("Multiple instances: make another copy of this module, with its own settings and mask")
        self.instances_button.hide()
        row.addWidget(self.instances_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.reset_button = CaptionButton("refresh")
        self.reset_button.setToolTip("Reset this module to its defaults")
        self.presets_button = CaptionButton("menu")
        self.presets_button.setToolTip("Presets for this module: load one, store the current settings as a new one")
        for button in (self.reset_button, self.presets_button):
            button.hide()
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.help_button = CaptionButton("help")
        row.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignVCenter)

    def _set_margins(self) -> None:
        """A header with no collapse arrow starts with its icon, which has to clear the module's colour bar down the left edge in the modern themes."""
        bar = 0 if (self._collapsible or THEME.style != "modern") else THEME.space_md + 2
        self._row.setContentsMargins(THEME.space_sm + bar, 0, THEME.space_sm, 0)

    def _show_icon(self) -> None:
        """The icon file for this module's title, in the theme's colour; no icon (and no gap) for a title that has none."""
        pix = panel_icons.for_title(self._title, 16, THEME.text_primary)
        self._icon_label.setPixmap(pix)
        self._icon_label.setVisible(not pix.isNull())

    _MARKS = {"star": "*", "dot": "●", "bar": "|"}

    def _restyle_star(self) -> None:
        self.changed_star.setText(self._MARKS.get(THEME.get("changed_mark"), "*"))
        self.changed_star.setStyleSheet(f"color: {THEME.get('changed_star')}; font-weight: bold; font-size: {THEME.font_size_header + 3}pt;")

    def apply_theme(self) -> None:
        self.setFixedHeight(THEME.font_size_header + THEME.space_lg + (8 if THEME.style == "modern" else 0))
        if hasattr(self, "changed_star"):
            self._restyle_star()
        if hasattr(self, "_icon_label"):
            self._set_margins()
            self._show_icon()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def set_preset_name(self, name: str | None, modified: bool = False, full_name: str | None = None, scope: str = "module") -> None:
        """The small grey "PRESET: name" beside the title. `full_name` is what the tip names when the label shows a shortened one (a folder path); `modified` adds
        "(edited)" for a look whose values have been changed since it was applied; `scope` is what the preset was applied to ("module" or "photo")."""
        if not name:
            self.preset_label.hide()
            self.preset_label.setToolTip("")
            return
        shown = name if len(name) <= 16 else name[:15] + "..."
        self.preset_label.setText(f"PRESET: {shown}" + (" (edited)" if modified else ""))
        tip = f"The preset '{full_name or name}' is applied to this {scope}"
        self.preset_label.setToolTip(tip + (", and its settings have been changed since" if modified else ""))
        self.preset_label.show()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        colours = STYLE.gradient(self._title)
        if THEME.style == "modern":
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self._hovered and self.cursor().shape() == Qt.CursorShape.PointingHandCursor:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(THEME.bg_hover))
                painter.drawRoundedRect(QRectF(self.rect()).adjusted(3, 3, -3, -3), THEME.radius_sm, THEME.radius_sm)
            if colours is not None:  # the module's colour, as a slim bar down the left edge
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(colours[0].lighter(135))
                painter.drawRoundedRect(QRectF(5, 7, 3, self.height() - 14), 1.5, 1.5)
            painter.end()
            return
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
    power_toggled = pyqtSignal(bool)  # the light in the header was clicked: the state it asks for

    def __init__(
        self,
        title: str,
        help_text: str = "",
        start_expanded: bool = True,
        collapsible: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(sunken=False, bg=THEME.bg_app, parent=parent)
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

        self._body_container = QWidget()      # what slides (its height is what opens and shuts); the controls keep their full size inside it
        clip_layout = QVBoxLayout(self._body_container)
        clip_layout.setContentsMargins(0, 0, 0, 0)
        self._content = QWidget()
        self._body_layout = QVBoxLayout(self._content)
        self._body_layout.setContentsMargins(
            THEME.space_sm, THEME.space_sm, THEME.space_sm, THEME.space_sm
        )
        clip_layout.addWidget(self._content)
        self.layout().addWidget(self._body_container)
        if collapsible and not start_expanded:
            self._body_container.setMaximumHeight(0)

        self._slide = Slide(self, self._body_container, self._content, lambda: THEME.get("module_slide_ms"), QEasingCurve.Type.InOutQuad, hide_when_closed=False, opened=start_expanded or not collapsible)

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

    def enable_power_switch(self) -> None:
        """Show the on/off light in the header; clicking it sends power_toggled with the state it asks for (the owner decides, then calls set_power)."""
        light = self._header.power_light
        if not light.isHidden():
            return
        light.show()
        light.clicked.connect(lambda: self.power_toggled.emit(not light.is_on()))

    def set_power(self, on: bool) -> None:
        """Show the module as on (green) or off (red); an off module's controls are greyed out (the header stays usable)."""
        self._header.power_light.set_on(on)
        self._body_container.setEnabled(on)

    def power_on(self) -> bool:
        return self._header.power_light.is_on()

    def set_display_title(self, text: str) -> None:
        """The name shown in the header (a copy of a module is shown with its number and name); the module's own title still picks its icon and colour."""
        self._header._title_label.setText(module_origin.with_origin(text, self._title))

    def set_changed(self, changed: bool) -> None:
        """Show (or take away) the red star beside the module's name: its settings are not the ones it starts with."""
        self._header.changed_star.setVisible(bool(changed))

    def is_changed(self) -> bool:
        return not self._header.changed_star.isHidden()

    def enable_instance_button(self, tooltip: str | None = None) -> CaptionButton:
        """Show the multiple-instances button (two overlapping squares) in the header."""
        if tooltip:
            self._header.instances_button.setToolTip(tooltip)
        self._header.instances_button.show()
        return self._header.instances_button

    @property
    def instances_button(self) -> CaptionButton:
        return self._header.instances_button

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

    def set_preset_status(self, name: str | None, modified: bool, full_name: str | None = None, scope: str = "module", show_edited: bool = False) -> None:
        """name is the preset loaded on this module (or None); the Update Preset button shows only while its values have been changed. A panel that is not a module
        (the Presets panel, for a whole look) passes its own `scope` and `show_edited` to have "(edited)" in its label instead of a button."""
        self._header.set_preset_name(name, modified and show_edited, full_name, scope)
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

        self._slide.go(expanded)
        self.toggled.emit(expanded)

    def collapse_now(self) -> bool:
        """Close the module at once, without the slide - for a module nobody can see (its tab was just left). Returns whether it was open."""
        if not self._collapsible or not self._expanded:
            return False
        self._expanded = False
        self._pinned = False
        self._header.arrow_button.set_expanded(False)
        self._slide.snap(False)
        self.toggled.emit(False)
        return True

    def _show_help(self) -> None:
        if self._help_text:
            QMessageBox.information(self, self._title, self._help_text)
