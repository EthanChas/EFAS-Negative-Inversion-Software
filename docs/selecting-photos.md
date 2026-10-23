# Selecting several photos

**In the Workbench** the grid has always taken a normal selection: click one, **Shift-click** another to take every photo between them, **Ctrl-click** to add one or take one away, drag round some tiles, and Ctrl+A for all. The right-hand panel and the buttons then act on all of them (rate, flag, tag, export, move, remove, delete, paste settings).

**In the editor's filmstrip** the same works now:

- A plain click opens the photo, as before, and selects only it.
- **Shift-click** selects every photo from the open one (or the last one clicked) to the one clicked, and **Ctrl-click** adds or takes away one. Neither opens anything, so you can build a selection without leaving the photo you are editing. A drag round some tiles selects them, and **Ctrl+A** selects the strip.
- The open photo is always marked: with a thinner accent frame when it is not selected, and with a light frame just inside the selected one when it is part of the selection.
- With **several** photos selected, the rating keys (1 to 5, 0) and the flag keys (K, R, U) act on **all** of them, and pressing a mark that all of them already have takes it off all of them, as it does for one photo. Auto-advance is not used with several selected.
- **Right-click** a selected photo for the menu for the whole selection: Rate, Flag, Paste Settings (when something has been copied), Remove from Workbench, Move to Folder and Delete from Disk. Right-click a photo that is not selected and it is selected on its own, with the ordinary menu (Open, Retake, Remove, Move, Delete).
- Opening another photo (a click, or the arrow keys) collapses the selection to that photo.

Code: `desktop/view/filmstrip.py` (the selection, the menu, the signals), `desktop/view/thumbnail_delegate.py` (the mark of the open photo), `AppWindow.strip_selection` and `mark_selection`, and `tests/test_filmstrip_selection.py`.

# Sliders and the mouse wheel

The wheel does nothing to a **slider, a number box or a drop-down until it has been clicked**: before that it scrolls the panel behind it, so scrolling a long tool list no longer changes every slider the pointer passes over. Once a control has been clicked it takes the wheel as before. A slider lets go of that again when the pointer leaves it; number boxes keep their focus (a number may be being typed), and scroll bars are left alone. One filter on the application does it for every control, in every window and dialog: `desktop/view/wheel_guard.py` (`tests/test_wheel_guard.py`).

# Photos that have been moved

When Finish Session or Move to Folder moves a photo, everything saved for it goes with it, and now so does its **plain thumbnail** as well as the edited-look one, so its tile does not have to be made again. The tiles of the moved photos are asked for as soon as they are moved (in the Workbench and the editor's strip), and a thumbnail that cannot be read the first time (a file that has only just been moved or written is often held for a second by the camera's software, a virus scan or the indexer) is tried again, three times, instead of being left blank until the photo is opened. See `features/browse/processor.py` (`get_thumbnail_with_retry`), `AppController.photo_thumbnails` and `AppWindow.refresh_thumbnails`, and `tests/test_thumbnails_after_a_move.py`.
