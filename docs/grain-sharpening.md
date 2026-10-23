# Grain Sharpening (Detail tab)

A camera scan of a negative often records the grain soft: the grain is a texture only a pixel or two wide, and the lens, the sensor's own filter and the demosaicing each blur it a little. **Grain Sharpening** makes the grain that is already in the scan **crisper**. It does not add grain (where the scan shows a flat grey there is nothing to sharpen), and it cannot show detail the capture did not record. Sharpening, the other module, works on the picture's detail and is set to leave the grain alone; this is the other way round.

- **Amount:** how much crisper. 0 is off. A full Amount raises the contrast of the grain band to about two and a half times what it was.
- **Size (px):** the grain's width in **scan pixels**, 0.6 to 4. **Match My Grain** measures the open photo the way the [Grain Report](grain-report.md) does and sets Size to that width; most camera scans are between 1 and 2.
- **Midtones:** 0 treats every tone alike, 1 leaves the deepest shadows and the highlights as they were (a bell over the mid lightness, so the grain in the shadows, where sensor noise sits, is raised less).

## How it works

On the picture's lightness (L of Lab, so colour is not changed) it takes the band of texture at the grain's size, the difference between a Gaussian blur of Size x 0.5 and one of Size x 1.6, eases it with a soft limit (about 3 lightness units, so a hard edge is not given a halo: the overshoot at a step edge is a few levels), weights it by the Midtones curve and adds Amount x 1.5 of it back. It works in horizontal strips with an overlap, so a big picture does not need the memory of the whole, and the strips join without a seam.

It runs on the picture after Sharpening and before the crop, so it is made from the whole scan. **Size is in pixels of the scan**: the editing preview is the scan made smaller, so the grain is under a pixel there (a blur narrower than 0.35 px is left out) and nothing shows. Zoom to 100% with **HQ** on, or look at the export, which is made from the scan itself. A small scan, whose preview is the scan, shows it straight away.

Like every module it is saved with the photo, can be part of a preset, can be switched off with its power light, has its own presets, and is undone with Ctrl+Z. The Grain Report counts it among the modules it compares (Sharpening, Chroma Denoise, Local Contrast and this one) and, when it is the one that raised the grain, says the grain is **crisper** rather than that sharpening is too strong.

Code: `features/grainsharp/logic.py`, `desktop/view/grainsharp_panel.py`, `tests/test_grain_sharpening.py`.
