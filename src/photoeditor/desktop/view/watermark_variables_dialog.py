"""The list of $(NAME) variables a watermark text or SVG marker can use, with what each is for the open photo - so the names do not have to be remembered."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QDialog, QHeaderView, QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ...theme.tokens import THEME

_SYNTAX = (
    "Put a name in $( ) in a watermark's text or in an SVG marker: $(CAMERA), $(EXIF.YEAR). Add a default with a minus sign, $(FILM-no film), or something to show only when the value is there, "
    "$(EXIF.YEAR+(c) ). $(CAMERA:0:8) takes the first eight letters, $(FILE.NAME^^) makes capitals, $(FILE.NAME/_/ ) swaps the first underscore for a space ($(FILE.NAME//_/ ) every one). "
    "In an SVG marker these also work: $(WATERMARK_TEXT), $(WATERMARK_COLOR), $(WATERMARK_FONT_FAMILY), $(WATERMARK_FONT_STYLE) and $(WATERMARK_FONT_WEIGHT), filled in from the marker's own "
    "Text, Colour and Font above. Double-click a row to copy its name."
)


class WatermarkVariablesDialog(QDialog):
    """Name and current value of every variable, filtered by the search box. Double-clicking a row copies `$(NAME)`."""

    def __init__(self, values: dict[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Watermark Variables")
        self.resize(620, 560)
        layout = QVBoxLayout(self)
        layout.setSpacing(THEME.space_sm)
        note = QLabel(_SYNTAX)
        note.setWordWrap(True)
        note.setProperty("role", "hint")
        layout.addWidget(note)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search the names and values")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)
        shown = {k: v for k, v in values.items() if k != "NL"}
        self._table = QTableWidget(len(shown), 2)
        self._table.setHorizontalHeaderLabels(["Name", "Value for this photo"])
        self._table.verticalHeader().hide()
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for row, (name, value) in enumerate(sorted(shown.items())):
            key = QTableWidgetItem(f"$({name})")
            key.setData(Qt.ItemDataRole.UserRole, name)
            self._table.setItem(row, 0, key)
            self._table.setItem(row, 1, QTableWidgetItem(value if value else "(empty)"))
        self._table.cellDoubleClicked.connect(self._copy)
        layout.addWidget(self._table, 1)
        self._status = QLabel("")
        self._status.setProperty("role", "hint")
        layout.addWidget(self._status)

    def _filter(self, text: str) -> None:
        words = text.casefold().split()
        for row in range(self._table.rowCount()):
            haystack = f"{self._table.item(row, 0).text()} {self._table.item(row, 1).text()}".casefold()
            self._table.setRowHidden(row, not all(w in haystack for w in words))

    def _copy(self, row: int, _column: int) -> None:
        text = self._table.item(row, 0).text()
        QGuiApplication.clipboard().setText(text)
        self._status.setText(f"Copied {text}")

    def names(self) -> list[str]:
        """The names listed, as written ($(NAME)); for tests."""
        return [self._table.item(row, 0).text() for row in range(self._table.rowCount())]
