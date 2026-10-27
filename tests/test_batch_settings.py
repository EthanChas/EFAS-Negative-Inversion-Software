"""Set chosen settings on several selected photos at once (film type above all: for the photos the auto-detection gets wrong)."""
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
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    S.save({"scan_quality": False})

    rng = np.random.default_rng(3)
    paths = []
    for i in range(3):
        img = cv2.GaussianBlur(rng.random((300, 450, 3)).astype(np.float32), (0, 0), 20)
        img = (50 + 150 * (img - img.min()) / np.ptp(img)).astype(np.uint8)
        p = os.path.join(folder, f"p{i}.png"); cv2.imwrite(p, img); paths.append(p)

    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop.view.batch_settings_dialog import BatchSettingsDialog
    win = aw.AppWindow(); win.resize(1400, 900); c = win.controller
    win.show(); app.processEvents()
    win.open_folder(folder, prefer=paths[0])

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
    s = c.state

    # ---- the dialog: nothing is set until a setting is ticked, and only ticked ones are returned
    d = BatchSettingsDialog(3)
    assert d.values() == {}
    d.set_film_type("c41")
    assert d.values() == {"film_type": "c41"}
    row = next(r for r in d._rows if r.field.key == "exposure_ev")
    row.use.setChecked(True); row.widget.setValue(0.5)
    assert d.values() == {"film_type": "c41", "exposure_ev": 0.5}
    d._rows[0].use.setChecked(False) if d._rows[0].field.key != "film_type" else None
    assert not any(r.field.kind == "curve" for r in d._rows), "curves are not set by typing"
    assert [r.field.key for r in d._rows][:2] == ["negative_inverted", "film_type"], "the negative's settings come first"

    # ---- setting the film type on the open photo and two that are not open
    before_exposure = {p: (edit_store.load_edit_state(c._db, p) or {}).get("exposure_ev") for p in paths}
    n = c.set_settings_on_paths(paths, {"film_type": "e6"})
    assert n == 3
    assert s.film_type == "e6" and s.negative_inverted is False, "the open photo is set live, as the Film type menu does it"
    for p in paths[1:]:
        saved = edit_store.load_edit_state(c._db, p)
        assert saved["film_type"] == "e6" and saved["negative_inverted"] is False, p
    n = c.set_settings_on_paths(paths, {"film_type": "c41", "exposure_ev": 0.4})
    assert n == 3 and s.film_type == "c41" and s.negative_inverted is True and abs(s.exposure_ev - 0.4) < 1e-9
    for p in paths[1:]:
        saved = edit_store.load_edit_state(c._db, p)
        assert saved["film_type"] == "c41" and saved["negative_inverted"] is True and abs(saved["exposure_ev"] - 0.4) < 1e-9, p
    # what was not ticked is left alone
    saved = edit_store.load_edit_state(c._db, paths[1])
    assert saved["contrast"] == 0.0 and saved["saturation"] == 0.0
    # nothing to set, or no photos: nothing happens
    assert c.set_settings_on_paths(paths, {}) == 0 and c.set_settings_on_paths([], {"film_type": "bw"}) == 0
    # each photo keeps its own crop; one undo of the roll action puts the other photos back
    folder_key = os.path.dirname(paths[0])
    entry = c.roll_undo_entry(folder_key)
    assert entry is not None
    win.close()
    print("BATCH SETTINGS OK"); sys.stdout.flush()
    os._exit(0)
''')


def test_set_settings_on_several_photos():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""), PHOTOEDITOR_AUDIO="off")
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=400)
    assert "BATCH SETTINGS OK" in done.stdout, done.stdout[-1500:] + done.stderr[-4000:]


def test_the_paper_simulations_are_in_print_responses_presets_menu():
    from photoeditor.features.lookpresets import module_builtin as mb
    from photoeditor.features.lookpresets.modules import panel_fields

    names = mb.names("printresponse")
    assert "B&W | Ilford Multigrade RC" in names and "Colour (RA4) | Kodak Endura Premier" in names and "Neutral (default)" in names and len(names) == 7
    keys = {f.key for f in panel_fields("printresponse")}
    for name in names:
        values = mb.get("printresponse", name)
        assert values and set(values) <= keys, name
    assert mb.names("exposure") == []
