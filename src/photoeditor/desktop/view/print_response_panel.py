from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from ...features.printresponse import logic as pr
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_PREVIEW_THROTTLE_MS = 33
_SETTLE_DEBOUNCE_MS = 200
_LABEL_WIDTH = 96


class _ResponsePlot(QWidget):
    """The response drawn as a curve: the straight diagonal for no change, and the shaped line over it."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._values = (0.0, 0.0, pr.WIDTH_DEFAULT, 0.0, pr.WIDTH_DEFAULT)
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(110)

    def sizeHint(self) -> QSize:
        return QSize(180, 110)

    def set_values(self, snap: float, toe: float, toe_width: float, shoulder: float, shoulder_width: float) -> None:
        self._values = (snap, toe, toe_width, shoulder, shoulder_width)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        side = min(box.width(), box.height())
        box = QRectF(box.center().x() - side / 2, box.top(), side, side)
        painter.fillRect(box, QColor(THEME.bg_input))
        painter.setPen(QPen(QColor(THEME.text_muted), 1, Qt.PenStyle.DotLine))
        for i in (1, 2, 3):
            painter.drawLine(QPointF(box.left() + side * i / 4, box.top()), QPointF(box.left() + side * i / 4, box.bottom()))
            painter.drawLine(QPointF(box.left(), box.top() + side * i / 4), QPointF(box.right(), box.top() + side * i / 4))
        painter.setPen(QPen(QColor(THEME.text_muted), 1))
        painter.drawLine(QPointF(box.left(), box.bottom()), QPointF(box.right(), box.top()))
        painter.drawRect(box)
        path = QPainterPath()
        for i, (x, y) in enumerate(pr.curve_points(*self._values)):
            point = (box.left() + x * side, box.bottom() - y * side)
            path.moveTo(*point) if i == 0 else path.lineTo(*point)
        painter.setPen(QPen(QColor(THEME.accent_primary), 2))
        painter.drawPath(path)
        painter.end()


class PrintResponseToolPanel(CollapsiblePanel):
    """Print Response, under WB Correction: Snap, Toe and Shoulder - the shape of a print's characteristic curve (features/printresponse/logic.py), drawn as a
    small graph. Same two-tier preview / full-recompute split as the other tone modules, carrying all five values in one signal pair."""

    changed = pyqtSignal(float, float, float, float, float)
    preview_requested = pyqtSignal(float, float, float, float, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Print Response",
            help_text=(
                "The shape of a print's response curve. Snap makes the midtones punchier (+) or gentler (-) while black and white stay where they are. Toe "
                "shapes how the shadows fade into black: + is a gentler, film-like fade, - sends them to black faster. Shoulder shapes how the highlights "
                "roll off into white: + protects highlight detail, - pushes them harder towards white. Toe Width and Shoulder Width set how far each "
                "roll-off reaches into the picture. The graph shows the result: the diagonal is no change. Double-click a slider to reset it."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._plot = _ResponsePlot()
        body.addWidget(self._plot)

        rows = QVBoxLayout()
        rows.setSpacing(THEME.space_sm)
        self._snap = SliderRow("Snap", min_value=-pr.SNAP_RANGE, max_value=pr.SNAP_RANGE, reset_value=0.0, decimals=2, step=0.01, label_width=_LABEL_WIDTH)
        self._toe = SliderRow("Toe", min_value=-pr.TOE_RANGE, max_value=pr.TOE_RANGE, reset_value=0.0, decimals=2, step=0.01, label_width=_LABEL_WIDTH)
        self._toe_width = SliderRow("Toe Width", min_value=pr.WIDTH_MIN, max_value=pr.WIDTH_MAX, reset_value=pr.WIDTH_DEFAULT, decimals=1, step=0.1, label_width=_LABEL_WIDTH)
        self._shoulder = SliderRow("Shoulder", min_value=-pr.SHOULDER_RANGE, max_value=pr.SHOULDER_RANGE, reset_value=0.0, decimals=2, step=0.01, label_width=_LABEL_WIDTH)
        self._shoulder_width = SliderRow("Shoulder Width", min_value=pr.WIDTH_MIN, max_value=pr.WIDTH_MAX, reset_value=pr.WIDTH_DEFAULT, decimals=1, step=0.1,
                                         label_width=_LABEL_WIDTH)
        for row, tip in (
            (self._snap, "Punchier (+) or gentler (-) midtones around mid grey; black and white stay where they are"),
            (self._toe, "How shadows fade into black: + a gentler, film-like fade; - to black faster"),
            (self._toe_width, "How far the toe's roll-off reaches up into the midtones"),
            (self._shoulder, "How highlights roll off into white: + protects highlight detail; - pushes them harder towards white"),
            (self._shoulder_width, "How far the shoulder's roll-off reaches down into the midtones"),
        ):
            row.setToolTip(tip)
            row.value_changed.connect(self._on_value_changed)
            rows.addWidget(row)
        body.addLayout(rows)

        self._pending_preview: tuple | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_THROTTLE_MS)
        self._preview_timer.timeout.connect(self._flush_pending_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(_SETTLE_DEBOUNCE_MS)
        self._settle_timer.timeout.connect(self._on_settled)

    def _current(self) -> tuple[float, float, float, float, float]:
        return (self._snap.value(), self._toe.value(), self._toe_width.value(), self._shoulder.value(), self._shoulder_width.value())

    def reset(self) -> None:
        """Back to neutral without emitting anything - used when a new file is opened, since the controller has already reset its own state."""
        self._settle_timer.stop()
        self._pending_preview = None
        self.set_values(0.0, 0.0, pr.WIDTH_DEFAULT, 0.0, pr.WIDTH_DEFAULT)

    def set_values(self, snap: float, toe: float, toe_width: float, shoulder: float, shoulder_width: float) -> None:
        """Sync the sliders and the graph without emitting anything - used by reset() and after a history revert."""
        self._snap.set_value(snap)
        self._toe.set_value(toe)
        self._toe_width.set_value(toe_width)
        self._shoulder.set_value(shoulder)
        self._shoulder_width.set_value(shoulder_width)
        self._plot.set_values(snap, toe, toe_width, shoulder, shoulder_width)

    def _on_value_changed(self, _value: float) -> None:
        values = self._current()
        self._plot.set_values(*values)
        if self._preview_timer.isActive():
            self._pending_preview = values
        else:
            self.preview_requested.emit(*values)
            self._preview_timer.start()
        self._settle_timer.start()

    def _flush_pending_preview(self) -> None:
        if self._pending_preview is not None:
            values, self._pending_preview = self._pending_preview, None
            self.preview_requested.emit(*values)
            self._preview_timer.start()

    def _on_settled(self) -> None:
        self.changed.emit(*self._current())
