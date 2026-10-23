"""The wheel changes a slider, a number box or a drop-down only once it has been clicked; before that it scrolls the panel behind it."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QScrollArea, QSlider, QVBoxLayout, QWidget
    app = QApplication([])
    from photoeditor.desktop.view import wheel_guard
    from photoeditor.desktop.view.slider_row import ResettableSlider

    def pump(s=0.05):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.005)

    area = QScrollArea(); area.setWidgetResizable(True); area.resize(300, 300)
    content = QWidget(); col = QVBoxLayout(content)
    slider = ResettableSlider(0); slider.setRange(0, 100); slider.setValue(50)
    spin = QDoubleSpinBox(); spin.setRange(0, 10); spin.setValue(5)
    combo = QComboBox(); combo.addItems(["a", "b", "c"]); combo.setCurrentIndex(1)
    for w in (slider, spin, combo):
        col.addWidget(w)
    filler = QWidget(); filler.setMinimumHeight(1500); col.addWidget(filler)
    area.setWidget(content); area.show(); area.activateWindow(); pump(0.2)
    assert wheel_guard.install() is wheel_guard.install(), "installed once"

    def wheel(widget, delta=120):
        pos = QPointF(widget.width() / 2, widget.height() / 2)
        ev = QWheelEvent(pos, widget.mapToGlobal(pos), QPoint(0, 0), QPoint(0, delta), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(widget, ev)
        pump()

    for w in (slider, spin, combo):
        w.clearFocus()   # (a window gives its first control the focus when it opens)
    pump()
    bar = area.verticalScrollBar()
    assert bar.value() == 0
    # not clicked yet: the controls keep their values, and the panel scrolls
    for w in (slider, spin, combo):
        assert not w.hasFocus()
    wheel(slider, -120); wheel(spin.lineEdit(), -120); wheel(spin, -120); wheel(combo, -120)
    assert slider.value() == 50 and spin.value() == 5 and combo.currentIndex() == 1, (slider.value(), spin.value(), combo.currentIndex())
    assert bar.value() > 0, "the wheel went on to the panel"
    scrolled = bar.value()
    # clicked (given focus): the wheel works on it
    slider.setFocus(); pump()
    assert slider.hasFocus()
    before = slider.value(); wheel(slider, 120)
    assert slider.value() != before and bar.value() == scrolled, "a clicked slider takes the wheel and the panel stays put"
    # the pointer leaves it: it lets go, and is guarded again
    QApplication.sendEvent(slider, QEvent(QEvent.Type.Leave)); pump()
    assert not slider.hasFocus()
    after = slider.value(); wheel(slider, 120)
    assert slider.value() == after, "guarded again"
    # a number box keeps its focus when the pointer leaves, and takes the wheel
    spin.setFocus(); pump(); QApplication.sendEvent(spin, QEvent(QEvent.Type.Leave)); pump()
    assert spin.hasFocus()
    v = spin.value(); wheel(spin, 120); assert spin.value() != v
    combo.setFocus(); pump(); i = combo.currentIndex(); wheel(combo, 120); assert combo.currentIndex() != i
    # a scroll bar is always moved by the wheel
    spin.clearFocus(); pump(); at = bar.value(); wheel(bar, -120); assert bar.value() != at

    # the main window puts the guard on
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow()
    assert wheel_guard._guard is not None and wheel_guard._guard.parent() is app
    win.close()
    print("OK")
''')


def test_the_wheel_waits_for_a_click():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_GPU": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-3000:]
