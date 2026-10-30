"""Where a theme puts things (theme/elements.py, the Layout group): the order and choice of the panels in the column beside the picture, which side that column is on, the tool rail's
tabs and side, and where the filmstrip sits. The window hands over the pieces once it is built; `apply()` reads the theme in force and arranges them, and is called again whenever a
theme is put in force. A panel or tab a theme leaves out is only put away: it comes back when a theme lists it again."""
from PyQt6.QtCore import QEvent, QObject, QTimer
from PyQt6.QtWidgets import QBoxLayout, QWidget

from ...theme.elements import LEFT_PANELS, TOOL_TABS
from ...theme.tokens import THEME


class _Keeper(QObject):
    """Keeps a panel a theme has left out put away: the window shows and hides panels for its own reasons (Tab hides them all, a view hides the filmstrip), and must not bring it back."""

    def __init__(self, widget: QWidget, hidden: set):
        super().__init__(widget)
        self._widget = widget
        self._hidden = hidden
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self._widget and event.type() == QEvent.Type.Show and self._hidden is not None and id(obj) in self._hidden:
            QTimer.singleShot(0, lambda: obj.hide() if id(obj) in self._hidden else None)
        return False


class ThemeLayout:
    def __init__(self, window, *, panels: dict, left_column: QBoxLayout, splitter, side_panes: tuple, rail, rail_row: QBoxLayout, frame_layout: QBoxLayout, filmstrip: QWidget):
        """`panels`: the left column's panels by name (LEFT_PANELS); `side_panes`: (the column of panels' pane, the modules' pane) as they sit in the splitter; `rail_row`: the layout
        holding the tool rail beside the modules; `frame_layout`: the window's own vertical layout, which holds the filmstrip."""
        self.window = window
        self.panels = panels
        self.left_column = left_column
        self.splitter = splitter
        self.left_pane, self.right_pane = side_panes
        self.rail = rail
        self.rail_row = rail_row
        self.frame_layout = frame_layout
        self.filmstrip = filmstrip
        self._away: set[int] = set()        # ids of the widgets a theme has put away
        self._keepers: dict[int, _Keeper] = {}
        self._applied: tuple | None = None
        self.swapped = False

    # ------------------------------------------------------------ helpers
    def _put_away(self, widget: QWidget, away: bool) -> None:
        key = id(widget)
        if away:
            self._away.add(key)
            if key not in self._keepers:
                self._keepers[key] = _Keeper(widget, self._away)
            widget.hide()
        elif key in self._away:
            self._away.discard(key)
            widget.show()

    def _items(self, layout: QBoxLayout) -> list:
        return [layout.itemAt(i) for i in range(layout.count())]

    # ------------------------------------------------------------ the pieces
    def _arrange_panels(self, wanted: list[str]) -> None:
        listed = [n for n in wanted if n in self.panels]
        rest = [n for n in self.panels if n not in listed]
        # take every panel out of the column (the stretch at its end too), put the listed ones back in order, then the left-out ones (put away), then the stretch
        for name in self.panels:
            self.left_column.removeWidget(self.panels[name])
        for i in range(self.left_column.count() - 1, -1, -1):
            item = self.left_column.itemAt(i)
            if item.spacerItem() is not None:
                self.left_column.takeAt(i)
        for name in (*listed, *rest):
            self.left_column.addWidget(self.panels[name])
        self.left_column.addStretch(1)
        for name in listed:
            self._put_away(self.panels[name], False)
        for name in rest:
            self._put_away(self.panels[name], True)

    def _arrange_sides(self, left_side: bool, widths: tuple[int, int]) -> None:
        panes = [self.splitter.widget(i) for i in range(self.splitter.count())]
        centre = next(w for w in panes if w is not self.left_pane and w is not self.right_pane)
        order = [self.left_pane, centre, self.right_pane] if left_side else [self.right_pane, centre, self.left_pane]
        if panes != order:
            sizes = self.splitter.sizes()
            by_widget = dict(zip(panes, sizes))
            for index, widget in enumerate(order):
                self.splitter.insertWidget(index, widget)
            self.splitter.setSizes([by_widget.get(w, 0) for w in order])
        self.swapped = not left_side
        for width, pane in zip(widths, (self.left_pane, self.right_pane)):
            if width > 0:
                sizes = self.splitter.sizes()
                index = self.splitter.indexOf(pane)
                give = width - sizes[index]
                centre_index = self.splitter.indexOf(centre)
                sizes[index] = width
                sizes[centre_index] = max(100, sizes[centre_index] - give)
                self.splitter.setSizes(sizes)

    def _arrange_rail(self, rail_left: bool) -> None:
        self.rail_row.removeWidget(self.rail)
        if rail_left:
            self.rail_row.insertWidget(0, self.rail)
        else:
            self.rail_row.insertWidget(self.rail_row.count() - 1, self.rail)       # before the stretch that ends the row

    def _arrange_filmstrip(self, where: str) -> None:
        self.frame_layout.removeWidget(self.filmstrip)
        if where == "top":
            self.frame_layout.insertWidget(self._first_page_index(), self.filmstrip, 0)
        else:
            self.frame_layout.addWidget(self.filmstrip, 0)
        self._put_away(self.filmstrip, where == "hidden")

    def _first_page_index(self) -> int:
        """Just above the page that holds the splitter (below the title bar and the menu bar)."""
        for i, item in enumerate(self._items(self.frame_layout)):
            widget = item.widget()
            if widget is not None and widget.isAncestorOf(self.splitter):
                return i
        return max(0, self.frame_layout.count() - 1)

    # ------------------------------------------------------------ applying
    def apply(self, first: bool = False) -> None:
        """Arrange the window as the theme in force says. Only what changed since the last time is redone; the widths are set when a theme is put in force, not when the program starts
        (the widths you dragged to are kept then)."""
        panels = [w.strip() for w in str(THEME.get("layout_left_panels")).split(",") if w.strip()]
        tabs = [w.strip() for w in str(THEME.get("layout_tool_tabs")).split(",") if w.strip()]
        side = THEME.get("layout_side_panels")
        rail = THEME.get("layout_tool_rail")
        strip = THEME.get("layout_filmstrip")
        widths = (0, 0) if first else (THEME.get("layout_left_width"), THEME.get("layout_sidebar_width"))
        signature = (tuple(panels), tuple(tabs), side, rail, strip)
        if signature != self._applied:
            self._arrange_panels(panels or list(LEFT_PANELS))
            self.rail.set_theme_tabs(tabs or list(TOOL_TABS))
            self._arrange_rail(rail == "left")
            self._arrange_filmstrip(strip)
            self._applied = signature
        self._arrange_sides(side == "left", widths)
