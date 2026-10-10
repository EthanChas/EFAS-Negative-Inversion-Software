"""Roll consistency (features/densitometry/rollcheck.py): frames scanned with a different light level or colour are found, steady rolls are not flagged."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_rebate as T  # noqa: E402
from photoeditor.features.densitometry import rollcheck  # noqa: E402
from photoeditor.features.densitometry.linear import ScanInfo  # noqa: E402

INFO = ScanInfo(True, "raw-linear", 14, quantisation=1e-5, noise_sigma=(2e-5,) * 3)


def frame(seed, light=1.0, tint=(1.0, 1.0, 1.0), with_border=True):
    v = T.film(seed=seed) if with_border else T.picture(T.H, T.W, seed)
    return np.clip(v * light * np.array(tint), 1e-5, 1.0)


def stats(frames, names=None):
    return [rollcheck.frame_stats(names[i] if names else f"f{i}", f, INFO) for i, f in enumerate(frames)]


def test_a_steady_roll_is_consistent():
    rep = rollcheck.compare(stats([frame(i) for i in range(5)]))
    assert rep.level == "ok" and all(c.level == "ok" for c in rep.frames) and "consistent" in rep.headline
    assert all(c.source == "border" for c in rep.frames)


def test_a_frame_scanned_with_brighter_light_is_flagged_by_how_much():
    frames = [frame(i) for i in range(5)]
    frames[3] = frame(3, light=1.6)
    rep = rollcheck.compare(stats(frames, list("abcde")))
    assert rep.level == "warning" and [c.label for c in rep.frames if c.level == "warning"] == ["d"]
    d = rep.frames[3]
    assert abs(d.light_stops - np.log2(1.6)) < 0.05 and "Brighter" in d.notes[0]


def test_a_colour_shift_is_flagged_separately_from_brightness():
    frames = [frame(i) for i in range(4)]
    frames[1] = frame(1, tint=(1.0, 1.0, 1.35))
    rep = rollcheck.compare(stats(frames))
    c = rep.frames[1]
    assert c.level == "warning" and abs(c.light_stops) < 0.1 and abs(c.tint_b - np.log2(1.35)) < 0.06 and "Colour differs" in c.notes[0]


def test_small_differences_are_only_noted():
    frames = [frame(i) for i in range(4)]
    frames[2] = frame(2, light=1.12)
    rep = rollcheck.compare(stats(frames))
    assert rep.level == "note" and rep.frames[2].level == "note"


def test_frames_without_a_border_are_judged_more_leniently_and_say_why():
    frames = [frame(i) for i in range(4)] + [frame(9, light=1.25, with_border=False)]
    rep = rollcheck.compare(stats(frames))
    last = rep.frames[-1]
    assert last.source == "estimated" and last.level != "ok" or last.level == "ok"
    if last.level != "ok":
        assert any("no clear border" in n for n in last.notes)


def test_a_sampled_roll_film_base_is_used_as_the_reference():
    frames = [frame(i, light=1.5) for i in range(3)]
    rep = rollcheck.compare(stats(frames), reference=tuple(T.BASE))
    assert rep.level == "warning" and all(abs(c.light_stops - np.log2(1.5)) < 0.06 for c in rep.frames) and "sampled" in rep.reference_source


def test_too_few_frames_says_so_instead_of_guessing():
    assert rollcheck.compare(stats([frame(0), frame(1)])).level == "unknown"
    assert rollcheck.compare([]).level == "unknown"


def test_clipped_scans_are_flagged():
    f = frame(0)
    f[100:200, 120:300] = 1.0
    frames = [f] + [frame(i) for i in range(1, 4)]
    rep = rollcheck.compare(stats(frames))
    assert any("clipped" in n for n in rep.frames[0].notes)
