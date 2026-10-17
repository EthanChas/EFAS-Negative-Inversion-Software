"""Dust and scratch repair on a 16-bit scan is made at 16 bits: a repaired patch carries the scan's own fine levels, not 256 steps pasted into it (after the inversion stretch a
negative's narrow range shows those steps as flat discs)."""
import numpy as np

from photoeditor.features.lut.logic import to_uint8
from photoeditor.features.retouch.logic import RetouchResult, remove_dust_and_scratches

SPECKS = [(200, 240), (500, 600), (660, 960), (120, 1040)]


def sky():
    """A smooth, grainy gradient that rises only about 40 eight-bit levels over the frame, with four dark specks (dust on a negative blocks light)."""
    rng = np.random.default_rng(3)
    h, w = 800, 1200
    y, x = np.mgrid[0:h, 0:w]
    base = 22000 + 9000 * (x / w) + 3000 * (y / h) + rng.normal(0, 25, (h, w))
    clean = np.clip(np.rint(np.stack([base, base * 0.9, base * 0.8], axis=2)), 0, 65535).astype(np.uint16)
    dirty = clean.copy()
    yy, xx = np.ogrid[:h, :w]
    for cy, cx in SPECKS:
        disc = (yy - cy) ** 2 + (xx - cx) ** 2 <= 4 ** 2
        dirty[disc] = np.clip(dirty[disc].astype(int) - 9000, 0, 65535)
    return clean, dirty


def test_a_16_bit_scan_is_repaired_at_16_bits():
    clean, dirty = sky()
    eight = to_uint8(dirty)
    old = remove_dust_and_scratches(eight, auto=True)           # the 8-bit repair, as it was pasted into the 16-bit scan
    new = remove_dust_and_scratches(eight, auto=True, wide=dirty)
    changed = np.any(old.pixels != eight, axis=2)
    assert changed.sum() > 200 and new.wide is not None and new.wide.dtype == np.uint16 and new.wide.shape == dirty.shape

    pasted = dirty.copy()
    pasted[changed] = old.pixels[changed].astype(np.uint16) * np.uint16(257)
    assert np.all(pasted[changed] % 257 == 0), "what pasting does: every repaired value one of 256 levels"
    assert np.mean(new.wide[changed] % 257 == 0) < 0.05, "repaired at 16 bits, the patch holds the scan's own fine levels"

    error = lambda img: np.abs(img[changed].astype(float) - clean[changed]).mean()
    assert error(new.wide) <= error(pasted) * 1.05, "and the repair is no less accurate"
    assert np.abs(dirty[changed].astype(float) - clean[changed]).mean() > 3 * error(new.wide), "the specks are really gone"


def test_everything_outside_the_repairs_is_left_exactly_as_it_was():
    _clean, dirty = sky()
    eight = to_uint8(dirty)
    new = remove_dust_and_scratches(eight, auto=True, wide=dirty)
    far = np.ones(dirty.shape[:2], bool)
    for cy, cx in SPECKS:
        far[max(0, cy - 40): cy + 40, max(0, cx - 40): cx + 40] = False
    assert np.array_equal(new.wide[far], dirty[far]), "the 16-bit scan is untouched away from the specks"
    assert np.array_equal(new.pixels[far], eight[far]), "and so is its 8-bit copy"
    near = np.any(new.pixels != eight, axis=2)
    assert np.abs(new.pixels[near].astype(int) - to_uint8(new.wide)[near].astype(int)).max() <= 1, "the 8-bit picture is the same repair, to the nearest level"


def test_a_scan_with_nothing_to_repair_comes_back_as_it_is():
    clean, _dirty = sky()
    eight = to_uint8(clean)
    result = remove_dust_and_scratches(eight, auto=True, wide=clean)
    assert result.pixels is eight and result.wide is None, "nothing found: the input itself, and no 16-bit copy to use in its place"
    assert remove_dust_and_scratches(eight, auto=False, wide=clean).pixels is eight


def test_the_renderer_uses_the_16_bit_repair_and_the_scan_when_there_is_none():
    from photoeditor.desktop.export_worker import default_edit_state
    from photoeditor.desktop.render import EditParams, Renderer

    _clean, dirty = sky()
    eight = to_uint8(dirty)
    renderer = Renderer()
    params = EditParams.from_dict({**default_edit_state(True), "dust_auto": True})
    repaired = renderer._retouched(eight, params, "frame", False, dirty)
    assert repaired.wide is not None and Renderer._retouched16(dirty, repaired) is repaired.wide
    plain = EditParams.from_dict({**default_edit_state(True), "dust_auto": False})
    untouched = renderer._retouched(eight, plain, "frame", False, dirty)
    assert untouched.pixels is eight and Renderer._retouched16(dirty, untouched) is dirty
    assert Renderer._retouched16(dirty, RetouchResult(eight)) is dirty
