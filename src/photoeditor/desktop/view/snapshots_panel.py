from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QWidget

from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel

_LIST_HEIGHT = 110


class SnapshotsPanel(CollapsiblePanel):
    """Named versions of the open photo's edits: take one, try something else, come back to it. A snapshot keeps everything about the edit (tone,
    color, crop, rotation, dust repairs, watermark...), unlike a preset, which is a look to share between photos. It only asks
    (the *_requested signals); the controller does the work."""

    take_requested = pyqtSignal(str)
    apply_requested = pyqtSignal(str)
    update_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Snapshots",
            help_text=(
                "A snapshot saves everything about this photo's edit under a name - tone, color, crop, rotation, dust repairs, watermark - so you can "
                "try another look and come back. Double-click a snapshot (or press Apply) to go back to it; that is one undoable step. Update "
                "overwrites the selected snapshot with the photo as it is now. Snapshots belong to the photo; presets are for sharing looks."
            ),
            start_expanded=False,
            parent=parent,
        )
        self.setMinimumWidth(220)
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._has_photo = False
        self._names: list[str] = []

        self._list = QListWidget()
        self._list.setMaximumHeight(_LIST_HEIGHT)
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        self._list.itemDoubleClicked.connect(lambda _item: self._apply())
        body.addWidget(self._list)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Snapshot name")
        self._name.returnPressed.connect(self._take)
        body.addWidget(self._name)
        self._take_btn = QPushButton("Take Snapshot")
        self._take_btn.setToolTip("Save this photo's edit as it is now under that name (an empty name numbers it)")
        self._take_btn.clicked.connect(self._take)
        body.addWidget(self._take_btn)

        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._apply)
        self._update_btn = QPushButton("Update")
        self._update_btn.setToolTip("Overwrite the selected snapshot with the photo as it is now")
        self._update_btn.clicked.connect(self._update)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._delete)
        for b in (self._apply_btn, self._update_btn, self._delete_btn):
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

    def set_snapshots(self, rows: list[tuple[str, str]], select: str | None = None) -> None:
        """rows: (name, when it was taken) for the open photo, newest first."""
        self._names = [n for n, _when in rows]
        self._list.clear()
        for name, when in rows:
            self._list.addItem(QListWidgetItem(f"{name}   ({when[:16]})" if when else name))
        if select in self._names:
            self._list.setCurrentRow(self._names.index(select))
        self._hint.setText("" if rows else "No snapshots of this photo yet")
        self._sync_buttons()

    def _selected(self) -> str | None:
        row = self._list.currentRow()
        return self._names[row] if 0 <= row < len(self._names) and self._list.selectedItems() else None

    def _sync_buttons(self) -> None:
        picked = self._selected() is not None and self._has_photo
        self._take_btn.setEnabled(self._has_photo)
        self._name.setEnabled(self._has_photo)
        for b in (self._apply_btn, self._update_btn, self._delete_btn):
            b.setEnabled(picked)

    def _take(self) -> None:
        if self._has_photo:
            name = self._name.text().strip()
            self._name.clear()
            self.take_requested.emit(name)

    def _apply(self) -> None:
        name = self._selected()
        if name:
            self.apply_requested.emit(name)

    def _update(self) -> None:
        name = self._selected()
        if name:
            self.update_requested.emit(name)

    def _delete(self) -> None:
        name = self._selected()
        if name:
            self.delete_requested.emit(name)
