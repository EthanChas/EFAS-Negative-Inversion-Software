from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QWidget,
)

from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel

_LIST_MAX_HEIGHT = 260


class HistoryPanel(CollapsiblePanel):
    """A constant, always-shown section underneath Masking - the same
    dedicated-section convention as White Balance (collapsible=False).
    An indented, numbered log of edits made to the open image this
    session - select an entry and click Revert (after a confirmation) to
    restore the image to that point; later entries are then discarded."""

    revert_requested = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "History",
            help_text=(
                "A running log of edits made to the open image. Select an "
                "entry and click Revert to go back to that point - edits "
                "made after it are discarded."
            ),
            collapsible=False,
            parent=parent,
        )
        self.setMinimumWidth(220)
        body = self.body()
        body.setSpacing(THEME.space_sm)

        self._has_entries = False

        list_row = QHBoxLayout()
        list_row.setContentsMargins(THEME.space_lg, 0, 0, 0)
        self._list = QListWidget()
        self._list.setMaximumHeight(_LIST_MAX_HEIGHT)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        list_row.addWidget(self._list)
        body.addLayout(list_row)

        self._revert_btn = QPushButton("Revert")
        self._revert_btn.setEnabled(False)
        self._revert_btn.clicked.connect(self._on_revert_clicked)
        body.addWidget(self._revert_btn)

        self.set_entries([])

    def set_entries(self, descriptions: list[str]) -> None:
        self._list.clear()
        self._has_entries = bool(descriptions)
        if not descriptions:
            placeholder = QListWidgetItem("No edits yet.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(placeholder)
        else:
            for index, text in enumerate(descriptions):
                self._list.addItem(f"{index + 1}. {text}")
        self._revert_btn.setEnabled(False)

    def _on_selection_changed(self) -> None:
        self._revert_btn.setEnabled(self._has_entries and self._list.currentRow() >= 0)

    def _on_revert_clicked(self) -> None:
        index = self._list.currentRow()
        if not self._has_entries or index < 0:
            return
        confirm = QMessageBox.question(
            self,
            "Revert",
            "Revert to this point? Edits made after it will be discarded.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.revert_requested.emit(index)
