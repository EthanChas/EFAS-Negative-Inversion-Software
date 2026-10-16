# Edge Bleed

Light from the clear film round a frame, from the gaps in the holder and from the sprocket holes spills into the picture's edges and lifts them. It is strongest at the border, dies away a short distance in, and differs from side to side (a scan against a light table often shows it worst beside the sprocket holes). A flat-field map cannot fix it: Flat Field corrects light that falls off smoothly across the whole frame, from a scan of the bare light. The **Edge Bleed** module (Negative tab, under Flat Field) has four tools for this fault.

The first three work in linear light on the picture after its rotation, straightening and flips and after dust repair, before the crop and the conversion, so the conversion (and the white and black point droppers) read the repaired picture. The fourth is laid over the finished picture.

## What counts as outside the picture

- **With a crop**, the crop is the picture's edge. The light outside it is what bleeds in.
- **Without a crop**, the clear film border found round the picture (the same detection Auto crop uses). It can be wrong when a dark holder is visible round the film: set a crop round the picture instead.
- **Edge dodge** needs neither: with no edge to go by it uses the edges of the image.

Only the light that comes from outside counts as a source: the pixels nearly as bright as the brightest out there, which is the clear film base and the holes. A dark holder gives off next to nothing and is not a source.

## The four tools

1. **Fill holder** (0-1). Within a strip round the picture (15% of its shorter side, leaving a small guard band at the edge, since the detected edge is only good to a few pixels), anything that is not clear film base, such as the dark edge of a holder, a bright sprocket hole or an edge code, is blended toward the film base. The base is the median of the pixels within 60-100% of the brightest tone outside. The picture itself is never touched. This tool fills the outside only, so with a crop it matters only where the crop is not drawn, and for the metering of an uncropped picture.
2. **Bleed repair** (0-1). The light the border gives off is spread with a Gaussian blur (its width is **Reach**, a share of the shorter side) and a share of it is subtracted from the picture, in linear light. Strength 1 takes off 60% of the spread light. **Auto strength** fits the share: for each side of the picture it takes the brightness profile running in from the edge (the median along the edge, so the scene does not count) and finds, by least squares against the same blurred border light, the share that explains how the edge brightens; the answer is the median over the sides. It is a guess (a bright scene edge reads as bleed), is sensitive to Reach, and is a place to start: judge it by eye. On a synthetic frame with 12% bleed added it recovers 0.119.
3. **Edge dodge** (0-1). For each side, the brightness profile running in from the edge is flattened toward the level just beyond Reach, by at most -30% and +40%, tapering to no change at the far end of the reach. It needs no border and no light model, so it also removes a lift that is not bleed, and a scene that really is brighter at its edge.
4. **Border mask**. A soft band of black, grey or white over the picture's outer edge: **Mask width** is a share of the shorter side on each edge (0 is off, up to 15%), **Mask feather** is how much of the band fades (0 hard, 1 the whole band). By default the band is **left out of the metering**: the conversion reads the picture without it (by widening the analysis margin, or shrinking the analysis region).

## Where it sits

Edge Bleed is a module like the others: a power light that makes the picture without it while keeping its settings, a reset button, module presets, undo, saving with the photo, and it can be part of a preset or the Clear button. The settings belong to each photo (a roll shot in one holder will want the same values: copy them with Paste Settings, or save a module preset).

## What it is not

Edge Bleed does not model your scanner. It is a handful of documented approximations (a Gaussian for the spread of the light, a flat share, a median profile) that are right in shape and need judging by eye. It does not remove dust, light leaks or a wedge of light on one side of the whole frame (that is Flat Field), and it cannot recover detail that bleed has clipped.
