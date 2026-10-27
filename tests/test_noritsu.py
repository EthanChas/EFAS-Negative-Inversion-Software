"""The Noritsu look: a numpy port of noritsu-tool (features/negative/noritsu.py). The reference numbers are what noritsu-tool's own process_negative returns for the same synthetic scan
(a film frame with a rebate, clear margins and black scan bars), read once from its code; the port is checked against them."""
import dataclasses
import os

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from photoeditor.features.negative import noritsu as N
from photoeditor.features.negative.metering import ENGINES, Metering

SCALE = 13000.0
PIXELS = [(60, 80), (120, 300), (250, 380), (330, 600), (400, 150), (440, 700)]
FRAME = (26, 474, 26, 734)      # the film frame noritsu-tool crops to (rows, then columns)
# noritsu-tool's output at PIXELS (in the full frame) for the settings named
REFERENCE = {
    "default": [[0.1686, 0.1181, 0.1097], [0.4257, 0.3798, 0.4012], [0.562, 0.5851, 0.5818], [0.8614, 0.8582, 0.849], [0.4287, 0.452, 0.4563], [1.0, 1.0, 0.9833]],
    "lab": [[0.0081, 0.0042, 0.0037], [0.0927, 0.0673, 0.0791], [0.2522, 0.2889, 0.2837], [0.8952, 0.8903, 0.8765], [0.0965, 0.1153, 0.1188], [0.9999, 0.9999, 0.988]],
    "portra160": [[0.1946, 0.1998, 0.2211], [0.4699, 0.5063, 0.6161], [0.6288, 0.7329, 0.8509], [0.9155, 0.9457, 0.9897], [0.472, 0.5965, 0.6924], [0.9503, 0.9764, 0.9894]],
    "sat": [[0.2064, 0.118, 0.1024], [0.5, 0.4352, 0.4656], [0.6284, 0.6591, 0.6547], [0.9267, 0.9228, 0.9116], [0.4882, 0.5205, 0.5265], [1.0, 1.0, 1.0]],
}
SETTINGS = {
    "default": N.Settings(),
    "lab": N.Settings(lab=True),
    "portra160": N.Settings(stock="portra160"),
    "sat": N.Settings(contrast=1.2, toe=0.05, gamma=0.8, saturation=1.3),
}
DMIN, DMAX, GAINS = [0.2596, 0.4948, 0.7695], [1.4767, 1.9266, 2.4278], [1.0171, 1.0069, 0.9769]


def scan(seed=3, rebate=True):
    """A synthetic colour negative as density codes: black scan bars, a clear margin, a film frame (orange mask, with a rebate band) and a scene with a gradient and some texture."""
    rng = np.random.default_rng(seed)
    h, w = 500, 760
    img = np.full((h, w, 3), 0.97, np.float32)
    img[:6] = 0.001
    img[-6:] = 0.001
    img[:, :6] = 0.001
    img[:, -6:] = 0.001
    fy0, fy1, fx0, fx1 = 26, h - 26, 26, w - 26
    base = np.array([0.55, 0.32, 0.17], np.float32)
    img[fy0:fy1, fx0:fx1] = base
    pad = 20 if rebate else 0
    iy0, iy1, ix0, ix1 = fy0 + pad, fy1 - pad, fx0 + pad, fx1 - pad
    yy, xx = np.mgrid[iy0:iy1, ix0:ix1]
    g = ((xx - ix0) / (ix1 - ix0) * 0.7 + (yy - iy0) / (iy1 - iy0) * 0.3).astype(np.float32)
    dens = np.stack([0.15 + 1.1 * g ** 1.1, 0.12 + 1.35 * g, 0.10 + 1.6 * g ** 0.9], -1) + rng.normal(0, 0.02, (iy1 - iy0, ix1 - ix0, 3)).astype(np.float32)
    img[iy0:iy1, ix0:ix1] = np.clip(base * 10 ** (-np.clip(dens, 0, None)), 0.002, 1.0)
    return np.clip(np.rint(-np.log10(img) * SCALE), 0, 65535).astype(np.uint16)


def _output(codes, settings):
    plan = N.plan_from_codes(codes, None, settings, SCALE)
    lut = N.build_lut(plan, SCALE)
    out = np.stack([lut[c][codes[..., c]] for c in range(3)], -1) / 255.0
    sat = settings.effective().saturation
    if abs(sat - 1.0) > 1e-4:
        out = N.adjust_saturation(np.clip(out, 0, 1).astype(np.float32), sat)
    return plan, out


def test_the_port_gives_what_noritsu_tool_gives():
    codes = scan()
    for name, settings in SETTINGS.items():
        plan, out = _output(codes, settings)
        got = [out[r, c].tolist() for r, c in PIXELS]
        assert np.allclose(got, REFERENCE[name], atol=3e-4), (name, got)
    plan = N.plan_from_codes(codes, None, N.Settings(), SCALE)
    assert np.allclose(plan.dmin, DMIN, atol=2e-4) and np.allclose(plan.dmax, DMAX, atol=2e-4) and np.allclose(plan.gains, GAINS, atol=2e-4)
    assert N.analysis_density(codes, None, SCALE).shape[:2] == (FRAME[1] - FRAME[0], FRAME[3] - FRAME[2]), "the clear margins and the black bars are cropped away"


def test_the_rebate_gives_dmin_and_without_one_a_percentile_does():
    with_rebate = N.analysis_density(scan(), None, SCALE)
    assert N.estimate_dmin_border(with_rebate) is not None
    assert N.estimate_dmin_border(N.analysis_density(scan(rebate=False), None, SCALE)) is None


def test_tables_and_profiles():
    curve = N.load_base_tone_curve()
    assert len(curve) == 20 and curve[0] == 0.0 and curve[-1] == 1.0 and all(b >= a for a, b in zip(curve, curve[1:]))
    assert N.load_base_tone_curve("00000002")[-1] == 1.0     # (it overshoots full scale by under 0.4%: clamped)
    lut = N.tone_curve_lut()
    assert len(lut) == 4096 and abs(lut[0]) < 1e-9 and abs(lut[-1] - 1.0) < 1e-9
    for stock in N.STOCKS:
        profile = N.stock_profile(stock)
        assert profile["lut"].shape == (3, 1024) and 0.0 <= profile["lut"].min() and profile["lut"].max() <= 1.0, stock
    assert N.stock_profile("nothing") is None


def test_the_table_is_what_the_stages_do_and_a_stock_replaces_the_curve_and_the_white_balance():
    codes = scan()
    base = N.Settings()
    plan = N.plan_from_codes(codes, None, base, SCALE)
    lut = N.build_lut(plan, SCALE)
    assert lut.shape == (3, 65536) and lut.min() >= 0.0 and lut.max() <= 255.0
    assert all(np.all(np.diff(lut[c]) >= -1e-3) for c in range(3)), "a denser negative is a brighter picture, so each channel's table never falls"
    assert not np.allclose(lut, N.build_lut(N.plan_from_codes(codes, None, dataclasses.replace(base, real_curve=True), SCALE), SCALE))
    stocked = N.plan_from_codes(codes, None, dataclasses.replace(base, stock="portra400"), SCALE)
    assert stocked.gains == (1.0, 1.0, 1.0) and plan.gains != (1.0, 1.0, 1.0)
    # the contrast, toe and gamma of the synthetic curve do nothing once a stock is chosen
    other = N.build_lut(N.plan_from_codes(codes, None, dataclasses.replace(base, stock="portra400", contrast=1.4, gamma=0.7), SCALE), SCALE)
    assert np.allclose(N.build_lut(stocked, SCALE), other)


def test_a_drawn_region_is_all_that_is_read_and_a_big_scan_is_read_at_every_kth_pixel():
    codes = scan()
    region = N.analysis_density(codes, (200, 100, 500, 400), SCALE)
    assert region.shape[:2] == (300, 300)
    big = np.repeat(np.repeat(codes, 3, axis=0), 3, axis=1)      # 1500 x 2280: bigger than ANALYSIS_PIXELS allows
    assert big.shape[0] * big.shape[1] > N.ANALYSIS_PIXELS
    a = N.plan_from_codes(codes, None, N.Settings(), SCALE)
    b = N.plan_from_codes(big, None, N.Settings(), SCALE)
    assert np.allclose(a.dmin, b.dmin, atol=2e-3) and np.allclose(a.dmax, b.dmax, atol=2e-2)


def test_the_autoparam_reading_and_suggestions():
    estimate = N.estimate_neg_density(N.analysis_density(scan(), None, SCALE))
    assert estimate["classification"] == "normal" and 1.3 < estimate["density_range"] < 1.5 and estimate["details"]["border_dmin_available"]
    assert N.suggest_params(estimate, "balanced")["gamma"] == 0.98 and N.suggest_params(estimate, "punchy")["saturation"] == 1.2 and N.suggest_params(estimate, "soft")["dmax_pct"] == 99.0
    thin = {"classification": "thin", "thin_score": 0.8}
    dense = {"classification": "dense", "thin_score": 0.1}
    t, d = N.suggest_params(thin), N.suggest_params(dense)
    assert t["gamma"] == 0.74 and t["contrast"] == 0.997 and t["dmax_pct"] == 98.0 and t["confidence"] == 0.68
    assert d["gamma"] == 1.14 and d["saturation"] == 1.09 and d["dmax_pct"] == 99.8


def test_the_engine_and_its_settings_are_kept_with_the_photo():
    assert "noritsu" in ENGINES
    m = Metering(engine="noritsu", nor_stock="superia800", nor_lab=True, nor_real_curve=True, nor_contrast=1.2, nor_toe=0.05, nor_gamma=0.8, nor_sat=1.3, nor_dmin_pct=1.0, nor_dmax_pct=98.0, nor_border=False, nor_auto_wb=False)
    assert Metering.from_dict(m.to_dict()) == m
    assert Metering.from_dict({"engine": "noritsu", "nor_stock": "bogus", "nor_gamma": 99}).nor_stock == "" and Metering.from_dict({"engine": "noritsu", "nor_gamma": 99}).nor_gamma == 1.6
    assert Metering(engine="noritsu").to_dict() == {"engine": "noritsu", "transfer": "auto"}


_APP = None


def _app():
    """One QApplication for the module, kept alive (a QApplication that is not held is destroyed at once)."""
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _render(codes_scan, metering):
    _app()
    from photoeditor.desktop.render import EditParams, Renderer
    from photoeditor.desktop.session import AppState
    st = AppState()
    st.negative_inverted = True
    st.metering = metering
    params = EditParams.from_state(st)
    return Renderer().render(codes_scan, params, ("noritsu", metering), codes_scan.shape[1], None, want_stats=False, overlay=False, flatfield=None)[0]


def test_the_renderer_makes_the_positive_and_the_saturation_works():
    codes = scan()
    linear = 10.0 ** (-codes.astype(np.float64) / SCALE)
    srgb = np.where(linear <= 0.0031308, 12.92 * linear, 1.055 * linear ** (1 / 2.4) - 0.055)
    pic = np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)       # the scan as an 8-bit sRGB file
    plain = _render(pic, Metering(engine="noritsu", transfer="srgb"))
    assert plain.shape[:2] == pic.shape[:2] and plain.dtype == np.uint8
    inside = plain[120:380, 120:640].astype(float)
    left, right = inside[:, :60].mean(), inside[:, -60:].mean()
    assert right > left + 20, "the denser part of the negative (the right) is the brighter part of the positive"
    grey = _render(pic, Metering(engine="noritsu", transfer="srgb", nor_sat=0.0))
    assert np.abs(grey[..., 0].astype(int) - grey[..., 1]).max() <= 1 and np.abs(grey[..., 1].astype(int) - grey[..., 2]).max() <= 1, "saturation 0 is a grey picture"
    assert not np.array_equal(plain, _render(pic, Metering(engine="noritsu", transfer="srgb", nor_stock="portra160")))
    assert not np.array_equal(plain, _render(pic, Metering(engine="noritsu", transfer="srgb", nor_lab=True)))


def test_the_panel_shows_its_controls_for_this_conversion_only():
    _app()
    from photoeditor.desktop.view.negative_tool_panel import NegativeToolPanel
    panel = NegativeToolPanel()
    assert [panel._conversion.itemData(i) for i in range(panel._conversion.count())] == ["print", "standard", "negpy056", "noritsu"]
    m = Metering(engine="noritsu", nor_stock="portra400", nor_sat=1.2, nor_dmax_pct=98.5, nor_border=False)
    panel.set_metering(m)
    assert panel._collect() == m
    assert panel._nor_rows["nor_contrast"].isEnabled() is False      # a stock profile replaces the synthetic curve
    panel.set_metering(Metering(engine="print"))
    assert all(w.isHidden() for w in panel._nor_widgets)
    panel.show_noritsu_suggestion({"gamma": 0.8, "dmax_pct": 98.0, "contrast": 1.0, "saturation": 1.1, "toe": 0.03, "classification": "thin", "description": "x", "confidence": 0.7})
    assert panel._nor_rows["nor_gamma"].value() == 0.8 and panel._nor_rows["nor_dmax_pct"].value() == 98.0
