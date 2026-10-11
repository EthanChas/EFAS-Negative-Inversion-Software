"""Export safety (one batch never overwrites its sources or another frame; unedited frames are flagged), output sharpening at final size, and 16-bit standard TIFF export."""
import dataclasses
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import cv2
import numpy as np
import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.desktop.export_worker import default_edit_state, export_photos  # noqa: E402
from photoeditor.features.export import logic as X  # noqa: E402
from photoeditor.features.export.sharpen import sharpen_output  # noqa: E402
from photoeditor.features.persistence import edit_store  # noqa: E402


def gradient16(h=60, w=1200):
    ramp = np.linspace(2000, 62000, w)[None, :, None] * np.array([1.0, 0.85, 0.7])[None, None, :]
    return np.clip(np.repeat(ramp, h, axis=0), 0, 65535).astype(np.uint16)


def write16(path, img):
    cv2.imwrite(str(path), img[..., ::-1])
    return str(path)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "e.db")
    edit_store.connect(path).close()
    return path


def test_two_photos_with_one_name_never_overwrite_each_other_in_one_batch(tmp_path, db):
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        cv2.imwrite(str(tmp_path / sub / "x.png"), np.full((30, 40, 3), 90 if sub == "a" else 180, np.uint8))
    opts = X.ExportOptions(fmt="png", dest_mode="folder", folder=str(tmp_path / "out"), on_conflict="overwrite")
    s = export_photos([str(tmp_path / "a" / "x.png"), str(tmp_path / "b" / "x.png")], [("p", opts)], db)
    assert not s["failed"] and sorted(os.listdir(tmp_path / "out")) == ["x.png", "x_1.png"], os.listdir(tmp_path / "out")
    again = export_photos([str(tmp_path / "a" / "x.png")], [("p", opts)], db)
    assert not again["failed"], "a later run may still overwrite files it made before, as the setting says"


def test_an_export_never_overwrites_a_source_even_when_told_to_overwrite(tmp_path, db):
    img = np.full((30, 40, 3), 120, np.uint8)
    srcs = []
    for n in ("one", "two"):
        p = tmp_path / f"{n}.png"
        cv2.imwrite(str(p), img)
        srcs.append(str(p))
    before = [open(p, "rb").read() for p in srcs]
    opts = X.ExportOptions(fmt="png", dest_mode="folder", folder=str(tmp_path), on_conflict="overwrite")
    s = export_photos(srcs, [("p", opts)], db)
    assert not s["failed"] and [open(p, "rb").read() for p in srcs] == before
    assert len(s["done"]) == 2 and all(d not in srcs for d in s["done"])


def test_output_sharpening_sharpens_edges_leaves_flat_areas_and_keeps_type_and_size():
    img = np.full((80, 160), 100, np.uint8)
    img[:, 80:] = 160
    img = np.repeat(img[..., None], 3, axis=2)
    assert sharpen_output(img, 0) is img
    out = sharpen_output(img, 60)
    assert out.dtype == img.dtype and out.shape == img.shape
    assert out[:, 76:80].min() < 100 and out[:, 80:84].max() > 160, "the edge gets overshoot on both sides"
    assert np.array_equal(out[:, :60], img[:, :60]) and np.array_equal(out[:, 100:], img[:, 100:]), "flat areas are untouched"
    big, small = sharpen_output(img, 100), sharpen_output(img, 20)
    assert np.abs(big.astype(int) - img).sum() > np.abs(small.astype(int) - img).sum()
    rng = np.random.default_rng(0)
    noise = np.clip(128 + rng.normal(0, 1.0, (60, 60, 3)), 0, 255).astype(np.uint8)
    assert np.abs(sharpen_output(noise, 100).astype(int) - noise).mean() < 0.2, "faint noise is not amplified"
    wide = (img.astype(np.uint16) * 257)
    ow = sharpen_output(wide, 60)
    assert ow.dtype == np.uint16 and ow[:, 80:84].max() > 160 * 257


def test_sharpening_runs_after_the_resize(tmp_path):
    img = np.zeros((200, 400, 3), np.uint8)
    img[:, 200:] = 255
    plain = X.prepare_pixels(img, X.ExportOptions(size_mode="long_edge", long_edge=100))
    sharp = X.prepare_pixels(img, X.ExportOptions(size_mode="long_edge", long_edge=100, output_sharpen=60))
    assert plain.size == sharp.size == (100, 50)
    a, b = np.asarray(plain).astype(int), np.asarray(sharp).astype(int)
    assert not np.array_equal(a, b) and b.max() >= a.max() and (b != a).any()
    assert X.ExportOptions.from_dict({"output_sharpen": 30, "bit_depth": 16}).bit_depth == 16


def test_a_16_bit_scan_exports_as_a_16_bit_tiff_with_its_profile_and_a_smooth_gradient(tmp_path, db):
    import tifffile

    src = write16(tmp_path / "scan.png", gradient16())
    state = default_edit_state(False)
    conn = edit_store.connect(db)
    edit_store.save_edit_state(conn, src, state)
    conn.close()
    opts = X.ExportOptions(fmt="tiff", bit_depth=16, dest_mode="folder", folder=str(tmp_path / "out"), tiff_compression="zip")
    s = export_photos([src], [("p", opts)], db)
    assert not s["failed"] and not s.get("notes"), s
    out = s["done"][0]
    with tifffile.TiffFile(out) as tf:
        page = tf.pages[0]
        assert page.dtype == np.uint16 and page.shape[2] == 3
        assert 34675 in page.tags, "the sRGB profile is tagged"
        data = page.asarray()
    assert len(np.unique(data[..., 1])) > 1000, "a smooth gradient keeps far more than 256 levels (one per column here)"
    eight = export_photos([src], [("p8", dataclasses.replace(opts, bit_depth=8, folder=str(tmp_path / "out8")))], db)
    assert eight["done"] and cv2.imread(eight["done"][0], cv2.IMREAD_UNCHANGED).dtype == np.uint8


def test_16_bit_falls_back_to_8_bit_and_says_why_when_an_8_bit_edit_is_on_or_the_source_is_8_bit(tmp_path, db):
    src = write16(tmp_path / "scan.png", gradient16())
    state = default_edit_state(False)
    state["sharpen_amount"] = 1.0
    conn = edit_store.connect(db)
    edit_store.save_edit_state(conn, src, state)
    conn.close()
    opts = X.ExportOptions(fmt="tiff", bit_depth=16, dest_mode="folder", folder=str(tmp_path / "o1"))
    s = export_photos([src], [("p", opts)], db)
    assert not s["failed"] and len(s["notes"]) == 1 and "8-bit" in s["notes"][0][1]
    assert cv2.imread(s["done"][0], cv2.IMREAD_UNCHANGED).dtype == np.uint8
    jpg = tmp_path / "eight.png"
    cv2.imwrite(str(jpg), np.full((30, 40, 3), 100, np.uint8))
    s2 = export_photos([str(jpg)], [("p", dataclasses.replace(opts, folder=str(tmp_path / "o2")))], db)
    assert len(s2["notes"]) == 1 and cv2.imread(s2["done"][0], cv2.IMREAD_UNCHANGED).dtype == np.uint8


def test_16_bit_with_output_sharpening_and_a_resize(tmp_path, db):
    src = write16(tmp_path / "scan.png", gradient16())
    conn = edit_store.connect(db)
    edit_store.save_edit_state(conn, src, default_edit_state(False))
    conn.close()
    opts = X.ExportOptions(fmt="tiff", bit_depth=16, dest_mode="folder", folder=str(tmp_path / "o"), size_mode="long_edge", long_edge=600, output_sharpen=40)
    s = export_photos([src], [("p", opts)], db)
    assert not s["failed"] and not s.get("notes")
    img = cv2.imread(s["done"][0], cv2.IMREAD_UNCHANGED)
    assert img.dtype == np.uint16 and img.shape[1] == 600


_UI = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.export import logic as X
    S.save({"scan_quality": False})
    folder = os.path.join(work, "roll"); os.makedirs(folder)
    paths = []
    for i in range(3):
        p = os.path.join(folder, f"f{i}.png"); cv2.imwrite(p, np.full((30, 40, 3), 60 + 40 * i, np.uint8)); paths.append(p)
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); c = win.controller
    win.open_folder(folder, prefer=paths[0])
    c.set_exposure_ev(0.5); c._save_edit_state()          # f0 edited; f1 and f2 never were
    out = os.path.join(work, "out")
    opts = X.ExportOptions(fmt="png", dest_mode="folder", folder=out)
    asked = []
    answer = {"v": "cancel"}
    win._ask_export_unedited = lambda n, t: (asked.append((n, t)), answer["v"])[1]
    def run(scope="folder"):
        win._on_export_requested(scope, [("p", opts)])
        if win._export_worker is not None:
            win._export_worker.wait(120000); app.processEvents()
    run(); assert asked == [(2, 3)] and win._export_worker is None and not os.path.exists(out), "cancel exports nothing"
    answer["v"] = "edited"; run()
    assert sorted(os.listdir(out)) == ["f0.png"], os.listdir(out)
    answer["v"] = "all"; opts.on_conflict = "overwrite"; run()
    assert sorted(os.listdir(out)) == ["f0.png", "f1.png", "f2.png"]
    asked.clear(); run("current"); assert not asked, "exporting the open photo does not ask"
    asked.clear(); run("edited"); assert not asked, "exporting only edited photos does not ask"
    win.close()
    print("EXPORT WARN OK")
''')


def test_unedited_photos_are_flagged_before_a_folder_export():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _UI], env=env, capture_output=True, text=True, timeout=300)
    assert "EXPORT WARN OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
