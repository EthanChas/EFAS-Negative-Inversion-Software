# How the modules stack

Every module works on the output of the one before it, in a fixed order. Nothing is applied twice and nothing overwrites another module's settings: each module owns its own numbers, saved with the photo, and the picture is rebuilt from the scan through the whole chain every time. Two modules that both touch brightness or colour *add up* (in the order below); they never fight over the same value.

## The order, top to bottom

1. **Frame and clean.** Straighten, distortion, keystone, flips, then dust and scratch repair.
2. **Edge Bleed** (Negative tab): Fill holder, Bleed repair and Edge dodge, on the picture after its geometry and before the crop and the conversion. The conversion therefore measures the repaired picture.
3. **Conversion** (Negative tab). The negative is turned into a positive: *Modern* (density, crosstalk, film curve, paper curve) or *Original* (stretch each channel between its darkest and lightest readings). Everything below works on this result.
4. **Colour trim** (Negative tab). The per-channel offsets, then White balance (temperature and tint).
5. **Exposure** (Tone tab). A gain in stops on the converted picture.
6. **Contrast**, then **Print Response** (Snap, Toe, Shoulder).
7. **Chroma Denoise, Local Contrast, Shadows & Highlights** and **Color** (saturation), when any of them is in use.
8. **Tone Curve.** The RGB curve first, then the red, green and blue curves, each on the output of the one before.
9. **Lab Look tone** (Fade, Glow, warm / magenta balance by tone). The tone curve and this come after steps 3 to 6 and are one lookup table.
10. **Colour in OKLCH**: Vibrance and the Color Mixer, then the Lab Look's scanner colour response, then **Color Toning** last.
11. **Sharpening**, then crop, **Edge Color** (on the cropped picture), **Vignette**, **Watermark**, the **Border mask** (Edge Bleed) and **Border** (Finishing).

When none of the steps in 7 is in use, steps 4 to 6, 8 and 9 are merged into one lookup table per channel; the order is the same.

Each tab follows this order, so working down a tab, and left to right across the tabs, is working in the order the picture is built.

## Which controls overlap

They do, and that is intended, because a photographer reaches the same result more than one way. Where the overlap is real:

| If you want | The controls that can do it | How they differ |
|---|---|---|
| The whole picture lighter or darker | **Print density** (Modern conversion), **Exposure**, a master **Tone Curve** point | *Print density* moves the picture along the paper's curve **before** the paper's toe and shoulder, so a darker print rolls off into the shoulder rather than clipping. *Exposure* is a straight gain on the finished picture, and can clip. A curve point does the same to a chosen tone only. Under Modern, set the overall level with Print density and keep Exposure for fine changes. |
| More or less contrast | **Grade** (Modern), **Contrast**, **Print Response**, the **Tone Curve** | *Grade* is the paper's slope; *Contrast* is a pivot around the middle after conversion; *Print Response* shapes the ends; a curve is any shape you draw. |
| A warmer or cooler picture | **Scanning light**, **Color trim**, **White balance**, the **red / green / blue curves**, **Lab Look balance by tone**, **Color Toning** | Trim and White balance move the whole picture; the channel curves and Lab Look balance work on tones; Color Toning tints a tone range toward any hue and keeps lightness. |
| A cleaner edge of the picture | **Flat Field**, **Edge Bleed** (repair, dodge, mask), **Vignette** | Flat Field evens out light that falls off smoothly across the whole frame; Edge Bleed removes light spilling in from the clear film and the sprocket holes, which is strongest at the border; Vignette is a creative darkening. |
| More colour | **Saturation** (Color), **Vibrance**, the **Color Mixer**, Lab Look **scanner colour** | Saturation is every colour equally; Vibrance favours the muted ones; the Mixer works on one colour range; the scanner response is a fixed look. |

None of these replaces another: using two of them moves the picture by both. If a picture looks wrong, the quickest check is the **power light** beside each module's name (click it to see the picture without that module while its settings are kept), and the **History** panel, which lists each change.

## Keeping track of what you have changed

- A module that has been changed shows a small grey **preset name** when it came from a preset, and the **power light** shows whether it is on.
- **Clear** in the Presets panel resets every module except Negative, as one undoable step.
- Applying a **preset** sets only the fields that preset names; all other modules stay as they were.
- Every change is a **History** step you can step back to, and a **Snapshot** keeps a whole state to return to.
