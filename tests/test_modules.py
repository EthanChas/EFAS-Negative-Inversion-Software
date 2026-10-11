"""Module (collapsible panel) settings: colour-coded headers with stable assigned colours, and opening on hover and closing when the mouse leaves."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.settings import logic as S  # noqa: E402


def test_the_two_settings_are_off_by_default_and_checked_for_type(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    d = S.load()
    assert d["hover_modules"] is False and d["module_colours"] is False and d["module_colour_choices"] == {}
    S.save({"hover_modules": True, "module_colours": True, "module_colour_choices": {"Export": "Teal", "Bad": 5}})
    d = S.load()
    assert d["hover_modules"] and d["module_colours"] and d["module_colour_choices"] == {"Export": "Teal"}
    (tmp_path / "settings.json").write_text('{"hover_modules": "yes", "module_colours": 1, "module_colour_choices": [1]}')
    S._cache = None
    d = S.load()
    assert d["hover_modules"] is False and d["module_colours"] is False and d["module_colour_choices"] == {}


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QEnterEvent
    from PyQt6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget
    from photoeditor.features.settings import logic as S
    app = QApplication([])
    from photoeditor.desktop.view import module_style as M
    from photoeditor.desktop.view import collapsible_panel as CP
    from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
    CP.HOVER_OPEN_MS = 20; CP.HOVER_CLOSE_MS = 20

    def pump(ms=120):
        end = time.time() + ms / 1000
        while time.time() < end:
            app.processEvents(); time.sleep(0.005)
    def enter(p): app.sendEvent(p, QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    def leave(p): app.sendEvent(p, QEvent(QEvent.Type.Leave))

    # --- assigned colours: stable, one per known module, and from the settings
    titles = list(M.KNOWN_MODULES)
    assert len(set(titles)) == len(titles)
    hues = [M.automatic_slot(t) for t in titles]
    assert hues == [M.automatic_slot(t) for t in titles], "the same every time"
    assert len({round(h, 4) for h, _t in hues}) == len(titles), "every known module has its own hue"
    assert {t for _h, t in hues} == {0, 1, 2}
    assert M.automatic_slot("A module from the future") == M.automatic_slot("A module from the future")
    assert M.automatic_slot("A module from the future") != M.automatic_slot("Another new one")
    assert M.STYLE.gradient("Export") is None, "off until the setting is on"
    M.STYLE.apply({"module_colours": True})
    a, b = M.STYLE.gradient("Export")
    assert a.valueF() > b.valueF() and a != M.STYLE.gradient("Exposure")[0]
    assert M.STYLE.gradient("Export")[0] == M.gradient_from_hue(*M.automatic_slot("Export"))[0]
    M.STYLE.apply({"module_colours": True, "module_colour_choices": {"Export": "Teal", "Exposure": "none"}})
    assert M.STYLE.gradient("Export")[0] == M.gradient_from_hue(M.NAMED["Teal"], 0)[0] and M.STYLE.gradient("Exposure") is None

    # --- the header paints the gradient and the menu changes a module's colour for good
    M.STYLE.apply({"module_colours": False})
    panel = CollapsiblePanel("Export", start_expanded=False)
    panel.resize(300, 60); panel.show(); pump(30)
    plain = panel.grab().toImage().pixelColor(150, 20)
    M.STYLE.apply({"module_colours": True})
    pump(30)
    coloured = panel.grab().toImage().pixelColor(150, 20)
    left = panel.grab().toImage().pixelColor(20, 20)
    assert plain != coloured and left != coloured, (plain.name(), coloured.name(), left.name())
    menu = panel._header.build_colour_menu()
    labels = [x.text() for x in menu.actions()]
    assert labels[0] == "Automatic" and "Teal" in labels and labels[-1] == "None (plain)" and menu.actions()[0].isChecked()
    [x for x in menu.actions() if x.text() == "Rose"][0].trigger()
    assert M.STYLE.choice("Export") == "Rose" and S.load()["module_colour_choices"] == {"Export": "Rose"}
    [x for x in panel._header.build_colour_menu().actions() if x.text() == "Automatic"][0].trigger()
    assert M.STYLE.choice("Export") == "M".replace("M", M.AUTOMATIC) and S.load()["module_colour_choices"] == {}
    M.STYLE.apply({})

    # --- hover: off means off
    p = CollapsiblePanel("Color", start_expanded=False)
    p.show(); enter(p); pump(); assert not p._expanded
    # on: entering opens it, leaving closes it
    M.STYLE.apply({"hover_modules": True})
    enter(p); pump(); assert p._expanded and not p.is_pinned()
    leave(p); pump(); assert not p._expanded
    # a quick pass over a module does not open it
    CP.HOVER_OPEN_MS = 150; p._open_timer.setInterval(150)
    enter(p); pump(30); leave(p); pump(250); assert not p._expanded
    CP.HOVER_OPEN_MS = 20; p._open_timer.setInterval(20)
    # coming back before it closes keeps it open
    enter(p); pump(); assert p._expanded
    p._close_timer.setInterval(150)
    leave(p); pump(40); enter(p); pump(250); assert p._expanded
    p._close_timer.setInterval(20)
    leave(p); pump(); assert not p._expanded

    # a click pins it open; leaving does not close it; a second click closes it
    enter(p); pump(); assert p._expanded
    p.toggle(); assert p.is_pinned() and p._expanded
    leave(p); pump(); assert p._expanded
    p.toggle(); assert not p._expanded and not p.is_pinned()
    # a click on a closed module opens and pins it
    p.toggle(); assert p._expanded and p.is_pinned()
    p.toggle(); assert not p._expanded

    # busy: a held mouse button, a drop-down, or typing in it stops the close
    q = CollapsiblePanel("Sharpening", start_expanded=False)
    field = QLineEdit(); q.body().addWidget(field); q.show()
    enter(q); pump(); assert q._expanded
    busy = {"on": True}
    q._busy = lambda: busy["on"]
    leave(q); pump(150); assert q._expanded, "still open while busy"
    busy["on"] = False; pump(150); assert not q._expanded, "closes once it is free"
    real = CollapsiblePanel._busy
    q2 = CollapsiblePanel("Contrast", start_expanded=False); f2 = QLineEdit(); q2.body().addWidget(f2); q2.show()
    enter(q2); pump(); f2.setFocus(); pump(30)
    if f2.hasFocus():
        assert real(q2) is True, "typing in a module keeps it open"
    # leaving then re-entering the same spot is not a leave
    leave(q2); enter(q2); pump(150); assert q2._expanded

    # turning hover on makes what is open now stay open; turning it off stops all of it
    r = CollapsiblePanel("Presets", start_expanded=True)
    M.STYLE.apply({"hover_modules": False}); M.STYLE.apply({"hover_modules": True})
    assert r.is_pinned(); leave(r); pump(); assert r._expanded
    M.STYLE.apply({"hover_modules": False})
    s_ = CollapsiblePanel("Tags", start_expanded=False); s_.show(); enter(s_); pump(); assert not s_._expanded
    # panels that are not collapsible never react
    M.STYLE.apply({"hover_modules": True})
    fixed = CollapsiblePanel("Fixed", collapsible=False); fixed.show(); enter(fixed); pump(); leave(fixed); pump()
    print("MODULES STYLE OK")

    # --- the settings dialog and the whole window
    M.STYLE.apply({})
    from photoeditor.desktop.view.settings_dialog import SettingsDialog
    d = SettingsDialog(None, None)
    assert not d._hover_modules.isChecked() and not d._module_colours.isChecked()
    d._hover_modules.setChecked(True); d._module_colours.setChecked(True)
    v = d.values(); assert v["hover_modules"] is True and v["module_colours"] is True
    S.save(v)
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow()
    assert M.STYLE.hover and M.STYLE.colours, "the window applies the saved settings when it starts"
    panels = win.findChildren(CollapsiblePanel)
    assert len(panels) > 20 and all(pp._header is not None for pp in panels)
    seen = {}
    for pp in panels:
        seen.setdefault(pp._title, pp)
    assigned = {t: M.STYLE.gradient(t)[0].name() for t in seen}
    assert len(set(assigned.values())) >= len(seen) - 3, "the editor's modules get their own colours"
    shown = next(pp for pp in panels if pp._title == "Export")
    shown.resize(300, 60); shown.show(); pump(30)
    assert shown.grab().toImage().pixelColor(8, shown._header.geometry().center().y()).name() != "#181818"
    win.close()
    print("MODULES WINDOW OK")
    sys.stdout.flush()
    os._exit(0)  # leaving the loose widgets to the interpreter's shutdown crashes some Qt versions; the app itself deletes its window first
''')


def test_module_colours_and_hover_behaviour():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "MODULES STYLE OK" in done.stdout and "MODULES WINDOW OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
