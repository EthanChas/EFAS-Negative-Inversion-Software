"""Turning a scanner-look or film-look preset from another program's published list of presets (JSON files of tone, saturation, fade, glow and colour-balance settings) into
an EFAS look - the conversion that made the built-in Lab Scanners and Film Stocks presets, kept as code so the rule is written down and testable. No Qt imports.

Tone, saturation, fade, glow and the colour balance of the shadows, midtones and highlights carry over (the last three into the Lab Look module, which keeps the three tonal
ranges apart as the originals do). The colour lookup table a preset names, its tone profile and its toning method have no equivalent in EFAS and are left out. The values are
approximations, not measurements of any machine or film."""
from typing import Any

SATURATION_PER = 50.0
TONE_PER = 100.0
LAB_PER = 50.0   # Fade and Glow run -50 to +50 in the original, which is -1 to +1 here
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
        "temperature": 0.0,
        "tint": 0.0,
        "shadows": _setting(settings, "Darks") / TONE_PER,
        "highlights": _setting(settings, "Lights") / TONE_PER,
        "print_toe": _setting(settings, "Blacks") / TONE_PER,
        "print_toe_width": DEFAULT_WIDTH,
        "print_shoulder": -_setting(settings, "Whites") / TONE_PER,
        "print_shoulder_width": DEFAULT_WIDTH,
        "lab_fade": _setting(settings, "LabFade") / LAB_PER,
        "lab_glow": _setting(settings, "LabGlow") / LAB_PER,
    }
    for part, name in (("Shadows", "shadows"), ("Mids", "mids"), ("Highs", "highs")):
        look[f"lab_by_{name}"] = _setting(settings, f"BlueYellow{part}") / BALANCE_PER
        look[f"lab_gm_{name}"] = _setting(settings, f"GreenMagenta{part}") / BALANCE_PER
    red = _balance(settings, "RedCyan") / RED_PER
    if red:
        look["invert_r"] = red
    return {key: round(value + 0.0, 4) for key, value in look.items()}
