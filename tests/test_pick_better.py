"""Pick Better: choosing the better of two prints, round after round (features/pickbetter/logic.py) and the window that does it."""
import dataclasses
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.negative.metering import Metering  # noqa: E402
from photoeditor.features.pickbetter import logic as pb  # noqa: E402


def _config(**changes):
    return {**pb.read(Metering(), 0.0, 0.0), **changes}


def test_a_config_reads_from_the_photo_and_writes_back_within_the_limits():
    m = Metering(grade=0.2, density=-0.3, paper_toe=0.4, grade_trim=(0.05, 0.0, -0.1), contrast_mask=0.5)
    cfg = pb.read(m, 0.3, -0.2)
    assert cfg["grade"] == 0.2 and cfg["trim_red"] == 0.05 and cfg["trim_blue"] == -0.1 and cfg["temperature"] == 0.3 and cfg["tint"] == -0.2 and cfg["contrast_mask"] == 0.5
    back, temperature, tint = pb.write(m, cfg)
    assert back == m and (temperature, tint) == (0.3, -0.2), "reading then writing changes nothing"
    wild, t, _ = pb.write(m, {**cfg, "grade": 9.0, "trim_green": -9.0, "temperature": 5.0})
    assert wild.grade == 0.5 and wild.grade_trim[1] == -0.3 and t == 1.0, "values are held to each control's range"
    assert len(pb.PICK_PARAMS) == len(pb.KEYS) == len(set(pb.KEYS)) == len(pb.DEFAULT_ROUTE) and sorted(pb.DEFAULT_ROUTE) == list(range(len(pb.PICK_PARAMS)))


def test_a_round_is_the_picture_with_one_control_a_step_stronger_and_a_step_weaker():
    progress = pb.start()
    index, p = pb.current(progress)
    assert p.key == "grade" and progress.round_number == 1 and progress.phase == pb.FIXED
    cfg = _config(grade=0.1)
    left, right = pb.pair(cfg, progress)
    assert left["grade"] == pytest.approx(0.1 + p.strong_step) and right["grade"] == pytest.approx(0.1 - p.strong_step)
    assert all(left[k] == cfg[k] for k in cfg if k != "grade") and all(right[k] == cfg[k] for k in cfg if k != "grade"), "only the round's control differs"
    wide, _ = pb.pair(cfg, progress, 2.0)
    assert wide["grade"] == pytest.approx(0.1 + 2 * p.strong_step) or wide["grade"] == p.hi, "the Difference slider widens the step"
    top, bottom = pb.pair(_config(grade=0.5), progress)[0], pb.pair(_config(grade=-0.5), progress)[1]
    assert top["grade"] < 0.5 and bottom["grade"] > -0.5, "at a limit a candidate is moved to the open side, so a pick always moves something"


def test_the_steps_shrink_with_each_pick_and_never_below_the_floor():
    p = pb.PICK_PARAMS[0]
    steps = [pb.step_for(p, n) for n in range(12)]
    assert steps[0] == p.strong_step and steps[1] == pytest.approx(p.strong_step * 2 / 3) and steps == sorted(steps, reverse=True)
    assert steps[-1] == p.floor
    progress, cfg = pb.start(), _config()
    seen = []
    for _ in range(len(pb.DEFAULT_ROUTE) * 2):
        index, param = pb.current(progress)
        left, _right = pb.pair(cfg, progress)
        seen.append((param.key, progress.phase, round(left[param.key] - cfg[param.key], 4)))
        cfg, progress = pb.pick(cfg, progress, 0)
    keys = [k for k, _ph, _d in seen]
    assert keys[: len(pb.DEFAULT_ROUTE)] == [pb.PICK_PARAMS[i].key for i in pb.DEFAULT_ROUTE], "the first pass visits every control along the route"
    assert {ph for _k, ph, _d in seen[len(pb.DEFAULT_ROUTE):]} == {pb.REFINE}, "and then it goes round again, refining"
    first = {k: d for k, ph, d in seen if ph == pb.FIXED}
    second = {k: d for k, ph, d in seen if ph == pb.REFINE}
    assert all(abs(second[k]) <= abs(first[k]) + 1e-9 for k in first if first[k]), "the second visit is a smaller step"
    assert progress.round_number == len(pb.DEFAULT_ROUTE) * 2 + 1 and len(keys) == len(pb.DEFAULT_ROUTE) * 2


def test_picking_moves_the_picture_and_neither_keeps_it_and_does_not_shrink_the_step():
    cfg, progress = _config(), pb.start()
    left, right = pb.pair(cfg, progress)
    new, after = pb.pick(cfg, progress, 0)
    assert new == left and after.counts[0] == 1 and after.round_number == 2 and pb.current(after)[1].key == "density"
    new, after = pb.pick(cfg, progress, 1)
    assert new == right
    same, kept = pb.reject(cfg, progress)
    assert same == cfg and kept.counts == progress.counts and kept.round_number == 2, "neither is not a pick: nothing moves and the next round starts as bold"
    assert pb.summary(cfg, left, progress) == "Grade +0.15" and pb.summary(cfg, cfg, progress) == "Grade"


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile, time, dataclasses
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    work = tempfile.mkdtemp(); folder = os.path.join(work, "r"); os.makedirs(folder)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.negative.metering import Metering
    S.save({"scan_quality": False})
    g = np.linspace(40, 215, 600, dtype=np.float32)[None, :, None] * np.ones((400, 1, 3), np.float32)
    cv2.imwrite(os.path.join(folder, "a.png"), np.clip(g + np.random.default_rng(0).normal(0, 3, g.shape), 0, 255).astype(np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.resize(1500, 950); c = win.controller; win.show(); app.processEvents(); win.open_folder(folder, prefer=os.path.join(folder, "a.png"))
    def pump(secs):
        end = time.time() + secs
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(3)
    assert c.pick_better_unavailable() == "" or "Invert" in c.pick_better_unavailable()
    c.set_negative_inverted(True); pump(1.5)
    c.set_metering(Metering(engine="standard")); pump(0.5)
    assert "NegPy Conversion" in c.pick_better_unavailable(), c.pick_better_unavailable()
    c.set_metering(Metering(engine="print", transfer="srgb")); pump(1.0)
    assert c.pick_better_unavailable() == ""
    # the button is in the Negative module and opens the window
    panel = win._negative_tool
    assert not panel._pick_better_btn.isHidden()
    panel._pick_better_btn.click(); pump(1.5)
    dlg = win._pick_better
    assert dlg.isVisible() and dlg._config is not None and "Round 1: Grade" in dlg._head.text()
    assert not dlg._labels[0].pixmap().isNull() and not dlg._labels[1].pixmap().isNull(), "both prints are shown"
    left_before = dlg._pair[0]["grade"]
    start_history = len(c.state.history)
    dlg.choose(0); pump(1.5)
    assert c.state.metering.grade == dlg._history[-1][0]["grade"] + 0.15 or abs(c.state.metering.grade - left_before) < 1e-9, c.state.metering
    assert abs(c.state.metering.grade - left_before) < 1e-6 and len(c.state.history) > start_history, "the pick is an edit of the photo, with its own step in the History"
    assert "Round 2: Print density" in dlg._head.text()
    dlg.neither(); pump(1.0)
    assert "Round 3: Temperature" in dlg._head.text() and abs(c.state.metering.grade - left_before) < 1e-6
    dlg.choose(1); pump(1.5)
    assert c.state.temperature < 0.0, ("the weaker temperature was picked", c.state.temperature)
    dlg.undo(); pump(1.0)
    assert c.state.temperature == 0.0 and "Round 3" in dlg._head.text(), "undo puts the photo back"
    dlg.undo(); pump(1.0)
    assert abs(c.state.metering.grade) < 1e-9 and "Round 1" in dlg._head.text()
    dlg.close(); pump(0.3)
    print("OK pick better")
""")


def test_the_window_tunes_the_open_photo():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK pick better" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
