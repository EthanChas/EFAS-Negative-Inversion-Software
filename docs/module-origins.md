# Where each module comes from

Every module's header says where it comes from, in brackets after its name: **(darktable)**, **(NegPy)** or **(EFAS)**. It is the honest label for a project that is built from other people's work: the interface and the layout of the modules follow darktable's as a whole, but this table is about the *module itself*.

- **(darktable)**: the module is ported from, or follows closely, darktable's own module of that kind.
- **(NegPy)**: the module is ported from, or adapted from, NegPy's (GPL-3.0).
- **(EFAS)**: the module was made for EFAS. It may look like darktable's (all of them are laid out the way darktable lays modules out), but its logic is EFAS's own.

The tag is only in the header. The module's own title (which picks its icon and colour, and which Find, the Classroom and the history use) is unchanged, so nothing that looks a module up by name is affected. A copy of a module (multiple instances) carries the tag of the module it was copied from.

| Module | Origin | What it took |
|---|---|---|
| Negative | NegPy | The inversion and metering approach, the film type heuristic, the print-stage approach behind the NegPy Conversion, and the film crosstalk profiles it bundles. The *Original* conversion is EFAS's own |
| Sharpening | NegPy | Its four sharpening methods (features/sharpening/logic.py) |
| Chroma Denoise | NegPy | Its chroma-only denoise (features/denoise/logic.py) |
| Dust & Scratches | NegPy | Its dust and scratch repair (features/retouch/logic.py) and clone tool |
| Local Contrast | NegPy | Its CLAHE on lightness (features/localcontrast/logic.py) |
| Flat Field | NegPy | Its flat-field correction (features/flatfield/logic.py); EFAS adds the *EFAS (original)* and *Improved* methods and the permanent flat field |
| Print Response | NegPy | Its Snap / Toe / Shoulder response of the paper curve, here as an edit of the finished tones, and its paper profiles as presets (see presets.md) |
| Color Toning | NegPy | The idea of split toning: a hue and a strength for the shadows, midtones and highlights |
| Retouch | darktable | Ported 1:1: the shapes, the wavelet scales, clone, heal, blur and fill, and the panel |
| Masks | darktable | The drawn masks (circle, ellipse, path, brush, gradient), their groups and keys, and the Masks panel |
| Watermark | darktable | The watermark variables (`$(EXIF.MAKER)` and the rest) and SVG markers, so darktable's own SVG files work |
| Tagging, Tags | darktable | The tagging module's layout: tags on the photo, and the tag dictionary below |
| Exposure, Tone Curve, Color, White Balance, Contrast, Shadows & Highlights, Color Mixer | EFAS | Made for EFAS (laid out like darktable's modules) |
| Halation, Grain Sharpening, Edge Bleed, Edge Color, Lab Look, Finishing | EFAS | Made for EFAS, from its own research |
| AI Dust Detection | EFAS | A small neural network (FilmDefectNet, the author's own) |
| Error marking | EFAS | Made for EFAS |
| Crop & Rotate | EFAS | Made for EFAS; only the composition guides' geometry is ported from NegPy |

Panels that are not modules (History, Library, Export, Snapshots, Versions, Presets and the others) carry no tag. If a tag here is wrong or a module deserves another, it is one line in `desktop/view/module_origin.py`.
