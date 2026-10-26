# Color Balance RGB (Color tab)

darktable's **color balance rgb**, by Aurelien Pierre, ported with its three pages, its sliders, its formulas and its presets: darktable's modern colour grading module.

## How it works

The picture is taken to **Filmlight Yrg** (a luminance and a chromaticity pair made from the CIE 2006 cone responses), where:

* **hue shift** rotates every hue at the same luminance; **vibrance** adds colour to the muted colours more than to the vivid ones; the **chroma** sliders (global, shadows, midtones, highlights) raise or lower colourfulness at the same luminance; a colour pushed out of the gamut is brought back at the same hue and luminance;
* the **four ways** work in the Filmlight RGB of those cones: a global **offset**, a **lift** (a slope in the shadows), a **gain** (a slope in the highlights) and a **power** (an exponent in the midtones), each with a **luminance**, a **hue** and a **chroma**; the shadows, midtones and highlights are three overlapping **masks** of the luminance, drawn in the graph of the *masks* page and shaped by *shadows fall-off*, *mask middle-gray fulcrum* and *highlights fall-off*;
* the luminance gets a **power** (midtones luminance) and a **contrast** about a grey fulcrum (*contrast gray fulcrum*), the power normalised to a *white fulcrum* in EV;

and last, **perceptual saturation** and **brilliance** (global, and for shadows, midtones and highlights) are applied in either **darktable UCS** (2022, the default) or **JzAzBz** (2021, the "legacy" one), each with its own gamut map that softly clips the saturation at constant brightness, so a boosted colour never leaves the picture's gamut or turns to a grey smudge.

## What EFAS does differently

* The 8-bit sRGB picture is made linear and taken as Rec. 709 primaries with a D65 white, which is what darktable's pipeline has for an sRGB profile after its own D50 to D65 adaptation; it is worked in single precision (double for JzAzBz, whose exponents of 134 need it) and brought back clipped to the sRGB gamut.
* The module does nothing while every grading slider is 0 (the formula and the masks alone change nothing). It works on the whole picture before the crop, after Tone Equalizer and Retouch and before Sharpening, and keeps the picture at 8 bits from there. It has the **Mask** box, an on/off light, **copies**, presets and a place in the history, and is part of every preview.
* The hue sliders have the colours of their hues painted under them. darktable's checkerboard preview of the masks and its colour pickers are not here.

## The presets

darktable's four: **basic colorfulness** (legacy, natural skin, vibrant colors, standard), in the module's Presets menu.

Code: `features/colorbalancergb/logic.py`, `desktop/view/color_balance_rgb_panel.py`, `desktop/view/dt_graphs.py`, `tests/test_color_balance_rgb_logic.py`.
