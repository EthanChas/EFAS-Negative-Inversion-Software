from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QWidget

from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel

_LIST_HEIGHT = 100


class VersionsPanel(CollapsiblePanel):
    """Virtual copies of the open photo: several complete edits of one scan (colour and black and white, two crops), switched between here."""

    new_requested = pyqtSignal(str)
    switch_requested = pyqtSignal(str)
    rename_requested = pyqtSignal(str, str)
    delete_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Versions",
            help_text=(
                "A virtual copy is another complete edit of the same photo, with no second file. Make Virtual Copy starts from the edit you have now and "
                "switches to the copy, so the version you were on stays exactly as it was. Double-click a version (or press Switch) to edit it. "
                "The Workbench marks photos that have copies (x2), and an export preset can include them (the copy's name is added to its file name). "
                "Ratings, flags and tags belong to the photo, so all versions share them."
            ),
            start_expanded=False,
            parent=parent,
        )
        self.setMinimumWidth(220)
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._has_photo = False
        self._rows: list[tuple[str, bool]] = []

        self._list = QListWidget()
        self._list.setMaximumHeight(_LIST_HEIGHT)
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        self._list.itemDoubleClicked.connect(lambda _item: self._switch())
        body.addWidget(self._list)
        self._new_btn = QPushButton("Make Virtual Copy")
        self._new_btn.setToolTip("Copy the edit as it is now into a new version and switch to it")
        self._new_btn.clicked.connect(lambda: self.new_requested.emit(""))
        body.addWidget(self._new_btn)
        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        self._switch_btn = QPushButton("Switch")
        self._switch_btn.clicked.connect(self._switch)
        self._rename_btn = QPushButton("Rename")
        self._rename_btn.clicked.connect(self._rename)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setToolTip("Delete the selected version (switch away from it first if you are editing it)")
        self._delete_btn.clicked.connect(self._delete)
        for b in (self._switch_btn, self._rename_btn, self._delete_btn):
            row.addWidget(b)
        body.addLayout(row)
        self._hint = QLabel("")
        self._hint.setProperty("role", "hint")
        self._hint.setWordWrap(True)
        body.addWidget(self._hint)
        self._sync_buttons()

    def set_has_photo(self, has: bool) -> None:
        self._has_photo = has
        self._sync_buttons()

    def set_versions(self, rows: list[tuple[str, bool]], select: str | None = None) -> None:
        """rows: (name, is the one being edited) for the open photo."""
        self._rows = list(rows)
        self._list.clear()
        for name, active in rows:
            self._list.addItem(QListWidgetItem(f"●  {name}   (editing)" if active else f"    {name}"))
        names = [n for n, _a in rows]
        if select in names:
            self._list.setCurrentRow(names.index(select))
        self._hint.setText("" if len(rows) > 1 else "This photo has one version. Make a virtual copy to try a second edit.")
        self._sync_buttons()

    def _selected(self) -> tuple[str, bool] | None:
        row = self._list.currentRow()
        return self._rows[row] if 0 <= row < len(self._rows) and self._list.selectedItems() else None

    def _sync_buttons(self) -> None:
        picked = self._selected() if self._has_photo else None
        self._new_btn.setEnabled(self._has_photo)
        self._switch_btn.setEnabled(bool(picked) and not picked[1])
        self._rename_btn.setEnabled(bool(picked))
        self._delete_btn.setEnabled(bool(picked) and not picked[1])

    def _switch(self) -> None:
        picked = self._selected()
        if picked and not picked[1]:
            self.switch_requested.emit(picked[0])

    def _rename(self) -> None:
        from PyQt6.QtWidgets import QInputDialog

        picked = self._selected()
        if not picked:
            return
        name, ok = QInputDialog.getText(self, "Rename version", "Name:", text=picked[0])
        if ok and name.strip():
            self.rename_requested.emit(picked[0], name.strip())

    def _delete(self) -> None:
        picked = self._selected()
        if picked and not picked[1]:
            self.delete_requested.emit(picked[0])
