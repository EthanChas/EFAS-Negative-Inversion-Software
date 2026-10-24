# Presets: folders, My Presets and Built-in Presets

The **Presets** module (left column, under History) holds saved looks: tone, colour, film type, sharpening and watermark. Cropping, rotation and dust repairs are never part of a preset.

## My Presets and Built-in Presets

Two buttons at the top of the module choose which list shows.

- **My Presets** are the presets you made. Save the open photo's look with **Save Current...**; delete, rename, move and edit them (Advanced Preset Edit).
- The **search box** above the list narrows whichever list is showing to the presets that have every word you type in their folder, name or, for the built-in ones, their description (so `warm lab` finds the built-ins whose description has both words). The folders the matches are in open by themselves and close again when you clear the box. Esc clears it, and Enter or the Down arrow selects the first preset found and moves to the list. A line under the box says how many presets are left, and when the list showing has none, how many the other one has.
- **Built-in Presets** come with EFAS and cannot be changed. Select one to read what it is; **Apply** it (or double-click), apply it to the **roll** (**To Roll...**), or hover it to preview it on the picture first. **Copy to My Presets** makes an editable copy of it.


## Organising My Presets

The **Organise** button beside the search box, and a right-click on a folder, a preset or empty space in the list, hold the tools for keeping a long list in order. They work on My Presets; the built-in list cannot be changed (a folder of it can be copied to My Presets).

- **New Folder...** makes a folder. It stays when it is empty, so you can set the folders up first and save into them later. A slash in the name makes one inside another: `Film/B&W` makes B&W inside Film (and Film, if it is not there). The name starts with the selected folder in it, so **New Subfolder** is the same command from a folder's right-click menu.
- **Move Selected to...** and **dragging** put a preset, or a whole folder, inside another folder; dropping on empty space puts it at the top level. A preset is never replaced: if the folder already has one with that name, nothing moves and a message says so. A folder cannot be moved into itself.
- **Duplicate** makes a copy next to the preset, called the same with " copy" added (" copy 2", and so on, if that is taken).
- **Remove Folder, Keep Its Presets** takes the folder away but not what is in it: its presets and folders move up one level, into the folder above (or the top level). A name that is already taken up there gets " copy" added, so nothing is replaced or lost. **Delete Folder and Its Presets** removes both, and asks first. An empty folder is removed without asking, and **Remove Empty Folders** clears every empty one at once.
- **Open All Folders** and **Close All Folders** do what they say. **Order Inside Folders** sets how presets are listed in each folder: in the order made (the default), A to Z, or Z to A, which turns the folders round as well. The choice is remembered.
- **Copy Folder to My Presets**, on a folder of Built-in Presets, copies every preset in it to My Presets, keeping the folders.

Folders that were made on purpose are kept in the same file as the presets (`look-presets.json` in the data folder, under `folders`), so a backup or a move of the data folder keeps them.

## Sharing presets (Export and Import)

Presets can be given to other people as a file and taken in from one. Under the list are **Export...** and **Import...**.

- **Export...** offers the **selected preset or folder** (a folder takes what is in it, folders inside it and the empty folders you made on purpose) or **All My Presets and Module Presets**. You choose where the file goes; its name ends in `.efaspresets` (it is plain JSON, so it can be read in a text editor). The same entries are in the right-click menu: **Export Preset...** on a preset, **Export Folder...** on a folder.
- A module's own presets (the little **Presets** menu in a module's header) can be exported too: **Export this module's presets...** writes just that module's, and **Import presets...** is in the same menu.
- **Import...** (also in the right-click menu of empty space in the list) reads a file, says what is in it, and adds the presets to **My Presets** and to the modules' presets. A file may hold both kinds. Nothing is added until you confirm. The folders in the file are made if you do not have them.
- **A name you already use.** If some presets in the file have names you already have, you are asked what to do with them: **Keep Both** (the default) adds the new one beside yours with ` (imported)` on its name (` (imported 2)` if that is taken too), **Replace Mine** puts the new one in the place of yours, **Skip Those** leaves them out, and **Cancel** adds nothing. Nothing of yours is changed unless you choose Replace Mine.

**What goes in the file.** The look a preset holds: tone, colour, film type, sharpening, watermark and the other settings of [the Presets module](#my-presets-and-built-in-presets), and the values of module presets. **Not** the photo, its crop, rotation or repairs (a preset never has those), and no date, name or account.

**Things that are left out or changed, and said so.** A preset can refer to something on your computer that other people do not have. A **watermark marker** chosen from the watermarks folder is written by its name only (the file itself is not put in the preset file; see [watermarks.md](watermarks.md)), and one chosen by a path on your disk is left out (the rest of the watermark is shared); a **film profile you made yourself** is replaced by the generic profile. After an export EFAS lists what was left out. A watermark that has **text** in it (a copyright line, say) is shared with the preset, because it is part of the look: the export and the import both say so, since the text is drawn on every picture the preset is put on. Look at a preset's watermark before you share it, and before you use one somebody sent.

**A file from someone else is checked, not trusted.** Every value is read against the setting it belongs to: a number must be a number and is pulled into the setting's range (an exposure of 9999 becomes the largest the slider allows), a choice must be one of the setting's choices, text is cut short, a curve must be a short list of points, and anything EFAS does not know is dropped. A preset that holds nothing usable is left out and counted. A file that is not a presets file, is far too big (over 8 MB), or was made by a newer EFAS than yours is refused with a message and nothing changes; a file with more than 1000 presets is read as far as the 1000th. The values are only ever used as numbers, text and choices: a presets file cannot run anything.

The format (`features/lookpresets/share.py`, tested in `tests/test_preset_share.py`):

```
{"format": "efas-presets", "version": 1, "made_by": "EFAS Negative Inversion Software 0.9.0",
 "look_presets": [{"name": "Film/Mine", "look": {"exposure_ev": 0.5, ...}}],
 "folders": ["Film/Empty"],
 "module_presets": {"exposure": [{"name": "Push a stop", "values": {"exposure_ev": 1.0}}]}}
```

Export presets (the file formats and sizes of the Export panel), camera and lens presets and film profiles are separate lists and are not part of this file.

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

## The Film Stocks (DarkSlide) built-in presets

DarkSlide's 78 film profiles (the same MIT-licensed source as above), in folders by maker: CineStill, Foma, Fuji, Generic, Harman, Ilford, Kentmere, Kodak, Lomography and Rollei. Slide films (Velvia, Provia, Ektachrome, Astia, and the like) are included, but EFAS inverts negatives, so for those only the look applies.

The conversion (`convert_darkslide_film` in `features/lookpresets/lookconvert.py`, tested; `tools/build_darkslide_presets.py` rebuilds the file from DarkSlide's `constants.ts`):

1. Contrast: (DarkSlide's Contrast - 10) / 100. Ten is its default.
2. Saturation: (Saturation - 100) / 100. A black-and-white stock is fully desaturated (-1).
3. Temperature and Tint: each divided by 100.
4. The stock's tonal character: its shadow lift above 0.05 (its Generic Color) times 3 is Lab Look's **Fade**, and its highlight roll-off above 0.5 times 0.6 is the Print Response **Shoulder**. Kodak Portra 400, with a lift of 0.15 and a roll-off of 0.70, gets a Fade of +0.30 and a Shoulder of +0.12; Kodak Ektar 100 (0.03, 0.30) gets a Fade of -0.06 and a Shoulder of -0.12.

Left out: Exposure, the red / green / blue balance, the black and white points, highlight protection, the colour matrices and the mask tuning. In DarkSlide those correct for its own inversion (the film base, the clip levels of its pipeline), so carrying them over would only shift EFAS's own conversion. The sizes are approximations, as with the other built-in sets.

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

## The Watermarks (EFAS Examples) built-in presets

Five examples of [watermarks](watermarks.md) that write the picture's own details (film, ISO, camera, lens, date, the roll's name, the frame's number) from the Roll Card and the frame through `$(NAME)` variables: a film credit in white or black (with the EFAS icon on its left), a film and camera line, a copyright line and a line of text with variables. They set the watermark only (the canister and the camera text are turned off, the tone and colour are left alone), and use the sample markers that come with EFAS, so they work on any computer. They are examples to apply, to learn from, or to copy to My Presets and change.

## The Papers (NegPy) built-in presets

Darkroom papers, ported from NegPy's paper profiles (GPL-3.0): **Foma Fomabrom Variant**, **Foma Fomatone MG Classic**, **Ilford Multigrade RC**, **Ilford Multigrade FB Classic** (in the *B&W* folder), **Kodak Endura Premier** and **Fujicolor Crystal Archive** (in *Colour (RA4)*), and **Neutral (default)** to go back. Each sets the five sliders of the **Print Response** module (Snap, Toe, Toe width, Shoulder, Shoulder width) and nothing else, so it adds a paper's tone curve to whatever look you have.

NegPy describes a paper by constants of its own characteristic curve (maximum and minimum density, how sharp the toe and the shoulder are, the midtone gamma). Print Response has five sliders instead, so the values here were **fitted**: `tools/fit_negpy_papers.py` runs NegPy's own curve code for neutral paper and for each paper at NegPy's default grade, with black point compensation on and Paper White off, turns both into display tones, and finds the slider values that make EFAS's neutral picture look like the same picture printed on that paper. The fit is within 0.1 to 0.4 of 255 tone levels everywhere. The papers differ from neutral only by 2 to 5 levels (rms), so these are subtle: they are a paper's *character*, a little more snap in the midtones and a softer shoulder, not a different picture.

Only the tone curve is carried over. NegPy's colour terms (the RA4 papers' channel gamma, dye matrix and base tint) and each B&W paper's lith colour path have no place in Print Response, and NegPy's own note says its values were loosely mapped from published datasheets, not calibrated (the Fuji paper is a rough estimate, as no curve is published for it).

## The Film Stocks built-in presets

Under **Film Stocks**, sorted by brand: **Cinestill/Cinestill**, **Fuji/Superia**, **Kodak/Gold**, **Kodak/Portra** and **Kodak/Portra Airy**. They are made the same way as the Scanners (EFAS Original) presets (the same conversion, from the film-look presets in the same published list), so everything said above applies: approximations of the stock's character in tone, saturation and warmth by tone, not a model of the film's colour. Kodak Gold is the warm one (warm, yellow shadows and midtones with clean highlights), Portra keeps its highlights soft and protected, Portra Airy lifts shadows and highlights. A film preset changes the picture the same way whatever film is in the scanner: use it as a starting point, not as proof of what the film looked like.

## Adding built-in presets

Built-in presets are JSON files in `src/photoeditor/assets/presets/`. Each file holds `{"presets": [{"name": "Folder/Name", "description": "...", "look": {...}}]}`, where `look` uses the slider keys of the Presets and Print Response modules (see `features/lookpresets/modules.py`). A new file in that folder appears in the Built-in Presets list the next time EFAS starts.

`tools/build_presets.py <folder>` rewrites the slider values of the built-in Scanners (EFAS Original) and Film Stocks presets from a folder of source files, using the conversion above.
