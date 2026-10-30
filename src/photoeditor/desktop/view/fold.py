"""Sections inside a module that fold, after NegPy's modules: each titled group of controls (FILM BASE, METERING, WHITE / BLACK POINT...) gets a chevron beside its title and closes to just its
title, so a long module reads as a few compartments you open when you need them. `fold_sections` makes them from a module's layout as it was built (a title is a label with role "subtitle");
which are closed is remembered between sessions."""

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QLayout, QLayoutItem, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from ...features.settings import logic as app_settings
from ...theme.tokens import THEME
from . import panel_icons
from .module_style import STYLE
from .dividers import ROLE as DIVIDER_ROLE
from .slide import Slide

# the icon beside a section's title, by the title (an icon file of assets/icon)
SECTION_ICONS = {
    "film base": "film", "scan quality": "scan-line", "inversion method": "contrast", "conversion": "chart-spline", "noritsu look": "printer", "metering": "sun", "white / black point": "sun-moon",
    "color trim": "palette", "on the scan": "scan-line", "on the picture": "frame", "straighten": "rotate-ccw", "distortion correction": "maximize", "lens correction": "focus", "keystone": "layout-grid",
    "balance by tone": "color-balance", "scanner colour": "printer", "placement": "frame", "canister": "canister", "camera and lens": "camera",
}


class _Body(QWidget):
    """The controls of a section, set in from the left with a thin accent rail and a faint tint down their side, so a group reads as belonging to its title."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(4, 0, self.width() - 4, self.height(), QColor(255, 255, 255, 9))
        rail = QColor(THEME.accent_primary)
        rail.setAlpha(150)
        painter.fillRect(3, 0, 2, self.height(), rail)


def _is_title(widget) -> bool:
    return isinstance(widget, QLabel) and widget.property("role") == "subtitle"


def _widgets_in(item: QLayoutItem) -> list[QWidget]:
    """The widgets a layout item puts in the section: itself if it is a widget, else those in its rows (a widget's own parts are not counted: only the widget is hidden or shown)."""
    out: list[QWidget] = []
    widget = item.widget()
    if widget is not None:
        out.append(widget)
        return out
    layout = item.layout()
    if layout is not None:
        for i in range(layout.count()):
            out += _widgets_in(layout.itemAt(i))
    return out


class _Watch(QObject):
    """Tells a section when a control inside it is shown or hidden (a module hides the controls that do not belong to the mode it is in), so a section with nothing showing goes too."""

    def __init__(self, section: "FoldSection"):
        super().__init__(section)
        self._section = section
        self._pending = False

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.HideToParent, QEvent.Type.ShowToParent) and not self._pending:
            self._pending = True
            QTimer.singleShot(0, self._run)
        return False

    def _run(self) -> None:
        self._pending = False
        self._section.sync()


class FoldSection(QWidget):
    """A title with a chevron, and the controls it folds."""

    folded = pyqtSignal(str, bool)       # (key, closed)
    ANIMATE = True                       # the group slides open and shut (the tests that look at it straight after a click turn this off)
    SLIDE_MS = 160
    HEAD_BUTTON_HEIGHT = 22              # the title bar is 28 high with 3 of room above and below

    def __init__(self, key: str, title: QLabel, extras: list[QLayoutItem], closed: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self._title = title
        self._closed = closed
        self._items: list[QLayoutItem] = []
        self._watched: list[QWidget] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._head = QWidget()      # the title bar: a darker rounded band behind the chevron, the icon and the title
        self._head.setObjectName("foldhead")
        self._head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        head = QHBoxLayout(self._head)
        head.setContentsMargins(4, 3, 6, 3)
        self._head.setFixedHeight(28)
        self._restyle_head()
        STYLE.changed.connect(self._restyle_head)
        self._chevron = QToolButton()
        self._chevron.setAutoRaise(True)
        self._chevron.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._chevron.setToolTip("Fold or open this section")
        self._chevron.clicked.connect(self.toggle)
        head.addWidget(self._chevron)
        icon_name = SECTION_ICONS.get(title.text().strip().lower())
        if icon_name:
            icon = QLabel()
            icon.setPixmap(panel_icons.pixmap(icon_name, 14, THEME.text_secondary))
            icon.setFixedWidth(18)
            head.addWidget(icon)
        head.addWidget(title, 1)
        for item in extras:
            if item.widget() is not None:
                widget = item.widget()
                if isinstance(widget, QAbstractButton) and not isinstance(widget, QToolButton):
                    widget.setFixedHeight(self.HEAD_BUTTON_HEIGHT)      # a button beside a title sits inside the title bar, not taller than it
                    widget.setStyleSheet("QPushButton { padding: 0px 10px; min-height: 0px; }")
                head.addWidget(widget)
            elif item.layout() is not None:
                head.addLayout(item.layout())
        outer.addWidget(self._head)
        outer.addSpacing(3)
        self._body = _Body()
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(12, 3, 0, 3)
        self._layout.setSpacing(4)
        self._clip = QWidget()      # what slides: the body keeps its full size inside it
        clip_layout = QVBoxLayout(self._clip)
        clip_layout.setContentsMargins(0, 0, 0, 0)
        clip_layout.addWidget(self._body)
        outer.addWidget(self._clip)
        self._slide = Slide(self, self._clip, self._body, self.SLIDE_MS)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._watch = _Watch(self)
        title.installEventFilter(self)
        title.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply()

    def _restyle_head(self) -> None:
        self._head.setStyleSheet(f"#foldhead {{ background: {THEME.bg_input}; border: 1px solid {THEME.border_color}; border-radius: 6px; }}"
                                 f"#foldhead:hover {{ border-color: {THEME.text_muted}; }}")

    def eventFilter(self, obj, event):
        if obj is self._title and event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            self.toggle()
            return True
        return super().eventFilter(obj, event)

    def add_item(self, item: QLayoutItem) -> None:
        """Move a layout item (a widget or a row of them) into the section."""
        if item.widget() is not None:
            self._layout.addWidget(item.widget())
        elif item.layout() is not None:
            self._layout.addLayout(item.layout())
        else:
            return
        self._items.append(item)
        for w in _widgets_in(item):
            w.installEventFilter(self._watch)
            self._watched.append(w)

    def is_closed(self) -> bool:
        return self._closed

    def toggle(self) -> None:
        self.set_closed(not self._closed)

    def set_closed(self, closed: bool, announce: bool = True) -> None:
        if closed == self._closed:
            return
        self._closed = closed
        self._apply(animate=True)
        if announce:
            self.folded.emit(self.key, closed)

    def _apply(self, animate: bool = False) -> None:
        self._chevron.setArrowType(Qt.ArrowType.RightArrow if self._closed else Qt.ArrowType.DownArrow)
        if animate and self.ANIMATE:
            self._slide.go(not self._closed)
        else:
            self._slide.snap(not self._closed)

    def sync(self) -> None:
        """Show the section when any control in it is showing (the title does not count)."""
        shown = any(not w.isHidden() for w in self._watched if not _is_title(w))
        if shown != (not self.isHidden()):
            self.setVisible(shown)


def fold_sections(layout: QVBoxLayout, scope: str, state: dict[str, bool] | None = None, start_closed: tuple[str, ...] = ()) -> list[FoldSection]:
    """Turn the titled groups of a module's layout into FoldSections. A title is a subtitle label standing in the layout (or leading a row of the layout: the rest of the row stays beside it
    in the header); everything after it up to the next title is the group's, and the thin dividers between groups are dropped (the title's chevron is the divider now). `state` says
    which sections the person closed or opened (key -> closed); `start_closed` are the titles that start closed until they choose. Controls before the first title stay where they are."""
    state = state or {}
    items = [layout.takeAt(0) for _ in range(layout.count())]

    def title_of(item):
        widget = item.widget()
        if _is_title(widget):
            return widget, []
        row = item.layout()
        if row is not None and row.count() and _is_title(row.itemAt(0).widget()):
            return row.itemAt(0).widget(), [row.takeAt(1) for _ in range(row.count() - 1)]
        return None, []

    sections: list[FoldSection] = []
    current: FoldSection | None = None
    for item in items:
        title, extras = title_of(item)
        if title is not None:
            extras = [e for e in extras if e is not None and (e.widget() is not None or e.layout() is not None)]
            name = title.text().strip().title() or "section"
            key = f"{scope}/{name}"
            current = FoldSection(key, title, extras, closed=state.get(key, name.upper() in start_closed))
            sections.append(current)
            layout.addWidget(current)
            continue
        widget = item.widget()
        if widget is not None and widget.property("role") == DIVIDER_ROLE:
            widget.hide()
            layout.addItem(item) if current is None else None
            continue
        if item.spacerItem() is not None and current is not None:
            continue
        if current is None:
            layout.addItem(item)
        else:
            current.add_item(item)
    for section in sections:
        section.sync()
    return sections


def folded_state() -> dict[str, bool]:
    """Which sections the person closed (True) or opened (False), from the settings."""
    return dict(app_settings.get("folded_sections") or {})


def remember(key: str, closed: bool) -> None:
    state = folded_state()
    state[key] = bool(closed)
    app_settings.save({"folded_sections": state})
