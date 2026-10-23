# Retouch (Frame & Clean tab)

Retouch is darktable's retouch module (5.4) ported to EFAS, **alongside** the Dust & Scratches tools, which are unchanged. Shapes are drawn on the picture (the [masks](masks.md)); each shape has an **algorithm** and a **wavelet scale**.

## Algorithms

- **Clone**: copies the picture from the shape's **source** over the shape.
- **Heal**: like clone, but what is copied is the source's *detail*. The difference between shape and source is smoothed by solving the Laplace equation inside the shape (Gauss-Seidel with over-relaxation, red/black checkerboard, at most 2000 iterations, darktable's `heal.c`) with the pixels outside as the fixed edge, and added to the source. A patch from a lighter part of the picture takes on the colour round it and keeps its texture.
- **Blur**: Gaussian, or bilateral (darktable's bilateral grid: only the lightness is smoothed, edge-aware, colour kept). Radius 0.1 to 200 (in scan pixels; it is scaled for the preview).
- **Fill**: *erase* (black, plus Brightness) or *colour* (plus Brightness). The colour is in linear light.

## Drawing

Choose the algorithm, then press a shape button (path, ellipse, circle, brush; Ctrl+click keeps drawing). New shapes start at darktable's "spots" sizes, smaller than the sizes of masks. For clone and heal the shape is placed with its source a little up and to the right, and **the source follows the pointer while the button is held**; later drag the dashed copy to move it. **Shift+click** before placing sets where the source of the shapes to come is (the first shape copies from there; later shapes keep the same distance from theirs); **Ctrl+Shift+click** sets one absolute spot for all. A path or brush gets its source from its first node. Scroll, Shift+scroll and Ctrl+scroll work as for masks.

Click a shape to **pick** it. The Blur type and radius, and the Fill mode, colour and brightness then change that shape (without a shape picked, they are what the next shape starts with). Ctrl+click an algorithm button changes the picked shape: clone and heal can be swapped, and blur and fill, nothing else (darktable's rule). The Shape opacity slider (and Ctrl+scroll) is the shape's opacity in Retouch's group; the algorithm's result is mixed in by `shape mask x opacity`.

## Wavelet scales

The scale bar has a box for the picture (**0**), the scales **1** to **N** and the residual **R**. The picture is split into N layers of detail, fine to coarse, and the residual (an "a trous" wavelet with the hat `[1 2 1]/4` widened by 2^scale pixels per pass, mirrored at the edges: darktable's `dwt.c`); the layers add up to the picture. A shape acts on the layer of the scale it was drawn on. Scale 0 acts on the picture itself, before it is split.

- Click a box to work on that scale; the shapes shown (pencil) are those of that scale. Scroll over the bar to step.
- Drag along the lower edge to set the number of scales (up to 15, and as many as the picture takes); drag along the upper edge for **merge from**: the layers from there on are added together and acted on as one layer (shapes of the scale numbers in the merged range act on the running sum).
- **Cut shapes** / **Paste shapes** move all the shapes of one scale onto another.
- **Display wavelet scale** shows the layer you are working on (details are mostly grey, so the lightness is put through *Black / Middle / White* levels; *Auto levels* fits them to the layer). **Show mask** paints where the shapes of the scale act; the last button shows the picture without Retouch. These views only apply while the panel is open.

Scales are counted in **pixels of the picture being made**, as in darktable: the editing preview is the scan made smaller, so it shows a wider area per scale than the export. Judge scale work at 100%.

## Where it sits in EFAS

On the picture after all the tone and colour modules and before Sharpening, on the whole scan before the crop, with the picture held in 8 bits from there on (so a picture with Retouch is made in 8 bits at that point). The picture is worked on as **linear light** (converted from the 8-bit sRGB-like picture and back). A shape's mask is laid on the picture the way the picture was turned, straightened and flipped, and a clone or heal source is found the same way.

Retouch's settings are saved with the photo, are in the undo history, and are not part of presets. Dragging a slider or a shape previews with Retouch included; other sliders' live previews leave it out (it is put back when you let go). Deleting a shape in the Masks panel takes it out of Retouch.

## What is not the same as darktable

- Retouch runs on the whole picture, not tile by tile; the shape's area is cut to what the source also covers (as `rt_intersect_2_rois` does).
- There is no on/off light for Retouch (delete its shapes, or use the "without Retouch" view).
- The mask of a path/brush: see [masks.md](masks.md).

Code: `features/retouchdt/` (`dwt.py`, `heal.py`, `bilateral.py`, `logic.py`), `desktop/view/retouch_panel.py`, `desktop/mask_tool.py` (sources); tests `test_retouchdt_engine.py`, `test_retouch_window.py`.
