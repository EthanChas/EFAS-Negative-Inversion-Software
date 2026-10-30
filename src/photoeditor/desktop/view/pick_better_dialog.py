"""Pick Better: the window that tunes the open photo's print by choosing the better of two. See features/pickbetter/logic.py for the rounds; this is the part you see: the two prints
side by side, what is being tried, and the buttons (and keys: left, right, down, backspace, escape)."""
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QCursor, QKeyEvent, QPixmap
from PyQt6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...features.pickbetter import logic as pb
from ...theme.tokens import THEME
from ..slideshow_worker import to_qimage
from .slider_row import SliderRow

_PREVIEW_WIDTH = 520


class PickBetterDialog(QDialog):
    """Two prints of the open photo, one control apart. Pick the better; the next round tries another control. Everything picked is an ordinary edit (one step in the History per pick)."""

    def __init__(self, controller, parent: QWidget | None = None):
        super().__init__(parent)
        self.c = controller
        self.setWindowTitle("Pick Better")
        self.setModal(False)
        self._progress = pb.start()
        self._history: list[tuple[dict, pb.Progress, tuple]] = []      # what to go back to: the config, the progress, and the photo's own values before the pick
        self._pair: tuple[dict, dict] | None = None
        self._config: dict | None = None
        col = QVBoxLayout(self)
        col.setSpacing(THEME.space_md)
        self._head = QLabel("")
        self._head.setStyleSheet(f"font-weight: bold; font-size: {THEME.font_size_title + 2}pt;")
        col.addWidget(self._head)
        self._last = QLabel("")
        self._last.setProperty("role", "hint")
        col.addWidget(self._last)
        images = QHBoxLayout()
        images.setSpacing(THEME.space_md)
        self._labels: list[QLabel] = []
        self._captions: list[QLabel] = []
        for side in range(2):
            box = QVBoxLayout()
            caption = QLabel("")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setProperty("role", "hint")
            image = QLabel()
            image.setMinimumSize(QSize(_PREVIEW_WIDTH, 200))
            image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image.setStyleSheet(f"background: {THEME.bg_input}; border: 1px solid {THEME.border_color};")
            image.setCursor(Qt.CursorShape.PointingHandCursor)
            image.mousePressEvent = lambda _e, s=side: self.choose(s)
            box.addWidget(caption)
            box.addWidget(image, 1)
            images.addLayout(box, 1)
            self._labels.append(image)
            self._captions.append(caption)
        col.addLayout(images, 1)
        self._difference = SliderRow("Difference", min_value=0.25, max_value=2.0, reset_value=1.0, decimals=2, step=0.05)
        self._difference.setToolTip("How far apart the two prints are. The picture itself does not change: only the step of this round.")
        self._difference.value_changed.connect(lambda _v: self._show_round())
        col.addWidget(self._difference)
        buttons = QHBoxLayout()
        self._left_btn = QPushButton("Left is better  (Left)")
        self._neither_btn = QPushButton("Neither  (Down)")
        self._right_btn = QPushButton("Right is better  (Right)")
        self._undo_btn = QPushButton("Undo the last pick  (Backspace)")
        self._finish_btn = QPushButton("Finish")
        self._left_btn.clicked.connect(lambda: self.choose(0))
        self._right_btn.clicked.connect(lambda: self.choose(1))
        self._neither_btn.clicked.connect(self.neither)
        self._undo_btn.clicked.connect(self.undo)
        self._finish_btn.clicked.connect(self.close)
        for b in (self._left_btn, self._neither_btn, self._right_btn, self._undo_btn, self._finish_btn):
            buttons.addWidget(b)
        col.addLayout(buttons)
        hint = QLabel("Each round differs in one control: the left is a step stronger and the right a step weaker. Pick the print you like better and the next round tries another control; "
                      "the steps get smaller as you go. Pick Better changes the NegPy Conversion's controls and the Color tab's temperature and tint.")
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        col.addWidget(hint)
        self.resize(_PREVIEW_WIDTH * 2 + 80, 520)

    # ------------------------------------------------------------ the rounds
    def begin(self) -> bool:
        """Start from the open photo as it is. False (with the reason shown) when it cannot be tuned this way."""
        reason = self.c.pick_better_unavailable()
        if reason:
            self._head.setText("Pick Better")
            self._last.setText(reason)
            for b in (self._left_btn, self._right_btn, self._neither_btn, self._undo_btn):
                b.setEnabled(False)
            for label in self._labels:
                label.clear()
            return False
        for b in (self._left_btn, self._right_btn, self._neither_btn):
            b.setEnabled(True)
        self._progress = pb.start()
        self._history.clear()
        self._last.setText("")
        self._config = self.c.pick_better_config()
        self._show_round()
        return True

    def _scale(self) -> float:
        return float(self._difference.value())

    def _show_round(self) -> None:
        if self._config is None:
            return
        _i, p = pb.current(self._progress)
        self._head.setText(f"Round {self._progress.round_number}: {p.name}" + ("" if self._progress.phase == pb.FIXED else "  (refining)"))
        self._pair = pb.pair(self._config, self._progress, self._scale())
        self._captions[0].setText(f"{p.name} {self._pair[0][p.key]:+.2f}  (stronger)" if p.lo < 0 else f"{p.name} {self._pair[0][p.key]:.2f}  (stronger)")
        self._captions[1].setText(f"{p.name} {self._pair[1][p.key]:+.2f}  (weaker)" if p.lo < 0 else f"{p.name} {self._pair[1][p.key]:.2f}  (weaker)")
        self._undo_btn.setEnabled(bool(self._history))
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            for side in range(2):
                pixels = self.c.pick_better_render(self._pair[side], _PREVIEW_WIDTH, side)
                if pixels is None:
                    self._labels[side].clear()
                    continue
                pix = QPixmap.fromImage(to_qimage(pixels))
                self._labels[side].setPixmap(pix.scaled(self._labels[side].size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        finally:
            QApplication.restoreOverrideCursor()

    def choose(self, side: int) -> None:
        if self._config is None or self._pair is None:
            return
        old = self._config
        new, progress = pb.pick(self._config, self._progress, side, self._scale())
        self._history.append((old, self._progress, self.c.pick_better_snapshot()))
        self.c.pick_better_commit(new, f"Pick Better: {pb.summary(old, new, self._progress)}")
        self._last.setText(f"Picked: {pb.summary(old, new, self._progress)}")
        self._config, self._progress = new, progress
        self._show_round()

    def neither(self) -> None:
        if self._config is None:
            return
        self._config, self._progress = pb.reject(self._config, self._progress)
        self._last.setText("Neither: the picture stays as it is")
        self._show_round()

    def undo(self) -> None:
        if not self._history:
            return
        config, progress, snapshot = self._history.pop()
        self.c.pick_better_restore(snapshot)
        self._config, self._progress = config, progress
        self._last.setText("Undone")
        self._show_round()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Left:
            self.choose(0)
        elif key == Qt.Key.Key_Right:
            self.choose(1)
        elif key == Qt.Key.Key_Down:
            self.neither()
        elif key in (Qt.Key.Key_Backspace, Qt.Key.Key_Up):
            self.undo()
        elif key == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
