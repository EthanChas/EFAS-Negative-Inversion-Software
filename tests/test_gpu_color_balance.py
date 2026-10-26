"""Color Balance RGB on the graphics card (features/gpu/colorbalance.py): when this computer has a Vulkan card, that its picture matches the processor's, and always that the card is only used
where it should be (darktable UCS, an 8-bit picture big enough to be worth it) and that trouble with it gives the processor's picture."""
import numpy as np
import pytest

from photoeditor.features import gpu
from photoeditor.features.colorbalancergb import logic as C
from photoeditor.features.gpu import colorbalance as G
from photoeditor.features.gpu import device as gpu_device


def _picture(h=420, w=520, seed=0):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.stack([30 + 200 * xx / w, 40 + 160 * yy / h, 220 - 180 * xx / w], axis=2) + rng.normal(0, 6, (h, w, 3))
    img[h // 3: 2 * h // 3, w // 4: 3 * w // 4] = (215, 80, 70)
    img[:20] = 3
    img[-20:] = 252
    return np.clip(img, 0, 255).astype(np.uint8)


@pytest.fixture()
def card(monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_GPU", "on")      # (the tests switch the card off by default)
    gpu.configure(enabled=True, limit=100)
    gpu_device.reset()
    if not gpu_device.available():
        pytest.skip("no Vulkan graphics card on this computer")
    yield
    gpu_device.reset()


def test_the_card_gives_the_processors_picture(card):
    img = _picture()
    cases = [C.PRESETS["basic colorfulness | standard"], C.PRESETS["basic colorfulness | vibrant colors"], {"cbr_shadows_C": 0.2, "cbr_shadows_H": 200.0},
             {"cbr_highlights_C": 0.1, "cbr_highlights_H": 60.0, "cbr_global_Y": 0.02}, {"cbr_vibrance": 0.4, "cbr_contrast": 0.2, "cbr_brilliance_global": 0.2, "cbr_hue_angle": 30.0},
             {"cbr_midtones_Y": 0.15, "cbr_midtones_C": 0.05, "cbr_midtones_H": 120.0, "cbr_white_fulcrum": 0.5}, {"cbr_saturation_global": 1.0, "cbr_chroma_global": 1.0, "cbr_brilliance_global": 0.8}]
    for values in cases:
        runs = G.STATS["runs"]
        on_card = C.apply_color_balance(img, values)
        assert G.STATS["runs"] == runs + 1, ("ran on the card", values)
        on_cpu = C.apply_color_balance(img, values, use_gpu=False)
        diff = np.abs(on_card.astype(int) - on_cpu.astype(int))
        assert diff.mean() < 0.05 and diff.max() <= 3, (values, diff.mean(), diff.max())


def test_a_picture_of_several_bands_comes_back_whole(card, monkeypatch):
    from photoeditor.features.gpu import throttle

    img = _picture(h=300, w=400)
    values = C.PRESETS["basic colorfulness | standard"]
    whole = C.apply_color_balance(img, values)
    monkeypatch.setattr(throttle.Throttle, "next_band_pixels", staticmethod(lambda *_a: 40_000))
    cut = C.apply_color_balance(img, values)
    assert np.array_equal(whole, cut), "a band at a time gives the same picture as one band"


def test_the_card_is_left_alone_when_it_should_be(monkeypatch):
    img = _picture()
    values = {**C.DEFAULTS, **C.PRESETS["basic colorfulness | standard"]}
    assert G.process(img[:100, :100], values) is None, "a small picture is quicker on the processor"
    assert G.process(img.astype(np.uint16), values) is None, "only an 8-bit picture goes to the card"
    assert G.process(img, {**values, "cbr_formula": 0.0}) is None, "JzAzBz needs double precision: the processor does it"
    assert G.parameters({**values, "cbr_formula": 0.0}) is None and G.parameters(values).shape == (G.PARAM_COUNT,)
    gpu.configure(enabled=False)
    try:
        assert G.process(img, values) is None and C.apply_color_balance(img, values) is not None
    finally:
        gpu.configure(enabled=True)
    monkeypatch.setenv("PHOTOEDITOR_GPU", "off")
    assert G.process(img, values) is None


def test_trouble_with_the_card_gives_the_processors_picture(card, monkeypatch):
    img = _picture()
    values = C.PRESETS["basic colorfulness | natural skin"]
    want = C.apply_color_balance(img, values, use_gpu=False)

    monkeypatch.setattr(G, "_program", lambda device: (_ for _ in ()).throw(RuntimeError("the driver went away")))
    out = C.apply_color_balance(img, values)
    assert np.array_equal(out, want), "the processor made the picture"
    assert not gpu_device.available(), "and the card is not used again in this run"
