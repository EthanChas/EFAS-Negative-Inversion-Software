"""Masks in the window: a module's Mask box draws a shape that becomes the module's mask, a second shape joins it in a group, the Masks panel lists and edits them, everything is undoable and
saved with the photo; and the Dust Detection folder lists what dust detection found (Dust, Hairs, Scratches), rings it on the picture and deletes it."""
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    from photoeditor.features.masks import blend as B, model as M
    S.save({"scan_quality": False})
    rng = np.random.default_rng(0)
    base = np.linspace(60, 190, 900, dtype=np.float32)[None, :, None] * np.ones((600, 1, 3), np.float32)
    img = np.clip(base + rng.normal(0, 3, (600, 900, 3)), 0, 255).astype(np.uint8)
    for x, y in ((150, 120), (700, 480), (420, 300)):   # three dark specks, round, a few pixels across
        cv2.circle(img, (x, y), 4, (20, 20, 20), -1)
    path = os.path.join(folder, "a.png"); cv2.imwrite(path, img)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=path)
    def pump(cond=lambda: False, secs=20.0):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if cond(): return True
            time.sleep(0.01)
        return cond()
    assert pump(lambda: c.state.image_rgb is not None); pump(secs=1.0)
    s = c.state; box = win._blend_boxes["exposure"]; editor = win._mask_editor; tool = editor.tool; mgr = win._mask_manager
    assert set(win._blend_boxes) >= {"exposure", "contrast", "tonecurve", "sharpening", "halation", "grainsharp"}, "every blendable module has a Mask box"
    assert s.blends == {} and s.masks == {}

    def show_pt(fx, fy):
        return c.raw_to_display(np.array([[fx, fy]], float))[0]
    def place(kind, fx, fy):
        x, y = show_pt(fx, fy)
        win.begin_mask_drawing("exposure", kind)
        assert tool.creation is not None and tool.active
        assert tool.press(x, y, "left", set(), 8.0), "the press places the shape"
        tool.release(x, y, "left", set(), 8.0)

    # --- a module's Mask box: choose Drawn mask, draw a circle -> it is the module's mask
    i = box._mode.findData(B.DRAWN); box._mode.setCurrentIndex(i); box._mode.activated.emit(i); app.processEvents()
    assert c.blend_of("exposure").mode == B.DRAWN and c.blend_of("exposure").mask_id == 0, (c.blend_of("exposure"), box._mode.findData(B.DRAWN), box._mode.count(), s.blends)
    c.set_exposure_ev(1.0); pump(secs=1.0)
    everywhere = s.image_rgb.astype(int).copy()
    before_circle = everywhere
    place(M.CIRCLE, 0.3, 0.5)
    assert pump(lambda: c.blend_of("exposure").mask_id == 1), (s.blends, s.masks)
    assert tool.creation is None and tool.edit and tool.visible == {1}, "after placing, the shape is there to edit"
    assert s.masks, s.masks
    assert pump(lambda: not np.array_equal(s.image_rgb.astype(int), everywhere), 10.0)
    assert box._edit.isChecked(), "the pencil shows the mask is being edited"
    # the circle lifts its neighbourhood only: the far right is as dark as with no exposure change
    c.set_module_enabled("exposure", False); pump(secs=1.0); off = s.image_rgb.astype(int).copy(); c.set_module_enabled("exposure", True); pump(secs=1.0)
    lit = s.image_rgb.astype(int)
    h, w = lit.shape[:2]
    cy, cx = int(0.5 * h), int(0.3 * w)
    assert np.abs(lit[cy-3:cy+3, cx-3:cx+3] - off[cy-3:cy+3, cx-3:cx+3]).mean() > 8, "inside the circle the exposure acts"
    assert np.abs(lit[:, int(0.8 * w):] - off[:, int(0.8 * w):]).mean() < 1.0, "outside it, it does not"

    # --- a second shape from the same Mask box joins the first in a group
    place(M.ELLIPSE, 0.7, 0.3)
    assert pump(lambda: len(s.masks) and len(c.mask_set().groups()) == 1), s.masks
    group = c.mask_set().groups()[0]
    assert c.blend_of("exposure").mask_id == group.id and [p["formid"] for p in group.points] == [1, 2], group.points
    assert group.name == "Exposure mask", group.name

    # --- the Masks panel lists them: Dust Detection folder first with Dust, Hairs, Scratches, then Groups and Shapes
    tree = mgr._tree
    top = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert top == ["Dust Detection", "Groups", "Shapes"], top
    subs = [tree.topLevelItem(0).child(i).text(0) for i in range(3)]
    assert subs == ["Dust", "Hairs", "Scratches"], subs
    groups_item, shapes_item = tree.topLevelItem(1), tree.topLevelItem(2)
    assert groups_item.childCount() == 1 and groups_item.child(0).childCount() == 2 and shapes_item.childCount() == 2
    # picking a shape in the list shows it on the picture
    shapes_item.child(0).setSelected(True); app.processEvents()
    assert editor._manager and tool.visible == {1}, tool.visible
    tree.clearSelection(); groups_item.child(0).setSelected(True); app.processEvents()
    assert tool.visible == {1, 2} and tool.parent_id == group.id

    # --- a free shape from the panel
    mgr._draw_buttons[M.CIRCLE].click(); assert tool.creation is not None and tool.creation.key is None
    x, y = show_pt(0.5, 0.8); tool.press(x, y, "left", set(), 8.0); tool.release(x, y, "left", set(), 8.0); app.processEvents()
    free = max(f.id for f in c.mask_set().shapes())
    assert len(c.mask_set().shapes()) == 3 and tool.visible == {free} and free == 4, (tool.visible, len(c.mask_set().shapes()))

    # --- scrolling a shape resizes it, and the change is one undo step once the wheel stops
    steps = len(s.history)
    x, y = show_pt(0.5, 0.8)
    before_r = c.mask_set().get(free).points[0]["radius"]
    for _ in range(4):
        assert tool.scroll(x, y, True, set(), 8.0)
    editor._flush.stop(); tool.flush(); app.processEvents()
    after_r = c.mask_set().get(free).points[0]["radius"]
    assert after_r > before_r, (before_r, after_r)
    assert len(s.history) == steps + 1, "four ticks of the wheel are one step in the history"
    c.undo(); app.processEvents()
    assert abs(c.mask_set().get(free).points[0]["radius"] - before_r) < 1e-9

    # --- delete, undo and persistence
    mgr.delete_requested.emit([free]); app.processEvents()
    assert c.mask_set().get(free) is None
    c.undo(); app.processEvents()
    assert c.mask_set().get(free) is not None
    c._save_edit_state()
    saved = edit_store.load_edit_state(c._db, path)
    assert saved["blends"]["exposure"]["mask_id"] == group.id and saved["masks"], saved["blends"]
    c.undo(); c.undo(); c.undo(); app.processEvents()   # the free circle, the group and the blend are taken back, one step each
    assert c.mask_set().get(free) is None and c.mask_set().get(group.id) is None, "the group is undone"

    # --- Dust Detection: a traced scratch and the specks
    c.state.scratch_lines = [[0.1, 0.5, 0.9, 0.5, 6.0]]
    c.set_dust(True, 0.5, 10, 0.8); pump(secs=1.5)
    mgr.detections_requested.emit(); assert pump(lambda: mgr._listed, 15.0), "the list fills once the picture is drawn with Show Detections"
    items = c.detection_items()
    assert len(items["scratches"]) == 1 and items["scratches"][0]["index"] == 0
    dust_label = tree.topLevelItem(0).child(2).text(0)
    assert dust_label == "Scratches (1)", dust_label
    scratch_leaf = tree.topLevelItem(0).child(2).child(0)
    scratch_leaf.setSelected(True); app.processEvents()
    marks = win._image_view._label._focus_marks
    assert marks and marks[0][0] == "line", "a picked scratch is underlined on the picture"
    mgr._delete_btn.click(); assert pump(lambda: not c.state.scratch_lines), "Delete takes the scratch out"
    assert pump(lambda: mgr._listed and tree.topLevelItem(0).child(2).text(0) == "Scratches (0)", 10.0), tree.topLevelItem(0).child(2).text(0)
    assert win._image_view._label._focus_marks == []
    print("OK dust:", len(items["dust"]), "hairs:", len(items["hairs"]))
    assert len(items["dust"]) >= 1, "the specks are listed under Dust"
    dust_item = tree.topLevelItem(0).child(0)
    assert dust_item.childCount() == len(items["dust"]) and dust_item.text(0).startswith("Dust (")
    tree.clearSelection(); dust_item.child(0).setSelected(True); app.processEvents()
    assert win._image_view._label._focus_marks[0][0] == "ring"
    n = len(items["dust"]); mgr._delete_btn.click()
    assert pump(lambda: mgr._listed and tree.topLevelItem(0).child(0).childCount() == n - 1, 15.0), (n, tree.topLevelItem(0).child(0).childCount())
    assert len(s.dust_excluded) == 1
""")


def test_masks_in_the_window():
    r = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env={**__import__("os").environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK dust" in r.stdout, r.stdout[-2000:] + r.stderr[-4000:]
