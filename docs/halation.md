# Halation

Real film has **halation**: light that passes through the emulsion bounces off the back of the film and exposes it a second time, round bright highlights, as a soft red-orange glow. **A scan of a negative already contains the film's own halation**, so the **Halation** module (Color tab, under Edge Color) recovers nothing. It makes a **simulated** extra glow, for a stronger look or for a scan whose capture lost some of it. It is off at Amount 0, and nothing in EFAS (no preset that comes with it, no default) turns it on for you.

- **Amount:** how strong the glow is. 0 is off.
- **Radius:** how far it spreads, as a share of the picture's shorter side (so the glow looks the same on a small preview and a full-size export).
- **Threshold:** how bright a part of the picture must be to glow, as display luminance (0.3 to 0.98). Lower lets more of the picture glow; at a threshold above the brightest part, nothing does.
- **Warmth:** 0 is a neutral glow, 1 is the red-orange of film's halation.

It works on the finished, cropped picture (8-bit), after Edge Color and before the vignette, by taking the picture's highlights, blurring them, tinting them and **screening** the result over the picture (`1 - (1 - picture) * (1 - amount * glow)`), so it can only brighten, never darken. Like every module it is saved with the photo, is part of a preset's look, can be switched off with its power light, and is undone with Ctrl+Z. See `features/halation/logic.py` and `tests/test_halation.py`.

If you want to know how much of the film's own glow your scan has before adding any, look at the highlights at 100% with Halation off.
