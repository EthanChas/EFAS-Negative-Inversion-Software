# Masks (the Masks panel, and every module's Mask box)

Masks limit a module to part of the picture. They are ported from darktable's (5.4) drawn masks: the shapes, their falloff, groups and the mouse and keys are darktable's. The Masks section is on the left of the picture; each module that works on the tone, colour or detail of the picture has a **Mask** box at its foot.

## Shapes

| Shape | How it is made | Scroll | Shift+scroll | Ctrl+scroll |
| --- | --- | --- | --- | --- |
| Circle | click | size | feather | opacity (in a group) |
| Ellipse | click | size | feather | opacity; Ctrl+Shift+scroll turns it |
| Path | click smooth nodes, Shift+click (or Ctrl+click) sharp ones, right-click or Enter to finish, Esc to cancel | (feather while drawing) | feather | opacity |
| Brush | press, drag, let go | size | hardness | opacity |
| Gradient | press and drag to set its direction | curvature | compression | opacity |

The **AI object** button (a wand) cuts an object out from a few clicks and keeps it as paths: see [ai-mask.md](ai-mask.md).

**Picking a shape that is under another.** The precise parts of any shape (an anchor, a node, a handle, a segment, a source) are picked first. Failing those, where several shapes overlap the one the pointer is inside (not just in the feather of) wins, and among those the smallest, so a small shape under or inside a bigger one can be picked and the bigger one is still picked outside it.

**A feather that fits the shape.** A path you draw gets a feather no wider than half its own radius (a path round a speck no longer gets 5% of the picture); making a path, circle or ellipse smaller with the wheel also takes its feather down to no wider than the shape (making it bigger leaves the feather as it is); and the next circle's feather follows its size down too.

Ctrl+click a shape button (or Ctrl while placing a circle, ellipse, brush or gradient) keeps the tool armed. Drag a shape to move it; drag its anchors to resize it (Ctrl+drag an ellipse anchor turns it, Shift+click an ellipse switches how its feather is measured). On a path: drag a node, drag a handle (Ctrl keeps it symmetric, Shift moves just that handle, right-click resets the curve), Shift+click (or Ctrl+click) a node to switch smooth and sharp, right-click a node to remove it, Ctrl+click a segment to add a node. Gradient: drag the arrow's tip to turn it, double-click to reset the curvature, Shift+click to switch linear and sigmoidal. Right-click a shape to delete it. The middle button pans while a mask is being drawn or edited.

Sizes are fractions of the scan's shorter side, and every shape is kept in the **untouched scan's frame**, so it stays on the same part of the picture when you crop, turn, flip or straighten.

## A module's Mask box

- **Off**: the module acts on everything (as it always did). **Uniformly**: everywhere, at *Opacity*. **Drawn mask**: only where the mask is.
- The shape buttons draw a shape for the module. The first becomes the module's mask; a second one makes a group (named "<module> mask") holding both. The pencil shows the mask's shapes on the picture to edit; the eye paints the mask yellow.
- **Invert** turns the mask over. **Refine**: *Blur* (a Gaussian of the mask, in pixels of a 1600 px picture), *Feather* (the mask follows edges of the picture, a guided filter), *Contrast* and *Brightness* (darktable's mask tone curve).
- The picture becomes `before + (module's result - before) x mask`, darktable's normal blend. A drawn mask with no shape chosen means everywhere (inverted, nowhere).

Modules that can be blended: Color (white balance and saturation together), Exposure, Contrast, Print Response, Chroma Denoise, Local Contrast, Shadows & Highlights, Tone Curve, Lab Look (with its scanner colour response), Color Mixer, Color Toning, Sharpening, Grain Sharpening, Tone Equalizer, Color Balance RGB, Diffuse or Sharpen, Edge Color, Halation.

## The Masks panel

On the left, under History, collapsible, laid out like darktable's mask manager. The top row is **created shapes** with the buttons that draw a free shape (brush, circle, ellipse, path, gradient) and one that groups the picked shapes. The list has the **Dust Detection** folder, **Groups** (with their shapes) and **Shapes**. Pick a shape or group to show it on the picture; the pencil under the list turns showing and editing on the picture on and off, the bin deletes.

Under the list, **properties** (open or closed with its arrow) are the picked shape's own sliders, the way darktable shows them: *size* and *feather* for a circle, those and *rotation* for an ellipse, *feather* for a path, *size*, *hardness* and a *smoothing* choice (how much a brush stroke is smoothed as you draw) for a brush, *compression*, *curvature* and *rotation* for a gradient, and *opacity* for a shape inside a group. They move with the shape when you scroll over it on the picture, and a slider's final value is one step in the history.

Right-click a shape: rename, duplicate, group, add to group, take out of a group, and for a shape in a group its **operation** (union, intersection, difference, sum, exclusion), *Inverted* and *Shown*.

**Dust Detection** is ready as soon as a photo is open, with three folders, **Dust**, **Hairs** and **Scratches**, each with a count. It is read from what dust detection finds in the picture just drawn (specks and hairs from the detection wash, scratches from the traced scratch lines) and follows the dust settings. While Auto Dust Removal or AI Dust Detection is on it lists what they found without Show Detections being on; with both off the detection is only run for Show Detections (it costs a pass over the picture), so turn that on to list the candidates, and the traced scratches are always listed. Click a folder (Dust, Hairs, Scratches, or the Dust Detection folder itself) to see everything in it on the picture: the specks and hairs washed in their own colours and ringed, the scratches underlined; click away to put the picture back. Pick a single entry to ring (or underline) just that one; Delete (the bin, or the Delete key) leaves that one mark unrepaired (a deleted scratch is taken out of the repairs).

## What is not the same as darktable

- No **parametric** masks (a mask chosen by colour or brightness range) yet; masks are drawn.
- A path's or brush's falloff is made from a distance map of the curve, with darktable's falloff profile, rather than darktable's own line drawing, so the numbers match closely but not bit for bit.
- A picture with a masked module is made in 8 bits from the first masked module of the colour stage; without masks the 16-bit path is unchanged.
- The mask outlines are placed with a grid-based mapping when the picture is straightened or has lens/keystone correction: within about a pixel at 1600 px wide.

Code: `features/masks/` (model, raster, blend, outline, frame), `desktop/mask_tool.py` (the mouse and keys, no Qt), `desktop/mask_blend.py` (render side), `desktop/view/mask_manager.py`, `blend_box.py`, `mask_editor.py`; tests `test_masks_engine.py`, `test_masks_render.py`, `test_mask_tool.py`, `test_masks_window.py`.
