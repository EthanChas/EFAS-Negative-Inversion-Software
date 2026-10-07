from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QWidget

from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel

_LIST_MAX_HEIGHT = 150


class LookPresetsPanel(CollapsiblePanel):
    """Saved looks, under History: save the open photo's tone, color, film type, sharpening and watermark under a name, then put it on
    any photo with Apply (or a double-click) - or on the whole folder. The panel only asks for names and confirmations; the controller
    keeps the presets."""

    save_requested = pyqtSignal(str)
    apply_requested = pyqtSignal(str)
    apply_folder_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    advanced_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Presets",
            help_text=(
                "Save the open photo's look (tone, color, film type, sharpening, watermark) under a name, then apply it to any photo - "
                "double-click a preset, or select it and press Apply. Cropping, rotation and dust repairs are never part of a preset."
            ),
            start_expanded=False,
            parent=parent,
        )
        self.setMinimumWidth(220)
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._names: list[str] = []
        self._has_photo = False

        self._list = QListWidget()
        self._list.setMaximumHeight(_LIST_MAX_HEIGHT)
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        self._list.itemDoubleClicked.connect(lambda _item: self._apply())
        body.addWidget(self._list)

        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._apply)
        self._folder_btn = QPushButton("To Folder...")
        self._folder_btn.setToolTip("Apply the selected preset to every photo in this photo's folder")
        self._folder_btn.clicked.connect(self._apply_folder)
        row.addWidget(self._apply_btn)
        row.addWidget(self._folder_btn)
        body.addLayout(row)

        self._advanced_btn = QPushButton("Advanced Preset Edit")
        self._advanced_btn.setToolTip("Open every module of the selected preset and edit its values")
        self._advanced_btn.clicked.connect(self._advanced)
        body.addWidget(self._advanced_btn)

        row2 = QHBoxLayout()
        row2.setSpacing(THEME.space_sm)
        self._save_btn = QPushButton("Save Current...")
        self._save_btn.setToolTip("Save this photo's look as a preset")
        self._save_btn.clicked.connect(self._save)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._delete)
        row2.addWidget(self._save_btn, 1)
        row2.addWidget(self._delete_btn)
        body.addLayout(row2)

        self.set_presets([])

    def set_presets(self, names: list[str], select: str | None = None) -> None:
        self._names = list(names)
        self._list.clear()
        if not names:
            placeholder = QListWidgetItem("No presets yet.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)
        for name in names:
            self._list.addItem(name)
            if select is not None and name.casefold() == select.casefold():
                self._list.setCurrentRow(self._list.count() - 1)
        self._sync_buttons()

    def set_has_photo(self, has_photo: bool) -> None:
        self._has_photo = has_photo
        self._sync_buttons()

    def selected(self) -> str | None:
        row = self._list.currentRow()
        return self._names[row] if self._names and 0 <= row < len(self._names) else None

    def _sync_buttons(self) -> None:
        picked = self.selected() is not None
        self._apply_btn.setEnabled(picked and self._has_photo)
        self._folder_btn.setEnabled(picked and self._has_photo)
        self._delete_btn.setEnabled(picked)
        self._advanced_btn.setEnabled(picked)
        self._save_btn.setEnabled(self._has_photo)

    def _apply(self) -> None:
        name = self.selected()
        if name is not None and self._has_photo:
            self.apply_requested.emit(name)

    def _advanced(self) -> None:
        name = self.selected()
        if name is not None:
            self.advanced_requested.emit(name)

    def _apply_folder(self) -> None:
        name = self.selected()
        if name is not None and self._has_photo:
            self.apply_folder_requested.emit(name)

    def _save(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Preset", "Name for this look:", text=self.selected() or "")
        name = " ".join(name.split())
        if not ok or not name:
            return
        if any(n.casefold() == name.casefold() for n in self._names):
            answer = QMessageBox.question(
                self, "Save Preset", f"A preset called '{name}' already exists. Replace it with this photo's look?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.save_requested.emit(name)

    def _delete(self) -> None:
        name = self.selected()
        if name is None:
            return
        answer = QMessageBox.question(
            self, "Delete Preset", f"Delete the preset '{name}'? Photos it was applied to keep their edits.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(name)
