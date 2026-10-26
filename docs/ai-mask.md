# The AI object mask

Click an object and the AI cuts it out. It is darktable's new AI object mask (darktable 5.6 and later), using the same models and the same steps, ported to EFAS. The result is kept as ordinary **path masks** (darktable's "apply as paths" option), so you can edit, group, invert and feather it like any shape you drew.

## Using it

1. **Get a model once.** The AI button (a wand) is in the **Masks** panel's row of shapes, and in every module's **Mask** box. The first time you press it with no model installed, EFAS opens **Extra > AI Models...** and offers to download one. EFAS asks first and says where it comes from and how big it is; nothing is downloaded unless you ask. **SAM 2.1 Tiny** (136 MB) is the smallest, **Small** (161 MB) is darktable's default, **Base Plus** (294 MB) is the most accurate and the slowest. You can also add a `.dtmodel` file you downloaded yourself.
2. **Press the AI button, then click.** EFAS first reads the whole picture (a few seconds on the processor; the status bar says "Reading the picture..."). Then every click answers at once: a **left click** on the object adds it, a **right click** (or Shift+click) on something that is *not* part of it takes that away. Each click refines the cut. The wheel still zooms, so you can click a small thing.
3. **Enter** keeps the cut: one path for each separate piece of the object, with sharp corners and a thin feather. Pressing the AI button again keeps it too, and so does going on to another tool or shape. Until it is kept the cut is only a preview and is not in the Shapes list; once kept it is listed there and the pencil (edit) button shows its nodes. **Backspace** takes the last click back, **Esc** cancels. Keeping a cut is one step in the undo history.

From the Masks panel the paths join the list of shapes. From a module's Mask box they become that module's mask (a second cut joins a group, as with any second shape).

## What it does, and its limits

- The picture the model sees is the one on screen (the converted positive, after the crop and turns), so what you click is what is cut. It is read at up to 1024 pixels, so an edge is as exact as that allows and traced as a polygon a pixel or so from the cut. Very fine detail (hair, a wire fence) is not followed: the models are not good at it, as darktable's own testers found.
- Of the separate regions the model finds, the ones with a click on the object are kept (the largest, if no click is inside one). **Holes inside the object are filled.** Small specks and pieces under 0.02% of the picture are left out, and at most eight pieces become paths.
- Not every cut is right. It is a model: add a background click where it takes too much, another object click where it leaves something out, and fix the rest by moving nodes.
- SegNext, the other model darktable offers, has different inputs and is not supported yet.

## Where the models run and where they come from

They run on this computer, on the processor, through the ONNX Runtime EFAS already ships (the same as the AI dust detection). Nothing about you or your photos is sent anywhere. They are darktable's packages from [darktable-org/darktable-ai](https://github.com/darktable-org/darktable-ai) (GPL-3.0), released as `.dtmodel` files (a zip with `config.json`, `encoder.onnx` and `decoder.onnx`); EFAS keeps them in its data folder under `ai-models`. The models are Segment Anything 2.1 from Meta: **the weights are Apache-2.0; the pictures it was trained on (SA-1B) are under a research-only licence of Meta's**, which darktable states too.

## How it works

The encoder looks at the picture once (long side made 1024 pixels, zero-padded to a square, ImageNet-normalised) and makes embeddings. For every click the decoder takes them with the clicks (label 1 for the object, 0 for not, and a padding point) and the previous answer, and returns three candidate masks and their predicted overlap; the best is cropped back to the picture, brought up to its size and turned into a probability. Above 0.5 is the object. Code: `features/aimask/runtime.py` (the model), `shapes.py` (regions, holes, outlines), `models.py` (packages), `desktop/ai_mask_service.py` (the worker thread), `desktop/ai_download.py`, `desktop/view/ai_models_dialog.py`, and the AI mode of `desktop/mask_tool.py`.
