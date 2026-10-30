# Folding sections inside a module

After NegPy's modules, the titled groups of controls inside a module (FILM BASE, SCAN QUALITY, METERING, WHITE / BLACK POINT and so on) fold. Each title has a chevron beside it: click the chevron or the title and the group closes to its title, click again and it opens. A closed group stays closed the next time you start EFAS (the choice is kept per section in the settings, `folded_sections`).

- **Which modules.** Negative, Lab Look, Crop & Rotate, Edge Bleed, Watermark and Canister Watermark, the ones with several groups. A module with one group has no sections.
- **Groups that are not in use go away.** Negative shows only the controls that belong to the conversion you chose: with the Noritsu look the NORITSU LOOK group is there and WHITE / BLACK POINT is not (that one is Original's); a group with nothing showing in it is not shown at all, rather than a title over an empty space.
- **COLOR TRIM starts closed** in Negative (its Scanning light button stays on the title's row); the other groups start open.
- **Dropdowns.** Dropdowns with three or more choices have ‹ and › either side that step to the neighbouring choice (and wrap past the ends) without opening the list, and the white / black point Channel choice is one row of buttons, All, Red, Green and Blue.
- **Opening and closing is smooth.** A section (and a module, under its header) slides open and shut with its controls held at full size inside a clip that moves around them, so nothing inside squashes or shivers on the way and it ends on exactly the height it was heading for (`desktop/view/slide.py`).

## The red star

A module with something changed from its defaults has a red * after its name in the header, and is listed in the Enabled modules tab (the power button). They are the same test (`controller.module_is_active`: the module is on and its settings are not the ones it starts with), so put the module back to its defaults (its Reset button, or by hand) and the star goes and the module leaves the Enabled list, which updates while it is open. A slider being dragged holds the list until it is let go, so the module does not move from under the hand.
