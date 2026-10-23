"""The scan's encoding: the Modern conversion turns a scan's numbers back into light with the curve they were made with (a RAW file EFAS decodes: BT.709; any other file: sRGB;
or one the person picks), per photo. A photo saved before this was a setting keeps the sRGB reading it was edited with."""
import inspect

import numpy as np
import pytest

from photoeditor.features.negative import filmsim, metering as metering_mod, printengine
from photoeditor.features.negative.metering import Metering


def scene(seed=0, size=(60, 90)):
    rng = np.random.default_rng(seed)
    h, w = size
    y, x = np.mgrid[0:h, 0:w]
    base = 0.15 + 0.7 * (x / w)[..., None] * np.array([1.0, 0.9, 0.8]) + 0.1 * (y / h)[..., None]
    base[10:30, 10:30] = (0.7, 0.2, 0.15)
    base[35:55, 50:80] = (0.15, 0.5, 0.2)
    return np.clip(base + rng.normal(0, 0.01, base.shape), 0.01, 0.98)


def test_the_density_table_reads_each_encoding_the_way_it_was_made():
    codes = np.array([0.02, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8])
    curves = {
        "srgb": lambda v: np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4),
        "bt709": lambda v: np.where(v < 0.081, v / 4.5, ((v + 0.099) / 1.099) ** (1 / 0.45)),
        "linear": lambda v: v,
    }
    for transfer, to_light in curves.items():
        table = printengine.density_table(np.uint16, transfer)
        got = table[np.rint(codes * 65535).astype(int)]
        assert np.allclose(got, -np.log10(to_light(codes)), atol=2e-3), transfer
    srgb, bt709 = printengine.density_table(np.uint16, "srgb"), printengine.density_table(np.uint16, "bt709")
    at = lambda v: int(round(v * 65535))
    assert srgb[at(0.02)] - bt709[at(0.02)] == pytest.approx(0.458, abs=0.005), "reading a BT.709 scan as sRGB overstates the densest density by about 0.46"
    assert srgb[at(0.8)] - bt709[at(0.8)] == pytest.approx(0.025, abs=0.005)
    assert np.all(np.diff(bt709) <= 1e-4), "more light, less density, over the whole range"
    assert printengine.TRANSFER_CURVES == ("srgb", "bt709", "linear")


def test_a_scan_encoded_with_bt709_is_converted_as_the_scene_it_was_made_from():
    """The same scene scanned and encoded two ways converts alike only when each is read with its own curve."""
    film = filmsim.expose(scene(), filmsim.PORTRA_LIKE, 0.0)
    light = np.clip(filmsim.scan(film, encode="linear").astype(np.float64) / 65535.0, 1e-5, 1.0)   # the light the sensor measured, before any curve

    def encoded(curve):
        if curve == "bt709":
            v = np.where(light < 0.018, 4.5 * light, 1.099 * light ** 0.45 - 0.099)
        else:
            v = np.where(light <= 0.0031308, 12.92 * light, 1.055 * light ** (1 / 2.4) - 0.055)
        return np.rint(np.clip(v, 0, 1) * 65535).astype(np.uint16)

    reference = printengine.convert(encoded("srgb"), printengine.Settings(transfer="srgb")).astype(float)
    right = printengine.convert(encoded("bt709"), printengine.Settings(transfer="bt709")).astype(float)
    wrong = printengine.convert(encoded("bt709"), printengine.Settings(transfer="srgb")).astype(float)
    off_right, off_wrong = np.abs(right - reference).mean(), np.abs(wrong - reference).mean()
    assert off_right < 2.0, "each read with its own curve, the two scans of one scene convert alike"
    assert off_wrong > 2.0 * off_right, "read with the wrong curve they do not"


def test_a_metering_remembers_the_scan_encoding_and_a_photo_saved_before_it_keeps_srgb():
    assert Metering().transfer == "auto"
    for transfer in ("auto", "srgb", "bt709", "linear"):
        m = Metering(transfer=transfer)
        assert Metering.from_dict(m.to_dict()).transfer == transfer
    assert Metering.from_dict({"engine": "print"}).transfer == "srgb", "saved when every scan was read as sRGB: the look it was edited with stays"
    assert Metering.from_dict({"engine": "print", "grade": 0.2}).transfer == "srgb"
    assert Metering.from_dict(None).transfer == "auto" and Metering.from_dict("x").transfer == "auto", "nothing saved: the default"
    assert Metering.from_dict({"engine": "print", "transfer": "gamma 3"}).transfer == "auto", "an unknown encoding is the default"
    assert Metering(transfer="auto").resolved(True).transfer == "bt709" and Metering(transfer="auto").resolved(False).transfer == "srgb"
    assert Metering(transfer="linear").resolved(True).transfer == "linear" and Metering(transfer="srgb").resolved(True).transfer == "srgb", "a chosen encoding is never replaced"
    assert "scan encoding" in metering_mod.changes(Metering(), Metering(transfer="linear"))


def test_the_renderer_resolves_automatic_from_the_file_and_reads_density_with_it():
    from photoeditor.desktop.render import EditParams, print_settings

    from photoeditor.desktop.export_worker import default_edit_state

    def params(path=None, raw=None, metering=Metering()):
        d = {**default_edit_state(True), "metering": metering.to_dict() if isinstance(metering, Metering) else metering, "image_path": path}
        if raw is not None:
            d["source_raw"] = raw
        return EditParams.from_dict(d)

    assert params("a.ARW").metering.transfer == "bt709" and params("b.dng").metering.transfer == "bt709", "a RAW file EFAS decodes carries libraw's BT.709 curve"
    assert params("c.tif").metering.transfer == "srgb" and params("d.jpg").metering.transfer == "srgb" and params().metering.transfer == "srgb"
    assert params(raw=True).metering.transfer == "bt709" and params("a.ARW", raw=False).metering.transfer == "srgb", "a saved state with no path says so outright"
    assert params("a.ARW", metering=Metering(transfer="linear")).metering.transfer == "linear", "a chosen encoding wins"
    assert params("a.ARW", metering={"engine": "print"}).metering.transfer == "srgb", "a photo edited before keeps sRGB, RAW or not"
    assert print_settings(params("a.ARW").metering).transfer == "bt709" and print_settings(params("c.tif").metering).transfer == "srgb"
    assert params(metering={"engine": "print", "transfer": "auto"}, raw=True).metering.transfer == "bt709"


def test_a_look_never_carries_the_scan_encoding():
    """Pasting settings or applying a preset changes the look; how the file was encoded stays what it is for that photo."""
    from photoeditor.desktop import controller

    source = inspect.getsource(controller.AppController.apply_look) + inspect.getsource(controller.AppController.preview_look)
    assert source.count("transfer=") == 2, "both put the photo's own encoding back over the look's metering"


def test_a_raw_file_is_decoded_with_libraws_own_curve(monkeypatch, tmp_path):
    """The Modern conversion reads RAW scans as BT.709 because libraw puts that curve on a decode that is not told otherwise. If a gamma is ever passed to the decode, the
    reading in render.py (`_source_is_raw`) has to follow it."""
    from photoeditor.features.open_image import processor

    seen = {}

    class Raw:
        rgb_xyz_matrix = np.eye(3, 4)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def postprocess(self, **kwargs):
            seen.update(kwargs)
            return np.zeros((4, 6, 3), dtype=np.uint16)

    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(processor.rawpy, "imread", lambda path: Raw())
    out = processor.load_image_rgb(str(tmp_path / "frame.ARW"))
    assert out.dtype == np.uint16 and seen["output_bps"] == 16
    assert "gamma" not in seen and "output_color" not in seen, "the default curve and colour space"


_PANEL_SCRIPT = r'''
    import os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_GPU"] = "off"
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.desktop.view.negative_tool_panel import NegativeToolPanel
    from photoeditor.features.negative.metering import Metering
    p = NegativeToolPanel()
    box = p._encoding
    assert [box.itemData(i) for i in range(box.count())] == ["auto", "srgb", "bt709", "linear"] and box.currentData() == "auto", "Automatic is the default"
    got = []
    p.metering_preview.connect(got.append)
    box.setCurrentIndex(box.findData("linear"))
    assert p._metering.transfer == "linear" and got and got[-1].transfer == "linear", "choosing an encoding is a metering change"
    p.set_metering(Metering(transfer="bt709"))
    assert box.currentData() == "bt709", "the panel shows the photo's encoding"
    p.set_metering(Metering.from_dict({"engine": "print"}))
    assert box.currentData() == "srgb", "a photo edited before shows the sRGB it keeps"
    p.set_metering(Metering(engine="standard"))
    assert box.isHidden(), "Original has no use for it, so it is put away"
    p.set_metering(Metering(engine="print"))
    assert not box.isHidden()
    p.reset()
    assert box.currentData() == "auto"
    print("OK")
'''


def test_the_negative_panel_offers_the_scan_encoding():
    import os
    import subprocess
    import sys
    import textwrap
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[1] / "src")
    out = subprocess.run([sys.executable, "-c", textwrap.dedent(_PANEL_SCRIPT)], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": src})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-1500:]


def test_a_raw_negative_is_read_with_its_own_curve_end_to_end_and_an_old_photo_keeps_its_look():
    import dataclasses

    from photoeditor.desktop.render import EditParams, Renderer
    from photoeditor.desktop.session import AppState

    film = filmsim.expose(scene(4, (50, 70)), filmsim.PORTRA_LIKE, 0.0)
    light = np.clip(filmsim.scan(film, encode="linear").astype(np.float64) / 65535.0, 1e-5, 1.0)
    as_srgb = np.rint(np.where(light <= 0.0031308, 12.92 * light, 1.055 * light ** (1 / 2.4) - 0.055) * 65535).astype(np.uint16)
    as_libraw = np.rint(np.where(light < 0.018, 4.5 * light, 1.099 * light ** 0.45 - 0.099) * 65535).astype(np.uint16)

    def render(path, scan, metering=None):
        state = dataclasses.replace(AppState(), image_path=path, negative_inverted=True)
        if metering is not None:
            state = dataclasses.replace(state, metering=metering)
        return Renderer().render(scan, EditParams.from_state(state), "t", scan.shape[1])[0].astype(float)

    reference = render("frame.tif", as_srgb)                      # the scene as an sRGB scan, read as sRGB
    raw = render("frame.ARW", as_libraw)                           # the same scene as a RAW decode, read with its own curve
    misread = render("frame.tif", as_libraw)                       # the same numbers read as sRGB
    assert np.abs(raw - reference).mean() < 0.5 * np.abs(misread - reference).mean(), "reading it with its own curve brings it back toward the scene"
    old = render("frame.ARW", as_libraw, Metering.from_dict({"engine": "print"}))
    assert np.array_equal(old, misread), "a photo edited before keeps the sRGB reading it was edited with"
    chosen = render("frame.tif", as_libraw, Metering(transfer="bt709"))
    assert np.array_equal(chosen, raw), "and choosing BT.709 for a file that is not RAW does the same as a RAW file's automatic"
