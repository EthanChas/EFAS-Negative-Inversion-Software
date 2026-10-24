"""Extra > Canon Tether and Live View: the camera's live picture in EFAS - as a positive, with focus peaking and a loupe - the lens driven from the computer with a sharpness meter to
find the sharpest spot by, and the shutter, saving each picture into a roll folder under a numbered name.

Everything about the camera happens off the window's thread (features/tether, desktop/tether_worker): the window only draws what it is handed and sends requests. The practice camera
(a made-up negative with a lens that goes out of focus) lets every control be tried without a camera. A Canon camera needs Canon's own EDSDK, which EFAS cannot include.
The approach follows the Canon EDSDK Film Scanner by Rafat Hossain (MIT); the code is EFAS's own.
"""

import os
import time
from collections import deque

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from ...features.focuspeaking import logic as peaking
from ...features.lightcheck.capture import RAW_EXTS
from ...features.open_image.logic import SUPPORTED_EXTS
from ...features.settings import logic as app_settings
from ...features.tether import edsdk_api, exposure, flatprofile, liveview, naming
from ...features.tether.session import CAMERAS, TetherSession, make_backend
from ...theme.tokens import THEME
from ..tether_worker import JobWorker, LiveWorker

_CLIP_WARN = 0.5   # per cent of the picture blown out before it is warned about
_GRADE_COLOURS = {"Sharpest": "#4caf50", "Sharp": "#8bc34a", "Nearly there": "#ffc107", "Soft": "#ff9800", "Blurred": "#f44336"}
_PEEK_KEY = Qt.Key.Key_N   # held: show the other of positive and negative until it is let go
_STATES = ("off", "connecting", "live", "busy", "closing")


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "hint")
    label.setWordWrap(True)
    return label


def primary_file(paths: list[str]) -> str:
    """The file of a shot worth opening in the editor: the RAW when there is one, else the first picture EFAS can open."""
    for wanted in (RAW_EXTS, SUPPORTED_EXTS):
        for p in paths:
            if os.path.splitext(p)[1].lower() in wanted:
                return p
    return ""


class ZoomMap(QWidget):
    """Where the camera's own zoom frame is in the whole picture: a small map (the last whole picture, with a rectangle for what the zoom shows) in the corner of the live picture. Click or drag
    in it to move the frame."""

    moved = pyqtSignal(float, float)      # the middle of the frame asked for, as fractions of the whole picture
    SIZE = QSize(168, 112)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Where the camera's zoom frame is in the whole picture. Click or drag here to move it; or drag the picture, or use Ctrl and the arrow keys")
        self._overview: QImage | None = None
        self._level, self._centre = 1, (0.5, 0.5)

    def set_overview(self, rgb) -> None:
        h, w = rgb.shape[:2]
        self._overview = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy().scaled(self.SIZE, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.update()

    def set_frame(self, level: int, centre: tuple) -> None:
        self._level, self._centre = max(1, int(level)), centre
        self.update()

    def frame_rect(self) -> QRectF:
        w, h = self.width(), self.height()
        fw, fh = w / self._level, h / self._level
        return QRectF(min(max(self._centre[0] * w - fw / 2, 0), w - fw), min(max(self._centre[1] * h - fh / 2, 0), h - fh), fw, fh)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(16, 16, 16, 235))
        if self._overview is not None:
            p.setOpacity(0.8)
            p.drawImage(0, 0, self._overview)
            p.setOpacity(1.0)
        box = self.frame_rect()
        p.fillRect(box, QColor(90, 200, 255, 60))
        p.setPen(QPen(QColor(90, 200, 255), 2))
        p.drawRect(box)
        p.setPen(QPen(QColor(235, 235, 235, 160), 1))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def _ask(self, event) -> None:
        self.moved.emit(min(max(event.position().x() / self.width(), 0.0), 1.0), min(max(event.position().y() / self.height(), 0.0), 1.0))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._ask(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._ask(event)


class LiveImage(QWidget):
    """The live picture, fitted to the window or zoomed (wheel, the slider, drag to move), with the sharpness region drawn on it, warnings, and (when asked) a loupe."""

    clicked = pyqtSignal(float, float)    # where, as fractions of the picture
    hovered = pyqtSignal(float, float)    # the same, as the mouse moves; (-1, -1) once it leaves
    zoom_changed = pyqtSignal(float)      # 1.0 is the whole picture fitted to the window
    panned = pyqtSignal(float, float)     # the middle button dragged the picture by this much (fractions of the picture) while `camera_pan` is on: the camera is to move its own zoom frame

    ZOOM_MAX = 8.0
    _DRAG_PIXELS = 4   # a press that moves less than this is a click (it measures there); more is a drag (it moves the picture)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(760, 500)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._image: QImage | None = None
        self._message = "Connect a camera to see its live picture."
        self._region: tuple | None = None
        self._info = ""
        self._warning = ""
        self._loupe: QImage | None = None
        self._zoom = 1.0
        self._centre = (0.5, 0.5)      # the part of the picture in the middle of the window, as fractions of it
        self._press: QPointF | None = None
        self._dragging = False
        self._histogram = None                 # (4, 256) counts of the camera's picture, drawn in the corner while show_histogram is on
        self.show_histogram = True
        self.map = ZoomMap(self)               # where the camera's zoom frame is: shown only while the camera's own zoom is in use
        self.map.hide()
        self._middle: QPointF | None = None    # where the middle button went down / was last seen: it moves around in the picture
        self.camera_pan = False                # on while the camera's own zoom is in use: the middle button then moves the camera's zoom frame, not our zoomed picture

    @property
    def zoom(self) -> float:
        return self._zoom

    def set_message(self, text: str) -> None:
        self._image, self._message = None, text
        self.update()

    def set_frame(self, rgb, region: tuple | None, info: str, warning: str, histogram=None) -> None:
        h, w = rgb.shape[:2]
        self._image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self._region, self._info, self._warning, self._histogram = region, info, warning, histogram
        self.update()

    def set_loupe(self, rgb) -> None:
        if rgb is None:
            self._loupe = None
        else:
            h, w = rgb.shape[:2]
            self._loupe = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self.update()

    # ------------------------------------------------------------ zoom and the part shown
    def set_zoom(self, zoom: float, about: tuple | None = None) -> None:
        """Zoom to `zoom` (1 fits the whole picture, up to ZOOM_MAX), keeping the point `about` (fractions of the picture) where it is on screen; the middle when not given."""
        zoom = max(1.0, min(self.ZOOM_MAX, float(zoom)))
        if zoom == self._zoom:
            return
        if about is not None and self._image is not None and zoom > 1.0:
            ax, ay = about
            fx, fy = self._screen_offset(ax, ay)   # where that point is on screen now, as fractions of the window from its middle
            self._zoom = zoom
            self._centre = (ax - fx / self._scale_x(), ay - fy / self._scale_y())
        else:
            self._zoom = zoom
        self._clamp_centre()
        self.zoom_changed.emit(self._zoom)
        self.update()

    def _fit_scale(self) -> float:
        return min(self.width() / self._image.width(), self.height() / self._image.height()) if self._image is not None else 1.0

    def _scale_x(self) -> float:
        """The picture's width on screen, in windows widths, per whole picture (so a distance in window widths over this is a distance in picture fractions)."""
        return self._image.width() * self._fit_scale() * self._zoom / max(1, self.width())

    def _scale_y(self) -> float:
        return self._image.height() * self._fit_scale() * self._zoom / max(1, self.height())

    def _screen_offset(self, fx: float, fy: float) -> tuple[float, float]:
        """Where the picture point (fx, fy) is, as a distance from the window's middle in window widths and heights."""
        return (fx - self._centre[0]) * self._scale_x(), (fy - self._centre[1]) * self._scale_y()

    def _clamp_centre(self) -> None:
        if self._image is None:
            self._centre = (0.5, 0.5)
            return
        cx, cy = self._centre
        out = []
        for c, scale in ((cx, self._scale_x()), (cy, self._scale_y())):
            half = 0.5 / scale if scale > 1.0 else 0.0   # a picture bigger than the window can slide until its edge meets the window's
            out.append(0.5 if scale <= 1.0 else min(max(c, half), 1.0 - half))
        self._centre = (out[0], out[1])

    def _target(self) -> QRectF:
        """Where the whole picture is, in window coordinates (larger than the window when zoomed)."""
        if self._image is None:
            return QRectF(self.rect())
        s = self._fit_scale() * self._zoom
        w, h = self._image.width() * s, self._image.height() * s
        return QRectF(self.width() / 2 - self._centre[0] * w, self.height() / 2 - self._centre[1] * h, w, h)

    def _fractions(self, pos: QPointF):
        t = self._target()
        if self._image is None or not t.contains(pos):
            return None
        return (pos.x() - t.left()) / t.width(), (pos.y() - t.top()) / t.height()

    def resizeEvent(self, event) -> None:
        self._clamp_centre()
        self.map.move(self.width() - self.map.width() - 10, 30)
        super().resizeEvent(event)

    def wheelEvent(self, event) -> None:
        if self._image is None:
            return
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.set_zoom(self._zoom * (1.25 ** steps), self._fractions(event.position()))
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press, self._dragging = event.position(), False
        elif event.button() == Qt.MouseButton.MiddleButton and self._image is not None:
            self._middle = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._middle is not None and self._image is not None and (event.buttons() & Qt.MouseButton.MiddleButton):
            delta = event.position() - self._middle
            self._middle = event.position()
            if self.camera_pan:
                t = self._target()
                self.panned.emit(delta.x() / max(1.0, t.width()), delta.y() / max(1.0, t.height()))
            elif self._zoom > 1.0:
                self._centre = (self._centre[0] - delta.x() / self.width() / self._scale_x(), self._centre[1] - delta.y() / self.height() / self._scale_y())
                self._clamp_centre()
                self.update()
            return
        if self._press is not None and self._image is not None and (self._zoom > 1.0 or self.camera_pan) and (event.buttons() & Qt.MouseButton.LeftButton):
            delta = event.position() - self._press
            if self._dragging or abs(delta.x()) + abs(delta.y()) >= self._DRAG_PIXELS:
                self._dragging = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self._press = event.position()
                if self.camera_pan and self._zoom == 1.0:      # the camera's zoom is on and ours is not: dragging moves the camera's zoom frame
                    t = self._target()
                    self.panned.emit(delta.x() / max(1.0, t.width()), delta.y() / max(1.0, t.height()))
                else:
                    self._centre = (self._centre[0] - delta.x() / self.width() / self._scale_x(), self._centre[1] - delta.y() / self.height() / self._scale_y())
                    self._clamp_centre()
                    self.update()
                return
        f = self._fractions(event.position())
        self.hovered.emit(*(f if f else (-1.0, -1.0)))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._middle = None
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        dragged, self._press, self._dragging = self._dragging, None, False
        self.setCursor(Qt.CursorShape.CrossCursor)
        f = self._fractions(event.position())
        if f and not dragged:
            self.clicked.emit(*f)

    def leaveEvent(self, _event) -> None:
        self.hovered.emit(-1.0, -1.0)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101010"))
        if self._image is None:
            p.setPen(QColor(THEME.text_hint))
            p.setFont(QFont(THEME.font_family, 11))
            p.drawText(QRectF(self.rect()).adjusted(30, 0, -30, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._message)
            return
        t = self._target()
        view = t.intersected(QRectF(self.rect()))
        scale = t.width() / self._image.width()   # screen pixels per picture pixel
        ratio = self.devicePixelRatioF()
        src = QRectF((view.left() - t.left()) / scale, (view.top() - t.top()) / scale, view.width() / scale, view.height() / scale)
        if scale * ratio < 0.7:
            # shrinking by a lot: Qt's plain smooth drawing skips pixels and shimmers, so the picture is first scaled down properly (area-averaged) to the size it is drawn at
            size = QSize(max(1, round(t.width() * ratio)), max(1, round(t.height() * ratio)))
            shown = self._image.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            shown.setDevicePixelRatio(ratio)
            p.drawImage(view, shown, QRectF((view.left() - t.left()) * ratio, (view.top() - t.top()) * ratio, view.width() * ratio, view.height() * ratio))
        else:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, scale * ratio < 4.0)   # zoomed in a lot, the picture's own pixels are shown as squares, to be judged
            p.drawImage(view, self._image, src)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setClipRect(QRectF(self.rect()))
        if self._region is not None:
            x0, y0, x1, y1 = self._region
            box = QRectF(t.left() + x0 * t.width(), t.top() + y0 * t.height(), (x1 - x0) * t.width(), (y1 - y0) * t.height())
            p.setPen(QPen(QColor(90, 200, 255, 220), 1.5, Qt.PenStyle.DashLine))
            p.drawRect(box)
        p.setFont(QFont(THEME.font_family, 9))
        p.setPen(QColor(235, 235, 235))
        zoom = f"   {self._zoom * 100:.0f}%" if self._zoom > 1.0 else ""
        p.drawText(QRectF(8, 6, self.width() - 16, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._info + zoom)
        if self._warning:
            p.setPen(QColor(THEME.status_critical))
            p.drawText(QRectF(8, 6, self.width() - 16, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._warning)
        if self.show_histogram and self._histogram is not None:
            self._paint_histogram(p)
        if self._loupe is not None:
            size = min(300, int(self.width() * 0.34), int(self.height() * 0.5))
            box = QRectF(self.width() - size - 8, self.height() - size - 8, size, size)
            p.drawImage(box, self._loupe)
            p.setPen(QPen(QColor(235, 235, 235), 1.5))
            p.drawRect(box)


    def _paint_histogram(self, p: QPainter) -> None:
        """The camera's histogram in the bottom left corner: red, green and blue, and the luminance as a white line; a bar at an edge when more than half a per cent is clipped there."""
        hist = self._histogram
        box = QRectF(10, self.height() - 108, 276, 98)
        p.fillRect(box, QColor(0, 0, 0, 150))
        inner = box.adjusted(8, 6, -8, -6)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        for third in (1, 2):
            x = inner.left() + inner.width() * third / 3
            p.drawLine(QPointF(x, inner.top()), QPointF(x, inner.bottom()))
        peak = max(float(hist[:, 1:255].max()), 1.0)    # (the two end bins are left out of the scale: a pile of clipped pixels would flatten the rest)
        step = inner.width() / 255

        def outline(row):
            path = QPainterPath()
            path.moveTo(inner.left(), inner.bottom())
            for i in range(256):
                path.lineTo(inner.left() + i * step, inner.bottom() - inner.height() * min(1.0, float(hist[row, i]) / peak))
            return path

        for row, (r, g, b) in enumerate(((255, 70, 70), (70, 220, 70), (90, 140, 255))):
            path = outline(row)
            path.lineTo(inner.right(), inner.bottom())
            path.closeSubpath()
            p.setBrush(QColor(r, g, b, 80))
            p.setPen(QPen(QColor(r, g, b, 190), 1))
            p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(245, 245, 245, 230), 1.2))
        p.drawPath(outline(3))
        total = max(float(hist[0].sum()), 1.0)
        for edge, x in ((0, inner.left()), (255, inner.right() - 3)):
            if float(hist[:3, edge].max()) * 100.0 / total >= _CLIP_WARN:
                p.fillRect(QRectF(x, inner.top(), 3, inner.height()), QColor(THEME.status_critical))


class Sparkline(QWidget):
    """The recent sharpness readings as a line, with the best so far marked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(46)
        self._values: list[float] = []
        self._best = 0.0

    def set_values(self, values, best: float) -> None:
        self._values, self._best = list(values), best
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(THEME.bg_input))
        top = max(self._best, max(self._values, default=0.0), 1e-9)
        h, w = self.height() - 6, self.width() - 6
        p.setPen(QPen(QColor(76, 175, 80, 140), 1, Qt.PenStyle.DashLine))
        yb = 3 + h * (1 - self._best / top)
        p.drawLine(QPointF(3, yb), QPointF(3 + w, yb))
        if len(self._values) > 1:
            p.setPen(QPen(QColor(230, 230, 230), 1.5))
            n = len(self._values) - 1
            pts = [QPointF(3 + w * i / n, 3 + h * (1 - v / top)) for i, v in enumerate(self._values)]
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)


class TetherWindow(QDialog):
    """The tether window. `factory(kind, sdk_folder)` makes the camera backend (a test gives a stand-in)."""

    _auto_say = pyqtSignal(str)         # progress from auto exposure, which runs off the window's thread
    captured = pyqtSignal(list)         # the paths a shot saved
    open_requested = pyqtSignal(str)    # a picture to open in the editor

    def __init__(self, parent=None, factory=make_backend, start_folder: str = "", saved_flatfield=None):
        super().__init__(parent)
        self.setWindowTitle("Canon Tether and Live View")
        self._saved_flatfield = saved_flatfield          # () -> EFAS's permanent flat field as a gain map, or None
        self._flat_gain = None                           # the gain map the preview is evened out with, and where it came from
        self._flat_source = ""                           # "captured" (from the light, in this window) or "efas"
        self._flat_frames: list | None = None            # the pictures of the light being collected, while capturing
        self._camera_zoom_level, self._camera_zoom_center = 1, (0.5, 0.5)
        self._zoom_sending, self._zoom_sent = False, (0.5, 0.5)
        self._overview_at = 0.0
        area = QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() is not None else None
        self.resize(min(1640, (area.width() - 40) if area else 1640), min(940, (area.height() - 60) if area else 940))   # wide, so the picture has room
        self._factory = factory
        self.session: TetherSession | None = None
        self._live: LiveWorker | None = None
        self._job: JobWorker | None = None
        self._focus_job: JobWorker | None = None
        self._frame = None
        self._seen = deque(maxlen=30)
        self._state = "off"
        self._hover = (-1.0, -1.0)
        self._alive: set = set()   # exposure jobs that are running: a QThread dropped while it runs aborts the program, so each is held until it finishes
        self._exposure_job: JobWorker | None = None
        self._auto_job: JobWorker | None = None
        self._exposure_timer = QTimer(self)
        self._exposure_timer.setInterval(2500)
        self._exposure_timer.timeout.connect(self.refresh_exposure)
        self._peek_from: bool | None = None   # the positive check's state before N was held
        self._live_buttons: list[QPushButton] = []   # the buttons that only work while the camera is live
        self._building = True
        self._build(start_folder)
        self._auto_say.connect(lambda text: self.exposure_note.setText(text))
        self._building = False
        self._flat_init()
        self._set_state("off")

    # ------------------------------------------------------------ building the window
    def _build(self, start_folder: str) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.image = LiveImage()
        self.image.clicked.connect(self._image_clicked)
        self.image.hovered.connect(self._image_hovered)
        left.addWidget(self.image, 1)
        zoom_row = QHBoxLayout()   # under the picture: how much of it to see
        zoom_row.addWidget(QLabel("Zoom"))
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(100, int(LiveImage.ZOOM_MAX * 100))
        self.zoom_slider.setValue(100)
        self.zoom_slider.setToolTip("Zoom the live picture: 100% fits it to the window. The mouse wheel zooms where the pointer is; drag the picture with the left or the middle button to move it; a click still measures sharpness there")
        self.zoom_slider.valueChanged.connect(lambda v: self.image.set_zoom(v / 100.0))
        zoom_row.addWidget(self.zoom_slider, 1)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setMinimumWidth(48)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addWidget(self._button("Fit", "Show the whole picture (0)", lambda: self.zoom_slider.setValue(100)))
        left.addLayout(zoom_row)
        camera_zoom = QHBoxLayout()    # the camera's own zoom: real sensor pixels, where the slider above only makes the pixels it has bigger
        camera_zoom.addWidget(QLabel("Camera zoom"))
        self.camera_zoom_buttons: dict[int, QPushButton] = {}
        for level, label in ((1, "Fit"), (5, "5x"), (10, "10x")):
            b = self._button(label, "Ask the camera to zoom its own live picture: at 5x or 10x it sends part of the sensor at the size of the whole picture, so the film's grain and fine detail show as real "
                                    "pixels (the Zoom slider only makes the pixels it already has bigger). Move around it by dragging the picture, by dragging the little map that appears in its corner, "
                                    "or with Ctrl and the arrow keys" if level > 1 else "The camera's whole live picture",
                             lambda _c=False, n=level: self.camera_zoom(n))
            b.setCheckable(True)
            b.setChecked(level == 1)
            b.setEnabled(False)
            self.camera_zoom_buttons[level] = b
            self._live_buttons.append(b)
            camera_zoom.addWidget(b)
        self.camera_zoom_note = _hint("")
        camera_zoom.addWidget(self.camera_zoom_note, 1)
        left.addLayout(camera_zoom)
        self.image.zoom_changed.connect(self._zoom_changed)
        self.image.panned.connect(self._camera_pan)
        self.image.map.moved.connect(self._zoom_map_moved)
        bar = QHBoxLayout()   # under the picture, where it is always in reach: the shutter, and what happened to the last shot
        self.capture_button = self._button("Capture (Space)", "Wait, release the shutter without focusing (focus stays where you put it), and save what the camera makes", self.capture)
        self.capture_button.setMinimumSize(190, 40)
        self.capture_button.setStyleSheet("font-weight: bold;")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        bar.addWidget(self.capture_button)
        bar.addWidget(self.status, 1)
        left.addLayout(bar)
        root.addLayout(left, 1)
        side = QWidget()
        side.setFixedWidth(360)
        col = QVBoxLayout(side)
        col.setContentsMargins(0, 0, 4, 0)
        col.addWidget(self._camera_box())
        col.addWidget(self._exposure_box())
        col.addWidget(self._capture_box(start_folder))
        col.addWidget(self._focus_box())
        col.addWidget(self._view_box())
        col.addWidget(self._flat_box())
        col.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(side)
        scroll.setFixedWidth(384)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(scroll)
        for key, action in (("Space", self.capture), ("0", lambda: self.zoom_slider.setValue(100)), ("I", lambda: self.positive_check.toggle()), ("P", lambda: self.peaking_check.toggle()), ("L", lambda: self.loupe_check.toggle()), ("H", lambda: self.histogram_check.toggle()),
                            ("Ctrl+Left", lambda: self._camera_step(-1, 0)), ("Ctrl+Right", lambda: self._camera_step(1, 0)), ("Ctrl+Up", lambda: self._camera_step(0, -1)), ("Ctrl+Down", lambda: self._camera_step(0, 1)),
                            ("Left", lambda: self.focus("near", "fine")), ("Right", lambda: self.focus("far", "fine")),
                            ("Shift+Left", lambda: self.focus("near", "medium")), ("Shift+Right", lambda: self.focus("far", "medium")),
                            ("Alt+Left", lambda: self.focus("near", "coarse")), ("Alt+Right", lambda: self.focus("far", "coarse"))):
            QShortcut(QKeySequence(key), self, activated=action)

    def _button(self, text: str, tip: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # a keystroke goes to the shortcuts, not to whichever button was last clicked
        b.clicked.connect(lambda _c=False: slot())
        return b

    def _camera_box(self) -> QGroupBox:
        box = QGroupBox("Camera")
        lay = QVBoxLayout(box)
        self.camera_combo = QComboBox()
        for key, label in CAMERAS:
            self.camera_combo.addItem(label, key)
        self.camera_combo.setCurrentIndex(max(0, self.camera_combo.findData(app_settings.get("tether_camera"))))
        self.camera_combo.currentIndexChanged.connect(self._camera_kind_changed)
        lay.addWidget(self.camera_combo)
        self.sdk_widget = QWidget()
        sdk = QVBoxLayout(self.sdk_widget)
        sdk.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.sdk_edit = QLineEdit(app_settings.get("tether_sdk_dir"))
        self.sdk_edit.setPlaceholderText("The folder of Canon's EDSDK (with EDSDK.dll)")
        self.sdk_edit.textChanged.connect(self._sdk_changed)
        row.addWidget(self.sdk_edit, 1)
        row.addWidget(self._button("Browse...", "Choose the folder you unpacked Canon's EDSDK into", self.choose_sdk))
        sdk.addLayout(row)
        self.sdk_status = _hint("")
        sdk.addWidget(self.sdk_status)
        sdk.addWidget(_hint("EFAS cannot include Canon's SDK (Canon licenses it to each developer and it may not be passed on): get your own copy from Canon's developer site. "
                            "Turn the camera's Wi-Fi and Bluetooth off, use a data cable straight into the computer, and close EOS Utility first."))
        lay.addWidget(self.sdk_widget)
        self.connect_button = self._button("Connect", "Connect to the camera and start its live picture", self.toggle_connection)
        lay.addWidget(self.connect_button)
        self.camera_info = QLabel("")
        self.camera_info.setWordWrap(True)
        lay.addWidget(self.camera_info)
        self.camera_note = _hint("")
        lay.addWidget(self.camera_note)
        return box

    def _exposure_box(self) -> QGroupBox:
        box = QGroupBox("Exposure")
        lay = QVBoxLayout(box)
        self.mode_label = _hint("")
        lay.addWidget(self.mode_label)
        grid = QGridLayout()
        self.exposure_combos: dict[str, QComboBox] = {}
        for row, key in enumerate(exposure.KEYS):
            grid.addWidget(QLabel(exposure.TITLES[key]), row, 0)
            combo = QComboBox()
            combo.setEnabled(False)
            combo.activated.connect(lambda _i, k=key: self.set_exposure_from_box(k))
            self.exposure_combos[key] = combo
            grid.addWidget(combo, row, 1)
        lay.addLayout(grid)
        self.auto_button = self._button("Auto exposure", "Set the shutter speed so the film's brightest colour is as bright as it can be without clipping (the camera's mode dial must be on M or Tv). It uses the "
                                        "live picture, so the film must be in place and lit", self.auto_exposure)
        self._live_buttons.append(self.auto_button)
        lay.addWidget(self.auto_button)
        self.exposure_note = _hint("")
        lay.addWidget(self.exposure_note)
        return box

    def _view_box(self) -> QGroupBox:
        box = QGroupBox("View")
        lay = QVBoxLayout(box)
        self.positive_check = QCheckBox("Show as a positive (I; hold N to peek at the negative)")
        self.positive_check.setChecked(True)
        self.positive_check.setToolTip("EFAS's own NegPy Conversion turns the negative into a picture as you focus, so you judge focus on what you will see")
        self.positive_check.toggled.connect(self._view_changed)
        lay.addWidget(self.positive_check)
        meter = QHBoxLayout()
        meter.addWidget(QLabel("Tones from"))
        self.metering_combo = QComboBox()
        for key, label in liveview.METERING:
            self.metering_combo.addItem(label, key)
        self.metering_combo.setToolTip("What the tones of the positive are worked out from, about twice a second. Whole picture: everything but the holder and what is blown out, so bright parts at the edges are not "
                                       "clipped to white. Middle: only the middle of the picture. Hold: keep the conversion as it is while you change frames")
        self.metering_combo.activated.connect(self._view_changed)
        meter.addWidget(self.metering_combo, 1)
        lay.addLayout(meter)
        row = QHBoxLayout()
        self.base_button = self._button("Pick the Clear Film", "Click this, then click a patch of clear film between frames: the conversion then knows the film's orange", self.arm_base_pick)
        self.base_button.setCheckable(True)
        row.addWidget(self.base_button)
        forget = self._button("Forget", "Go back to working the film base out from the picture", self.forget_base)
        self._live_buttons.append(forget)
        row.addWidget(forget)
        lay.addLayout(row)
        self.base_label = _hint("Film base: worked out from the picture.")
        lay.addWidget(self.base_label)
        self.peaking_check = QCheckBox("Focus peaking (P)")
        self.peaking_check.setToolTip("Marks what is in focus in colour, from blue (sharp) to red (sharpest), the way a camera's own peaking does")
        self.peaking_check.toggled.connect(self._view_changed)
        lay.addWidget(self.peaking_check)
        sens = QHBoxLayout()
        sens.addWidget(QLabel("Peaking sensitivity"))
        self.peaking_value = QLabel("50%")
        self.peaking_value.setMinimumWidth(40)
        self.peaking_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sens.addStretch(1)
        sens.addWidget(self.peaking_value)
        lay.addLayout(sens)
        self.peaking_slider = QSlider(Qt.Orientation.Horizontal)
        self.peaking_slider.setRange(0, 100)
        self.peaking_slider.setValue(50)
        self.peaking_slider.setToolTip("100% marks every sharp spot, 0% only the very sharpest")
        self.peaking_slider.valueChanged.connect(lambda v: (self.peaking_value.setText(f"{v}%"), self._view_changed()))
        lay.addWidget(self.peaking_slider)
        self.histogram_check = QCheckBox("Histogram (H)")
        self.histogram_check.setChecked(True)
        self.histogram_check.setToolTip("The camera's own picture as a histogram in the bottom left of the live picture: red, green and blue, with the luminance as a white line. A bar at the left or right edge "
                                        "means more than half a per cent of the picture is clipped there. Use it to set the exposure so the film's range sits inside it")
        self.histogram_check.toggled.connect(self._histogram_toggled)
        lay.addWidget(self.histogram_check)
        self.loupe_check = QCheckBox("Loupe (L): enlarge what the mouse is over")   # drawn bottom right, with the picture's own pixels
        self.loupe_check.setToolTip("Four times the camera's own pixels round the mouse, not the smaller picture shown")
        self.loupe_check.toggled.connect(self._loupe_toggled)
        lay.addWidget(self.loupe_check)
        return box

    def _flat_box(self) -> QGroupBox:
        box = QGroupBox("Flat field")
        lay = QVBoxLayout(box)
        self.flat_check = QCheckBox("Even out the preview with a flat field")
        self.flat_check.setToolTip("Divides the live picture by the light's own falloff, so a bright middle and dark corners do not hide how even the film is. The preview only: the shots the camera saves are "
                                   "corrected by EFAS's flat field in the editor as before")
        self.flat_check.setEnabled(False)
        self.flat_check.toggled.connect(self._view_changed)
        lay.addWidget(self.flat_check)
        row = QHBoxLayout()
        self.flat_capture_button = self._button("Capture the light", "Take the film out so the picture is only the bare light (bright, not white), then click: eight live pictures are averaged into a flat field, "
                                                                     "kept for next time", self.capture_flat_field)
        self._live_buttons.append(self.flat_capture_button)
        row.addWidget(self.flat_capture_button)
        self.flat_forget_button = self._button("Forget", "Stop evening the preview out (and throw away the flat field captured here)", self.forget_flat_field)
        row.addWidget(self.flat_forget_button)
        lay.addLayout(row)
        self.flat_saved_button = self._button("Use EFAS's flat field", "Use the permanent flat field set in the Flat Field panel, when there is one and it is switched on", self.use_saved_flat_field)
        lay.addWidget(self.flat_saved_button)
        self.flat_label = _hint("")
        lay.addWidget(self.flat_label)
        return box

    def _focus_box(self) -> QGroupBox:
        box = QGroupBox("Focus drive")
        lay = QVBoxLayout(box)
        lay.addWidget(_hint("\u2190 \u2192  fine  \u00b7  Shift  medium  \u00b7  Alt  coarse"))
        grid = QGridLayout()
        keys = {"coarse": "Alt+", "medium": "Shift+", "fine": ""}
        for row, (direction, order) in enumerate((("near", ("coarse", "medium", "fine")), ("far", ("fine", "medium", "coarse")))):
            grid.addWidget(QLabel("Nearer" if direction == "near" else "Farther"), row, 0)
            for c, name in enumerate(order, start=1):
                b = self._button(name.capitalize(), f"Drive the lens {'nearer' if direction == 'near' else 'farther'} in {name} steps ({keys[name]}{'Left' if direction == 'near' else 'Right'})",
                                 lambda d=direction, n=name: self.focus(d, n))
                self._live_buttons.append(b)
                grid.addWidget(b, row, c)
        lay.addLayout(grid)
        self.focus_note = _hint("")
        lay.addWidget(self.focus_note)
        self.sharp_label = QLabel("Sharpness: -")
        self.sharp_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        lay.addWidget(self.sharp_label)
        self.grade_label = QLabel("")
        self.grade_label.setStyleSheet("font-weight: bold; font-size: 15px;")
        lay.addWidget(self.grade_label)
        self.sharp_bar = QProgressBar()
        self.sharp_bar.setRange(0, 100)
        self.sharp_bar.setFormat("%p% of the best so far")
        lay.addWidget(self.sharp_bar)
        self.spark = Sparkline()
        lay.addWidget(self.spark)
        row = QHBoxLayout()
        for text, tip, slot in (("Reset Best", "Start the best-so-far reading over", self.reset_best),
                                ("Centre", "Measure sharpness in the middle of the picture again (a click on the picture measures where you click)", self.measure_centre),
                                ("Corners", "Compare the sharpness at the corners with the middle: a camera that is not parallel to the film shows corners that differ", self.check_corners)):
            b = self._button(text, tip, slot)
            self._live_buttons.append(b)
            row.addWidget(b)
        lay.addLayout(row)
        self.corner_label = _hint("")
        lay.addWidget(self.corner_label)
        lay.addWidget(_hint("Left and Right drive the lens (fine; Shift for medium, Alt for coarse). Go past the sharpest spot and back: the meter peaks there. Click the picture to measure sharpness where you click."))
        return box

    def _capture_box(self, start_folder: str) -> QGroupBox:
        box = QGroupBox("Capture")
        lay = QVBoxLayout(box)
        row = QHBoxLayout()
        self.folder_edit = QLineEdit(start_folder or app_settings.get("tether_folder"))
        self.folder_edit.setPlaceholderText("The roll folder to save pictures in")
        self.folder_edit.textChanged.connect(self._names_changed)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(self._button("Browse...", "Choose the folder to save pictures in", self.choose_folder))
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Name"))
        self.prefix_edit = QLineEdit(app_settings.get("tether_prefix"))
        self.prefix_edit.setMaximumWidth(120)
        self.prefix_edit.textChanged.connect(self._names_changed)
        row.addWidget(self.prefix_edit)
        self.next_label = QLabel("")
        row.addWidget(self.next_label, 1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Wait before the shutter"))
        self.settle_spin = QDoubleSpinBox()
        self.settle_spin.setRange(0.0, 10.0)
        self.settle_spin.setSingleStep(0.5)
        self.settle_spin.setSuffix(" s")
        self.settle_spin.setValue(app_settings.get("tether_settle"))
        self.settle_spin.setToolTip("Time for the rig to stop shaking after you press Capture: vibration is the main cause of soft scans on a copy stand")
        self.settle_spin.valueChanged.connect(self._names_changed)
        row.addWidget(self.settle_spin)
        row.addStretch(1)
        lay.addLayout(row)
        self.show_check = QCheckBox("Open each picture in EFAS")
        self.show_check.setChecked(app_settings.get("tether_show"))
        self.show_check.setToolTip("After each shot the RAW (or the JPEG) opens in the editor, and the folder shows in the Workbench")
        lay.addWidget(self.show_check)
        self.recent = QListWidget()
        self.recent.setMaximumHeight(110)
        self.recent.setToolTip("The pictures taken now. Double-click one to open it in the editor.")
        self.recent.itemDoubleClicked.connect(lambda item: self.open_requested.emit(item.data(Qt.ItemDataRole.UserRole)))
        lay.addWidget(self.recent)
        self._refresh_names()
        self._sdk_changed()
        return box

    # ------------------------------------------------------------ state
    def _zoom_changed(self, zoom: float) -> None:
        value = round(zoom * 100)
        self.zoom_label.setText(f"{value}%")
        if self.zoom_slider.value() != value:
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(value)
            self.zoom_slider.blockSignals(False)

    # ------------------------------------------------------------ the camera's exposure
    def refresh_exposure(self) -> None:
        """Ask the camera what it is set to now (a dial may have been turned) and show it. One question at a time."""
        session = self.session
        if session is None or self._state not in ("live", "busy") or (self._exposure_job is not None and self._exposure_job.isRunning()):
            return
        job = JobWorker(session.exposure)
        job.done.connect(self._show_exposure)
        job.failed.connect(lambda _m: None)   # a missed reading is not worth a message: the next one comes in a moment
        self._start_exposure_job(job)

    def _start_exposure_job(self, job: JobWorker) -> None:
        self._exposure_job = job
        self._alive.add(job)
        job.finished.connect(lambda j=job: self._alive.discard(j))
        job.start()

    def _show_exposure(self, state) -> None:
        if state is None or self.session is None:
            return
        self.mode_label.setText(f"The camera is in {state.mode} mode." + ("" if state.can_set("tv") else " Turn its dial to M to set the shutter speed and aperture from here."))
        for key, combo in self.exposure_combos.items():
            current, choices = state.values.get(key), state.choices.get(key, ())
            if combo.view().isVisible():
                continue   # do not change a list the person has open
            combo.blockSignals(True)
            combo.clear()
            offered = list(choices)
            if current is not None and current not in offered:
                offered.append(current)
            for code in sorted(offered, key=lambda c: (exposure.signed8(c) if key == "comp" else (c if key != "tv" else -c))):
                combo.addItem(exposure.label(key, code), code)
            if current is not None:
                combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.setEnabled(bool(choices))
            combo.blockSignals(False)

    def set_exposure_from_box(self, key: str) -> None:
        session, combo = self.session, self.exposure_combos[key]
        if session is None or self._state != "live" or combo.currentData() is None:
            return
        code = int(combo.currentData())
        job = JobWorker(lambda: session.set_exposure(key, code))
        job.done.connect(lambda _r: self.refresh_exposure())
        job.failed.connect(self._exposure_failed)
        self._start_exposure_job(job)

    def _exposure_failed(self, message: str) -> None:
        self.exposure_note.setText(message)
        self.refresh_exposure()

    def auto_exposure(self) -> None:
        session = self.session
        if session is None or self._state != "live" or (self._auto_job is not None and self._auto_job.isRunning()):
            return
        self.auto_button.setEnabled(False)
        self.exposure_note.setText("Measuring...")
        job = JobWorker(lambda: session.auto_exposure(say=lambda text: self._auto_say.emit(text)))
        job.done.connect(self._auto_done)
        job.failed.connect(self._auto_failed)
        self._auto_job = job
        self._alive.add(job)
        job.finished.connect(lambda j=job: self._alive.discard(j))
        job.start()

    def _auto_done(self, result) -> None:
        self.auto_button.setEnabled(self._state == "live")
        self.exposure_note.setText(result.message)
        self.refresh_exposure()

    def _auto_failed(self, message: str) -> None:
        self.auto_button.setEnabled(self._state == "live")
        self.exposure_note.setText(message)

    # ------------------------------------------------------------ the flat field of the preview
    def _flat_init(self) -> None:
        reference = flatprofile.load()
        if reference is not None:
            self._set_flat(flatprofile.gain_of(reference), "captured")
        else:
            self._set_flat(None, "")

    def _set_flat(self, gain, source: str, say: str = "") -> None:
        self._flat_gain, self._flat_source = gain, source if gain is not None else ""
        was, self._building = self._building, True
        self.flat_check.setEnabled(gain is not None)
        self.flat_check.setChecked(gain is not None)
        self._building = was
        self.flat_label.setText(say or ("Evening out the preview with the flat field captured from the light." if source == "captured" else
                                        "Evening out the preview with EFAS's permanent flat field." if source == "efas" else
                                        "No flat field: the preview shows the light as the camera sees it. Take the film out, then Capture the light."))
        self._sync_flat_buttons()
        if self.session is not None:
            self.session.pipeline.set_flatfield(gain)
            self._apply_view()

    def _sync_flat_buttons(self) -> None:
        self.flat_forget_button.setEnabled(self._flat_gain is not None)
        self.flat_saved_button.setEnabled(self._saved_flatfield is not None)
        self.flat_capture_button.setEnabled(self._state == "live" and self._flat_frames is None)

    def capture_flat_field(self) -> None:
        """Collect a few live pictures of the bare light and make the preview's flat field from them."""
        if self._state != "live" or self.session is None or self._flat_frames is not None:
            return
        if self._camera_zoom_level > 1:
            self.flat_label.setText("Put the camera zoom back to Fit first: the flat field is of the whole picture.")
            return
        self._flat_frames = []
        self.flat_label.setText("Capturing the light...")
        self._sync_flat_buttons()

    def _collect_flat(self, frame) -> None:
        frames = self._flat_frames
        if frames is None:
            return
        small = flatprofile.shrink(frame.rgb)
        if frames and frames[0].shape != small.shape:
            frames.clear()
        frames.append(small)
        if len(frames) < flatprofile.FRAMES:
            return
        self._flat_frames = None
        problem = flatprofile.problem_with(frames)
        if problem:
            self.flat_label.setText(problem)
            self._sync_flat_buttons()
            return
        reference = flatprofile.reference_from_frames(frames)
        gain, spread = flatprofile.fit(reference)
        if spread > flatprofile.MAX_UNEVEN:
            self.flat_label.setText("That is not bare light: it has too much in it to be a smooth glow (film, or the holder, is in the way). Take everything out of the picture and try again.")
            self._sync_flat_buttons()
            return
        try:
            flatprofile.save(reference)
        except OSError:
            pass     # it works for this session; it is only not kept
        self._set_flat(gain, "captured")

    def use_saved_flat_field(self) -> None:
        gain = self._saved_flatfield() if self._saved_flatfield is not None else None
        if gain is None:
            self.flat_label.setText("EFAS has no permanent flat field switched on (Flat Field panel).")
            return
        self._set_flat(gain, "efas")

    def forget_flat_field(self) -> None:
        flatprofile.forget()
        self._flat_frames = None
        self._set_flat(None, "")

    def _set_state(self, state: str) -> None:
        self._state = state
        live, busy = state == "live", state == "busy"
        can_use = live or busy
        self.camera_combo.setEnabled(state == "off")
        self.sdk_widget.setEnabled(state == "off")
        self.sdk_widget.setVisible(self.camera_combo.currentData() == "canon")
        self.connect_button.setText({"off": "Connect", "connecting": "Connecting...", "live": "Disconnect", "busy": "Disconnect", "closing": "Disconnecting..."}[state])
        self.connect_button.setEnabled(state in ("off", "live"))
        for w in (self.positive_check, self.base_button, self.peaking_check, self.peaking_slider, self.loupe_check):
            w.setEnabled(can_use)
        for b in self._live_buttons:
            b.setEnabled(live)
        self._sync_flat_buttons()
        self.capture_button.setEnabled(live)
        if state == "off":
            self.image.set_message("Connect a camera to see its live picture.")
            self.camera_info.setText("")
            self.camera_note.setText("")
            self.focus_note.setText("")
            self._exposure_timer.stop()
            self.mode_label.setText("")
            self.exposure_note.setText("")
            for combo in self.exposure_combos.values():
                combo.clear()
                combo.setEnabled(False)

    def _camera_kind_changed(self) -> None:
        if not self._building:
            self.sdk_widget.setVisible(self.camera_combo.currentData() == "canon")

    def _sdk_changed(self) -> None:
        path = edsdk_api.find_library(self.sdk_edit.text().strip())
        if path:
            self.sdk_status.setText(f"Found {path}")
            self.sdk_status.setStyleSheet(f"color: {THEME.status_success};")
        else:
            self.sdk_status.setText("EDSDK.dll was not found in that folder." if self.sdk_edit.text().strip() else "Choose the folder you unpacked Canon's EDSDK into.")
            self.sdk_status.setStyleSheet("")

    def choose_sdk(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder of Canon's EDSDK", self.sdk_edit.text().strip())
        if folder:
            self.sdk_edit.setText(folder)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder to save pictures in", self.folder_edit.text().strip())
        if folder:
            self.folder_edit.setText(folder)

    def _names_changed(self) -> None:
        self._refresh_names()
        if self.session is not None:
            self.session.folder = self.folder_edit.text().strip()
            self.session.prefix = naming.clean_prefix(self.prefix_edit.text())
            self.session.settle_s = self.settle_spin.value()

    def _refresh_names(self) -> None:
        folder, prefix = self.folder_edit.text().strip(), naming.clean_prefix(self.prefix_edit.text())
        self.next_label.setText(f"next: {prefix}{naming.next_frame(folder, prefix):0{naming.DIGITS}d}" if folder else "choose a folder")

    # ------------------------------------------------------------ connecting
    def toggle_connection(self) -> None:
        if self._state == "off":
            self.connect_camera()
        elif self._state in ("live", "busy"):
            self.disconnect_camera()

    def connect_camera(self) -> None:
        kind, sdk = self.camera_combo.currentData(), self.sdk_edit.text().strip()
        if kind == "canon" and not edsdk_api.find_library(sdk):
            self.status.setStyleSheet(f"color: {THEME.status_critical};")
            self.status.setText("Choose the folder of Canon's EDSDK first (the one with EDSDK.dll).")
            return
        self._save_settings()
        self.session = TetherSession(self._factory(kind, sdk), self.folder_edit.text().strip(), self.prefix_edit.text(), self.settle_spin.value())
        self.status.setStyleSheet("")
        self.status.setText("Connecting...")
        self.image.set_message("Connecting to the camera...")
        self._set_state("connecting")
        job = JobWorker(self.session.open)
        job.done.connect(self._connected)
        job.failed.connect(self._connect_failed)
        self._job = job
        job.start()

    def _connected(self, _result) -> None:
        info, caps = self.session.backend.info, self.session.backend.capabilities
        self.camera_info.setText(f"{info.model}" + (f"\n{info.lens}" if info.lens else ""))
        self.focus_note.setText("" if caps.focus_drive else caps.note("focus_drive") or "This lens cannot be focused from the computer.")
        self.status.setText("Connected. Live picture running.")
        self._seen.clear()
        self._frame = None
        self._apply_view()
        self._live = LiveWorker(self.session)
        self._live.frame.connect(self._on_frame)
        self._live.failed.connect(self._live_failed)
        self._live.start()
        self.image.set_message("Waiting for the first live picture...")
        self._set_state("live")
        for level, b in self.camera_zoom_buttons.items():     # (after the state has switched the live buttons on: the zoom ones only if the camera offers it)
            b.setChecked(level == 1)
            b.setEnabled(bool(caps.zoom) or level == 1)
        self.camera_zoom_note.setText("" if caps.zoom else "This camera does not send a zoomed live picture.")
        self._camera_zoom_level, self._camera_zoom_center = 1, (0.5, 0.5)
        self.image.camera_pan = False
        self.image.map.hide()
        self.session.pipeline.set_flatfield(self._flat_gain)
        self._apply_view()
        self._exposure_timer.start()
        self.exposure_note.setText("" if caps.exposure else "This camera does not report its exposure to the computer.")
        self.auto_button.setEnabled(caps.exposure)
        self.refresh_exposure()

    def _connect_failed(self, message: str) -> None:
        self.session = None
        self._set_state("off")
        self.status.setStyleSheet(f"color: {THEME.status_critical};")
        self.status.setText(message)
        self.image.set_message(message)

    def _live_failed(self, message: str) -> None:
        self.status.setStyleSheet(f"color: {THEME.status_critical};")
        self.status.setText(message)
        self.disconnect_camera()

    def disconnect_camera(self) -> None:
        if self.session is None or self._state in ("off", "closing"):
            return
        self._set_state("closing")
        self._stop_live()
        session, self.session, self._frame = self.session, None, None
        job = JobWorker(session.close)
        job.done.connect(lambda _r: self._closed())
        job.failed.connect(lambda m: (self.status.setText(m), self._closed()))
        self._job = job
        job.start()

    def _stop_live(self) -> None:
        live, self._live = self._live, None
        if live is not None:
            live.stop()
            live.wait(5000)

    def _closed(self) -> None:
        self._set_state("off")

    def closeEvent(self, event) -> None:
        self._save_settings()
        self._exposure_timer.stop()
        self._stop_live()
        if self.session is not None:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self.session.close()   # the camera thread takes a moment to give the camera back
            except Exception:
                pass
            finally:
                QApplication.restoreOverrideCursor()
            self.session = None
        for job in (self._job, self._focus_job, self._exposure_job, self._auto_job, *list(self._alive)):
            if job is not None:
                job.wait(10000)
        super().closeEvent(event)

    def _save_settings(self) -> None:
        app_settings.save({"tether_camera": self.camera_combo.currentData(), "tether_sdk_dir": self.sdk_edit.text().strip(), "tether_folder": self.folder_edit.text().strip(),
                           "tether_prefix": naming.clean_prefix(self.prefix_edit.text()), "tether_settle": self.settle_spin.value(), "tether_show": self.show_check.isChecked()})

    # ------------------------------------------------------------ the live picture
    def _on_frame(self, frame) -> None:
        try:
            self._show_frame(frame)
        finally:
            if self._live is not None:
                self._live.ack()   # whatever happened while drawing, the worker is told it may send the next one

    def _show_frame(self, frame) -> None:
        self._frame = frame
        self._collect_flat(frame)
        now = time.monotonic()
        self._seen.append(now)
        fps = (len(self._seen) - 1) / (self._seen[-1] - self._seen[0]) if len(self._seen) > 2 and self._seen[-1] > self._seen[0] else 0.0
        h, w = frame.rgb.shape[:2]
        bad = [f"{c} {v:.1f}%" for c, v in frame.clipped.items() if v >= _CLIP_WARN]
        session = self.session
        region = None
        if session is not None:
            x0, y0, x1, y1 = liveview.region_box(frame.rgb.shape, *session.view.region)
            region = (x0 / w, y0 / h, x1 / w, y1 / h)
        self.image.set_frame(frame.image, region, f"{w} x {h}   {fps:.0f} fps", ("Blown out: " + "  ".join(bad)) if bad else "", frame.histogram)
        if self._camera_zoom_level == 1 and now - self._overview_at > 0.7:
            self.image.map.set_overview(frame.image)      # (the map's picture is the last whole one: it cannot be taken while zoomed)
            self._overview_at = now
        if session is not None:
            best = max(session.best, 1e-9)
            self.sharp_label.setText(f"Sharpness: {frame.sharpness:.2f}     best {session.best:.2f}")
            word, share = liveview.grade(frame.sharpness, session.best)
            self.grade_label.setText(f"{word}  ({share * 100:.0f}% of the best)" if word else "")
            self.grade_label.setStyleSheet(f"font-weight: bold; font-size: 15px; color: {_GRADE_COLOURS.get(word, THEME.text_primary)};")
            self.sharp_bar.setValue(int(min(100, 100 * frame.sharpness / best)))
            self.spark.set_values(session.history, session.best)
        if self.loupe_check.isChecked() and self._hover[0] >= 0 and session is not None:
            self.image.set_loupe(session.pipeline.loupe(frame, *self._hover, session.view))

    # ------------------------------------------------------------ N: a quick look at the other view
    def keyPressEvent(self, event) -> None:
        if event.key() == _PEEK_KEY and not event.modifiers() and not event.isAutoRepeat() and self.positive_check.isEnabled():
            if self._peek_from is None:
                self._peek_from = self.positive_check.isChecked()
                self.positive_check.setChecked(not self._peek_from)
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == _PEEK_KEY and not event.isAutoRepeat():
            self._end_peek()
            return
        super().keyReleaseEvent(event)

    def _end_peek(self) -> None:
        if self._peek_from is not None:
            was, self._peek_from = self._peek_from, None
            self.positive_check.setChecked(was)

    def focusOutEvent(self, event) -> None:
        self._end_peek()   # the release would go to another window
        super().focusOutEvent(event)

    def _view_changed(self, *_args) -> None:
        if not self._building:
            self._apply_view()

    def _apply_view(self) -> None:
        if self.session is not None:
            flat = self.flat_check.isChecked() and self._flat_gain is not None
            self.session.set_view(positive=self.positive_check.isChecked(), peaking=self.peaking_check.isChecked(), peaking_sensitivity=self.peaking_slider.value() / 100.0,
                                  flatfield=flat and self._camera_zoom_level == 1, metering=self.metering_combo.currentData())
            if flat and self._camera_zoom_level > 1:
                self.flat_label.setText("The flat field is off while the camera is zoomed in: it is of the whole picture.")
            elif self._flat_gain is not None and self._flat_frames is None:
                self.flat_label.setText("Evening out the preview with " + ("the flat field captured from the light." if self._flat_source == "captured" else "EFAS's permanent flat field.")
                                        if flat else "The flat field is kept but switched off.")

    def _histogram_toggled(self, on: bool) -> None:
        self.image.show_histogram = on
        self.image.update()

    def _loupe_toggled(self, on: bool) -> None:
        if not on:
            self.image.set_loupe(None)

    def _image_hovered(self, x: float, y: float) -> None:
        self._hover = (x, y)
        if x < 0:
            self.image.set_loupe(None)
        elif self.loupe_check.isChecked() and self._frame is not None and self.session is not None:
            self.image.set_loupe(self.session.pipeline.loupe(self._frame, x, y, self.session.view))

    def _image_clicked(self, x: float, y: float) -> None:
        if self.session is None or self._frame is None:
            return
        if self.base_button.isChecked():
            colour = self.session.pipeline.flat_colour(liveview.sample_colour(self._frame.rgb, x, y), x, y, self._frame.rgb.shape, self.session.view)
            self.session.set_view(base_rgb=colour)
            self.base_button.setChecked(False)
            self.base_label.setText("Film base: sampled, R {:.0f}  G {:.0f}  B {:.0f}.".format(*colour))
        else:
            self.session.set_view(region=(x, y, self.session.view.region[2]))

    def arm_base_pick(self) -> None:
        if self.base_button.isChecked():
            self.status.setStyleSheet("")
            self.status.setText("Click a patch of clear film on the picture.")

    def forget_base(self) -> None:
        if self.session is not None:
            self.session.set_view(base_rgb=None)
        self.base_button.setChecked(False)
        self.base_label.setText("Film base: worked out from the picture.")

    def reset_best(self) -> None:
        if self.session is not None:
            self.session.reset_best()

    def measure_centre(self) -> None:
        if self.session is not None:
            self.session.set_view(region=(0.5, 0.5, self.session.view.region[2]))

    def check_corners(self) -> None:
        if self._frame is None:
            return
        values = liveview.corner_sharpness(self._frame.rgb)
        centre = max(values["centre"], 1e-9)
        worst = min((v for k, v in values.items() if k != "centre"), default=centre)
        verdict = ("The corners are about as sharp as the middle." if worst >= 0.8 * centre else
                   f"The softest corner is only {100 * worst / centre:.0f}% as sharp as the middle: the camera may not be parallel to the film, or the lens may be soft at its edges.")
        self.corner_label.setText("  ".join(f"{k} {v:.1f}" for k, v in values.items()) + "\n" + verdict)

    # ------------------------------------------------------------ doing things
    def focus(self, direction: str, coarseness: str) -> None:
        if self._state != "live" or self.session is None or (self._focus_job is not None and self._focus_job.isRunning()):
            return
        session = self.session
        job = JobWorker(lambda: session.focus(direction, coarseness))
        job.failed.connect(self._focus_failed)
        self._focus_job = job
        job.start()

    def camera_zoom(self, level: int) -> None:
        """Camera zoom Fit / 5x / 10x: the camera zooms its own live picture (the picture gets real detail)."""
        if self._state != "live" or self.session is None:
            return
        for n, b in self.camera_zoom_buttons.items():
            b.setChecked(n == level)
        self._camera_zoom_level, self._camera_zoom_center = level, (0.5, 0.5)
        self.image.camera_pan = level > 1
        self.image.map.set_frame(level, self._camera_zoom_center)
        self.image.map.setVisible(level > 1)
        self._apply_view()
        self._send_camera_zoom(level, None)      # (the camera's own position for it: the middle, unless it says otherwise)

    def _camera_pan(self, fx: float, fy: float) -> None:
        """The picture was dragged by (fx, fy) of its size: it follows the pointer, so the camera's zoom frame moves the other way (a fifth or a tenth as far)."""
        cx, cy = self._camera_zoom_center
        level = max(1, self._camera_zoom_level)
        self._set_zoom_centre((cx - fx / level, cy - fy / level))

    def _camera_step(self, dx: int, dy: int) -> None:
        """Ctrl and an arrow key: move the zoom frame by half of what it shows."""
        cx, cy = self._camera_zoom_center
        half = 0.5 / max(1, self._camera_zoom_level)
        self._set_zoom_centre((cx + dx * half, cy + dy * half))

    def _zoom_map_moved(self, fx: float, fy: float) -> None:
        self._set_zoom_centre((fx, fy))

    def _set_zoom_centre(self, centre: tuple) -> None:
        """Put the middle of the camera's zoom frame here (fractions of the whole picture, held inside it) and ask the camera."""
        level = self._camera_zoom_level
        if self._state != "live" or self.session is None or level <= 1:
            return
        half = 0.5 / level
        self._camera_zoom_center = (min(max(centre[0], half), 1 - half), min(max(centre[1], half), 1 - half))
        self.image.map.set_frame(level, self._camera_zoom_center)
        self._send_camera_pan()

    def _send_camera_pan(self) -> None:
        """One request to the camera at a time: while one is on its way, further movement only changes where the next one goes."""
        if self._zoom_sending or self.session is None:
            return
        self._zoom_sending, self._zoom_sent = True, self._camera_zoom_center
        job = self._send_camera_zoom(self._camera_zoom_level, self._zoom_sent, pan=True)
        job.finished.connect(self._camera_pan_sent)

    def _camera_pan_sent(self) -> None:
        self._zoom_sending = False
        if self._camera_zoom_level > 1 and self._camera_zoom_center != self._zoom_sent:
            self._send_camera_pan()

    def _send_camera_zoom(self, level: int, center, pan: bool = False) -> JobWorker:
        session = self.session
        job = JobWorker(lambda: session.set_zoom(level) if center is None else session.set_zoom(level, center))
        job.failed.connect(self._focus_failed)
        if not pan:      # a zoom the camera refuses is not on; a move it refuses leaves the zoom as it is, and says so
            job.failed.connect(lambda _m: self._camera_zoom_refused())
        self._alive.add(job)
        job.finished.connect(lambda j=job: self._alive.discard(j))
        job.start()
        return job

    def _camera_zoom_refused(self) -> None:
        self._camera_zoom_level, self._camera_zoom_center = 1, (0.5, 0.5)
        self.image.camera_pan = False
        self.image.map.hide()
        for n, b in self.camera_zoom_buttons.items():
            b.setChecked(n == 1)
        self._apply_view()

    def _focus_failed(self, message: str) -> None:
        self.status.setStyleSheet(f"color: {THEME.status_critical};")
        self.status.setText(message)

    def capture(self) -> None:
        if self._state != "live" or self.session is None:
            return
        folder = self.folder_edit.text().strip()
        if not folder:
            self.status.setStyleSheet(f"color: {THEME.status_critical};")
            self.status.setText("Choose a folder to save the pictures in first.")
            return
        self._names_changed()
        self._save_settings()
        self.status.setStyleSheet("")
        self.status.setText(f"Waiting {self.settle_spin.value():g} s for the rig to settle, then taking the picture...")
        self._set_state("busy")
        self.capture_button.setEnabled(False)
        job = JobWorker(self.session.capture)
        job.done.connect(self._captured)
        job.failed.connect(self._capture_failed)
        self._job = job
        job.start()

    def _captured(self, paths) -> None:
        if self._state == "busy":
            self._set_state("live")
        names = ", ".join(os.path.basename(p) for p in paths)
        self.status.setStyleSheet("")
        self.status.setText(f"Saved {names}")
        for p in paths:
            item = QListWidgetItem(os.path.basename(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.recent.insertItem(0, item)
        while self.recent.count() > 12:
            self.recent.takeItem(self.recent.count() - 1)
        self._refresh_names()
        self.captured.emit(list(paths))
        main = primary_file(paths)
        if self.show_check.isChecked() and main:
            self.open_requested.emit(main)

    def _capture_failed(self, message: str) -> None:
        if self._state == "busy":
            self._set_state("live")
        self.status.setStyleSheet(f"color: {THEME.status_critical};")
        self.status.setText(message)
