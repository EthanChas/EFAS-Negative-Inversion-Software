"""Markers in the window: the Marker list and its controls in the Watermark tab, the variables of the open photo (and what the Roll Card changes), the Variables list, and the export."""
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
    folder = os.path.join(work, "Holiday 2024"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
    from photoeditor.features.settings import logic as S
    from photoeditor.features.watermark import library
    from photoeditor.features.watermark.marks import Marks
    from photoeditor.features.metadata.roll import RollCard
    S.save({"scan_quality": False})

    rng = np.random.default_rng(3)
    img = cv2.GaussianBlur(rng.random((600, 900, 3)).astype(np.float32), (0, 0), 25)
    img = (50 + 150 * (img - img.min()) / np.ptp(img)).astype(np.uint8)
    path = os.path.join(folder, "frame7.png"); cv2.imwrite(path, img)

    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view import watermark_variables_dialog as D
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
    tool = win._watermark_tool; s = c.state

    # ---- the Marker list: the samples, "None", and what each marker can use
    names = [tool._marker_combo.itemData(i) for i in range(tool._marker_combo.count())]
    assert names[0] == "" and {"simple-text.svg", "copyright-line.svg", "film-frame-info.svg"} <= set(names), names
    assert tool._marker_combo.itemText(0) == "None" and "sample" in tool._marker_combo.itemText(names.index("simple-text.svg"))
    assert not tool._logo_text.isEnabled() and not tool._logo_color.isEnabled() and not tool._logo_font.isEnabled(), "no marker: nothing to set"
    tool._marker_combo.setCurrentIndex(names.index("simple-text.svg"))
    assert s.marks.logo == "simple-text.svg" and tool._logo_text.isEnabled() and tool._logo_color.isEnabled() and tool._logo_font.isEnabled() and tool._logo_bold.isEnabled()
    assert "text, colour, font" in tool._logo_name.text(), tool._logo_name.text()
    tool._marker_combo.setCurrentIndex(names.index("film-frame-info.svg"))
    assert not tool._logo_text.isEnabled() and tool._logo_color.isEnabled(), "this marker writes the film's details: it has no use for a text of your own"

    # ---- the text, colour, size and rotation reach the picture
    tool._marker_combo.setCurrentIndex(names.index("simple-text.svg"))
    before = s.image_rgb.copy()
    tool._logo_text.setText("(c) Me $(EXIF.YEAR-2026)"); tool._logo_color.set_value("#ff0000"); tool._logo_size.set_value(60); tool._logo_position.setCurrentIndex(tool._logo_position.findData("center"))
    tool._emit_marks()
    assert s.marks.logo_text == "(c) Me $(EXIF.YEAR-2026)" and s.marks.logo_color == "#ff0000" and s.marks.logo_size == 0.6
    assert pump(lambda: not np.array_equal(s.image_rgb, before)), "the marker is drawn"
    red = (s.image_rgb[..., 0].astype(int) - s.image_rgb[..., 1].astype(int) > 100).sum()
    assert red > 200, "in red"
    tool._logo_scale_on.setCurrentIndex(tool._logo_scale_on.findData("width")); tool._logo_rotation.set_value(90); tool._emit_marks()
    assert s.marks.logo_scale_on == "width" and s.marks.logo_rotation == 90.0
    tool.set_marks(s.marks)   # what a history step does: the controls show what is stored
    assert tool._logo_scale_on.currentData() == "width" and tool._logo_rotation.value() == 90 and tool._logo_text.text() == "(c) Me $(EXIF.YEAR-2026)" and tool._marker_combo.currentData() == "simple-text.svg"

    # ---- a picture marker has its own colours; a marker that is not there is said to be missing and is not drawn
    png = os.path.join(work, "dot.png"); cv2.imwrite(png, np.full((40, 40, 4), 255, np.uint8))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (png, ""))
    tool._choose_logo()
    assert s.marks.logo == "dot.png" and os.path.isfile(os.path.join(library.user_dir(), "dot.png")) and "Picture marker" in tool._logo_name.text()
    assert not tool._logo_text.isEnabled() and not tool._logo_color.isEnabled()
    tool.set_marks(Marks(logo="gone.svg", logo_size=0.5))
    assert "Missing: gone.svg" in tool._logo_name.text() and tool._marker_combo.currentData() == "gone.svg" and tool._marker_combo.currentText() == "Missing: gone.svg"
    assert not Marks(logo="gone.svg").has_logo()
    open(os.path.join(library.user_dir(), "gone.svg"), "w").write('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
    tool._marker_reload.click()
    assert tool._marker_combo.currentText() == "gone (svg)" and "Missing" not in tool._logo_name.text(), "a file put into the folder is found by Reload"

    # ---- the variables of the open photo, and what a Roll Card changes
    v = c.watermark_variables()
    assert v["FILE.NAME"] == "frame7" and v["FILE.FOLDER"] == "Holiday 2024" and v["ROLL.NAME"] == "Holiday 2024" and v["CAMERA"] == "", v
    c.set_marks(Marks(text="$(CAMERA)", text_position="center", text_size=0.08))
    assert pump(lambda: s.marks.text == "$(CAMERA)")
    empty = s.image_rgb.copy()
    c.set_roll(RollCard(camera="Pentax K1000", film="Kodak Gold 200", iso=200, lens="SMC 50mm f/2"))
    assert dict(s.wm_vars)["CAMERA"] == "Pentax K1000" and dict(s.wm_vars)["FILM"] == "Kodak Gold 200" and dict(s.wm_vars)["EXIF.ISO"] == "200" and dict(s.wm_vars)["LENS"] == "SMC 50mm f/2"
    assert pump(lambda: not np.array_equal(s.image_rgb, empty)), "the text comes from the Roll Card: it is drawn once the card is filled in"
    one = s.image_rgb.copy()
    c.set_roll(RollCard(camera="Canon AE-1 Program", film="Kodak Gold 200", iso=200))
    assert pump(lambda: not np.array_equal(s.image_rgb, one)), "a different camera writes different words"

    # ---- the Variables... list
    shown = []
    D.WatermarkVariablesDialog.exec = lambda self: shown.append(self.names())
    tool.variables_requested.emit()
    assert shown and {"$(CAMERA)", "$(EXIF.YEAR)", "$(FILE.NAME)", "$(FILM)", "$(ROLL.NAME)"} <= set(shown[-1]) and "$(NL)" not in shown[-1], shown

    # ---- the export draws it too: the render parameters for a photo that is not open carry the variables
    from photoeditor.desktop import export_worker as X
    c._save_edit_state()
    params, _ff = X._edits_for(path, c._db, cv2.resize(img, (300, 200)))
    got = dict(params.wm_vars)
    assert got["CAMERA"] == "Canon AE-1 Program" and got["FILE.NAME"] == "frame7" and got["EXIF.ISO"] == "200", got
    c.set_marks(Marks())
    c._save_edit_state()
    params, _ff = X._edits_for(path, c._db, cv2.resize(img, (300, 200)))
    assert params.wm_vars == (), "a photo with no watermark does not pay for the variables"
    win.close()
    print("WATERMARK MARKERS OK")
''')


def test_markers_and_variables_in_the_window():
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], capture_output=True, text=True, timeout=400, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert "WATERMARK MARKERS OK" in done.stdout, done.stdout[-1500:] + done.stderr[-4000:]
