"""Diffuse or Sharpen on the graphics card (features/gpu/diffuse.py): when this computer has a Vulkan card, that its picture matches the processor's (presets, the luminance mask, a picture cut into
strips), and always that the card is only used where it should be and that trouble with it gives the processor's picture."""
import numpy as np
import pytest

from photoeditor.features import gpu
from photoeditor.features.diffuse import logic as D
from photoeditor.features.gpu import device as gpu_device
from photoeditor.features.gpu import diffuse as G

pytestmark = pytest.mark.filterwarnings("ignore")


def _picture(h=420, w=520, seed=0):
    import cv2

    rng = np.random.default_rng(seed)
    base = np.zeros((h, w, 3), dtype=np.float32)
    base[:, : w // 2] = (60, 90, 140)
    base[:, w // 2:] = (190, 170, 120)
    base[h // 3: 2 * h // 3, w // 4: 3 * w // 4] = (230, 80, 70)
    base = cv2.GaussianBlur(base, (0, 0), 2.0) + rng.normal(0, 5, base.shape)
    return np.clip(base, 0, 255).astype(np.uint8)


@pytest.fixture()
def card(monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_GPU", "on")      # (the tests switch the card off by default)
    gpu.configure(enabled=True, limit=100)
    gpu_device.reset()
    if not gpu_device.available():
        pytest.skip("no Vulkan graphics card on this computer")
    yield
    gpu_device.reset()


def test_the_card_gives_the_processors_picture_for_darktables_presets(card):
    img = _picture()
    before = G.STATS["runs"]
    for name in ("sharpness | normal", "surface blur", "lens deblur | soft", "artistic effects | bloom", "denoise | fine"):
        on_card = D.apply_diffuse(img, D.PRESETS[name])
        assert G.STATS["runs"] > before, f"{name} ran on the card"
        before = G.STATS["runs"]
        on_cpu = D.apply_diffuse(img, D.PRESETS[name], use_gpu=False)
        diff = np.abs(on_card.astype(int) - on_cpu.astype(int))
        assert diff.mean() < 0.05 and diff.max() <= 2, (name, diff.mean(), diff.max())


def test_the_luminance_mask_and_the_zoom_are_the_same_on_the_card(card):
    img = _picture()
    img[100:200, 100:260] = 250
    values = {**D.PRESETS["inpaint highlights"], "dif_threshold": 0.5}
    a, b = D.apply_diffuse(img, values), D.apply_diffuse(img, values, use_gpu=False)
    assert np.abs(a.astype(int) - b.astype(int)).max() <= 2
    values = D.PRESETS["sharpness | strong"]
    a, b = D.apply_diffuse(img, values, zoom=3.0), D.apply_diffuse(img, values, zoom=3.0, use_gpu=False)
    assert np.abs(a.astype(int) - b.astype(int)).max() <= 2


def test_a_picture_too_large_for_one_pass_is_cut_into_strips_that_agree(card, monkeypatch):
    img = _picture(h=700, w=300)
    values = D.PRESETS["sharpness | normal"]
    whole = D.apply_diffuse(img, values)
    monkeypatch.setattr(G, "MAX_PIXELS", 300 * 250)
    runs = G.STATS["runs"]
    cut = D.apply_diffuse(img, values)
    assert G.STATS["runs"] - runs == 3 and np.abs(whole.astype(int) - cut.astype(int)).max() <= 2
    # with strips this short there would be more overlap than picture: the processor path takes it
    monkeypatch.setattr(G, "MAX_PIXELS", 300 * 20)
    assert G.process(img, {**D.DEFAULTS, **values}, 1.0) is None


def test_the_card_is_left_alone_when_it_should_be(monkeypatch):
    img = _picture()
    values = {**D.DEFAULTS, **D.PRESETS["sharpness | normal"]}
    assert G.process(img[:100, :100], values, 1.0) is None, "a small picture is quicker on the processor"
    assert G.process(img.astype(np.uint16), values, 1.0) is None, "only an 8-bit picture goes to the card"
    gpu.configure(enabled=False)
    try:
        assert G.process(img, values, 1.0) is None and D.apply_diffuse(img, values) is not None
    finally:
        gpu.configure(enabled=True)
    monkeypatch.setenv("PHOTOEDITOR_GPU", "off")
    assert G.process(img, values, 1.0) is None


def test_trouble_with_the_card_gives_the_processors_picture(card, monkeypatch):
    img = _picture()
    values = D.PRESETS["sharpness | fast"]
    want = D.apply_diffuse(img, values, use_gpu=False)

    def broken(*_a, **_k):
        raise RuntimeError("the driver went away")

    monkeypatch.setattr(G, "run", broken)
    out = D.apply_diffuse(img, values)
    assert np.array_equal(out, want), "the processor made the picture"
    assert not gpu_device.available(), "and the card is not used again in this run"


def test_the_records_of_the_dispatches_are_one_binding_apart():
    assert G.RECORD * 4 == 256, "a binding's offset must be a multiple of 256 bytes"
    rec = G._record(100, 50, 4, 1, (1, 2, 3, 4), (0, 1, 2, 0), 0.5, 2.0, (0.1, 0.2, 0.3, 0.4), 1.5)
    assert rec.shape == (G.RECORD,) and list(rec[:4]) == [100, 50, 4, 1] and rec[18] == 1.5 and list(rec[8:12]) == [0, 1, 2, 0]
