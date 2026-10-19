"""Tool guides for finishing a picture and getting it out of EFAS: vignette and border, the watermark, exporting, file formats, metadata and the proofing tools."""
from .logic import Lesson, Section

SECTIONS = [
    Section("finish", "Finish and export", "The last touches, then writing the finished pictures to disk: what each option does and why."),
]

LESSONS = [
    Lesson("finishing-module", "finish", "Finishing: vignette and border", "See how the vignette weights the corners, how the border grows the picture, and why both come last.",
           r"""
**Finishing** holds two touches that belong at the very end of the work, and it is applied after everything else, over the finished crop. That has a useful consequence: the vignette and the border are **not part of the histogram**, which describes the picture before they are added, so they never distort what you read from it.

## Vignette

A **vignette** darkens, or lightens, the picture towards its corners, drawing the eye to the centre. It is both an old photographic accident (lenses do it) and a deliberate technique.

**How it works.** EFAS draws a weight mask, built small (192 pixels on the long side) and enlarged smoothly to the picture's size. The weight is zero in the middle and grows towards the corners, along a smooth curve (a smoothstep) that starts at a distance set by **Size** and reaches its maximum at the corner. The distance is measured relative to the picture's own shape, so the shape of the vignette follows the frame: an ellipse on a 3:2 picture rather than a circle. A **positive** vignette multiplies each pixel by one minus the strength times the weight, so the corners go **darker**, towards black. A **negative** one moves each pixel *towards white* by the strength times the weight, so the corners get **lighter**.

**Vignette** is the amount (-1 to +1). **Size** (0 to 1) is how far out from the centre the picture is left completely alone: a bigger Size leaves more of the middle clear and confines the effect to the very corners, while a small Size starts darkening almost from the centre.

A **subtle** vignette (a low strength with a middle Size) is one of the oldest tricks for giving a scan a finished feel. A **light** vignette (negative) is a classic look for high-key portraits.

NOTE: A vignette *fixes* nothing. If your corners are dark because of uneven scanning light, correct that first with Flat Field ([[flat-field-module]]); adding a vignette on top is then a choice, not a repair.

## Border

**Border** surrounds the picture with a frame, in **white**, **black**, **grey** (a middle grey) or **warm paper** (a creamy off-white). Its width is a share of the picture's **shorter side**, up to 20%. The border is **added around** the picture rather than cut out of it: the finished picture is larger, by the border's width on every side. A thin white border mimics the border of a darkroom print and is lovely for sharing; a black one makes a picture look like a negative carrier's edge. Choose the colour to suit where it will be shown, not the picture.

The finishing touches are applied before any watermark: see [[watermark-module]].
""", keywords=("vignette", "border", "frame", "corners", "finishing", "print", "white border", "darken corners"), module="Finishing", see=("watermark-module", "flat-field-module")),

    Lesson("watermark-module", "finish", "Watermark: canister, text and marker", "Understand the four kinds of mark, how they position themselves, and how they become part of the exported picture.",
           r"""
A **watermark** in EFAS is anything added to the finished picture that is *not* part of the photograph: a stamp, a caption, a copyright line, a logo. There are four kinds, and they can be combined. Everything you place here is **part of the finished image**, so it is in exports too. Because it is added at the very end, it does not affect the histogram or any measurement.

## The four marks

**Canister** is a 3D film canister placed over the picture like a stamp, a nod to where the picture came from. **Film** picks the label (the built-in stocks are Fomapan 200, Ilford Delta 400 and Kodak Gold 200), **Texture** the body of the canister (aluminium, plastic or scuffed), **Size** how big it is and **Position** where it sits. **None** removes it.

**Camera and lens** writes the two lines of the gear used, in white, with a tiny credit line, either beside a canister or, without one (or with **Next to the canister** turned off), as a block of its own with its own position, size, colour and font. The **Camera** and **Lens** boxes, when left empty, use the ones from the **Roll Card**, which is another reason to fill that in first ([[roll-card-lesson]]).

**Text** is any words you type: a copyright line, your name, a caption; several lines are fine. Choose a **font** (any font installed on the computer, or a font file), **bold** or *italic*, a **colour** and an **Opacity**. **More text options** opens alignment, **line gap**, letter **spacing**, **rotation**, an **outline** and a **shadow**, which help make text readable over a busy part of the picture.

**Marker** adds your own mark: an **SVG**, which stays perfectly sharp at any size, or a picture such as a **PNG** with a transparent background. Markers are files in a **watermarks folder** and are chosen by name from a list: **Add...** copies a file into the folder, **Open Folder** shows it, **Reload** looks again, and three samples come with EFAS. A preset that uses a marker remembers its name, so it works on any computer that has a file of that name.

An SVG can be a **template**, the way darktable's watermarks are. Where it has `$(WATERMARK_TEXT)`, `$(WATERMARK_COLOR)` or the font variables, EFAS fills them in from the marker's own **Text**, **Colour** and **Font**, and the general variables work too: `$(CAMERA)`, `$(EXIF.YEAR)`, `$(FILM)`, `$(FILE.NAME)` and more, taken from the Roll Card and the frame. So one file can write `(c) 2024 Your Name` or the film and camera of every frame in a roll. **Variables...** lists every name with its value for the open photo, and the Text mark understands them too. The camera, lens and ISO are the film camera's, from the Roll Card ([[roll-card-lesson]]). Text and quotes in a value cannot break the SVG, because everything put into it is made safe first. **Scale on** chooses what the size is a share of: the picture's shorter side (the same look in portrait and landscape), its longer side, or the marker's width or height against the picture's, and **Rotate** turns the marker. See [[watermark-variables]] for the details.

## Placing the marks

Each mark has a **Position** menu. For finer control, tick **Move and resize on the picture**: you can then drag any mark with the mouse and drag a corner to resize it. As soon as you move a mark by hand its Position menu changes to **Custom**; choosing a position from the menu puts it back.

## Using it

Keep a watermark **small and quiet** if it is a credit: bottom corner, modest size, modest opacity. A large stamp over the middle of a picture ruins it. For a copyright line that is meant to deter copying, remember that a mark in a corner can simply be cropped off; one that is part of the picture is harder to remove but also more intrusive. If you export a picture for printing, think about whether you want a mark on it at all, since a watermark is baked into the exported pixels and cannot be removed later (your original, as always, is untouched).
""", keywords=("watermark", "canister", "text", "logo", "marker", "copyright", "camera", "lens", "signature", "svg", "png", "stamp", "credit"), module="Watermark", see=("watermark-variables", "roll-card-lesson", "exporting")),

    Lesson("watermark-variables", "finish", "Watermark variables and SVG templates", "Write a watermark once that fills in the film, camera, year or file name of every picture, the way darktable's watermarks do.",
           r"""
A watermark can write something different on every picture without you typing it each time. In the **Text** mark, in the marker's **Text** and inside an **SVG** marker, anything written as `$(NAME)` is replaced by what that name means for the picture: `(c) $(EXIF.YEAR) $(CAMERA)` becomes `(c) 1987 Pentax K1000`. This is the same idea, and the same `$(...)` writing, that darktable's watermark module uses, so an SVG made for darktable works here.

## What the names mean

**Variables...** in the Watermark tab lists every name with its value for the open photo, and a double-click copies one. The file gives `FILE.NAME` (without the extension), `FILE.EXTENSION` and `FILE.FOLDER` (the folder's name, not its whole path). Today's date gives `YEAR`, `MONTH`, `DAY` and the like. The frame's own date gives `EXIF.YEAR`, `EXIF.MONTH.LONG` and the rest of the `EXIF.` dates. The film and roll give `FILM`, `FILM.ISO`, `ROLL.NAME`, `ROLL.DEVELOPER`, `FRAME` and more, and the film camera gives `CAMERA`, `LENS` and `EXIF.ISO`. These come from the **Roll Card** ([[roll-card-lesson]]) and the frame's details, because the scan's own camera says nothing about the film. Inside an SVG marker there are five more, which EFAS fills in from the marker's own Text, Colour and Font: `WATERMARK_TEXT`, `WATERMARK_COLOR`, `WATERMARK_FONT_FAMILY`, `WATERMARK_FONT_STYLE` and `WATERMARK_FONT_WEIGHT`. A name that has nothing to give is empty, and a name EFAS does not know is empty too.

## Shaping a value

A few small additions after the name change how it comes out. A minus sign gives a default for an empty value, so `$(FILM-no film)` writes `no film` when the roll has no film, and the default may be another variable: `$(EXIF.YEAR-$(YEAR))`. A plus sign gives something to show only when the value is there, so `$(LENS+ - $(LENS))` writes a dash and the lens, or nothing. A colon cuts a piece out: `$(CAMERA:0:8)` is the first eight letters and `$(CAMERA:-4)` the last four. `^^` makes capitals and `,,` small letters (a single `^` or `,` does only the first letter), and `/old/new` swaps the first `old` for `new`, or every one with `//old/new`. Pieces are plain text, not patterns.

## Writing an SVG template

Draw the SVG in any editor and put the variables where the changing words go, for example `<text fill="$(WATERMARK_COLOR)">$(WATERMARK_TEXT)</text>`. Leave room in the drawing for the longest text, since text outside it is cut off. Put the file in the **watermarks folder** (the Marker section's **Open Folder** opens it) and press **Reload**. EFAS reads the file as text, fills in the variables and then draws it, so everything stays sharp at any size. Every value is made safe for XML on its way in, so a quote or an ampersand in a film name cannot break the file, and a value that looks like a variable is only text. Three samples come with EFAS: a line of text, a copyright line and a film and camera line.

TIP: A preset that uses a marker remembers its name, not the file, so before you send a preset to someone, give them the SVG too and tell them to put it in their watermarks folder.
""", keywords=("variables", "template", "darktable", "watermark", "svg", "marker", "$(", "exif", "camera", "film", "year", "file name"), module="Watermark", see=("watermark-module", "roll-card-lesson")),

    Lesson("exporting", "finish", "Exporting: presets, scopes and names", "Understand how the Export panel turns your edits into files: presets, what gets exported, where it goes, and what it is called.",
           r"""
Exporting is where all your edits are applied for real. EFAS never changes your scan: the edit is a recipe, and the Export panel *cooks* it into a new file, at the photograph's **full original resolution**, with every saved edit applied.

## Presets: what an export is

An export is described by a **preset**: a file format with its quality settings, a size, and options such as embedding a colour profile. EFAS comes with a set: **Web (2048 px JPEG)**, **Social (1080 px JPEG)**, **High quality JPEG (full size)**, **Print (full-size TIFF)**, **Archive (full-size PNG)**, **Modern web (WebP)**, and three that export the conversion alone for grading elsewhere (see [[export-formats]]). You **tick** the presets to export, and **each ticked preset writes its own file per photograph**, so one run can produce a web JPEG and an archive TIFF at once. Click a preset's name to edit its format, quality and size; changes save automatically. **New**, **Rename** and **Delete** manage the list.

## Scope: what is exported

Choose what to export: the **current image**, the **keepers** (the photos you marked with `K`) in the filmstrip's folder, and other scopes. In the Workbench, **Export Selected...** exports whatever you have selected. Virtual copies can be included, and their name is added to the file name.

## Where it goes and what it is called

You choose a destination **folder**, or have the files go in a subfolder **beside each original** (named Export unless you change it). **Date subfolders (DD-MM-YYYY)** file by the day of each photo. **Folder per preset** keeps presets of the same format apart. A file **name pattern** builds the name from tokens: `{name}` (the original's name), `{n}` (a running number), `{date}`, `{w}` and `{h}` (the size), `{format}`, `{roll}` and `{frame}` (from the Roll Card). You can add a **prefix** or **suffix** to a preset, too. If a file of that name already exists, EFAS by default **renames** the new one (adding `_1` and so on); you can choose to skip it or overwrite it.

## Quick Export

**Quick Export** (`Ctrl+E`, or File > Quick Export) exports the open image with the highlighted preset, immediately, with no choices to make. It is the fast way to get a picture out as you work.

## Good habits

Export from a picture that you have looked at in **HQ** (`Ctrl+H`), because the export is made at full resolution and the preview is not. Keep one **archive** preset (a full-size TIFF or PNG) and one **sharing** preset (a JPEG at a long edge you choose). Export the keepers as a batch when a roll is finished, and let the Roll Card write the film and camera into each file ([[export-metadata]]).
""", keywords=("export", "save", "jpeg", "png", "tiff", "presets", "quick export", "batch", "output", "scope", "file name", "pattern"), module="Export", see=("export-formats", "export-metadata")),

    Lesson("export-formats", "finish", "File formats, size and bit depth", "Choose between JPEG, PNG, TIFF and WebP, and understand the size, bit depth and sharpening options.",
           r"""
Every export preset makes four decisions: the **format**, the **size**, the **bit depth** and the **finishing options**. The right answer depends on where the picture is going.

## The formats

**JPEG** is the universal sharing format: small files that open everywhere. It is **lossy**, so it throws information away to save space. **Quality** sets how much (85 to 95 is visually indistinguishable from the original for most pictures) and **chroma subsampling** chooses whether colour is stored at full detail (4:4:4) or at half resolution (4:2:0), which is smaller and fine for the web but can blur thin coloured edges. JPEG is 8-bit only.

**PNG** is **lossless**: what goes in comes out exactly. It is good for archiving and for pictures with flat colours, and it can be 8- or 16-bit. Its compression setting only trades speed for file size, never quality. Files are large for photographs.

**TIFF** is also **lossless** (EFAS uses LZW compression, which only shrinks the file) and can be **16-bit**. It is the format for **printing** and for editing the picture further in another program. Files are large.

**WebP** is a modern web format, smaller than JPEG for the same quality, with either a quality setting or a lossless mode. Support is good, but not as universal as JPEG.

## Size

**Original** keeps the full resolution. **Long edge** sets the longer side to a number of pixels (2048 for the web is typical); **Percent** scales by a share; **Fit** fits the picture inside a box. **Don't upscale** (on by default) stops a small picture from being enlarged, and **Resample** chooses how it is shrunk (Lanczos by default, the sharpest). **DPI** is only a note in the file for printing: it changes nothing about the pixels.

## Bit depth

**8-bit** has 256 levels per channel and is enough for any finished picture. **16-bit** has 65,536 and matters for pictures you will keep **editing**: a strongly stretched tone leaves visible banding in 8 bits. EFAS keeps RAW and 16-bit scans at 16 bits through the conversion and every tone and colour edit (exposure, contrast, tone curve, shadows and highlights, saturation, colour, chroma denoise and local contrast), so a 16-bit TIFF export keeps that precision, unless sharpening, edge colour, a vignette, a border or a watermark is on ([[raw-and-bit-depth]]).

## Colour and sharpening

**Embed sRGB** stores a colour profile in the file so other programs show the colours as you saw them. **Grayscale** makes a black-and-white file. **Copy EXIF** carries the scan's camera information across. **Output sharpening** applies a final light sharpening for the size and format of the file: pictures made smaller for the web usually look better with a little, and sharpening for output should be the *only* sharpening done for that purpose, so if you set it here, keep the Sharpening module gentle ([[sharpening-module]]).

## Exporting without the look

Three built-in presets export the **conversion alone**, as 16-bit TIFFs, for finishing in other software: **Flat for grading** (the inversion and framing only, with no tone curve, contrast, colour or retouching), **Linear light** (the same with the display curve removed, for compositing) and **Density, log** (density above the film base, in a fixed range so the values can be converted back exactly). Each can also write a **conversion record**, a small file recording the source, the film base, the method and the settings.
""", keywords=("jpeg", "png", "tiff", "webp", "16-bit", "quality", "size", "resolution", "output sharpening", "flat export", "dpi", "srgb", "bit depth", "subsampling"), module="Export", see=("raw-and-bit-depth", "exporting")),

    Lesson("export-metadata", "finish", "Metadata in your exports", "Know what information goes into an exported file besides the picture, and where it comes from.",
           r"""
A picture file carries more than pixels. It also holds **metadata**: when it was taken, with what camera and lens, with what keywords, and who made it. Other programs, and anyone you send the file to, can read it. A scanned negative is a special case, because the file's own information describes the *scan*, not the photograph: the camera is whatever you scanned with, and the date is the day of the scan.

## What EFAS can write

With **Write roll card** on (in the **Roll Card Export** panel), the details of the roll (film, camera, lens, the days it was shot, how it was developed and scanned) and of the frame (its number, date, place and your note) are written into the **EXIF** and **XMP** of each exported file. That turns a file that says "scanned on a Canon EOS" into one that says "Kodak Portra 400, shot on a Pentax 6x7, October 1998".

With **Keep original EXIF** the scan's own information is left as it is, and nothing of the card is written.

**Tags** you have added are written into exported JPEGs as **Windows tags**, and kept in the **.xmp sidecar** next to your scan, where Lightroom and darktable read them as keywords.

## Why it matters

Metadata is what makes a picture **findable** and **attributable** later. A photo organiser can sort by film or lens; a family member can see the date a negative was *shot* rather than the day it was scanned. It costs a minute to fill in the Roll Card for a roll, and it pays back on every frame. Metadata is also information about you, so check what you are sharing: a place or a note you typed travels with the file.
""", keywords=("metadata", "exif", "xmp", "tags", "roll card", "copyright", "keywords", "windows tags", "sidecar"), module="Roll Card Export", see=("roll-card-lesson", "tags-and-collections")),

    Lesson("proofing-tools", "finish", "Proofing: test strip, ring-around and contact sheets", "Use the proofing tools to compare many variations at once instead of deciding from a single preview.",
           r"""
Judging a picture from one preview is hard, because the eye adapts: after a minute, almost any colour balance looks right. Photographers in a darkroom solved this a century ago by printing **test strips**, a series of exposures side by side, and choosing the one that looks best. EFAS has the same idea built in.

## Test Strip

**Test Strip** (`Shift+T`, or Edit > Test Strip...) prints the photograph at **25 exposure and contrast steps**, side by side, a grid of five exposures against five contrasts. You pick the one that looks right and it becomes the setting. It is the fastest way to find the right brightness and contrast for a frame that you cannot judge by eye.

## Ring-Around

**Ring-Around** (`Shift+F`, or Edit > Ring-Around...) does the same for colour. It steps the colour balance round the photograph in a **5 by 5 mosaic**, and the tile where a cast disappears shows you which way to move. It is the classic darkroom tool for finding a balance, and the best remedy for a colour cast you can see but cannot name.

## Before & after

**Before & after** (`\`) splits the picture so you can compare your edit with the original scan, which is a quick way to check that you have not drifted from where you started.

## Contact sheets

**File > Contact Sheet (PDF)...** puts every frame of the roll on **printable pages**, with its roll details, frame numbers, stars and flags, like the contact sheet a lab makes from a roll. It is useful for choosing which frames to print, and for keeping a paper record of a roll.

TRY: Open a picture with a cast, press `Shift+F`, and look for the tile where the grey things look grey. That tile shows you the correction in one look.
""", keywords=("test strip", "ring around", "contact sheet", "proof", "compare", "pdf", "variations", "darkroom", "split view", "before after"), see=("exposure-module", "recipe-colour-cast")),
]
