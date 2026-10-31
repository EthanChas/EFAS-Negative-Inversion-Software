"""Sections that fold inside a module (desktop/view/fold.py), after NegPy's modules."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from photoeditor.desktop.view import fold
from photoeditor.desktop.view.dividers import add_divider

_APP = None
fold.FoldSection.ANIMATE = False      # these tests look at the sections straight after a click: the slide has its own test


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _title(text):
    label = QLabel(text)
    label.setProperty("role", "subtitle")
    return label


def _module():
    host = QWidget()
    body = QVBoxLayout(host)
    first = QPushButton("before any title")
    body.addWidget(first)
    body.addWidget(_title("FILM BASE"))
    a = QPushButton("Sample")
    body.addWidget(a)
    add_divider(body)
    body.addWidget(_title("METERING"))
    row = QHBoxLayout()
    b, c = QPushButton("Draw"), QPushButton("Clear")
    row.addWidget(b)
    row.addWidget(c)
    body.addLayout(row)
    extra = QHBoxLayout()
    extra.addWidget(_title("COLOR TRIM"))
    light = QPushButton("Scanning light...")
    extra.addWidget(light)
    body.addLayout(extra)
    d = QPushButton("Red")
    body.addWidget(d)
    return host, body, dict(first=first, a=a, b=b, c=c, light=light, d=d)


def test_titled_groups_become_sections_that_fold(monkeypatch, tmp_path):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    _app()
    host, body, w = _module()
    sections = fold.fold_sections(body, "demo", {}, ("COLOR TRIM",))
    assert [s.key for s in sections] == ["demo/Film Base", "demo/Metering", "demo/Color Trim"]
    host.show()
    assert w["first"].parentWidget() is host, "controls before the first title stay where they were"
    assert w["a"].parentWidget() is sections[0]._body and w["b"].parentWidget() is sections[1]._body and w["d"].parentWidget() is sections[2]._body
    assert w["light"].parentWidget() is sections[2]._head, "what stood beside a title stays beside it, in the title bar"
    assert w["light"].height() <= sections[2]._head.height() - 4 and w["light"].geometry().bottom() < sections[2]._head.height(), "and a button there fits inside the bar rather than standing taller than it"
    assert not sections[0].is_closed() and sections[2].is_closed(), "the one asked to start closed is closed"
    assert w["a"].isVisible() and not w["d"].isVisible()
    seen = []
    for s in sections:
        s.folded.connect(lambda key, closed: seen.append((key, closed)))
    sections[0]._chevron.click()
    assert sections[0].is_closed() and not w["a"].isVisible() and seen == [("demo/Film Base", True)]
    sections[0]._title.setProperty("x", 1)
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(3, 3), QPointF(3, 3), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(sections[0]._title, release)
    assert not sections[0].is_closed() and w["a"].isVisible(), "a click on the title folds and opens too"


def test_a_section_with_nothing_showing_is_not_shown(monkeypatch, tmp_path):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    app = _app()
    host, body, w = _module()
    sections = fold.fold_sections(body, "demo", {})
    host.show()
    w["b"].hide(); w["c"].hide()
    app.processEvents(); app.processEvents()
    assert sections[1].isHidden() and not sections[0].isHidden(), "Metering has nothing in it showing"
    w["b"].show()
    app.processEvents(); app.processEvents()
    assert not sections[1].isHidden()


def test_which_sections_are_closed_is_kept(monkeypatch, tmp_path):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    _app()
    assert fold.folded_state() == {}
    fold.remember("demo/Metering", True)
    fold.remember("demo/Color Trim", False)
    assert fold.folded_state() == {"demo/Metering": True, "demo/Color Trim": False}
    host, body, w = _module()
    sections = fold.fold_sections(body, "demo", fold.folded_state(), ("COLOR TRIM",))
    assert [s.is_closed() for s in sections] == [False, True, False], "what was chosen beats the default"


def test_a_section_slides_shut_and_open(monkeypatch, tmp_path):
    import time
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    app = _app()
    monkeypatch.setattr(fold.FoldSection, "ANIMATE", True)
    host, body, w = _module()
    sections = fold.fold_sections(body, "demo", {})
    host.show()
    app.processEvents(); app.processEvents()
    s = sections[0]
    full = s._body.height()
    assert full > 10 and s._clip.isVisible()
    s.toggle()
    assert s.is_closed(), "the state changes at once, the picture follows"
    assert s._slide.running() and s._clip.isVisible(), "it slides rather than snaps"
    heights, inner = [], []
    deadline = time.time() + 2
    while s._clip.isVisible() and time.time() < deadline:
        app.processEvents(); time.sleep(0.004)
        heights.append(s._clip.height()); inner.append(s._body.height())
    assert not s._clip.isVisible() and s._clip.maximumHeight() > 10_000
    assert heights == sorted(heights, reverse=True) and len(set(heights)) > 2, "the clip closes steadily"
    assert set(inner) <= {full}, ("the controls inside do not squash while it slides", sorted(set(inner)))
    s.toggle()
    heights, inner = [], []
    deadline = time.time() + 2
    while s._clip.maximumHeight() < 10_000 and time.time() < deadline:
        app.processEvents(); time.sleep(0.004)
        heights.append(s._clip.height()); inner.append(s._body.height())
    assert s._clip.isVisible() and s._body.height() == full, "it ends on the height it began with: no jump at the end"
    assert heights == sorted(heights) and len(set(heights)) > 2 and set(inner) <= {full}
