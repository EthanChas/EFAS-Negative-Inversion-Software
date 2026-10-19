# Watermarks: markers, SVG files and variables

The **Watermark** tab (Watermark and Finishing) puts four kinds of mark on the finished picture: a film **canister**, **camera and lens** text, a block of **text**, and a **marker** (an SVG or a picture). They are drawn at the very end, so they are in every export and have no effect on the histogram or any measurement.

This page is about the **marker** and the **variables**, which work the way darktable's watermark module works, so an SVG written for darktable can be used here.

## How darktable does it, and what EFAS takes from it

darktable's watermark module keeps a list of SVG (and PNG) files in a `watermarks` folder, with a reload button; you pick one by name. It reads the SVG as text and replaces `$(NAME)` placeholders before drawing it: its own `$(WATERMARK_TEXT)`, `$(WATERMARK_COLOR)`, `$(WATERMARK_FONT_FAMILY)`, `$(WATERMARK_FONT_STYLE)` and `$(WATERMARK_FONT_WEIGHT)`, filled in from the module's Text, Colour and Font controls, and the general variables of the image (the file name, the Exif date, the camera). Its size can be a share of the image, of its longer or shorter side, or of its height, and the mark can be rotated, faded and placed on a nine-cell grid with offsets.

EFAS now does all of that, with these differences, on purpose:

- **Everything put into an SVG is made safe.** Every value that goes into the file has `& < > " '` turned into XML entities, so a Roll Card with an ampersand or a quote in a name cannot break the file or add elements to it. (darktable leaves quotes alone.)
- **A value is never read for variables again.** A film called `$(FILE.NAME)` shows that text; it does not become the file name.
- **The camera, lens and ISO are the film camera's.** `$(EXIF.MAKER)`, `$(EXIF.MODEL)`, `$(EXIF.LENS)` and `$(EXIF.ISO)` give the camera, lens and film speed of the **Roll Card** and the frame's own details (the scan's own Exif says nothing about the film), and the film-scanner names are there as well (`$(FILM)`, `$(ROLL.NAME)`, ...). So a darktable SVG that writes the camera writes the film camera here.
- **`$(FILE.FOLDER)` is the folder's name,** not its whole path, so a watermark does not tell people how your disk is laid out.
- The marker has its **own** Text, Colour and Font, separate from the Text mark's, so one picture can carry a text mark and an SVG marker with different words.
- Not carried over: darktable's tag, rating, colour label and `Xmp.dc.*` variables, and its "advanced" two-step scale options. The four **Scale on** choices below cover the cases people use.

## The watermarks folder

Markers live in a **watermarks folder** in EFAS's data folder (`~/.EFAS/watermarks`, or whatever your data folder is). Three samples come with EFAS and are listed with "sample" after their names:

- `simple-text.svg`: one line of text in the colour and font you choose.
- `copyright-line.svg`: `(c) 2024 Your Name`: the year of the frame (this year if the frame has no date) and your text.
- `film-frame-info.svg`: two lines from the Roll Card: the film and its ISO, and the camera and lens. A part with nothing to show is left out.

**Marker** (a list, with **None** first) chooses one by its file name. **Reload** looks in the folder again after you have put a file there, **Open Folder** opens it in Explorer, and **Add...** copies a file you choose into the folder and uses it. A file of yours with the name of a sample hides the sample. A name that is already taken gets `_2` and so on: nothing is overwritten.

Because a marker is chosen **by name**, a preset or a file that uses `signature.svg` works on any computer that has a file of that name in its watermarks folder. A marker chosen before this existed was chosen by its whole path; that still works where the file is. A marker that is not there is shown as *Missing* and is not drawn; put a file of that name in the folder and press Reload.

SVG files can be drawn in any editor (Inkscape, say). The SVG's own size sets the shape of the marker: leave room for the longest text it will have, since text outside the drawing is cut off. Qt's SVG renderer draws it, which covers shapes, paths, gradients and basic text; very new SVG features may not appear.

## The controls

Which of **Text**, **Colour** and **Font** can be used depends on the marker: they are available when the SVG has the matching variable, and greyed out for a picture or an SVG that has its own text and colours. The line under the Marker list says what the chosen marker takes.

- **Text:** up to 511 characters. It may hold variables: `(c) $(EXIF.YEAR) $(CAMERA)`.
- **Font, B, I:** a font installed on this computer (or a font file) with bold and italic.
- **Color:** white, black or any colour.
- **Size** and **Scale on:** what the size is a percentage of. **Shorter side** (the default) is the marker's longer side against the picture's shorter side, so it looks the same in portrait and landscape. **Longer side** is against the picture's longer side. **Width** and **Height** are the marker's own width or height against the picture's, which is how to keep the height of a line of text constant.
- **Opacity** and **Rotate** (clockwise degrees; the box turns with it).
- **Position:** nine places and **Custom**, which appears once you drag the marker on the picture (tick **Move and resize on the picture**).
- **Variables...** lists every variable with its value for the open photo; double-click a row to copy its name.

The Text mark (not only the marker) understands variables too.

## Variables

Put a name in `$( )`: `$(CAMERA)`. The names are not case-sensitive. A name with nothing behind it is empty, and **Variables...** shows which are empty for the photo you have open.

| Kind | Names |
|---|---|
| The file | `FILE.NAME` (without the extension), `FILE.EXTENSION`, `FILE.FOLDER` (the folder's name) |
| Today (the preview's time when the photo was opened; the export's own time when it is exported) | `YEAR`, `YEAR.SHORT`, `MONTH`, `MONTH.LONG`, `MONTH.SHORT`, `DAY`, `HOUR`, `MINUTE`, `SECOND` |
| The frame's date (from its details or the Roll Card's dates) | `EXIF.YEAR`, `EXIF.YEAR.SHORT`, `EXIF.MONTH`, `EXIF.MONTH.LONG`, `EXIF.MONTH.SHORT`, `EXIF.DAY`, `EXIF.HOUR`, `EXIF.MINUTE`, `EXIF.DATE.REGIONAL`, `EXIF.TIME.REGIONAL` |
| The film camera | `CAMERA` (make and model), `EXIF.MAKER` or `MAKER`, `EXIF.MODEL` or `MODEL`, `LENS` or `EXIF.LENS`, `EXIF.ISO`, `EXIF.FOCAL.LENGTH`, `EXIF.APERTURE` |
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

`features/watermark/variables.py` (the `$(NAME)` language and the film's variables, tested in `tests/test_watermark_variables.py`), `library.py` (the watermarks folder), `logoimage.py` (reading the SVG as text, filling it in and drawing it), `marks.py` (the settings and where each mark goes), `desktop/view/watermark_panel.py` and `watermark_variables_dialog.py` (the tab and the list of variables), and `tests/test_watermark_markers.py` and `test_watermark_markers_ui.py`.
