"""The white / black point droppers on the Negative tab: click one, click the picture, the point is set from that spot and the tool deselects."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from photoeditor.features.negative import logic as N
from photoeditor.features.negative.metering import Metering

SRC = str(Path(__file__).resolve().parents[1] / "src")


def negative(wide: bool = False, seed: int = 0) -> np.ndarray:
    """A colour-negative-looking scan: an orange cast over smooth tone with a little noise."""
    rng = np.random.default_rng(seed)
    h, w = 160, 240
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    tone = 0.25 + 0.5 * (0.5 * x / w + 0.5 * y / h)               # 0.25..0.75 of the range
    cast = np.array([0.95, 0.72, 0.5], np.float32)
    img = tone[..., None] * cast[None, None, :] + rng.normal(0, 0.004, (h, w, 3))
    top = 65535 if wide else 255
    return np.clip(img * top, 0, top).astype(np.uint16 if wide else np.uint8)


def out_at(pixels: np.ndarray, metering: Metering, x: int, y: int) -> list[float]:
    lut = N.compute_invert_lut(pixels, None, None, metering)
    top = 65535 if pixels.dtype == np.uint16 else 255
    return [float(lut[c][int(pixels[y, x, c])]) for c in range(3)] if top == 255 else [float(lut[c][int(pixels[y, x, c])]) for c in range(3)]


@pytest.mark.parametrize("wide", [False, True])
def test_the_clicked_spot_becomes_pure_white_in_every_channel(wide):
    px = negative(wide)
    floors, ceils = N.measure_reading(px, None, None, Metering())
    top = 65535.0 if wide else 255.0
    for x, y in ((20, 15), (60, 40), (100, 20)):  # three spots in the denser (darker) part of the scan: the bright part of the picture
        spot = tuple(float(px[y, x, c]) / top for c in range(3))
        new = N.point_from_pixel("white", spot, floors, ceils, Metering())
        assert new is not None and new.white != 0.0 and new.black == 0.0 and new.black_trim == (0.0, 0.0, 0.0)
        got = out_at(px, new, x, y)
        assert all(v >= 254.0 for v in got), (x, y, got)
        assert all(-1.0 <= t <= 1.0 for t in new.white_trim) and abs(new.white) <= 2.0


@pytest.mark.parametrize("wide", [False, True])
def test_the_clicked_spot_becomes_pure_black_in_every_channel(wide):
    px = negative(wide)
    floors, ceils = N.measure_reading(px, None, None, Metering())
    top = 65535.0 if wide else 255.0
    for x, y in ((200, 120), (120, 80), (170, 60)):  # the thin (lighter) part of the scan: the dark part of the picture
        spot = tuple(float(px[y, x, c]) / top for c in range(3))
        new = N.point_from_pixel("black", spot, floors, ceils, Metering())
        assert new is not None and new.black != 0.0 and new.white == 0.0
        got = out_at(px, new, x, y)
        assert all(v <= 1.0 for v in got), (x, y, got)


def test_it_keeps_the_other_metering_settings_and_the_other_point():
    px = negative()
    start = Metering(buffer=0.2, range_clip=0.5, cast_removal=0.8, black=0.3, black_trim=(0.1, 0.0, -0.1))
    floors, ceils = N.measure_reading(px, None, None, start)
    spot = tuple(float(px[30, 40, c]) / 255 for c in range(3))
    new = N.point_from_pixel("white", spot, floors, ceils, start)
    assert (new.buffer, new.range_clip, new.cast_removal, new.black, new.black_trim, new.rect) == (0.2, 0.5, 0.8, 0.3, (0.1, 0.0, -0.1), None)
    assert new.white != start.white


def test_a_spot_that_would_make_the_white_and_black_meet_is_refused():
    px = negative()
    floors, ceils = N.measure_reading(px, None, None, Metering())
    dense = tuple(float(px[5, 5, c]) / 255 for c in range(3))      # the bright end of the picture
    thin = tuple(float(px[150, 235, c]) / 255 for c in range(3))   # the dark end of the picture
    assert N.point_from_pixel("white", thin, floors, ceils, Metering()) is None, "the dark end of the picture cannot be its white point"
    assert N.point_from_pixel("black", dense, floors, ceils, Metering()) is None, "the bright end cannot be its black point"
    assert N.point_from_pixel("white", dense, floors, ceils, Metering()) is not None and N.point_from_pixel("black", thin, floors, ceils, Metering()) is not None


def test_the_reading_is_the_one_the_inversion_uses():
    px = negative(True)
    for m in (Metering(), Metering(range_clip=1.0, cast_removal=0.5, buffer=0.2)):
        floors, ceils = N.measure_reading(px, (10, 10, 200, 140), (200, 150, 100), m)
        lut = N.compute_invert_lut(px, (10, 10, 200, 140), (200, 150, 100), m)
        sample = np.arange(65536, dtype=np.float32)
        density = -np.log10(np.clip(sample / 65535.0, 1e-6, 1.0))
        for c in range(3):
            span = max(ceils[c] - floors[c], 1e-6)
            expected = np.clip((density - floors[c]) / max(ceils[c] - floors[c], 1e-6) * 255.0, 0, 255)
            assert np.allclose(lut[c], expected, atol=1e-3), (m, c)


# ------------------------------------------------------------------ the window
_SCRIPT = textwrap.dedent(r"""
    import os, sys, tempfile, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    work = tempfile.mkdtemp()
    sys.path.insert(0, SRC)
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.features.negative.metering import Metering
    S.save({"scan_quality": False})
    rng = np.random.default_rng(0)
    h, w = 300, 450
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    tone = 0.2 + 0.55 * (0.5 * x / w + 0.5 * y / h)
    img = tone[..., None] * np.array([0.5, 0.72, 0.95], np.float32)[None, None, :] + rng.normal(0, 0.004, (h, w, 3))   # BGR: orange cast
    path = os.path.join(work, "neg.png"); cv2.imwrite(path, np.clip(img * 255, 0, 255).astype(np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); c = win.controller; nt = win._negative_tool
    win.open_folder(work, prefer=path)
    def pump(s):
        end = time.time() + s
        while time.time() < end: app.processEvents(); time.sleep(0.01)
    pump(2)
    c.set_metering(Metering(engine="standard")); pump(0.5)   # the droppers belong to the Original conversion
    shown = lambda: c.state.image_rgb
    luma = lambda px: float(px.astype(np.float32).mean())

    # not inverted: a notice, nothing changes
    c.set_negative_inverted(False); pump(1.0)
    nt._droppers["white"].setChecked(True)
    assert win._point_dropper == "white" and win._image_view._label._pick_mode, "armed"
    win._on_pixel_picked(300, 100, (0, 0, 0))
    assert c.state.metering == Metering(engine="standard"), c.state.metering
    assert win._point_dropper is None and not nt._droppers["white"].isChecked(), "one click and the tool deselects"
    assert not win._image_view._label._pick_mode
    assert "Invert" in win._coord_label.text(), (win._coord_label.text(), c.state.negative_inverted)

    c.set_negative_inverted(True); pump(1.5)
    before = shown().copy()
    # white dropper on a spot well inside the lighter half
    nt._droppers["white"].setChecked(True)
    nt._droppers["black"].setChecked(True)          # one dropper at a time
    assert win._point_dropper == "black" and not nt._droppers["white"].isChecked() and nt._droppers["black"].isChecked()
    nt._droppers["white"].setChecked(True)
    assert win._point_dropper == "white" and not nt._droppers["black"].isChecked()
    sh = shown().shape
    px, py = int(sh[1] * 0.22), int(sh[0] * 0.2)
    win._on_pixel_picked(px, py, (0, 0, 0))
    pump(1.5)
    m = c.state.metering
    assert m.white != 0.0 and m.black == 0.0, m
    assert win._point_dropper is None and not nt._droppers["white"].isChecked() and not win._image_view._label._pick_mode, "the dropper is put away"
    spot = shown()[py - 1:py + 2, px - 1:px + 2].reshape(-1, 3).astype(np.float32).mean(axis=0)
    assert spot.min() >= 250, spot                  # that spot is white, in all three channels
    assert abs(nt._white.value() - m.white) < 0.02 or nt._channel.currentIndex() != 0
    assert "White point set" in win._coord_label.text()

    # black dropper on a dark spot
    nt._droppers["black"].setChecked(True)
    bx, by = int(sh[1] * 0.8), int(sh[0] * 0.75)
    win._on_pixel_picked(bx, by, (0, 0, 0)); pump(1.5)
    spot = shown()[by - 1:by + 2, bx - 1:bx + 2].reshape(-1, 3).astype(np.float32).mean(axis=0)
    assert spot.max() <= 5, spot
    assert c.state.metering.black != 0.0 and c.state.metering.white == m.white, "the white point set before is kept"

    # a spot that cannot be the white point is refused, and the tool still deselects
    keep = c.state.metering
    nt._droppers["white"].setChecked(True)
    win._on_pixel_picked(bx, by, (0, 0, 0)); pump(0.5)
    assert c.state.metering == keep and "cannot be the white point" in win._coord_label.text() and not nt._droppers["white"].isChecked()

    # with a crop on, the click still lands on the spot you pointed at
    c.reset_metering(); pump(1)
    c.set_crop_rect((90, 60, 380, 250)); pump(1.5)
    sh = shown().shape
    assert sh[1] < 450, sh
    nt._droppers["white"].setChecked(True)
    px, py = int(sh[1] * 0.25), int(sh[0] * 0.25)
    win._on_pixel_picked(px, py, (0, 0, 0)); pump(1.5)
    spot = shown()[py - 1:py + 2, px - 1:px + 2].reshape(-1, 3).astype(np.float32).mean(axis=0)
    assert spot.min() >= 250, ("cropped", spot)

    # a new photo leaves no dropper armed
    nt._droppers["black"].setChecked(True)
    win.open_folder(work, prefer=path); pump(1.5)
    assert win._point_dropper is None and not nt._droppers["black"].isChecked()
    win.close()
    print("DROPPERS OK")
    sys.stdout.flush(); os._exit(0)
""")


def test_the_droppers_in_the_window():
    script = _SCRIPT.replace("SRC", repr(SRC))
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", script], env=env, capture_output=True, text=True, timeout=300)
    assert "DROPPERS OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3500:]
