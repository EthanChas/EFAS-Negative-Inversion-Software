"""The conversion from another program's scanner-look settings to EFAS sliders (docs/presets.md)."""
import pytest

from photoeditor.features.lookpresets import builtin, nlp
from photoeditor.features.lookpresets.modules import LOOK_KEYS


def test_each_rule_on_its_own():
    assert nlp.convert({"Saturation": 5})["saturation"] == pytest.approx(0.10)
    assert nlp.convert({"Darks": -24})["shadows"] == pytest.approx(-0.24) and nlp.convert({"Lights": 12})["highlights"] == pytest.approx(0.12)
    assert nlp.convert({"Blacks": -20, "LabFade": 7})["print_toe"] == pytest.approx(-0.13), "blacks and fade share the toe"
    assert nlp.convert({"Whites": 15})["print_shoulder"] == pytest.approx(-0.15), "brighter whites push the highlights harder to white"
    warm = nlp.convert({"BlueYellowShadows": 6, "BlueYellowHighs": 3})
    assert warm["temperature"] == pytest.approx((6 * 0.5 + 3 * 0.2) / 50)
    assert nlp.convert({"GreenMagentaMids": -4})["tint"] == pytest.approx(-4 * 0.3 / 50)
    assert nlp.convert({"RedCyanHighs": -2, "RedCyanShadows": 2})["invert_r"] == pytest.approx((-2 * 0.2 + 2 * 0.5) / 100)


def test_what_cannot_be_carried_over_is_left_out_and_a_blank_preset_is_neutral():
    out = nlp.convert({"LabGlow": 12, "LUT": "Frontier", "ToneProfile": "linear", "ToningMethod": "vintageToning", "ColorMethod": "shadowWeighted"})
    assert out == nlp.convert({}) and "invert_r" not in out
    assert out["saturation"] == out["shadows"] == out["highlights"] == out["print_toe"] == out["print_shoulder"] == 0 and out["print_toe_width"] == 2.5
    assert nlp.convert({"Saturation": "lots", "Darks": None, "Lights": True})["saturation"] == 0, "damaged values count as zero"


def test_every_converted_key_is_a_slider_a_look_can_hold():
    assert set(nlp.convert({"RedCyanHighs": 1})) <= set(LOOK_KEYS)


def test_the_lab_scanner_presets_are_here():
    names = builtin.names()
    assert {"Lab Scanners/Frontier 100", "Lab Scanners/Crystal 100", "Lab Scanners/Noritsu (Green Shadows)", "Lab Scanners/Pakon (Clean and Rich)"} <= set(names)
    pakon = builtin.get("Lab Scanners/Pakon (Clean and Rich)")
    assert pakon["highlights"] > 0 and pakon["print_shoulder"] < 0 and "subtle" in builtin.description("Lab Scanners/Pakon (Clean and Rich)")


def test_the_film_stock_presets_are_here_in_brand_folders():
    names = set(builtin.names())
    assert {"Film Stocks/Cinestill/Cinestill", "Film Stocks/Fuji/Superia", "Film Stocks/Kodak/Gold", "Film Stocks/Kodak/Portra", "Film Stocks/Kodak/Portra Airy"} <= names
    gold, portra, airy = (builtin.get(f"Film Stocks/Kodak/{n}") for n in ("Gold", "Portra", "Portra Airy"))
    assert gold["temperature"] > 0.05, "Gold is the warm one"
    assert portra["print_shoulder"] > 0 and portra["highlights"] < 0, "Portra protects its highlights"
    assert airy["shadows"] > 0 and airy["highlights"] > 0, "Airy lifts both ends"
    import json

    raw = json.loads((builtin.PRESET_DIR / "film-stocks.json").read_text(encoding="utf-8"))
    for item in raw["presets"]:
        assert item["description"] and set(item["look"]) <= set(LOOK_KEYS), item["name"]
