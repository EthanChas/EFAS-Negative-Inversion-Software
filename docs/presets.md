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

## The Lab Scanners built-in presets

| Preset | What it does |
|---|---|
| Lab Scanners/Frontier 100 | A Fuji Frontier-style look at full strength: deeper shadows, a soft fade in the blacks, a gentle highlight roll-off, a little more saturation, a warm and slightly green balance |
| Lab Scanners/Crystal 100 | A Fuji Crystal Archive paper-style look at full strength: richer, deeper blacks, a little less shadow detail, more saturation, a touch of warmth in the midtones |
| Lab Scanners/Pakon (Clean and Rich) | A Pakon-style look: clean, bright highlights with a firm white, a slight saturation lift, otherwise neutral. Subtle: most of a Pakon scan's look is its colour response, which EFAS cannot copy |
| Lab Scanners/Noritsu (Green Shadows) | A Noritsu-style look: lifted shadows, bright clean highlights with more separation, a faint green in the shadows, a modest saturation lift |

**What these are, and are not.** They are EFAS's own approximations, made by converting the tone, saturation and colour-balance settings of the matching scanner-look presets in another program's published list into EFAS's sliders. They are not measurements of the machines, not a copy of that program's presets, and not its colour lookup tables or camera profiles (those are not included). The 100 in *Frontier 100* and *Crystal 100* means full strength. Treat them as starting points and adjust by eye.

The conversion, from the other program's values (their scale is about 100 per unit). It is written as code in `features/lookpresets/lookconvert.py` and tested:

| Their setting | EFAS slider | Rule |
|---|---|---|
| Saturation | Saturation | value / 50 |
| Darks | Shadows | value / 100 |
| Lights | Highlights | value / 100 |
| Blacks, Fade | Print Response > Toe | (Blacks + Fade) / 100 |
| Whites | Print Response > Shoulder | minus Whites / 100 |
| Blue/Yellow in shadows, mids, highlights | Temperature | weighted 0.5, 0.3, 0.2, then / 50 |
| Green/Magenta in shadows, mids, highlights | Tint | weighted 0.5, 0.3, 0.2, then / 50 |
| Red/Cyan in shadows, mids, highlights | Color trim > Red | weighted 0.5, 0.3, 0.2, then / 100 (only when it is not zero) |
| Glow, tone profile, the colour lookup table | not used | EFAS has no equivalent |

EFAS has no separate colour balance for shadows and highlights, so the three tonal ranges are folded into one overall balance.

## The Film Stocks built-in presets

Under **Film Stocks**, sorted by brand: **Cinestill/Cinestill**, **Fuji/Superia**, **Kodak/Gold**, **Kodak/Portra** and **Kodak/Portra Airy**. They are made the same way as the Lab Scanners presets (the same conversion, from the film-look presets in the same published list), so everything said above applies: approximations of the stock's character in tone, saturation and warmth, not a model of the film's colour. Kodak Gold is the warm one (a yellow balance), Portra keeps its highlights soft and protected, Portra Airy lifts shadows and highlights. A film preset changes the picture the same way whatever film is in the scanner: use it as a starting point, not as proof of what the film looked like.

## Adding built-in presets

Built-in presets are JSON files in `src/photoeditor/assets/presets/`. Each file holds `{"presets": [{"name": "Folder/Name", "description": "...", "look": {...}}]}`, where `look` uses the slider keys of the Presets and Print Response modules (see `features/lookpresets/modules.py`). A new file in that folder appears in the Built-in Presets list the next time EFAS starts.
