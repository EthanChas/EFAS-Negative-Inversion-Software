"""The written read-out under the histogram: exposure, tonal range, contrast, clipping, colour and the scan grading."""
import numpy as np

from photoeditor.features.densitometry.quality import ScanQuality
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


def test_exposure_words():
    assert R.exposure_verdict(40) == "Underexposed" and R.exposure_verdict(120) == "Well exposed" and R.exposure_verdict(210) == "Overexposed"
    lines = dict(R.exposure_lines(R.tonal_readout(ramp())))
    assert lines["Exposure"] in ("Well exposed, 128", "Well exposed, 127")
    assert lines["Range"].startswith("Full, ") and "/" in lines["Dark / mid / light"]


def test_contrast_runs_from_flat_to_harsh():
    labels = []
    for lo, hi in ((110, 140), (90, 170), (50, 200), (30, 215), (0, 255)):
        img = np.concatenate([flat(lo, (20, 60)), flat(hi, (20, 60))])
        labels.append(R.contrast_label(R.tonal_readout(img)))
    assert labels == ["Very flat", "Flat", "Normal", "Punchy", "Harsh"], labels
    assert dict(R.contrast_lines(R.tonal_readout(ramp())))["Contrast"] in ("Harsh", "Punchy")
    assert R.range_label({"p1": 5, "p99": 250}) == "Full range" and R.range_label({"p1": 60, "p99": 190}) == "Narrow range"


def test_clipping_lines():
    img = np.concatenate([flat(0, (10, 60)), flat(255, (10, 60)), flat(128, (20, 60))])
    r = R.tonal_readout(img)
    assert abs(r["blocked_pct"] - 25) < 0.1 and abs(r["blown_pct"] - 25) < 0.1
    lines = dict(R.clipping_lines(r))
    assert lines == {"Blocked shadows": "25%", "Blown highlights": "25%"}
    clean = dict(R.clipping_lines(R.tonal_readout(flat(128))))
    assert clean == {"Blocked shadows": "0%", "Blown highlights": "0%"}


def test_colour_words():
    neutral = R.tonal_readout(flat(128))
    assert R.cast_label(neutral) == "Neutral" and R.saturation_label(neutral["saturation"]) == "Monochrome"
    warm = np.full((10, 10, 3), (150, 128, 100), np.uint8)
    assert "warm" in R.cast_label(R.tonal_readout(warm)).lower()
    cool = np.full((10, 10, 3), (100, 128, 160), np.uint8)
    assert "cool" in R.cast_label(R.tonal_readout(cool)).lower()
    green = np.full((10, 10, 3), (110, 150, 110), np.uint8)
    assert "green" in R.cast_label(R.tonal_readout(green)).lower()
    magenta = np.full((10, 10, 3), (150, 100, 150), np.uint8)
    assert "magenta" in R.cast_label(R.tonal_readout(magenta)).lower()
    strong = np.full((10, 10, 3), (220, 128, 40), np.uint8)
    assert "strongly warm" in R.cast_label(R.tonal_readout(strong)).lower()
    assert [R.saturation_label(s) for s in (0.02, 0.15, 0.3, 0.6, 0.9)] == ["Monochrome", "Muted", "Natural", "Vivid", "Very vivid"]
    vivid = np.full((10, 10, 3), (250, 40, 40), np.uint8)
    assert R.saturation_label(R.tonal_readout(vivid)["saturation"]) == "Very vivid"


def test_black_picture_does_not_break_it():
    r = R.tonal_readout(flat(0))
    assert r["saturation"] == 0.0 and r["mean"] == 0 and r["blocked_pct"] == 100
    assert dict(R.exposure_lines(r))["Exposure"].startswith("Underexposed")


def test_scan_lines():
    lines = dict(R.scan_lines("c41", True, (210, 130, 80), "classic", "", "whole frame less 12% margin"))
    assert lines == {"Type": "Colour negative, inverted", "Film base": "Sampled (210, 130, 80)", "Inversion": "Standard", "Metering": "whole frame less 12% margin"}
    bw = dict(R.scan_lines("bw", True, None, "curve", "Tri-X 400", ""))
    assert bw["Type"] == "Black & white negative, inverted" and bw["Film base"] == "Auto-estimated" and bw["Inversion"] == "Curve-informed: Tri-X 400" and "Metering" not in bw
    slide = dict(R.scan_lines("e6", False, None, "classic", "", ""))
    assert slide["Type"] == "Slide"
    assert [k for k, _ in R.scan_lines("", False, None, "classic", "", "")] == ["Film base", "Inversion"]


def test_metering_text():
    assert R.metering_text(0.12, None, 0.0, 0.0, 0.0) == "whole frame less 12% margin"
    assert R.metering_text(0.12, (1, 2, 3, 4), 2.0, 0.0, 0.0) == "drawn region; range clip 2"
    assert R.metering_text(0.05, None, 0.0, 0.25, 0.0) == "whole frame less 5% margin; points moved"
