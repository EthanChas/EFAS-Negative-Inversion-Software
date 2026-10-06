import numpy as np
from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent,
)
from PyQt6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from ...theme.tokens import THEME
from ...features.geometry.guides import CropGuide, guide_shapes
from ...features.retouch.curve import smooth_path
from .bevel_widgets import BevelPanel
from .loading_overlay import ExportIndicator, HqIndicator
from .peaking_slider import PeakingSlider

_PLACEHOLDER_TEXT = "No image open.\nUse File → Open Image... to get started."
_NO_MAX = 16777215  # Qt's own QWIDGETSIZE_MAX
_MIN_ZOOM = 0.05
_MAX_ZOOM = 8.0
_ZOOM_STEP = 0.9
_CROP_HANDLE_RADIUS = 8  # widget pixels - how close a click needs to be to grab a handle


def _checker_pixmap(cell: int = 4) -> QPixmap:
    """An 8x8 two-tone checker: opaque squares on one diagonal, clear on the other."""
    pix = QPixmap(cell * 2, cell * 2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.fillRect(0, 0, cell, cell, QColor(0, 0, 0, 255))
    p.fillRect(cell, cell, cell, cell, QColor(0, 0, 0, 255))
    p.end()
    return pix


def _grid_pixmap(cell: int = 7) -> QPixmap:
    """A square tile with a one-pixel line along its top and left edge - tiled, a grid of lines every `cell` pixels."""
    pix = QPixmap(cell, cell)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.fillRect(0, 0, cell, 1, QColor(0, 0, 0, 255))
    p.fillRect(0, 0, 1, cell, QColor(0, 0, 0, 255))
    p.end()
    return pix


def _rgb_to_pixmap(pixels: np.ndarray) -> QPixmap:
    pixels = np.ascontiguousarray(pixels)
    h, w, _ = pixels.shape
    image = QImage(pixels.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image.copy())  # copy() detaches from `pixels`' own buffer


class _ImageLabel(QLabel):
    """The label that actually shows the scaled pixmap - once an image is
    loaded its size always exactly matches the displayed (zoomed) pixmap, so
    mapping a mouse position to a source-image pixel is a plain division by
    the current scale, no centering-offset math needed."""

    pixel_hovered = pyqtSignal(int, int, object)  # image x, image y, (r, g, b)
    hover_cleared = pyqtSignal()
    pixel_picked = pyqtSignal(int, int, object)  # a click while in pick mode
    crop_requested = pyqtSignal(int, int, int, int)  # x1, y1, x2, y2, a drag while in crop mode
    drag_moved = pyqtSignal(int, int)  # dx, dy since the last drag_moved (screen pixels)
    proof_picked = pyqtSignal(int, int)  # a tile of the test strip / ring-around was clicked: row, column
    stroke_completed = pyqtSignal(object)  # list of (x, y) image-pixel points - a painted stroke or a finished polyline
    tool_clicked = pyqtSignal(float, float)  # a click while the single-click heal tool is active
    source_picked = pyqtSignal(float, float)  # an Alt-click while the clone tool is active: where to copy from, in image pixels

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self._pixels: np.ndarray | None = None
        self._scale = 1.0
        self._dragging = False
        self._drag_last_pos = None
        self._pick_mode = False
        self._pick_cursor: QCursor | None = None
        self._crop_mode = False
        self._cropping = False
        self._crop_rect_image: tuple[int, int, int, int] | None = None  # (x1,y1,x2,y2), image coords
        self._crop_handle: str | None = None  # "move", a compass code ("nw".."se"), or None
        self._crop_drag_anchor: tuple[float, float] | None = None  # widget-space press position
        self._crop_drag_start_rect: tuple[int, int, int, int] | None = None
        self._overlay: QImage | None = None
        self._overlay_buf: np.ndarray | None = None
        self._clip: QImage | None = None
        self._clip_buf: np.ndarray | None = None
        self._range: QImage | None = None
        self._range_buf: np.ndarray | None = None
        self._range_grid = QBrush(_grid_pixmap())
        self._peak: QImage | None = None
        self._clone_source: tuple[float, float] | None = None  # the clone tool's source and offset (image pixels), for the dashed marker
        self._clone_offset: tuple[float, float] | None = None
        self._peak_buf: np.ndarray | None = None
        self._checker = QBrush(_checker_pixmap())
        self._crop_ratio = None  # None = free, "original" = the frame's own shape, or a landscape w/h number
        self._guide = CropGuide.THIRDS
        self._guide_orientation = 0
        self._tool: str | None = None  # "heal" (drag), "smart" (click) or "polyline" (click points)
        self._tool_radius = None  # () -> brush radius in image pixels, for the cursor
        self._stroke: list[tuple[float, float]] = []
        self._painting = False
        self._hover: QPointF | None = None
        self._drag_button = Qt.MouseButton.LeftButton
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._proof: QImage | None = None  # the test strip / ring-around mosaic, drawn over the whole picture
        self._proof_buf = None
        self._proof_geometry = (1, 1, 0, 1, 1)  # tile width, tile height, gap, rows, columns - in mosaic pixels
        self._proof_labels: list[str] = []
        self._proof_banner = ""
        self._proof_hover: tuple[int, int] | None = None
        self._split: QImage | None = None  # the "before" picture, drawn over the left of the divider
        self._split_buf = None
        self._split_pos = 0.5              # the divider, as a share of the picture's width
        self._split_drag = False
        self.setMouseTracking(True)

    def set_source(self, pixels: np.ndarray | None) -> None:
        self._pixels = pixels

    def set_scale(self, scale: float) -> None:
        self._scale = scale

    def set_split(self, pixels: np.ndarray | None) -> None:
        """Before / after: `pixels` (the same picture before the edit, framed the same way) is shown left of a draggable divider, the edit right of
        it. None turns the split off."""
        if pixels is None:
            self._split = self._split_buf = None
            self._split_drag = False
        else:
            self._split_buf = np.ascontiguousarray(pixels)
            h, w = self._split_buf.shape[:2]
            self._split = QImage(self._split_buf.data, w, h, w * 3, QImage.Format.Format_RGB888)
        self.update()

    def split_active(self) -> bool:
        return self._split is not None

    def set_proof(self, mosaic: np.ndarray | None, tile: tuple[int, int] = (1, 1), gap: int = 0, grid: int = 5, labels: list[str] | None = None, banner: str = "") -> None:
        """A test strip / ring-around: `mosaic` is the grid x grid tiles (each tile[0] x tile[1] pixels, `gap` apart) already laid out; it covers the
        whole picture on screen like a contact sheet, each tile named by `labels` (row by row). None puts the picture back."""
        if mosaic is None:
            self._proof = self._proof_buf = None
            self._proof_hover = None
        else:
            self._proof_buf = np.ascontiguousarray(mosaic)
            h, w = self._proof_buf.shape[:2]
            self._proof = QImage(self._proof_buf.data, w, h, w * 3, QImage.Format.Format_RGB888)
            self._proof_geometry = (tile[0], tile[1], gap, grid, grid)
            self._proof_labels = list(labels or [])
            self._proof_banner = banner
        self.setCursor(Qt.CursorShape.PointingHandCursor) if mosaic is not None else self.unsetCursor()
        self.update()

    def proof_active(self) -> bool:
        return self._proof is not None

    def _proof_cell_rect(self, row: int, col: int) -> QRectF:
        tw, th, gap, rows, cols = self._proof_geometry
        mw, mh = cols * tw + (cols - 1) * gap, rows * th + (rows - 1) * gap
        sx, sy = self.width() / mw, self.height() / mh
        return QRectF(col * (tw + gap) * sx, row * (th + gap) * sy, tw * sx, th * sy)

    def _proof_cell_at(self, pos) -> tuple[int, int] | None:
        rows, cols = self._proof_geometry[3:]
        for row in range(rows):
            for col in range(cols):
                if self._proof_cell_rect(row, col).contains(pos):
                    return row, col
        return None

    def _paint_proof(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        painter.drawImage(QRectF(self.rect()), self._proof)
        rows, cols = self._proof_geometry[3:]
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        for row in range(rows):
            for col in range(cols):
                rect = self._proof_cell_rect(row, col)
                centre = (row, col) == (rows // 2, cols // 2)
                text = self._proof_labels[row * cols + col] if row * cols + col < len(self._proof_labels) else ""
                if text:
                    width = min(rect.width() - 8, painter.fontMetrics().horizontalAdvance(text) + 12)
                    badge = QRectF(rect.left() + 4, rect.bottom() - 24, width, 20)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(0, 0, 0, 170))
                    painter.drawRoundedRect(badge, 3, 3)
                    painter.setPen(QColor(255, 255, 255) if not centre else QColor(255, 210, 90))
                    painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
                if centre or (row, col) == self._proof_hover:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(QColor(255, 210, 90) if centre else QColor(255, 255, 255, 235), 2))
                    painter.drawRect(rect.adjusted(1, 1, -1, -1))
        if self._proof_banner:
            width = painter.fontMetrics().horizontalAdvance(self._proof_banner) + 24
            banner = QRectF((self.width() - width) / 2, 8, width, 24)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 190))
            painter.drawRoundedRect(banner, 4, 4)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(banner, Qt.AlignmentFlag.AlignCenter, self._proof_banner)

    def _near_divider(self, x: float) -> bool:
        return self._split is not None and abs(x - self._split_pos * self.width()) <= 10

    def _paint_split(self, painter: QPainter) -> None:
        x = round(self._split_pos * self.width())
        h = self.height()
        painter.save()
        painter.setClipRect(0, 0, x, h)
        painter.drawImage(QRectF(self.rect()), self._split)
        painter.restore()
        painter.setPen(QPen(QColor(255, 255, 255, 235), 2))
        painter.drawLine(x, 0, x, h)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawEllipse(QPointF(x, h / 2), 11, 11)
        painter.setPen(QPen(QColor(255, 255, 255, 235), 2))
        painter.drawLine(x - 4, int(h / 2) - 4, x - 7, int(h / 2))
        painter.drawLine(x - 7, int(h / 2), x - 4, int(h / 2) + 4)
        painter.drawLine(x + 4, int(h / 2) - 4, x + 7, int(h / 2))
        painter.drawLine(x + 7, int(h / 2), x + 4, int(h / 2) + 4)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        for text, at, align in (("BEFORE", 8, Qt.AlignmentFlag.AlignLeft), ("AFTER", self.width() - 8, Qt.AlignmentFlag.AlignRight)):
            width = painter.fontMetrics().horizontalAdvance(text) + 12
            left = at if align == Qt.AlignmentFlag.AlignLeft else at - width
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 160))
            painter.drawRoundedRect(QRectF(left, 8, width, 20), 3, 3)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(QRectF(left, 8, width, 20), Qt.AlignmentFlag.AlignCenter, text)

    def set_overlay(self, rgba: np.ndarray | None) -> None:
        """A (h, w, 4) RGBA wash drawn stretched over the whole image."""
        if rgba is None:
            self._overlay = self._overlay_buf = None
        else:
            self._overlay_buf = np.ascontiguousarray(rgba)
            h, w = self._overlay_buf.shape[:2]
            self._overlay = QImage(self._overlay_buf.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        self.update()

    def set_clip_overlay(self, rgba: np.ndarray | None) -> None:
        """Clipping marks: an (h, w, 4) RGBA (blue shadows / red highlights),
        stretched over the image and drawn through a checker pattern."""
        if rgba is None:
            self._clip = self._clip_buf = None
        else:
            self._clip_buf = np.ascontiguousarray(rgba)
            h, w = self._clip_buf.shape[:2]
            self._clip = QImage(self._clip_buf.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        self.update()

    def set_clone_marker(self, source, offset) -> None:
        """The clone tool's marker: source is the picked point (or None), offset the brush-to-source offset once fixed - both in image pixels."""
        self._clone_source, self._clone_offset = source, offset
        self.update()

    def set_range_overlay(self, rgba: np.ndarray | None) -> None:
        """The part of the picture whose brightness is selected on the Exposure graph: an (h, w, 4) green mask, stretched over the image and
        drawn through a grid pattern."""
        if rgba is None:
            self._range = self._range_buf = None
        else:
            self._range_buf = np.ascontiguousarray(rgba)
            h, w = self._range_buf.shape[:2]
            self._range = QImage(self._range_buf.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        self.update()

    def _paint_range(self, painter: QPainter, region: QRect) -> None:
        # Off-screen for just the exposed region, like the clipping marks: a faint green wash over the selected pixels, then the same
        # mask again kept only along the lines of a grid, so the area reads as a green lattice with the picture still visible through it.
        img = QImage(region.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.translate(-region.topLeft())
        p.setOpacity(0.16)
        p.drawImage(QRectF(self.rect()), self._range)
        p.setOpacity(1.0)
        lattice = QImage(region.size(), QImage.Format.Format_ARGB32_Premultiplied)
        lattice.fill(Qt.GlobalColor.transparent)
        q = QPainter(lattice)
        q.translate(-region.topLeft())
        q.drawImage(QRectF(self.rect()), self._range)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        q.fillRect(QRect(region.topLeft(), region.size()), self._range_grid)
        q.end()
        p.resetTransform()
        p.drawImage(0, 0, lattice)
        p.end()
        painter.drawImage(region.topLeft(), img)

    def set_peaking_overlay(self, rgba: np.ndarray | None) -> None:
        """Focus peaking marks: an (h, w, 4) RGBA (blue, green, yellow by how sharp), stretched over the image."""
        if rgba is None:
            self._peak = self._peak_buf = None
        else:
            self._peak_buf = np.ascontiguousarray(rgba)
            h, w = self._peak_buf.shape[:2]
            self._peak = QImage(self._peak_buf.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        self.update()

    def _paint_clip(self, painter: QPainter, region: QRect) -> None:
        # Composited off-screen for just the exposed region (a zoomed-in
        # label can be thousands of pixels wide): the marks, then a checker
        # fill keeps only every other square of them.
        img = QImage(region.size(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.translate(-region.topLeft())
        p.drawImage(QRectF(self.rect()), self._clip)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        p.fillRect(QRect(region.topLeft(), region.size()), self._checker)
        p.end()
        painter.drawImage(region.topLeft(), img)

    def set_tool(self, mode: str | None, radius_provider=None) -> None:
        """Heal-brush tools: mode None turns them off. radius_provider() is
        the cursor's brush radius in image pixels."""
        self._tool = mode
        self._tool_radius = radius_provider
        self._stroke = []
        self._painting = False
        if mode is not None:
            self.setCursor(Qt.CursorShape.BlankCursor)  # the brush circle is the cursor
        else:
            self.unsetCursor()
        self.update()

    def _img_pt(self, pos) -> tuple[float, float]:
        scale = self._scale if self._scale > 0 else 1.0
        return (pos.x() / scale, pos.y() / scale)

    def _line_tool(self) -> bool:
        """The click-point tools: "polyline" and "curve" (any number of points, finished by hand; the curve is smoothed through them) and
        "line2" (two points, finishes itself)."""
        return self._tool in ("polyline", "curve", "line2", "straighten")

    def _finish_polyline(self) -> None:
        stroke, self._stroke = self._stroke, []
        self.update()
        if len(stroke) >= 2:
            if self._tool == "curve":  # the smooth curve through the clicked points, as a dense polyline
                stroke = smooth_path(stroke, 2.0)
            self.stroke_completed.emit(stroke)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._line_tool():
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._finish_polyline()
                event.accept()
                return
            if key == Qt.Key.Key_Escape:
                self._stroke = []
                self.update()
                event.accept()
                return
            if key == Qt.Key.Key_Backspace:
                self._stroke = self._stroke[:-1]
                self.update()
                event.accept()
                return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._tool in ("polyline", "curve") and event.button() == Qt.MouseButton.LeftButton:
            self._finish_polyline()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def set_pick_mode(self, enabled: bool, cursor: QCursor | None = None) -> None:
        """While enabled, a left-click picks a pixel (pixel_picked) instead
        of starting the usual click-and-drag pan."""
        self._pick_mode = enabled
        self._pick_cursor = cursor
        if enabled and cursor is not None:
            self.setCursor(cursor)
        else:
            self.unsetCursor()

    def set_crop_mode(self, enabled: bool, cursor: QCursor | None = None, initial_rect=None) -> None:
        """While enabled, dragging defines/moves/resizes a crop rectangle
        (crop_requested on every release) instead of panning. initial_rect
        (x1,y1,x2,y2 in image coords), when given, starts as the active,
        draggable selection - re-entering crop mode on an image that
        already has a crop picks up right where that crop left off,
        instead of forcing a redraw from scratch."""
        self._crop_mode = enabled
        self._cropping = False
        self._crop_handle = None
        self._crop_rect_image = initial_rect if enabled else None
        if enabled and cursor is not None:
            self.setCursor(cursor)
        else:
            self.unsetCursor()
        self.update()

    def set_crop_guide(self, guide: str, orientation: int = 0) -> None:
        """The composition guide drawn inside the crop rectangle."""
        self._guide = CropGuide(guide)
        self._guide_orientation = orientation
        self.update()

    def set_crop_ratio(self, ratio) -> None:
        """Constrain the crop to an aspect ratio: None for free, "original"
        for the frame's own shape, or a number w/h >= 1 (auto-oriented to
        landscape or portrait by the drag). While cropping, an existing
        rectangle snaps to the ratio right away - the largest one that fits
        inside it, same center - and is reported like any other crop."""
        self._crop_ratio = ratio
        if not self._crop_mode or self._pixels is None or ratio is None:
            return
        h, w = self._pixels.shape[:2]
        x1, y1, x2, y2 = self._crop_rect_image or (0, 0, w, h)
        landscape = (x2 - x1) >= (y2 - y1)
        r = self._ratio_value(landscape)
        bw, bh = x2 - x1, y2 - y1
        if bw / max(bh, 1) > r:
            bw = bh * r
        else:
            bh = bw / r
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        rect = (round(cx - bw / 2), round(cy - bh / 2), round(cx + bw / 2), round(cy + bh / 2))
        self._crop_rect_image = rect
        self.update()
        if rect[2] - rect[0] >= 1 and rect[3] - rect[1] >= 1:
            self.crop_requested.emit(*rect)

    def _ratio_value(self, landscape: bool) -> float:
        """The w/h to hold the crop to (needs a ratio to be set)."""
        if self._crop_ratio == "original":
            h, w = self._pixels.shape[:2]
            return w / h
        r = float(self._crop_ratio)
        return r if landscape else 1.0 / r

    def _constrain_to_ratio(self, rect, start_rect, handle: str):
        """rect is the dragged rectangle; returns it held to the ratio. A
        corner handle keeps the opposite corner fixed and fits the ratio
        inside the dragged box; an edge handle drives that dimension and
        resizes the other about its center."""
        h_img, w_img = self._pixels.shape[:2]
        sx1, sy1, sx2, sy2 = start_rect
        fresh = (sx2 - sx1) == 0 or (sy2 - sy1) == 0  # just started drawing: the drag picks the orientation
        x1, y1, x2, y2 = rect
        if handle in ("nw", "ne", "sw", "se"):
            ax, ay = (sx2 if "w" in handle else sx1), (sy2 if "n" in handle else sy1)
            mx, my = (x1 if "w" in handle else x2), (y1 if "n" in handle else y2)
            dx, dy = (1 if mx >= ax else -1), (1 if my >= ay else -1)
            bw, bh = abs(mx - ax), abs(my - ay)
            landscape = bw >= bh if fresh else (sx2 - sx1) >= (sy2 - sy1)
            r = self._ratio_value(landscape)
            if bw / max(bh, 1e-6) > r:
                bw = bh * r
            else:
                bh = bw / r
            max_w = (w_img - ax) if dx > 0 else ax
            max_h = (h_img - ay) if dy > 0 else ay
            if bw > max_w:
                bw, bh = max_w, max_w / r
            if bh > max_h:
                bw, bh = max_h * r, max_h
            nx, ny = ax + dx * bw, ay + dy * bh
            return (round(min(ax, nx)), round(min(ay, ny)), round(max(ax, nx)), round(max(ay, ny)))
        landscape = (sx2 - sx1) >= (sy2 - sy1)
        r = self._ratio_value(landscape)
        if handle in ("e", "w"):
            bw = x2 - x1
            bh = bw / r
            cy = (sy1 + sy2) / 2
            limit = 2 * min(cy, h_img - cy)
            if bh > limit:
                bh, bw = limit, limit * r
            if handle == "e":
                return (round(x1), round(cy - bh / 2), round(x1 + bw), round(cy + bh / 2))
            return (round(x2 - bw), round(cy - bh / 2), round(x2), round(cy + bh / 2))
        bh = y2 - y1  # "n" / "s"
        bw = bh * r
        cx = (sx1 + sx2) / 2
        limit = 2 * min(cx, w_img - cx)
        if bw > limit:
            bw, bh = limit, limit / r
        if handle == "s":
            return (round(cx - bw / 2), round(y1), round(cx + bw / 2), round(y1 + bh))
        return (round(cx - bw / 2), round(y2 - bh), round(cx + bw / 2), round(y2))

    def _paint_guide(self, painter: QPainter, rect: QRect) -> None:
        """The composition guide, clipped to the crop rectangle."""
        shapes = guide_shapes(self._guide, rect.width(), rect.height(), self._guide_orientation)
        if not shapes:
            return
        painter.save()
        painter.setClipRect(rect)
        painter.translate(rect.topLeft())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for color, width in ((QColor(0, 0, 0, 110), 2.0), (QColor(255, 255, 255, 200), 1.0)):
            painter.setPen(QPen(color, width))
            for shape in shapes:
                points = [QPointF(x, y) for x, y in shape]
                painter.drawPolyline(points) if len(points) > 2 else painter.drawLine(points[0], points[1])
        painter.restore()

    def set_crop_selection(self, rect) -> None:
        """Replace the crop overlay's rect directly (e.g. Clear Crop),
        without going through a drag."""
        self._crop_rect_image = rect
        self.update()

    def _to_image_coords(self, wx: float, wy: float) -> tuple[int, int]:
        if self._pixels is None or self._scale <= 0:
            return 0, 0
        h, w = self._pixels.shape[:2]
        return min(max(round(wx / self._scale), 0), w), min(max(round(wy / self._scale), 0), h)

    def _crop_handle_at(self, pos) -> str | None:
        """Which handle (if any) a widget-space point is close enough to
        grab - the 8 compass points around the current crop rect, or
        "move" for anywhere inside its body."""
        if self._crop_rect_image is None or self._scale <= 0:
            return None
        x1, y1, x2, y2 = self._crop_rect_image
        wx1, wy1, wx2, wy2 = x1 * self._scale, y1 * self._scale, x2 * self._scale, y2 * self._scale
        midx, midy = (wx1 + wx2) / 2, (wy1 + wy2) / 2
        handles = {
            "nw": (wx1, wy1), "n": (midx, wy1), "ne": (wx2, wy1),
            "w": (wx1, midy), "e": (wx2, midy),
            "sw": (wx1, wy2), "s": (midx, wy2), "se": (wx2, wy2),
        }
        for name, (hx, hy) in handles.items():
            if abs(pos.x() - hx) <= _CROP_HANDLE_RADIUS and abs(pos.y() - hy) <= _CROP_HANDLE_RADIUS:
                return name
        if wx1 <= pos.x() <= wx2 and wy1 <= pos.y() <= wy2:
            return "move"
        return None

    def _update_crop_drag(self, wx: float, wy: float) -> None:
        if self._crop_drag_start_rect is None or self._scale <= 0 or self._pixels is None:
            return
        h, w = self._pixels.shape[:2]
        dx = (wx - self._crop_drag_anchor[0]) / self._scale
        dy = (wy - self._crop_drag_anchor[1]) / self._scale
        x1, y1, x2, y2 = self._crop_drag_start_rect

        if self._crop_handle == "move":
            rw, rh = x2 - x1, y2 - y1
            x1 = min(max(x1 + dx, 0), w - rw)
            y1 = min(max(y1 + dy, 0), h - rh)
            x2, y2 = x1 + rw, y1 + rh
        else:
            handle = self._crop_handle or ""
            if "w" in handle:
                x1 = min(max(x1 + dx, 0), w)
            if "e" in handle:
                x2 = min(max(x2 + dx, 0), w)
            if "n" in handle:
                y1 = min(max(y1 + dy, 0), h)
            if "s" in handle:
                y2 = min(max(y2 + dy, 0), h)

        rect = (round(x1), round(y1), round(x2), round(y2))
        if self._crop_ratio is not None and self._crop_handle != "move":
            rect = self._constrain_to_ratio((x1, y1, x2, y2), self._crop_drag_start_rect, self._crop_handle or "se")
        self._crop_rect_image = rect

    def _pixel_at(self, pos) -> tuple[int, int, tuple[int, int, int]] | None:
        if self._pixels is None or self._scale <= 0:
            return None
        h, w = self._pixels.shape[:2]
        img_x = int(pos.x() / self._scale)
        img_y = int(pos.y() / self._scale)
        if img_x < 0 or img_y < 0 or img_x >= w or img_y >= h:
            return None
        r, g, b = (int(v) for v in self._pixels[img_y, img_x])
        return img_x, img_y, (r, g, b)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._proof is not None:
            if event.button() == Qt.MouseButton.LeftButton:
                cell = self._proof_cell_at(event.position())
                if cell is not None:
                    self.proof_picked.emit(*cell)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._split is not None and self._tool is None and self._near_divider(event.position().x()):
            self._split_drag = True  # grab the divider
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._crop_mode and self._pixels is not None:
            pos = event.position()
            handle = self._crop_handle_at(pos)
            if handle is None:
                # No existing rect, or clicked outside it - start a brand
                # new one, anchored at this point (dragging its own
                # bottom-right corner from here).
                img_pt = self._to_image_coords(pos.x(), pos.y())
                self._crop_rect_image = (img_pt[0], img_pt[1], img_pt[0], img_pt[1])
                handle = "se"
            self._cropping = True
            self._crop_handle = handle
            self._crop_drag_anchor = (pos.x(), pos.y())
            self._crop_drag_start_rect = self._crop_rect_image
            self.update()
            event.accept()
            return
        if self._tool is not None and event.button() == Qt.MouseButton.LeftButton and self._pixels is not None:
            pt = self._img_pt(event.position())
            self.setFocus()
            if self._tool == "clone" and event.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.source_picked.emit(*pt)
            elif self._tool in ("heal", "clone"):
                self._painting = True
                self._stroke = [pt]
            elif self._tool == "smart":
                self.tool_clicked.emit(*pt)
            elif self._tool in ("line2", "straighten"):  # two clicks: the second one finishes it
                self._stroke.append(pt)
                if len(self._stroke) >= 2:
                    self._finish_polyline()
            else:  # polyline: each click adds a point; double-click or Enter finishes
                self._stroke.append(pt)
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton and self._pixels is not None and self._tool is not None:
            # With a brush tool active the left button paints, so pan with the middle one.
            self._dragging = True
            self._drag_button = Qt.MouseButton.MiddleButton
            self._drag_last_pos = event.globalPosition()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pick_mode:
            picked = self._pixel_at(event.position())
            if picked is not None:
                self.pixel_picked.emit(*picked)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pixels is not None:
            self._dragging = True
            self._drag_button = Qt.MouseButton.LeftButton
            self._drag_last_pos = event.globalPosition()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._proof is not None:
            cell = self._proof_cell_at(event.position())
            if cell != self._proof_hover:
                self._proof_hover = cell
                self.update()
            event.accept()
            return
        if self._split_drag:
            self._split_pos = min(1.0, max(0.0, event.position().x() / max(1, self.width())))
            self.update()
            event.accept()
            return
        if self._split is not None and self._tool is None and not self._dragging:
            if self._near_divider(event.position().x()):
                self.setCursor(Qt.CursorShape.SplitHCursor)
            else:
                self.unsetCursor()
        if self._cropping:
            pos = event.position()
            self._update_crop_drag(pos.x(), pos.y())
            self.update()
            return

        if self._dragging:
            pos = event.globalPosition()
            dx = pos.x() - self._drag_last_pos.x()
            dy = pos.y() - self._drag_last_pos.y()
            self._drag_last_pos = pos
            self.drag_moved.emit(int(dx), int(dy))
            return

        if self._tool is not None:
            self._hover = event.position()
            if self._painting:
                pt = self._img_pt(event.position())
                last = self._stroke[-1]
                if (pt[0] - last[0]) ** 2 + (pt[1] - last[1]) ** 2 >= 4.0:  # ~2 image px between samples
                    self._stroke.append(pt)
            self.update()
        super().mouseMoveEvent(event)
        picked = self._pixel_at(event.position())
        if picked is None:
            self.hover_cleared.emit()
            return
        self.pixel_hovered.emit(*picked)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._split_drag:
            self._split_drag = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._cropping:
            self._cropping = False
            self._crop_handle = None
            self._crop_drag_anchor = None
            self._crop_drag_start_rect = None
            rect = self._crop_rect_image
            self.update()
            if rect is not None:
                x1, y1, x2, y2 = rect
                if abs(x2 - x1) >= 1 and abs(y2 - y1) >= 1:
                    self.crop_requested.emit(x1, y1, x2, y2)
                else:
                    self._crop_rect_image = None  # degenerate (a plain click) - discard
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._painting:
            self._painting = False
            stroke, self._stroke = self._stroke, []
            self.update()
            if stroke:
                self.stroke_completed.emit(stroke)
            event.accept()
            return
        if event.button() == self._drag_button and self._dragging:
            self._dragging = False
            if self._tool is not None:
                self.setCursor(Qt.CursorShape.BlankCursor)
            elif self._pick_mode and self._pick_cursor is not None:
                self.setCursor(self._pick_cursor)
            else:
                self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hover = None
        if self._tool is not None:
            self.update()
        if not self._dragging:
            self.hover_cleared.emit()

    def _paint_tool(self, painter: QPainter) -> None:
        scale = self._scale
        radius = max(1.0, (self._tool_radius() if self._tool_radius else 4.0) * scale)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._stroke:
            pts = [QPointF(x * scale, y * scale) for x, y in self._stroke]
            if self._tool in ("heal", "clone"):  # the capsule the brush has painted so far
                band = QPen(QColor(255, 200, 0, 90), 2 * radius)
                band.setCapStyle(Qt.PenCapStyle.RoundCap)
                band.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(band)
                if len(pts) == 1:
                    painter.drawPoint(pts[0])
                else:
                    painter.drawPolyline(pts)
            else:  # polyline: the clicked points, plus a rubber band to the cursor
                painter.setPen(QPen(QColor(255, 200, 0, 220), 1.5))
                path = pts + ([self._hover] if self._hover is not None else [])
                if self._tool == "curve" and len(path) > 1:  # the curve as it will be repaired, with the cursor as its next point
                    path = [QPointF(x, y) for x, y in smooth_path([(p.x(), p.y()) for p in path], 3.0)]
                if len(path) > 1:
                    painter.drawPolyline(path)
                if self._tool == "line2" and len(pts) == 1 and self._hover is not None and abs(self._hover.x() - pts[0].x()) > 4:
                    # the line as it will be repaired: carried on past both points to the edges of the picture
                    slope = (self._hover.y() - pts[0].y()) / (self._hover.x() - pts[0].x())
                    right = float(self.width())
                    painter.setPen(QPen(QColor(255, 200, 0, 120), 1, Qt.PenStyle.DashLine))
                    painter.drawLine(QPointF(0.0, pts[0].y() - slope * pts[0].x()), QPointF(right, pts[0].y() + slope * (right - pts[0].x())))
                painter.setBrush(QColor(255, 200, 0, 220))
                for p in pts:
                    painter.drawEllipse(p, 3, 3)
        if self._tool == "clone" and self._clone_source is not None:
            # where the brush copies from: the picked source until the first stroke, then following the brush at the same offset
            if self._clone_offset is not None and self._hover is not None:
                at = QPointF(self._hover.x() + self._clone_offset[0] * scale, self._hover.y() + self._clone_offset[1] * scale)
            elif self._clone_offset is None:
                at = QPointF(self._clone_source[0] * scale, self._clone_source[1] * scale)
            else:
                at = None
            if at is not None:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
                painter.drawEllipse(at, radius, radius)
                dashed = QPen(QColor(255, 255, 255, 240), 1.5, Qt.PenStyle.DashLine)
                painter.setPen(dashed)
                painter.drawEllipse(at, radius, radius)
                painter.drawLine(QPointF(at.x() - 4, at.y()), QPointF(at.x() + 4, at.y()))
                painter.drawLine(QPointF(at.x(), at.y() - 4), QPointF(at.x(), at.y() + 4))
        if self._hover is not None and self._tool in ("heal", "smart", "clone"):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(0, 0, 0, 200), 3))
            painter.drawEllipse(self._hover, radius, radius)
            painter.setPen(QPen(QColor(255, 255, 255, 240), 1.5))
            painter.drawEllipse(self._hover, radius, radius)
        elif self._hover is not None and self._line_tool():
            painter.setPen(QPen(QColor(255, 255, 255, 240), 1.5))
            painter.drawLine(QPointF(self._hover.x() - 6, self._hover.y()), QPointF(self._hover.x() + 6, self._hover.y()))
            painter.drawLine(QPointF(self._hover.x(), self._hover.y() - 6), QPointF(self._hover.x(), self._hover.y() + 6))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._overlay is not None and not self._crop_mode:
            painter = QPainter(self)
            painter.drawImage(QRectF(self.rect()), self._overlay)
            painter.end()
        if self._clip is not None and not self._crop_mode:
            painter = QPainter(self)
            self._paint_clip(painter, event.rect().intersected(self.rect()))
            painter.end()
        if self._range is not None and not self._crop_mode:
            painter = QPainter(self)
            self._paint_range(painter, event.rect().intersected(self.rect()))
            painter.end()
        if self._peak is not None and not self._crop_mode:
            painter = QPainter(self)
            painter.drawImage(QRectF(self.rect()), self._peak)
            painter.end()
        if self._split is not None and not self._crop_mode:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_split(painter)
            painter.end()
        if self._proof is not None and not self._crop_mode:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            self._paint_proof(painter)
            painter.end()
            return
        if self._tool is not None and not self._crop_mode:
            painter = QPainter(self)
            self._paint_tool(painter)
            painter.end()
        if not self._crop_mode or self._crop_rect_image is None or self._scale <= 0:
            return

        x1, y1, x2, y2 = self._crop_rect_image
        left, right = sorted((x1 * self._scale, x2 * self._scale))
        top, bottom = sorted((y1 * self._scale, y2 * self._scale))
        rect = QRect(round(left), round(top), round(right - left), round(bottom - top))

        painter = QPainter(self)
        dim = QColor(0, 0, 0, 120)
        full = self.rect()
        painter.fillRect(QRect(0, 0, full.width(), rect.top()), dim)
        painter.fillRect(QRect(0, rect.bottom(), full.width(), full.height() - rect.bottom()), dim)
        painter.fillRect(QRect(0, rect.top(), rect.left(), rect.height()), dim)
        painter.fillRect(QRect(rect.right(), rect.top(), full.width() - rect.right(), rect.height()), dim)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.PenStyle.DashLine))
        painter.drawRect(rect)
        self._paint_guide(painter, rect)

        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        half = _CROP_HANDLE_RADIUS // 2
        midx, midy = (rect.left() + rect.right()) / 2, (rect.top() + rect.bottom()) / 2
        for hx, hy in (
            (rect.left(), rect.top()), (midx, rect.top()), (rect.right(), rect.top()),
            (rect.left(), midy), (rect.right(), midy),
            (rect.left(), rect.bottom()), (midx, rect.bottom()), (rect.right(), rect.bottom()),
        ):
            painter.drawRect(QRect(round(hx - half), round(hy - half), half * 2, half * 2))
        painter.end()


class _ZoomScrollArea(QScrollArea):
    """A QScrollArea whose wheel turns into zoom instead of the usual
    scroll - panning (once zoomed past the viewport) still works via the
    scrollbars/drag, that's just not what the wheel does here."""

    wheel_zoomed = pyqtSignal(int)  # angleDelta().y()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.wheel_zoomed.emit(event.angleDelta().y())
        event.accept()


class ImageView(QWidget):
    """Shows the currently open image in a sunken viewport: centered and
    scaled to fit when first opened or after Reset, then freely zoomable
    with the scroll wheel (panning via the scrollbars once zoomed past the
    viewport). Emits pixel_hovered(x, y, rgb) while the mouse moves over the
    image, and zoom_changed(percent) - percent of the image's actual pixel
    size, the normal photo-viewer convention - whenever the zoom changes."""

    pixel_hovered = pyqtSignal(int, int, object)
    hover_cleared = pyqtSignal()
    pixel_picked = pyqtSignal(int, int, object)
    crop_requested = pyqtSignal(int, int, int, int)
    zoom_changed = pyqtSignal(float)
    stroke_completed = pyqtSignal(object)
    proof_picked = pyqtSignal(int, int)
    tool_clicked = pyqtSignal(float, float)
    source_picked = pyqtSignal(float, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._viewport = BevelPanel(sunken=True, bg=THEME.bg_input, thickness=1)
        outer.addWidget(self._viewport)

        self._scroll = _ZoomScrollArea()
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidgetResizable(True)  # until an image is loaded - see clear()
        self._scroll.wheel_zoomed.connect(self._on_wheel_zoom)
        self._viewport.layout().addWidget(self._scroll)

        self._label = _ImageLabel()
        self._label.setText(_PLACEHOLDER_TEXT)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setProperty("role", "subtitle")
        self._label.pixel_hovered.connect(self.pixel_hovered)
        self._label.hover_cleared.connect(self.hover_cleared)
        self._label.pixel_picked.connect(self.pixel_picked)
        self._label.crop_requested.connect(self.crop_requested)
        self._label.drag_moved.connect(self._on_drag_moved)
        self._label.stroke_completed.connect(self.stroke_completed)
        self._label.proof_picked.connect(self.proof_picked)
        self._label.tool_clicked.connect(self.tool_clicked)
        self._label.source_picked.connect(self.source_picked)
        self._scroll.setWidget(self._label)

        self._hq_indicator = HqIndicator(self)
        self._export_indicator = ExportIndicator(self)
        self.peaking_slider = PeakingSlider(self)
        self._peaking_anchor = None  # () -> x in this view's coordinates that the slider is centred over (the Peaking button)
        self._pixmap: QPixmap | None = None
        self._fit_scale = 1.0
        self._zoom = 1.0

    def set_image(self, pixels: np.ndarray) -> None:
        self._pixmap = _rgb_to_pixmap(pixels)
        self._label.set_source(pixels)
        self._scroll.setWidgetResizable(False)  # the label now sizes itself, for zoom/pan
        self._recompute_fit_scale()
        self._zoom = 1.0
        self._apply_zoom()

    def update_pixels(self, pixels: np.ndarray) -> None:
        """Refresh the displayed pixel data in place (e.g. after an
        exposure adjustment) at whatever zoom/pan is already set, unlike
        set_image() - which is for actually opening a different image."""
        if self._pixmap is None:
            return
        old_w = self._pixmap.width()
        self._pixmap = _rgb_to_pixmap(pixels)
        # The same picture at a different pixel size (the HQ toggle, or a
        # low-res drag preview giving way to the full-res render): keep it
        # the same size on screen instead of jumping, and let the reported
        # zoom percent track the true pixel size.
        if old_w > 0 and self._pixmap.width() != old_w:
            self._fit_scale *= old_w / self._pixmap.width()
        self._label.set_source(pixels)
        self._apply_zoom()

    def set_overlay(self, rgba: np.ndarray | None) -> None:
        self._label.set_overlay(rgba)

    def set_clip_overlay(self, rgba: np.ndarray | None) -> None:
        self._label.set_clip_overlay(rgba)

    def set_peaking_overlay(self, rgba: np.ndarray | None) -> None:
        self._label.set_peaking_overlay(rgba)

    def set_range_overlay(self, rgba: np.ndarray | None) -> None:
        self._label.set_range_overlay(rgba)

    def set_clone_marker(self, source, offset) -> None:
        self._label.set_clone_marker(source, offset)

    def set_hq_state(self, mode: str, detail: str = "") -> None:
        """The HQ tag in the bottom-right corner: "loading" (a loading bar), "ready" (a yellow HQ tag, with detail beside it) or "off"."""
        if mode == "loading":
            self._hq_indicator.show_loading()
        elif mode == "ready":
            self._hq_indicator.show_ready(detail)
        else:
            self._hq_indicator.hide_indicator()
        self._place_badge()

    def set_export_progress(self, photos_done: int, photos_total: int, fraction: float) -> None:
        """The export tag in the top-left corner: the spinner, bar and "3/12 \u00b7 9 left"."""
        self._export_indicator.set_progress(photos_done, photos_total, fraction)
        self._place_badge()

    def set_peaking_slider_visible(self, visible: bool, anchor=None) -> None:
        """Show the focus-peaking level slider above the Peaking button; anchor() gives the x (in this view) to centre it over."""
        self._peaking_anchor = anchor
        self.peaking_slider.setVisible(visible)
        if visible:
            self.peaking_slider.raise_()
        self._place_badge()

    def end_export_progress(self) -> None:
        self._export_indicator.finish()

    def _place_badge(self) -> None:
        ind = self._hq_indicator
        ind.move(self.width() - ind.width() - 16, self.height() - ind.height() - 16)
        self._export_indicator.move(16, 16)
        slider = self.peaking_slider
        if slider.isVisible():
            x = self._peaking_anchor() if self._peaking_anchor is not None else self.width() // 2
            slider.move(max(8, min(self.width() - slider.width() - 8, x - slider.width() // 2)), self.height() - slider.height() - 12)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_badge()

    def set_tool(self, mode: str | None, radius_provider=None) -> None:
        self._label.set_tool(mode, radius_provider)

    def set_split(self, pixels: np.ndarray | None) -> None:
        self._label.set_split(pixels)

    def set_proof(self, mosaic, tile=(1, 1), gap: int = 0, grid: int = 5, labels=None, banner: str = "") -> None:
        self._label.set_proof(mosaic, tile, gap, grid, labels, banner)

    def proof_active(self) -> bool:
        return self._label.proof_active()

    def split_active(self) -> bool:
        return self._label.split_active()

    def set_crop_guide(self, guide: str, orientation: int = 0) -> None:
        self._label.set_crop_guide(guide, orientation)

    def set_crop_ratio(self, ratio) -> None:
        self._label.set_crop_ratio(ratio)

    def set_pick_mode(self, enabled: bool, cursor: QCursor | None = None) -> None:
        """While enabled, a left-click on the image emits pixel_picked
        instead of starting the usual click-and-drag pan - used by the tone
        curve's eyedropper."""
        self._label.set_pick_mode(enabled, cursor)

    def enter_crop_mode(self, preview_pixels: np.ndarray, initial_rect, cursor: QCursor) -> None:
        """Shows preview_pixels (the pre-crop frame) at fit-to-viewport
        zoom, with initial_rect (an existing crop, if any) as the starting,
        draggable selection - so re-opening the Crop tool on an
        already-cropped image picks up where that crop left off, at full
        zoomed-out extent, rather than forcing a redraw from scratch."""
        self._pixmap = _rgb_to_pixmap(preview_pixels)
        self._label.set_source(preview_pixels)
        self._recompute_fit_scale()
        self._zoom = 1.0
        self._apply_zoom()
        self._label.set_crop_mode(True, cursor, initial_rect)

    def exit_crop_mode(self, pixels: np.ndarray) -> None:
        """Back to showing the real (post-crop) image - whatever crop was
        last applied is already baked into pixels."""
        self._label.set_crop_mode(False)
        self.update_pixels(pixels)

    def clear_crop_selection(self) -> None:
        """Drops the crop overlay's rect directly (Clear Crop), without a
        drag - a no-op if crop mode isn't currently active."""
        self._label.set_crop_selection(None)

    def reset_crop_mode(self) -> None:
        """Forces crop mode off without needing a frame to switch to - used
        when a new file is opened (set_image() is about to replace the
        whole display anyway)."""
        self._label.set_crop_mode(False)

    def clear(self) -> None:
        self._pixmap = None
        self._label.set_source(None)
        self._label.setMinimumSize(0, 0)
        self._label.setMaximumSize(_NO_MAX, _NO_MAX)
        self._label.setText(_PLACEHOLDER_TEXT)
        self._scroll.setWidgetResizable(True)

    def reset_zoom(self) -> None:
        """The bottom-bar Reset button - back to fit-to-viewport, recomputed
        fresh in case the window was resized since the image was opened."""
        if self._pixmap is None:
            return
        self._recompute_fit_scale()
        self._zoom = 1.0
        self._apply_zoom()

    def toggle_fit_100(self) -> None:
        """The Z key: fit to the window, or - when already fitted - the image's actual pixels (100%)."""
        if self._pixmap is None:
            return
        if abs(self._zoom - 1.0) < 1e-3:
            self.set_zoom_percent(100)
        else:
            self.reset_zoom()

    def set_zoom_percent(self, percent: float) -> None:
        """A preset from the zoom dropdown - an absolute percentage of the
        image's actual pixel size, independent of the current fit baseline."""
        if self._pixmap is None or self._fit_scale <= 0:
            return
        self._zoom = min(_MAX_ZOOM, max(_MIN_ZOOM, (percent / 100) / self._fit_scale))
        self._apply_zoom()

    # No resizeEvent override: the zoom level stays stable across an
    # ordinary window resize (recomputing fit on every resize would
    # silently change what "100%" means underfoot) - only Reset recomputes
    # the fit baseline.

    def _on_wheel_zoom(self, angle_delta_y: int) -> None:
        if self._pixmap is None:
            return
        factor = 1 / _ZOOM_STEP if angle_delta_y > 0 else _ZOOM_STEP
        new_zoom = min(_MAX_ZOOM, max(_MIN_ZOOM, self._zoom * factor))
        if new_zoom == self._zoom:
            return

        # Zoom around the viewport's current center rather than the cursor -
        # simpler and robust regardless of whether the content is currently
        # smaller than the viewport (and thus centered, not scrolled).
        hbar, vbar = self._scroll.horizontalScrollBar(), self._scroll.verticalScrollBar()
        viewport_size = self._scroll.viewport().size()
        center_x = hbar.value() + viewport_size.width() / 2
        center_y = vbar.value() + viewport_size.height() / 2
        ratio = new_zoom / self._zoom

        self._zoom = new_zoom
        self._apply_zoom()

        hbar.setValue(int(center_x * ratio - viewport_size.width() / 2))
        vbar.setValue(int(center_y * ratio - viewport_size.height() / 2))

    def _on_drag_moved(self, dx: int, dy: int) -> None:
        hbar, vbar = self._scroll.horizontalScrollBar(), self._scroll.verticalScrollBar()
        hbar.setValue(hbar.value() - dx)
        vbar.setValue(vbar.value() - dy)

    def _recompute_fit_scale(self) -> None:
        if self._pixmap is None or self._pixmap.width() <= 0 or self._pixmap.height() <= 0:
            self._fit_scale = 1.0
            return
        viewport_size = self._scroll.viewport().size()
        if viewport_size.width() <= 0 or viewport_size.height() <= 0:
            self._fit_scale = 1.0
            return
        self._fit_scale = min(
            viewport_size.width() / self._pixmap.width(),
            viewport_size.height() / self._pixmap.height(),
        )

    def _apply_zoom(self) -> None:
        if self._pixmap is None:
            return
        scale = self._fit_scale * self._zoom
        w = max(1, round(self._pixmap.width() * scale))
        h = max(1, round(self._pixmap.height() * scale))
        scaled = self._pixmap.scaled(
            w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self._label.setPixmap(scaled)
        self._label.setFixedSize(scaled.size())
        self._label.set_scale(scale)
        self.zoom_changed.emit(scale * 100)
