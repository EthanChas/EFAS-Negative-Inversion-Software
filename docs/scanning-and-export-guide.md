# Scanning quality, merging and flat exports: a practical guide

*This guide, like the project's changelogs and release notes, is written by AI (Claude); see the README.*

These tools help you get a clean scan of a negative and take the result into other software. All of them are optional. Nothing here changes how an existing photo is converted unless you choose it.

## Scan quality (Convert tab)

When you open a RAW scan, the Convert tab shows a one-line verdict under SCAN QUALITY: good, clipped, underexposed or limited by the density of the film. It comes from the same measurements as Advanced mode (the film base, the headroom before the sensor clips, and the noise in the densest areas), explained in plain words with the number of stops involved.

- **Clipped**: part of the film base or the lightest areas reached the sensor's limit. Use a shorter exposure.
- **Underexposed**: the film base sits far below the sensor's limit, so shadows carry more noise than they need to. Use a longer exposure, or merge a bracket (below).
- **Limited by density**: the densest parts of the film are lost in noise at this exposure. A longer exposure, or a bracket, recovers them.

The verdict needs a RAW file (or a scan merged here). It can be switched off in Settings.

## Finding the film base automatically

Convert tab > **Find Film Base Automatically** looks for the clear border of the film in the open scan. It shows the area it found, marked on the scan, with how confident it is and why. **Nothing changes until you press Use This Film Base.** A border beside bare backlight is told apart from the backlight itself; a border with no backlight next to it is offered with lower confidence. If no border is found you are told, and you can still sample one yourself.

## One film base for the whole roll

Convert tab > **Find Film Base for the Whole Roll** reads the clear border of up to 12 frames spread along the open photo's folder and combines them into one film base. The border around a frame is the same film on every frame, so reading several of them steadies the colour from frame to frame, and what is in any single picture (a snow scene, a sunset) cannot pull the reading. Frames without a clear, even border are left out, and a roll is only offered a base when at least two frames have one and most of them agree. You are shown the colour and how many frames it came from; **nothing changes until you confirm**, and Clear goes back to estimating each photo on its own.

## Inverting before the camera's colour matrix (Settings > RAW decoding)

A RAW file is normally opened with the camera's white balance and its camera-to-sRGB colour matrix already applied. The matrix mixes the three channels and clips what falls outside sRGB, and on a negative that happens while the orange mask is still in the picture. Turning on **Invert negatives before the camera's colour matrix** opens RAW files in the camera's own colour channels (white balance still applied), inverts there, and puts the camera's colour matrix on the finished positive, in linear light, so neutrals stay neutral. It is off by default because it changes how photos you have already edited look, so try it on a copy of a roll first. While it is on, a 16-bit TIFF export of a RAW photo is written at 8 bits for the colour-matrix step; the 16-bit tone chain is used when it is off. `tools/compare_decode.py` writes the standard and the linear versions of a RAW file side by side so you can judge it on your own scans.

## Merging scans (File > Merge Scans)

Two kinds of merge, both from RAW scans, both saved as a new 16-bit linear TIFF with a small sidecar file (`.efas-merge.json`) that lets EFAS read the exact linear values back. Your original scans are never changed.

**Exposure bracket.** Scan the same frame with different exposure times (the same light). Short exposures keep the clear film base from clipping; long ones lift the dense areas out of the noise. Each pixel of the result is a weighted average of the frames in which it was neither clipped nor at the noise floor, weighted by how much noise each contributes, so you get the highlights of the short frame and the shadows of the long one. The merged scan is in the units of the shortest exposure, so the film base stays below 1.

- Exposure times are read from the files. **Check them.** A wrong time makes the merge wrong. EFAS compares the frames where they overlap and warns if a frame's signal does not match its stated time (a rounded time, flickering light, a sensor that is not linear).
- Keep the camera and film still. EFAS corrects shifts of a few pixels (to a small fraction of a pixel) and warns above two. It does not correct rotation or a change of scale.
- The result reports what share of the picture came from each frame, and the shadow noise reduction against the shortest frame alone.

**One light per colour.** If your light source can show red, green and blue separately, scan the frame three times, once under each colour, each exposed to suit its own film layer. EFAS takes the red channel from the red-lit scan, green from the green-lit one and blue from the blue-lit one. It warns when a channel clipped or is very dim.

The merged file opens like any photo, and is read as exact linear light, so scan quality, density, film base and the curve-informed inversion all work on it.

## Exporting without the look (File > Quick Export and the Export panel)

The Export panel has an **Output** choice. *Standard* is the picture as you edited it. The others export the conversion alone, as 16-bit TIFF, for finishing in other software:

- **Flat for grading**: the inversion and framing only, with no tone curve, contrast, colour or retouching, so you can grade it yourself.
- **Linear light**: the same, with the display curve removed, for compositing or colour-managed work.
- **Density (log)**: density above the film base, stored in a fixed range (0 to 4.0 density) so values can be converted back exactly.

Presets for the three are offered once. Each can also write a **conversion record** (`.json`) beside the picture: the source file and its checksum, the film base, inversion method and profile, your edits and the settings, so the conversion can be reproduced or audited later.

## Roll consistency (File > Check Roll Consistency)

Reads the RAW scans in the open folder and finds frames whose film base reads brighter, darker or tinted compared with the rest, which means the light, the exposure or the white balance changed during the scan. Each frame is listed with how far it differs (in stops) and why. Frames with a clear border are judged strictly; frames without one are estimated from the picture and judged more leniently, because the difference may be the scene. If you sampled a film base for the roll, it is used as the reference. Nothing is changed; the check only reports.

## Tethering a Canon camera (Extra > Canon Tether and Live View)

EFAS can drive a Canon camera on a copy stand: live picture as a positive with focus peaking and a loupe, the lens driven from the computer with a sharpness meter, and the shutter released without refocusing into a numbered roll folder. It needs your own copy of Canon's EDSDK (which EFAS cannot include) and works on Windows only so far; a practice camera lets you try it without a camera. The full description, what has and has not been tried, and troubleshooting are in [tether.md](tether.md).

## Check your scanning light (Extra > Check My Scanning Light)

Measures whether the light you scan with is steady and even, from RAW photos taken with your scanning camera. It reads the sensor's own values (black level taken off, no demosaic, no white balance, no profile), so the numbers describe the light and not any conversion, and it changes nothing. There are two checks. The method is adapted from [lightdrift](https://github.com/davidesqalv/lightdrift) by David Esquivel (MIT licence).

**Bare light.** Photograph the light with no film in the holder, on manual (fixed shutter speed, aperture, ISO and focus), bright but not blown out: two shots straight after switching it on, then one every 5 to 10 minutes for an hour or so, and touch nothing. Choose the photos (or their folder). Each is compared with the first: brightness (whether it dims or brightens, and when it settles), colour (red and blue each against green, which exposure cannot change), evenness (the middle of the frame against the four corners, a measure that includes the lens's own falloff), whether anything is blown out, and whether the camera settings stayed the same. The answer is a short list with a word for each (OK, SMALL, CHANGED, CHECK, FIX), a bottom line such as "let the light warm up about 10 minutes before scanning", charts, a map of the lit area for the first and the last photo, and the numbers shot by shot.

**Scans of a roll.** Choose the RAW scans of one roll of colour negatives. In each scan it finds the clear orange film border, the bare light in the sprocket holes and the black holder (shown in colour in the picture of what was measured, so you can see it found the right places), and compares each scan with a reference (the first colour negative, or the scan you pick). It reports: whether the clear film came out as bright as the shutter speed, ISO and aperture say it should (a gap means the light or the film changed, and a change of camera settings is named as the cause when that is the reason); the colour of the light in the sprocket holes against the colour of the clear film (a changed light moves both, a different film moves only the film); whether the camera chose the exposure itself; how many stops the clear film sits below blown out, with a suggested shutter speed when it is too dark; whether the densest film is down in the sensor noise; how even the light is toward the corners; and how much stray light reaches the black holder. A list of what to do closes the answer. Scans that are not colour negatives are skipped. It works best with a bit of border and the sprocket holes in the picture.

**Check Roll Consistency** (File menu) tells you which frames of a roll differ from the rest and can even them out; the film-scan check here explains why, from the camera's own settings, and also looks at exposure, stray light and evenness. The bare-light check is separate: it is about the light, not any roll.

Both checks read each file once, in the background (about a second a photo), and **Stop** ends the run. Camera settings and capture times come from the files' EXIF; where a RAW format does not carry them, the JPEG preview inside it is tried, and what is still missing is shown as a question mark and never guessed. **Save Report** writes the report as text and the numbers beside it as a .csv.

## Sharing a film profile

In Film Profiles, **Share as Bundle** writes a `.efasprofile` file holding the profile, optionally the camera set-up, your name and a note, and a checksum of each part. It shows a **fingerprint**: send it to the receiver by a different route (a message, say).

**Import** opens a bundle only after checking it: the files must match their checksums, nothing unexpected may be inside, the profile must be valid and its curves must be physically sensible (rising with exposure, within possible densities). It then shows what it contains and asks before importing.

What this proves and does not prove: it shows the file is intact and the numbers are sensible. It does not show who made it or how carefully the film was measured; anyone can build a consistent bundle. A profile received this way is always added as *supplied by someone else*, with the sender's name, the original claim and the fingerprint kept in its details, and it never overwrites your own.

## Colour accuracy from a colour target (Camera Set-ups > Colour Target)

If you have a transmission colour target (an IT8.7/1 slide or negative target and its reference file), scan it with the same light and exposure as your film, open it, sample the clear light, then load the reference file (CGATS text, or CSV with XYZ or Lab columns under D50) and mark the outer edges of the patch array and its columns and rows. EFAS reads each patch as the fraction of clear light each channel passes, fits a 3x3 matrix to the colours the maker measured (clear light maps exactly to white), and reports the colour error (Delta E 2000) before and after, and on patches held out of the fit. It rates the result excellent, acceptable or poor, and leaves out patches that are clipped, too dark or uneven.

The result is saved with the camera set-up as a record of how colour-accurate that set-up is. **The standard conversion does not apply it**; that is a deliberate choice, so existing conversions stay exactly as they were.

## Removing and deleting photos

Two different actions, kept apart on purpose.

**Remove from Workbench** takes a photo off the Workbench grid and the filmstrip. The file stays on disk with its edits, and it does not come back when the library refreshes. Use it for frames you do not want to see again but do not want to lose. Where: the Selection panel in the Workbench, right-click on a photo (Workbench or filmstrip), the Delete key in the Workbench grid, and File > Remove Open Photo from Workbench. **Removed Photos** (Workbench top bar, or File menu) lists them and restores any or all.

**Delete from Disk** deletes the files. It is in the same places (Shift+Delete in the grid, File > Delete Open Photo from Disk), and always opens a confirmation that shows how many photos, their names, where they are and their total size, in red, with Cancel as the default button. The red button stays disabled until you tick "I understand these files will be deleted from my disk".

- Files go to the **Recycle Bin**, never straight to oblivion. If the Recycle Bin cannot be used, nothing is deleted. A photo is only reported deleted once it is really gone from its folder; any that could not be moved are listed and left alone.
- The small files EFAS keeps beside a photo (its `.xmp` and merge sidecar) go with it.
- Only photo files are ever deleted: never a folder, and never another kind of file.
- Your saved edits, rating and tags stay, so a photo restored from the Recycle Bin comes back with its look.
- If the deleted photo is open in the editor, the editor moves to the next photo in the filmstrip.

## Crop Roll and Reset Crops (filmstrip)

Beside the photo count above the filmstrip, **Crop Roll** auto-crops every photo of the roll the way the editor's Auto Crop & Straighten button does for one: it finds the picture inside the scan's border and crops to it, straightening it first if it is slightly tilted. A small confirmation shows how many photos will be cropped. Photos that already have a crop are left alone unless you tick "Also replace the crops already made", and photos with no clear border are left as they are. **Reset Crops** takes the crop off every photo of the roll that has one (it says how many); rotation, straightening, tone and every other edit stay.

The photo open in the editor goes through the editor, so that one can be undone with Ctrl+Z. The others are saved directly, so a whole-roll crop cannot be undone in one step (the confirmation says so). The button turns into **Stop** while a roll is being cropped.

## Keystone correction (Crop & Rotate)

When the camera is tilted over a copy stand, or the film is not flat, straight lines lean towards each other. The **Keystone** sliders in Crop & Rotate fix that: **Vertical** widens the top of the picture (positive) or the bottom (negative), **Horizontal** does the same for the left and right. **Auto Keystone** looks for the long straight lines in the scan (film borders, frame edges, sprocket holes, walls), measures how they lean and sets the sliders; it then refines the result by correcting the picture and measuring again. It says so, and changes nothing, when the lines are already parallel, too few, or do not agree with each other. It is a suggestion to check, not a verdict: a picture whose straight lines are not meant to be parallel can fool it.

The correction cuts the corrected picture from inside the frame, so there are no empty corners, and it is stored with the photo like any other edit (and undoes like one). Spots and clone strokes you painted follow the correction. It is not part of copied or pasted looks, because it belongs to one scan.

## Virtual copies (Versions)

A virtual copy is another complete edit of the same scan, with no second file. In the editor's **Versions** panel, **Make Virtual Copy** starts a new version from the edit you have now and switches to it; the version you were on stays exactly as it was. Switch between versions by double-clicking. From the Workbench, **Make Virtual Copy** adds a version to each selected photo without opening it. Photos with copies show **x2** on their tile, and `versions:>1` finds them. In an export preset, **Also export virtual copies** writes every version; the copy's name is added to its file name (`photo_Black and white.jpg`).

Ratings, flags and tags belong to the photo, so all its versions share them, and so does the choice of inversion method. Thumbnails show the version you were last editing.

## Smart collections (Workbench)

The **Smart Collections** section saves the Workbench's filters (the search words, Collection, Date, Rating & Status and Sort settings) under a name. Choosing a collection applies them. It is not a list of photos: it re-runs on the whole library each time, so new photos that fit appear by themselves, and relative dates such as "Last 7 days" stay relative. Each collection shows how many photos it holds now. Save with the same name to replace one. A collection that names a camera, film or folder the library does not have right now keeps it, and shows no photos until one appears.

## Find duplicates

**Find Duplicates** (Workbench top bar, or File menu) looks through the photos in the Workbench. *Identical files* have exactly the same contents; only files of the same size are read, so it is fast. *Look-alikes* are found with a small fingerprint of each picture, so re-saved, resized and re-exported copies match. A fingerprint cannot tell a copy from another exposure of the same frame or the next frame of a burst, which is why look-alikes are listed for you to judge, not removed. Each photo is in one group only. In every group one photo is marked **keep (suggested)**: the highest rated, then edited, then with copies or tags, then the largest picture and file. The others are ticked.

**Remove Ticked from Workbench** takes them off the Workbench (the files stay), and **Delete Ticked from Disk** uses the same Recycle Bin deletion and confirmation as everywhere else. If every photo of a group is ticked, nothing happens until you untick one.

## Reporting a problem (Info > Report a Problem)

EFAS keeps a small log of what it reports, including errors that would otherwise vanish in a window with no console (`logs/efas.log` in the data folder). **Report a Problem** asks what happened and how to repeat it, then shows exactly what the report holds: the versions of the program and its libraries, your system, your preference switches, the sizes of the data files and the latest lines of the log, with folders stripped from every path and e-mail addresses blanked. Photos, edits, tags, notes, roll cards and folder names are never included.

**Nothing is sent by EFAS.** *Save Report File* writes a zip. *Open GitHub Issue* saves the file, then opens your browser at the project's new-issue page with your text filled in; you read it, press Submit (a GitHub account is needed) and drag the zip into the description to attach it.

## Module behaviour and colours (Settings > General)

**Open modules when the mouse is over them, close them when it leaves**: with this on, resting the mouse on a module (a collapsible panel such as Exposure or Crop & Rotate) opens it and moving off closes it, so only the one you are using is open. A brief pass over a module does not open it, and a module does not close while a mouse button is held (dragging a slider out of it), a drop-down list is showing, or you are typing in it. Click a module's header to **pin** it open; click again to unpin and close it. Modules that are open when you turn the setting on stay open until you click them. It is off by default.

**Colour-code modules**: every module gets its own header gradient. The colours are assigned, not random: a module has the same gradient every time and on every computer (the editor's modules have a fixed order spread round the colour wheel; a module added later gets a colour from a checksum of its name). Right-click a module's header to pick one of twelve named colours for it, go back to its automatic colour, or turn its colour off. It is off by default.

## Undo for whole-roll actions

Crop Roll, Reset Crops, Paste to Folder / Paste to Selected and Even Out Roll each leave a record of what they changed, and the **Undo** button beside Reset Crops (above the filmstrip) undoes the last one in this folder, naming it ("Undo Crop Roll"). It puts back only what the action changed, and only on photos that still hold what the action wrote: a photo you have edited since is left alone and listed. Other edits you made to a photo afterwards (say exposure) are kept when its crop is undone. The photo open in the editor is undone with Ctrl+Z, as before, except for a film-base change from Even Out Roll, which Undo reverts on every photo. The last five actions per folder are kept, and they survive closing the program.

## Find (Ctrl+K)

**Edit > Find a Control or Action** (Ctrl+K) opens a small search box. Type a name or what a control does and it lists the matching modules, sliders, buttons and menu actions: `brightness` finds Exposure, `straighten` finds Angle and Auto Crop & Straighten, `vignette` finds Flat Field, `perspective` finds the Keystone sliders. Up and Down choose, Enter goes there. For a module or control it switches between the Workbench and the editor if needed, opens the module and its tab, scrolls to it and flashes it; for a menu action it runs it. Every word you type must match. The key can be changed in Settings > Keybinds.

## Export: safety, output sharpening and 16-bit

- **Nothing is overwritten by accident.** An export never writes over one of its own source photos or over another photo exported in the same batch (two photos called `x.jpg` from different folders become `x.jpg` and `x_1.jpg`), even when the destination setting says to overwrite files from earlier exports. One photo failing does not stop the batch.
- **Unedited photos are flagged.** Exporting a folder, a selection or the keepers when some photos have no saved edits asks first: export all, only the edited ones, or cancel. Exporting the open photo, or "photos with saved edits", does not ask.
- **Output sharpening** (Export panel, 0 to 100) sharpens the finished picture at its final size, after any resize. The Sharpening module works at the editing size, which a resize then softens. Faint noise is not amplified, and flat areas are untouched. Try 20 to 40 for a resized picture.
- **16-bit TIFF.** With Format TIFF and Bit depth 16-bit, a photo with a 16-bit source and only edits that keep 16 bits (inversion, colour balance, exposure, contrast, tone curve, shadows/highlights, saturation, colour, chroma denoise, local contrast, crop and rotation) is written as a 16-bit TIFF tagged sRGB, which keeps the full precision of the scan for grading elsewhere. A photo with a step that works at 8 bits only switched on (sharpening, edge colour, vignette, border, watermark) or an 8-bit source is saved as 8-bit, and the export says how many. On the command line: `--sharpen 30 --bit-depth 16`.

## Check Flat Field

In the Flat Field module, **Check Flat Field** measures how even a picture of the light is: the smooth shading in stops (what the correction is for), blotchiness (dust, marks on the light, picture content), colour shading, and how much is clipped white or too dark. It can check the open photo (after the folder's flat field, if one is on, to show what is left), or any file as a reference. A reference is checked before it is saved: if it is clipped or blotchy you see why and choose to use it anyway or cancel, because a correction made from it would copy those marks into every frame. After Auto (Roll) builds a correction, it also reports whether the correction is strong or capped.

## Even Out Roll

In **Check Roll Consistency**, **Even Out Differing Frames** converts each frame the check found different against its own film base (its clear border, read as the picture shows it) instead of the roll's, so it matches the rest. Only frames whose border EFAS is sure about (high confidence) are touched, and a border that is not a uniform patch in the picture is skipped. The roll's film base and your other edits are not changed. It is undone with the Undo button above the filmstrip, or for the whole roll with **Use the Roll's Film Base Again**. Setting the roll's film base while a photo is open removes that photo's own film base.

## Workbench: search suggestions and the Library list

**Search suggestions.** Type in the Workbench search box and EFAS offers what you can say: `rat` offers `rating:`, `rating:>` offers `rating:>=1` to `rating:>=4`, `camera:` offers the cameras your library has, and a plain word such as `canon` offers values that start with it (`camera:"Canon EOS R"`). Each suggestion shows what it means and how many photos it matches. Pick one with the arrow keys and Enter or the mouse; it replaces only the word you were typing, so earlier terms stay, and a leading minus (`-fl`) is kept (`-flag:`). Choosing a field name such as `rating:` opens the list of its values straight away.

**Library list.** The Workbench's left column starts with the same folder list as the editor's Library (they share the same folders: add or remove one in either and the other follows). Click a folder to show only the photos in it and its subfolders. The reset button (the loop icon) in the Library's header clears the choice, so no folder is selected and every photo shows. The folder choice is saved with a smart collection. Settings > General > **Show the Library folder list in the Workbench** turns the list off.

**Organising folders.** Right-click a folder in either Library list (they are the same list, so a change in one shows in the other):

- **New Folder...** asks for a name and makes an empty folder on your disk inside the one you clicked. Names Windows does not allow (`\ / : * ? " < > |`, a trailing dot, `CON` and the like) are refused with the reason.
- **Rename Folder...** renames the folder on your disk, in the place it is in; it never replaces another folder. Everything EFAS keeps for the photos in it follows them to their new paths: edits and their history, versions, snapshots, ratings, flags, tags, the film base, photos taken off the Workbench, the folder's own flat field, Roll Card and film-base settings (and those of the folders inside it), smart collections that look in the folder, the library index and the thumbnails. A hotstack mark, the recent folders, a live session in progress and the folder open in the filmstrip follow too, and a photo open in the editor is opened again at its new place. A root can be renamed as well.
- **Move Folder to...** picks another folder and moves this one into it; dragging the folder onto the other folder does the same after a confirmation. Everything listed under Rename follows. A folder cannot go into itself, over a folder of the same name, or to another drive (that would mean copying every photo and deleting the originals, which is left to File Explorer: move it there, then add the new place with the + button). If the new place is outside the Library folders the folder drops off the list.
- **Move to Folder...** for photos (the Workbench's button and right-click menu, and the filmstrip's menu) asks for a folder and moves the selected photos into it with their `.xmp` and merge sidecars. A name that is taken in that folder is never overwritten (the photo becomes `name_1`, `name_2`...). Each photo keeps its edits and history, versions, snapshots, rating, flag, tags and film base; the library index and the thumbnail follow, a photo that was open is opened again at its new place, and a photo of a live hotstack session that you move leaves the session.
- **Delete Folder...** shows what is inside (photos and their size, folders, other files) and moves the folder and everything in it to the **Recycle Bin**, only after you tick the box and press the red button; Cancel is the default. It never deletes for good: with no Recycle Bin available nothing is deleted, and if Windows cannot use the Recycle Bin for the folder (too big, or on a drive that has none) Windows asks you first. The saved edits, ratings and tags stay in EFAS, so photos restored from the Recycle Bin get their look back. It is refused while a photo from the folder is open in the editor, for EFAS's own data folder, for a drive, and for a link.
- **Remove from Library** takes a folder off the list. A root leaves the root list as before; a folder inside a root is *hidden* together with the folders in it, and its photos leave the Workbench. Nothing on disk or in the edits changes. **Bring Back Removed Folders** (in the right-click menu once there is one, also when you right-click empty space in the list) shows them all again and reads their photos back into the Workbench.

## Command line

The same conversion without a window, for batches and scripts (from a source install; the packaged Windows app has no console):

```
python -m photoeditor convert ROLL_FOLDER --preset "Print" --out OUT_FOLDER
python -m photoeditor convert A.CR2 B.CR2 --kind flat --record
python -m photoeditor presets
python -m photoeditor info IMG_0001.CR2
python -m photoeditor check-roll ROLL_FOLDER
python -m photoeditor merge --bracket A.CR2 B.CR2 C.CR2 --times 0.01 0.04 0.16 --out merged.tif
```

It reads the editor's data folder, so saved edits, film bases and your export presets apply exactly as in the editor (use `--data-dir` for another folder, and `--versions` to include virtual copies). A preset is matched by name, or by part of its name when that is unambiguous. `convert` writes beside each photo in an `Export` folder unless `--out` is given, never overwrites unless `--overwrite` is given, and exits with status 1 when any photo failed (2 for a bad command).

## Not included

Other processes (ECN-2 motion-picture film, for example) are not supported as a separate mode. The film base, density and curve tools are process-neutral, and you can characterize any process with a step tablet, but EFAS makes no claims about process-specific colour.
