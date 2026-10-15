from PyQt6.QtCore import QEvent, QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QStyle, QTreeWidget, QTreeWidgetItem, QWidget

from ...features.presettree import logic as tree

NAME_ROLE = Qt.ItemDataRole.UserRole  # a preset row: the name as stored
FOLDER_ROLE = Qt.ItemDataRole.UserRole + 1  # a folder row: its path


class PresetTree(QTreeWidget):
    """A list of names shown as a tree (folders and presets, see features/presettree): "B&W/Number 1" is Number 1 inside B&W. Used for the Presets list and the Film
    Profiles list. Folders open and close with a click or double-click and are remembered while the list is rebuilt."""

    activated_name = pyqtSignal(str)  # a preset was double-clicked
    hovered = pyqtSignal(str)  # the mouse rests on a preset
    hover_left = pyqtSignal()  # the mouse left the list, or is over a folder
    context_requested = pyqtSignal(str, str, QPoint)  # "preset" or "folder", its name or path, where on screen

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._open: set[str] = set()  # folders the person opened (casefolded paths); the rest start closed
        self._known: set[str] = set()
        self._tips: dict[str, str] = {}
        self.itemEntered.connect(self._on_entered)
        self.itemDoubleClicked.connect(self._on_double_clicked)
        self.itemExpanded.connect(lambda item: self._remember(item, True))
        self.itemCollapsed.connect(lambda item: self._remember(item, False))
        self.customContextMenuRequested.connect(self._on_context)
        self.viewport().installEventFilter(self)

    # ------------------------------------------------------------ filling
    def set_names(self, names: list[str], select: str | None = None, tips: dict[str, str] | None = None, empty_text: str = "") -> None:
        """Show these names as a tree. A folder seen for the first time starts closed; one the person opened stays open, and the folders above a selected preset are opened to show it. `select` is a name to select."""
        self.blockSignals(True)
        self.clear()
        self._tips = {tree.clean_path(k).casefold(): v for k, v in (tips or {}).items()}
        nodes = tree.build(names)
        if not nodes and empty_text:
            placeholder = QTreeWidgetItem([empty_text])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addTopLevelItem(placeholder)
        selected: QTreeWidgetItem | None = None
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)

        def add(node: tree.Node, parent: QTreeWidgetItem | None) -> None:
            nonlocal selected
            item = QTreeWidgetItem([node.label])
            (parent.addChild(item) if parent is not None else self.addTopLevelItem(item))
            if node.is_folder:
                item.setData(0, FOLDER_ROLE, node.path)
                item.setIcon(0, folder_icon)
                for child in node.children:
                    add(child, item)
                key = node.path.casefold()
                self._known.add(key)
                item.setExpanded(key in self._open)
            else:
                item.setData(0, NAME_ROLE, node.full)
                tip = self._tips.get(node.path.casefold(), "")
                if tip:
                    item.setToolTip(0, tip)
                if select is not None and tree.clean_path(select).casefold() == node.path.casefold():
                    selected = item

        for node in nodes:
            add(node, None)
        self.blockSignals(False)
        if selected is not None:
            self._reveal(selected)
            self.setCurrentItem(selected)

    def _reveal(self, item: QTreeWidgetItem) -> None:
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            self._remember(parent, True)
            parent = parent.parent()

    def _remember(self, item: QTreeWidgetItem, opened: bool) -> None:
        path = item.data(0, FOLDER_ROLE)
        if path:
            (self._open.add if opened else self._open.discard)(path.casefold())

    # ------------------------------------------------------------ what is picked
    def selected_name(self) -> str | None:
        item = self.currentItem()
        return item.data(0, NAME_ROLE) if item is not None and item.data(0, NAME_ROLE) else None

    def selected_folder(self) -> str:
        """The folder of the selection: the folder itself, or the one a preset sits in ("" at the top)."""
        item = self.currentItem()
        if item is None:
            return ""
        path = item.data(0, FOLDER_ROLE)
        return path if path else tree.parent(item.data(0, NAME_ROLE) or "")

    def select_name(self, name: str) -> bool:
        """Select a preset by its name (opening the folders above it)."""
        found: list[QTreeWidgetItem] = []

        def walk(item: QTreeWidgetItem) -> None:
            if item.data(0, NAME_ROLE) == name:
                found.append(item)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.topLevelItemCount()):
            walk(self.topLevelItem(i))
        if found:
            self._reveal(found[0])
            self.setCurrentItem(found[0])
        return bool(found)

    def names_in_view(self) -> list[str]:
        out: list[str] = []

        def walk(item: QTreeWidgetItem) -> None:
            if item.data(0, NAME_ROLE):
                out.append(item.data(0, NAME_ROLE))
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.topLevelItemCount()):
            walk(self.topLevelItem(i))
        return out

    # ------------------------------------------------------------ events
    def _on_entered(self, item: QTreeWidgetItem, _column: int) -> None:
        name = item.data(0, NAME_ROLE)
        if name:
            self.hovered.emit(name)
        else:
            self.hover_left.emit()

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        name = item.data(0, NAME_ROLE)
        if name:
            self.activated_name.emit(name)
        else:
            item.setExpanded(not item.isExpanded())

    def _on_context(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        self.setCurrentItem(item)
        name, folder = item.data(0, NAME_ROLE), item.data(0, FOLDER_ROLE)
        if name:
            self.context_requested.emit("preset", name, self.viewport().mapToGlobal(pos))
        elif folder:
            self.context_requested.emit("folder", folder, self.viewport().mapToGlobal(pos))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport() and event.type() in (QEvent.Type.Leave, QEvent.Type.Hide):
            self.hover_left.emit()
        return super().eventFilter(watched, event)
