# Where each module comes from

Every module's header says where it comes from, in brackets after its name: **(darktable)**, **(NegPy)**, **(EFAS)** or, for the two modules that have a part of each, **(NegPy & EFAS)**. It is the honest label for a project that is built from other people's work: the interface and the layout of the modules follow darktable's as a whole, but this table is about the *module itself*.

- **(darktable)**: the module is ported from, or follows closely, darktable's own module of that kind.
- **(NegPy)**: the module is ported from, or adapted from, NegPy's (GPL-3.0).
- **(NegPy & EFAS)**: Negative and Sharpening. Negative's **NegPy Conversion** is ported from NegPy; its **Original** conversion was made for EFAS. Sharpening's four methods are NegPy's; what EFAS built round them is its own.
- **(EFAS)**: the module was made for EFAS. It may look like darktable's (all of them are laid out the way darktable lays modules out), but its logic is EFAS's own.

The tag is only in the header. The module's own title (which picks its icon and colour, and which Find, the Classroom and the history use) is unchanged, so nothing that looks a module up by name is affected. A copy of a module (multiple instances) carries the tag of the module it was copied from.

| Module | Origin | What it took |
|---|---|---|
| Negative | NegPy & EFAS | NegPy 0.56 (old) is NegPy 0.56.0's own conversion ported as it was (features/negative/negpy056.py, checked against NegPy's code). The NegPy Conversion takes NegPy's inversion and metering approach, the film type heuristic, the print-stage approach behind the NegPy Conversion, and the film crosstalk profiles it bundles. The *Original* conversion is EFAS's own |
| Sharpening | NegPy & EFAS | NegPy's four sharpening methods (Unsharp Mask, Deconvolution, Surface Blur, Wavelet; features/sharpening/logic.py). EFAS added the Mask box, copies of the module, the 16-bit path and the link to the Grain Report, and Grain Sharpening is a separate EFAS module |
| Chroma Denoise | NegPy | Its chroma-only denoise (features/denoise/logic.py) |
| Dust & Scratches | NegPy | Its dust and scratch repair (features/retouch/logic.py) and clone tool |
| Local Contrast | NegPy | Its CLAHE on lightness (features/localcontrast/logic.py) |
| Flat Field | NegPy | Its flat-field correction (features/flatfield/logic.py); EFAS adds the *EFAS (original)* and *Improved* methods and the permanent flat field |
| Print Response | NegPy | Its Snap / Toe / Shoulder response of the paper curve, here as an edit of the finished tones, and its paper profiles as presets (see presets.md) |
| Color Toning | NegPy | The idea of split toning: a hue and a strength for the shadows, midtones and highlights |
| Retouch | darktable | Ported 1:1: the shapes, the wavelet scales, clone, heal, blur and fill, and the panel |
| Masks | darktable | The drawn masks (circle, ellipse, path, brush, gradient), their groups and keys, the Masks panel, and the AI object mask (darktable's models and steps) |
| Watermark | darktable | The module itself, with darktable's arithmetic for the marker's size (scale on, scale, the advanced options), alignment, offsets and rotation, its drawing and its blending; the watermark variables (`$(EXIF.MAKER)` and the rest) and SVG markers, so darktable's own SVG files work |
| Diffuse or Sharpen | darktable | The whole module (`features/diffuse/logic.py`): the wavelet decomposition, the anisotropic heat-diffusion step, its four speeds and anisotropies, the edge controls, the luminance threshold that inpaints highlights, and all of darktable's presets for it. See [diffuse-or-sharpen.md](diffuse-or-sharpen.md) |
| Tone Equalizer | darktable | The whole module (`features/toneequalizer/logic.py`): the nine nodes and their curve, the luminance estimators, the guided and exposure-independent guided filters, the mask compensation and the wands, and darktable's presets. See [tone-equalizer.md](tone-equalizer.md) |
| Color Balance RGB | darktable | The whole module (`features/colorbalancergb/logic.py`): the grading in Filmlight Yrg, the four ways, the masks, perceptual saturation and brilliance in JzAzBz or darktable UCS with their gamut maps, and darktable's presets. See [color-balance-rgb.md](color-balance-rgb.md) |
| Tagging, Tags | darktable | The tagging module's layout: tags on the photo, and the tag dictionary below |
| Exposure, Tone Curve, Color, White Balance, Contrast, Shadows & Highlights, Color Mixer | EFAS | Made for EFAS (laid out like darktable's modules) |
| Halation, Grain Sharpening, Edge Bleed, Edge Color, Lab Look, Finishing | EFAS | Made for EFAS, from its own research |
| Canister Watermark | EFAS | EFAS's original watermarking (a 3D film canister, the camera and lens text and the old text mark), kept as a module of its own beside darktable's Watermark |
| AI Dust Detection | EFAS | A small neural network (FilmDefectNet, the author's own) |
| Error marking | EFAS | Made for EFAS |
| Crop & Rotate | EFAS | Made for EFAS; only the composition guides' geometry is ported from NegPy |

Panels that are not modules (History, Library, Export, Snapshots, Versions, Presets and the others) carry no tag. If a tag here is wrong or a module deserves another, it is one line in `desktop/view/module_origin.py`.
