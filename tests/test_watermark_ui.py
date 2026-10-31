"""The Watermark tab and the picture: dragging and resizing marks with the mouse, the marker's Move X and Move Y, independent camera/lens text, SVG/PNG markers, and a photo's old Text watermark."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile, time, faulthandler
    faulthandler.enable()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from photoeditor.features.settings import logic as S
    from photoeditor.features.watermark.marks import CUSTOM, Marks
    from photoeditor.features.watermark import layout
    S.save({"scan_quality": False})

    rng = np.random.default_rng(3)
    img = cv2.GaussianBlur(rng.random((600, 900, 3)).astype(np.float32), (0, 0), 25)
    img = (50 + 150 * (img - img.min()) / np.ptp(img)).astype(np.uint8)
    path = os.path.join(folder, "a.png"); cv2.imwrite(path, img)
    svg = os.path.join(work, "logo.svg")
    open(svg, "w").write('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect width="200" height="100" fill="#00aa00"/></svg>')

    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller
    win.show(); app.processEvents()
    win.open_folder(folder, prefer=path)

    def pump(cond=lambda: False, secs=20.0):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond():
                return True
            time.sleep(0.01)
        return cond()
    assert pump(lambda: c.state.image_rgb is not None)
    pump(secs=1.0)
    win._on_tool_tab_toggled("watermark", True); win._tool_rail.set_tab_checked("watermark", True)      # (a closed tab is hidden, so nothing in it is laid out: open the Finish tab)
    tool = win._watermark_tool          # darktable's Watermark: the marker
    ctool = win._canister_tool          # EFAS's Canister Watermark: the canister, the camera and lens text, the old text mark
    view = win._image_view
    s = c.state

    # ---- the Text section is gone: a line of text is the simple-text marker. A style change draws, and the Custom entry is greyed out
    assert not hasattr(tool, "_mark_text") and not hasattr(tool, "_text_position"), "no separate Text section"
    names = [tool._marker_combo.itemData(i) for i in range(tool._marker_combo.count())]
    tool._marker_combo.setCurrentIndex(names.index("simple-text.svg"))
    tool._logo_text.setText("Hello film"); tool._scale.set_value(30); tool._base_combo.setCurrentIndex(tool._base_combo.findData("smaller")); tool._opacity.set_value(100)
    tool._align_buttons[6].click()
    assert pump(lambda: s.marks.has_logo()) and s.marks.logo_text == "Hello film" and s.marks.logo_align == 6 and s.marks.logo_scale == 30.0 and s.marks.logo_base == "smaller"
    assert tool._align_buttons[6].isChecked() and not tool._align_buttons[4].isChecked(), "one alignment at a time"
    assert not tool._img_combo.isVisibleTo(tool) and not tool._svg_combo.isVisibleTo(tool), "the two Advanced controls show only with Scale on advanced options"
    plain = s.image_rgb.copy()
    tool._logo_bold.setChecked(True); tool._rotation.set_value(0); tool._emit_marks()
    assert s.marks.logo_bold
    assert pump(lambda: not np.array_equal(s.image_rgb, plain))

    # ---- the drag switch is under the marker, and turns on a box for it
    layout_order = [tool._marker_combo, tool._xoff, tool._yoff, tool._edit_box]
    ys = [w.mapTo(tool, w.rect().topLeft()).y() for w in layout_order]
    assert ys == sorted(ys), ("the Move and resize box is under the marker's sliders", ys)
    tool._edit_box.setChecked(True)
    assert win._mark_editing
    assert pump(lambda: "logo" in view._label._mark_boxes), view._label._mark_boxes
    x, y, w, h = view._label._mark_boxes["logo"]
    k = view._label._scale
    assert k > 0

    # ---- dragging the marker with the mouse: its X and Y offsets follow (shares of the base, here the smaller border: 600) and the Alignment stays
    label = view._label
    start = QPoint(int((x + w / 2) * k), int((y + h / 2) * k))
    end = QPoint(int((x + w / 2) * k) + int(150 * k), int((y + h / 2) * k) - int(200 * k))
    QTest.mousePress(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(label, QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2))
    QTest.mouseMove(label, end)
    QTest.mouseRelease(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    app.processEvents()
    assert s.marks.logo_align == 6, "the alignment is untouched"
    assert abs(s.marks.logo_xoff - (150 / 600)) < 0.02 and abs(s.marks.logo_yoff - (-200 / 600)) < 0.02, (s.marks.logo_xoff, s.marks.logo_yoff)
    assert abs(tool._xoff.value() - s.marks.logo_xoff) < 0.002 and abs(tool._yoff.value() - s.marks.logo_yoff) < 0.002, "the sliders show how far it was moved"
    assert pump(lambda: abs(view._label._mark_boxes["logo"][0] - (x + 150)) < 4), view._label._mark_boxes["logo"]
    assert any("Watermark" in e.description or "moved" in e.description for e in s.history[-1:]), s.history[-1].description

    # ---- the X and Y sliders move it too, and zero puts it back
    tool._xoff.set_value(0); tool._yoff.set_value(0); tool._emit_marks()
    assert s.marks.logo_xoff == 0 and s.marks.logo_yoff == 0
    assert pump(lambda: abs(view._label._mark_boxes["logo"][0] - x) < 4 and abs(view._label._mark_boxes["logo"][1] - y) < 4), view._label._mark_boxes["logo"]
    tool._xoff.set_value(0.2); tool._emit_marks()
    assert abs(s.marks.logo_xoff - 0.2) < 1e-6 and pump(lambda: abs(view._label._mark_boxes["logo"][0] - (x + 0.2 * 600)) < 4)

    # ---- choosing a corner moves the anchor (the sliders' offset stays)
    tool._xoff.set_value(0); tool._emit_marks()
    tool._align_buttons[0].click()
    assert s.marks.logo_align == 0 and s.marks.logo_xoff == 0 and tool._align_buttons[0].isChecked()

    # ---- resizing with a corner handle scales the marker
    assert pump(lambda: view._label._mark_boxes["logo"][0] < 100)
    x, y, w, h = view._label._mark_boxes["logo"]
    before = s.marks.logo_scale
    view._label._mark_sel = "logo"
    corner = QPoint(int((x + w) * k), int((y + h) * k))
    drag_to = QPoint(corner.x() + int(w * k), corner.y() + int(h * k))
    QTest.mousePress(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, corner)
    QTest.mouseMove(label, drag_to)
    QTest.mouseRelease(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, drag_to)
    app.processEvents()
    assert s.marks.logo_scale > before * 1.5, (before, s.marks.logo_scale)
    assert s.marks.logo_align == 0

    # ---- darktable's range: the slider ends at 100%, and the box beside it takes any size up to 500%
    assert tool._scale._slider.maximum() > 0 and abs(tool._scale._spin.maximum() - 500.0) < 1e-6 and abs(tool._scale._spin.minimum() - 1.0) < 1e-6
    tool._scale._spin.setValue(450.0)
    assert tool._scale.value() == 450.0 and tool._scale._slider.value() == tool._scale._slider.maximum(), "the slider rests at its end"
    tool._emit_marks()
    assert s.marks.logo_scale == 450.0
    assert pump(lambda: "logo" in view._label._mark_boxes and view._label._mark_boxes["logo"][2] > 2000), view._label._mark_boxes.get("logo")
    tool._scale.set_value(before); tool._emit_marks()

    # ---- undo restores the old placement and the panel follows
    c.undo(); app.processEvents()
    assert tool.marks() == s.marks

    # ---- a photo that still has a Text watermark from an earlier version: it is drawn, the panel says so, and it can be made a marker or removed
    c.set_marks(Marks(text="Old words", text_size=0.05, text_color="#ff0000", text_position="top_left"))
    assert pump(lambda: s.marks.has_text() and not s.marks.logo)
    win._show_watermark_marks(s.marks)   # (the panels follow a change made elsewhere, such as a preset, through the window)
    assert ctool._old_text.isVisibleTo(ctool), ("note hidden", ctool._old_text.text(), s.marks)
    assert "Old words" in ctool._old_text.text() and ctool._old_text_convert.isEnabled(), (ctool._old_text.text(), ctool._old_text_convert.isEnabled(), s.marks.logo)
    ctool._old_text_convert.click()
    assert s.marks.text == "" and s.marks.logo == "simple-text.svg" and s.marks.logo_text == "Old words" and s.marks.logo_color == "#ff0000" and s.marks.logo_align == 0
    assert not ctool._old_text.isVisibleTo(ctool) and tool._marker_combo.currentData() == "simple-text.svg", "the marker is the Watermark module's: its panel shows it"
    c.set_marks(Marks(text="Other words", logo="simple-text.svg"))
    assert pump(lambda: s.marks.has_text())
    win._show_watermark_marks(s.marks)
    assert ctool._old_text.isVisibleTo(ctool) and not ctool._old_text_convert.isEnabled(), "a photo has one marker: choose None first"
    ctool._old_text_remove.click()
    assert s.marks.text == "" and s.marks.logo == "simple-text.svg" and not ctool._old_text.isVisibleTo(ctool)
    c.set_marks(Marks())
    assert pump(lambda: not s.marks.has_logo())

    # ---- camera and lens on their own, no canister
    assert s.wm_film == "off"
    ctool._info.setChecked(True)
    ctool._camera.setText("Pentax K1000"); ctool._lens.setText("SMC 50mm f/2"); ctool._on_text_finished()
    assert pump(lambda: s.wm_info and s.wm_camera == "Pentax K1000")
    assert ctool._info_position.isEnabled() and ctool._info_size.isEnabled(), "its own style controls are live without a canister"
    assert pump(lambda: "info" in view._label._mark_boxes), view._label._mark_boxes
    c.state.image_rgb  # rendered with the text
    ctool._info_credit.setChecked(False)
    assert not s.marks.info_credit

    # ---- a canister: beside text again; untick Next to the canister to make it independent
    ctool._film.setCurrentIndex(ctool._film.findData("kodak_gold_200"))
    assert s.wm_film == "kodak_gold_200"
    assert pump(lambda: "canister" in view._label._mark_boxes and "info" not in view._label._mark_boxes), view._label._mark_boxes
    assert not ctool._info_position.isEnabled(), "beside the canister the standalone style controls are off"
    ctool._info_beside.setChecked(False)
    assert pump(lambda: "info" in view._label._mark_boxes and "canister" in view._label._mark_boxes)

    # ---- drag the canister: Position menu says Custom; a size drag makes Size Custom; a menu pick puts it back
    x, y, w, h = view._label._mark_boxes["canister"]
    k = view._label._scale
    start = QPoint(int((x + w / 2) * k), int((y + h / 2) * k)); end = QPoint(start.x() - int(200 * k), start.y() - int(100 * k))
    QTest.mousePress(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(label, end)
    QTest.mouseRelease(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    app.processEvents()
    assert s.marks.has_custom_canister() and ctool._position.currentData() == CUSTOM
    assert s.wm_position == "bottom_right", "the stored menu choice is untouched"
    assert ctool.values()[3] == "bottom_right"
    assert pump(lambda: "canister" in view._label._mark_boxes)
    x, y, w, h = view._label._mark_boxes["canister"]
    view._label._mark_sel = "canister"
    corner = QPoint(int((x + w) * k), int((y + h) * k))
    to = QPoint(corner.x() + int(w * k * 0.5), corner.y() + int(h * k * 0.5))
    QTest.mousePress(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, corner)
    QTest.mouseMove(label, to)
    QTest.mouseRelease(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, to)
    app.processEvents()
    assert s.marks.canister_size > 0 and ctool._size.currentData() == CUSTOM
    ctool._position.setCurrentIndex(ctool._position.findData("top_left"))
    assert s.wm_position == "top_left" and not s.marks.has_custom_canister() and ctool._position.currentData() == "top_left"
    ctool._size.setCurrentIndex(ctool._size.findData("small"))
    assert s.wm_size == "small" and s.marks.canister_size == 0.0

    # ---- logos: an SVG and a PNG
    QMessageBox.warning = staticmethod(lambda *a, **k: None)
    from PyQt6.QtWidgets import QFileDialog
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (svg, ""))
    tool._choose_logo()
    from photoeditor.features.watermark import library
    assert s.marks.logo == "logo.svg" and os.path.isfile(os.path.join(library.user_dir(), "logo.svg")), "Add... copies the file into the watermarks folder and uses it by name"
    assert "SVG" in tool._logo_name.text() and tool._marker_combo.currentData() == "logo.svg"
    assert pump(lambda: "logo" in view._label._mark_boxes and abs(view._label._mark_boxes["logo"][2] / view._label._mark_boxes["logo"][3] - 2.0) < 0.05), ("the box keeps the SVG's shape", view._label._mark_boxes.get("logo"))
    png = os.path.join(work, "logo.png"); cv2.imwrite(png, np.full((50, 50, 4), 255, np.uint8))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (png, ""))
    tool._choose_logo()
    assert s.marks.logo == "logo.png"
    bad = os.path.join(work, "bad.svg"); open(bad, "w").write("<svg")
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (bad, ""))
    tool._choose_logo()
    assert s.marks.logo == "logo.png" and not os.path.exists(os.path.join(library.user_dir(), "bad.svg")), "an unreadable SVG is refused, and is not copied"

    # ---- saved and restored with the photo
    c._save_edit_state()
    saved = c._db and __import__("photoeditor.features.persistence.edit_store", fromlist=["x"]).load_edit_state(c._db, path)
    assert Marks.from_dict(saved["marks"]) == s.marks
    c.reset_edits() if hasattr(c, "reset_edits") else None

    # ---- fonts: the list fills in, and a font file can be picked
    tool._start_font_scan()
    assert pump(lambda: tool._logo_font.count() > 3, 60.0), tool._logo_font.count()
    fam = tool._logo_font.itemData(1)
    assert fam is not None
    tool._logo_font.set_value(fam)
    assert tool._logo_font.value() == fam
    tool._logo_font.set_value("C:/some/where/Custom.ttf")
    assert tool._logo_font.currentText() == "Custom.ttf" and tool._logo_font.value() == "C:/some/where/Custom.ttf"

    # ---- editing off: no boxes
    tool._edit_box.setChecked(False)
    assert not view._label._mark_boxes

    win.close()
    print("WATERMARK UI OK"); sys.stdout.flush()
    os._exit(0)
''')


def test_watermark_panel_and_dragging():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=400)
    assert "WATERMARK UI OK" in done.stdout, done.stdout[-1500:] + done.stderr[-4000:]
