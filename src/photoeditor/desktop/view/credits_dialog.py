from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...theme.tokens import THEME

_CREDITS = (
    "<p><b>Credits &amp; inspiration</b></p>"
    "<p>This editor was inspired by three programs, and borrows ideas from all of them:</p>"
    "<ul>"
    "<li><b>darktable</b> - the free, open-source darkroom: focus peaking, the per-module presets and reset buttons, "
    "the way modules are laid out. <a href=\"https://www.darktable.org\">darktable.org</a></li>"
    "<li><b>NegPy</b> - a free, open-source film-negative editor: the negative inversion and metering ideas, "
    "dust and scratch repair, local contrast (CLAHE), the clone tool and more. Parts of this app are adapted "
    "from its code (GPL-3.0). <a href=\"https://github.com/marcinz606/NegPy\">github.com/marcinz606/NegPy</a></li>"
    "<li><b>Adobe Lightroom</b> - culling with flags and stars, presets, the histogram and clipping views, "
    "contact sheets. <a href=\"https://www.adobe.com/products/photoshop-lightroom.html\">adobe.com/lightroom</a></li>"
    "</ul>"
    "<p>Please go and check them out - they are fantastic programs, and well worth your time.</p>"
    "<p>The AI dust detection runs a small model from the FilmDefectNet project.</p>"
)


class CreditsDialog(QDialog):
    """Info > Credits: who this app was inspired by, with links."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Credits")
        self.setMinimumWidth(460)
        outer = QVBoxLayout(self)
        outer.setSpacing(THEME.space_lg)
        label = QLabel(_CREDITS)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(True)  # the links open in the browser
        label.setStyleSheet(f"a {{ color: {THEME.accent_hover}; }}")
        outer.addWidget(label)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close.setDefault(True)
        row.addWidget(close)
        outer.addLayout(row)
