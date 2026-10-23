"""Copies of a module (darktable's multiple instances): the bookkeeping, and the picture made with them - a copy is one more step after its module, with its own settings and its own mask."""
import dataclasses

import numpy as np

from photoeditor.desktop.render import EditParams, Renderer
from photoeditor.desktop.session import AppState
from photoeditor.features.instances import logic as I
from photoeditor.features.masks import blend as B
from photoeditor.features.masks import model as M
from photoeditor.features.masks import state as S

W, H = 400, 300


def _scan(seed=1):
    rng = np.random.default_rng(seed)
    base = np.linspace(40, 200, W, dtype=np.float32)[None, :, None] * np.ones((H, 1, 3), np.float32)
    return np.clip(base + rng.normal(0, 6, (H, W, 3)), 0, 255).astype(np.uint8)


def _render(scan, **kw):
    p = dataclasses.replace(EditParams.from_state(AppState()), negative_inverted=False, **kw)
    return Renderer().render(scan, p, "inst", scan.shape[1])[0].astype(int)


def test_copies_are_numbered_named_cleaned_and_taken_away():
    inst, first = I.add({}, "exposure")
    inst, second = I.add(inst, "exposure", {"exposure_ev": 0.7}, "  skin   tones ")
    assert (first, second) == (1, 2) and I.get(inst, "exposure", 2)["values"]["exposure_ev"] == 0.7 and I.get(inst, "exposure", 1)["values"] == I.defaults_of("exposure")
    assert I.title(inst, "exposure", 0) == "Exposure" and I.title(inst, "exposure", 1) == "Exposure 1" and I.title(inst, "exposure", 2) == "Exposure 2 - skin tones"
    inst = I.remove(inst, "exposure", 1)
    assert [i["id"] for i in inst["exposure"]] == [2] and I.number_of(inst, "exposure", 2) == 1, "the numbers follow the copies that are left"
    assert I.add(inst, "tonecurve")[1] == 0, "a module that cannot be copied is not"
    messy = I.clean({"exposure": [{"id": 3, "values": {"exposure_ev": 99}}, {"id": 3}, {"id": "x"}, 5], "nonsense": [{"id": 1}], "sharpening": [{"id": 1, "values": {"sharpen_method": "bogus", "sharpen_amount": 5}}]})
    assert messy["exposure"][0]["values"]["exposure_ev"] <= 3 and len(messy["exposure"]) == 1 and "nonsense" not in messy
    assert messy["sharpening"][0]["values"]["sharpen_amount"] == 1.0 and messy["sharpening"][0]["values"]["sharpen_method"] == I.defaults_of("sharpening")["sharpen_method"]
    full = {}
    for _ in range(I.MAX_INSTANCES + 2):
        full, _id = I.add(full, "contrast")
    assert len(full["contrast"]) == I.MAX_INSTANCES
    assert I.thawed(I.frozen(inst)) == {"exposure": [(2, I.get(inst, "exposure", 2)["values"])]} and hash(I.frozen(inst))


def test_a_copy_of_exposure_is_one_more_exposure_step_and_is_switched_off_by_its_light():
    scan = _scan()
    once = _render(scan, exposure_ev=1.0)
    twice = _render(scan, exposure_ev=0.5, instances=I.frozen({"exposure": [{"id": 1, "name": "", "on": True, "values": {"exposure_ev": 0.5}}]}))
    assert np.abs(once - twice).mean() < 1.5, "0.5 EV and a copy of 0.5 EV make 1 EV"
    off = _render(scan, exposure_ev=0.5, instances=I.frozen({"exposure": [{"id": 1, "name": "", "on": False, "values": {"exposure_ev": 0.5}}]}))
    assert np.abs(off - _render(scan, exposure_ev=0.5)).mean() < 0.01, "a copy that is off is not made"


def test_a_copy_has_its_own_mask_and_the_module_keeps_its_own():
    scan = _scan()
    ms = M.MaskSet()
    ms.add(M.CIRCLE, M.circle(0.3, 0.5, 0.15, 0.02))
    items = {"exposure": [{"id": 1, "name": "", "on": True, "values": {"exposure_ev": 1.2}}]}
    plain = _render(scan)
    blended = _render(scan, instances=I.frozen(items), masks_json=S.masks_json(ms.to_dict()), blends=S.blends_tuple({"exposure#1": B.Blend(mode=B.DRAWN, mask_id=1).to_dict()}))
    cy, cx = int(0.5 * H), int(0.3 * W)
    assert np.abs(blended[cy - 3:cy + 3, cx - 3:cx + 3] - plain[cy - 3:cy + 3, cx - 3:cx + 3]).mean() > 8, "inside the copy's mask it acts"
    assert np.abs(blended[:, int(0.8 * W):] - plain[:, int(0.8 * W):]).mean() < 1.0, "outside it, it does not"


def test_copies_of_the_other_modules_act_too():
    scan = _scan()
    base = _render(scan)
    for key, values in (("contrast", {"contrast": 0.6}), ("sharpening", {"sharpen_amount": 1.0}), ("shadows_highlights", {"shadows": 0.8}), ("localcontrast", {"local_contrast": 1.0}), ("colortoning", {"tone_hue_mids": 30.0, "tone_amt_mids": 1.0}),
                        ("denoise", {"chroma_denoise": 1.0}), ("halation", {"hal_amount": 1.0, "hal_threshold": 0.3}), ("grainsharp", {"gs_amount": 1.0, "gs_size": 1.5}), ("edgecolor", {"ec_light": 0.8})):
        items = {key: [{"id": 1, "name": "", "on": True, "values": values}]}
        out = _render(scan, instances=I.frozen(items))
        assert np.abs(out - base).mean() > 0.05, key
