import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...features.proofs import logic as proofs
from ...theme.tokens import THEME

_CELL_W, _CELL_H = 176, 132
_GAP = 6
_LEFT, _TOP = 92, 44


def _qimage(rgb: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(rgb)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()


class ProofGrid(QWidget):
    """The 5 x 5 mosaic: every tile a real render, the centre one the photo as it is. Click a tile to pick it."""

    picked = pyqtSignal(int, int)  # row, column

    def __init__(self, kind: str, tiles: list[np.ndarray], parent: QWidget | None = None):
        super().__init__(parent)
        self._kind = proofs.KINDS[kind]
        self._tiles = [_qimage(t) for t in tiles]
        self._hover: tuple[int, int] | None = None
        n = proofs.GRID
        self.setFixedSize(_LEFT + n * _CELL_W + (n - 1) * _GAP + 8, _TOP + n * _CELL_H + (n - 1) * _GAP + 8)
        self.setMouseTracking(True)

    def _cell_rect(self, row: int, col: int) -> QRectF:
        return QRectF(_LEFT + col * (_CELL_W + _GAP), _TOP + row * (_CELL_H + _GAP), _CELL_W, _CELL_H)

    def _cell_at(self, pos: QPointF) -> tuple[int, int] | None:
        for row in range(proofs.GRID):
            for col in range(proofs.GRID):
                if self._cell_rect(row, col).contains(pos):
                    return row, col
        return None

    def mouseMoveEvent(self, event) -> None:
        cell = self._cell_at(event.position())
        if cell != self._hover:
            self._hover = cell
            self.setCursor(Qt.CursorShape.PointingHandCursor if cell else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event) -> None:
        self._hover = None
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at(event.position())
            if cell is not None:
                self.picked.emit(*cell)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(THEME.bg_app))
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        p.setFont(small)
        k = self._kind
        mid = proofs.GRID // 2
        for col in range(proofs.GRID):  # what each column changes, over it
            r = self._cell_rect(0, col)
            p.setPen(QColor(THEME.text_primary if col == mid else THEME.text_secondary))
            p.drawText(QRectF(r.left(), 6, r.width(), 16), Qt.AlignmentFlag.AlignCenter, proofs.axis_label(k.columns, col))
        p.setPen(QColor(THEME.text_hint))
        first, last = self._cell_rect(0, 0), self._cell_rect(0, proofs.GRID - 1)
        p.drawText(QRectF(first.left(), 22, 200, 16), Qt.AlignmentFlag.AlignLeft, f"← {k.columns.ends[0]}")
        p.drawText(QRectF(last.right() - 200, 22, 200, 16), Qt.AlignmentFlag.AlignRight, f"{k.columns.ends[1]} →")
        p.drawText(QRectF(first.left() + 200, 22, last.right() - first.left() - 400, 16), Qt.AlignmentFlag.AlignCenter, k.columns.title)
        for row in range(proofs.GRID):
            r = self._cell_rect(row, 0)
            p.setPen(QColor(THEME.text_primary if row == mid else THEME.text_secondary))
            p.drawText(QRectF(4, r.top(), _LEFT - 10, r.height() / 2), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, proofs.axis_label(k.rows, row))
            if row in (0, proofs.GRID - 1):
                p.setPen(QColor(THEME.text_hint))
                text = f"↑ {k.rows.ends[0]}" if row == 0 else f"{k.rows.ends[1]} ↓"
                p.drawText(QRectF(4, r.top() + r.height() / 2, _LEFT - 10, r.height() / 2), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, text)
        for row in range(proofs.GRID):
            for col in range(proofs.GRID):
                rect = self._cell_rect(row, col)
                p.fillRect(rect, QColor(0, 0, 0))
                image = self._tiles[row * proofs.GRID + col]
                scale = min(rect.width() / image.width(), rect.height() / image.height())
                w, h = image.width() * scale, image.height() * scale
                p.drawImage(QRectF(rect.left() + (rect.width() - w) / 2, rect.top() + (rect.height() - h) / 2, w, h), image)
                if (row, col) == (mid, mid):
                    p.setPen(QPen(QColor(THEME.accent_hover), 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(rect.adjusted(1, 1, -1, -1))
                elif (row, col) == self._hover:
                    p.setPen(QPen(QColor(255, 255, 255, 230), 2))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(rect.adjusted(1, 1, -1, -1))
        p.end()


class ProofDialog(QDialog):
    """Test Strip / Ring-Around: the photo printed 25 ways at once. Click a tile and its values become the photo's (one undoable step)."""

    def __init__(self, kind: str, tiles: list[np.ndarray], parent: QWidget | None = None):
        super().__init__(parent)
        k = proofs.KINDS[kind]
        self.setWindowTitle(k.title)
        self._choice: tuple[int, int] | None = None
        col = QVBoxLayout(self)
        col.setSpacing(THEME.space_md)
        hint = QLabel(k.hint)
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        col.addWidget(hint)
        self._grid = ProofGrid(kind, tiles)
        self._grid.picked.connect(self._pick)
        col.addWidget(self._grid)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton("Close")
        close.setToolTip("Leave the photo as it is")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        col.addLayout(row)

    def _pick(self, row: int, col: int) -> None:
        self._choice = (row, col)
        self.accept()

    def choice(self) -> tuple[int, int] | None:
        """The (row, column) picked, or None when the dialog was closed without one (or the centre tile - the photo as it is - was picked)."""
        mid = proofs.GRID // 2
        return None if self._choice in (None, (mid, mid)) else self._choice
