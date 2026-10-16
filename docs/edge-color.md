# Edge Color

**Edge Color** (Color tab) corrects a colour or brightness difference that grows toward the edges of the picture.

## What it is for

A flash lights the middle of a frame and little of its edges, so the edges are left to whatever else is lighting the room: fluorescent tubes put a **green** cast on daylight film, tungsten an **orange** one, and the edges are usually darker too. A lens that darkens its corners does something similar. It is in the picture, so:

- **Flat Field** cannot fix it. Flat Field divides out the *scanner's* light, from a scan of the bare light; the bare light has no colour cast at the edges and the picture's edges do.
- **Edge Bleed** does not fix it either: that removes light spilling into the picture from the clear film and the sprocket holes, and works on the scan before the conversion.
- **Vignette** (Watermark tab, Finishing) changes brightness only.

## The controls

| | |
|---|---|
| **Tint** | at the edges, toward magenta (+) or green (-) |
| **Warmth** | at the edges, toward yellow (+) or blue (-) |
| **Light** | at the edges, brighter (+) or darker (-) |
| **Size** | where the correction starts, from the centre (0) to the edge (1); a bigger Size leaves more of the middle alone. The correction grows smoothly from there to full strength at the edge |
| **Shape** | 0 follows an ellipse (a flash's falloff reaches furthest into the corners), 1 follows the picture's rectangle (an even band round all four sides) |
| **Auto match the colour** | measures the colour of the outer 8% band against the middle of the picture (30-70% of each side) in OKLab and adds the Tint and Warmth that bring them together. Press it again to refine. **Light is left to you**: a picture often has bright or dark things at its edges, and matching them to the middle would darken or lighten real content |

The correction is a shift of the OKLab a, b and L values (the same colour space as Color Mixer and Color Toning), so it moves colour without dragging lightness along; Tint at 1 is a shift of 0.06 in a, Warmth at 1 is 0.06 in b, Light at 1 is 0.15 in L, all at full weight at the edge.

## Where it sits

It works on the **finished, cropped picture**, just before the Vignette, so "the edges" are the edges you can see. **Crop off the film's own border first**: the clear film base at the edge of a frame is a hard-edged strip (it inverts to a green or dark band), which a soft correction cannot hide and Auto would chase. Edge Color is a module like the others: a power light, a reset button, module presets, undo, saving with the photo, and it can be part of a preset or the Clear button.

## An example

A flash photograph on colour negative film, rendered with a green haze along its bottom and top edges and a hard green strip down one side. Flat Field left the colour of those edges exactly as it was: the scanner's light was colour-neutral (the bare-light reference's green balance stayed within 2% of 1.00 on every side) and the flat field was working (the film border strip varied 15-18% along its length before it and 6-9% after). The hard strip is the film's clear border (cropped off); with it gone, **Auto match the colour** pulled the soft green haze toward the middle's colour (Tint +0.14, Warmth -0.56 on that picture). A thin hard strip along the far edge was a second piece of border and needs the crop to move in a little further.
