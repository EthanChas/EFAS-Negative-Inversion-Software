"""Confirming an automatically found film border: the raw scan with the suggested rectangle marked, what was found, and a clear choice."""

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ...features.lut.logic import to_uint8

_CONFIDENCE_TEXT = {
    "high": "Looks like the film border (high confidence).",
    "medium": "A uniform strip, probably the film border (medium confidence). Check the marked area before using it.",
    "low": "A uniform strip that might be the film border (low confidence). Check the marked area carefully.",
}


class RebateDialog(QDialog):
    """Shows where the film border was found. Nothing changes until 'Use This Film Base' is pressed."""

    def __init__(self, raw: np.ndarray, rebate, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Film border found")
        self.resize(820, 620)
        col = QVBoxLayout(self)
        a = np.ascontiguousarray(to_uint8(raw))
        h, w = a.shape[:2]
        pm = QPixmap.fromImage(QImage(a.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy())
        painter = QPainter(pm)
        painter.setPen(QPen(Qt.GlobalColor.green if rebate.confidence == "high" else Qt.GlobalColor.yellow, max(3, w // 300)))
        x1, y1, x2, y2 = rebate.rect
        painter.drawRect(x1, y1, x2 - x1, y2 - y1)
        painter.end()
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setPixmap(pm.scaled(780, 440, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        col.addWidget(self.image, 1)
        text = QLabel(f"{_CONFIDENCE_TEXT[rebate.confidence]}\n\n" + " ".join(rebate.reasons) +
                      "\n\nEFAS will use the marked area as the film base for every photo in this folder. Use it only if it is the clear, unexposed film, not the bare light "
                      "beyond the film, a frame line or part of the picture.")
        text.setWordWrap(True)
        col.addWidget(text)
        row = QHBoxLayout()
        use = QPushButton("Use This Film Base")
        use.setDefault(True)
        use.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(use)
        row.addWidget(cancel)
        col.addLayout(row)
