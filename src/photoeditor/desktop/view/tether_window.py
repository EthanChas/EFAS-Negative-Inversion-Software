"""Extra > Canon Tether and Live View: the camera's live picture in EFAS - as a positive, with focus peaking and a loupe - the lens driven from the computer with a sharpness meter to
find the sharpest spot by, and the shutter, saving each picture into a roll folder under a numbered name.

Everything about the camera happens off the window's thread (features/tether, desktop/tether_worker): the window only draws what it is handed and sends requests. The practice camera
(a made-up negative with a lens that goes out of focus) lets every control be tried without a camera. A Canon camera needs Canon's own EDSDK, which EFAS cannot include.
The approach follows the Canon EDSDK Film Scanner by Rafat Hossain (MIT); the code is EFAS's own.
"""

import os
import time
from collections import deque

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPen, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from ...features.focuspeaking import logic as peaking
from ...features.lightcheck.capture import RAW_EXTS
from ...features.open_image.logic import SUPPORTED_EXTS
from ...features.settings import logic as app_settings
from ...features.tether import edsdk_api, liveview, naming
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


class LiveImage(QWidget):
    """The live picture, fitted to the window, with the sharpness region drawn on it, warnings, and (when asked) a loupe."""

    clicked = pyqtSignal(float, float)    # where, as fractions of the picture
    hovered = pyqtSignal(float, float)    # the same, as the mouse moves; (-1, -1) once it leaves

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 380)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._image: QImage | None = None
        self._message = "Connect a camera to see its live picture."
        self._region: tuple | None = None
        self._info = ""
        self._warning = ""
        self._loupe: QImage | None = None

    def set_message(self, text: str) -> None:
        self._image, self._message = None, text
        self.update()

    def set_frame(self, rgb, region: tuple | None, info: str, warning: str) -> None:
        h, w = rgb.shape[:2]
        self._image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self._region, self._info, self._warning = region, info, warning
        self.update()

    def set_loupe(self, rgb) -> None:
        if rgb is None:
            self._loupe = None
        else:
            h, w = rgb.shape[:2]
            self._loupe = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self.update()

    def _target(self) -> QRectF:
        if self._image is None:
            return QRectF(self.rect())
        scale = min(self.width() / self._image.width(), self.height() / self._image.height())
        w, h = self._image.width() * scale, self._image.height() * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _fractions(self, pos: QPointF):
        t = self._target()
        if self._image is None or not t.contains(pos):
            return None
        return (pos.x() - t.left()) / t.width(), (pos.y() - t.top()) / t.height()

    def mouseMoveEvent(self, event) -> None:
        f = self._fractions(event.position())
        self.hovered.emit(*(f if f else (-1.0, -1.0)))

    def leaveEvent(self, _event) -> None:
        self.hovered.emit(-1.0, -1.0)

    def mousePressEvent(self, event) -> None:
        f = self._fractions(event.position())
        if f and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(*f)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101010"))
        if self._image is None:
            p.setPen(QColor(THEME.text_hint))
            p.setFont(QFont(THEME.font_family, 11))
            p.drawText(QRectF(self.rect()).adjusted(30, 0, -30, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._message)
            return
        t = self._target()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(t, self._image)
        if self._region is not None:
            x0, y0, x1, y1 = self._region
            box = QRectF(t.left() + x0 * t.width(), t.top() + y0 * t.height(), (x1 - x0) * t.width(), (y1 - y0) * t.height())
            p.setPen(QPen(QColor(90, 200, 255, 220), 1.5, Qt.PenStyle.DashLine))
            p.drawRect(box)
        p.setFont(QFont(THEME.font_family, 9))
        p.setPen(QColor(235, 235, 235))
        p.drawText(QRectF(t.left() + 8, t.top() + 6, t.width() - 16, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._info)
        if self._warning:
            p.setPen(QColor(THEME.status_critical))
            p.drawText(QRectF(t.left() + 8, t.top() + 6, t.width() - 16, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._warning)
        if self._loupe is not None:
            size = min(260, int(t.width() * 0.4), int(t.height() * 0.6))
            box = QRectF(t.right() - size - 8, t.bottom() - size - 8, size, size)
            p.drawImage(box, self._loupe)
            p.setPen(QPen(QColor(235, 235, 235), 1.5))
            p.drawRect(box)


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

    captured = pyqtSignal(list)         # the paths a shot saved
    open_requested = pyqtSignal(str)    # a picture to open in the editor

    def __init__(self, parent=None, factory=make_backend, start_folder: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Canon Tether and Live View")
        self.resize(1180, 760)
        self._factory = factory
        self.session: TetherSession | None = None
        self._live: LiveWorker | None = None
        self._job: JobWorker | None = None
        self._focus_job: JobWorker | None = None
        self._frame = None
        self._seen = deque(maxlen=30)
        self._state = "off"
        self._hover = (-1.0, -1.0)
        self._peek_from: bool | None = None   # the positive check's state before N was held
        self._live_buttons: list[QPushButton] = []   # the buttons that only work while the camera is live
        self._building = True
        self._build(start_folder)
        self._building = False
        self._set_state("off")

    # ------------------------------------------------------------ building the window
    def _build(self, start_folder: str) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.image = LiveImage()
        self.image.clicked.connect(self._image_clicked)
        self.image.hovered.connect(self._image_hovered)
        left.addWidget(self.image, 1)
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
        col.addWidget(self._capture_box(start_folder))
        col.addWidget(self._focus_box())
        col.addWidget(self._view_box())
        col.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(side)
        scroll.setFixedWidth(384)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        root.addWidget(scroll)
        for key, action in (("Space", self.capture), ("I", lambda: self.positive_check.toggle()), ("P", lambda: self.peaking_check.toggle()), ("L", lambda: self.loupe_check.toggle()),
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

    def _view_box(self) -> QGroupBox:
        box = QGroupBox("View")
        lay = QVBoxLayout(box)
        self.positive_check = QCheckBox("Show as a positive (I; hold N to peek at the negative)")
        self.positive_check.setChecked(True)
        self.positive_check.setToolTip("EFAS's own Modern conversion turns the negative into a picture as you focus, so you judge focus on what you will see")
        self.positive_check.toggled.connect(self._view_changed)
        lay.addWidget(self.positive_check)
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
        self.loupe_check = QCheckBox("Loupe (L): enlarge what the mouse is over")   # drawn bottom right, with the picture's own pixels
        self.loupe_check.setToolTip("Four times the camera's own pixels round the mouse, not the smaller picture shown")
        self.loupe_check.toggled.connect(self._loupe_toggled)
        lay.addWidget(self.loupe_check)
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
        self.capture_button.setEnabled(live)
        if state == "off":
            self.image.set_message("Connect a camera to see its live picture.")
            self.camera_info.setText("")
            self.camera_note.setText("")
            self.focus_note.setText("")

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
        for job in (self._job, self._focus_job):
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
        self.image.set_frame(frame.image, region, f"{w} x {h}   {fps:.0f} fps", ("Blown out: " + "  ".join(bad)) if bad else "")
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
            self.session.set_view(positive=self.positive_check.isChecked(), peaking=self.peaking_check.isChecked(), peaking_sensitivity=self.peaking_slider.value() / 100.0)

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
            colour = liveview.sample_colour(self._frame.rgb, x, y)
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
