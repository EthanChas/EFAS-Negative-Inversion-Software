"""Rendering on the graphics card: the throttle, the settings, the shader's layout, and - when this computer has a Vulkan card - that the card's pictures match the processor's and that
trouble with the card falls back to the processor."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from photoeditor.features import gpu
from photoeditor.features.gpu import device as gpu_device
from photoeditor.features.gpu import kernels as K
from photoeditor.features.gpu import pipeline as P
from photoeditor.features.gpu import throttle as T
from photoeditor.features.settings import logic as S

SRC = str(Path(__file__).resolve().parents[1] / "src")


# ------------------------------------------------------------------ the throttle
def test_a_limit_below_100_rests_for_the_rest_of_the_time():
    assert T.Throttle(100).rest_for(0.010) == 0.0
    assert T.Throttle(50).rest_for(0.010) == pytest.approx(0.010), "half the time: as long as it worked"
    assert T.Throttle(25).rest_for(0.010) == pytest.approx(0.030), "a quarter of the time: three times as long"
    assert T.Throttle(10).rest_for(0.5) == T.MAX_REST, "one slow band cannot freeze the render"
    assert T.Throttle(50).rest_for(0.0) == 0.0


def test_short_rests_are_saved_up_so_the_system_clock_cannot_stretch_them():
    slept = []
    t = T.Throttle(50, sleep=slept.append)
    for _ in range(3):
        assert t.after_band(0.003) == 0.0, "3 ms of rest is not worth a sleep (it would last a whole clock tick)"
    assert slept == []
    assert t.after_band(0.003) == pytest.approx(0.012) and slept == [pytest.approx(0.012)], "taken together once there is enough"
    assert t.busy == pytest.approx(0.012) and t.rested == pytest.approx(0.012)
    full = T.Throttle(100, sleep=slept.append)
    full.after_band(0.5)
    assert len(slept) == 1, "at 100% it never rests"


def test_bands_are_sized_to_take_a_few_milliseconds_each():
    assert T.Throttle.next_band_pixels(0, 0.0) == T.FIRST_BAND_PIXELS
    assert T.Throttle.next_band_pixels(262_144, 0.008) == 262_144, "just right"
    assert T.Throttle.next_band_pixels(262_144, 0.016) == 131_072, "too slow: smaller"
    assert T.Throttle.next_band_pixels(262_144, 0.0001) == T.MAX_BAND_PIXELS and T.Throttle.next_band_pixels(262_144, 5.0) == T.MIN_BAND_PIXELS


# ------------------------------------------------------------------ the settings
def test_the_limit_is_kept_between_10_and_100_and_the_card_can_be_switched_off(monkeypatch):
    gpu.configure(enabled=True, limit=100)
    try:
        gpu.configure(limit=5)
        assert gpu.limit() == 10
        gpu.configure(limit=500)
        assert gpu.limit() == 100
        gpu.configure(limit=40, enabled=False)
        assert gpu.limit() == 40 and not gpu.enabled()
        gpu.configure(enabled=True)
        monkeypatch.setenv("PHOTOEDITOR_GPU", "off")
        assert not gpu.enabled(), "the environment switch wins"
        monkeypatch.setenv("PHOTOEDITOR_GPU", "on")
        assert gpu.enabled()
    finally:
        gpu.configure(enabled=True, limit=100)


def test_the_gpu_settings_are_saved_and_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    assert S.load()["gpu_enabled"] is True and S.load()["gpu_limit"] == 100
    S.save({"gpu_enabled": False, "gpu_limit": 35})
    assert S.load()["gpu_enabled"] is False and S.load()["gpu_limit"] == 35
    S.save({"gpu_limit": 3})
    assert S.load()["gpu_limit"] == 10
    S.save({"gpu_limit": 900})
    assert S.load()["gpu_limit"] == 100
    S.save({"gpu_limit": "fast", "gpu_enabled": "yes"})
    assert S.load()["gpu_limit"] == 100 and S.load()["gpu_enabled"] is True, "a wrong-typed value falls back to the default"


def test_small_pictures_and_other_depths_never_go_to_the_card(monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_GPU", "on")
    assert not P.usable((100, 100, 3)), "too small to be worth the trip"
    assert not P.usable((1000, 1000)), "not an RGB picture"
    assert P.tone(np.zeros((1000, 1000, 3), np.uint16), saturation=0.2) is None, "only 8-bit pictures"
    monkeypatch.setenv("PHOTOEDITOR_GPU", "off")
    assert not P.usable((1000, 1000, 3)) and P.tone(np.zeros((1000, 1000, 3), np.uint8), saturation=0.2) is None


def test_the_shader_source_is_complete_and_the_layout_does_not_overlap():
    src = K.source()
    assert "$" not in src and "@compute" in src and "fn main" in src
    assert K.P_GAIN + 256 == K.PARAM_COUNT
    spans = [(K.P_SAT_K, 1), (K.P_VIG_STRENGTH, 3), (K.P_VIBRANCE, 1), (K.P_RESP_AMOUNT, 2), (K.P_RESP_CAST, 6), (K.P_TONE_COS, 3), (K.P_TONE_SIN, 3), (K.P_TONE_STRENGTH, 3),
             (K.P_M1INV, 9), (K.P_M2INV, 9), (K.P_MIX, 24), (K.P_GAIN, 256)]
    used = set()
    for start, n in spans:
        cells = set(range(start, start + n))
        assert not cells & used, (start, n)
        used |= cells
    assert max(used) < K.PARAM_COUNT
    flags = [K.F_SH, K.F_SAT, K.F_LUT, K.F_COLOR, K.F_VIG, K.F_MIX, K.F_VIB, K.F_RESP, K.F_TONING]
    assert len(set(flags)) == len(flags) and all(f & (f - 1) == 0 for f in flags)


def test_the_stages_asked_for_become_flags_the_same_way_the_cpu_decides_to_run_them():
    flags, params, table = P.tone_params()
    assert flags == 0 and table is None
    flags, params, table = P.tone_params(shadows=0.2, saturation=0.1)
    assert flags == K.F_SH | K.F_SAT and params[K.P_SAT_K] == np.float32(1.1) and params[K.P_GAIN + 255] > 0
    lut = np.tile(np.arange(256, dtype=np.uint8), (3, 1))
    flags, params, table = P.tone_params(tone_lut=lut)
    assert flags == K.F_LUT and table.shape == (768,) and table[257] == 1
    flags, *_ = P.tone_params(color=({}, "none", 1.0))
    assert flags == 0, "a neutral colour setting does nothing, as on the CPU"
    flags, params, _ = P.tone_params(color=({"vibrance": 0.3, "mix_hue_red": 0.2, "tone_amt_shadows": 0.5, "tone_hue_shadows": 90.0}, "frontier", 0.5))
    assert flags == K.F_COLOR | K.F_VIB | K.F_MIX | K.F_RESP | K.F_TONING
    assert params[K.P_VIBRANCE] == np.float32(0.3) and params[K.P_MIX] == np.float32(0.2) and params[K.P_TONE_STRENGTH] == np.float32(0.5)
    assert params[K.P_RESP_SCALE] == np.float32(1.0 + 0.5 * (1.10 - 1.0)) and params[K.P_TONE_COS] == pytest.approx(0.0, abs=1e-6) and params[K.P_TONE_SIN] == pytest.approx(1.0)
    flags, *_ = P.tone_params(color=({"tone_hue_shadows": 90.0}, "none", 1.0))
    assert flags == 0, "a toning hue with no strength changes nothing"


# ------------------------------------------------------------------ on the card (skipped on a computer without a Vulkan card)
@pytest.fixture
def card(monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_GPU", "on")
    gpu_device.reset()
    gpu.configure(enabled=True, limit=100)
    if not gpu_device.available():
        gpu_device.reset()
        pytest.skip("no usable graphics card here")
    yield gpu_device.info()
    gpu_device.reset()
    gpu.configure(enabled=True, limit=100)


def _pictures():
    rng = np.random.default_rng(3)
    h, w = 420, 563   # odd width: the bands and the last band's padding are exercised
    noise = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    grad = np.stack([xx * 255 // (w - 1), yy * 255 // (h - 1), (xx + yy) * 255 // (w + h - 2)], axis=-1).astype(np.uint8)
    prim = np.zeros((h, w, 3), np.uint8)
    prim[:, : w // 3, 0] = 255
    prim[:, w // 3: 2 * w // 3, 1] = 255
    prim[:, 2 * w // 3:, 2] = 255
    grey = np.repeat(np.linspace(0, 255, w).astype(np.uint8)[None, :, None], h, axis=0).repeat(3, axis=2)
    return {"noise": noise, "gradient": grad, "primaries": prim, "greys": grey}


def _cpu(img, shadows=0.0, highlights=0.0, saturation=0.0, tone_lut=None, color=None):
    from photoeditor.features.color.logic import adjust_saturation
    from photoeditor.features.colormix.logic import apply_color
    from photoeditor.features.lut.logic import apply_channel_lut
    from photoeditor.features.shadows_highlights.logic import adjust_shadows_highlights

    out = adjust_shadows_highlights(img, shadows, highlights)
    out = adjust_saturation(out, saturation)
    if tone_lut is not None:
        out = apply_channel_lut(out, tone_lut)
    if color is not None:
        out = apply_color(out, *color)
    return out


def _close(got, ref, label, within_one=1.0, mean=0.01):
    d = np.abs(got.astype(np.int16) - ref.astype(np.int16))
    assert (d <= 1).mean() >= within_one and d.mean() <= mean, f"{label}: max {d.max()}, mean {d.mean():.4f}, share beyond 1 level {(d > 1).mean():.6f}"


_MIX = {"vibrance": 0.3, "mix_hue_red": 0.4, "mix_sat_blue": -0.5, "mix_lum_green": 0.3, "mix_sat_orange": 0.6, "mix_hue_aqua": -0.3, "tone_hue_shadows": 220.0,
        "tone_amt_shadows": 0.4, "tone_hue_highs": 40.0, "tone_amt_highs": 0.3}
_LUT = np.stack([np.clip(np.arange(256) ** 1.1, 0, 255), np.arange(256)[::-1], np.clip(np.arange(256) * 1.2 - 10, 0, 255)]).astype(np.uint8)


def test_the_card_finds_a_vulkan_device(card):
    assert card["name"] and card["backend"] in ("Vulkan", "D3D12", "Metal"), card
    assert gpu_device.describe().startswith(card["name"])


@pytest.mark.parametrize("name", ["noise", "gradient", "primaries", "greys"])
def test_the_per_pixel_stages_on_the_card_match_the_processors(card, name):
    img = _pictures()[name]
    for label, kw, tight in (
        ("shadows and highlights", dict(shadows=0.3, highlights=-0.2), True),
        ("saturation", dict(saturation=0.25), True),
        ("tone table", dict(tone_lut=_LUT), True),
        ("vibrance and mixer", dict(color=({"vibrance": 0.3, "mix_hue_red": 0.4, "mix_sat_blue": -0.5, "mix_lum_green": 0.3}, "none", 1.0)), False),
        ("scanner response", dict(color=({}, "frontier", 0.8)), False),
        ("toning", dict(color=(_MIX, "noritsu", 0.5)), False),
        ("everything together", dict(shadows=0.2, highlights=-0.1, saturation=0.15, tone_lut=_LUT, color=(_MIX, "crystal", 1.0)), False),
    ):
        got = P.tone(img, **kw)
        assert got is not None and got.shape == img.shape and got.dtype == np.uint8, label
        # the card's arithmetic differs from numpy's in the last place: a pixel can land one level away, and in the colour work a colour right on the edge of the gamut can be
        # judged in or out differently (a few pixels in a hundred thousand)
        _close(got, _cpu(img, **kw), f"{name} {label}", within_one=1.0 if tight else 0.9995, mean=0.001 if tight else 0.02)


def test_the_vignette_on_the_card_matches_the_processors(card):
    from photoeditor.features.finishing.logic import apply_vignette

    img = _pictures()["gradient"]
    for amount, size in ((0.4, 0.5), (-0.5, 0.3), (1.0, 0.0), (-1.0, 0.9)):
        got = P.vignette(img, amount, size)
        assert got is not None
        _close(got, apply_vignette(img, amount, size), f"vignette {amount} {size}", within_one=1.0, mean=0.001)
    assert P.vignette(img, 0.0, 0.5) is None, "no vignette: nothing to do"


def test_a_picture_that_is_not_a_whole_number_of_bands_comes_back_whole(card, monkeypatch):
    monkeypatch.setattr(P, "MIN_PIXELS", 0)
    rng = np.random.default_rng(8)
    for shape in ((401, 777, 3), (1, 5000, 3), (3000, 1, 3), (7, 9999, 3)):
        img = rng.integers(0, 256, shape, dtype=np.uint8)
        got = P.tone(img, tone_lut=_LUT)
        assert got is not None and np.array_equal(got, _cpu(img, tone_lut=_LUT)), shape


def test_a_lower_limit_makes_the_card_rest_and_100_does_not(card):
    img = np.random.default_rng(1).integers(0, 256, (1500, 2000, 3), dtype=np.uint8)
    colour = ({"vibrance": 0.3, "mix_hue_red": 0.2, "mix_sat_blue": -0.2}, "none", 1.0)
    gpu.configure(limit=100)
    before = dict(P.STATS)
    assert P.tone(img, color=colour) is not None
    assert P.STATS["rested"] == before["rested"], "at 100% it never rests"
    gpu.configure(limit=20)
    before = dict(P.STATS)
    assert P.tone(img, color=colour) is not None
    busy, rested = P.STATS["busy"] - before["busy"], P.STATS["rested"] - before["rested"]
    assert rested > 0 and rested == pytest.approx(busy * 4, rel=0.5, abs=0.05), (busy, rested)


def test_any_trouble_with_the_card_hands_the_work_back_to_the_processor(card, monkeypatch):
    img = np.random.default_rng(2).integers(0, 256, (600, 700, 3), dtype=np.uint8)

    def broken(*_a, **_k):
        raise RuntimeError("the driver was reset")

    monkeypatch.setattr(P, "_run", broken)
    assert P.tone(img, saturation=0.3) is None
    assert not gpu_device.available() and "driver was reset" in gpu_device.describe(), "the card is not tried again"
    assert P.tone(img, saturation=0.3) is None and P.vignette(img, 0.3, 0.5) is None


def _params(**changes):
    from photoeditor.desktop import render as R

    base = dict(exposure_ev=0.0, tone_curve_points=((0, 0), (255, 255)), negative_inverted=False, rotation_quarter_turns=0, flip_h=False, flip_v=False, crop_rect=None, saturation=0.0,
                temperature=0.0, tint=0.0, shadows=0.0, highlights=0.0, sharpen_amount=0.0, sharpen_radius=1.0, sharpen_masking=0.0, sharpen_method="usm", dust_auto=False,
                dust_threshold=0.66, dust_size=4, scratch_lines=(), scratch_sensitivity=0.5, heal_strokes=(), film_type="auto", invert_r=0.0, invert_g=0.0, invert_b=0.0, contrast=0.0,
                fine_rotation=0.0, distortion=0.0, chroma_denoise=0.0, wm_film="off", wm_texture="plastic", wm_size="medium", wm_position="bottom_right", wm_info=False, wm_camera="",
                wm_lens="", film_base=None)
    return R.EditParams(**{**base, **changes})


def test_the_renderer_uses_the_card_for_a_big_picture_and_gets_the_same_picture(card):
    from photoeditor.desktop.render import Renderer

    img = _pictures()["gradient"]
    params = _params(saturation=0.2, shadows=0.2, highlights=-0.1, vibrance=0.3, mix_hue_red=0.3, mix_sat_blue=-0.3, vignette=0.4, exposure_ev=0.2, contrast=10.0)
    runs = P.STATS["runs"]
    on = Renderer().render(img, params, "t", img.shape[1], want_stats=False)[0]
    assert P.STATS["runs"] >= runs + 2, "the colour stages and the vignette both went to the card"
    gpu.configure(enabled=False)
    runs = P.STATS["runs"]
    off = Renderer().render(img, params, "t", img.shape[1], want_stats=False)[0]
    assert P.STATS["runs"] == runs, "switched off: the processor does it all"
    _close(on, off, "rendered picture", within_one=0.999, mean=0.02)


def test_the_renderer_still_renders_when_the_card_fails_in_the_middle(card, monkeypatch):
    from photoeditor.desktop.render import Renderer

    img = _pictures()["noise"]
    params = _params(saturation=0.2, vibrance=0.3, vignette=0.3)
    gpu.configure(enabled=False)
    expected = Renderer().render(img, params, "t", img.shape[1], want_stats=False)[0]
    gpu.configure(enabled=True)
    monkeypatch.setattr(P, "_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("out of memory")))
    got = Renderer().render(img, params, "t", img.shape[1], want_stats=False)[0]
    assert np.array_equal(got, expected), "the processor's own picture"


# ------------------------------------------------------------------ the Settings page
_SETTINGS_SCRIPT = textwrap.dedent(r"""
    import os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_GPU"] = "off"
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.features.settings import logic as S
    from photoeditor.desktop.view.settings_dialog import SettingsDialog
    S.save({"gpu_enabled": False, "gpu_limit": 40})
    d = SettingsDialog(None, None)
    titles = [d._categories.item(i).text() for i in range(d._categories.count())]
    assert "Graphics card" in titles and titles.index("Graphics card") < titles.index("Keybinds")
    assert not d._gpu_enabled.isChecked() and d._gpu_limit.value() == 40 and d._gpu_limit_label.text() == "40%"
    assert d._gpu_limit.minimum() == 10 and d._gpu_limit.maximum() == 100
    assert "PHOTOEDITOR_GPU" in d._gpu_status.text()
    d._gpu_enabled.setChecked(True); d._gpu_limit.setValue(75)
    v = d.values()
    assert v["gpu_enabled"] is True and v["gpu_limit"] == 75 and d._gpu_limit_label.text() == "75%"
    S.save(v); assert S.load()["gpu_limit"] == 75 and S.load()["gpu_enabled"] is True
    print("OK")
""")


def test_the_settings_page_has_the_switch_and_the_limit():
    out = subprocess.run([sys.executable, "-c", _SETTINGS_SCRIPT], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]


_WINDOW_SCRIPT = textwrap.dedent(r"""
    import os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"; os.environ["PHOTOEDITOR_GPU"] = "off"
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.features import gpu
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False, "gpu_limit": 30, "gpu_enabled": False})
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow()
    assert gpu.limit() == 30, "the window hands the saved limit to the render code"
    S.save({"gpu_limit": 65, "gpu_enabled": True})
    win._apply_gpu_settings()
    assert gpu.limit() == 65 and not gpu.enabled(), "(the environment switch still wins)"
    win.close()
    print("OK")
""")


def test_the_window_hands_the_saved_gpu_settings_to_the_render_code():
    out = subprocess.run([sys.executable, "-c", _WINDOW_SCRIPT], capture_output=True, text=True, timeout=180, env={**os.environ, "PYTHONPATH": SRC})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-2500:]
