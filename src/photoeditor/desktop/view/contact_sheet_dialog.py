from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget

from ...features.contactsheet.logic import MAX_COLUMNS, MIN_COLUMNS, PAGE_SIZES, SheetOptions, cell_layout
from ...theme.tokens import THEME


class ContactSheetDialog(QDialog):
    """The options for a contact sheet PDF: columns, paper size and orientation, and whether rejected frames are included. OK leads on to
    choosing where to save it; the pages-needed line updates as the choices change."""

    def __init__(self, frame_count: int, rejected_count: int, initial: SheetOptions, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Contact Sheet (PDF)")
        self._frame_count = frame_count
        self._rejected_count = rejected_count

        outer = QVBoxLayout(self)
        outer.setSpacing(THEME.space_lg)
        form = QFormLayout()
        form.setSpacing(THEME.space_md)
        self._columns = QSpinBox()
        self._columns.setRange(MIN_COLUMNS, MAX_COLUMNS)
        self._columns.setValue(initial.columns)
        form.addRow("Columns", self._columns)
        self._page = QComboBox()
        self._page.addItems(list(PAGE_SIZES))
        self._page.setCurrentText(initial.page)
        form.addRow("Paper", self._page)
        self._orientation = QComboBox()
        self._orientation.addItems(["Landscape", "Portrait"])
        self._orientation.setCurrentText("Landscape" if initial.landscape else "Portrait")
        form.addRow("Orientation", self._orientation)
        outer.addLayout(form)

        self._rejected = QCheckBox(f"Include rejected frames ({rejected_count})")
        self._rejected.setChecked(initial.include_rejected)
        self._rejected.setEnabled(rejected_count > 0)
        self._rejected.setToolTip("Rejected frames are shown faded with a red cross; left out, the other frames keep their numbers")
        outer.addWidget(self._rejected)

        self._summary = QLabel()
        self._summary.setStyleSheet(f"color: {THEME.text_hint};")
        outer.addWidget(self._summary)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = QPushButton("Choose File...")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        outer.addLayout(buttons)

        for signal in (self._columns.valueChanged, self._page.currentIndexChanged, self._orientation.currentIndexChanged, self._rejected.toggled):
            signal.connect(self._update_summary)
        self._update_summary()

    def options(self) -> SheetOptions:
        return SheetOptions(
            columns=self._columns.value(),
            page=self._page.currentText(),
            landscape=self._orientation.currentText() == "Landscape",
            include_rejected=self._rejected.isChecked(),
        )

    def _update_summary(self) -> None:
        o = self.options()
        shown = self._frame_count - (0 if o.include_rejected else self._rejected_count)
        pages = len(cell_layout(o, shown))
        self._summary.setText(f"{shown} frame{'s' if shown != 1 else ''} on {pages} page{'s' if pages != 1 else ''}")
