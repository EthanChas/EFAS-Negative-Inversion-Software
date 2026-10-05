from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPaintEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

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
        row.addStretch(1)

        self.help_button = CaptionButton("help")
        row.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignVCenter)

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
