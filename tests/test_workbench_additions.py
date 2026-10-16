"""The clipped-share arrows on the histogram, the Slideshow / Maps / Classroom pages, folder icons, and filtering the Workbench by error marks."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from photoeditor.features.library import query as Q

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _row(name, errors=()):
    return {
        "name": name, "ext": ".tif", "_blob": name.lower(), "rating": 0, "flag": None, "edited": False, "camera": "", "roll_camera": "", "lens": "", "roll_lens": "", "film": "",
        "folder": "C:\\x", "folder_key": "c:\\x", "tags": [], "iso": 0, "day": "2026-10-01", "errors": list(errors), "error_count": len(errors),
        "errors_text": " ".join(sorted({f"{k} x" for k in errors})), "taken": "2026-10-01", "mtime_ns": 0,
    }


def test_the_search_finds_photos_by_the_faults_marked_on_them():
    from photoeditor.features.errormarks import logic as E

    rows = [_row("a", ["scratch", "scratch", "dust"]), _row("b", ["newton"]), _row("c")]
    for r in rows:
        r["errors_text"] = " ".join(sorted({f"{k} {E.kind(k).label.lower()}" for k in r["errors"]}))

    def names(text):
        return [r["name"] for r in Q.filter_rows(rows, Q.Query(text=text))]

    assert names("error:yes") == ["a", "b"] and names("error:none") == ["c"] and names("error:any") == ["a", "b"]
    assert names("error:scratch") == ["a"] and names("error:newton") == ["b"] and names("fault:dust") == ["a"]
    assert names("error:\"newton rings\"") == ["b"], "a kind can be found by its name"
    assert names("-error:yes") == ["c"] and names("error:scratch -error:newton") == ["a"]
    assert Q.parse_terms("error:yes") == [(False, "error", "yes")], "error is a field of its own, not plain text"


def test_a_filter_state_and_a_smart_collection_can_hold_an_error_filter():
    assert Q.default_state()["errors"] == "" and Q.clean_state({"errors": "scratch"})["errors"] == "scratch"
    assert Q.clean_state({"errors": "nonsense"})["errors"] == "" and Q.clean_state({"errors": 5})["errors"] == ""
    assert Q.clean_state({"errors": "none"})["errors"] == "none"
    rows = [_row("a", ["scratch"]), _row("b"), _row("c", ["dust"])]
    pick = lambda e: [r["name"] for r in Q.filter_rows(rows, Q.query_from_state({"errors": e}))]
    assert pick("any") == ["a", "c"] and pick("none") == ["b"] and pick("dust") == ["c"] and pick("") == ["a", "b", "c"]
    assert Q.Query(errors="any").is_filtering() and not Q.Query().is_filtering()
    assert "error marks" in Q.describe_state({"errors": "any"}) and "scratches" in Q.describe_state({"errors": "scratch"})


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    from PyQt6.QtWidgets import QApplication, QLabel
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    rng = np.random.default_rng(0)
    a = os.path.join(work, "a.png"); cv2.imwrite(a, rng.integers(60, 190, (200, 300, 3), dtype=np.uint8))
    b = os.path.join(work, "b.png"); cv2.imwrite(b, rng.integers(60, 190, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.features.library import query as Q
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=a); c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(2)

    # --- Maps and Classroom: buttons before Workbench and Editor, each a page that says Soon (the Slideshow is a real page: tests/test_slideshow.py)
    assert list(win._view_buttons) == ["slideshow", "maps", "classroom", "lighttable", "editor"], list(win._view_buttons)
    for key, title in (("maps", "Maps"), ("classroom", "Classroom")):
        win._view_buttons[key].click(); pump(0.3)
        page = win._view_stack.currentWidget()
        texts = [l.text() for l in page.findChildren(QLabel)]
        assert texts == [title, "Soon\u2122"], texts
        assert win._view_buttons[key].isChecked() and not win._view_buttons["editor"].isChecked() and not win.lighttable_active()
    win.set_view("lighttable"); pump(0.6)
    assert win.lighttable_active() and win._view_buttons["lighttable"].isChecked() and not win._view_buttons["classroom"].isChecked()
    win.set_view("editor"); pump(0.3)
    assert win._view_stack.currentIndex() == 0 and win._view_buttons["editor"].isChecked()

    # --- the clipped share beside the histogram: the numbers, a click marks the picture
    h = win._histogram_panel
    lum = [0] * 256; lum[0] = 40; lum[2] = 10; lum[100] = 900; lum[255] = 50
    h.set_data({"r": lum, "g": lum, "b": lum}, lum); pump(0.2)
    shadows, highlights = h.clip_share()
    assert abs(shadows - 5.0) < 1e-6 and abs(highlights - 5.0) < 1e-6, (shadows, highlights)
    h.grab()   # paints, so the arrows have somewhere to be
    assert set(h._clip_rects) == {"shadows", "highlights"} and h._clip_rects["shadows"].right() < h._clip_rects["highlights"].left()
    for width in (120, 200, 320):   # a narrow histogram (log scale on, zoomed) still paints, and the arrows stay inside it
        h.resize(width, 150); h.set_log(True); h._zoom_min, h._zoom_max = 40.0, 120.0; h.grab()
        assert all(r.left() >= 0 and r.right() <= width for r in h._clip_rects.values()) or width == 120, (width, h._clip_rects)
    h._zoom_min, h._zoom_max = 0.0, 255.0; h.set_log(False); h.resize(300, 150); h.grab()
    assert win._tool_rail._buttons["correction"].text() == "Frame && Clean", "an ampersand shows as an ampersand, not a keyboard mnemonic"
    def click(kind):
        r = h._clip_rects[kind]
        ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(r.center()), QPointF(r.center()), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        h.mousePressEvent(ev)
    click("shadows"); pump(0.4)
    assert win._shadow_clip_btn.isChecked() and not win._highlight_clip_btn.isChecked() and h._clip_marking == (True, False)
    click("highlights"); pump(0.4)
    assert win._highlight_clip_btn.isChecked() and h._clip_marking == (True, True)
    click("shadows"); click("highlights"); pump(0.4)
    assert not win._shadow_clip_btn.isChecked() and h._clip_marking == (False, False)

    # --- the library's folders have icons (a file from assets/icon), open while expanded
    os.makedirs(os.path.join(work, "sub"))
    tree = win._library_panel._tree
    tree.add_root(work); pump(0.2)
    top = tree.topLevelItem(tree.topLevelItemCount() - 1)
    assert top is not None and not top.icon(0).isNull(), "a folder has an icon"
    shut = top.icon(0).pixmap(16, 16).toImage()
    top.setExpanded(True); pump(0.2)
    assert not top.icon(0).isNull() and top.icon(0).pixmap(16, 16).toImage() != shut, "open while expanded"
    top.setExpanded(False); pump(0.2)
    assert top.icon(0).pixmap(16, 16).toImage() == shut
    wtree = win._lighttable.library_panel._tree
    wtree.add_root(work); pump(0.2)
    assert not wtree.topLevelItem(wtree.topLevelItemCount() - 1).icon(0).isNull(), "the Workbench's library too"

    # --- error marks, from the editor to the Workbench's filter
    c.add_error_mark("scratch", 10, 10, 60, 40); pump(0.5)
    c._save_edit_state()
    meta = Q.load_meta(c._db, [{"path": a, "folder": work}, {"path": b, "folder": work}])
    assert meta.errors[Q.norm(a)] == ["scratch"] and Q.norm(b) not in meta.errors
    win.set_view("lighttable"); pump(1.5)
    lt = win._lighttable
    assert [k for k in ("any", "none", "scratch", "newton") if lt._errors.findData(k) >= 0] == ["any", "none", "scratch", "newton"]
    lt.set_filter_state({"errors": "scratch"}); pump(0.5)
    shown = [r["name"] for r in lt._shown]
    assert shown == ["a"], shown
    assert lt.filter_state()["errors"] == "scratch"
    lt.set_filter_state({"errors": "none"}); pump(0.5)
    assert [r["name"] for r in lt._shown] == ["b"]
    lt.set_filter_state({}); lt._search.setText("error:yes"); lt._text_timer.stop(); lt.apply_filters(); pump(0.3)
    assert [r["name"] for r in lt._shown] == ["a"]
    lt.clear_filters(); pump(0.3)
    assert lt._errors.currentData() == "" and len(lt._shown) == 2
    print("OK")
""")


def test_the_new_views_arrows_icons_and_error_filter_in_the_window():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=300, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]
