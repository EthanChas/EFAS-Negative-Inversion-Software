<div align="center">

<img src="src/photoeditor/assets/icon/efas-logo.png" alt="EFAS logo" width="150">

# EFAS Negative Inversion Software

**Bring your film negatives to life.**

A free, open-source film-negative converter for your desktop.<br>
From a single scan to a whole roll: invert, grade, repair, organise and export, all locally and non-destructively.

[![Tests](https://github.com/EthanChas/EFAS-Negative-Inversion-Software/actions/workflows/tests.yml/badge.svg)](https://github.com/EthanChas/EFAS-Negative-Inversion-Software/actions/workflows/tests.yml)
&nbsp;[![Latest release](https://img.shields.io/github/v/release/EthanChas/EFAS-Negative-Inversion-Software)](../../releases)
&nbsp;[![Licence: GPL v3](https://img.shields.io/badge/licence-GPL--3.0-blue)](LICENSE)

[**Download for Windows →**](../../releases) &nbsp;·&nbsp; [**Run from source →**](#get-started)

[Features](#features) · [Presets](#presets) · [Plugins](#plugins) · [Get started](#get-started) · [Your data](#where-your-data-lives) · [Privacy](#privacy) · [Docs](#documentation)

</div>

---

> **Notice:** this software is heavily under development and may have issues and bugs. Back up your photos and use it at your own risk.

<details>
<summary><b>About this README (AI-written documentation)</b></summary>

&nbsp;

The changelogs, release notes, README and guides in this project are written by AI (Claude, by Anthropic), not by hand. Ethan, the author, would rather spend their time on the software than on writing changelogs, and an AI keeps them more consistent and better organised. MINOR Code correction. Ethan decides what gets built and how it should work. If something in the text is wrong or unclear, please open an issue.

Built in **Python** with **PyQt6**. Created by Ethan.

</details>

Open a negative (RAW, TIFF, PNG or JPEG), invert it, balance the colour and tone, retouch dust and scratches, then export. Every edit is stored per photo in a local database and nothing is ever written over your originals.

## Features

<details open>
<summary><b>Negative inversion and tone</b></summary>

&nbsp;

- **Negative inversion and metering**: film-base sampling, per-channel balance, colour-negative and black-and-white modes, eyedropper picking, **White / Black point droppers**
- **Scanning light** (Negative > Color trim): a starting colour trim from the colour temperature of the backlight the negative was photographed on
- **Exposure, tone curve, contrast, shadows/highlights, local contrast, sharpening, denoise, flat-field correction** (the flat-field map ignores specks of dust on the light-source reference)
- **Tone Curve** (Tone tab): an **RGB** curve and a **Red**, **Green** and **Blue** curve, each with its own tab, a graph you click to add a point, drag to move and double-click to remove, and **In** / **Out** boxes for the selected point. **Black**, **Grey** and **White** point pickers set the three colour curves from a spot you click on the picture (so that spot prints black, neutral grey or white), **Auto** sets each channel's black and white points from the picture, and **Reset** / **Reset All** put the curve, or all four, back to a straight line. The colour curves are saved, undone, copied and put in presets like the rest (see [how the modules stack](docs/how-modules-stack.md))
- **Module search**: a search box above the modules (Edit > Search Modules puts the cursor in it). Type a name, what you want to do (`tint`, `sharpen`, `dust`, `vignette`) or the name of a control, and every module that matches, from every tab, is gathered into one list in place of the tab that was showing, best match first (a few are opened at once). Clear the box or press Esc and each module goes back to its own tab, in its own place, and the tab that was showing opens again; clicking a tab does the same and opens that tab. It uses the same common words as Find (Ctrl+K), so `brightness` finds Exposure
- **Flat Field methods** (Negative tab, Flat Field > Method): **EFAS (original)**, **NegPy** and **Improved**. Both older methods smooth the gain map with a blur of 1/16 of the long side, which flattens the steep falloff at the borders and leaves the edges of a reference about 13% dark (18% in the corners); **Improved** blurs by 1/64 with the edge pixels repeated outward (a 5x5 median filter still keeps dust specks on the light out of the map) and leaves the edges within 1-3%. The reference each flat field was made from is kept with it, so switching the method makes the folder's and the permanent flat field again at once, without picking the reference again. See [the flat field page](docs/flat-field.md)
- **Edge Bleed** (Negative tab, under Flat Field): four tools for light that spills into a picture's edges from the clear film, the holder's gaps and the sprocket holes, which a flat-field map cannot fix. **Fill holder** paints what is outside the picture but not clear film with the film base; **Bleed repair** takes the scattered border light off the picture in linear light, with an **Auto strength** that fits it from the picture's own edge; **Edge dodge** flattens each edge's brightness profile (it needs no clear border); and a soft **Border mask** (black, grey or white) covers what is left, optionally kept out of the metering. See [the edge bleed page](docs/edge-bleed.md)
- **Print Response** (Tone tab): **Snap**, **Toe** and **Shoulder**, with a width for each roll-off, shape the picture's response curve the way a print's characteristic curve is shaped, drawn as a small graph
- **Module on/off lights**: a light beside each editing module's name (a square in the Classic theme, a circle with a grey border in the others); green is on, red is off. Click it to make the picture without that module while keeping its settings
- **Clipped shares on the histogram**: a ◀ and a ▶ in the graph's corner give the percent of the picture in the blocked shadows and the blown highlights; click one to mark those tones on the picture in blue or red (the same marks as the Shadow / Highlight Clipping buttons)
- **Histogram**: stays in view while the sidebar scrolls; **Log** scale and **Split** (red, green and blue in separate strips) buttons; the Color graph is greyed out for a black-and-white negative
- **A short written read-out under the histogram**: exposure, contrast, range, clipping, colour, saturation and the channel averages, then the scan quality; hover a row for the full detail

</details>

<details>
<summary><b>Retouching, geometry and finishing</b></summary>

&nbsp;

- **Dust and scratch removal**: manual spot and curved-scratch tools, a clone tool and AI dust detection. If automatic detection gets one wrong, show the detections, click that one with Delete Repair and only it is left alone (Reset Deleted brings them back)
- **Error marking** (Frame & Clean tab, and **View > Error Marks** or **Shift+E**): drag boxes round faults in a scan, each kind with its own colour and tag: scratches red, watermarks yellow, transport lines dark navy, Newton rings, light leaks, dust and hairs, fingerprints, unknown. Right-click a mark to change or remove it. Marks are notes kept with the photo, follow the crop and rotation, and are never part of an export
- **Geometry**: crop with guides, straighten tool, automatic crop by border gradient, **Four-Corner Straighten** (click the four corners of the photo and the Angle and Keystone are set to make them a true rectangle, then cropped, in one undoable step), keystone correction with an automatic suggestion from straight lines
- **Crop Roll** can make every crop the same size, each centred where its own border was found
- **Finishing**: vignette and borders
- **Watermarks**: a 3D film canister, camera and lens text (with or without the canister), styled text in any installed font or font file, and your own SVG or PNG logo. Drag any of them on the picture to move or resize them

</details>

<details>
<summary><b>Library and workflow</b></summary>

&nbsp;

- **Library**: a Workbench grid with search by camera, lens, film, ISO, date, roll, rating and flag; stars, flags, tags, snapshots, history; sort by name, date or number of photos
- **Tags** nest (`People/Family`; searching People finds everything inside it), with a drop-down of every tag you have made, a quick tag bar (`T`), and a Tagging panel like darktable's with Lightroom keyword import and export
- **Error marks in the Workbench**: search `error:yes`, `error:none`, `error:scratch` (or `-error:...`), pick **Errors** under Rating & Status, or save it in a smart collection, to find the photos that have faults marked on them (Negative tab > Error marking)
- **Folder icons** beside the folders in the editor's and the Workbench's Library, shut or open (Lucide icons from the icon folder)
- **Folder tools in the Library** (right-click any folder, in the editor or the Workbench): **New Folder...** makes a real folder inside it; **Rename Folder...** renames it on your disk, and its photos keep their edits, ratings, flags, tags, versions, history, the folder's flat field, Roll Card and film base, and their thumbnails; **Move Folder to...** (or drag the folder onto another, after a confirmation) moves it into another folder on the same drive the same way; **Move to Folder...** on photos (the Workbench's button and menu, the filmstrip menu) moves them, with their sidecars and edits, into a folder and never overwrites a name that is taken; **Delete Folder...** moves the folder and everything in it to the Recycle Bin after a confirmation that shows what is inside (the edits stay in EFAS, so a restored photo keeps its look); **Remove from Library** works on any folder, not only a root (a folder inside a root is left out of the list and the Workbench, its photos untouched, and **Bring Back Removed Folders** shows it again). The folders that were open stay open after any of these.
- **Slideshow** (the button before Workbench and Editor): plays the photos the Workbench is showing (its search and filters apply), the ones selected in it, or the editor's open folder, each **with its saved edits** (or as the scan is), made at the size your screen needs on a background thread with the next few made ahead. Choose the seconds per photo (1 to 120), a **cut or a crossfade**, **shuffle**, **loop** and **captions** (file name, film, roll, day). A **progress bar** along the bottom fills as the photo's time runs out and freezes with a pause. **Choose photos...** opens a grid of thumbnails with ticks (Select all / none / Invert) to leave photos out, **X** leaves out the one on screen, and **Restart** (or Home) goes back to the first photo and the start of the music. Space plays and pauses, the arrows step, **F** or a double-click goes full screen (Esc leaves, the cursor hides itself), C toggles captions. The settings are remembered. See [the slideshow page](docs/slideshow.md)
- **Slideshow music and video**: music plays while the slideshow plays, looped, at a volume you set: three built-in pieces made inside EFAS from sine waves, plucked strings and an electric-piano voice (so there is nothing to license), or your own **.wav and .mp3** files, which **Add music...** copies into EFAS's folder. **Export video...** makes the show into an **MP4**: a size from 720p to 4K, 24 to 30 frames a second, crossfades, captions burned in, with the music looped to the length of the video and faded out over its last two seconds. With [ffmpeg](https://ffmpeg.org) on the PATH (or chosen in the dialog) it is H.264 with AAC sound; without it, OpenCV's writer makes a silent MPEG-4 video
- **Classroom** (the view button between Maps and Workbench): a built-in guide for new people, and a fuller version of the **?** help on each tool. It has a **search box** and over a hundred guides in the order a beginner needs them: the basics of photography (light, exposure, the exposure triangle, histograms, white balance, sharpness, RAW), how film works, scanning film with a camera, getting around EFAS, then an **in-depth guide to every tool**, tab by tab (Convert, Frame & Clean, Tone, Color, Detail, Finish and export), explaining what it does to the picture, what each control really changes and when to use it. After those come working a whole roll, worked examples (your first roll, a colour cast, uneven light, dust, black and white, slide film, a tethered session) and a reference (the keyboard shortcuts as you have bound them, a glossary, troubleshooting, the Settings). **Show me** takes you to the tool a guide is about and flashes it, and the guide you were reading is remembered. See [the Classroom page](docs/classroom.md)
- **Graphics card (Vulkan) and a GPU limit** (Settings > Graphics card): the heaviest per-pixel stages - the colour work in OKLCH (Vibrance, the Color Mixer, the scanner colour response, Color Toning), shadows / highlights, saturation, the tone table and the vignette - run on your graphics card instead of the processor, through Vulkan (wgpu). On a 30 megapixel photo the colour work takes about 0.17 s instead of 53 s, and a preview about 0.03 s instead of 4.6 s. A **limit** slider (10% to 100%) makes the card work in short bands with a rest after each, so it is busy for only that share of the time: cooler, quieter, and the screen and other programs keep the rest. Denoise, sharpening, local contrast, geometry and dust repair still run on the processor. If there is no usable card, or it gives any trouble, the processor does everything as before. See [the graphics card page](docs/gpu.md)
- **Hotstack** (right-click a folder in a Library list, in the editor or the Workbench, and choose **Mark as Hotstack**): the folder's icon and name turn red, it is saved, and the folder is watched - it is the one your camera software saves into (Canon's EOS Utility over USB or Wi-Fi, for one). Each photo that lands in it is read into the library, selected in the Workbench and - **Show Each New Photo in the Editor**, on by default, in the flame button's menu in the Workbench's top bar, which shows while you are in a hotstack folder - opened in the editor with the negative converted, so you can check focus, exposure and the edges before the next frame. A photo is waited for until its file stops growing, so a RAW file still coming over Wi-Fi is never opened half-written; the day sub-folders EOS Utility makes are watched too, and the photos already in the folder are left alone. More than one folder can be a hotstack. **Retake This Photo** (the flame button's menu, right-click, File menu, only inside a hotstack folder): shoot the frame again and the next photo to arrive takes the old one's name and place, starting from its edits; the old one is set aside in a Retakes folder, never deleted. **Finish Session** (the top bar, and File menu, while you are in a hotstack folder and photos have arrived): moves the session's photos into a `DD-MM-YYYY` folder (the Export panel's date format) inside the hotstack, with their edits, ratings, flags, tags and the folder's flat field and Roll Card going along. See [the Hotstack page](docs/hotstack.md)
- **Find (Ctrl+K)** reaches any control, menu action, preset, module preset or smart collection
- **Virtual copies** (several edits of one scan), **smart collections**, a **duplicate finder**, and **undo for whole-roll actions**
- **Proofing tools**: test strip, ring-around, split view, contact sheets
- **Color Mixer** and a better colour model: Vibrance that spares skin tones and already-vivid colours, and Hue / Saturation / Lightness for eight colour ranges, all worked in OKLCH so a colour moves without dragging its lightness or hue along (see [the colour page](docs/color-mixer.md)); Lab Look also has a scanner colour response (Frontier, Noritsu, Pakon, Crystal Archive)
- **Color Toning** (Color tab): a hue and a strength for the shadows, the midtones and the highlights, a tint added in OKLab so the lightness stays put (split toning with a third region; see [the colour page](docs/color-mixer.md))
- **Edge Color** (Color tab): a Tint, Warmth and Light correction that grows toward the picture's edges, for a flash that lit the middle of the frame and left the edges to the room's own light (a green edge from fluorescent tubes, an orange one from tungsten) or a lens that darkens its corners; Flat Field cannot fix that, because it corrects the scanner's light and this is in the picture. **Auto match the colour** compares the outer band with the middle; **Size** and **Shape** (ellipse to rectangle) place it. It works on the cropped picture (see [the edge color page](docs/edge-color.md))
- **Lab Look**: Fade, Glow, and warm / cool and green / magenta balance for the shadows, midtones and highlights separately, the character a lab's scanner adds; the built-in Scanners (EFAS Original) and Film Stocks presets use it
- **Modern conversion** (default; **Original** is one dropdown away): a conversion that treats the film, the scene and the paper separately: dye crosstalk is taken out, part of the film's toe and shoulder is put back, and the picture prints through a paper curve with a toe and a shoulder, so highlights roll off instead of clipping. An **Encoding** setting (Automatic by default) reads each scan with the curve it was made with: BT.709 for a RAW file EFAS decodes, sRGB for other files, or Linear for a scanner TIFF saved without a curve. It can be measured against a film simulator (see [the design page](docs/film-and-paper-conversion.md))
- **16 bits all the way**: a RAW or 16-bit scan is kept at 16 bits through the conversion and every tone and colour edit (exposure, contrast, tone curve, shadows / highlights, saturation, colour, chroma denoise, local contrast, on the graphics card too) and is rounded to 8 bits once, at the end. A negative's narrow range, stretched, no longer shows gaps in the histogram, and a 16-bit TIFF export keeps its 16 bits unless sharpening, edge colour, a vignette, a border or a watermark is on
- **Steadier colour on a roll**: *Find Film Base for the Whole Roll* reads the clear border of several frames into one film base; an optional *linear camera RGB* RAW decode inverts the negative before the camera's colour matrix is applied (see the [scanning guide](docs/scanning-and-export-guide.md))
- **Check My Scanning Light** (Extra menu): from RAW photos taken with your scanning camera, measures whether your backlight is steady and even (bare-light photos over an hour: warm-up, colour drift, evenness, blown-out, same settings), and whether a roll of scans was made under a steady light and the right exposure (the clear film, the sprocket holes and the black holder in each scan tell a changed light from a changed exposure or a different film, and say what to change). It reads the sensor's own values and changes nothing
- **Export**: JPEG, PNG and TIFF (16-bit supported), size and quality options, metadata and XMP, batch export, output sharpening, export safety checks
- **Film Colour Reference** (Extra menu, and the Convert tab): search a film stock and see photos shot on it, from lomography.com, in a clean gallery to judge a conversion's colour against (see [Privacy](#privacy))
- **Command line**: `python -m photoeditor convert|presets|info|check-roll|merge`, using the editor's own data folder

</details>

<details>
<summary><b>Scientific measurement and film science (Advanced mode)</b></summary>

&nbsp;

- **Scientific measurement**: linear RAW values, optical density, per-channel film base (Dmin) and Dmax, a density histogram, an H&D curve viewer for curve data you supply, and the calibration behind every number. See [the design document](docs/scientific-inversion-design.md)
- **Film characterization (optional)**: calibrate your camera against a step tablet, fit a film's H&D curves from a strip exposed through one, save film profiles, and optionally convert with the measured curves. Never builds a curve from an ordinary photograph. See the [guide](docs/film-characterization-guide.md) and the [design document](docs/sensitometry-tier2-design.md)
- **Scanning quality and merging**: a plain scan-quality verdict, automatic film-border finding (confirmed before use), bracketed-exposure and one-light-per-colour scan merging into a measured 16-bit linear scan, roll consistency checks, **Check Flat Field**, **Even Out Roll**, and an optional colour-target accuracy fit. See the [scanning guide](docs/scanning-and-export-guide.md)
- **Flat exports**: flat, linear-light and density 16-bit TIFF outputs for grading elsewhere, with an optional conversion record
- **Shareable film profiles**: `.efasprofile` bundles that are checksummed, sanity-checked and imported as received, never as your own measurement. Film profiles can be sorted into folders (`Kodak/Portra 400/Roll 3`)

</details>

<details>
<summary><b>Look and feel</b></summary>

&nbsp;

- **Themes**: **Modern** (the default), Default, Midnight, Graphite, Darkroom and High contrast, with accent colours and text size, plus your own themes as CSS files (Settings > Themes; see [docs/themes.md](docs/themes.md))
- **Dividers** between the sections inside the modules, and modules that close when you switch tabs (a setting)
- **Keyboard shortcuts** for the common actions, all rebindable in Settings > Keybinds

</details>

<details>
<summary><b>Safety and updates</b></summary>

&nbsp;

- **Data safety**: automatic backups, startup health check with restore, and full data export/import (Settings > Data & backup)
- **Report a problem**: a redacted report you can read, save and attach to a GitHub issue; nothing is sent automatically
- **Updates**: Info > Version, with a startup notice when a new version is out (see [Updates](#updates))

</details>

## Presets

<details>
<summary><b>Preset folders, built-in presets and hover preview</b></summary>

&nbsp;

- **Folders**: a name with slashes (`B&W/Number 1`) is a preset inside a folder, like the nesting of tags. The Presets list and the Film Profiles list show them as a tree; right-click a folder to save into it, rename it or delete it.
- **Organise** (the button beside the Presets search box): make **folders** (an empty folder stays, and a slash makes one inside another, like `Film/B&W`), make a **subfolder** inside the selected one, **Move Selected to...**, **Duplicate**, **Remove Folder, Keep Its Presets** (what is inside moves up a level; a name already taken up there gets "copy" added, so nothing is replaced) or **Delete Folder and Its Presets**, **Remove Empty Folders**, open or close every folder, and choose the **order inside folders** (the order made, A to Z or Z to A; it is remembered). Drag a preset or a folder onto another folder, or onto empty space for the top level. A folder of Built-in Presets can be copied to My Presets whole.
- **My Presets and Built-in Presets**: two buttons switch the list between the presets you made and the ones that come with EFAS (read-only; **Copy to My Presets** makes an editable copy).
- **Search**: a search box above the Presets list narrows the list that is showing to the presets that have every word you type in their folder, name or (for the built-in ones) description, with the folders they are in opened. `warm lab` finds the built-ins whose description has both words; Esc clears the box, and Enter or the Down arrow picks the first one found. It says how many are left, and when this list has none, how many the other list has.
- **Built-in sets**: **Scanners (EFAS Original)** (Frontier 100, Crystal 100, Pakon, Noritsu), **Scanners (DarkSlide)** (the five lab styles of the open-source program DarkSlide, as tone curves: Frontier Classic, Frontier Modern, Noritsu, Neutral, Agfa d-Lab), **Film Stocks (DarkSlide)** (DarkSlide's 78 film profiles, by maker, from Kodak Portra to Ilford HP5 to Lomography) and **Film Stocks** (Cinestill, Fuji Superia, Kodak Gold, Portra, Portra Airy). They are EFAS's own approximations of the tone, saturation and warmth of those looks, not measurements.
- **Hover preview**: rest the mouse on a preset to see it on the picture before applying it (Settings > General turns it off). **Clear** takes the look off the photo again.

See [docs/presets.md](docs/presets.md) for how the built-in presets were made and how to add your own.

</details>

## Plugins

<details open>
<summary><b>Extend EFAS with Python or Lua</b></summary>

&nbsp;

EFAS can be extended with plugins written in **Python** or **Lua** (Lua 5.4 is built in; nothing to install). A plugin can add menu items and modules (buttons, sliders, check boxes, drop-downs, text boxes) to the editor, read the open photo and change its edit the way the sliders do, measure the picture, apply presets, add tags, and react to events.

- Every plugin starts **switched off**; turn each on in **Settings > Plugins**, which also opens the plugins folder, installs five examples and makes an empty plugin to start from.
- **View > Plugin Output** opens a window with everything the plugins print and every error found in them.
- **Lua plugins run in a sandbox** (no files, no programs, no internet, time-limited). **Python plugins run with the same access as EFAS itself**, so only switch on Python plugins you trust.

**Documentation for plugin authors** ([start here: docs/plugins](docs/plugins/README.md)):

| Page | What is in it |
|---|---|
| [Getting started](docs/plugins/getting-started.md) | Your first plugin in ten minutes, in Lua and Python |
| [The manifest](docs/plugins/manifest.md) | `plugin.json` and where plugins live |
| [API reference](docs/plugins/api-reference.md) | Every function, for both languages |
| [UI and modules](docs/plugins/ui-and-modules.md) | Menu items, modules, buttons, sliders and the rest |
| [Events](docs/plugins/events.md) | Reacting to a photo opening, the edit changing and more |
| [Lua](docs/plugins/lua.md) / [Python](docs/plugins/python.md) | What each language can use and how it behaves |
| [Plugin Output and debugging](docs/plugins/plugin-output.md) | Finding your plugin's output and errors |
| [Security](docs/plugins/security.md) | What a plugin can and cannot do |
| [Examples](docs/plugins/examples.md) | Five complete plugins to read and copy |
| [How it is built](docs/plugins/internals.md) | For people changing EFAS itself |

</details>

## Get started

<details open>
<summary><b>Download (Windows)</b></summary>

&nbsp;

Grab the single-file `.exe` from the [Releases](../../releases) page. There is nothing to install, and it updates itself from **Info > Version**.

</details>

<details>
<summary><b>Run from source (Windows, Linux, macOS)</b></summary>

&nbsp;

```bash
git clone https://github.com/EthanChas/EFAS-Negative-Inversion-Software.git
cd EFAS-Negative-Inversion-Software
python -m pip install -e .
```

(That installs every dependency, including `send2trash` on Linux and macOS, which moves deleted photos to the Trash. To install them by hand instead: `python -m pip install PyQt6 Pillow rawpy numpy opencv-python-headless onnxruntime piexif tifffile lupa wgpu send2trash`.)

On Linux, Qt needs a few system libraries; on Debian or Ubuntu: `sudo apt install libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0`.

On Windows, double-click `start.bat` (or run `start.bat console` to keep a console open for errors). On Linux and macOS run `./start.sh`. From any shell:

```bash
PYTHONPATH=src python -m photoeditor
```

On Windows PowerShell set the path first: `$env:PYTHONPATH = "src"`.

</details>

<details>
<summary><b>Supported systems</b></summary>

&nbsp;

| OS | Status |
|---|---|
| Windows 10 / 11 | Supported. The released `.exe` is Windows only |
| Linux | Runs from source. The automated tests run on it, but the author has not yet used it on a real Linux machine |
| macOS | Runs from source. The automated tests run on it, but the author has not yet used it on a real Mac |

The tests run on Windows, Linux and macOS through GitHub Actions ([`tests.yml`](.github/workflows/tests.yml)), so a problem on another system shows up there. Please report anything that looks wrong on Linux or macOS. Known differences: the self-updating `.exe` is Windows only (elsewhere Info > Version opens the release page); fonts and default text sizes follow the system; on a Mac the Delete key in the Workbench is the key labelled delete (Backspace); deleting photos uses the system Trash through the `send2trash` package.

</details>

<details>
<summary><b>Requirements</b></summary>

&nbsp;

- **Python 3.10 or newer** (developed and tested on 3.13)
- Dependencies: PyQt6 >= 6.6, Pillow >= 10, rawpy >= 0.19, numpy >= 1.26, opencv-python-headless >= 4.8, onnxruntime >= 1.17, piexif >= 1.1, tifffile >= 2023.1, lupa >= 2.0 (the Lua interpreter for plugins), wgpu >= 0.32 (the graphics card, through Vulkan; without it, or without a Vulkan card, everything runs on the processor)

</details>

<details>
<summary><b>Build the app</b></summary>

&nbsp;

`python tools/build_app.py` builds for the system it runs on (a `.exe` on Windows, a `.app` on macOS, one executable on Linux), after `python -m pip install pyinstaller`. PyInstaller cannot build for another system. The **Build apps** workflow (Actions tab, run by hand) builds all three. The Windows command it wraps:

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name "EFAS Negative Inversion Software" --paths src --add-data "src/photoeditor/assets;photoeditor/assets" --hidden-import onnxruntime --hidden-import lupa.lua54 --collect-all lupa --exclude-module torch --exclude-module transformers --exclude-module tensorflow --exclude-module scipy --exclude-module numba --exclude-module matplotlib --exclude-module pandas --exclude-module tkinter --exclude-module sklearn --exclude-module sympy --exclude-module onnx run_app.py
```

The result is `dist/EFAS Negative Inversion Software.exe`. The excluded modules only keep the build small and fast.

</details>

<details>
<summary><b>Run the tests</b></summary>

&nbsp;

```bash
python -m pip install pytest
python -m pytest
```

</details>

## Where your data lives

<details open>
<summary><b>The EFAS data folder</b></summary>

&nbsp;

Everything EFAS keeps for itself lives in **one folder, `.EFAS`, in your home folder**:

| System | Default location |
|---|---|
| Windows | `C:\Users\<you>\.EFAS` |
| macOS | `/Users/<you>/.EFAS` |
| Linux | `/home/<you>/.EFAS` |

Set the `PHOTOEDITOR_DATA_DIR` environment variable to use a different folder. **Settings > Data & backup** shows the folder, backs it up and exports or imports everything.

**Upgrading from an older version:** versions before 0.6 kept their files in `~/.photoeditor` under vaguer names. The first start of a newer version moves everything across by itself into `.EFAS` and removes the old folder, so there is nothing to do.

What is inside:

| In `.EFAS` | What it holds |
|---|---|
| `photo-edits.db` | Every photo's edits, history, ratings, flags, roll cards, snapshots, tags and error marks |
| `workbench-index.db` | The Workbench's index of your library, so search and sorting are quick |
| `app-settings.json` | Settings > Preferences: theme, keybinds, switches, which plugins are on |
| `window-and-panel-layout.ini`, `last-session.json`, `recent-folders.json` | Where the window, panels and last folder were |
| `look-presets.json`, `module-presets.json` | Your presets (My Presets and each module's presets) |
| `camera-and-lens-presets.json`, `camera-and-lens-lists/`, `remembered-metadata.json` | Camera and lens names and the details EFAS remembers for the Roll Card |
| `film-profiles/`, `camera-setups/` | Film profiles and camera set-ups from Advanced mode |
| `database-backups/` | The daily database backups (`photo-edits-YYYY-MM-DD.db`) |
| `plugins/` | Your plugins, one folder each (**Settings > Plugins > Open plugins folder**) |
| `plugin-data/` | What each plugin saves: its settings and files |
| `themes/` | Theme files you imported |
| `thumbnail-cache/`, `ai-dust-cache/`, `font-list-cache.json`, `film-reference-films.json` | Caches; safe to delete, they are rebuilt (Settings > Storage clears them) |
| `logs/` | The program's log, used by Report a Problem |

Next to your **photos**, EFAS also writes a small `.xmp` sidecar file for each edited photo, so an edit travels with the picture. Your original photo files are never changed.

</details>

## Privacy

<details>
<summary><b>What goes online (very little)</b></summary>

&nbsp;

The editor is **offline only**. No data is sent out: no analytics, no telemetry, no accounts, and your photos and edits never leave your computer.

The one thing it does online is ask the GitHub releases page for the latest version number, so it can tell you when an update exists (and download it if you choose to update). That is a plain web request, so GitHub sees your IP address the way any website does, and nothing else. You can turn the check off under Settings > General, and you can run the app with no internet connection at all.

The other online feature is the **Film Colour Reference**. It does nothing until you open it from the Extra menu or the Convert tab and agree to it once (Settings > General turns it off again). While its window is open it reads lomography.com's film list and the sample photos of the film you pick, only from lomography.com's own film pages (never its search, browse or API pages, which its robots.txt asks programs to avoid), with a User-Agent that says what it is. What you type in its search box stays on this computer (the film list is searched here), no information about you or your photos is sent, and lomography.com sees your IP address like any website does. The photos are shown, not saved or edited; they are by Lomography community members, so each shows who took it and links to its page. Only the film list (names and page addresses) is kept, for two weeks, in the data folder.

**Plugins** are the one place EFAS cannot promise this for you: a Python plugin can do anything Python can, including going online. Lua plugins cannot. See [plugin security](docs/plugins/security.md).

Your privacy is a right, and it will be respected.

</details>

## Updates

<details>
<summary><b>How updating works</b></summary>

&nbsp;

- **Info > Version** shows the installed version and checks for a newer one. **Info > Check for Updates...** does the same check directly.
- On start, if a newer version is available, the app says so and asks whether you would like to update.
- Choosing **Update** downloads the new `.exe` from the GitHub release, checks its size and SHA-256 checksum against what GitHub lists, replaces the running program and restarts it. Downloads are only accepted over https from GitHub's own hosts.
- Self-update works for the packaged Windows `.exe`. When running from source, the update button opens the release page instead.

</details>

## Documentation

<details>
<summary><b>All the guides</b></summary>

&nbsp;

| Guide | What it covers |
|---|---|
| [Plugins](docs/plugins/README.md) | Writing plugins in Python and Lua: API, UI, events, security, examples |
| [Presets](docs/presets.md) | Folders, My and Built-in presets, how the built-in ones were made |
| [Themes](docs/themes.md) | The built-in themes and writing your own as a CSS file |
| [Classroom](docs/classroom.md) | The built-in guides: what is in them, in what order, and how they are written |
| [Hotstack](docs/hotstack.md) | Watching a camera's folder, retaking a frame, finishing a session |
| [Graphics card](docs/gpu.md) | Vulkan rendering and the GPU limit |
| [Scanning and export guide](docs/scanning-and-export-guide.md) | Scan quality, merging scans, flat exports |
| [Film characterization guide](docs/film-characterization-guide.md) | Calibrating, fitting film curves, saving film profiles |
| [Scientific inversion design](docs/scientific-inversion-design.md) | How the measured conversion works |
| [Sensitometry design](docs/sensitometry-tier2-design.md) | Film profiles, camera set-ups and the curve-informed inversion |

</details>

## Credits and inspiration

<details>
<summary><b>Projects that inspired EFAS</b></summary>

&nbsp;

The interface and module layout are based on and inspired by darktable. The editing features draw on the programs below. Please try them; they are excellent.

| Project | What it inspired | Link |
|---|---|---|
| darktable | The darkroom layout, module panels with presets and reset buttons, focus peaking | [darktable.org](https://www.darktable.org) |
| Adobe Lightroom | Culling with flags and stars, presets, histogram and clipping views, contact sheets | [adobe.com/products/photoshop-lightroom](https://www.adobe.com/products/photoshop-lightroom.html) |
| CineStill CS Negative+ Convert Tools | The idea of a fast, accurate film-scan conversion workflow | [cinestillfilm.com](https://cinestillfilm.com), [PetaPixel write-up](https://petapixel.com/2025/07/01/cinestills-new-film-scan-conversion-software-is-fast-accurate-and-free) |
| NegPy | Negative inversion and metering approach, dust and scratch repair, local contrast (CLAHE), clone tool, the Snap / Toe / Shoulder response, the print-stage approach behind the Modern conversion, and the sixteen film crosstalk profiles it bundles (unchanged, GPL-3.0). Parts of this app are adapted from its code (GPL-3.0) | [github.com/marcinz606/NegPy](https://github.com/marcinz606/NegPy) |
| Lucide | The panel and tool-rail icons, loaded from `src/photoeditor/assets/icon` as plain SVG files (ISC licence) | [lucide.dev](https://lucide.dev) |
| DarkSlide | Ideas for roll-wide same-size crops, previewing a profile on hover and scanning-light settings | [github.com/kilianvivien/DarkSlide](https://github.com/kilianvivien/DarkSlide) |
| lightdrift | The method behind Check My Scanning Light: measuring a scanning light's brightness, colour and evenness from raw sensor values, and judging a roll from its clear film border, sprocket holes and holder. Re-written as EFAS's own code (MIT) | [github.com/davidesqalv/lightdrift](https://github.com/davidesqalv/lightdrift) |
| Pakon F-X35 scanner reference | An outside check on the Modern conversion's density step: how the Pakon scanners turn a colour negative into a positive, from reverse engineering and hardware checks (documentation, CC BY 4.0). Nothing is copied; see [the design page](docs/film-and-paper-conversion.md) | [github.com/alibosworth/pakon-reference](https://github.com/alibosworth/pakon-reference) |
| FilmDefectNet | The small ONNX model behind AI dust detection | FilmDefectNet project |

Also built on [PyQt6](https://pypi.org/project/PyQt6/), [Pillow](https://python-pillow.org), [rawpy](https://github.com/letmaik/rawpy), [NumPy](https://numpy.org), [OpenCV](https://opencv.org), [ONNX Runtime](https://onnxruntime.ai) and [Lupa](https://github.com/scoder/lupa) (Lua).

</details>

<details>
<summary><b>How it was made</b></summary>

&nbsp;

- Created in PyQt6 by Ethan.
- Changelogs, release notes and documentation are written by AI (Claude), because it is more effective and better organised than writing them by hand.
- UI design and interface are based on, and inspired by, darktable.
- Design, basic functionality and concepts by Ethan.
- Developed with the help of Claude (Anthropic) for code corrections, bug fixes and implementation work.

</details>

## Symbols

<details>
<summary><b>Every icon and glyph</b></summary>

&nbsp;

Every icon and button glyph the app draws is rendered to the [`symbols`](symbols) folder for easy reference. Regenerate them with `python tools/export_symbols.py` (set `QT_QPA_PLATFORM=windows` on Windows so fonts render correctly).

</details>

## Licence

Copyright (C) 2026 Ethan.

This is free, open-source software, released under the [GNU General Public License v3.0](LICENSE). You are free to use, edit and redistribute it, as long as redistributed versions (modified or not) stay open source under the same licence. The GPL is used because parts of the app are adapted from [NegPy](https://github.com/marcinz606/NegPy), which is GPL-3.0.

There is no warranty of any kind.
