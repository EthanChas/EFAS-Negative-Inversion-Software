"""Turning a scanner-look or film-look preset from another program's published list of presets (JSON files of tone, saturation, fade, glow and colour-balance settings) into
an EFAS look - the conversion that made the built-in Scanners (EFAS Original) and Film Stocks presets, kept as code so the rule is written down and testable. No Qt imports.

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
RESPONSE_OF_TABLE = {"frontier": "frontier", "crystal": "crystal", "pakon": "pakon", "noritsu": "noritsu"}   # the original's colour tables EFAS has a stand-in for; "Natural" is none


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
    table = settings.get("LUT")
    look["lab_response"] = RESPONSE_OF_TABLE.get(table.strip().lower(), "none") if isinstance(table, str) else "none"
    look["lab_response_amount"] = 1.0
    red = _balance(settings, "RedCyan") / RED_PER
    if red:
        look["invert_r"] = red
    return {key: (round(value + 0.0, 4) if isinstance(value, float) else value) for key, value in look.items()}


# ---- DarkSlide's film profiles (github.com/kilianvivien/DarkSlide, MIT) -> an EFAS look
DS_CONTRAST_NEUTRAL = 10.0      # DarkSlide's default Contrast; the look is the difference from it, on its -100..100 scale
DS_SATURATION_NEUTRAL = 100.0   # its Saturation is a percentage of the colour the picture has
DS_TONE_PER = 100.0
DS_SHADOW_LIFT_NEUTRAL = 0.05   # the tonal character of its Generic Color profile: no fade, no change to the shoulder
DS_FADE_PER = 3.0               # Fade per unit of shadow lift above neutral: a shadow lift of 0.15 (Portra 400) is a Fade of 0.30
DS_ROLLOFF_NEUTRAL = 0.50
DS_SHOULDER_PER = 0.6           # a highlight roll-off of 0.70 (Portra 400) is a Shoulder of +0.12; 0.30 (Ektar) is -0.12


def convert_darkslide_film(profile: dict[str, Any]) -> dict[str, float]:
    """The EFAS look for one of DarkSlide's film profiles ({"type": "color" | "bw", "settings": {...}, "tonal": {...} | None}).

    Carried over: Contrast, Saturation (a black-and-white stock is fully desaturated), Temperature and Tint, and the stock's tonal character - the shadow lift as Lab Look's Fade and
    the highlight roll-off as the Print Response Shoulder. Left out: Exposure, the red / green / blue balance, black and white points and highlight protection, which in DarkSlide
    correct for its own inversion (the film base and the clip levels of its pipeline) and would only shift EFAS's own conversion; and the colour matrix and mask tuning. Every key is
    always present, so applying a profile replaces the last one."""
    settings = profile.get("settings") or {}
    tonal = profile.get("tonal") or {}
    num = lambda key, default: float(settings.get(key, default))
    saturation = -1.0 if profile.get("type") == "bw" else (num("saturation", DS_SATURATION_NEUTRAL) - DS_SATURATION_NEUTRAL) / DS_SATURATION_NEUTRAL
    look = {
        "contrast": (num("contrast", DS_CONTRAST_NEUTRAL) - DS_CONTRAST_NEUTRAL) / DS_TONE_PER,
        "saturation": saturation,
        "temperature": num("temperature", 0.0) / DS_TONE_PER,
        "tint": num("tint", 0.0) / DS_TONE_PER,
        "lab_fade": (float(tonal.get("shadowLift", DS_SHADOW_LIFT_NEUTRAL)) - DS_SHADOW_LIFT_NEUTRAL) * DS_FADE_PER,
        "print_shoulder": (float(tonal.get("highlightRolloff", DS_ROLLOFF_NEUTRAL)) - DS_ROLLOFF_NEUTRAL) * DS_SHOULDER_PER,
    }
    return {key: round(value + 0.0, 4) for key, value in look.items()}
