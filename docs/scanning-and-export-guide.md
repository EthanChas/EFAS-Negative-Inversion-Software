# Scanning quality, merging and flat exports: a practical guide

These tools help you get a clean scan of a negative and take the result into other software. All of them are optional. Nothing here changes how an existing photo is converted unless you choose it.

## Scan quality (Negative tab)

When you open a RAW scan, the Negative tab shows a one-line verdict under SCAN QUALITY: good, clipped, underexposed or limited by the density of the film. It comes from the same measurements as Advanced mode (the film base, the headroom before the sensor clips, and the noise in the densest areas), explained in plain words with the number of stops involved.

- **Clipped**: part of the film base or the lightest areas reached the sensor's limit. Use a shorter exposure.
- **Underexposed**: the film base sits far below the sensor's limit, so shadows carry more noise than they need to. Use a longer exposure, or merge a bracket (below).
- **Limited by density**: the densest parts of the film are lost in noise at this exposure. A longer exposure, or a bracket, recovers them.

The verdict needs a RAW file (or a scan merged here). It can be switched off in Settings.

## Finding the film base automatically

Negative tab > **Find Film Base Automatically** looks for the clear border of the film in the open scan. It shows the area it found, marked on the scan, with how confident it is and why. **Nothing changes until you press Use This Film Base.** A border beside bare backlight is told apart from the backlight itself; a border with no backlight next to it is offered with lower confidence. If no border is found you are told, and you can still sample one yourself.

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

## Not included

Other processes (ECN-2 motion-picture film, for example) are not supported as a separate mode. The film base, density and curve tools are process-neutral, and you can characterize any process with a step tablet, but EFAS makes no claims about process-specific colour.
