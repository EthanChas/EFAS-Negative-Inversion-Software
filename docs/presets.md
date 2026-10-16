# Presets: folders, My Presets and Built-in Presets

The **Presets** module (left column, under History) holds saved looks: tone, colour, film type, sharpening and watermark. Cropping, rotation and dust repairs are never part of a preset.

## My Presets and Built-in Presets

Two buttons at the top of the module choose which list shows.

- **My Presets** are the presets you made. Save the open photo's look with **Save Current...**; delete, rename, move and edit them (Advanced Preset Edit).
- **Built-in Presets** come with EFAS and cannot be changed. Select one to read what it is; **Apply** it (or double-click), apply it to the **roll** (**To Roll...**), or hover it to preview it on the picture first. **Copy to My Presets** makes an editable copy of it.

## Folders

A name with slashes is a path: **B&W/Number 1** is the preset *Number 1* inside the folder *B&W*, like the nesting of tags. A folder exists because a name runs through it; there are no empty folders to look after.

- Type the slashes into the name when you save or rename a preset (**Save Current...**, right-click > **Rename or Move...**).
- Right-click a **folder** for **Save Current Look Here...**, **Rename Folder...** (also moves it: rename `B&W` to `Film/B&W`) and **Delete Folder and Its Presets...**. A rename that would give a preset a name another already has is refused, and nothing changes.
- Saving with a preset or folder selected starts the name in that folder.
- Folders open and close with a click or double-click and stay as you left them.

The same goes for **Film Profiles** (Advanced mode): put slashes in a profile's name under **Edit Details...** (`Kodak/Portra 400/Roll 3`) and the profile list becomes a tree. In the drop-downs that choose a profile for an inversion the folders read `Kodak › Portra 400 › Roll 3`.

## The Scanners (DarkSlide) built-in presets

The five lab styles that ship with [DarkSlide](https://github.com/kilianvivien/DarkSlide) (MIT licence, (c) 2026 Kilian Vivien), carried over as they are defined there: a master tone curve, optional red / green / blue curves, and a saturation and a temperature nudge (DarkSlide's `saturationBias` and `temperatureBias` divided by 100). They use the Tone Curve module (all four curves) and the Color module's Saturation and Temperature, so they show up as curves on the graph and can be edited from there.

| Preset | What it does |
|---|---|
| Scanners (DarkSlide)/Frontier Classic | Warm, saturated colour with lifted blacks and a gentle shoulder (saturation +0.10, temperature +0.08) |
| Scanners (DarkSlide)/Frontier Modern | Cleaner highlights with a lighter Frontier-style colour signature (+0.03, +0.03) |
| Scanners (DarkSlide)/Noritsu | Cooler, straighter midtones with slightly firmer contrast (-0.02, -0.05) |
| Scanners (DarkSlide)/Neutral | A straight line and no bias, for grading by hand |
| Scanners (DarkSlide)/Agfa d-Lab | Cooler midtones with muted saturation and a slight green bias (-0.04, -0.03) |

DarkSlide's own "tonal character" overrides (shadow lift, highlight roll-off, midtone anchor) belong to its pipeline and are not carried over: the curves already hold the lifted blacks and the soft shoulder. The folder is named for where the styles come from; **Scanners (EFAS Original)** below holds EFAS's own looks, made with the Lab Look module.

## The Scanners (EFAS Original) built-in presets

| Preset | What it does |
|---|---|
| Scanners (EFAS Original)/Frontier 100 | A Fuji Frontier-style look at full strength: deeper shadows, a soft fade in the blacks, a gentle lift of the midtones, a gentle highlight roll-off, a little more saturation, warmth that is stronger in the shadows than the highlights and a faint green in the shadows |
| Scanners (EFAS Original)/Crystal 100 | A Fuji Crystal Archive paper-style look at full strength: richer, deeper blacks, a little less shadow detail, more saturation, a touch of warmth in the midtones |
| Scanners (EFAS Original)/Pakon (Clean and Rich) | A Pakon-style look: clean, bright highlights with a firm white, a slight saturation lift, otherwise neutral. Subtle: most of a Pakon scan's look is its colour response, which EFAS cannot copy |
| Scanners (EFAS Original)/Noritsu (Green Shadows) | A Noritsu-style look: lifted shadows, bright clean highlights with more separation, a faint green in the shadows, a modest saturation lift |

**What these are, and are not.** They are EFAS's own approximations, made by converting the tone, saturation, fade, glow and colour-balance settings of the matching scanner-look presets in another program's published list into EFAS's sliders. They are not measurements of the machines, not a copy of that program's presets, and not its colour lookup tables or camera profiles (those are not included). The 100 in *Frontier 100* and *Crystal 100* means full strength. Treat them as starting points and adjust by eye.

The conversion, from the other program's values (their scale is about 100 per unit). It is written as code in `features/lookpresets/lookconvert.py` and tested:

| Their setting | EFAS slider | Rule |
|---|---|---|
| Saturation | Saturation | value / 50 |
| Darks | Shadows | value / 100 |
| Lights | Highlights | value / 100 |
| Blacks | Print Response > Toe | value / 100 |
| Whites | Print Response > Shoulder | minus value / 100 |
| Fade | Lab Look > Fade | value / 50 (a negative value is kept) |
| Glow | Lab Look > Glow | value / 50 (a negative value is kept) |
| Blue/Yellow in shadows, mids, highlights | Lab Look > Warmth: Shadows, Midtones, Highlights | each value / 50, kept apart |
| Green/Magenta in shadows, mids, highlights | Lab Look > Magenta: Shadows, Midtones, Highlights | each value / 50, kept apart |
| Red/Cyan in shadows, mids, highlights | Color trim > Red | weighted 0.5, 0.3, 0.2, then / 100 (only when it is not zero) |
| The colour lookup table, tone profile, toning method | not used | EFAS has no equivalent |

The three tonal ranges of the colour balance are kept apart, not folded into one overall cast: a preset that is warm in the shadows and clean in the highlights comes out that way. The global Temperature and Tint of a converted look are left at zero, so the White Balance module stays yours.

## The Lab Look module

**Lab Look** (left column, under Print Response) holds what a lab's scanner adds to a print:

- **Fade** works on the shadows and runs from minus to plus. Plus compresses their tonality: smoother shadows with less detail and no pure black (at +1 the black rises by about a fifth of the display range, and the lift dies away quickly with brightness, so the midtones and the top stay put). Minus expands it: a deeper, cleaner black and more shadow contrast (the lower midtones rise by about an eighth of the range at -1).
- **Glow** works on the highlights and runs from minus to plus. Plus compresses their tonality: smoother, softer highlights with less visible detail, with the black and the top held, so the midtones rise a little to make room (up to about a tenth of the display range). Minus expands it: a starker look with more highlight detail and darker midtones. It is a tone curve, not a blur: it softens nothing and costs nothing per picture.
- **Warmth** and **Magenta** for the **shadows, midtones and highlights**, six sliders: warmer (+) or cooler (-), and toward magenta (+) or green (-), each only in its own tonal range (smooth, overlapping ranges, so there is no visible edge).

Both Fade and Glow run from -1 to +1 here, which is -50 to +50 on the program the built-in presets were converted from.

**How Fade and Glow were worked out.** The program's own description (Fade compresses the tonality of the shadows, Glow that of the highlights) and a measurement of its output agree; see also [what a lab look is](lab-look-research.md). Their shapes were measured, not guessed: the same photograph was converted in that program with its Glow at -50 and +50, and its Fade at -50 and +50, and the pictures were compared by brightness percentiles. Glow +50 against -50 moved the median from 98 to 149 (of 255) with the darkest tones unchanged and the brightest about the same, and it did not reduce fine detail, so it is a tone curve and not a bloom, and the top of the range bunched together (95th to 99th percentile 29 levels apart at -50, 6 apart at +50), which is the highlight compression the program describes. Fade +50 lifted the black frame around the picture from 1 to 50, tapering to nothing by the lower midtones; Fade -50 left it at pure black and raised everything from the lower midtones up by about 30 levels. The curves in `features/lablook/logic.py` are fitted to those numbers, so they are close, not exact: one photograph and two ends of each slider cannot pin down the whole curve.

It has an on/off light, a reset button and module presets like the other modules. All of it is curves of the tone ramp, applied after the tone curve and in the 16-bit chain.

## The Film Stocks built-in presets

Under **Film Stocks**, sorted by brand: **Cinestill/Cinestill**, **Fuji/Superia**, **Kodak/Gold**, **Kodak/Portra** and **Kodak/Portra Airy**. They are made the same way as the Scanners (EFAS Original) presets (the same conversion, from the film-look presets in the same published list), so everything said above applies: approximations of the stock's character in tone, saturation and warmth by tone, not a model of the film's colour. Kodak Gold is the warm one (warm, yellow shadows and midtones with clean highlights), Portra keeps its highlights soft and protected, Portra Airy lifts shadows and highlights. A film preset changes the picture the same way whatever film is in the scanner: use it as a starting point, not as proof of what the film looked like.

## Adding built-in presets

Built-in presets are JSON files in `src/photoeditor/assets/presets/`. Each file holds `{"presets": [{"name": "Folder/Name", "description": "...", "look": {...}}]}`, where `look` uses the slider keys of the Presets and Print Response modules (see `features/lookpresets/modules.py`). A new file in that folder appears in the Built-in Presets list the next time EFAS starts.

`tools/build_presets.py <folder>` rewrites the slider values of the built-in Scanners (EFAS Original) and Film Stocks presets from a folder of source files, using the conversion above.
