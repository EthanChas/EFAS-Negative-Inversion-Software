"""The segmented choice and the ‹ › arrows on dropdowns (after NegPy's controls)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from photoeditor.desktop.view.segmented import SegmentedControl, add_steppers, add_steppers_in

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_a_segmented_control_answers_like_the_dropdown_it_replaces():
    _app()
    seg = SegmentedControl()
    seen = []
    seg.currentIndexChanged.connect(seen.append)
    for label in ("All", "Red", "Green"):
        seg.addItem(label, label.lower())
    assert seg.count() == 3 and seg.currentIndex() == 0 and seg.currentData() == "all" and seg.itemText(1) == "Red" and seg.findData("green") == 2 and seg.findData("x") == -1
    seg._buttons[1].click()
    assert seg.currentIndex() == 1 and seen == [1] and [b.isChecked() for b in seg._buttons] == [False, True, False]
    seg._buttons[1].click()
    assert seen == [1], "choosing the lit one again changes nothing"
    seg.blockSignals(True)
    seg.setCurrentIndex(2)
    seg.blockSignals(False)
    assert seg.currentIndex() == 2 and seen == [1] and seg.currentData() == "green", "blockSignals holds back the signal but not the change"


def _row():
    host = QWidget()
    outer = QVBoxLayout(host)
    inner = QHBoxLayout()
    outer.addLayout(inner)
    combo = QComboBox()
    for text in ("One", "Two", "Three", "Four"):
        combo.addItem(text, text.lower())
    inner.addWidget(QLabel("Pick"))
    inner.addWidget(combo, 1)
    return host, combo


def test_arrows_step_the_dropdown_and_wrap():
    _app()
    host, combo = _row()
    seen = []
    combo.currentIndexChanged.connect(seen.append)
    assert add_steppers(combo) and combo.property("stepper")
    assert not add_steppers(combo), "once"
    box = combo.parentWidget()
    buttons = box.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QToolButton"]).QToolButton)
    previous, following = buttons[0], buttons[1]
    following.click()
    assert combo.currentIndex() == 1
    previous.click(); previous.click()
    assert combo.currentIndex() == 3, "past the first comes the last"
    following.click()
    assert combo.currentIndex() == 0, "past the last comes the first"
    assert seen == [1, 0, 3, 0]


def test_not_every_dropdown_gets_arrows():
    _app()
    host = QWidget()
    layout = QVBoxLayout(host)
    two = QComboBox()
    two.addItems(["a", "b"])
    editable = QComboBox()
    editable.setEditable(True)
    editable.addItems(["a", "b", "c"])
    many = QComboBox()
    many.addItems(["a", "b", "c"])
    for w in (two, editable, many):
        layout.addWidget(w)
    assert add_steppers_in(host) == 1 and many.property("stepper") and not two.property("stepper") and not editable.property("stepper")


def test_the_arrows_follow_the_dropdown_when_a_panel_hides_it():
    _app()
    host, combo = _row()
    host.show()
    add_steppers(combo)
    box = combo.parentWidget()
    assert box.isVisible()
    combo.setVisible(False)
    assert not box.isVisible()
    combo.setVisible(True)
    assert box.isVisible() and combo.isVisible()
