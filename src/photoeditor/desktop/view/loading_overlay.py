from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from ...theme.tokens import THEME

_TICK_MS = 16
_ROLL_R = 28
_GAP = 150
_STRIP_H = 34
_FRAME_W, _FRAME_PITCH = 32, 36
_HOLE_PITCH = _FRAME_PITCH / 4
_PX_PER_TICK = 2.0
_DEGREES_PER_TICK = 4.0
_SCALE = 1.1


class LoadingOverlay(QWidget):
    """A full-covering veil with an animated film strip - a roll on the left (its mouth facing right) feeding film across into a mirrored roll
    on the right - and "Loading..." text, shown while AppController opens a file. The decode runs on a worker thread (see
    workers.run_blocking) while the UI event loop keeps turning, which is what lets the film actually travel instead of freezing mid-frame."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._shift = 0.0
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._advance)
        self.hide()

    def _advance(self) -> None:
        self._shift = (self._shift + _PX_PER_TICK) % _FRAME_PITCH
        self._angle = (self._angle + _DEGREES_PER_TICK) % 360
        self.update()

    def showEvent(self, event) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _draw_roll(self, painter: QPainter, center_x: float, center_y: float, facing: int) -> None:
        """One roll of film: facing=1 has its mouth (the slot the film passes through) on the right, facing=-1 is the mirror image."""
        r = _ROLL_R
        accent = QColor("#d6d6d6")
        painter.save()
        painter.translate(center_x, center_y)
        painter.scale(facing, 1)
        painter.setPen(QPen(accent, 2))
        painter.setBrush(QColor("#2a2a2a"))
        painter.drawRoundedRect(QRectF(r - 5, -_STRIP_H / 2 - 4, 13, _STRIP_H + 8), 3, 3)
        painter.setBrush(QColor("#1b1b1b"))
        painter.drawEllipse(QRectF(-r, -r, 2 * r, 2 * r))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 38), 1.5))
        for k in (0.8, 0.62):
            painter.drawEllipse(QRectF(-r * k, -r * k, 2 * r * k, 2 * r * k))
        painter.rotate(self._angle * facing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#9a9a9a"))
        hub = r * 0.38
        painter.drawEllipse(QRectF(-hub, -hub, 2 * hub, 2 * hub))
        painter.setBrush(QColor("#1b1b1b"))
        for i in range(3):
            painter.save()
            painter.rotate(i * 120)
            painter.drawRect(QRectF(-1.6, -hub * 0.85, 3.2, hub * 0.7))
            painter.restore()
        painter.setBrush(accent)
        painter.drawEllipse(QRectF(-3, -3, 6, 6))
        painter.restore()

    def _draw_film(self, painter: QPainter, left: float, right: float, cy: float) -> None:
        """The strip between the rolls, its frames and sprocket holes sliding to the right."""
        top = cy - _STRIP_H / 2
        painter.save()
        painter.setClipRect(QRectF(left, top - 1, right - left, _STRIP_H + 2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#121212"))
        painter.drawRect(QRectF(left, top, right - left, _STRIP_H))
        x = left - _FRAME_PITCH + self._shift
        while x < right:
            painter.setBrush(QColor(150, 150, 150, 215))
            painter.drawRoundedRect(QRectF(x + 2, top + 6, _FRAME_W, _STRIP_H - 12), 2, 2)
            x += _FRAME_PITCH
        painter.setBrush(QColor(225, 225, 225, 235))
        x = left - _HOLE_PITCH + (self._shift % _HOLE_PITCH)
        while x < right:
            painter.drawRoundedRect(QRectF(x, top + 1.8, 5, 3.4), 1, 1)
            painter.drawRoundedRect(QRectF(x, top + _STRIP_H - 5.2, 5, 3.4), 1, 1)
            x += _HOLE_PITCH
        painter.restore()
        painter.setPen(QPen(QColor(255, 255, 255, 60), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(left, top), QPointF(right, top))
        painter.drawLine(QPointF(left, top + _STRIP_H), QPointF(right, top + _STRIP_H))

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 140))

        cx, cy = self.width() / 2, self.height() / 2 - 18
        left_roll, right_roll = cx - _GAP / 2 - _ROLL_R, cx + _GAP / 2 + _ROLL_R
        painter.save()
        painter.translate(cx, cy)
        painter.scale(_SCALE, _SCALE)
        painter.translate(-cx, -cy)
        self._draw_film(painter, left_roll + _ROLL_R, right_roll - _ROLL_R, cy)
        self._draw_roll(painter, left_roll, cy, 1)
        self._draw_roll(painter, right_roll, cy, -1)
        painter.restore()

        painter.setPen(QColor(THEME.text_primary))
        font = painter.font()
        font.setPointSize(THEME.font_size_title + 2)
        font.setBold(True)
        painter.setFont(font)
        text_rect = QRectF(0, cy + _ROLL_R * _SCALE + 14, self.width(), 30)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "Loading…")
        painter.end()

    def show_over(self, parent: QWidget) -> None:
        """Covers parent's current geometry and raises above its siblings."""
        self.setParent(parent)
        self.setGeometry(parent.rect())
        self.show()
        self.raise_()


class HqIndicator(QWidget):
    """The HQ status in the image's bottom-right corner."""

    _TICK_MS = 30
    _SWEEP_MS = 1100
    _YELLOW = QColor("#e8c527")
    _BAR_W = 64

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._mode = "off"
        self._detail = ""
        self._phase = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._advance)
        self.hide()

    def mode(self) -> str:
        return self._mode

    def show_loading(self) -> None:
        self._set("loading", "")
        if not self._timer.isActive():
            self._phase = 0.0
            self._timer.start()

    def show_ready(self, detail: str = "") -> None:
        self._timer.stop()
        self._set("ready", detail)

    def hide_indicator(self) -> None:
        self._timer.stop()
        self._set("off", "")

    def _bold_metrics(self) -> QFontMetrics:
        font = self.font()
        font.setBold(True)
        return QFontMetrics(font)

    def _set(self, mode: str, detail: str) -> None:
        self._mode, self._detail = mode, detail
        if mode == "off":
            self.hide()
            return
        bold, plain = self._bold_metrics(), self.fontMetrics()
        if mode == "loading":
            width = 10 + bold.horizontalAdvance("HQ loading") + 10 + self._BAR_W + 10
        else:
            width = 10 + bold.horizontalAdvance("HQ") + (10 + plain.horizontalAdvance(detail) if detail else 0) + 12
        self.setFixedSize(width + 4, 26)
        self.update()
        self.show()
        self.raise_()

    def _advance(self) -> None:
        self._phase = (self._phase + self._TICK_MS / self._SWEEP_MS) % 1.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(1, 1, self.width() - 2, self.height() - 2)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.setBrush(QColor(0, 0, 0, 200))
        left_mid = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if self._mode == "ready":
            painter.setPen(QPen(self._YELLOW, 2))
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(self._YELLOW)
            painter.drawText(QRectF(10, 0, self.width(), self.height()), left_mid, "HQ")
            if self._detail:
                painter.setPen(QColor(THEME.text_secondary))
                font.setBold(False)
                painter.setFont(font)
                x = 10 + self._bold_metrics().horizontalAdvance("HQ") + 10
                painter.drawText(QRectF(x, 0, self.width() - x, self.height()), left_mid, self._detail)
        elif self._mode == "loading":
            painter.setPen(QPen(QColor(THEME.border_color), 1))
            painter.drawRoundedRect(box, 4, 4)
            painter.setPen(QColor(THEME.text_primary))
            painter.drawText(QRectF(10, 0, self.width(), self.height()), left_mid, "HQ loading")
            bar = QRectF(self.width() - self._BAR_W - 10, self.height() / 2 - 4, self._BAR_W, 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 45))
            painter.drawRect(bar)
            chunk = self._BAR_W * 0.38
            x = bar.left() + (self._BAR_W + chunk) * self._phase - chunk
            painter.setClipRect(bar)
            painter.setBrush(self._YELLOW)
            painter.drawRect(QRectF(x, bar.top(), chunk, bar.height()))
        painter.end()


class ExportIndicator(QWidget):
    """Shown in the image's top-left corner while photos are being exported: a spinning ring, a progress bar and "3/12 \u00b7 9 left" (photos
    finished, of the whole batch, and how many remain). Click-through, like the HQ tag."""

    _TICK_MS = 30
    _BAR_W = 90
    _RING = 16

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._angle = 0
        self._fraction = 0.0
        self._text = ""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._advance)
        self.hide()

    def set_progress(self, photos_done: int, photos_total: int, fraction: float) -> None:
        """photos_done of photos_total are finished; fraction (0-1) is the whole job's progress, for the bar."""
        left = max(0, photos_total - photos_done)
        self._text = f"Exporting {photos_done}/{photos_total} \u00b7 {left} left"
        self._fraction = max(0.0, min(1.0, fraction))
        width = 10 + self._RING + 8 + self.fontMetrics().horizontalAdvance(f"Exporting {photos_total}/{photos_total} \u00b7 {photos_total} left") + 10 + self._BAR_W + 10
        self.setFixedSize(width, 26)
        if not self.isVisible():
            self._timer.start()
            self.show()
        self.raise_()
        self.update()

    def finish(self) -> None:
        self._timer.stop()
        self.hide()

    def _advance(self) -> None:
        self._angle = (self._angle - 10) % 360
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(0, 0, 0, 200))
        painter.setPen(QPen(QColor(THEME.accent_hover), 2))
        painter.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 4, 4)
        ring = QRectF(10, (self.height() - self._RING) / 2, self._RING, self._RING).adjusted(1.5, 1.5, -1.5, -1.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 50), 3))
        painter.drawEllipse(ring)
        arc = QPen(QColor(THEME.accent_hover), 3)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc)
        painter.drawArc(ring, self._angle * 16, 100 * 16)
        painter.setPen(QColor(THEME.text_primary))
        text_x = 10 + self._RING + 8
        text_w = self.width() - text_x - self._BAR_W - 20
        painter.drawText(QRectF(text_x, 0, text_w, self.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)
        bar = QRectF(self.width() - self._BAR_W - 10, self.height() / 2 - 4, self._BAR_W, 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 45))
        painter.drawRect(bar)
        painter.setBrush(QColor(THEME.accent_hover))
        painter.drawRect(QRectF(bar.left(), bar.top(), bar.width() * self._fraction, bar.height()))
        painter.end()
