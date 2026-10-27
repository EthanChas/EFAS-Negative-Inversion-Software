"""The histogram stays in view while the sidebar scrolls; Log and Split; a black-and-white negative greys the Color graph out; Alt+E; Find reaches presets."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from photoeditor.features.keybinds import logic as K

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_shift_e_is_the_default_for_error_marks_and_clashes_with_nothing():
    action = K.BY_ID["error_marks"]
    assert action.default == "Alt+E" and action.kind == "menu" and action.category == "Viewing"
    assert K.conflicts(K.bindings(None)) == {}


_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtGui import QImage, QKeySequence
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.find import logic as F
    from photoeditor.features.lookpresets import store
    from photoeditor.features.negative.logic import ProcessMode
    S.save({"scan_quality": False})
    p = os.path.join(work, "a.png")
    cv2.imwrite(p, np.random.default_rng(0).integers(40, 200, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.resize(1500, 600); win.open_folder(work, prefer=p)
    c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
    pump(1.5)

    # --- the histogram is frozen: it is not in the scrolling part, and does not move when that is scrolled
    hist = win._histogram_panel
    scroll = win._sidebar_scroll
    assert not scroll.widget().isAncestorOf(win._wb_panel) and not scroll.widget().isAncestorOf(hist)
    assert scroll.widget().isAncestorOf(win._stats_panel) and scroll.widget().isAncestorOf(win._tool_rail), "the figures and tools scroll"
    win._tool_rail._buttons["negative"].click(); pump(0.9)
    for m in win._negative_panel.findChildren(type(win._wb_panel)):
        m.set_expanded(True)
    pump(0.6)
    bar = scroll.verticalScrollBar()
    assert bar.maximum() > 0, "there is something to scroll"
    top = hist.mapTo(win, QPoint(0, 0))
    bar.setValue(bar.maximum()); pump(0.3)
    assert hist.mapTo(win, QPoint(0, 0)) == top and hist.isVisible() and hist.height() > 100, "the graph did not move"
    bar.setValue(0)

    # --- Log and Split
    assert win._hist_log_btn.text() == "Log" and win._hist_split_btn.text() == "Split"
    assert not hist.log_scale() and not hist.channels_split()
    counts = {"r": [0] * 256, "g": [0] * 256, "b": [0] * 256}
    counts["r"][50] = 5000; counts["g"][128] = 5000; counts["b"][200] = 5000
    for i in range(256):
        for k in counts: counts[k][i] += 3 if k == "r" else 8      # thin tails everywhere
    hist.set_data(counts, [sum(v) // 3 for v in zip(*counts.values())])
    def grab():
        img = hist.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
        return np.frombuffer(img.constBits().asstring(img.sizeInBytes()), np.uint8).reshape(img.height(), img.bytesPerLine())[:, : img.width() * 3].reshape(img.height(), img.width(), 3).copy()
    win._color_btn.click(); pump(0.2)
    plain = grab()
    win._hist_log_btn.click(); pump(0.2)
    logged = grab()
    assert hist.log_scale() and S.get("histogram_log") is True and not np.array_equal(plain, logged), "log changes the picture"
    # in log the thin tails stand clearly above the baseline (in the plain graph they are almost flat)
    rect = hist._plot_rect()
    def tail_height(img):
        x = rect.left() + int(rect.width() * 0.8)         # bin ~204: only a thin tail of green and red there
        column = img[rect.top():rect.bottom() + 1, x]
        filled = np.where(np.abs(column.astype(int) - np.array([20, 20, 20])).max(axis=1) > 60)[0]
        return rect.height() - (filled.min() if len(filled) else rect.height())
    assert tail_height(logged) > tail_height(plain) + 5, (tail_height(plain), tail_height(logged))
    win._hist_log_btn.click(); pump(0.2)
    assert not hist.log_scale() and np.array_equal(grab(), plain) and S.get("histogram_log") is False

    win._hist_split_btn.click(); pump(0.2)
    split = grab()
    assert hist.channels_split() and S.get("histogram_split") is True and not np.array_equal(split, plain)
    bands = hist._bands(rect)
    assert len(bands) == 3 and all(b.height() > 20 for b in bands) and bands[0].bottom() < bands[1].top() < bands[1].bottom() < bands[2].top()
    def has(img, band, colour, tol=30):
        sub = img[band.top():band.bottom() + 1, band.left():band.right() + 1].astype(int)
        return bool((np.abs(sub - np.array(colour)).max(axis=2) <= tol).any())
    from photoeditor.theme.tokens import THEME
    rgb = lambda h: [int(h[i:i + 2], 16) for i in (1, 3, 5)]
    red, green, blue = rgb(THEME.channel_red), rgb(THEME.channel_green), rgb(THEME.channel_blue)
    assert has(split, bands[0], red) and not has(split, bands[0], green) and not has(split, bands[0], blue), "the top strip is red only"
    assert has(split, bands[1], green) and not has(split, bands[1], red) and has(split, bands[2], blue) and not has(split, bands[2], red)
    win._hist_split_btn.click(); pump(0.2)
    assert not hist.channels_split()

    # --- a black-and-white negative: the Color graph is greyed out and the graph shows brightness
    win._hist_split_btn.click(); pump(0.1)
    assert win._color_btn.isChecked() and win._color_btn.isEnabled() and win._hist_split_btn.isEnabled()
    c.set_film_type("bw"); pump(0.8)
    assert c.is_black_and_white() and not win._color_btn.isEnabled() and win._exposure_btn.isChecked() and hist._mode == "exposure"
    assert not win._hist_split_btn.isEnabled() and "black-and-white" in win._color_btn.toolTip()
    win._color_btn.click(); pump(0.1)
    assert hist._mode == "exposure", "a greyed-out button does nothing"
    c.set_film_type("c41"); pump(0.8)
    assert not c.is_black_and_white() and win._color_btn.isEnabled() and win._color_btn.isChecked() and hist._mode == "color", "back to Color for a colour film"
    assert win._hist_split_btn.isEnabled()
    # a person who chose Exposure stays on Exposure
    win._exposure_btn.click(); pump(0.1)
    c.set_film_type("bw"); pump(0.5); c.set_film_type("c41"); pump(0.5)
    assert win._exposure_btn.isChecked() and hist._mode == "exposure" and win._color_btn.isEnabled()
    # on Auto, a negative the program detects as black and white counts too
    win._color_btn.click(); pump(0.1)
    c.set_film_type("auto"); c.state.detected_mode = ProcessMode.BW; c.negative_state_changed.emit(); pump(0.2)
    assert c.is_black_and_white() and not win._color_btn.isEnabled()
    c.state.detected_mode = ProcessMode.C41; c.negative_state_changed.emit(); pump(0.2)
    assert not c.is_black_and_white() and win._color_btn.isEnabled() and win._color_btn.isChecked()

    # --- Alt+E shows and hides the error marks
    action = win._error_marks_action
    assert action.shortcut() == QKeySequence("Alt+E")
    was = action.isChecked()
    win.activateWindow(); win.setFocus()
    QTest.keyClick(win, Qt.Key.Key_E, Qt.KeyboardModifier.AltModifier); pump(0.2)
    assert action.isChecked() != was, "Alt+E toggled the error marks"
    QTest.keyClick(win, Qt.Key.Key_E, Qt.KeyboardModifier.AltModifier); pump(0.2)
    assert action.isChecked() == was

    # --- Find reaches presets
    store.save_preset("B&W/Number 1", {"contrast": 0.1}); c.look_presets_changed.emit("")
    c.store_module_preset("exposure", "Soft shadows")
    win._lighttable.set_collections([("My Roll", {})])
    entries = win.find_entries()
    def hit(query, kind):
        return [e for e in F.search(entries, query) if e.kind == kind]
    mine = hit("number 1", "preset")
    assert mine and mine[0].where == "My Presets" and mine[0].extra == {"name": "B&W/Number 1", "builtin": False}, mine[:1]
    assert hit("frontier", "preset")[0].where == "Built-in Presets" and hit("green shadows", "preset")
    assert hit("soft shadows", "preset")[0].where == "Exposure presets" and hit("my roll", "collection")
    assert hit("b&w", "preset") and hit("preset", "preset"), "folder names and the word preset find them too"
    # choosing one goes to it: the Presets list opens on the right set and selects it, nothing is applied
    win.set_view("lighttable"); pump(0.3)
    steps = len(c.state.history)
    win.go_to_entry(mine[0]); pump(0.8)
    pp = win._presets_panel
    assert not win.lighttable_active() and pp._expanded and not pp.showing_builtin() and pp.selected() == "B&W/Number 1" and len(c.state.history) == steps
    win.go_to_entry(hit("crystal 100", "preset")[0]); pump(0.8)
    assert pp.showing_builtin() and pp.selected() == "Scanners (EFAS Original)/Crystal 100" and len(c.state.history) == steps
    win.go_to_entry(hit("my roll", "collection")[0]); pump(0.8)
    assert win.lighttable_active() and win._lighttable._collection_box.currentData() == "My Roll"
    print("ok")
''')


def test_histogram_pinned_log_split_black_and_white_and_find_presets():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout[-2500:] + r.stderr[-3500:]
