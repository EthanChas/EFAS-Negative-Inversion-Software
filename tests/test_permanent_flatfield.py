"""The permanent flat field (one for every photo, in every folder, forever), the Tagging panel starting closed, and the old thumbnail caches coming home."""
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import numpy as np

SRC = str(Path(__file__).resolve().parents[1] / "src")
TESTS = str(Path(__file__).resolve().parent)

_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    data = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_DATA_DIR"] = data
    work = tempfile.mkdtemp()
    sys.path.insert(0, TESTS)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    from photoeditor.desktop import export_worker
    S.save({"scan_quality": False})
    import test_flatfield_check as T
    folders, paths = [], []
    for name in ("one", "two"):
        f = os.path.join(work, name); os.makedirs(f); folders.append(f)
        p = os.path.join(f, "a.png"); cv2.imwrite(p, T.field(level=150, falloff=0.9, seed=3)[..., ::-1]); paths.append(p)
    light = os.path.join(work, "light.png"); cv2.imwrite(light, T.field(falloff=0.5, seed=11)[..., ::-1])
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); c = win.controller
    win.open_folder(folders[0], prefer=paths[0])

    # the Tagging panel starts closed in the editor and the Workbench
    assert not win._tagging_panel._expanded and not win._lighttable.tagging._expanded

    assert c._ff is None and not c.flatfield_info()["permanent"]["has"]
    c.set_permanent_flatfield_from_reference(light)
    info = c.flatfield_info()
    assert c._ff is not None and info["scope"] == "permanent" and info["permanent"]["enabled"] and info["permanent"]["source"] == "light.png"
    assert "permanent flat field" in win._flatfield_tool._permanent_hint.text().lower()

    # a photo in another folder gets it too, including in the export path
    win.open_folder(folders[1], prefer=paths[1])
    assert c._ff is not None and c.flatfield_info()["scope"] == "permanent"
    _params, ff = export_worker._edits_for(paths[1], c._db, np.zeros((10, 10, 3), np.uint8))
    assert ff is not None

    # a folder flat field wins over it (no stacking), and goes back to it when removed
    c.set_folder_flatfield_from_reference(light)
    assert c.flatfield_info()["scope"] == "folder"
    c.clear_folder_flatfield()
    assert c.flatfield_info()["scope"] == "permanent"
    c.set_folder_flatfield_from_reference(light)
    c.set_flatfield_enabled(False)
    assert c.flatfield_info()["scope"] == "permanent"
    c.clear_folder_flatfield()

    # switched off, it does nothing; on again it is back
    c.set_permanent_flatfield_enabled(False)
    assert c._ff is None and c.flatfield_info()["scope"] == "" and c.flatfield_info()["permanent"]["has"]
    assert export_worker._edits_for(paths[1], c._db, np.zeros((10, 10, 3), np.uint8))[1] is None
    c.set_permanent_flatfield_enabled(True)
    assert c._ff is not None

    # it is still there after the app is closed and opened again
    win.close()
    win2 = aw.AppWindow(); c2 = win2.controller
    win2.open_folder(folders[0], prefer=paths[0])
    assert c2._ff is not None and c2.flatfield_info()["scope"] == "permanent"

    # a folder's flat field can be promoted to the permanent one
    c2.clear_permanent_flatfield()
    assert c2._ff is None
    c2.set_folder_flatfield_from_reference(light)
    c2.make_folder_flatfield_permanent()
    c2.clear_folder_flatfield()
    assert c2.flatfield_info()["scope"] == "permanent" and c2.flatfield_info()["permanent"]["source"] == "light.png"
    c2.clear_permanent_flatfield()
    assert c2._ff is None and not c2.flatfield_info()["permanent"]["has"]
    win2.close()
    print("PERMANENT FLAT OK")
'''.replace("TESTS", repr(TESTS)))


def test_permanent_flat_field_and_closed_tagging():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=300)
    assert "PERMANENT FLAT OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]


def test_old_thumbnail_caches_are_merged_into_the_data_folder(tmp_path):
    from photoeditor.desktop import paths as P

    old1 = tmp_path / "python" / "cache" / "thumbnails"
    old2 = tmp_path / "pythonw" / "cache" / "thumbnails"
    new = tmp_path / ".EFAS" / "thumbnail-cache"
    for d in (old1, old2, new):
        d.mkdir(parents=True)
    (old1 / "a_edited.jpg").write_bytes(b"cropped")
    (old1 / "b.jpg").write_bytes(b"plain")
    (old2 / "c_edited.jpg").write_bytes(b"rotated")
    (old1 / "same.jpg").write_bytes(b"old copy")
    (new / "same.jpg").write_bytes(b"new copy")
    now = time.time()
    os.utime(old1 / "same.jpg", (now - 100, now - 100))
    os.utime(new / "same.jpg", (now, now))
    (old2 / "newer.jpg").write_bytes(b"newer old")
    (new / "newer.jpg").write_bytes(b"stale new")
    os.utime(new / "newer.jpg", (now - 100, now - 100))

    for old in (old1, old2):
        P.merge_thumbnails(str(old), str(new))

    assert sorted(p.name for p in new.iterdir()) == ["a_edited.jpg", "b.jpg", "c_edited.jpg", "newer.jpg", "same.jpg"]
    assert (new / "same.jpg").read_bytes() == b"new copy" and (new / "newer.jpg").read_bytes() == b"newer old"
    assert (new / "a_edited.jpg").read_bytes() == b"cropped"
    assert not old1.exists() and not old2.exists(), "the emptied old cache folders are removed"
    assert (tmp_path / "python").exists(), "the shared python folder itself is left alone"


def _narrow_negative16(h=200, w=600):
    x = np.linspace(0, 1, w, dtype=np.float32)[None, :, None] * np.ones((h, 1, 3), np.float32)
    return (24000 + 20000 * x).astype(np.uint16)  # a scan using only a third of the 16-bit range, smooth


def test_flat_field_keeps_a_16_bit_scan_16_bit():
    from photoeditor.features.flatfield.logic import apply_flatfield

    scan = _narrow_negative16()
    out = apply_flatfield(scan, np.ones((10, 10, 3), np.float32))
    assert out.dtype == np.uint16 and np.abs(out.astype(int) - scan.astype(int)).max() <= 1
    assert apply_flatfield(scan.astype(np.uint8), np.ones((4, 4, 3), np.float32)).dtype == np.uint8


def test_rendering_with_a_flat_field_keeps_every_level_of_a_narrow_range_negative():
    """The flat field used to drop the render to 8 bits first: the stretched negative then had ~40 levels instead of 256 (visible banding)."""
    from photoeditor.desktop.render import EditParams, Renderer
    from photoeditor.features.flatfield.logic import gain_token

    scan = _narrow_negative16()
    from photoeditor.desktop.session import AppState

    state = AppState()
    from photoeditor.features.negative.metering import Metering
    state.metering = Metering(engine="standard")   # the Original conversion keeps a narrow range's levels; Modern is covered by its own tests
    state.negative_inverted = True
    params = EditParams.from_state(state)
    plain = Renderer().render(scan, params, "a", scan.shape[1], want_stats=False)[0]
    gain = np.ones((10, 10, 3), np.float32)
    flat = Renderer().render(scan, params, "a", scan.shape[1], want_stats=False, flatfield=(gain_token(gain), gain))[0]
    levels = lambda im: len(np.unique(im[..., 0]))
    assert levels(plain) > 200 and levels(flat) > 200, (levels(plain), levels(flat))
    assert np.abs(flat.astype(int) - plain.astype(int)).max() <= 1
