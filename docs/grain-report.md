# Grain Report (Extra > Grain Report...)

EFAS never adds grain: a scan of film already has its own, and adding more would be inventing texture the film did not have. What it can do is **measure the grain that is there** and tell you two things.

The dialog opens with two lines: **Grain: not resolved / partly resolved / resolved** (what your scan shows) and **Your edits: kept / removing / boosting / off** (what Sharpening, Chroma Denoise and Local Contrast do to it), each with one sentence. The first patch is shown at 100% below them. The numbers, the advice and the limits are under **Details**, which is closed until you open it.

## 1. What your capture resolves

Film grain is a texture a few to a few tens of micrometres across. A scan whose pixels are about as big as the grain, or whose focus is soft, cannot show it: what looks like grain is then mostly **sensor noise**, and the picture is limited by the capture and not by the film.

The report finds up to four **flat, mid-tone patches** of the open photo (256 by 256 pixels, away from the picture's edges, not clipped, with no gradient or detail in them), takes out the slow variation under each, and measures what is left, in the scan's own pixels:

- **Strength:** the standard deviation of the texture as a percentage of the brightness. Per channel as well for a colour scan; blue is usually the grainiest.
- **Width:** the lag, in pixels, at which the texture's autocorrelation falls to a half (the *correlation width*). White noise is about half a pixel; a soft texture is wider.

The verdict comes from the width: under **1 pixel** the grain is *not resolved* (the texture is at the pixel level), from 1 to 2 it is *partly resolved*, and from **2 pixels** up it is *resolved*. Each comes with advice in plain words: a closer capture, the lens's sharpest aperture, careful focus and a low ISO resolve more.

With the film's format set to **35mm** in the Roll Card, the report also says how many micrometres of film one pixel covers (the 36 mm frame width over the picture's width, assuming the frame fills the picture).

**Limits, stated in the report:** the camera's demosaicing makes noise about a pixel wide even when the film's grain is much finer, so a width near one pixel can mean fine grain that is simply not resolved, not that there is no grain. And it measures the patches it picked, not every part of the picture. If it cannot find a flat, mid-tone area (a picture that is all detail or clipped, or smaller than a patch) it says so and measures nothing.

## 2. Whether your edits keep it

Sharpening raises fine texture; Chroma Denoise and Local Contrast change it. The report converts **the same patches at the scan's own resolution** with your settings and with Sharpening, Chroma Denoise and Local Contrast off, and compares the **fine texture** (what a one-pixel blur removes) of the two. The answer is in words: the edits keep it (within about 15% below to 20% above), remove about some percentage of it, or raise it so sharpening is making the grain and the noise stronger, naming the module that did most when one stands out. The first patch is shown at 100% both ways, so you can see it.

If all three detail modules are off, it says so. It is not measured with the film-profile (curve) conversion. Nothing in the photo is changed by the report.

## Where it is in the code

`features/grain/logic.py` (the patches, the strength, the width, the verdicts and the comparison; no Qt), `AppController.grain_report` and `_grain_effect` (they convert the patches with a renderer of their own, so nothing on screen is touched), `desktop/view/grain_report_dialog.py`, and the tests `tests/test_grain_logic.py` and `tests/test_grain_report_ui.py`.
