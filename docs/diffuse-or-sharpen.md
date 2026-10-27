# Diffuse or Sharpen (Detail tab)

darktable's **diffuse or sharpen**, ported with its controls, its ranges, its tooltips and all of its presets. It simulates the diffusion of light with a heat-transfer model, and so it can apply an iterative edge-oriented blur, inpaint damaged parts of the picture, or remove blur with a blind deconvolution. In darktable it is the module behind "lens deblur", "dehaze" and the sharpening presets, and here too.

## How it works

The picture is cut into wavelet scales (a B-spline decomposition, as the contrast equalizer does), each a layer of detail at one size. From the coarsest to the finest, each scale gets a step of a partial differential equation: its high-frequency layer and the low-frequency layer under it are convolved with a 3x3 **anisotropic Laplacian** whose shape follows the local gradient, and the result is added back. That is repeated for the number of **iterations**. The four **speeds** (1st and 2nd order act on the low frequencies, 3rd and 4th on the high ones) say how fast and which way: negative sharpens, positive blurs, 0 does nothing. The four **anisotropies** say whether the diffusion follows the edges (negative), avoids them (positive) or both alike (0). The **radius** controls choose which scales are worked on: a *central radius* of 0 acts on the finest details (for deblurring and denoising), a larger one acts on local contrast; the *radius span* is how wide a band round it.

**Sharpness** raises or lowers the highest frequencies. **Edge sensitivity** and **edge threshold** keep the diffusion away from edges, to avoid halos and noise on smooth surfaces. The **luminance masking threshold** limits the module to the parts brighter than it: with 0 it works on the whole picture, with a value it works on the bright parts only, starting them from noise, which is how "inpaint highlights" fills in blown highlights.

## What EFAS does differently

* The picture is worked in **linear light**, as darktable does (the module is scene-referred): the 8-bit sRGB picture is made linear first and brought back after. A scene-referred module sees values above 1; an 8-bit picture has none, so a luminance threshold of 1.41 (darktable's "inpaint highlights") finds nothing: lower it to try the idea on a scan.
* The radii are in pixels of the **full** picture. On the smaller editing preview they are made proportionally smaller, so the preview looks like the export.
* It is a slow module (it solves an equation on every scale on every iteration). The **graphics card** does the work when there is one (see [gpu.md](gpu.md): a preview in a fraction of a second, a 24 megapixel export in about five), and the preview follows the slider. On the processor (a row of blocks on every core) it takes seconds to minutes, so, as in darktable's fast pipe, the module is **not run while a slider is being dragged** and the preview waits until the slider is let go.
* The module does nothing while the four speeds, the sharpness and the luminance threshold are all 0 (darktable's defaults).
* It works on the whole picture before the crop, after Sharpening and Grain Sharpening, and keeps the picture at 8 bits from there. Like every module it has the **Mask** box, an on/off light, **copies** (multiple instances), its own presets and a place in the history.

## The presets

The module's Presets menu lists darktable's (less its denoise and artistic effects presets, which are left out): **lens deblur** (soft, medium, hard), **dehaze** (default, extra contrast), **surface blur**, **sharpen demosaicing** (no AA filter, AA filter), **local contrast** (normal, fine, fast), **inpaint highlights**, and **sharpness** (fast, normal, strong). Applying one is one undoable step and sets every control of the module.

Code: `features/diffuse/logic.py`, `desktop/view/diffuse_panel.py`, `tests/test_diffuse_logic.py`.
