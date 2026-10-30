"""Opening and closing a block of controls smoothly. Shrinking a widget's maximum height alone squeezes the controls inside it while the layout fights back, and the height the slide
ends on was only a guess, so the block shivered on the way and jumped at the end. A Slide instead holds the content at the full height it needs for the width it has (so nothing inside
moves or squashes) and moves only the clip around it, from the height it has to the height it will have."""

from PyQt6.QtCore import QEasingCurve, QObject, QVariantAnimation
from PyQt6.QtWidgets import QWidget

NO_LIMIT = 16777215      # QWIDGETSIZE_MAX


class Slide(QObject):
    """`clip` is the widget that holds `content` (a layout with the content as its only item, no margins) and sits in the host's layout; `host` is what has to be showing for a slide to be
    seen. With `hide_when_closed` a closed clip is hidden; otherwise it stays shown at no height."""

    ANIMATE = True       # the tests that look straight after a click turn this off

    def __init__(self, host: QWidget, clip: QWidget, content: QWidget, duration: int = 160, easing=QEasingCurve.Type.OutCubic, hide_when_closed: bool = True, opened: bool = True):
        super().__init__(host)
        self._host = host
        self._clip = clip
        self._content = content
        self._hide = hide_when_closed
        self._open = opened
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(easing)
        self._anim.valueChanged.connect(lambda h: self._clip.setMaximumHeight(int(h)))
        self._anim.finished.connect(self._done)

    def running(self) -> bool:
        return self._anim.state() == QVariantAnimation.State.Running

    def full_height(self) -> int:
        """The height the content asks for at the width it will have."""
        width = max(self._clip.width() if self._clip.isVisible() else self._host.width(), 1)
        if self._content.hasHeightForWidth():
            height = self._content.heightForWidth(width)
            if height > 0:
                return height
        return max(self._content.sizeHint().height(), 1)

    def snap(self, opened: bool) -> None:
        """Open or close at once."""
        self._anim.stop()
        self._open = opened
        self._content.setMinimumHeight(0)
        if self._hide:
            self._clip.setMaximumHeight(NO_LIMIT)
            self._clip.setVisible(opened)
        else:
            self._clip.setMaximumHeight(NO_LIMIT if opened else 0)

    def go(self, opened: bool) -> None:
        """Open or close, sliding when it can be seen."""
        if not (self.ANIMATE and self._host.isVisible()):
            self.snap(opened)
            return
        self._anim.stop()
        self._open = opened
        shown = self._clip.isVisible() and not self._clip.isHidden()
        here = self._clip.height() if shown else 0
        full = self.full_height()
        self._content.setMinimumHeight(max(full, here))      # the content keeps its size; only the clip around it moves
        if opened:
            self._clip.setMaximumHeight(here)
            self._clip.setVisible(True)
            self._anim.setStartValue(float(here))
            self._anim.setEndValue(float(full))
        else:
            self._anim.setStartValue(float(here))
            self._anim.setEndValue(0.0)
        self._anim.start()

    def _done(self) -> None:
        self._content.setMinimumHeight(0)
        if self._hide:
            self._clip.setMaximumHeight(NO_LIMIT)
            self._clip.setVisible(self._open)
        else:
            self._clip.setMaximumHeight(NO_LIMIT if self._open else 0)
