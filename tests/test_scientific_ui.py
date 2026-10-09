"""The scientific measurement wired into the editor: storage, settings, and the Advanced Mode flow end to end on a synthetic negative."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.persistence import consolidate, edit_store  # noqa: E402


def test_linear_reference_round_trip(tmp_path):
    conn = edit_store.connect(str(tmp_path / "t.db"))
    folder = edit_store.folder_key(str(tmp_path / "roll" / "a.cr2"))
    assert edit_store.get_linear_ref(conn, folder, "base") is None
    edit_store.set_linear_ref(conn, folder, "base", (0.193, 0.326, 0.153), 169)
    edit_store.set_linear_ref(conn, folder, "clear", (0.9, 0.95, 0.8), 40)
    assert edit_store.get_linear_ref(conn, folder, "base") == ((0.193, 0.326, 0.153), 169)
    edit_store.set_linear_ref(conn, folder, "base", (0.2, 0.3, 0.1), 10)
    assert edit_store.get_linear_ref(conn, folder, "base") == ((0.2, 0.3, 0.1), 10)
    assert edit_store.get_linear_ref(conn, folder, "clear")[0] == (0.9, 0.95, 0.8)
    edit_store.delete_linear_ref(conn, folder, "base")
    assert edit_store.get_linear_ref(conn, folder, "base") is None and edit_store.get_linear_ref(conn, folder, "clear") is not None
    with pytest.raises(ValueError):
        edit_store.set_linear_ref(conn, folder, "nonsense", (1, 1, 1))
    conn.close()


def test_linear_references_survive_the_data_merge(tmp_path):
    assert "folder_linear_ref" in consolidate._TABLES
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    ca, cb = edit_store.connect(str(a)), edit_store.connect(str(b))
    edit_store.set_linear_ref(ca, "roll1", "base", (0.1, 0.2, 0.3), 5)
    edit_store.set_linear_ref(cb, "roll2", "base", (0.4, 0.5, 0.6), 7)
    edit_store.set_linear_ref(cb, "roll1", "base", (0.9, 0.9, 0.9), 1)
    cb.close()
    assert consolidate._merge_db(ca, str(b))
    ca.commit()
    merged = ca
    assert edit_store.get_linear_ref(merged, "roll1", "base")[0] == (0.1, 0.2, 0.3)
    assert edit_store.get_linear_ref(merged, "roll2", "base")[0] == (0.4, 0.5, 0.6)
    merged.close()


def test_new_settings_are_validated(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    from photoeditor.features.settings import logic as s

    assert s.get("advanced_mode") is False and s.get("scan_transfer") == "srgb"
    s.save({"advanced_mode": True, "scan_transfer": "linear"})
    assert s.get("advanced_mode") is True and s.get("scan_transfer") == "linear"
    Path(s.settings_path()).write_text('{"advanced_mode": "yes", "scan_transfer": "log"}')
    assert s.get("advanced_mode") is False and s.get("scan_transfer") == "srgb"


_SCRIPT = textwrap.dedent(r'''
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    data = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_DATA_DIR"] = data
    work = tempfile.mkdtemp()
    import numpy as np
    from PIL import Image
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_transfer": "linear"})

    # A negative with known densities, stored as linear 8-bit: a clear border (the film base) and a ramp of known density above it.
    base_v = np.array([0.80, 0.60, 0.40])
    h, w = 200, 320
    net = np.concatenate([np.zeros((h, 40)), np.tile(np.linspace(0.0, 1.0, w - 40), (h, 1))], axis=1)
    v = base_v[None, None, :] * 10.0 ** -net[..., None]
    path = os.path.join(work, "neg.png")
    Image.fromarray(np.round(np.clip(v, 0, 1) * 255).astype(np.uint8)).save(path)

    app = QApplication([])
    from photoeditor.desktop.view.app_window import AppWindow
    from photoeditor.features.persistence import edit_store
    w_ = AppWindow(); c = w_.controller

    def pump(cond, secs=30):
        t = time.time()
        while time.time() - t < secs and not cond():
            QCoreApplication.processEvents(); time.sleep(0.02)
        return cond()

    c.open_file(path)
    assert c.current_measurement() is None and not c.linear_ready(), "nothing may be measured before Advanced Mode is on"
    assert not w_._advanced.isVisibleTo(w_)
    w_._negative_tool._advanced.setChecked(True)
    assert w_._advanced.isVisibleTo(w_) and S.get("advanced_mode") is True
    assert pump(lambda: c.current_measurement() is not None)
    m = c.current_measurement()
    assert not m.base.measured and m.confidence == "low" and not m.info.measured

    framed = c.framed_linear()
    assert framed.shape[:2] == c.render_raw_scan().shape[:2], "the picker image and the linear scan must be the same size"
    c.set_film_base((200, 150, 100), pick=(15, 100))
    m = c.current_measurement()
    assert m.base.measured and np.allclose(m.base.v, base_v, rtol=0.01)
    # the analysis leaves the 12% margin out, so the ramp's densest measured point is where the region ends, not its true end
    expected_top = ((w - int(w * 0.12)) - 40) / (w - 40)
    assert abs(m.dmax.value[1] - expected_top) < 0.03, (m.dmax.value, expected_top)
    ref = edit_store.get_linear_ref(c.database(), edit_store.folder_key(path), "base")
    assert ref is not None and np.allclose(ref[0], m.base.v)

    probe = c.linear_values_at(15 + 40 + 140, 100)
    from photoeditor.features.densitometry import analysis
    reading = analysis.density_at(m, probe)
    assert 0.3 < reading["above_base"][1] < 0.8, reading

    c.set_linear_reference("clear", (15, 100))
    assert all(abs(x) < 0.01 for x in c.current_measurement().dmin_abs)
    c.set_film_base(None)
    assert not c.current_measurement().base.measured
    assert edit_store.get_linear_ref(c.database(), edit_store.folder_key(path), "base") is None

    w_._negative_tool._advanced.setChecked(False)
    assert not w_._advanced.isVisibleTo(w_) and S.get("advanced_mode") is False
    w_.close()
    print("SCIENTIFIC UI OK")
''')


def test_advanced_mode_end_to_end():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=180)
    assert done.returncode == 0 and "SCIENTIFIC UI OK" in done.stdout, (done.stdout + done.stderr)[-3000:]
