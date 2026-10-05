from PyQt6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QToolButton, QVBoxLayout, QWidget

from ...theme.tokens import THEME
from .bevel_widgets import thin_sunken_panel

_COLLAPSED_WIDTH = 44
_EXPANDED_WIDTH = 150
_BUTTON_SIZE = 40
_BLANK_ICON_SIZE = 22
_HOVER_DURATION_MS = 150
_HOVER_EASING = QEasingCurve.Type.InOutQuad
_NO_MAX = 16777215  # Qt's own QWIDGETSIZE_MAX - "no cap" for maximumWidth


class ToolRail(QWidget):
    """A vertical strip of icon tool buttons on the left of the tool-panel
    row - narrow (icon only) normally, widening on hover to show each tab's
    name next to its icon. Clicking a tab toggles it on/off; the caller
    (AppWindow) decides what that means - here it's just a rail."""

    tab_toggled = pyqtSignal(str, bool)  # tab id, now-checked

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(_COLLAPSED_WIDTH)
        self.setMaximumWidth(_COLLAPSED_WIDTH)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, THEME.space_sm, 2, THEME.space_sm)
        self._layout.setSpacing(2)
        self._layout.addStretch(1)  # tabs pinned to the top

        self._buttons: dict[str, QToolButton] = {}

        # minimumWidth and maximumWidth are animated together, in lockstep,
        # rather than leaving minimumWidth fixed at _COLLAPSED_WIDTH: with
        # only maximumWidth raised, this rail would compete for space with
        # anything else in its row that also wants to grow, and Qt clips -
        # doesn't elide - a tool button's text when it loses that fight,
        # mangling the label ("WB Correction" became "WB Cltion"). Locking
        # min=max at every frame makes the rail's width non-negotiable, so
        # the rail's label is always shown in full.
        self._max_animation = QPropertyAnimation(self, b"maximumWidth", self)
        self._max_animation.setDuration(_HOVER_DURATION_MS)
        self._max_animation.setEasingCurve(_HOVER_EASING)
        self._max_animation.finished.connect(self._on_animation_finished)

        self._min_animation = QPropertyAnimation(self, b"minimumWidth", self)
        self._min_animation.setDuration(_HOVER_DURATION_MS)
        self._min_animation.setEasingCurve(_HOVER_EASING)

    def add_tab(self, tab_id: str, icon: QPixmap | None, label: str) -> None:
        button = QToolButton()
        button.setCheckable(True)
        if icon is None:
            # A genuinely blank icon, not just an unset one - Qt/Fusion draws
            # a stray placeholder glyph for a null QIcon in icon-only mode,
            # which is worse than a blank tab for a tab with no icon yet.
            icon = QPixmap(_BLANK_ICON_SIZE, _BLANK_ICON_SIZE)
            icon.fill(Qt.GlobalColor.transparent)
        button.setIcon(QIcon(icon))
        button.setText(label)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setMinimumHeight(_BUTTON_SIZE)
        # QToolButton's default horizontal size policy is Preferred, not
        # Expanding - without this it just takes its own natural
        # (icon-sized) width in this QVBoxLayout instead of filling the
        # frame around it, leaving the frame's own padding looking uneven.
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.clicked.connect(lambda checked, tid=tab_id: self.tab_toggled.emit(tid, checked))
        self._buttons[tab_id] = button

        # Each tab gets its own snug sunken frame (not one frame around the
        # whole rail) - it just inherits the rail's current width like any
        # other child in this QVBoxLayout, so it widens/narrows in step with
        # the rail's own hover animation without needing one of its own.
        frame = thin_sunken_panel(h_margin=1, v_margin=1)
        frame.layout().addWidget(button)
        self._layout.insertWidget(self._layout.count() - 1, frame)

    def set_tab_checked(self, tab_id: str, checked: bool) -> None:
        """Sync a tab's checked look to an external toggle without
        re-emitting tab_toggled - setChecked() alone never fires clicked(),
        only a real user click does, so this can't loop back into whatever
        called it."""
        button = self._buttons.get(tab_id)
        if button is not None:
            button.setChecked(checked)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        for button in self._buttons.values():
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._animate_to(_EXPANDED_WIDTH)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._animate_to(_COLLAPSED_WIDTH)

    def _animate_to(self, target: int) -> None:
        self._max_animation.stop()
        self._min_animation.stop()
        self._max_animation.setStartValue(self.maximumWidth())
        self._max_animation.setEndValue(target)
        self._min_animation.setStartValue(self.minimumWidth())
        self._min_animation.setEndValue(target)
        self._max_animation.start()
        self._min_animation.start()

    def _on_animation_finished(self) -> None:
        if self.maximumWidth() <= _COLLAPSED_WIDTH:
            for button in self._buttons.values():
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)


class SlideOutPanel(QWidget):
    """Wraps a single content widget, animating its own maximumWidth between
    0 and the content's natural width - the horizontal counterpart to
    CollapsiblePanel's vertical slide, used for a tool tab's dropdown.

    Also overrides sizeHint() to follow that same open/closed target: a box
    layout sizes a stretch-0 item from its sizeHint(), not its
    maximumWidth() (that's only an upper cap on top of it) - without this,
    the panel would default to its content's own smallest possible layout
    even with maximumWidth raised to let it be wider.

    The caller keeps this at stretch=0 with a trailing addStretch(1) in its
    row (see AppWindow), the same structure that reliably pins the rail to
    the left when this is closed - a real widget's stretch factor is no
    substitute for an actual spacer: when this is capped to 0 width, a
    stretch factor on it just leaves unclaimed surplus space that Qt has no
    guaranteed left-aligned way to dispose of (it can end up centering the
    row instead), where a plain addStretch(1) always absorbs it. Instead,
    sizeHint() itself reports "fill the rest" (recomputed live, not a
    cached value) while open, which a stretch-0 item still gets in full
    before any trailing stretch sees a leftover to claim."""

    def __init__(self, content: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMaximumWidth(0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content)
        self._content = content
        self._is_open = False

        self._animation = QPropertyAnimation(self, b"maximumWidth", self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._animation.finished.connect(self._on_animation_finished)

    def sizeHint(self) -> QSize:
        return QSize(self._target_width(), super().sizeHint().height())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            parent.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if (
            watched is self.parentWidget()
            and event.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest)
            and self._is_open
        ):
            self.updateGeometry()
        return False

    def _target_width(self) -> int:
        if not self._is_open:
            return 0
        parent = self.parentWidget()
        fallback = self._content.sizeHint().width()
        return max(fallback, parent.width() - self.x()) if parent else fallback

    def set_open(self, open_: bool) -> None:
        self._is_open = open_
        target = self._target_width()

        self._animation.stop()
        self._animation.setStartValue(self.width())
        self._animation.setEndValue(target)
        self._animation.start()
        self.updateGeometry()

    def _on_animation_finished(self) -> None:
        if self._is_open:
            self.setMaximumWidth(_NO_MAX)
