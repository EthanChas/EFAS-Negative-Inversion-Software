from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QCheckBox, QGridLayout, QLabel, QPushButton, QWidget

from ...features.errormarks import logic as marks
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel


def _swatch(colour: str, size: int = 14) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setPen(QColor(255, 255, 255, 200))
    painter.setBrush(QColor(colour))
    painter.drawRect(0, 0, size - 1, size - 1)
    painter.end()
    return QIcon(pix)


class ErrorMarksPanel(CollapsiblePanel):
    """Negative tab > Error marking: pick a kind of fault, then drag boxes round that fault on the picture. Each kind has its own colour and name tag. The marks are
    notes kept with the photo (never part of the edit that is exported); the checkbox here, and View > Error Marks, show or hide them."""

    kind_chosen = pyqtSignal(str)  # the kind to mark now, or "" for none
    visibility_toggled = pyqtSignal(bool)
    clear_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Error marking",
            help_text=(
                "Pick a kind of fault below, then drag a box round it on the picture: scratches are red, watermarks yellow, transport lines dark navy, and so on. "
                "Each mark carries a tag with its name. Right-click a mark to change what it is or take it off. Marks are notes for you, kept with the photo; they "
                "are never part of the exported picture, and they stay on the fault if you crop, rotate or straighten afterwards. Show or hide them with the box "
                "below or View > Error Marks."
            ),
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._show = QCheckBox("Show error marks on the picture")
        self._show.setChecked(True)
        self._show.setToolTip("The same switch as View > Error Marks")
        self._show.toggled.connect(self.visibility_toggled)
        body.addWidget(self._show)

        title = QLabel("MARK A FAULT")
        title.setProperty("role", "subtitle")
        body.addWidget(title)
        grid = QGridLayout()
        grid.setSpacing(THEME.space_sm)
        self._buttons: dict[str, QPushButton] = {}
        for i, kind in enumerate(marks.KINDS):
            button = QPushButton(kind.label)
            button.setCheckable(True)
            button.setIcon(_swatch(kind.colour))
            button.setToolTip(f"{kind.hint}. Click, then drag a box round each one on the picture; click again to stop marking.")
            button.clicked.connect(lambda checked, k=kind.id: self._on_clicked(k, checked))
            self._buttons[kind.id] = button
            grid.addWidget(button, i // 2, i % 2)
        body.addLayout(grid)

        self._hint = QLabel("Drag a box on the picture. Right-click a mark to change or remove it.")
        self._hint.setWordWrap(True)
        self._hint.setProperty("role", "hint")
        body.addWidget(self._hint)
        self._summary = QLabel(marks.summary([]))
        self._summary.setWordWrap(True)
        body.addWidget(self._summary)
        self._clear = QPushButton("Clear all marks")
        self._clear.setToolTip("Take every mark off this photo (you are asked first)")
        self._clear.clicked.connect(self.clear_requested)
        body.addWidget(self._clear)
        self.set_summary([])

    def _on_clicked(self, kind_id: str, checked: bool) -> None:
        for other, button in self._buttons.items():
            if other != kind_id:
                button.setChecked(False)
        self.kind_chosen.emit(kind_id if checked else "")

    def active_kind(self) -> str:
        return next((k for k, b in self._buttons.items() if b.isChecked()), "")

    def set_active_kind(self, kind_id: str) -> None:
        """Show which kind is being marked, without sending anything."""
        for k, button in self._buttons.items():
            button.blockSignals(True)
            button.setChecked(k == kind_id)
            button.blockSignals(False)

    def set_marks_visible(self, visible: bool) -> None:
        self._show.blockSignals(True)
        self._show.setChecked(visible)
        self._show.blockSignals(False)

    def set_summary(self, found: list[dict]) -> None:
        self._summary.setText(marks.summary(found))
        self._clear.setEnabled(bool(found))
