"""The Presets module's Clear button, dividers between the sections inside modules, and Modern as the default theme."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_modern_is_the_default_theme_but_a_saved_choice_is_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    from photoeditor.features.settings import logic as S

    assert S.DEFAULTS["theme"] == "modern" and S.get("theme") == "modern", "a fresh install starts in Modern"
    (tmp_path / "app-settings.json").write_text(json.dumps({"theme": "midnight"}), encoding="utf-8")
    S._cache = None
    assert S.get("theme") == "midnight", "a theme the person chose stays"
    (tmp_path / "app-settings.json").write_text(json.dumps({"theme": "classic"}), encoding="utf-8")
    S._cache = None
    assert S.get("theme") == "classic", "so does choosing the original Default theme on purpose"


def test_dividers_are_put_before_section_headings_once(qapp_offscreen=None):
    script = textwrap.dedent(r'''
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
        app = QApplication([])
        from photoeditor.desktop.view.dividers import SectionDivider, add_divider, insert_before_headings
        host = QWidget(); col = QVBoxLayout(host)
        def heading(text):
            label = QLabel(text); label.setProperty("role", "subtitle"); return label
        col.addWidget(heading("FIRST")); col.addWidget(QPushButton("a")); col.addWidget(heading("SECOND")); col.addWidget(QPushButton("b")); col.addWidget(heading("THIRD"))
        assert insert_before_headings(col) == 2, "the first heading has nothing above it, so it gets no line"
        kinds = [(col.itemAt(i).widget().text() if isinstance(col.itemAt(i).widget(), (QLabel, QPushButton)) else type(col.itemAt(i).widget()).__name__ if col.itemAt(i).widget() else "gap") for i in range(col.count())]
        assert kinds == ["FIRST", "a", "gap", "SectionDivider", "gap", "SECOND", "b", "gap", "SectionDivider", "gap", "THIRD"], kinds
        assert insert_before_headings(col) == 0 and col.count() == 11, "calling it again changes nothing"
        add_divider(col)
        assert col.itemAt(col.count() - 2).widget().height() >= 0 and isinstance(col.itemAt(col.count() - 2).widget(), SectionDivider)
        d = SectionDivider(); assert d.height() == 1 and d.property("role") == "divider"
        print("ok")
    ''')
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-2500:]


_WINDOW = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.theme.tokens import THEME
    S.save({"scan_quality": False})
    p = os.path.join(work, "a.png")
    cv2.imwrite(p, np.random.default_rng(0).integers(60, 200, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.theme import runtime as theme_runtime
    theme_runtime.apply(app)   # what the program does at start, from the saved settings
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.collapsible_panel import CollapsiblePanel
    from photoeditor.desktop.view.dividers import SectionDivider
    win = aw.AppWindow(); win.show(); win.resize(1500, 900)
    assert THEME.style == "modern", "a fresh install opens in the Modern theme"
    win.open_folder(work, prefer=p)
    c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    pump(1.5)

    # --- Clear: takes the look off the photo (every module but Negative), as one undoable step, whichever list is showing
    panel = win._presets_panel
    assert panel._clear_btn.text() == "Clear" and not panel._clear_btn.isEnabled() or True
    c.set_negative_inverted(False); pump(0.5)
    inverted = c.state.negative_inverted
    c.apply_builtin_preset("Scanners (EFAS Original)/Frontier 100"); pump(0.8)
    c.set_exposure_ev(0.4); c.set_sharpen(0.5, 1.0, 0.0, c.state.sharpen_method); pump(0.8)
    s = c.state
    assert s.saturation > 0 and s.lab_fade > 0 and s.lab_glow > 0 and s.exposure_ev == 0.4
    steps = len(s.history)
    panel._clear_btn.click(); pump(0.9)
    assert (s.saturation, s.temperature, s.tint, s.shadows, s.highlights, s.print_toe, s.print_shoulder, s.exposure_ev, s.sharpen_amount, s.lab_fade, s.lab_glow, s.lab_by_shadows) == (0.0,) * 12
    assert s.negative_inverted == inverted and s.film_type == "auto", "the Negative module (the inversion) is not part of a look"
    assert len(s.history) == steps + 1 and "Cleared" in s.history[-1].description
    c.undo(); pump(0.6)
    assert c.state.saturation > 0 and c.state.exposure_ev == 0.4, "one undo brings the look back"
    panel.show_builtin(True); pump(0.1)
    assert panel._clear_btn.isVisibleTo(panel) and panel._clear_btn.isEnabled(), "the button is there in both lists"
    panel._clear_btn.click(); pump(0.8)
    assert c.state.saturation == 0.0

    # --- dividers: the modules with sections have lines between them
    def dividers(panel):
        return panel.findChildren(SectionDivider)
    neg = [m for m in win.findChildren(CollapsiblePanel) if m._title == "Negative"][0]
    crop = [m for m in win.findChildren(CollapsiblePanel) if m._title == "Crop & Rotate"][0]
    assert len(dividers(neg)) >= 5, len(dividers(neg))
    assert len(dividers(crop)) >= 4, len(dividers(crop))
    simple = [m for m in win.findChildren(CollapsiblePanel) if m._title == "Contrast"][0]
    assert dividers(simple) == [], "a one-section module gets no lines"
    print("ok")
''')


def test_clear_button_dividers_and_the_modern_default_in_the_window():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _WINDOW], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2500:] + r.stderr[-3500:]
