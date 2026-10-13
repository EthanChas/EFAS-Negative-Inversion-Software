"""Turning a scanner-look preset from Negative Lab Pro's published list (the JSON files of its "NLP Color" presets) into an EFAS look - the conversion that made the
Lab Scanners built-in presets, kept as code so the rule is written down and testable. No Qt imports.

Only the tone, saturation and colour-balance settings can be carried over; the colour lookup table a preset names ("Frontier", "Crystal", "Pakon"...) and its glow
setting have no equivalent in EFAS and are left out (docs/presets.md). EFAS has no separate colour balance for shadows and highlights, so the three tonal ranges are
folded into one overall balance. The values are approximations, not measurements of any machine.
"""
from typing import Any

SATURATION_PER = 50.0
TONE_PER = 100.0
BALANCE_PER = 50.0
RED_PER = 100.0
RANGE_WEIGHTS = (("Shadows", 0.5), ("Mids", 0.3), ("Highs", 0.2))  # how much each tonal range counts in the one overall colour balance
DEFAULT_WIDTH = 2.5


def _setting(settings: dict[str, Any], key: str) -> float:
    value = settings.get(key, 0)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _balance(settings: dict[str, Any], name: str) -> float:
    return sum(_setting(settings, f"{name}{part}") * weight for part, weight in RANGE_WEIGHTS)


def convert(settings: dict[str, Any]) -> dict[str, float]:
    """The EFAS look for a preset's `settings` dict. Every key is always present, so applying it sets every one of these sliders."""
    look = {
        "saturation": _setting(settings, "Saturation") / SATURATION_PER,
        "temperature": _balance(settings, "BlueYellow") / BALANCE_PER,
        "tint": _balance(settings, "GreenMagenta") / BALANCE_PER,
        "shadows": _setting(settings, "Darks") / TONE_PER,
        "highlights": _setting(settings, "Lights") / TONE_PER,
        "print_toe": (_setting(settings, "Blacks") + _setting(settings, "LabFade")) / TONE_PER,
        "print_toe_width": DEFAULT_WIDTH,
        "print_shoulder": -_setting(settings, "Whites") / TONE_PER,
        "print_shoulder_width": DEFAULT_WIDTH,
    }
    red = _balance(settings, "RedCyan") / RED_PER
    if red:
        look["invert_r"] = red
    return {key: round(value + 0.0, 4) for key, value in look.items()}
