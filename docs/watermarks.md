# Watermarks: markers, SVG files and variables

The **Finish** tab (with Finishing) has two watermark modules. **Watermark** is darktable's: a **marker** (an SVG or a picture) sized and placed exactly as darktable's module does it. **Canister Watermark** is EFAS's own original watermarking: a film **canister** and **camera and lens** text (see the end of this page). They are drawn at the end, after the crop and before the border, so they are in every export and have no effect on the histogram or any measurement.

This page is about the **marker** and the **variables**, which work the way darktable's watermark module works, so an SVG written for darktable can be used here.

## How darktable does it, and what EFAS takes from it

darktable's watermark module keeps a list of SVG (and PNG) files in a `watermarks` folder, with a reload button; you pick one by name. It reads the SVG as text and replaces `$(NAME)` placeholders before drawing it: its own `$(WATERMARK_TEXT)`, `$(WATERMARK_COLOR)`, `$(WATERMARK_FONT_FAMILY)`, `$(WATERMARK_FONT_STYLE)` and `$(WATERMARK_FONT_WEIGHT)`, filled in from the module's Text, Colour and Font controls, and the general variables of the image (the file name, the Exif date, the camera). Its size can be a share of the image, of its larger or smaller border, or of its height, or (advanced) any picture dimension against either marker dimension; the mark can be rotated, faded and placed on a nine-cell grid with offsets.

EFAS does all of that with darktable's own arithmetic (see [How the marker is sized and placed](#how-the-marker-is-sized-and-placed)), with these differences, on purpose:

- **Everything put into an SVG is made safe.** Every value that goes into the file has `& < > " '` turned into XML entities, so a Roll Card with an ampersand or a quote in a name cannot break the file or add elements to it. (darktable leaves quotes alone.)
- **A value is never read for variables again.** A film called `$(FILE.NAME)` shows that text; it does not become the file name.
- **The camera, lens and ISO are the film camera's.** `$(EXIF.MAKER)`, `$(EXIF.MODEL)`, `$(EXIF.LENS)` and `$(EXIF.ISO)` give the camera, lens and film speed of the **Roll Card** and the frame's own details (the scan's own Exif says nothing about the film), and the film-scanner names are there as well (`$(FILM)`, `$(ROLL.NAME)`, ...). So a darktable SVG that writes the camera writes the film camera here.
- **`$(FILE.FOLDER)` is the folder's name,** not its whole path, so a watermark does not tell people how your disk is laid out.
- The marker has its **own** text, font and color. There is no separate Text section any more: a line of text is the `simple-text.svg` sample marker. A photo that was given a Text watermark by an earlier version still shows it, and the Canister Watermark module then offers **Make it a Marker** (the same words, size, colour, font and place, as one line) or **Remove It**.
- Besides SVG and PNG, a marker can be a JPEG, WebP, BMP or TIFF picture; it is sized and turned like a PNG.
- **Your old darktable SVGs open as they are.** The names darktable accepts in its own SVGs work here: the underscore spellings (`$(EXIF_ISO)`, `$(EXIF_FOCAL_LENGTH)`, `$(EXIF_APERTURE)`, `$(EXIF_EXPOSURE)`, `$(EXIF_YEAR)`...) are read as the dotted names, `$(EXIF.FOCAL.LENGTH)`, `$(EXIF.APERTURE)`, `$(EXIF.EXPOSURE)` and `$(EXIF.ISO)` are the number only (as in darktable, so `$(EXIF_FOCAL_LENGTH)mm f/$(EXIF_APERTURE)` reads `50mm f/2`), `$(EXIF.DATE)` is the frame's date, and `$(Xmp.dc.creator)` and `$(Xmp.dc.rights)` are the Artist and Copyright of the scan's own Exif. Copy the files into your watermarks folder (**Add...**, or the folder itself) and they are in the list. A name EFAS does not know comes out empty. (darktable leaves some of those as literal text, and matches names in exact case; EFAS ignores case.)
- Not carried over: darktable's tag, rating, colour label and the other `Xmp.dc.*` variables.

## The watermarks folder

Markers live in a **watermarks folder** in EFAS's data folder (`~/.EFAS/watermarks`, or whatever your data folder is). Four samples come with EFAS and are listed with "sample" after their names:

- `efas-film-credit.svg`: the EFAS film credit: the EFAS icon on the left, then the film and its ISO in bold, a short rule, the camera and lens, and the date and *Edited with EFAS Negative Inversion Software* in small letters. Everything but the icon comes from the Roll Card and the frame. The icon is inside the file (a small picture), so the marker still works when you copy it to another computer.
- `simple-text.svg`: one line of text in the colour and font you choose.
- `copyright-line.svg`: `(c) 2024 Your Name`: the year of the frame (this year if the frame has no date) and your text.
- `film-frame-info.svg`: two lines from the Roll Card: the film and its ISO, and the camera and lens. A part with nothing to show is left out.

**marker** (a list, with **None** first) chooses one by its file name. **Reload** looks in the folder again after you have put a file there, **Open Folder** opens it in Explorer, and **Add...** copies a file you choose into the folder and uses it. A file of yours with the name of a sample hides the sample. A name that is already taken gets `_2` and so on: nothing is overwritten.

Because a marker is chosen **by name**, a preset or a file that uses `signature.svg` works on any computer that has a file of that name in its watermarks folder. A marker chosen before this existed was chosen by its whole path; that still works where the file is. A marker that is not there is shown as *Missing* and is not drawn; put a file of that name in the folder and press Reload.

SVG files can be drawn in any editor (Inkscape, say). The SVG's own size sets the shape of the marker: leave room for the longest text it will have, since text outside the drawing is cut off. Qt's SVG renderer draws it, which covers shapes, paths, gradients and basic text; very new SVG features may not appear.

## Example presets

The built-in presets (Presets > **Built-in Presets** > **Watermarks (EFAS Examples)**) are ready-made watermarks that write the picture's own details, to apply as they are or to learn from. Each sets the whole watermark: it turns off the canister and the camera and lens text and sets one marker, with its position, size and colour.

- **Film credit, bottom left, light** and **dark**: the `efas-film-credit.svg` marker in white or black.
- **Film and camera line, bottom centre**: `film-frame-info.svg`, two quiet lines.
- **Copyright line, bottom right**: `copyright-line.svg` with the example name `Your Name`; change it in the **text** box.
- **Roll and frame line, top left**: `simple-text.svg` with variables in its Text (the roll's name, the frame's number and the file name).

Fill in the **Roll Card** first (film, ISO, camera, lens, dates): that is where the words come from. A preset that uses a sample marker works on any computer, because the samples come with EFAS. Apply one, then press **Variables...** to see what the picture will say, and change the text, color, scale or alignment in the Watermark module as you like. **Save Current...** in the Presets module keeps your version as one of your own presets.

## How the marker is sized and placed

This is darktable's own arithmetic (its watermark module's `process()`), measured on the **cropped** picture, before the border:

- **The marker's own size** is a whole number of pixels, as darktable counts it: an SVG's stated width and height, rounded (so a strip stated as 100 by 5.5 is 100 by 6), or one stated side and the shape of its viewBox; an SVG with no size stated is its viewBox fitted into a 32767 pixel square. A picture is its pixel size. The drawing is fitted into that size in proportion and centred, with room for text that runs a little outside it.
- **scale on** says what the marker's size is measured against, and **scale** (1% to 500%) multiplies it:
  - **image**: a wide marker's width, or a tall one's height, is the picture's width or height. At 100% a caption strip spans the picture whatever its size.
  - **larger border** / **smaller border**: the marker's longer side is the picture's longer / shorter side.
  - **height**: the marker's height is the picture's height.
  - **advanced options**: **scale marker to** (image width, image height, larger or smaller image border) and **marker reference** (marker width or height) are chosen separately.
- **alignment** is nine places, row by row from the top left. A turned marker is aligned by the box round it, so it sits against the corner it is aligned to however it is turned. The middle row and column are the picture's middle.
- **x offset** and **y offset** (-1 to 1) move the marker from its place, as shares of the **base** width and height: the picture's own width and height, except on the larger and smaller border, where both are that border.
- **rotation** (-180 to 180 degrees, clockwise is plus) turns the marker about the middle of its box.
- It is blended as darktable does: each pixel of the marker has its alpha times the **opacity**, and the picture shows through what is left.

Because everything is a share of the picture, a marker comes out the same in a preview and in an export of any size. A marker many times the picture (500% of a border) is drawn only where it is on the picture, so it costs no more than the picture does.

## The controls

Which of **text**, **font** and **color** can be used depends on the marker: they are available when the SVG has the matching variable, and greyed out for a picture or an SVG that has its own text and colours. The line under the marker list says what the chosen marker takes.

- **marker**, **Reload**, **Add...**, **Open Folder**, **Variables...**: as above. **Variables...** lists every variable with its value for the open photo; double-click a row to copy its name.
- **text:** up to 511 characters. It may hold variables: `(c) $(EXIF.YEAR) $(CAMERA)`.
- **font, B, I:** a font installed on this computer (or a font file) with bold and italic.
- **color:** white, black or any colour.
- **opacity**.
- **Placement:** **rotation**, **scale**, **scale on** (with **scale marker to** and **marker reference** when it is advanced options), **alignment**, **x offset** and **y offset**, as above. The scale slider goes to 100%, and the box beside it takes any size up to 500%.
- **Move and resize on the picture:** tick it, then drag the marker with the mouse to move it, and drag a corner to resize it. The alignment stays, and **x offset** and **y offset** show how far you moved it, so the sliders and the mouse do the same thing; **scale** follows a resize. It works for the canister and the camera and lens text of Canister Watermark too, and the box is one setting for both modules.

The marker's **text** understands variables too, as in `(c) $(EXIF.YEAR) $(CAMERA)`.

## Markers made with an earlier version

A photo or preset made before the Watermark module followed darktable stored a marker's size as a share of the picture, a position and a margin. It is read as the same marker with darktable's settings: the size becomes **scale** with the matching **scale on** (shorter side is **smaller border**, longer side **larger border**, fit the picture **image**, width and height **advanced options**), and the position and the move become an **alignment** and offsets (the old margin of 3% of the shorter side becomes an offset, worked out for a 3:2 picture). Nothing else changes, and once it is saved it is stored in the new form. A size over 500% is kept at 500%.

## Canister Watermark: the original EFAS watermark

**Canister Watermark** (a module of its own in the same tab, made for EFAS) holds EFAS's original watermarking, from before the Watermark module followed darktable:

- a 3D film **canister** over the picture like a stamp: **Film**, **Texture**, **Size** and **Position** (and **Custom** for one you have dragged on the picture);
- the **camera and lens** text, beside the canister or on its own, with its own position, size, colour and font, and a tiny credit line;
- the **old Text mark** a photo from an earlier version may still have, which can be made a marker (in the Watermark module) or removed.

It has its own presets, reset and on/off light, and the Watermark module's do not touch it, nor its do the Watermark's. They are two modules over one set of watermark settings, so a look made before the split still opens with the canister in Canister Watermark and the marker in Watermark.

## Variables

Put a name in `$( )`: `$(CAMERA)`. The names are not case-sensitive. A name with nothing behind it is empty, and **Variables...** shows which are empty for the photo you have open.

| Kind | Names |
|---|---|
| The file | `FILE.NAME` (without the extension), `FILE.EXTENSION`, `FILE.FOLDER` (the folder's name) |
| Today (the preview's time when the photo was opened; the export's own time when it is exported) | `YEAR`, `YEAR.SHORT`, `MONTH`, `MONTH.LONG`, `MONTH.SHORT`, `DAY`, `HOUR`, `MINUTE`, `SECOND` |
| The frame's date (from its details or the Roll Card's dates) | `EXIF.DATE` (as written: `2024-03-09`, `2024-03-09 14:30` or just `2024`), `DATE` (today, `2026-10-19`), `EXIF.YEAR`, `EXIF.YEAR.SHORT`, `EXIF.MONTH`, `EXIF.MONTH.LONG`, `EXIF.MONTH.SHORT`, `EXIF.DAY`, `EXIF.HOUR`, `EXIF.MINUTE`, `EXIF.DATE.REGIONAL`, `EXIF.TIME.REGIONAL` |
| The film camera | `CAMERA` (make and model), `EXIF.MAKER` or `MAKER`, `EXIF.MODEL` or `MODEL`, `LENS` or `EXIF.LENS`, and as numbers only, like darktable: `EXIF.ISO`, `EXIF.FOCAL.LENGTH`, `EXIF.APERTURE`, `EXIF.EXPOSURE` (the shutter, from the Roll Card's Exposure box: `1/125 f/8` gives `1/125` and `8`). With their units: `FOCAL.LENGTH` (`50 mm`), `APERTURE` (`f/8`), `SHUTTER` (`1/125 s`); and `EXPOSURE`, the Exposure box as it was written |
| The scan's own Exif | `Xmp.dc.creator` (also `CREATOR`, `ARTIST`) and `Xmp.dc.rights` (also `RIGHTS`, `COPYRIGHT`): the Artist and Copyright the scanning camera wrote into the file |
| The film and the roll | `FILM`, `FILM.ISO`, `FILM.MAKER`, `FILM.TYPE`, `FILM.FORMAT`, `ROLL.NAME` (the Roll Card's name, else the folder's), `ROLL.FILM`, `ROLL.ISO`, `ROLL.FORMAT`, `ROLL.CAMERA`, `ROLL.LENS`, `ROLL.DEVELOPER`, `ROLL.SCANNED_WITH`, `PUSH.PULL`, `FRAME`, `NOTE` |
| Place | `LOCATION.CITY`, `LOCATION.STATE`, `LOCATION.COUNTRY` |
| EFAS | `EFAS.NAME`, `EFAS.VERSION` |
| Only inside an SVG marker | `WATERMARK_TEXT`, `WATERMARK_COLOR` (as `#rrggbb`), `WATERMARK_FONT_FAMILY`, `WATERMARK_FONT_STYLE` (`normal` or `italic`), `WATERMARK_FONT_WEIGHT` (`400` or `700`) |

The same small language as darktable's lets you shape a value:

| Write | Gives |
|---|---|
| `$(FILM-no film)` | `no film` when the value is empty (the default can hold variables: `$(EXIF.YEAR-$(YEAR))`) |
| `$(LENS+ - $(LENS))` | ` - ` and the lens, only when there is a lens |
| `$(CAMERA:0:8)` / `$(CAMERA:-4)` | the first eight letters / the last four (`$(CAMERA:6)` is from the seventh letter on) |
| `$(FILE.NAME^^)` / `$(FILE.NAME,,)` | all capitals / all small letters (`^` and `,` do the first letter only) |
| `$(FILE.NAME/_/ )` / `$(FILE.NAME//_/ )` | the first / every underscore changed to a space |
| `$(FILE.NAME#IMG_)` / `$(FILE.NAME%_edit)` | the same text with that taken off the start / the end |

Pieces are plain text, not patterns. At most 400 variables are filled in per text, defaults inside defaults go three deep, and a value is cut at 1000 characters, so a template cannot run away.

## Sharing

A preset that uses a marker stores its **name** (not a path), so a preset file that is exported keeps `signature.svg` and the settings, and says so: it is drawn on another computer only when that computer has a file of that name in its watermarks folder. The marker's own file is not put in the preset file. A marker chosen by a path (older presets) is left out of an exported preset. See [presets.md](presets.md#sharing-presets-export-and-import). A watermark with text in it is shared with the preset, so look at it before you send it.

## Where it is in the code

`features/watermark/variables.py` (the `$(NAME)` language and the film's variables, tested in `tests/test_watermark_variables.py`), `library.py` (the watermarks folder), `logoimage.py` (reading the SVG as text and filling it in), `marks.py` (the settings, which module owns which, and the reading of an earlier version's marker), `dtmark.py` (darktable's sizing, placing and drawing of a marker), `desktop/view/watermark_panel.py` (the Watermark module) and `canister_panel.py` (Canister Watermark), `watermark_variables_dialog.py` (the list of variables), and `tests/test_watermark_markers.py` and `test_watermark_markers_ui.py`.
