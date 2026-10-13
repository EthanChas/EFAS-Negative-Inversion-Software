# EFAS Negative Inversion Software

**Notice: this software is heavily under development and may have issues and bugs. Back up your photos and use it at your own risk.**

**AI Generated DESCRIPTION:** the changelogs, release notes, README and guides in this project are written by AI (Claude, by Anthropic), not by hand. Ethan, the author, would rather spend their time on the software than on writing changelogs, and an AI keeps them more consistent and better organised. MINOR Code correction. Ethan decides what gets built and how it should work. If something in the text is wrong or unclear, please open an issue.

A desktop editor for turning scanned or camera-scanned film negatives into finished positives. Open a negative (RAW, TIFF, PNG or JPEG), invert it, balance the colour and tone, retouch dust and scratches, then export, all non-destructively, with every edit stored per photo in a local database.

Built in **Python** with **PyQt6**. Created by Ethan.

## Features

- **Negative inversion and metering**: film-base sampling, per-channel balance, colour-negative and black-and-white modes, eyedropper picking
- **Exposure, tone curve, contrast, shadows/highlights, local contrast, sharpening, denoise, flat-field correction**
- **A short written read-out under the histogram**: exposure, contrast, range, clipping, colour, saturation and the channel averages on one line each, then the scan quality and a line on the negative; hover a row for the full detail
- **Dust and scratch removal**: manual spot and curved-scratch tools, a clone tool and AI dust detection. If automatic detection gets one wrong, show the detections, click that one with Delete Repair and only it is left alone (Reset Deleted brings them back)
- **Geometry**: crop with guides, straighten tool, automatic crop by border gradient
- **Finishing**: vignette and borders
- **Watermarks**: a 3D film canister, camera and lens text (with or without the canister), styled text in any installed font or font file (bold, italic, any colour, spacing, rotation, outline), and your own SVG or PNG logo. Drag any of them on the picture to move or resize them: the Position menu switches to Custom, and picking a corner from the menu puts it back
- **Library**: a Workbench grid with search by camera, lens, film, ISO, date, roll, rating and flag; stars, flags, tags, snapshots, history. Tags nest (`People/Family`; searching People finds everything inside it), the drop-down under the tag box lists every tag you have made so you never retype one, and `T` opens a quick tag bar: type a few letters and Enter adds the closest tag. A Tagging panel on the left of the editor and the Workbench works like darktable's: the tags on the open photo (or the selected photos, with counts), and the whole tag dictionary below as a list or a tree, with filter-as-you-type, suggestions, rename, change path, delete, and Lightroom keyword import and export. The edit history is saved with each photo, so it is all there, in order, when you reopen the app
- **Look presets** and per-module presets, copy and paste of settings between photos
- **Proofing tools**: test strip, ring-around, split view, contact sheets
- **Export**: JPEG, PNG and TIFF (16-bit supported), size and quality options, metadata and XMP, batch export
- **Scientific measurement (Advanced mode)**: linear RAW values, optical density, per-channel film base (Dmin) and Dmax, a density histogram, an H&D curve viewer for curve data you supply, and the calibration behind every number. See [the design document](docs/scientific-inversion-design.md)
- **Film characterization (Advanced mode, optional)**: calibrate your camera against a step tablet, fit a film's H&D curves from a strip exposed through one, save film profiles, and optionally convert with the measured curves. Never builds a curve from an ordinary photograph. See the [guide](docs/film-characterization-guide.md) and the [design document](docs/sensitometry-tier2-design.md)
- **Scanning quality and merging**: a plain scan-quality verdict, automatic film-border finding (confirmed before use), bracketed-exposure and one-light-per-colour scan merging into a measured 16-bit linear scan, roll consistency checks, and an optional colour-target accuracy fit. See the [scanning guide](docs/scanning-and-export-guide.md)
- **Flat exports**: flat, linear-light and density 16-bit TIFF outputs for grading elsewhere, with an optional conversion record
- **Shareable film profiles**: `.efasprofile` bundles that are checksummed, sanity-checked and imported as received, never as your own measurement
- **Undo for whole-roll actions**, **Find (Ctrl+K)** for any control or action, **Check Flat Field**, **Even Out Roll**, export safety checks, output sharpening and 16-bit TIFF export
- **Keystone correction** with an automatic suggestion from straight lines, **virtual copies** (several edits of one scan), **smart collections** and a **duplicate finder** in the Workbench
- **Command line**: `python -m photoeditor convert|presets|info|check-roll|merge`, using the editor's own data folder
- **Report a problem**: a redacted report you can read, save and attach to a GitHub issue; nothing is sent automatically
- **Updates**: Info > Version, with a startup notice when a new version is out (see Updates below)
- **Themes**: Default, Modern, Midnight, Graphite, Darkroom and High contrast, with accent colours and text size, plus your own themes as CSS files (Settings > Themes; see [docs/themes.md](docs/themes.md))
- **Film Colour Reference** (Extra menu, and the Negative tab): search a film stock and see photos shot on it, from lomography.com, in a clean gallery to judge a conversion's colour against (see Privacy below)
- **Same-size roll crops** (Crop Roll > "Make every crop the same size"), **preset preview on hover** (Presets list; Settings > General turns it off) and **scanning-light presets** (Negative > Color trim > Scanning light: a starting colour trim from the backlight's colour temperature, assuming a daylight camera white balance). The flat-field map now also ignores specks of dust on the light-source reference
- **Error marking** (Negative tab > Error marking, and View > Error Marks to show or hide): drag boxes round faults in a scan, each kind with its own colour and name tag (scratches red, watermarks yellow, transport lines dark navy, Newton rings, light leaks, dust and hairs, fingerprints, unknown). Right-click a mark to change or remove it. Marks are notes kept with the photo, follow the crop and rotation, and are never part of an export
- **Four-Corner Straighten** (Crop & Rotate): click the four corners of the photo, in any order, and the Angle and Keystone are set to make them a true rectangle, then cropped to it, in one undoable step
- **Module on/off lights**: a light beside each editing module's name (a square in the Classic theme, a circle with a grey border in the others); green is on, red is off. Click it to make the picture without that module while keeping its settings (per photo; the Negative module has no light)
- **Plugins** in **Python and Lua**: add menu items, modules, buttons and sliders to the editor, read and change the open photo, react to events, with a **Plugin Output** window under View (Settings > Plugins; see [docs/plugins](docs/plugins/README.md))
- **Data safety**: automatic backups, startup health check with restore, and full data export/import (Settings > Data & backup)

## Plugins

EFAS can be extended with plugins written in **Python** or **Lua** (Lua 5.4 is built in; nothing to install). A plugin can add menu items and modules (buttons, sliders, check boxes, drop-downs, text boxes) to the editor, read the open photo and change its edit the way the sliders do, measure the picture, apply presets, add tags, and react to events. Every plugin starts switched off; turn each on in **Settings > Plugins**, which also opens the plugins folder, installs five examples and makes an empty plugin to start from. **View > Plugin Output** opens a window with everything the plugins print and every error found in them.

Lua plugins run in a sandbox (no files, no programs, no internet, time-limited); Python plugins run with the same access as EFAS itself, so only switch on Python plugins you trust.

The documentation for plugin authors is in [docs/plugins](docs/plugins/README.md): [getting started](docs/plugins/getting-started.md), [the manifest](docs/plugins/manifest.md), [API reference](docs/plugins/api-reference.md), [UI and modules](docs/plugins/ui-and-modules.md), [events](docs/plugins/events.md), [Lua](docs/plugins/lua.md), [Python](docs/plugins/python.md), [Plugin Output and debugging](docs/plugins/plugin-output.md), [security](docs/plugins/security.md) and [examples](docs/plugins/examples.md).

## Privacy

The editor is **offline only**. No data is sent out: no analytics, no telemetry, no accounts, and your photos and edits never leave your computer.

The one thing it does online is ask the GitHub releases page for the latest version number, so it can tell you when an update exists (and download it if you choose to update). That is a plain web request, so GitHub sees your IP address the way any website does, and nothing else. You can turn the check off under Settings > General, and you can run the app with no internet connection at all.

The other online feature is the **Film Colour Reference**. It does nothing until you open it from the Extra menu or the Negative tab and agree to it once (Settings > General turns it off again). While its window is open it reads lomography.com's film list and the sample photos of the film you pick, only from lomography.com's own film pages (never its search, browse or API pages, which its robots.txt asks programs to avoid), with a User-Agent that says what it is. What you type in its search box stays on this computer (the film list is searched here), no information about you or your photos is sent, and lomography.com sees your IP address like any website does. The photos are shown, not saved or edited; they are by Lomography community members, so each shows who took it and links to its page. Only the film list (names and page addresses) is kept, for two weeks, in the data folder.

Your privacy is a right, and it will be respected.

## Updates

- **Info > Version** shows the installed version and checks for a newer one. **Info > Check for Updates...** does the same check directly.
- On start, if a newer version is available, the app says so and asks whether you would like to update.
- Choosing **Update** downloads the new `.exe` from the GitHub release, checks its size and SHA-256 checksum against what GitHub lists, replaces the running program and restarts it. Downloads are only accepted over https from GitHub's own hosts.
- Self-update works for the packaged Windows `.exe`. When running from source, the update button opens the release page instead.

## Credits and inspiration

The interface and module layout are based on and inspired by darktable. The editing features draw on the programs below. Please try them; they are excellent.

| Project | What it inspired | Link |
|---|---|---|
| darktable | The darkroom layout, module panels with presets and reset buttons, focus peaking | [darktable.org](https://www.darktable.org) |
| Adobe Lightroom | Culling with flags and stars, presets, histogram and clipping views, contact sheets | [adobe.com/products/photoshop-lightroom](https://www.adobe.com/products/photoshop-lightroom.html) |
| CineStill CS Negative+ Convert Tools | The idea of a fast, accurate film-scan conversion workflow | [cinestillfilm.com](https://cinestillfilm.com), [PetaPixel write-up](https://petapixel.com/2025/07/01/cinestills-new-film-scan-conversion-software-is-fast-accurate-and-free) |
| NegPy | Negative inversion and metering approach, dust and scratch repair, local contrast (CLAHE), clone tool. Parts of this app are adapted from its code (GPL-3.0) | [github.com/marcinz606/NegPy](https://github.com/marcinz606/NegPy) |
| FilmDefectNet | The small ONNX model behind AI dust detection | FilmDefectNet project |

Also built on [PyQt6](https://pypi.org/project/PyQt6/), [Pillow](https://python-pillow.org), [rawpy](https://github.com/letmaik/rawpy), [NumPy](https://numpy.org), [OpenCV](https://opencv.org) and [ONNX Runtime](https://onnxruntime.ai).

## How it was made

- Created in PyQt6 by Ethan.
- Changelogs, release notes and documentation are written by AI (Claude), because it is more effective and better organised than writing them by hand.
- UI design and interface are based on, and inspired by, darktable.
- Design, basic functionality and concepts by Ethan.
- Developed with the help of Claude (Anthropic) for code corrections, bug fixes and implementation work.

## Requirements

- **Python 3.10 or newer** (developed and tested on 3.13)
- Dependencies: PyQt6 >= 6.6, Pillow >= 10, rawpy >= 0.19, numpy >= 1.26, opencv-python-headless >= 4.8, onnxruntime >= 1.17, piexif >= 1.1, tifffile >= 2023.1, lupa >= 2.0 (the Lua interpreter for plugins)

## Supported systems

| OS | Status |
|---|---|
| Windows 10 / 11 | Supported (the released `.exe` is Windows only) |
| Linux | Runs from source (see below). Written to be portable but not yet tested on a real Linux machine by the author |
| macOS | Runs from source (see below). Written to be portable but not yet tested on a real Mac by the author |

The tests run on Windows, Linux and macOS through GitHub Actions (`.github/workflows/tests.yml`), so a problem on another system shows up there. Please report anything that looks wrong on Linux or macOS. Known differences: the self-updating `.exe` is Windows only (elsewhere Info > Version opens the release page); fonts follow the system; on a Mac the Delete key in the Workbench is the key labelled delete (Backspace); deleting photos uses the system Trash through the `send2trash` package.

## Download

Grab the single-file `.exe` from the [Releases](../../releases) page. There is nothing to install.

## Run from source

```bash
git clone https://github.com/EthanChas/EFAS-Negative-Inversion-Software.git
cd EFAS-Negative-Inversion-Software
python -m pip install PyQt6 Pillow rawpy numpy opencv-python-headless onnxruntime piexif tifffile lupa
```

On Linux and macOS also install `send2trash` (needed to move deleted photos to the Trash). On Linux, Qt needs a few system libraries; on Debian or Ubuntu: `sudo apt install libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0`.

On Windows, double-click `start.bat` (or run `start.bat console` to keep a console open for errors). On Linux and macOS run `./start.sh`. From any shell:

```bash
PYTHONPATH=src python -m photoeditor
```

On Windows PowerShell set the path first: `$env:PYTHONPATH = "src"`.

## Build the app

`python tools/build_app.py` builds for the system it runs on (a `.exe` on Windows, a `.app` on macOS, one executable on Linux), after `python -m pip install pyinstaller`. PyInstaller cannot build for another system. The **Build apps** workflow (Actions tab, run by hand) builds all three. The Windows command it wraps:

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name "EFAS Negative Inversion Software" --paths src --add-data "src/photoeditor/assets;photoeditor/assets" --hidden-import onnxruntime --hidden-import lupa.lua54 --collect-all lupa --exclude-module torch --exclude-module transformers --exclude-module tensorflow --exclude-module scipy --exclude-module numba --exclude-module matplotlib --exclude-module pandas --exclude-module tkinter --exclude-module sklearn --exclude-module sympy --exclude-module onnx run_app.py
```

The result is `dist/EFAS Negative Inversion Software.exe`. The excluded modules only keep the build small and fast.

## Tests

```bash
python -m pip install pytest
python -m pytest
```

## Where your data lives

Edits, presets, settings and backups are kept in `~/.photoeditor` (on Windows, `C:\Users\<you>\.photoeditor`). Set the `PHOTOEDITOR_DATA_DIR` environment variable to use a different folder.

## Symbols

Every icon and button glyph the app draws is rendered to the [`symbols`](symbols) folder for easy reference. Regenerate them with `python tools/export_symbols.py` (set `QT_QPA_PLATFORM=windows` on Windows so fonts render correctly).

## Licence

Copyright (C) 2026 Ethan.

This is free, open-source software, released under the [GNU General Public License v3.0](LICENSE). You are free to use, edit and redistribute it, as long as redistributed versions (modified or not) stay open source under the same licence. The GPL is used because parts of the app are adapted from [NegPy](https://github.com/marcinz606/NegPy), which is GPL-3.0.

There is no warranty of any kind.
