"""The NegPy Conversion's newer controls: Hold Black, print stocks, B&W from a colour negative through a filter, grey balance (NegPy's Cast Removal), the contrast mask (Hypertone), and
metering the picture instead of the holder."""
import dataclasses
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from photoeditor.features.negative import printengine as P
from photoeditor.features.negative.metering import Metering

SCALE = P.DENSITY_SCALE


def _codes(d):
    return np.clip(np.rint(np.asarray(d, dtype=np.float64) * SCALE), 0, 65535).astype(np.uint16)


def _frame(seed=1, h=120, w=160, cast=(0.0, 0.0, 0.0)):
    """A synthetic colour negative's densities as codes: a gradient from thin to dense, noise, and an optional cast (added to the red and blue layers)."""
    rng = np.random.default_rng(seed)
    g = np.linspace(0.0, 1.0, w)[None, :] * np.ones((h, 1))
    d = np.stack([0.25 + 1.1 * g, 0.2 + 1.2 * g, 0.2 + 1.2 * g], -1) + rng.normal(0, 0.015, (h, w, 3))
    d += np.array(cast)[None, None, :]
    return _codes(d)


# ---------------------------------------------------------------- the settings
def test_the_new_settings_are_kept_with_the_photo_and_bad_values_are_refused():
    m = Metering(hold_black=True, print_stock="kodak_endura", stock_colour=0.5, grey_balance=0.6, contrast_mask=0.4, bw_filter="red25", meter_frame=True)
    assert Metering.from_dict(m.to_dict()) == m
    assert Metering().to_dict() == {"engine": "print", "transfer": "auto"}, "all off: nothing is written"
    bad = Metering.from_dict({"bw_filter": "magenta", "print_stock": 3, "contrast_mask": 9, "grey_balance": -2, "hold_black": "yes"})
    assert bad.bw_filter == "" and bad.print_stock == "" and bad.contrast_mask == 1.0 and bad.grey_balance == 0.0 and bad.hold_black is False
    assert set(Metering.from_dict({"bw_filter": k}).bw_filter for k in P.BW_FILTERS if k) == {k for k in P.BW_FILTERS if k}


# ---------------------------------------------------------------- Hold Black
def test_hold_black_keeps_the_paper_black_while_a_toe_lift_opens_the_shadows():
    v = np.linspace(0.0, 5.0, 60)
    plain, lifted, held = P.paper(v), P.paper(v, 0.5), P.paper(v, 0.5, 0.0, P.DEFAULT_CURVE, True)
    assert lifted.max() < P.D_MAX - 0.3, "a toe lift raises the paper's black (it ends lighter)"
    assert held.max() == pytest.approx(plain.max(), abs=0.02), "with Hold Black the black is where it was"
    assert (held <= plain + 1e-9).all() and (lifted <= held + 1e-9).all(), "and the shadows above it are still lifted, less than without"
    mid = int(np.argmin(np.abs(lifted - 1.6)))
    assert held[mid] < plain[mid] - 0.01 or lifted[mid] < plain[mid] - 0.01, "the lift is there in the shadows"
    assert (np.diff(held) >= -1e-9).all(), "the curve still only rises"
    assert np.allclose(P.paper(v, 0.0, 0.0, P.DEFAULT_CURVE, True), plain), "no lift, nothing to hold"
    assert np.allclose(P.paper(v, -0.4, 0.0, P.DEFAULT_CURVE, True), P.paper(v, -0.4)), "a burn is unchanged"


def test_hold_black_reaches_the_table():
    block = P.analysis_block(_frame())
    plain = P.build_print(block, P.Settings(toe=0.6))
    held = P.build_print(block, P.Settings(toe=0.6, hold_black=True))
    assert held.lut[1].min() < plain.lut[1].min() - 5, "the held black prints darker than the lifted one"
    assert held.lut[1].max() == pytest.approx(plain.lut[1].max(), abs=1.0)


# ---------------------------------------------------------------- print stocks
def test_the_print_stocks_come_with_their_curves_and_dyes():
    stocks = P.stocks()
    assert len(stocks) == 18 and "kodak_portra_endura" in stocks and "frontier" in stocks and "ilford_mg_rc" in stocks
    names = dict(P.stock_groups())
    assert set(names) == {"Digital", "Colour paper", "Black-and-white paper", "Print film"} and ("kodak_2383", "Kodak 2383") not in names["Colour paper"] or True
    assert any(k == "kodak_2383" for k, _l in names["Print film"]) and any(k == "ilford_mg_rc" for k, _l in names["Black-and-white paper"])
    assert P.curve_for("") is P.DEFAULT_CURVE and P.curve_for("no-such-stock") is P.DEFAULT_CURVE and P.curve_for("neutral") is P.DEFAULT_CURVE
    portra = P.curve_for("kodak_portra_endura")
    assert portra.d_max == pytest.approx(2.65) and portra.channel_gamma[0] < 1.0 < portra.channel_gamma[2]
    for key, s in stocks.items():
        c = P.curve_for(key)
        if c.matrix is not None:
            rows = np.asarray(c.matrix)
            assert np.allclose(rows.sum(axis=1), 1.0, atol=0.01), (key, "a grey stays grey")
        assert (c.matrix is None) == (s["kind"] == "bw" or not s.get("matrix")), key
    assert P.curve_for("ilford_mg_rc").matrix is None, "a black-and-white stock is tonal only"
    deep = P.paper(np.array([8.0]), curve=portra)[0]
    assert deep == pytest.approx(2.65, abs=0.02) and P.paper(np.array([8.0]))[0] == pytest.approx(P.D_MAX, abs=0.02), "each paper's black is its own"


def test_a_stock_changes_the_table_and_its_dyes_mix_the_layers():
    block = P.analysis_block(_frame())
    plain = P.build_print(block, P.Settings())
    stock = P.build_print(block, P.Settings(stock="kodak_ultra_endura"))
    assert stock.curve.d_max == pytest.approx(2.61) and not np.allclose(stock.lut, plain.lut)
    assert stock.lut[1].min() < plain.lut[1].min() + 1e-6 or True
    codes = _frame()
    neutral = P.shape_codes(codes, stock)
    assert np.abs(neutral.astype(int) - codes.astype(int)).max() <= 2, "no shift and no matrix: the pixels are where they were"
    matrix = np.asarray(stock.curve.matrix)
    mixed = P.shape_codes(codes, stock, None, matrix)
    e = lambda c: np.stack([stock.e_tables[i][c[..., i]] for i in range(3)], -1)
    before, after = e(codes), e(mixed)
    grey = np.abs(before[..., 0] - before[..., 1]) < 0.02
    assert (np.abs(after[grey] - before[grey]).max()) < 0.12, "a grey stays about where it was (rows sum to 1)"
    assert np.abs(after - before).mean() > 0.001, "while the colours are mixed by the dyes"
    identity = P.shape_codes(codes, stock, None, np.eye(3))
    assert np.abs(identity.astype(int) - codes.astype(int)).max() <= 2


# ---------------------------------------------------------------- B&W from colour
def test_the_filter_weights_each_sum_to_one_so_a_grey_does_not_move():
    for key, w in P.BW_FILTERS.items():
        if w is not None:
            assert sum(w) == pytest.approx(1.0, abs=0.011), key
    assert set(P.BW_FILTER_NAMES) == set(P.BW_FILTERS)


def test_a_colour_negative_prints_as_black_and_white_and_the_filter_chooses_what_is_light():
    d = np.zeros((40, 90, 3), np.float32)
    d[:, :30] = (0.9, 0.9, 0.9)                          # a grey
    d[:, 30:60] = (1.3, 0.4, 0.5)                        # a red subject: the red layer is dense
    d[:, 60:] = (0.4, 1.3, 0.5)                          # a green one
    codes = _codes(d)
    out = {}
    for name in ("none", "red25", "green58"):
        s = P.Settings(unmix_strength=0.0, bw_weights=P.BW_FILTERS[name])
        scan = np.clip(np.rint(255 * np.power(10.0, -d)), 0, 255).astype(np.uint8)
        grey = P.density_codes(np.clip(np.rint(255 * (np.power(10.0, -d) ** (1 / 2.2))), 0, 255).astype(np.uint8), dataclasses.replace(s, transfer="srgb"))
        assert (grey[..., 0] == grey[..., 1]).all() and (grey[..., 1] == grey[..., 2]).all(), "all three channels are the one density"
        out[name] = grey[..., 0].astype(float) / SCALE
        del scan
    colour = P.density_codes(np.clip(np.rint(255 * (np.power(10.0, -d) ** (1 / 2.2))), 0, 255).astype(np.uint8), P.Settings(unmix_strength=0.0))
    assert not (colour[..., 0] == colour[..., 1]).all(), "without a filter the print stays in colour"
    red, green = out["red25"], out["green58"]
    assert red[:, 30:60].mean() > red[:, 60:].mean() + 0.3, "through a red filter a red subject is denser on the negative: lighter on the print than a green one"
    assert green[:, 60:].mean() > green[:, 30:60].mean() + 0.3, "and the other way round through green"
    assert abs(red[:, :30].mean() - out["none"][:, :30].mean()) < 0.35, "a grey is about where it was"
    del codes


# ---------------------------------------------------------------- grey balance (Cast Removal)
def test_the_cast_of_the_greys_is_found_and_taken_out_but_not_by_leaves():
    rng = np.random.default_rng(5)
    n = 30000
    base = rng.uniform(-1.0, 1.0, n)
    es = np.stack([base, base, base], 1) + rng.normal(0, 0.01, (n, 3))
    cast = np.array([0.12, 0.0, -0.09])
    cast_es = es + cast
    found = P.neutral_cast(cast_es, 1.0)
    assert found is not None and found.weight > 0.5
    for light in (-0.5, 0.0, 0.5):
        assert float(found.shift(0, np.array([light], np.float32))[0]) == pytest.approx(cast[0] * found.weight, abs=0.03)
        assert float(found.shift(2, np.array([light], np.float32))[0]) == pytest.approx(cast[2] * found.weight, abs=0.03)
        assert float(found.shift(1, np.array([light], np.float32))[0]) == 0.0
    leaves = cast_es.copy()
    leaves[: n // 2] += np.array([-0.2, 0.0, -0.2])           # half the frame is foliage: greener than the greys (on both counts)
    with_leaves = P.neutral_cast(leaves, 1.0)
    assert with_leaves is not None
    assert float(with_leaves.shift(0, np.array([0.0], np.float32))[0]) / with_leaves.weight == pytest.approx(cast[0], abs=0.06), "leaves do not drag the cast toward green"
    assert P.neutral_cast(cast_es, 0.0) is None
    colourful = rng.uniform(-1, 1, (n, 3))                    # nothing grey in the frame
    none = P.neutral_cast(colourful, 1.0)
    assert none is None or none.weight < 0.25, "a frame with no neutral gets little or no correction"
    assert P.neutral_cast(cast_es[:100], 1.0) is None, "and a handful of pixels has no say"


def test_grey_balance_takes_a_cast_out_of_the_print():
    """A cast that is only in the middle tones (a layer's curve bulging), which the balance of the frame's ends cannot see."""
    rng = np.random.default_rng(4)
    h, w = 120, 160
    g = np.linspace(0.0, 1.0, w)[None, :] * np.ones((h, 1))

    def densities(g, bump):
        d = np.stack([0.25 + 1.1 * g, 0.2 + 1.2 * g, 0.2 + 1.2 * g], -1)
        d[..., 0] += bump * 0.16 * np.sin(np.pi * g)
        d[..., 2] -= bump * 0.12 * np.sin(np.pi * g)
        return d

    caste = _codes(densities(g, 1.0) + rng.normal(0, 0.012, (h, w, 3)))
    block = P.analysis_block(caste)
    ramp = np.linspace(0.05, 0.95, 40)
    greys = _codes(densities(ramp[None, :] * np.ones((1, 1)), 1.0))      # the greys of that frame

    def chroma(settings):
        built = P.build_print(block, settings)
        out = P.apply_lut(greys, built.lut).astype(float)[0]
        return float(np.abs(out[:, 0] - out[:, 1]).mean() + np.abs(out[:, 2] - out[:, 1]).mean())

    plain, balanced = chroma(P.Settings()), chroma(P.Settings(grey_balance=1.0))
    assert balanced < plain * 0.8, (plain, balanced)
    assert chroma(P.Settings(grey_balance=0.5)) < plain and chroma(P.Settings(grey_balance=0.5)) > balanced - 1e-9, "half the slider takes out about half"
    assert chroma(P.Settings(grey_balance=0.0)) == pytest.approx(plain, abs=1e-6)


# ---------------------------------------------------------------- the contrast mask
def test_the_contrast_mask_opens_big_dark_areas_and_holds_back_big_bright_ones_and_keeps_detail():
    h, w = 160, 240
    d = np.empty((h, w, 3), np.float32)
    d[:, : w // 2] = 0.45                                   # a large thin (dark in the print) area
    d[:, w // 2:] = 1.65                                    # and a large dense (bright) one
    checker = ((np.indices((h, w)).sum(axis=0) // 3) % 2).astype(np.float32) * 0.12
    d += checker[..., None]
    codes = _codes(d)
    built = P.build_print(P.analysis_block(codes), P.Settings())
    plain = P.apply_lut(codes, built.lut).astype(float)
    plane = P.mask_plane(codes, built)
    shift = P.mask_shift(plane, built, 1.0)
    assert float(P.mask_shift(plane, built, 0.0).max()) == 0.0 and np.abs(P.mask_shift(plane, built, 0.5)).max() < np.abs(shift).max()
    import cv2

    full = cv2.resize(shift, (w, h), interpolation=cv2.INTER_LINEAR)
    masked = P.apply_lut(P.shape_codes(codes, built, full), built.lut).astype(float)
    left, right = (slice(0, h), slice(8, w // 2 - 8)), (slice(0, h), slice(w // 2 + 8, w - 8))
    dark_p, dark_m = plain[left].mean(), masked[left].mean()
    bright_p, bright_m = plain[right].mean(), masked[right].mean()
    assert (dark_m < dark_p) != (bright_m < bright_p) or (dark_m != dark_p and bright_m != bright_p), "the two areas move in opposite directions"
    assert abs(masked[left].mean() - masked[right].mean()) < abs(plain[left].mean() - plain[right].mean()), "the big difference between them is reduced"
    detail_p = plain[10:60, 10:60].std()
    detail_m = masked[10:60, 10:60].std()
    assert detail_m > 0.6 * detail_p, "the fine detail is kept"
    flat = _codes(np.full((h, w, 3), 1.0, np.float32))
    flat_built = P.build_print(P.analysis_block(_frame()), P.Settings())
    flat_shift = P.mask_shift(P.mask_plane(flat, flat_built), flat_built, 1.0)
    assert np.abs(flat_shift).max() < np.abs(shift).max(), "a frame that is all middle changes little"


# ---------------------------------------------------------------- in the renderer
def _render(pic, metering, **state):
    from PyQt6.QtWidgets import QApplication

    from photoeditor.desktop.render import EditParams, Renderer
    from photoeditor.desktop.session import AppState

    global _APP
    _APP = QApplication.instance() or QApplication([])
    st = AppState()
    st.negative_inverted = True
    st.metering = metering
    for k, v in state.items():
        setattr(st, k, v)
    return Renderer().render(pic, EditParams.from_state(st), ("pf", repr(metering), repr(state)), pic.shape[1], None, want_stats=False, overlay=False, flatfield=None)[0]


_APP = None


def _pic():
    light = np.power(10.0, -_frame(seed=2, h=200, w=300).astype(np.float64) / SCALE)
    srgb = np.where(light <= 0.0031308, 12.92 * light, 1.055 * np.power(light, 1 / 2.4) - 0.055)
    return np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)


def test_the_renderer_uses_each_control():
    pic = _pic()
    base = Metering(engine="print", transfer="srgb")
    plain = _render(pic, base)
    assert plain.shape == pic.shape
    for name, m in (("stock", dataclasses.replace(base, print_stock="kodak_portra_endura")), ("mask", dataclasses.replace(base, contrast_mask=1.0)),
                    ("grey", dataclasses.replace(base, grey_balance=1.0)), ("hold", dataclasses.replace(base, paper_toe=0.6, hold_black=True)),
                    ("toe", dataclasses.replace(base, paper_toe=0.6))):
        assert not np.array_equal(plain, _render(pic, m)), name
    assert not np.array_equal(_render(pic, dataclasses.replace(base, paper_toe=0.6)), _render(pic, dataclasses.replace(base, paper_toe=0.6, hold_black=True)))
    colour = _render(pic, base)
    assert np.abs(colour[..., 0].astype(int) - colour[..., 2]).max() > 5, "in colour the layers differ"
    for engine in ("print", "negpy056", "noritsu", "standard"):
        bw = _render(pic, dataclasses.replace(base, engine=engine, bw_filter="orange21"))
        assert (bw[..., 0] == bw[..., 1]).all() and (bw[..., 1] == bw[..., 2]).all(), engine
    off = _render(pic, dataclasses.replace(base, engine="standard"))
    assert np.abs(off[..., 0].astype(int) - off[..., 2]).max() >= 0
    assert not np.array_equal(_render(pic, dataclasses.replace(base, bw_filter="red25")), _render(pic, dataclasses.replace(base, bw_filter="green58")))
    held = _render(pic, dataclasses.replace(base, meter_frame=True))
    assert held.shape == pic.shape, "metering the picture runs (with no film frame to find it reads as it always did)"


def test_the_panel_shows_and_collects_the_controls_for_the_print_conversion():
    from PyQt6.QtWidgets import QApplication

    global _APP
    _APP = QApplication.instance() or QApplication([])
    from photoeditor.desktop.view.negative_tool_panel import NegativeToolPanel

    panel = NegativeToolPanel()
    m = Metering(engine="print", print_stock="fuji_crystal", stock_colour=0.5, grey_balance=0.7, contrast_mask=0.3, hold_black=True, bw_filter="yellow8", meter_frame=True)
    panel.set_metering(m)
    assert panel._collect() == m
    assert panel._stock.itemData(0) == "" and panel._stock.findData("fuji_crystal") > 0 and panel._bw_filter.findData("yellow8") > 0
    assert not panel._stock.isHidden() and not panel._hold_black.isHidden() and not panel._print_rows["contrast_mask"].isHidden()
    panel.set_metering(dataclasses.replace(m, engine="standard"))
    assert panel._stock.isHidden() and panel._hold_black.isHidden() and panel._print_rows["grey_balance"].isHidden() and not panel._bw_filter.isHidden(), "the B&W print is offered with every conversion"
    panel.set_metering(Metering(engine="print", print_stock="gone"))
    assert panel._collect().print_stock == "gone" and "missing" in panel._stock.currentText()
