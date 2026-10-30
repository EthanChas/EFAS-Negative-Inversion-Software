# Interface conventions (taken from NegPy)

NegPy has no design skill file. Its rules are the "UI conventions" section of its `CLAUDE.md` (also `AGENTS.md`), on top of `negpy/desktop/view/styles/` (`theme.py` the colour and size tokens, `templates.py` the control factories, `modern_dark.qss` the stylesheet, `color_vision.py` the colour-blind palettes). EFAS follows the same ideas in its own words and code; this page is the short list, for the next time a panel is added.

1. **A new control reuses an existing one.** It never brings a new look: the same sizes, colours and spacing from the theme tokens, never a literal in a stylesheet string.
2. **Every tab opens with a heading** (`desktop/view/tab_header.py`): its icon and name in capitals over one line saying what the tab is for, and a small heading over each group of modules in it. Modules keep their own cards under those headings.
3. **Groups inside a module fold** (`desktop/view/fold.py`): a chevron beside the title, the choice kept between sessions, and a group with nothing showing is not shown. A control that only matters when another is on goes in a group or under it, not beside it.
4. **Choices.** Two to four short fixed choices in view are a segmented row (`desktop/view/segmented.py`, `SegmentedControl`); a longer list is a dropdown with ‹ › arrows that step to the neighbour and wrap. An on/off choice is a checkbox or a toggle, never a pair of buttons.
5. **Reset.** Every editing module has a Reset in its header (and Presets where it has presets); a preset's name shows in grey beside the title, built-in presets included.
6. **Hide or gray out.** Hide a single control the mode can never use; gray out a whole group the mode cannot use, with one line saying why.
7. **Labels** are Title Case for a control and sentence case beside a dropdown; a unit goes beside the number, not in the label; every control has a tooltip.
8. **Words.** Plain words for a photographer who does not know darkroom terms; one sentence per tooltip where it can be.
9. **Changed means starred.** A module that is not at its defaults has a red * beside its name and is in the Enabled modules list; at its defaults it has neither (`CollapsiblePanel.set_changed`, `AppWindow._refresh_module_marks`).
10. **Things that open slide** (`desktop/view/slide.py`): the controls keep their size and a clip moves around them, never a height that squeezes the layout.
