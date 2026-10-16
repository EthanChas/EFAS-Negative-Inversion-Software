# Graphics card (Vulkan) and the GPU limit

The editor can run the heaviest per-pixel stages of the edit pipeline on your graphics card, through **Vulkan**, and a **limit** keeps it from working the card flat out. Both are in **Settings > Graphics card**.

## What runs on the card

These stages work on every pixel by itself, and they are the ones that cost the most on the processor. They run as one program on the card, in the order the processor pipeline runs them:

1. shadows / highlights
2. saturation
3. the tone table (the tone curve, the lab look and the per-colour curves, as one lookup)
4. the colour work in OKLCH: **Vibrance, the Color Mixer, the scanner colour response and Color Toning**
5. the **vignette**

Everything else stays on the processor: denoise, sharpening, local contrast, the geometry (rotation, straightening, distortion, keystone), dust repair, the edge tools, the border, the watermark and the histogram. The RAW decoding and the inversion's measuring are unchanged too.

How much it matters, measured on a 6720 x 4480 photo and a 2048 x 1365 preview (RTX 3060 Ti; the processor times are for this computer's processor):

| work | processor | graphics card |
|---|---|---|
| vibrance + colour mixer + vignette, full size | 53 s | 0.17 s |
| the same, preview size | 4.6 s | 0.03 s |
| saturation + shadows / highlights, full size | 1.6 s | 0.14 s |
| saturation + shadows / highlights, preview | 0.10 s | 0.02 s |

Edits that are only a tone curve, exposure, contrast or colour balance were never slow (they are lookups, 20 to 45 ms even at full size), so they stay as they were.

## How closely it matches the processor

It is the same arithmetic, written for the card, and each stage rounds to 8 bits exactly where the processor's stage does. The card's maths differs from the processor's in the last decimal place, so a pixel can land one level (out of 255) away from the processor's picture, and in the colour work a colour that sits right on the edge of the sRGB gamut can be judged in or out differently. In the tests that is a few pixels in a hundred thousand, and the average difference is under 0.001 of a level. If you need the pictures to be identical to the processor's, switch the card off (below): every export then comes out exactly as in earlier versions.

## Settings > Graphics card

* **Use the graphics card for the colour work**: on by default. Off, everything runs on the processor.
* **Most of the card's time it may take** (10% to 100%): see below.
* The page names the card in use (and the back end: Vulkan where there is one; the other real back ends, D3D12 and Metal, are the fall-back; a software renderer is never used) and says how much work it has done this session.

A picture smaller than about a third of a megapixel always runs on the processor, because the trip to the card would cost more than it saves.

## The limit

The picture goes to the card in **bands of rows**, each sized to keep the card busy for only a few milliseconds. After each band the card is left alone for as long as the limit asks, so over the whole picture it is busy for that share of the time:

* **100%**: no rest; the card works as fast as it can.
* **50%**: each band is followed by a rest as long as the work. The picture takes about twice as long and the card works half the time.
* **25%**: a rest three times as long: about four times as long overall.

Why lower it: the card (and its fan) stays cooler and quieter, the screen and other programs keep the rest of the card's time, and a laptop on battery lasts longer. The limit applies to previews, HQ renders and exports alike. Short rests are saved up and taken together, because a sleep of a few milliseconds lasts a whole clock tick on Windows and would rest far longer than asked. The card is never idle for longer than three quarters of a second at a time.

## If the card cannot be used

* No Vulkan driver, a driver that will not open, or the optional `wgpu` package missing: the processor does everything, as before. Settings > Graphics card says why.
* Any error while the card is working (a driver reset, out of memory): that picture and every later one are done on the processor, and the card is not tried again until the editor is restarted.
* The environment variable `PHOTOEDITOR_GPU=off` switches the card off whatever the settings say (the tests use it; so can you, to compare).

The card opens in the background when the editor starts (it takes about a second), so the first big picture does not wait for it.

## For developers

The code is in `src/photoeditor/features/gpu`: `device.py` (finding and opening the card, the only place that imports `wgpu`), `kernels.py` (the WGSL shader and the layout of the numbers it is given), `pipeline.py` (bands, buffers, falling back), `throttle.py` (the limit). `desktop/render.py` calls `gpu_pipeline.tone(...)` and `gpu_pipeline.vignette(...)` and runs the processor's own stages when they return `None`. `tests/test_gpu.py` compares the card's pictures with the processor's for every stage (it is skipped on a computer without a usable card).
