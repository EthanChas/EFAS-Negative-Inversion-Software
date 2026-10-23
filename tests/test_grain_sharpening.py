"""Grain Sharpening: the logic (the grain made crisper, nothing else changed), and the module in the window (saved with the photo, in presets, undoable, switchable, in the Grain Report)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import cv2
import numpy as np

from photoeditor.features.grain import logic as grain
from photoeditor.features.grainsharp import logic as G

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _scan(seed=1, level=120.0, strength=5.0, shape=(600, 900)):
    """A smooth picture with a gentle slope and grain about a pixel and a half wide."""
    rng = np.random.default_rng(seed)
    h, w = shape
    base = np.full((h, w), level, np.float32) + np.linspace(-25, 25, w, dtype=np.float32)[None, :]
    noise = cv2.GaussianBlur(rng.normal(0, 1, (h, w)).astype(np.float32), (0, 0), 0.9)
    noise /= noise.std()
    grey = np.clip(base + noise * strength, 0, 255)
    return np.dstack([grey, grey * 0.97, grey * 0.9]).astype(np.uint8)


def test_off_and_below_a_pixel_leave_the_picture_alone():
    img = _scan()
    assert G.apply_grain_sharpening(img, {"gs_amount": 0.0}) is img and G.apply_grain_sharpening(img, None) is img
    assert G.is_neutral({}) and G.is_neutral({"gs_amount": 0}) and not G.is_neutral({"gs_amount": 0.1})
    assert G.apply_grain_sharpening(img, {"gs_amount": 1.0, "gs_size": 1.2}, scale=0.2) is img, "on a preview where the grain is under a pixel there is nothing of it to sharpen"
    assert G.band_sigmas(2.0, 0.5) == (0.5, 1.6) and G.band_sigmas(99.0)[1] == G.HIGH_RATIO * G.SIZE_RANGE[1], "Size is clamped, and scaled to the picture's pixels"


def test_the_grain_gets_crisper_with_more_amount_and_nothing_else_changes():
    img = _scan()
    base = grain.measure(img)
    last = base.strength
    for amount in (0.25, 0.5, 1.0):
        out = G.apply_grain_sharpening(img, {"gs_amount": amount, "gs_size": 1.3, "gs_midtones": 0.5})
        reading = grain.measure(out)
        assert reading.strength > last, (amount, reading.strength, last)
        last = reading.strength
    assert last > 1.4 * base.strength, "a full Amount raises the grain's contrast a good deal"
    assert reading.width < base.width, "and makes it narrower: crisper"
    low = lambda p: cv2.GaussianBlur(p.astype(np.float32), (0, 0), 12)
    assert float(np.abs(low(out) - low(img)).mean()) < 0.6, "the picture's own tones, which are not grain, are not moved"
    assert np.abs(out.reshape(-1, 3).mean(0) - img.reshape(-1, 3).mean(0)).max() < 0.8, "and the colour of the picture is as it was"
    assert out.shape == img.shape and out.dtype == np.uint8


def test_a_hard_edge_is_not_given_a_halo():
    step = np.full((200, 300, 3), 60, np.uint8)
    step[:, 150:] = 200
    out = G.apply_grain_sharpening(step, {"gs_amount": 1.0, "gs_size": 1.3, "gs_midtones": 0.0}).astype(int)
    assert out.max() - 200 <= 16 and 60 - out.min() <= 16, (out.max(), out.min())


def test_midtones_favours_the_middle_tones_over_the_shadows():
    dark = _scan(seed=2, level=18.0, strength=3.0, shape=(300, 450))
    mid = _scan(seed=3, level=125.0, strength=5.0, shape=(300, 450))
    both = np.concatenate([dark, mid], axis=1)
    def raised(midtones):
        out = G.apply_grain_sharpening(both, {"gs_amount": 1.0, "gs_size": 1.3, "gs_midtones": midtones}).astype(np.float32)
        def texture(p):   # the grain's own contrast: what is left of the lightness once the slow variation is taken out
            grey = p.astype(np.float32).mean(axis=2)
            return float((grey - cv2.GaussianBlur(grey, (0, 0), 3.0)).std())
        gain = lambda a, b: texture(a) / texture(b)
        return gain(out[:, :450], both[:, :450]), gain(out[:, 450:], both[:, 450:])
    flat_dark, flat_mid = raised(0.0)
    picky_dark, picky_mid = raised(1.0)
    assert picky_dark < flat_dark and picky_mid > 1.2, "with Midtones up the shadows are left more as they were"
    assert abs(picky_mid - flat_mid) < abs(picky_dark - flat_dark) + 0.5


def test_a_tall_picture_made_in_strips_matches_one_made_whole():
    tall = _scan(shape=(1000, 500))
    values = {"gs_amount": 0.8, "gs_size": 1.6, "gs_midtones": 0.3}
    whole = G._body(tall, 0.8, *G.band_sigmas(1.6), 0.3)
    strips = G.apply_grain_sharpening(tall, values)
    assert int(np.abs(whole.astype(int) - strips.astype(int)).max()) <= 1, "the overlap between strips hides the seams"


def test_the_grain_report_calls_it_crisper_and_not_too_strong():
    names = {"grain": "Grain Sharpening", "sharpen": "Sharpening"}
    text = grain.effect_sentence(grain.DetailEffect(1.7, {"grain": 1.7, "sharpen": 1.0}), names)
    assert "Grain Sharpening" in text and "crisper" in text and "too strong" not in text and "(and the noise) stronger" not in text, text
    other = grain.effect_sentence(grain.DetailEffect(1.7, {"grain": 1.0, "sharpen": 1.7}), names)
    assert "stronger" in other and "Sharpening" in other, other
    from photoeditor.desktop.view.grain_report_dialog import GrainReportDialog

    word, sentence = GrainReportDialog.edits_word({"effect": grain.DetailEffect(1.7, {"grain": 1.7}), "effect_text": text})
    assert word == "crisper" and "crisper" in sentence
    assert GrainReportDialog.edits_word({"effect": grain.DetailEffect(1.7, {"sharpen": 1.7}), "effect_text": other})[0] == "boosting"


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.persistence import edit_store
    from photoeditor.features.grain import logic as grain
    S.save({"scan_quality": False})
    rng = np.random.default_rng(0)
    noise = cv2.GaussianBlur(rng.normal(0, 1, (600, 900)).astype(np.float32), (0, 0), 0.9); noise /= noise.std()
    grey = np.clip(150 + noise * 5.0, 0, 255)
    img = np.dstack([grey, grey, grey]).astype(np.uint8)   # a (nearly grey) negative made of nothing but grain; small enough that the preview is the scan itself
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
    s = c.state; tool = win._grainsharp_tool
    before = s.image_rgb.copy()
    strength = lambda p: grain.measure(p).strength
    assert s.gs_amount == 0.0 and tool.values()["gs_amount"] == 0.0, "off until you turn it on"

    # the panel sets it, the picture changes, the history says so
    tool._rows["gs_amount"].set_value(0.9); tool._rows["gs_size"].set_value(1.5); tool._on_value_changed(); tool._settle_timer.stop(); c.set_grain_sharpening(tool.values())
    assert pump(lambda: not np.array_equal(s.image_rgb, before)), "the grain is changed"
    assert s.gs_amount == 0.9 and s.gs_size == 1.5 and "Grain sharpening" in s.history[-1].description, s.history[-1].description
    assert strength(s.image_rgb) > 1.2 * strength(before), (strength(s.image_rgb), strength(before))

    # saved with the photo, and in the look a preset holds
    c._save_edit_state()
    saved = edit_store.load_edit_state(c._db, path)
    assert saved["gs_amount"] == 0.9 and saved["gs_size"] == 1.5
    look = c.current_look()
    assert look["gs_amount"] == 0.9 and "gs_midtones" in look
    assert c.save_look_preset("Crisp") and c.look_preset("Crisp")["gs_amount"] == 0.9

    # undo, the module's on/off light, reset to defaults
    c.undo(); app.processEvents()
    assert s.gs_amount == 0.0 and tool.values()["gs_amount"] == 0.0 and pump(lambda: np.array_equal(s.image_rgb, before)), "undo puts the grain back and the panel follows"
    assert c.apply_look_preset("Crisp") and pump(lambda: s.gs_amount == 0.9)
    assert pump(lambda: not np.array_equal(s.image_rgb, before))
    c.set_module_enabled("grainsharp", False)
    assert pump(lambda: np.array_equal(s.image_rgb, before)), "switched off: the picture is made as if the module were untouched"
    c.set_module_enabled("grainsharp", True)
    assert pump(lambda: not np.array_equal(s.image_rgb, before))
    assert c.reset_module("grainsharp") and s.gs_amount == 0.0
    assert pump(lambda: np.array_equal(s.image_rgb, before))

    # Match My Grain: Size is set from what the Grain Report measures, and says so
    width = c.measured_grain_width()
    assert width is not None and 0.6 < width < 4.0, width
    win.match_grain_size(); app.processEvents()
    assert abs(tool.values()["gs_size"] - min(max(width, 0.6), 4.0)) < 0.02 and "wide in the scan" in tool._note.text(), tool._note.text()
    assert pump(lambda: not tool._settle_timer.isActive(), secs=5.0) and abs(s.gs_size - tool.values()["gs_size"]) < 0.02, "the size is applied once the slider settles"

    # the Grain Report counts it among the modules, and with it on calls the result crisper
    c.set_grain_sharpening({"gs_amount": 1.0, "gs_size": 1.5, "gs_midtones": 0.5}); pump(secs=0.5)
    report = c.grain_report()
    assert report["ok"] and "grain" in report["effect"].by_module and report["effect"].by_module["grain"] > 1.2, report["effect"]
    assert "crisper" in report["effect_text"], report["effect_text"]
    win.close()
    print("GRAINSHARP OK")
""")


def test_grain_sharpening_in_the_window():
    done = subprocess.run([sys.executable, "-c", _SCRIPT], capture_output=True, text=True, timeout=400, env={**os.environ, "PYTHONPATH": SRC, "PHOTOEDITOR_AUDIO": "off"})
    assert "GRAINSHARP OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3000:]
