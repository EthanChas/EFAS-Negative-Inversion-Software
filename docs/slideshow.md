# Slideshow

The **Slideshow** button (before Workbench and Editor) plays your photos with their saved edits, with music if you want it, and can make the show into an MP4 video.

## The photos

**Photos** chooses where they come from: *Shown in the Workbench* (what its search and filters leave, in its order), *Selected in the Workbench*, or *Open folder (filmstrip)*. Each photo is made with its saved edits (an unedited negative is shown inverted, as the editor opens it), or as the scan is with **With edits** off, at the size the stage needs (up to 4K), on a worker thread; the next two are made ahead, so the show does not wait on a RAW decode.

**Choose photos...** opens a grid of thumbnails (the Workbench's own) with a tick on each: untick a photo to leave it out of the show **and of an exported video**; Select all, Select none and Invert do what they say. **X** leaves out the photo on screen and moves on. The count beside the button says how many are left out. Nothing is deleted or changed, and the left-out photos stay left out when you change the source, until you put them back (they are forgotten when EFAS closes).

## Playing

**Each photo for** 1 to 120 seconds; **Change with** a cut or a 0.7 s crossfade; **Shuffle** (the photo on screen stays up), **Loop**, **Captions** (the file name, with the film, roll and day when the Workbench knows them), **With edits**, and **Progress bar**: a thin bar along the bottom of the stage that fills as the photo's time runs out, freezes when you pause and carries on from there.

| Key | |
|---|---|
| Space | play / pause |
| Right, Down, Page Down, N | next |
| Left, Up, Page Up, P | previous |
| Home, or the restart button | back to the beginning: the first photo of the show and the start of the music (playing or paused stays as it was) |
| End | the last photo |
| X | leave this photo out |
| F, F11, double-click | full screen (the stage moves into a black window; Esc leaves; the cursor hides after two seconds) |
| C | captions on / off |

The editor's own keys (arrows stepping the roll, 0-5 rating, R / K / U flags) do nothing while the Slideshow, Maps or Classroom page is up.

## Music

**Music** plays while the show plays, loops, and waits while it is paused; leaving the page stops it. The choices are:

- three **built-in pieces**, made inside EFAS from sine waves, plucked strings and an electric-piano voice (so there is nothing to license; the same sound each time). They are made the first time you choose one (a few seconds) and kept as WAV files in EFAS's folder: **Drifting** (60 beats a minute, slow pads, a long reverb), **Morning Light** (76, plucked arpeggios) and **Night Reel** (84, a warm lo-fi). Each is a loop that joins up with itself;
- **your own .wav and .mp3 files**: **Add music...** copies them into EFAS's folder (`slideshow-music/yours`) and lists them as "name (yours)". The file you add from is never touched. **Remove** deletes only EFAS's copy. A file has to look like a WAV or MP3 and be between 1 KB and 200 MB.

**Volume** is remembered with the choice. If the music cannot be played (no audio output, or a file the system cannot decode) a note appears beside the music box and the show carries on without it.

## Making a video

**Export video...** opens a dialog: where to save the `.mp4`, a **size** (HD 1280 x 720, Full HD, QHD, 4K), a **frame rate** (24, 25 or 30), **seconds per photo**, **cut or crossfade**, whether to **burn the captions in**, and the **music** and its volume. Each photo is fitted into the frame on black (nothing is cropped) and held for its seconds; with Crossfade the first 0.7 s of each photo fade in from the one before, as on screen, so the video is exactly (photos x seconds) long. Photos left out of the show are left out of the video. A photo that cannot be made is skipped and the dialog says so.

- **With ffmpeg** (found through the path you choose in the dialog, then the PATH, then the `imageio-ffmpeg` package if it is installed) the video is H.264 with the music mixed in as AAC: looped to the length of the video, at your volume, and faded out over its last two seconds. If that ffmpeg has no libx264 it falls back to its MPEG-4 encoder. On Windows: `winget install Gyan.FFmpeg`.
- **Without ffmpeg**, OpenCV's own MP4 writer makes the video: it plays almost everywhere but uses the older MPEG-4 codec and **has no sound**. The dialog says so before you start, and again if you chose music.

The video is written to a hidden partial file and renamed when it is finished, so Cancel (or a failure) leaves nothing behind.
