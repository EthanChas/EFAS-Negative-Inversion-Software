# Lens correction from the Lensfun database

**Crop & Rotate > Lens Correction** uses the [Lensfun](https://lensfun.github.io) database (through the optional `lensfunpy` package) to correct the lens the photo was taken with: its **colour fringes**, its **dark corners**, and a **starting value for the Distortion slider**. It is **off by default** and changes nothing until you switch a correction on.

## How the lens is found

From the photo's EXIF: the camera make and model, the lens name, the focal length and the aperture. All four have to be there (a tethered shot from a Canon body has them; a file that lost its EXIF has not). The panel says what it found, for example *Lens profile found: Canon EF 100mm f/2.8 Macro USM on Canon EOS 5D Mark IV (100 mm, f/8)*, or why there is none: the package is not installed, the EXIF is incomplete, the camera is not in the database, or the lens is not.

## The three corrections

- **Correct colour fringes** (lateral chromatic aberration): the lens images red and blue a little larger or smaller than green, which shows as coloured edges towards the corners. Each colour is moved back by what the profile says (green is the reference and does not move). On a full frame body with a 100 mm macro lens the red channel is out by about one pixel at the corners at full resolution.
- **Correct vignetting**: brightens the corners by what the profile says (about 11% at the corners of that lens at f/8 and 0.4 m), in linear light, the way the flat field is applied. **A flat field already contains the vignetting** (it was measured through the same lens), so with a flat field on, only the colour fringes are corrected, and the panel says so.
- **Use the Profile's Distortion**: sets the Distortion slider to the value that best matches the profile. The slider has one radial term (k1), the profile's own model has more, so this is an approximation, and the slider is still yours to adjust. A 100 mm macro lens has very little distortion (a few thousandths).

## Focus distance

A Lensfun profile is made for ordinary shooting distances. Close up, as on a copy stand, it is an approximation, which is why **Focus distance (m)** can be set: 0.4 m suits a 100 mm macro lens at 1:1 on a full frame camera, 1000 is "far away", how most photographs are taken. It changes the vignetting and the distortion the profile gives; colour fringes hardly depend on it.

## What happens to the picture

The corrections are made on the scan itself, before the flat field and everything else, so the rest of EFAS works on a corrected picture; they are in the preview and in every export (a photo that is not open reads its own EXIF when it is exported). They are worked out on a small grid (a lens's corrections are smooth) and brought up to the picture's size a strip at a time, so even a 30-megapixel scan needs no large coordinate maps. The setting is saved with the photo's edits and covered by undo.

## Installing the database

`pip install lensfunpy` (or `pip install photoeditor[lenses]`). Its wheels carry the Lensfun library and a database; the packaged build includes them when it is built on a machine that has the package. Without it the controls are off and the panel says the database is not installed.

## Credit

Lensfun by the Lensfun project (the library LGPL-3, the database CC BY-SA 3.0); lensfunpy by Maik Riechert (MIT). The idea came from the suggestion on the NegPy tracker (issue 1033).

Code: `features/lenscorrect/logic.py` (finding the profile, the corrections, the distortion fit; no Qt), `desktop/render.py` (`_lens_corrected`), `desktop/view/crop_tool_panel.py` (the controls).
