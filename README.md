# EFAS Negative Inversion Software

**Notice: this software is heavily under development and may have issues and bugs. Back up your photos and use it at your own risk.**

A desktop editor for turning scanned or camera-scanned film negatives into finished positives. Open a negative (RAW, TIFF, PNG or JPEG), invert it, balance the colour and tone, retouch dust and scratches, then export, all non-destructively, with every edit stored per photo in a local database.

Built in **Python** with **PyQt6**. Created by Ethan.

## Features

- **Negative inversion and metering**: film-base sampling, per-channel balance, colour-negative and black-and-white modes, eyedropper picking
- **Exposure, tone curve, contrast, shadows/highlights, local contrast, sharpening, denoise, flat-field correction**
- **Dust and scratch removal**: manual spot and curved-scratch tools, a clone tool and AI dust detection
- **Geometry**: crop with guides, straighten tool, automatic crop by border gradient
- **Finishing**: vignette, borders and a film-carrier frame; text and logo watermarks
- **Library**: a Workbench grid with search by camera, lens, film, ISO, date, roll, rating and flag; stars, flags, tags, snapshots, history
- **Look presets** and per-module presets, copy and paste of settings between photos
- **Proofing tools**: test strip, ring-around, split view, contact sheets
- **Export**: JPEG, PNG and TIFF (16-bit supported), size and quality options, metadata and XMP, batch export
- **Updates**: Info > Version, with a startup notice when a new version is out (see Updates below)
- **Data safety**: automatic backups, startup health check with restore, and full data export/import (Settings > Data & backup)

## Privacy

The editor is **offline only**. No data is sent out: no analytics, no telemetry, no accounts, and your photos and edits never leave your computer.

The one thing it does online is ask the GitHub releases page for the latest version number, so it can tell you when an update exists (and download it if you choose to update). That is a plain web request, so GitHub sees your IP address the way any website does, and nothing else. You can turn the check off under Settings > General, and you can run the app with no internet connection at all.

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
- UI design and interface are based on, and inspired by, darktable.
- Design, basic functionality and concepts by Ethan.
- Developed with the help of Claude (Anthropic) for code corrections, bug fixes and implementation work.

## Requirements

- **Python 3.10 or newer** (developed and tested on 3.13)
- Dependencies: PyQt6 >= 6.6, Pillow >= 10, rawpy >= 0.19, numpy >= 1.26, opencv-python-headless >= 4.8, onnxruntime >= 1.17

## Supported systems

| OS | Status |
|---|---|
| Windows 10 / 11 | Supported (the released `.exe` is Windows only) |
| Linux | Work in progress, untested |
| macOS | Work in progress, untested |

## Download

Grab the single-file `.exe` from the [Releases](../../releases) page. There is nothing to install.

## Run from source

```bash
git clone https://github.com/EthanChas/EFAS-Negative-Inversion-Software.git
cd EFAS-Negative-Inversion-Software
python -m pip install PyQt6 Pillow rawpy numpy opencv-python-headless onnxruntime
```

On Windows, double-click `start.bat` (or run `start.bat console` to keep a console open for errors). From any shell:

```bash
PYTHONPATH=src python -m photoeditor
```

On Windows PowerShell set the path first: `$env:PYTHONPATH = "src"`.

## Build the EXE

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name "EFAS Negative Inversion Software" --paths src --add-data "src/photoeditor/assets;photoeditor/assets" --hidden-import onnxruntime --exclude-module torch --exclude-module transformers --exclude-module tensorflow --exclude-module scipy --exclude-module numba --exclude-module matplotlib --exclude-module pandas --exclude-module tkinter --exclude-module sklearn --exclude-module sympy --exclude-module onnx run_app.py
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
