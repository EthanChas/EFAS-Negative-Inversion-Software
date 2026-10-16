# Flat Field and its three methods

**Flat Field** (Negative tab) corrects uneven light: vignetting from the lens and falloff from the light panel. You give it a picture of the bare light (a **reference**), or let **Auto (Roll)** pool every frame of a folder, and it divides that falloff out of every photo in the folder (or, as the **Permanent** flat field, out of every photo you open). It works in linear light, so a 16-bit scan keeps its levels.

The reference is turned into a **gain map**: for each pixel and colour, the average brightness of the reference divided by its (smoothed) brightness there. How the reference is smoothed is the **method**.

## The three methods

| Method | What it does | Edges of a steep reference after its own correction |
|---|---|---|
| **EFAS (original)** | a 5x5 median filter against dust on the light, then a Gaussian blur of **1/16** of the long side | about **13% dark** (18% in the corners) |
| **NegPy** | NegPy's: the same blur of 1/16 of the long side, **no dust filter** | the same as EFAS (about 13% / 18% dark), and dust specks print into the map |
| **Improved** | the 5x5 median filter, then a blur of **1/64** of the long side, with the edge pixels **repeated outward** instead of mirrored | within **1-3%** of the middle |

The two older methods blur so widely that the steep falloff in the last tenth of the frame is smoothed away: a mirrored edge pulls bright middle values into the edge's own blur, so the gain there is too low and the border stays dark. The Improved method keeps the dust filter and a blur wide enough to remove sensor noise and soft specks, but narrow enough to follow a steep border. Numbers from the 16_10_2026 reference (a 256 x 171 map, a rectangular falloff to about 40% at the corners): the left edge ends at 0.863 of the middle with the original blur and 0.983 with Improved; the corners 0.804 and 0.976.

The cost is dust: a blur that follows the border also follows a large mark on the light. A speck up to 2 pixels on the 256-pixel map (about 52 pixels in the scan) changes the gain by 0.1% with Improved (0.0% with the original); 3 pixels by 3% (0.4%); 4 pixels by 13% (0.7%). **Check Flat Field** shows whether a reference has marks like that; clean the light and shoot it again if it does.

## Choosing a method

**Method** at the top of the Flat Field panel is one choice for everything. **New flat fields are made with it** (the default is Improved), and **choosing a different one makes the folder's flat field and the permanent one again** from the reference each was built from. EFAS keeps that small linear reference map with the gain (about 520 KB each), so you do not pick the reference again to compare the methods.

A flat field made **before the methods existed** (EFAS's original, with no reference kept) stays exactly as it is when you change the method. The panel says so, and picking its reference again makes it with the method you chose.

NegPy's method is included so that EFAS can reproduce a NegPy result and so the two can be compared; the Improved method is the one to use.

## What Flat Field cannot do

It corrects the *scanner's* light. A colour or brightness difference that is in the picture itself (a flash that lit only the middle of the frame, the film's own border) is not in the reference, so Flat Field leaves it: for that see [Edge Color](edge-color.md) and [Edge Bleed](edge-bleed.md).
