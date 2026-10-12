"""The short written read-out under the histogram: a few compact rows, with the detail in tooltips."""
import numpy as np

from photoeditor.features.whitebalance import readout as R


def flat(v, shape=(40, 60)):
    return np.full((*shape, 3), v, np.uint8)


def ramp():
    return np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2).repeat(8, axis=0)


def test_readout_numbers_for_a_known_picture():
    r = R.tonal_readout(ramp())
    assert abs(r["mean"] - 127.5) < 1 and abs(r["median"] - 127.5) < 2
    assert r["p1"] < 5 and r["p99"] > 250 and abs((r["p95"] - r["p5"]) - 230) < 6
    assert abs(r["shadows_pct"] - 25) < 1 and abs(r["highlights_pct"] - 25) < 1 and abs(r["midtones_pct"] - 50) < 1.5
    assert r["blocked_pct"] < 2 and r["blown_pct"] < 3
    assert abs(r["r"] - r["g"]) < 0.01 and r["saturation"] == 0.0


def test_there_are_only_six_short_rows():
    rows = R.compact_rows(R.tonal_readout(ramp()))
    assert [label for label, _v, _t in rows] == ["Exposure", "Contrast", "Range", "Clipping", "Colour", "Saturation"]
    for label, value, tip in rows:
        assert len(value) <= 18, (label, value)
        assert len(tip) > len(value), "the detail is in the tooltip"


def test_the_rows_say_what_they_should():
    rows = {label: (value, tip) for label, value, tip in R.compact_rows(R.tonal_readout(ramp()))}
    assert rows["Exposure"][0] in ("Well exposed, 128", "Well exposed, 127")
    assert rows["Range"][0].startswith("Full ") and rows["Contrast"][0] in ("Harsh", "Punchy")
    assert "/" in rows["Clipping"][0] and rows["Colour"][0] == "Neutral" and rows["Saturation"][0] == "Monochrome"
    assert "median" in rows["Exposure"][1] and "deviation" in rows["Contrast"][1] and "Blocked shadows" in rows["Clipping"][1]
    assert "Dark (below 64)" in rows["Range"][1] and "light (192 and up)" in rows["Range"][1], "the dark / middle / light split is in the tooltip"


def test_exposure_words():
    assert R.exposure_verdict(40) == "Underexposed" and R.exposure_verdict(120) == "Well exposed" and R.exposure_verdict(210) == "Overexposed"


def test_contrast_runs_from_flat_to_harsh():
    labels = []
    for lo, hi in ((110, 140), (90, 170), (50, 200), (30, 215), (0, 255)):
        img = np.concatenate([flat(lo, (20, 60)), flat(hi, (20, 60))])
        labels.append(R.contrast_label(R.tonal_readout(img)))
    assert labels == ["Very flat", "Flat", "Normal", "Punchy", "Harsh"], labels
    assert R.range_label({"p1": 5, "p99": 250}) == "Full range" and R.range_label({"p1": 60, "p99": 190}) == "Narrow range"


def test_clipping_row():
    img = np.concatenate([flat(0, (10, 60)), flat(255, (10, 60)), flat(128, (20, 60))])
    r = R.tonal_readout(img)
    assert abs(r["blocked_pct"] - 25) < 0.1 and abs(r["blown_pct"] - 25) < 0.1
    assert dict((l, v) for l, v, _t in R.compact_rows(r))["Clipping"] == "25% / 25%"
    assert dict((l, v) for l, v, _t in R.compact_rows(R.tonal_readout(flat(128))))["Clipping"] == "0% / 0%"


def test_colour_words():
    neutral = R.tonal_readout(flat(128))
    assert R.cast_label(neutral) == "Neutral" and R.saturation_label(neutral["saturation"]) == "Monochrome"
    assert "warm" in R.cast_label(R.tonal_readout(np.full((10, 10, 3), (150, 128, 100), np.uint8))).lower()
    assert "cool" in R.cast_label(R.tonal_readout(np.full((10, 10, 3), (100, 128, 160), np.uint8))).lower()
    assert "green" in R.cast_label(R.tonal_readout(np.full((10, 10, 3), (110, 150, 110), np.uint8))).lower()
    assert "magenta" in R.cast_label(R.tonal_readout(np.full((10, 10, 3), (150, 100, 150), np.uint8))).lower()
    assert "strongly warm" in R.cast_label(R.tonal_readout(np.full((10, 10, 3), (220, 128, 40), np.uint8))).lower()
    assert [R.saturation_label(s) for s in (0.02, 0.15, 0.3, 0.6, 0.9)] == ["Monochrome", "Muted", "Natural", "Vivid", "Very vivid"]
    assert R.saturation_label(R.tonal_readout(np.full((10, 10, 3), (250, 40, 40), np.uint8))["saturation"]) == "Very vivid"


def test_colour_row_is_short():
    cols = lambda rgb: dict((l, v) for l, v, _t in R.compact_rows(R.tonal_readout(np.full((10, 10, 3), rgb, np.uint8))))
    assert cols((128, 128, 128))["Colour"] == "Neutral"
    assert cols((132, 128, 124))["Colour"] == "Slight warm" and cols((136, 128, 120))["Colour"] == "Warm" and cols((220, 128, 40))["Colour"] == "Strong warm"
    assert R.cast_short(R.tonal_readout(np.full((10, 10, 3), (150, 100, 150), np.uint8))) == "Strong magenta"
    assert all(len(cols(c)["Colour"]) <= 16 for c in ((110, 150, 110), (150, 100, 150), (100, 128, 160), (250, 40, 40), (132, 128, 124)))
    assert cols((250, 40, 40))["Saturation"] == "Very vivid"


def test_black_picture_does_not_break_it():
    r = R.tonal_readout(flat(0))
    assert r["saturation"] == 0.0 and r["mean"] == 0 and r["blocked_pct"] == 100
    assert dict((l, v) for l, v, _t in R.compact_rows(r))["Exposure"].startswith("Underexposed")


def test_the_negative_summary_is_one_short_line():
    text, tip = R.negative_summary("c41", True, (210, 130, 80), "classic", "", "")
    assert text == "Colour neg, inverted, sampled base"
    assert "Film base: sampled (210, 130, 80)" in tip and "Inversion: standard" in tip and "Recognised as: Colour negative, inverted" in tip and "Metering" not in tip
    text, tip = R.negative_summary("bw", True, None, "curve", "Tri-X 400", "drawn region")
    assert text == "B&W neg, inverted, auto base, curve: Tri-X 400, metering changed"
    assert "Metering: drawn region" in tip and "Film base: estimated from the photo" in tip
    assert R.negative_summary("e6", False, None, "classic", "", "")[0] == "Slide, auto base"
    assert R.negative_summary("", False, None, "classic", "", "")[0] == "Not inverted, auto base"
    assert R.negative_summary("c41", False, None, "classic", "", "")[0] == "Colour neg, not inverted, auto base"


def test_metering_is_only_mentioned_when_it_is_not_the_ordinary_way():
    assert R.metering_text(0.12, None, 0.0, 0.0, 0.0) == ""
    assert R.metering_text(0.12, (1, 2, 3, 4), 2.0, 0.0, 0.0) == "drawn region, range clip 2"
    assert R.metering_text(0.05, None, 0.0, 0.25, 0.0) == "whole frame less 5% margin, points moved"
