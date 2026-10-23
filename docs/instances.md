# Multiple instances (copies of a module)

As in darktable, a module can be copied. The two-squares button in the header of **Exposure, Contrast, Shadows & Highlights, Local Contrast, Chroma Denoise, Color Mixer, Color Toning, Sharpening, Grain Sharpening, Halation, Edge Color and Retouch** opens a menu: **New instance** (a copy with the module's defaults), **Duplicate instance** (a copy of what the module is set to now; for Retouch the algorithm, scales and sizes but no shapes). Up to 8 copies of a module.

- A copy is a panel right after its module, titled with the module's name, its number and its name ("Exposure 2 - shadows"). The module itself is not numbered. The copy's header button: **Rename**, **Duplicate**, **Delete**; it also has a reset button and its own **on/off light**.
- Its controls are the module's own fields (a slider for each number, a box for each choice), and a **Mask** box at the foot: the copy's mask is its own (kept under the key `exposure#2`: the module key, `#`, the copy's id).
- A copy of Retouch is a whole Retouch: its own shapes (in a group of their own in the Masks panel), scales, algorithm and views. Drawing, picking and editing work on whichever Retouch's buttons you press.
- **How the picture is made**: the module, then its copies in order, each one more step (exposure and contrast copies join the ramp, the others are steps of their own after the module; sharpening, grain sharpening, edge color and halation copies come where the module does). With any copy of a colour-stage module the colour stages are made one module at a time and in 8 bits, as with a mask.
- Saved with the photo (the `instances` column), in the undo history, in exports; not in presets (a preset applies to the module itself).
- The **Enabled** tab (the power button at the top of the tool tabs) lists the modules and copies that are on and not at their defaults.

Not copyable yet: Negative, Color (white balance and saturation), Tone Curve, Print Response, Lab Look, Crop & Rotate, Dust & Scratches (one set of repairs per photo), Finishing, Watermark.

Code: `features/instances/logic.py`, `desktop/view/instance_panel.py`, `desktop/mask_blend.py` and `desktop/render.py` (the steps), `desktop/controller.py` (`add_instance` and the rest); tests `test_instances.py`, `test_instances_window.py`, `test_retouch_copies.py`.
