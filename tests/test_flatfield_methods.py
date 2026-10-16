"""The three flat-field methods (EFAS's original, NegPy's, and Improved): the maths, what is kept in the database so the method can be changed later, and the panel."""
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from photoeditor.features.flatfield import logic as F
from photoeditor.features.persistence import edit_store

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _vignette_map(h=171, w=256, edge=0.4):
    """A small linear map of a light that falls off steeply toward its borders (like a lens and a light panel together)."""
    ys = np.linspace(-1, 1, h, dtype=np.float32)[:, None]
    xs = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
    r = np.maximum(np.abs(ys), np.abs(xs))   # a rectangular falloff
    profile = 1.0 - (1.0 - edge) * np.clip((r - 0.55) / 0.45, 0, 1) ** 2
    return np.repeat(profile[..., None], 3, axis=2).astype(np.float32)


def _edge_vs_middle(ref, gain):
    a = ref * gain
    h, w = a.shape[:2]
    mid = a[h // 4:3 * h // 4, w // 4:3 * w // 4].mean()
    return {"left": a[h // 4:3 * h // 4, :w // 40].mean() / mid, "corner": a[:h // 40, :w // 40].mean() / mid}


def test_the_methods_are_named_and_a_wrong_name_falls_back_to_the_original():
    assert list(F.METHODS) == ["efas", "negpy", "improved"] and F.METHOD_DEFAULT == "improved"
    assert set(F.METHOD_NOTES) == set(F.METHODS)
    ref = _vignette_map()
    assert np.array_equal(F.gain_from_map(ref, "nonsense"), F.gain_from_map(ref, "efas"))
    assert np.array_equal(F.gain_from_map(ref), F.gain_from_map(ref, "efas")), "the default of the function is the original, so older callers get what they always got"
    rgb = (np.random.default_rng(0).random((600, 900, 3)) * 255).astype(np.uint8)
    assert np.array_equal(F.compute_gain(rgb), F.gain_from_map(F.reference_map(rgb), "efas")) and max(F.reference_map(rgb).shape[:2]) == 256


def test_improved_keeps_the_falloff_at_the_borders_that_efas_and_negpy_smooth_away():
    ref = _vignette_map()
    efas, negpy, improved = (_edge_vs_middle(ref, F.gain_from_map(ref, m)) for m in ("efas", "negpy", "improved"))
    assert efas["left"] < 0.93 and efas["corner"] < 0.9, efas
    assert abs(efas["left"] - negpy["left"]) < 0.01 and abs(efas["corner"] - negpy["corner"]) < 0.01, "NegPy's blur is the same width as EFAS's"
    assert improved["left"] > 0.96 and improved["corner"] > 0.95, improved
    assert improved["left"] > efas["left"] + 0.05 and improved["corner"] > efas["corner"] + 0.07
    for method in F.METHODS:
        gain = F.gain_from_map(ref, method)
        assert gain.shape == ref.shape and gain.dtype == np.float32 and gain.min() >= 0.25 and gain.max() <= 4.0
        assert abs(float(gain.mean()) - 1.0) < 0.15, "gains average about 1, so the picture's brightness is not moved"


def test_a_dust_filter_keeps_specks_on_the_light_out_of_the_map_but_negpy_has_none():
    ref = _vignette_map(edge=0.9)
    dusty = ref.copy()
    for y, x in ((60, 100), (90, 150), (40, 60)):
        dusty[y:y + 2, x:x + 2] *= 0.3
    worst = {m: float(np.abs(F.gain_from_map(dusty, m) / F.gain_from_map(ref, m) - 1).max()) for m in F.METHODS}
    assert worst["efas"] < 0.005 and worst["improved"] < 0.005, worst
    assert worst["negpy"] > worst["efas"] * 4, worst


def test_a_pooled_roll_reference_goes_through_the_method_too():
    rng = np.random.default_rng(2)
    light = np.clip(_vignette_map(), 0, 1)
    frames = [(np.clip(light * rng.uniform(0.3, 1.0, (1, 1, 3)) ** (1 / 2.2), 0, 1) * 255).astype(np.uint8) for _ in range(6)]
    frames = [np.repeat(np.repeat(f, 3, axis=0), 3, axis=1)[:480, :720] for f in frames]
    pooled = F.pool_reference_from_frames(frames)
    for method in F.METHODS:
        assert np.array_equal(F.pool_gain_from_frames(frames, method=method), F.gain_from_map(pooled, method))


def test_the_database_keeps_the_method_and_the_reference_and_old_rows_are_still_read(tmp_path):
    conn = edit_store.connect(str(tmp_path / "e.db"))
    ref = _vignette_map(60, 90)
    gain = F.gain_from_map(ref, "improved")
    edit_store.set_folder_flatfield(conn, "f", gain, "ref.CR2", method="improved", reference=ref)
    row = edit_store.get_folder_flatfield(conn, "f")
    assert row["method"] == "improved" and np.array_equal(row["reference"], ref) and np.array_equal(row["gain"], gain) and row["enabled"]
    edit_store.update_folder_flatfield_gain(conn, "f", F.gain_from_map(ref, "negpy"), "negpy")
    row = edit_store.get_folder_flatfield(conn, "f")
    assert row["method"] == "negpy" and np.array_equal(row["gain"], F.gain_from_map(ref, "negpy")) and np.array_equal(row["reference"], ref)
    edit_store.set_global_flatfield(conn, gain, "g.CR2", method="efas", reference=None)
    assert edit_store.get_global_flatfield(conn)["reference"] is None and edit_store.get_global_flatfield(conn)["method"] == "efas"
    edit_store.update_global_flatfield_gain(conn, F.gain_from_map(ref, "improved"), "improved")
    assert edit_store.get_global_flatfield(conn)["method"] == "improved"
    conn.close()

    # a database from before the methods existed: the tables have no method and no reference column
    old = tmp_path / "old.db"
    raw = sqlite3.connect(str(old))
    for table, key in (("folder_flatfield", "folder TEXT PRIMARY KEY"), ("global_flatfield", "id INTEGER PRIMARY KEY CHECK (id = 1)")):
        raw.execute(f"CREATE TABLE {table} ({key}, enabled INTEGER NOT NULL DEFAULT 1, source TEXT NOT NULL DEFAULT '', height INTEGER NOT NULL, width INTEGER NOT NULL, gain BLOB NOT NULL)")
    raw.execute("INSERT INTO folder_flatfield VALUES ('old', 1, 'a.CR2', 60, 90, ?)", (gain.tobytes(),))
    raw.execute("INSERT INTO global_flatfield VALUES (1, 1, 'b.CR2', 60, 90, ?)", (gain.tobytes(),))
    raw.commit()
    raw.close()
    conn = edit_store.connect(str(old))
    row = edit_store.get_folder_flatfield(conn, "old")
    assert row["method"] == "efas" and row["reference"] is None and np.array_equal(row["gain"], gain), "built the original way, nothing to rebuild from"
    assert edit_store.get_global_flatfield(conn)["method"] == "efas"
    conn.close()


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "advanced_mode": False})
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.flatfield import logic as F
    from photoeditor.features.persistence import edit_store
    h, w = 400, 600
    ys = np.linspace(-1, 1, h)[:, None]; xs = np.linspace(-1, 1, w)[None, :]
    r = np.maximum(np.abs(ys), np.abs(xs)); light = 1.0 - 0.6 * np.clip((r - 0.55) / 0.45, 0, 1) ** 2
    def save(name, scene):
        img = np.clip(light[..., None] * scene, 0, 1) ** (1 / 2.2)
        p = os.path.join(work, name); cv2.imwrite(p, (img * 255 + 0.5).astype(np.uint8)[..., ::-1]); return p
    rng = np.random.default_rng(1)
    ref = save("ref.png", np.full((h, w, 3), 0.9))
    frames = [save(f"f{i}.png", rng.uniform(0.2, 0.9, (1, 1, 3)) * np.ones((h, w, 3))) for i in range(6)]
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=frames[0]); c = win.controller
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(2)
    tool = win._flatfield_tool
    assert [tool._method.itemData(i) for i in range(3)] == ["efas", "negpy", "improved"]
    assert tool._method.currentData() == "improved" and c.flatfield_method() == "improved", "new flat fields are made the improved way by default"
    folder_key = edit_store.folder_key(frames[0])

    # a reference makes a flat field by the chosen method, and the reference is kept with it
    c.set_folder_flatfield_from_reference(ref); pump(1.0)
    row = edit_store.get_folder_flatfield(c._db, folder_key)
    assert row["method"] == "improved" and row["reference"] is not None and np.array_equal(row["gain"], F.gain_from_map(row["reference"], "improved"))
    info = c.flatfield_info()
    assert info["method"] == "improved" and info["rebuildable"] and info["method_choice"] == "improved"
    improved_gain = row["gain"].copy()

    # switching the method makes the flat field again from the kept reference, with no need to pick the reference
    tool._method.setCurrentIndex(tool._method.findData("efas")); pump(0.8)
    row = edit_store.get_folder_flatfield(c._db, folder_key)
    assert S.load()["flatfield_method"] == "efas" and row["method"] == "efas" and np.array_equal(row["gain"], F.gain_from_map(row["reference"], "efas"))
    assert not np.array_equal(row["gain"], improved_gain) and c._ff is not None
    c.set_flatfield_method("negpy"); pump(0.5)
    assert edit_store.get_folder_flatfield(c._db, folder_key)["method"] == "negpy" and tool._method.currentData() == "negpy" and "NegPy" in tool._method_note.text()

    # the open photo is corrected with the gain of the method in use: the improved one flattens the falloff more
    def edge_ratio():
        img = c.state.image_rgb.astype(np.float32); hh, ww = img.shape[:2]
        return float(img[hh // 4:3 * hh // 4, :ww // 40].mean() / img[hh // 4:3 * hh // 4, ww // 4:3 * ww // 4].mean())
    c.set_negative_inverted(False); pump(0.8)
    ratios = {}
    for m in ("efas", "improved"):
        c.set_flatfield_method(m); pump(1.0); ratios[m] = edge_ratio()
    assert ratios["improved"] > ratios["efas"] + 0.03, ratios

    # the permanent flat field and Auto (Roll) keep their reference and method too
    c.set_permanent_flatfield_from_reference(ref); pump(0.8)
    glob = edit_store.get_global_flatfield(c._db)
    assert glob["method"] == "improved" and glob["reference"] is not None
    c.clear_folder_flatfield(); pump(0.3)
    c.start_roll_flatfield()
    end = time.time() + 60
    while c._ff_worker is not None and time.time() < end: pump(0.1)
    row = edit_store.get_folder_flatfield(c._db, folder_key)
    assert row is not None and row["source"] == "Auto (Roll)" and row["method"] == "improved" and row["reference"] is not None, row and row["source"]
    c.set_flatfield_method("efas"); pump(0.5)
    assert edit_store.get_folder_flatfield(c._db, folder_key)["method"] == "efas" and edit_store.get_global_flatfield(c._db)["method"] == "efas"

    # a flat field made before the methods existed cannot be rebuilt: it stays as it is and the panel says so
    edit_store.set_folder_flatfield(c._db, folder_key, row["gain"], "old.CR2", method="efas", reference=None); pump(0.2)
    c._load_flatfield(); pump(0.2)
    c.set_flatfield_method("improved"); pump(0.5)
    kept = edit_store.get_folder_flatfield(c._db, folder_key)
    assert kept["method"] == "efas" and np.array_equal(kept["gain"], row["gain"]), "left as it was"
    assert "pick the reference again" in tool._method_note.text(), tool._method_note.text()
    win.close()
    print("OK")
""")


def test_the_panel_and_the_controller_make_and_remake_flat_fields_by_method():
    out = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=600, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-3000:]


def test_the_setting_is_kept_and_a_bad_value_falls_back(tmp_path, monkeypatch):
    from photoeditor.features.settings import logic as settings

    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    assert settings.load()["flatfield_method"] == "improved"
    settings.save({"flatfield_method": "negpy"})
    assert settings.load()["flatfield_method"] == "negpy"
    assert settings._clean({"flatfield_method": "sharpest"})["flatfield_method"] == "improved" and settings._clean({"flatfield_method": 3})["flatfield_method"] == "improved"
    pytest.importorskip("PyQt6")
