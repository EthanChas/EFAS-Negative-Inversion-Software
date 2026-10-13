"""Scanning-light presets: a starting Color trim for the backlight a negative was photographed on - pure numpy-free maths, no Qt/UI imports.

A light that is warmer or cooler than daylight tints the whole scan. EFAS's Color cast control already removes a cast it can measure from the picture, so this is
a starting point for when that is turned down, or for a scan whose base was not sampled: it works out how much red, green and blue the light adds compared with
daylight and gives the trim that undoes it on the positive.

What it assumes (and the preset's note says so): the light is a black-body radiator at its colour temperature, and the camera's white balance was left at
daylight (5500 K). A real LED is not a black-body; its colour temperature is a summary of its tint, not its spectrum. A light that has no published temperature
(for example the CineStill CS-LITE, whose modes are described by use, not in Kelvin) has no preset here: pick Custom and type the temperature you measured or the
maker gives. Nothing here is measured from your camera; adjust by eye.
"""
from .logic import INVERT_OFFSET_LEVELS

REFERENCE_KELVIN = 5500.0
MIN_KELVIN, MAX_KELVIN = 2000.0, 12000.0
_SAMPLE_GREY = 0.18  # linear: the middle grey the trim is worked out at

# name, Kelvin, what it is
PRESETS = (
    ("Daylight / flash (5500 K)", 5500.0, "Matches a camera white balance set to daylight: no correction."),
    ("Cool white LED panel or screen (6500 K)", 6500.0, "Light tables, tablets and phone screens are usually about 6500 K."),
    ("Neutral white LED (4000 K)", 4000.0, "Many LED light pads and bulbs sold as neutral or cool white."),
    ("Warm white LED (3000 K)", 3000.0, "Household bulbs sold as warm white."),
    ("Tungsten / halogen (3200 K)", 3200.0, "Incandescent and halogen lamps, and tungsten-balanced film lights."),
)


def blackbody_xy(kelvin: float) -> tuple[float, float]:
    """The chromaticity of a black-body radiator at this temperature (Kim et al.'s cubic fit of the Planckian locus, good from 1667 K to 25000 K)."""
    t = float(min(max(kelvin, 1667.0), 25000.0))
    if t <= 4000.0:
        x = -0.2661239e9 / t**3 - 0.2343589e6 / t**2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t**3 + 2.1070379e6 / t**2 + 0.2226347e3 / t + 0.240390
    if t <= 2222.0:
        y = -1.1063814 * x**3 - 1.34811020 * x**2 + 2.18555832 * x - 0.20219683
    elif t <= 4000.0:
        y = -0.9549476 * x**3 - 1.37418593 * x**2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x**3 - 5.87338670 * x**2 + 3.75112997 * x - 0.37001483
    return x, y


def blackbody_rgb(kelvin: float) -> tuple[float, float, float]:
    """The light's linear red, green and blue (sRGB primaries), scaled so green is 1."""
    x, y = blackbody_xy(kelvin)
    big_x, big_z = x / y, (1 - x - y) / y  # Y = 1
    r = 3.2404542 * big_x - 1.5371385 - 0.4985314 * big_z
    g = -0.9692660 * big_x + 1.8760108 + 0.0415560 * big_z
    b = 0.0556434 * big_x - 0.2040259 + 1.0572252 * big_z
    return r / g, 1.0, b / g


def _oetf(linear: float) -> float:
    linear = max(0.0, linear)
    return 12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055


def trim_for(kelvin: float, reference: float = REFERENCE_KELVIN) -> tuple[float, float, float]:
    """The Color trim (red, green, blue, each -1 to 1 as the Negative tab's sliders) that undoes the tint of a light at `kelvin` for a camera balanced for
    `reference`. A warmer light gives red more and blue less; green is the anchor and stays 0. At the reference temperature the trim is all zero."""
    kelvin = min(max(float(kelvin), MIN_KELVIN), MAX_KELVIN)
    light, ref = blackbody_rgb(kelvin), blackbody_rgb(reference)
    out = []
    for c in range(3):
        gain = light[c] / ref[c]  # how much more of this colour the light has than the reference
        level = 255.0 * (_oetf(_SAMPLE_GREY * gain) - _oetf(_SAMPLE_GREY))
        out.append(round(max(-1.0, min(1.0, level / INVERT_OFFSET_LEVELS)), 3))
    out[1] = 0.0
    return out[0], out[1], out[2]


def preset_trim(name: str) -> tuple[float, float, float] | None:
    for preset_name, kelvin, _note in PRESETS:
        if preset_name == name:
            return trim_for(kelvin)
    return None
