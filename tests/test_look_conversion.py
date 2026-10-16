"""The conversion from another program's scanner-look settings to EFAS sliders (docs/presets.md)."""
import pytest

from photoeditor.features.lookpresets import builtin, lookconvert
from photoeditor.features.lookpresets.modules import LOOK_KEYS


def test_each_rule_on_its_own():
    assert lookconvert.convert({"Saturation": 5})["saturation"] == pytest.approx(0.10)
    assert lookconvert.convert({"Darks": -24})["shadows"] == pytest.approx(-0.24) and lookconvert.convert({"Lights": 12})["highlights"] == pytest.approx(0.12)
    both = lookconvert.convert({"Blacks": -20, "LabFade": 7, "LabGlow": 12})
    assert both["print_toe"] == pytest.approx(-0.20) and both["lab_fade"] == pytest.approx(7 / 50) and both["lab_glow"] == pytest.approx(12 / 50), "fade and glow are the Lab Look's, on the original's -50 to +50 scale"
    assert lookconvert.convert({"Whites": 15})["print_shoulder"] == pytest.approx(-0.15), "brighter whites push the highlights harder to white"
    warm = lookconvert.convert({"BlueYellowShadows": 6, "BlueYellowHighs": 3})
    assert warm["lab_by_shadows"] == pytest.approx(6 / 50) and warm["lab_by_highs"] == pytest.approx(3 / 50) and warm["lab_by_mids"] == 0, "each tonal range keeps its own balance"
    assert warm["temperature"] == 0 and warm["tint"] == 0
    assert lookconvert.convert({"GreenMagentaMids": -4})["lab_gm_mids"] == pytest.approx(-4 / 50)
    assert lookconvert.convert({"RedCyanHighs": -2, "RedCyanShadows": 2})["invert_r"] == pytest.approx((-2 * 0.2 + 2 * 0.5) / 100)


def test_what_cannot_be_carried_over_is_left_out_and_a_blank_preset_is_neutral():
    out = lookconvert.convert({"LUT": "Frontier", "ToneProfile": "linear", "ToningMethod": "vintageToning", "ColorMethod": "shadowWeighted"})
    assert out == lookconvert.convert({}) and "invert_r" not in out
    assert out["saturation"] == out["shadows"] == out["highlights"] == out["print_toe"] == out["print_shoulder"] == 0 and out["print_toe_width"] == 2.5
    assert lookconvert.convert({"Saturation": "lots", "Darks": None, "Lights": True})["saturation"] == 0, "damaged values count as zero"


def test_every_converted_key_is_a_slider_a_look_can_hold():
    assert set(lookconvert.convert({"RedCyanHighs": 1})) <= set(LOOK_KEYS)


def test_the_lab_scanner_presets_are_here():
    names = builtin.names()
    assert {"Lab Scanners/Frontier 100", "Lab Scanners/Crystal 100", "Lab Scanners/Noritsu (Green Shadows)", "Lab Scanners/Pakon (Clean and Rich)"} <= set(names)
    frontier = builtin.get("Lab Scanners/Frontier 100")
    assert frontier["lab_fade"] == pytest.approx(11 / 50) and frontier["lab_glow"] == pytest.approx(12 / 50) and frontier["lab_by_shadows"] > frontier["lab_by_highs"] > 0, "Frontier fades, glows, and is warmer in its shadows"
    pakon = builtin.get("Lab Scanners/Pakon (Clean and Rich)")
    assert pakon["highlights"] > 0 and pakon["print_shoulder"] < 0 and "subtle" in builtin.description("Lab Scanners/Pakon (Clean and Rich)")


def test_the_film_stock_presets_are_here_in_brand_folders():
    names = set(builtin.names())
    assert {"Film Stocks/Cinestill/Cinestill", "Film Stocks/Fuji/Superia", "Film Stocks/Kodak/Gold", "Film Stocks/Kodak/Portra", "Film Stocks/Kodak/Portra Airy"} <= names
    gold, portra, airy = (builtin.get(f"Film Stocks/Kodak/{n}") for n in ("Gold", "Portra", "Portra Airy"))
    assert gold["lab_by_mids"] > 0.05 and gold["lab_by_shadows"] > 0.05 and gold["lab_by_highs"] == 0, "Gold is warm in the shadows and midtones, clean in the highlights"
    assert portra["print_shoulder"] > 0 and portra["highlights"] < 0, "Portra protects its highlights"
    assert airy["shadows"] > 0 and airy["highlights"] > 0, "Airy lifts both ends"
    import json

    raw = json.loads((builtin.PRESET_DIR / "film-stocks.json").read_text(encoding="utf-8"))
    for item in raw["presets"]:
        assert item["description"] and set(item["look"]) <= set(LOOK_KEYS), item["name"]
