# Tone Equalizer (Tone tab)

darktable's **tone equalizer**, by Aurelien Pierre, ported with its three pages, its estimators, its guided filters, its wands, its mask view and its presets. It relights the picture by an **exposure correction for each octave of brightness**, the way an audio equalizer sets a gain for each octave of sound, and it can do it **locally**: the gain follows the light of a region, so the local contrast inside the region is kept.

## How it works

Nine **nodes** sit one EV apart from -8 EV (deep shadows) to 0 EV (white), each set from -2 to +2 EV. The gain at any brightness is a smooth curve through them (a series of gaussians solved by least squares; *curve smoothing* widens or narrows them, and too much makes the curve oscillate). A pixel's brightness is not its own but that of a **mask**: a luminance estimate (RGB average, HSL lightness, HSV value, RGB sum, euclidean norm (the default), power norm or geometric mean), which by default is blurred by an **edge-aware guided filter** so that two pixels of one region get one correction. *Preserve details* chooses how: no filter (global and local contrast change), the guided filter, darktable's exposure-independent guided filter (**EIGF**, the default, which smooths shadows and highlights alike) or the average of the two with the unfiltered mask. *Smoothing diameter*, *filter diffusion* (the passes), *edge feathering* (how closely the blur follows edges) and *mask quantization* (a posterisation that helps the guiding) tune the blur.

The mask's *exposure compensation* slides it along the nodes and its *contrast compensation* spreads it, so that a picture that is mostly dark or mostly light uses all nine. The **wands** beside them set both from the open photo's mask (they read its histogram: the average exposure is centred on -4 EV, and 90% of the mask is spread over -7 to -1 EV, with darktable's correction for the filter in use).

## The window

**simple**: a slider for each node. **advanced**: the curve, with the histogram of the mask behind it; drag a node up to lighten and down to darken, double-click to reset; and the curve smoothing and the two mask compensations with their wands. **masking**: the estimator, the details, the iterations, the diameter, the feathering and the quantization. **display exposure mask** shows the mask as a grey picture in place of the result (a view of the picture, not an edit: nothing is saved or put in the history).

## What EFAS does differently

* The picture is worked in **linear light**: the 8-bit sRGB picture is made linear, multiplied by the gain and brought back, clipped at white. darktable's module is scene-referred; an EFAS picture is already the finished tones, which suits the -8 EV to 0 EV range well.
* The module does nothing while all nine nodes are 0. It works on the whole picture before the crop, after Retouch and before Color Balance RGB and Sharpening, and keeps the picture at 8 bits from there. It has the **Mask** box (a mask over the tone equalizer is how a local dodge or burn is done), an on/off light, **copies**, presets and a place in the history. It is part of every preview, as it is quick.

## The presets

darktable's: **simple tone curve**, **mask blending** (all purposes, people with backlight), **compress shadows/highlights** (EIGF or GF; strong, medium, soft), **contrast tone curve** (soft, medium, strong) and **relight: fill-in**, in the module's Presets menu.

Code: `features/toneequalizer/logic.py`, `desktop/view/tone_equalizer_panel.py`, `desktop/view/dt_graphs.py`, `tests/test_tone_equalizer_logic.py`.
