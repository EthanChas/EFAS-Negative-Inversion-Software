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

The finishing touches are applied before any watermark: see [[watermark-module]] and [[canister-watermark-module]].
""", keywords=("vignette", "border", "frame", "corners", "finishing", "print", "white border", "darken corners"), module="Finishing", see=("watermark-module", "canister-watermark-module", "flat-field-module")),

    Lesson("watermark-module", "finish", "Watermark: a marker on the picture", "Put an SVG or picture marker on the finished picture, sized and placed the way darktable's Watermark module does.",
           r"""
The **Watermark** module is ported from darktable's: a **marker** (an SVG, which stays perfectly sharp at any size, or a picture such as a PNG with a transparent background) laid over the finished picture. Everything it puts there is **part of the finished image**, so it is in exports too. It is added after the crop, the vignette and Edge Color and before the border, so it does not affect the histogram or any measurement. EFAS's own older watermarks (the film canister and the camera and lens text) are a separate module, [[canister-watermark-module]].

## The marker

Markers are files in a **watermarks folder** and are chosen by name from the **marker** list: **Add...** copies a file into the folder, **Open Folder** shows it, **Reload** looks again, and four samples come with EFAS. A preset that uses a marker remembers its name, so it works on any computer that has a file of that name. An SVG can be a **template**, the way darktable's watermarks are. Where it has `$(WATERMARK_TEXT)`, `$(WATERMARK_COLOR)` or the font variables, EFAS fills them in from the **text**, **font** and **color** here, and the general variables work too: `$(CAMERA)`, `$(EXIF.YEAR)`, `$(FILM)`, `$(FILE.NAME)` and more, taken from the Roll Card and the frame. So one file can write `(c) 2024 Your Name` or the film and camera of every frame in a roll. **Variables...** lists every name with its value for the open photo. A line of words, such as a copyright, is the **simple-text** marker. See [[watermark-variables]] for the details. **opacity** is how see-through it is.

## Sizing it: scale on

The size is worked out on the **cropped** picture, as darktable does it, and **scale** (1% to 500%) multiplies it. **scale on** chooses what the marker's size is measured against:

**image** measures a wide marker's width, or a tall one's height, against the picture's width or height, so 100% fits the picture the way a strip fits its width. **larger border** and **smaller border** measure the marker's longer side against the picture's longer or shorter side, and the smaller border gives the same look in portrait and landscape. **height** measures the marker's height against the picture's height. **advanced options** lets you choose both: **scale marker to** (the picture's width, height, larger or smaller border) and **marker reference** (the marker's width or height).

A marker's own size is counted in whole pixels, the way darktable counts it, so a strip stated as 100 by 5.5 is 100 by 6, and an SVG with no size stated is fitted into a large square.

## Placing it

**alignment** is a grid of nine places, from the top left to the bottom right. **x offset** and **y offset** move the marker from its place as a share of the picture (of the base width and height: the picture's own, except on the larger and smaller border, where both are that border). **rotation** turns it clockwise about its middle, and alignment allows for the turn, so a turned marker still sits against the corner it is aligned to. **Move and resize on the picture** lets you drag the marker with the mouse (the offsets follow, and the alignment stays) and drag a corner to resize it (scale follows).

## Using it

Keep a watermark **small and quiet** if it is a credit: bottom corner, modest size, modest opacity. A large stamp over the middle of a picture ruins it. For a copyright line that is meant to deter copying, remember that a mark in a corner can simply be cropped off; one that is part of the picture is harder to remove but also more intrusive. If you export a picture for printing, think about whether you want a mark on it at all, since a watermark is baked into the exported pixels and cannot be removed later (your original, as always, is untouched).
""", keywords=("watermark", "text", "logo", "marker", "copyright", "signature", "svg", "png", "stamp", "credit", "scale", "alignment", "offset", "rotate", "darktable"), module="Watermark", see=("watermark-variables", "canister-watermark-module", "roll-card-lesson", "exporting")),

    Lesson("canister-watermark-module", "finish", "Canister Watermark: canister and camera text", "EFAS's own original watermark: a film canister over the picture and the camera and lens written beside it.",
           r"""
**Canister Watermark** is EFAS's original watermark, kept as a module of its own beside darktable's [[watermark-module]]. It adds something to the finished picture that is *not* part of the photograph: a stamp that says where the picture came from. It is **part of the finished image**, so it is in exports too, and because it is added at the very end it does not affect the histogram or any measurement.

## The canister

A 3D film canister is placed over the picture like a stamp. **Film** picks the label (the built-in stocks are Fomapan 200, Ilford Delta 400 and Kodak Gold 200), **Texture** the body of the canister (aluminium, plastic or scuffed), **Size** how big it is and **Position** where it sits. **None** removes it.

## Camera and lens

**Add Camera and Lens** writes the two lines of the gear used, in white, with a tiny credit line, either beside a canister or, without one (or with **Next to the canister** turned off), as a block of its own with its own position, size, colour and font. The **Camera** and **Lens** boxes, when left empty, use the ones from the **Roll Card**, which is another reason to fill that in first ([[roll-card-lesson]]).

## Placing it

**Move and resize on the picture** lets you drag the canister or the camera text with the mouse and drag a corner to resize it. Dragging changes the **Position** (or **Size**) menu to **Custom**; choosing a position from the menu puts it back.

## The old text watermark

Earlier versions had a separate Text mark. A photo that still has one shows it here, with buttons to make it a marker (the simple-text marker of the Watermark module, where it can be edited) or to remove it.

## Using it

Keep it **small and quiet**: a canister in a bottom corner at a modest size. A big stamp over the middle of a picture ruins it. A mark is baked into the exported pixels and cannot be removed later (your original, as always, is untouched).
""", keywords=("canister", "film", "camera", "lens", "credit", "stamp", "watermark", "efas", "original", "text"), module="Canister Watermark", see=("watermark-module", "roll-card-lesson", "exporting")),

    Lesson("halation-module", "finish", "Halation: a simulated glow", "Understand what halation is, why a film scan already has it, and what the module's sliders do if you add more.",
           r"""
**Halation** is the soft red-orange glow round bright highlights that film makes: light goes through the emulsion, bounces off the back of the film and exposes it a second time. Because it happens in the film, **your scan of a negative already contains its own halation**. The Halation module (Color tab, under Edge Color) therefore does not recover anything; it makes a **simulated** extra glow, for a stronger look or for a scan whose capture lost some. It is off at **Amount** 0, and nothing in EFAS turns it on for you.

## The sliders

**Amount** is how strong the glow is. **Radius** is how far it spreads, as a share of the picture's shorter side, so the glow looks the same on a preview and on a full-size export. **Threshold** is how bright a part must be to glow: lower lets more of the picture glow, and above the brightest part nothing does. **Warmth** goes from a neutral glow (0) to the red-orange of film's halation (1).

## How it works

It takes the picture's highlights, blurs them, tints them and screens the result over the picture, so it can only brighten. It works on the finished, cropped picture, after Edge Color and before the vignette. Like the other modules it is saved with the photo, can be part of a preset, can be switched off with its power light and is undone with Ctrl+Z.

## When it is worth using

Halation shows most round small, very bright things on a dark ground: street lights at night, a lit window, the sun through leaves, a bright sky behind a branch. In those pictures a little glow can bring back the bloom a film stock without an anti-halation layer would have made. In an evenly lit daytime picture there is little over the threshold, so it has almost nothing to work on, and a high Amount only makes the highlights look dirty.

TIP: Be honest about it. A glow you add is a look you chose, not something the film did; keep it small, and compare with the highlights at 100% with the module off, so you know what the scan already had.
""", keywords=("halation", "glow", "bloom", "highlights", "red", "film look", "simulated"), module="Halation", see=("watermark-module", "lab-look-module")),

    Lesson("carrier-module", "finish", "Negative Carrier: the filed rebate", "Understand what a filed-out negative carrier prints, and what the module's sliders do.",
           r"""
In the darkroom a negative carrier whose aperture has been **filed out** larger than the frame prints the film's own **rebate**: the dark edge of the film between the picture and the filed metal, and past the metal a margin of bare paper. The edge is never clean: the film gate is a little uneven, the filed aperture is ragged, its corners are rounded, and light flares off the bevel. Printers use it as a signature, proof that the whole frame was printed. The **Negative Carrier** module (Finishing tab) simulates it, after NegPy's.

## The sliders

**Width** is how wide the rebate prints, in mm on a 30 cm print (0 is off); it scales with the picture, so a preview and a full-size export look the same. **Rough** is how ragged the filed edge is. **Corner** is how round the corners of the filed aperture are. **Flare** is the bright line light makes along the filed bevel.

## How it works

The pattern is fixed: one filed carrier for every frame, so the same photo always prints the same edge. It works on the finished, cropped picture, after the vignette and before the watermark and the border, and the picture is composited in linear light over white paper. The filed edge and the flare are exposure, so the more of the paper is exposed, the darker it prints.

## When it is worth using

It suits pictures meant as prints, in a frame or a book, where the black edge says the picture is whole. On a picture that will be cropped again or put on a busy page it only gets in the way.

TIP: It adds pixels that were never in the scan, so keep a copy without it; it cannot be taken out of an export.
""", keywords=("carrier", "rebate", "filed", "border", "frame", "edge", "black edge", "darkroom", "print"), module="Negative Carrier", see=("halation-module", "watermark-module")),

    Lesson("watermark-variables", "finish", "Watermark variables and SVG templates", "Write a watermark once that fills in the film, camera, year or file name of every picture, the way darktable's watermarks do.",
           r"""
A watermark can write something different on every picture without you typing it each time. In the Watermark module's **text** and inside an **SVG** marker, anything written as `$(NAME)` is replaced by what that name means for the picture: `(c) $(EXIF.YEAR) $(CAMERA)` becomes `(c) 1987 Pentax K1000`. This is the same idea, and the same `$(...)` writing, that darktable's watermark module uses, so an SVG made for darktable works here.

## What the names mean

**Variables...** in the Watermark tab lists every name with its value for the open photo, and a double-click copies one. The file gives `FILE.NAME` (without the extension), `FILE.EXTENSION` and `FILE.FOLDER` (the folder's name, not its whole path). Today's date gives `YEAR`, `MONTH`, `DAY` and the like. The frame's own date gives `EXIF.YEAR`, `EXIF.MONTH.LONG` and the rest of the `EXIF.` dates. The film and roll give `FILM`, `FILM.ISO`, `ROLL.NAME`, `ROLL.DEVELOPER`, `FRAME` and more, and the film camera gives `CAMERA`, `LENS` and `EXIF.ISO`. These come from the **Roll Card** ([[roll-card-lesson]]) and the frame's details, because the scan's own camera says nothing about the film. Inside an SVG marker there are five more, which EFAS fills in from the marker's own Text, Colour and Font: `WATERMARK_TEXT`, `WATERMARK_COLOR`, `WATERMARK_FONT_FAMILY`, `WATERMARK_FONT_STYLE` and `WATERMARK_FONT_WEIGHT`. A name that has nothing to give is empty, and a name EFAS does not know is empty too.

## Shaping a value

A few small additions after the name change how it comes out. A minus sign gives a default for an empty value, so `$(FILM-no film)` writes `no film` when the roll has no film, and the default may be another variable: `$(EXIF.YEAR-$(YEAR))`. A plus sign gives something to show only when the value is there, so `$(LENS+ - $(LENS))` writes a dash and the lens, or nothing. A colon cuts a piece out: `$(CAMERA:0:8)` is the first eight letters and `$(CAMERA:-4)` the last four. `^^` makes capitals and `,,` small letters (a single `^` or `,` does only the first letter), and `/old/new` swaps the first `old` for `new`, or every one with `//old/new`. Pieces are plain text, not patterns.

## Writing an SVG template

Draw the SVG in any editor and put the variables where the changing words go, for example `<text fill="$(WATERMARK_COLOR)">$(WATERMARK_TEXT)</text>`. Leave room in the drawing for the longest text, since text outside it is cut off. Put the file in the **watermarks folder** (the Watermark module's **Open Folder** opens it) and press **Reload**. EFAS reads the file as text, fills in the variables and then draws it, so everything stays sharp at any size. Every value is made safe for XML on its way in, so a quote or an ampersand in a film name cannot break the file, and a value that looks like a variable is only text. Four samples come with EFAS: a line of text, a copyright line, a film and camera line and the **EFAS film credit** (with the EFAS icon on its left), and the built-in presets under **Watermarks (EFAS Examples)** apply them with a position, size and colour already set.

If you already have SVGs from darktable, copy them into the watermarks folder: they work as they are. The names darktable accepts are understood, including the underscore spellings such as `$(EXIF_ISO)` and `$(EXIF_FOCAL_LENGTH)`, which give just the number as in darktable, and `$(Xmp.dc.creator)` gives the Artist the scanning camera wrote into the file. In EFAS the camera, lens and ISO are the film's, from the Roll Card, and the exposure comes from the Roll Card's Exposure box, so `1/125 f/8` there gives `1/125` and `8`.

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

**Before & after** (`\`) splits the picture so you can compare your edit with the picture right after inversion, which is a quick way to check that you have not drifted from where you started. The list beside the button lets you compare with any step of the History instead ("3. Exposure set to +0.60 EV"), so you can see what a later step did. Both sides are made at full resolution (HQ is switched on while the split is up and back as it was when it closes), so the Before is as sharp as the After.

## Contact sheets

**File > Contact Sheet (PDF)...** puts every frame of the roll on **printable pages**, with its roll details, frame numbers, stars and flags, like the contact sheet a lab makes from a roll. It is useful for choosing which frames to print, and for keeping a paper record of a roll.

TRY: Open a picture with a cast, press `Shift+F`, and look for the tile where the grey things look grey. That tile shows you the correction in one look.
""", keywords=("test strip", "ring around", "contact sheet", "proof", "compare", "pdf", "variations", "darkroom", "split view", "before after"), see=("exposure-module", "recipe-colour-cast")),
]
