"""The Film & Paper (Print Engine) conversion: its maths, the film simulator it is measured against, and its place in the renderer."""
import dataclasses

import numpy as np
import pytest

from photoeditor.features.negative import filmsim, printengine
from photoeditor.features.negative.metering import Metering


def scene(seed=0, size=(60, 90)):
    """A synthetic picture with smooth gradients, a few colour blocks and some noise, as sRGB 8-bit."""
    rng = np.random.default_rng(seed)
    h, w = size
    y, x = np.mgrid[0:h, 0:w]
    base = 0.15 + 0.7 * (x / w)[..., None] * np.array([1.0, 0.9, 0.8]) + 0.1 * (y / h)[..., None]
    base[10:30, 10:30] = (0.7, 0.2, 0.15)
    base[35:55, 50:80] = (0.15, 0.5, 0.2)
    return np.clip(base + rng.normal(0, 0.01, base.shape), 0.01, 0.98)


def negative_of(linear, film=filmsim.PORTRA_LIKE, stops=0.0):
    return filmsim.scan(filmsim.expose(linear, film, stops), encode="srgb")


def test_the_paper_curve_is_smooth_bounded_and_never_reverses():
    v = np.linspace(-3, 6, 400)
    d = printengine.paper(v)
    assert np.all(np.diff(d) >= 0) and d[-1] > d[0], "more straight-line density never prints lighter"
    assert d.min() >= printengine.D_MIN - 1e-9 and d.max() <= printengine.D_MAX + 1e-9
    for toe, shoulder in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1)):
        assert np.all(np.diff(printengine.paper(v, toe, shoulder)) >= 0), (toe, shoulder)
    assert abs(float(printengine.paper(printengine._V_MID)) - printengine.MID_DENSITY) < 1e-6


def test_paper_white_and_paper_black_are_the_ends_of_the_range():
    assert float(printengine.reflectance(printengine.D_MIN)) == pytest.approx(1.0)
    assert float(printengine.reflectance(printengine.D_MAX)) == pytest.approx(0.0, abs=1e-9)
    assert 0.1 < float(printengine.reflectance(printengine.MID_DENSITY)) < 0.3


def test_crosstalk_unmixing_keeps_greys_grey_and_density_codes_round_trip():
    grey = np.full((8, 8, 3), 30000, np.uint16)
    codes = printengine.density_codes(grey)
    assert codes.dtype == np.uint16 and np.ptp(codes[0, 0]) <= 2, "equal channels stay equal through the matrix"
    plain = printengine.density_codes(grey, printengine.Settings(unmix_strength=0.0))
    d = printengine.density_table(np.uint16)[30000]
    assert abs(plain[0, 0, 0] / printengine.DENSITY_SCALE - d) < 1e-3
    assert np.allclose(printengine.mixing_matrix(printengine.GENERIC_UNMIX, 1.0).sum(axis=1), 1.0)
    assert np.allclose(printengine.mixing_matrix(printengine.GENERIC_UNMIX, 0.0), np.eye(3))


def test_the_lookup_table_prints_more_exposure_lighter():
    original = scene()
    lut = printengine.build_lut(printengine.analysis_block(printengine.density_codes(negative_of(filmsim.srgb_to_linear(np.rint(original * 255).astype(np.uint8))))))
    assert lut.shape == (3, 65536) and lut.min() >= 0 and lut.max() <= 255
    for c in range(3):
        assert np.all(np.diff(lut[c]) >= -1e-3), "a denser negative (more light in the scene) never prints darker"


def test_the_engine_makes_a_positive_that_looks_like_the_scene():
    original8 = (scene() * 255).astype(np.uint8)
    lin = filmsim.srgb_to_linear(original8)
    for film in (filmsim.PORTRA_LIKE, filmsim.FLAT_FILM, filmsim.CONTRASTY_FILM):
        result = printengine.convert(negative_of(lin, film))
        assert result.shape == original8.shape and result.dtype == np.uint8
        s = filmsim.score(result, original8)
        assert s.chroma_error < 20 and s.clipped < 0.05, (film, s)
        # bright parts of the scene are bright in the print
        assert result[..., :].mean(axis=2)[:, 70:].mean() > result[..., :].mean(axis=2)[:, :20].mean()


def test_it_is_at_least_as_good_as_the_straight_stretch_on_the_simulator():
    from photoeditor.features.negative.logic import compute_invert_lut

    original8 = (scene(1) * 255).astype(np.uint8)
    lin = filmsim.srgb_to_linear(original8)
    ours, theirs = [], []
    for film in filmsim.FILMS.values():
        for stops in (-1.0, 0.0, 1.5):
            scan = negative_of(lin, film, stops)
            ours.append(filmsim.score(printengine.convert(scan), original8))
            lut = compute_invert_lut(scan)
            std = np.stack([np.clip(np.rint(lut[c][scan[..., c]]), 0, 255) for c in range(3)], axis=-1).astype(np.uint8)
            theirs.append(filmsim.score(std, original8))
    assert np.mean([s.clipped for s in ours]) <= np.mean([s.clipped for s in theirs]) + 1e-9
    assert np.mean([s.total() for s in ours]) <= np.mean([s.total() for s in theirs]) * 1.15


def test_a_sampled_film_base_is_used_and_gives_a_sensible_picture():
    lin = filmsim.srgb_to_linear((scene(2) * 255).astype(np.uint8))
    scan = negative_of(lin)
    base_codes = filmsim.scan(np.array([[list(filmsim.PORTRA_LIKE.d_min)]]), encode="srgb")[0, 0]
    with_base = printengine.convert(scan, printengine.Settings(restore=1.0), base_codes)
    without = printengine.convert(scan, printengine.Settings(restore=1.0))
    assert with_base.shape == without.shape and not np.array_equal(with_base, without)
    assert 20 < with_base.mean() < 235


def test_every_control_does_what_it_says():
    lin = filmsim.srgb_to_linear((scene(3) * 255).astype(np.uint8))
    scan = negative_of(lin)
    base = printengine.convert(scan).astype(float)
    assert printengine.convert(scan, printengine.Settings(density=0.5)).mean() < base.mean(), "more print density is darker"
    assert printengine.convert(scan, printengine.Settings(density=-0.5)).mean() > base.mean()
    harder = printengine.convert(scan, printengine.Settings(grade=0.3)).astype(float)
    softer = printengine.convert(scan, printengine.Settings(grade=-0.3)).astype(float)
    assert harder.std() > base.std() > softer.std(), "a harder grade spreads the tones"
    red_hard = printengine.convert(scan, printengine.Settings(trims=(0.3, 0.0, 0.0))).astype(float)
    red_soft = printengine.convert(scan, printengine.Settings(trims=(-0.3, 0.0, 0.0))).astype(float)
    assert red_hard[..., 0].std() > base[..., 0].std() > red_soft[..., 0].std() and abs(red_hard[..., 1].mean() - base[..., 1].mean()) < 1.0, "a layer's grade moves only that layer"
    assert printengine.convert(scan, printengine.Settings(shoulder=1.0)).max() <= base.max()
    assert printengine.convert(scan, printengine.Settings(toe=1.0)).min() >= base.min()


def test_the_simulated_film_responds_like_film():
    stops = np.linspace(-6, 6, 25)
    grey = np.full((25, 1, 3), 0.18) * (2.0 ** stops)[:, None, None]
    d = filmsim.expose(grey)
    assert np.all(np.diff(d, axis=0) > 0), "more exposure, more density"
    slope = np.diff(d[:, 0, 1])
    assert slope[len(slope) // 2] > slope[0] * 1.5 and slope[len(slope) // 2] > slope[-1] * 1.5, "S-shaped: toe and shoulder flatten the ends"
    assert d[0, 0, 2] > d[0, 0, 0], "the mask: the blue layer's base is the densest"


def test_modern_is_the_default_and_the_choice_is_always_saved():
    assert Metering().engine == "print" and Metering().to_dict() == {"engine": "print"}
    assert Metering(engine="standard").to_dict() == {"engine": "standard"}
    m = Metering(engine="print", grade=0.2, crosstalk=0.5, film_curve=0.9, density=-0.3, paper_toe=0.4, paper_shoulder=-0.2, grade_trim=(0.1, 0.0, -0.2))
    assert Metering.from_dict(m.to_dict()) == m and set(m.to_dict()) == {"engine", "grade", "crosstalk", "film_curve", "density", "paper_toe", "paper_shoulder", "grade_trim"}
    assert Metering.from_dict({"engine": "print", "grade_trim": [5, -5, 0]}).grade_trim == (0.3, -0.3, 0.0)
    original = Metering(engine="standard", range_clip=0.3)
    assert Metering.from_dict(original.to_dict()) == original
    bad = Metering.from_dict({"engine": "warp", "grade": 9, "crosstalk": "x", "density": float("nan")})
    assert bad.engine == "print" and bad.grade == 0.5 and bad.crosstalk == 1.0 and bad.density == 0.0
    assert Metering.from_dict(None).engine == "print", "a photo with nothing saved gets the default"
    assert Metering.from_dict({}).engine == "standard" and Metering.from_dict({"range_clip": 0.2}).engine == "standard", "a photo saved before Modern existed keeps Original"


def test_photos_edited_before_modern_keep_their_look_and_untouched_ones_get_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    from photoeditor.features.persistence import edit_store
    from photoeditor.features.tonecurve.logic import DEFAULT_POINTS

    conn = edit_store.connect(str(tmp_path / "t.db"))
    state = edit_store.load_edit_state(conn, "x") or None
    assert state is None
    from photoeditor.desktop.export_worker import default_edit_state

    legacy = dict(default_edit_state(True))
    legacy["metering"] = {}
    edit_store.save_edit_state(conn, "untouched.png", legacy)
    edited = dict(legacy)
    edited["exposure_ev"] = 0.5
    edit_store.save_edit_state(conn, "edited.png", edited)
    assert edit_store.load_edit_state(conn, "untouched.png")["metering"] == {"engine": "print"}, "never edited: today's default"
    assert edit_store.load_edit_state(conn, "edited.png")["metering"] == {}, "edited before Modern: stays as saved, which reads as Original"
    assert Metering.from_dict(edit_store.load_edit_state(conn, "edited.png")["metering"]).engine == "standard"
    assert edit_store.touched_paths(conn, ["untouched.png", "edited.png"], DEFAULT_POINTS) == {"edited.png"}
    modern = dict(legacy)
    modern["metering"] = {"engine": "print"}
    edit_store.save_edit_state(conn, "modern.png", modern)
    assert edit_store.touched_paths(conn, ["modern.png"], DEFAULT_POINTS) == set(), "a photo left on the default conversion is still untouched"
    tuned = dict(modern)
    tuned["metering"] = {"engine": "print", "grade": 0.1}
    edit_store.save_edit_state(conn, "tuned.png", tuned)
    assert edit_store.touched_paths(conn, ["tuned.png"], DEFAULT_POINTS) == {"tuned.png"}
    conn.close()


def test_the_dropdown_offers_modern_first_and_original_and_follows_the_photo():
    import os
    import subprocess
    import sys
    import textwrap
    from pathlib import Path

    script = textwrap.dedent(r'''
        import os, tempfile
        os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        from photoeditor.desktop.view.negative_tool_panel import NegativeToolPanel
        from photoeditor.features.negative.metering import Metering
        p = NegativeToolPanel()
        box = p._conversion
        assert [box.itemText(i) for i in range(box.count())] == ["Modern (film & paper)", "Original (stretch)"]
        assert box.currentData() == "print", "Modern is the default"
        assert all(r.isEnabled() for r in (*p._print_rows.values(), *p._trim_rows))
        got = []
        p.metering_changed.connect(got.append); p.metering_preview.connect(got.append)
        box.setCurrentIndex(box.findData("standard"))
        assert p._metering.engine == "standard" and not any(r.isEnabled() for r in (*p._print_rows.values(), *p._trim_rows)), "Original has no print controls"
        box.setCurrentIndex(box.findData("print"))
        assert not p._range.isEnabled() and not p._white.isEnabled() and not any(b.isEnabled() for b in p._droppers.values()), "Modern puts Original's stretch controls away"
        box.setCurrentIndex(box.findData("standard"))
        assert p._range.isEnabled() and p._white.isEnabled() and all(b.isEnabled() for b in p._droppers.values())
        p.set_metering(Metering(engine="print", grade=0.2))
        assert box.currentData() == "print" and abs(p._print_rows["grade"].value() - 0.2) < 1e-6
        p.set_metering(Metering(engine="standard"))
        assert box.currentData() == "standard"
        p.reset()
        assert box.currentData() == "print", "reset goes back to Modern"
        print("OK")
    ''')
    src = str(Path(__file__).resolve().parents[1] / "src")
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120, env={**os.environ, "PYTHONPATH": src})
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout[-1500:] + out.stderr[-1500:]


def test_the_renderer_uses_it_for_16_bit_8_bit_and_black_and_white_scans():
    from photoeditor.desktop.render import EditParams, Renderer
    from photoeditor.desktop.session import AppState

    lin = filmsim.srgb_to_linear((scene(4, (50, 70)) * 255).astype(np.uint8))
    scan16 = negative_of(lin)
    scan8 = (scan16 // 257).astype(np.uint8)
    default = EditParams.from_state(AppState())
    assert default.metering.engine == "print", "a new photo is converted the Modern way"
    params = dataclasses.replace(default, negative_inverted=True, metering=Metering(engine="standard"))
    printed = dataclasses.replace(params, metering=Metering(engine="print"))
    for scan in (scan16, scan8):
        a = Renderer().render(scan, params, "t", scan.shape[1])[0]
        b = Renderer().render(scan, printed, "t", scan.shape[1])[0]
        assert a.shape == b.shape == (50, 70, 3) and a.dtype == b.dtype == np.uint8
        assert np.abs(a.astype(int) - b.astype(int)).mean() > 1, "the engine changed the conversion"
        assert b.mean(axis=2)[:, 55:].mean() > b.mean(axis=2)[:, :15].mean(), "the right side of the scene is lighter"
    bw = dataclasses.replace(printed, film_type="bw")
    out = Renderer().render(scan16, bw, "t", 70)[0]
    assert np.abs(out[..., 0].astype(int) - out[..., 2].astype(int)).max() <= 3, "a black and white negative stays neutral"
    deep = Renderer().render(scan16, printed, "t", 70, deep=True)[0]
    assert deep.dtype == np.uint16 and deep.shape == (50, 70, 3)
    renderer = Renderer()
    first = renderer.render(scan16, printed, "t", 70)[0]
    again = renderer.render(scan16, printed, "t", 70)[0]
    assert np.array_equal(first, again), "the cached density image gives the same picture"
    changed = renderer.render(scan16, dataclasses.replace(printed, metering=Metering(engine="print", density=0.6)), "t", 70)[0]
    assert changed.mean() < first.mean(), "a changed control is not served from the cache"


def test_the_film_profiles_from_negpy_are_bundled_and_usable(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    found = printengine.profiles()
    bundled = [k for k, v in found.items() if v["source"] == "bundled"]
    assert len(bundled) == 16 and {"kodak_portra_400", "fujifilm_pro_400h", "kodak_ektar_100", "kodak_vision3_500t"} <= set(bundled)
    assert list(found)[:2] == ["generic", "none"], "generic and none come first in the menu"
    for key, info in found.items():
        m = np.array(info["matrix"])
        assert m.shape == (3, 3) and np.all(np.isfinite(m)), key
        assert np.allclose(printengine.mixing_matrix(m, 1.0).sum(axis=1), 1.0), key
    assert printengine.matrix_for("kodak_portra_400")[1][0] == pytest.approx(-0.129) and printengine.matrix_for("nonsense") == printengine.GENERIC_UNMIX
    assert np.allclose(printengine.mixing_matrix(printengine.matrix_for("none"), 1.0), np.eye(3))
    assert "NegPy" in open(printengine._BUNDLED + "/README.md", encoding="utf-8").read(), "the source and licence are stated next to the data"
    # a profile of the user's own
    folder = tmp_path / "crosstalk"
    folder.mkdir()
    (folder / "mine.toml").write_text('name = "My film and light"\nmatrix = [[1,-0.1,0],[-0.1,1,-0.1],[0,-0.1,1]]\n', encoding="utf-8")
    (folder / "broken.toml").write_text("matrix = [[1,2]]", encoding="utf-8")
    mine = printengine.profiles()
    assert mine["user:mine"]["name"] == "My film and light" and "user:broken" not in mine


def test_a_film_profile_changes_the_picture_and_is_kept_with_the_photo():
    lin = filmsim.srgb_to_linear((scene(5) * 255).astype(np.uint8))
    scan = negative_of(lin)
    a = printengine.convert(scan, printengine.Settings(unmix_matrix=printengine.matrix_for("kodak_ektar_100")))
    b = printengine.convert(scan, printengine.Settings(unmix_matrix=printengine.matrix_for("none")))
    assert np.abs(a.astype(int) - b.astype(int)).mean() > 0.3, "a profile with real crosstalk changes the colour"
    m = Metering(engine="print", film="kodak_portra_400")
    assert Metering.from_dict(m.to_dict()) == m and Metering().film == "generic" and "film" not in Metering().to_dict()
    from photoeditor.desktop.render import EditParams, Renderer, print_settings
    from photoeditor.desktop.session import AppState

    assert print_settings(m).unmix_matrix == printengine.matrix_for("kodak_portra_400")
    params = dataclasses.replace(EditParams.from_state(AppState()), negative_inverted=True, metering=Metering(engine="print", film="kodak_ektar_100"))
    other = dataclasses.replace(params, metering=Metering(engine="print", film="none"))
    renderer = Renderer()
    one = renderer.render(scan, params, "t", scan.shape[1])[0]
    two = renderer.render(scan, other, "t", scan.shape[1])[0]
    assert not np.array_equal(one, two), "changing the film profile is not served from the cache"
