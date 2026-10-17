"""The Classroom's guides to the program itself: getting around EFAS and how its modules work, and the tools that work on a whole roll."""
from .logic import Lesson, Section

SECTIONS = [
    Section("tour", "Getting around EFAS", "Opening photos, the library, going through a roll, and how the modules work and combine."),
    Section("roll", "Working a whole roll", "The roll card, presets, copies, tags, shooting tethered, slideshows and keeping your work safe."),
]

LESSONS = [
    # ------------------------------------------------------------------ getting around
    Lesson("opening-photos", "tour", "Opening photos and folders", "Understand the ways to open a photo or a roll, and why a folder per roll is the habit that helps most.",
           r"""
EFAS opens RAW files (CR2, CR3, NEF, ARW, DNG and the other common RAW formats), TIFF, PNG and JPEG. There are several ways in, and they suit different moments.

**File > Open Image...** opens one file. **File > Open Folder...** (`Ctrl+Shift+O`) opens a whole roll: the filmstrip fills with the folder's photos and the first one opens in the editor, or the one you were last on, since EFAS remembers the photo you were on in each folder. **File > Open Recent** lists the folders you used lately. You can also **drag** a folder or a photograph from Explorer onto the window, and the **Library** list gives you a permanent set of folders to click through ([[library-and-folders]]).

## Why one roll per folder

Many of EFAS's settings belong to a **folder** rather than to a single photo, and that is what makes a roll feel like a unit. The film base you sampled, the flat field, the Roll Card, and a whole-roll crop all apply to every frame in the folder, and they are saved with it. If two rolls share a folder, they share those settings, and a film base sampled for one will quietly be wrong for the other. Name the folder after the date and the film (`2026-10-12 Portra 400`), and the habit pays back for years.

## Where your edits live

EFAS never changes your scan files. Your edits are stored in a small database in EFAS's own data folder, filed against **where each file is**. So you can move the whole library to another drive, as long as you keep to EFAS's own ways of moving things, and keep a backup of both your scans and your data (see [[data-safety]]). Renaming or moving a file *outside* EFAS breaks that link: the photo opens as a fresh, unedited scan, though its old edits are still in the backups.
""", keywords=("open", "folder", "file", "drag", "import", "recent", "roll", "library", "raw", "database"), see=("library-and-folders", "filmstrip-and-culling")),

    Lesson("library-and-folders", "tour", "The Library: your folders at a glance", "See how the Library list organises your roots and folders, and how it differs between the editor and the Workbench.",
           r"""
The **Library** panel is a folder tree, like the shelves of a film library. You add one or more **root folders** (for example `D:\Film Scans`) with the **+** button, and every folder inside a root appears below it. The tree reads a folder only when you open it, so a huge archive costs nothing until you look inside.

## What a click does

In the **editor**, clicking a folder opens it as a roll: the filmstrip fills with its photos. In the **Workbench**, clicking a folder narrows the grid to the photos in it and in the folders inside it; the reset button in the panel's header clears the choice and shows every photo again. The two Library lists show the same folders and stay in step: adding or removing a root in one adds or removes it in the other.

Each folder shows a muted note on the right: how many photos it holds, or, if you have sorted by date, the date of the newest. **Sort** orders the folders by name, by date (when the newest photo in each last changed), by number of photos, or in the order you added them.

## Right-click

Right-click a top-level folder to **remove it from the list**. Only the entry goes: your photos and edits are never touched, and you can add the folder back at any time. Right-click *any* folder to **Mark as Hotstack** (the folder turns red and is watched for photos as they arrive: see [[hotstack-lesson]]) or to show it in Explorer.

## Roots and folders you opened by hand

The Workbench covers the Library's roots, and also any folder you have opened recently or are viewing now, so a folder you opened from the File menu appears in the Workbench without being a root. The Library list is how you make a folder permanent.
""", keywords=("library", "folders", "root", "tree", "sort", "browse", "add folder", "hotstack"), module="Library", see=("workbench-lesson", "hotstack-lesson")),

    Lesson("workbench-lesson", "tour", "The Workbench: your whole library as a grid", "Learn how the Workbench finds photos with its search, filters and smart collections, and how to act on many photos at once.",
           r"""
The **Workbench** (press `W`, and `D` to go back to the editor) is the library as a grid of thumbnails: every photo EFAS knows about, in one place. It is for *finding, judging and organising* rather than for editing, and it is built around a search that understands what you know about a photograph.

## Finding photos

The **Search** box accepts plain words, every one of which must appear somewhere in a photo's name, folder, camera, lens, film, roll, note, place or date. Add **field terms** to be exact: `camera:canon`, `lens:100`, `film:portra`, `roll:tokyo`, `folder:hotstack`, `ext:cr2`, `iso:400` (or `iso:>=800`, or `iso:100-400`), `date:2026-10` (or a single day, or a range like `date:2026-09..2026-10`), `rating:>=3`, `flag:keeper`, `edited:yes`, `tag:family`, and the faults you marked, `error:scratch`. A minus sign in front leaves matches out (`-camera:canon`). Suggestions appear as you type.

The panels below the search narrow the library without typing: **Collection** by folder, camera, lens, film, ISO or tag, with the number of photos each has; **Date** by day, week, month, year or a range you choose; **Rating & Status** by stars, flag, edited or not, and faults; **Sort** by date, name, rating and more.

A **smart collection** saves a search under a name. It is *not* a list of photos: it re-runs on the whole library each time you pick it, so a photo that fits appears in it by itself.

## Acting on photos

The right-hand column has **Image Information** (what the library knows about the photo) and **Selection**, which acts on every selected photo: rate (`1` to `5`) and flag (`K`, `R`, `U`) them, add tags, open one in the editor, **Export Selected...**, copy the settings of one and paste them on many, **Make Virtual Copy**, and take photos off the Workbench or delete them from disk (to the Recycle Bin, after a confirmation).

The slider in the top bar changes the thumbnail size (or hold `Ctrl` and scroll), **Refresh** looks for photos that were added or removed outside EFAS, and **Removed Photos...** brings back photos you took off. **Find Duplicates...** looks for identical files and look-alike pictures.

The Workbench shows the *edited* look of each photo in its thumbnail once you have opened it in the editor, so a roll you have worked on looks worked on at a glance.
""", keywords=("workbench", "lighttable", "grid", "search", "filter", "sort", "library", "smart collection", "thumbnails"), module="Smart Collections", see=("tags-and-collections", "filmstrip-and-culling")),

    Lesson("filmstrip-and-culling", "tour", "The filmstrip and culling a roll", "See how the filmstrip, the keyboard and the flags let you choose the frames worth finishing, quickly.",
           r"""
Across the bottom of the editor is the **filmstrip**: one thumbnail for each frame of the roll you have open. Click a frame to open it, or step with the arrow keys. It is the quickest way round a roll, and also the place where a roll is **culled**.

## Culling

Culling is choosing which frames are worth your time, and the point of the keyboard shortcuts is to do it fast, with one hand, without moving the mouse. `Left` and `Right` step through the frames, `Home` and `End` jump to the first and last. `K` marks a **keeper**, `R` marks a frame **rejected** and `U` clears the flag; `1` to `5` give stars and `0` takes them away; `T` opens the quick tag bar. With **Auto-advance after flagging** turned on in Settings > General, marking a frame moves to the next one automatically, so a whole roll can be culled with a single key per frame.

A rejected frame is only *flagged*: nothing is deleted. To take it out of the lists, right-click it and choose **Remove from Workbench** (the file stays on disk), or **Delete from Disk...**, which sends it to the Recycle Bin after you confirm.

## Using what you marked

The filmstrip's **filter** menu shows only what you want to see: *All photos*, *Keepers*, *Not rejected*, *Rejected*, *Unedited* or *Rated (1+ stars)*. The Export panel can export just the keepers, and the Workbench can search `flag:keeper`. A good rhythm is to cull the roll first (one quick pass, flagging as you go), then work on the keepers, and finally export them as a batch.

## Whole-roll buttons

The filmstrip also carries the buttons for tools that act on every frame at once, such as **Crop Roll** and **Reset Crops**, and an **undo** for them, because a change to a whole roll deserves its own undo ([[whole-roll-tools]]).
""", keywords=("cull", "rate", "stars", "flag", "keeper", "reject", "filmstrip", "navigate", "shortcut", "filter"), see=("tags-and-collections", "exporting")),

    Lesson("histogram-panel", "tour", "The histogram and its read-out", "Learn every part of the histogram panel: the graphs, the log and split views, the clipping arrows and the plain-words read-out.",
           r"""
Beside the picture, the histogram panel (titled **White Balance** in the sidebar) shows how the picture's tones are spread, and it updates as you edit. If you are new to reading one, [[histogram-basics]] explains the idea; this guide covers what the panel itself offers.

## The graph

**Color** shows three graphs, one each for red, green and blue, so you can see a colour channel running out of range before the picture shows it. **Exposure** shows a single brightness graph. **Log** changes the height from linear to a logarithmic scale, so small amounts at the ends (a few percent of pixels blocked or blown) become visible. **Split** separates red, green and blue into three strips. For a black-and-white negative the Color graph is greyed out, since there is only brightness.

**Scroll** over the graph to zoom, **double-click** to reset. **Hover over the picture** and the graph marks that pixel's brightness; hover the graph itself for a value and a count.

## The clipping arrows

In the graph's corners, a triangle on the left and one on the right give the **percentage of the picture that is blocked (left) or blown (right)**. Click one and those tones are painted on the picture, in blue for shadows and red for highlights, so you can see exactly where they are. They are the same marks as the **Shadow / Highlight Clipping** buttons.

## The read-out

Below the graph, a short block of plain words describes the picture: its **exposure**, **contrast**, **range**, how much is **clipped**, its **colour** and **saturation**, and the channel averages, followed by the **scan quality** verdict. Hover a row for the full detail. It is a second opinion: a quick check that a picture which *looks* fine is not secretly losing its highlights.

NOTE: The histogram describes the finished picture before the **vignette and border** are added (they are applied last), so it always describes the photograph itself.
""", keywords=("histogram", "graph", "readout", "clipping", "levels", "log", "split", "white balance panel"), module="White Balance", see=("histogram-basics", "clipping")),

    Lesson("viewing-tools", "tour", "Viewing tools: zoom, before & after, peaking, HQ", "Understand what each viewing aid shows you, and what the preview is and is not.",
           r"""
A few viewing tools help you judge a picture, and one of them changes what you are judging.

## Zoom and moving about

Scroll over the picture to zoom, drag to move it, and press `Z` to flip between **fit to window** and **100%**. 100% shows one picture pixel to one screen pixel, which is the only honest view for judging sharpness, grain and dust.

## Preview and HQ

By default you edit a **preview**: a reduced copy of the scan, so sliders respond instantly even on a huge file. **HQ** (`Ctrl+H`) switches to the photograph's **full resolution**, which is slower on a big scan but is exactly what an export will be made from. Use the preview to work and HQ to check, especially for the detail tools. **Settings > General** can switch HQ on for every photo you open.

## Looking at the picture

**Before & after** (`\`) splits the picture so you can compare your edit with the original scan. **Focus peaking** (`Ctrl+Shift+F`) paints the sharp edges of the picture, which makes it easy to judge whether a scan is in focus and where the focus falls. **Error marks** (`Shift+E`) show or hide the faults you marked. **Hide the panels** (`Tab`) gives the picture the whole window.

The proofing tools, **test strip** (`Shift+T`) and **ring-around** (`Shift+F`), show variations side by side: see [[proofing-tools]].

TRY: Zoom to 100% on a sharp edge, turn peaking on and then off. You will quickly learn what 'sharp' looks like in your own scans, and which parts of a scan the focus has missed.
""", keywords=("zoom", "before after", "split view", "peaking", "fit", "100%", "hq", "full resolution", "hide panels", "preview"), see=("proofing-tools", "focus-and-sharpness")),

    Lesson("modules-basics", "tour", "How a module works", "Learn the controls every module shares: the header, the power light, reset, sliders, presets and help.",
           r"""
Every tool in EFAS is a **module**, a collapsible panel such as Exposure, Crop & Rotate or Sharpening, and they are all built the same way, so once you know one you know them all.

## The header

Click a module's header to open or close it. Beside the name is a **power light**: green when the module is on and red when it is off. Click it to see the picture *without* that module while keeping every setting, which is a quick way to judge what a tool is really doing. The **reset** button puts the module back to its defaults, and the **?** gives the short help for the module (this Classroom goes further).

## Sliders

Drag a slider, or type an exact number into its box. **Double-click** a slider to reset it to its starting value, and use the mouse wheel for fine steps. A slider at its resting value does nothing at all: the module is exactly neutral, bit for bit, which is why you can leave a module open without it affecting the picture.

## Presets, search and tidiness

Most modules have an **Update Preset** button: a module can keep **its own presets**, saved sets of just that module's sliders, which you can apply on their own or fold into a bigger look ([[presets-lesson]]).

The **module search box** above the tabs finds a module by name or by what it does (`tint`, `dust`, `brightness`) and gathers the matching modules from every tab into one list; clearing it (or `Esc`) sends each module back to its place. `Ctrl+K` does a similar job for any control or action ([[find-and-search-controls]]).

**Settings > General** can make modules open when the mouse is over them, close when you change tab, and give each its own colour.

## Order

Tabs and modules follow the order a picture is worked on, so working from the first tab to the last is a good default. The order the work is *actually done in* is described in [[order-of-operations]].
""", keywords=("modules", "power light", "reset", "slider", "double-click", "presets", "search", "controls", "header", "on off"), see=("order-of-operations", "undo-and-history")),

    Lesson("order-of-operations", "tour", "The order in which EFAS works on a picture", "Follow a photograph through the whole chain, from the scan to the exported file, and see why the order matters.",
           r"""
Editing is a **chain**: the picture passes through the tools in a fixed order, and each tool works on what the one before it produced. You do not choose the order, which is a good thing, because the order matters a great deal. Here it is, from the scan to the file.

## On the scan

The scan is first corrected as a *scan*: the **flat field** evens out the backlight, and **dust and scratch repairs** are made. Then the geometry is applied: **straightening, distortion correction and keystone**, then any quarter turns and flips. The **edge tools** (Fill holder, Bleed repair, Edge dodge) work next, from the edge of your crop. These all come before the conversion because the conversion measures the picture, and it must measure the corrected picture.

## The conversion and the early tone

Then the negative is **converted**, with the **colour trim** and the Color module's **Temperature and Tint**, then **Exposure**, **Contrast** and **Print Response**. All of these work on each colour channel separately, so EFAS folds them into one lookup table, which is why changing them is instant.

## Pixel by pixel

Next come the tools that look at neighbouring pixels or at the colour of each pixel: **Chroma Denoise**, **Local Contrast**, **Shadows & Highlights** and **Saturation**. After them, a second lookup applies the **Tone Curve** (the master curve, then red, green and blue) and the **Lab Look**.

## Colour and detail

The **Color Mixer**, **Vibrance**, the scanner colour response and **Color Toning** come next, working in OKLCH on the finished tones. **Sharpening** comes after them.

## The finishing

Only now is the picture **cropped**. The histogram is measured on the cropped picture. Then come **Edge Color**, the **Vignette**, the **Watermark**, the **Border mask** and the **Border**, and last of all, the export's own resizing and output sharpening.

## What this means for you

Work roughly from the first tab to the last. An early change can alter how a later tool looks: a different crop changes the measurement, so colours can shift; a different conversion changes what the tone tools are shaping. If a late tool seems to misbehave, look at the early ones first. And since **presets and copy / paste carry the values** of the tools, but not the crop, rotation or dust repairs (which belong to one particular frame), a preset applied to another photo recreates the *look*, not the framing.

(The fuller story of how modules combine, and how a preset stacks on a module, is in `docs/how-modules-stack.md`.)
""", keywords=("pipeline", "order", "stack", "sequence", "first", "last", "before", "after", "chain", "process"), see=("modules-basics", "presets-lesson", "tone-overview")),

    Lesson("undo-and-history", "tour", "Undo, redo and the History panel", "Understand the layers of going back, from a single step to a whole photo.",
           r"""
Editing is exploration, and the freedom to explore depends on being able to go back. EFAS gives you several levels of undo, from the smallest to the largest.

**Undo and redo** (`Ctrl+Z`, `Ctrl+Y`) step back and forward through your changes. A drag of a slider counts as one step, however long the drag, so you undo what you *did*, not every intermediate value.

**History** is the same record made visible: a running log of every edit to the open photo, each with a description such as 'Exposure +0.30'. Select an entry and press **Revert** to go back to that moment; the edits made after it are discarded. It is the tool for 'I liked it three changes ago'.

**Snapshots** save the whole edit under a name so you can return to it by choice: see [[snapshots-lesson]]. **Virtual copies** keep two versions side by side: see [[versions-lesson]].

**Reset all edits** (`Ctrl+Shift+R`) puts the photo back to the plain converted scan.

Whole-roll actions, such as **Crop Roll**, change many photos at once, so they have their own **undo** button in the filmstrip. Use it straight away if a roll action was a mistake.

TIP: Before a long or risky session, save a snapshot called `before`. It costs nothing, and you can always come back to it.
""", keywords=("undo", "redo", "history", "revert", "reset", "back", "ctrl+z"), module="History", see=("snapshots-lesson", "versions-lesson")),

    Lesson("snapshots-lesson", "tour", "Snapshots: keeping a look to come back to", "Learn what a snapshot stores, how it differs from a preset and from a virtual copy, and when to use each.",
           r"""
A **snapshot** saves *everything* about this photo's edit under a name: tone, colour, crop, rotation, dust repairs and watermark. You then try something else, and if you do not like it, you go back.

## Using snapshots

**Save** a snapshot from the **Snapshots** panel and give it a name, such as `warm` or `before dust`. To go back, double-click it (or select it and press **Apply**). Applying a snapshot is **one undoable step**, so even that can be undone. **Update** overwrites the selected snapshot with the photo as it is now.

## How it differs from the alternatives

A snapshot belongs to **one photo**. A **preset** ([[presets-lesson]]) is for sharing a look *between* photographs, and does not include the crop, rotation or repairs, which belong to a particular frame. A snapshot includes everything, because it is about getting back to a state of *this* photo.

A snapshot and a **virtual copy** ([[versions-lesson]]) both let you keep a variation, but differently. A snapshot is a memory of one edit: the photo is still only one edit at a time, and you move between them. A virtual copy is a second version that *exists alongside* the first, so both can be exported and both show in the Workbench. If you want a colour version and a black-and-white version of a frame, both to export, make a virtual copy; if you want a safe point to retreat to, take a snapshot.
""", keywords=("snapshot", "save look", "go back", "checkpoint", "try", "compare"), module="Snapshots", see=("undo-and-history", "versions-lesson")),

    Lesson("find-and-search-controls", "tour", "Finding any control with Find (Ctrl+K)", "Jump straight to a tool, a menu action, a preset or a collection by name.",
           r"""
With dozens of modules and hundreds of controls, the fastest way to a tool is often to name it. Press `Ctrl+K` and start typing: **Find** searches every module, every control inside every module, every menu action, every preset, every module preset and every smart collection.

It understands everyday words as well as names. Typing `brightness` finds **Exposure**; `grain` finds the denoise and sharpening tools; `dust` finds the Dust & Scratches module and the AI dust module and the dust controls inside them. Pick a result and EFAS does the rest: it switches to the right page and tab, opens the module, scrolls to the control and **flashes** it so you can see where it is. For a menu action it runs it.

The **module search box** above the tabs is a different, quieter tool for a similar job: it gathers the matching *modules* into one list in the place of the tab you were on, so you can use several of them together without hopping between tabs ([[modules-basics]]).

TRY: Press `Ctrl+K`, type `vignette`, and see how many places it turns up: the Finishing module's slider, its presets, and related tools.
""", keywords=("find", "search", "ctrl+k", "jump", "command", "quick", "names"), see=("modules-basics",)),

    # ------------------------------------------------------------------ working a whole roll
    Lesson("roll-card-lesson", "roll", "The Roll Card", "Understand why a roll has a card, what each part of it records, and how it reaches your exported files.",
           r"""
A roll of film is a unit: one film, loaded in one camera with one lens, shot over a few days, developed one way and scanned one way. When you scan it, that unit dissolves into a folder of files that say only 'scanned on this day, with this camera'. The **Roll Card** puts the unit back, and it does so with a simple rule: it belongs to the **folder**, so every photo in the folder inherits it and you fill it in **once**.

## The roll

In the **Roll Card** tab, the **Roll** panel holds what the whole roll has in common: the **film** (with its ISO and format), the **camera**, the **lens**, the **first and last day** it was shot, how it was developed and scanned, and notes. Names you have used before are suggested as you type, which makes it quick to repeat for the next roll. Give a first and a last day and EFAS dates the frames **evenly across them**, which is right for a roll shot over a holiday.

## This frame

**This frame** holds the details of one photograph only. Its **frame number**, which, left on auto, follows the photo's place in the folder's filmstrip; a **date** that overrides the roll's dates for this frame; a **place**; and your own **note**.

## Presets for your gear

**Roll Card Presets** remember your own cameras, lenses and films. A camera preset can remember its usual lens, so choosing the camera fills the lens in if it is empty; a film preset remembers its ISO and format. Fill them in once and every later roll is a couple of clicks.

## Where the card goes

The card makes your pictures **searchable** in the Workbench by film and roll, supplies the film, camera and lens to the **watermark** ([[watermark-module]]), and, if **Write roll card** is on in **Roll Card Export**, writes the details into the EXIF and XMP of every exported file ([[export-metadata]]). A scanned negative would otherwise carry only the day it was scanned.
""", keywords=("roll card", "metadata", "film", "camera", "lens", "dates", "frame number", "exif", "notes", "roll details"), module="Roll", see=("watermark-module", "export-metadata")),

    Lesson("presets-lesson", "roll", "Presets, and copying settings between photos", "Learn what a preset stores and leaves out, how the built-in sets were made, and the quickest ways to give a look to many photos.",
           r"""
Once one frame looks right, the rest of the roll should not take as long. That is what presets, and copy and paste, are for.

## What a preset is

A **preset** is a saved look: the open photo's **tone, colour, film type, sharpening and watermark settings**, stored under a name. It deliberately **leaves out the crop, the rotation and the dust repairs**, because those belong to one particular frame and would be wrong on another. Apply a preset to a different photograph and you recreate the *look*, not the framing.

In the **Presets** panel, **My Presets** are the ones you made, and **Built-in Presets** come with EFAS and are read-only (copy one to My Presets to change it). Put a slash in a name to make a folder: `B&W/Number 1` is *Number 1* inside *B&W*, shown as a tree.

With a long list, use the **search box** above it. It keeps only the presets that have every word you type in their folder, name or, for the built-in ones, description, so `portra` finds the Portra stocks and the presets whose description mentions Portra, and `warm lab` finds the built-ins whose description has both words. The folders the matches are in open by themselves. `Esc` clears the box, and `Enter` or the Down arrow selects the first one found. If the list you are looking at has no match, the line under the box says how many the other list has. Apply a preset by double-clicking it, or select it and press **Apply**. **Hover preview** lets you rest the mouse on a preset to see it on the picture before you apply it; move away and the photo goes back (Settings > General can turn it off).

## The built-in sets

The built-in sets come in groups: **Scanners (EFAS Original)** (Frontier 100, Crystal 100, Pakon, Noritsu), **Scanners (DarkSlide)**, **Film Stocks (DarkSlide)** (78 film profiles by maker) and **Film Stocks** (Cinestill, Fuji Superia, Kodak Gold, Portra and more). They are EFAS's own **approximations** of the tone, saturation and warmth of those looks, built from the Lab Look, tone curve and colour tools, not measurements of the real thing ([[lab-look-module]]). They are best treated as good starting points to adjust.

## Module presets

Individual modules can keep **their own presets** too, saved sets of just that module's sliders (see [[modules-basics]]). A module preset is what you want when you like one tool's setting but not the whole look.

## Copy and paste

`Ctrl+Shift+C` copies the open photo's settings and `Ctrl+Shift+V` pastes them onto another. In the Workbench you can paste onto **many selected photos at once**, which is the quickest way to give a whole roll the same look: perfect one frame, copy it, select the rest and paste. Copy and paste carry the same things a preset does, and leave the crop, rotation and repairs alone.

TIP: Even after pasting, each frame deserves a glance. Exposure varies from frame to frame, so the paste is a good starting point, not the finish.
""", keywords=("preset", "look", "copy", "paste", "batch", "film stock", "apply", "roll", "hover preview", "built-in", "darkslide"), module="Presets", see=("order-of-operations", "versions-lesson")),

    Lesson("versions-lesson", "roll", "Virtual copies (versions)", "Understand how one scan can hold several complete edits, with no second file.",
           r"""
Sometimes one frame deserves two treatments: a warm colour version and a black-and-white one, a tight crop and a wide one. Copying the file would waste space and break the link between the copies; EFAS instead lets one scan hold several **versions**, called **virtual copies**.

## How it works

A virtual copy is **another complete edit of the same photograph, with no second file**. The scan stays where it is, once. EFAS simply keeps more than one saved edit for it: the one you are working on, and the others. **Make Virtual Copy** (in the **Versions** panel, or in the Workbench's Selection panel) *starts from the edit you have now* and switches to the new copy, so the version you were on stays exactly as it was.

## Using versions

Double-click a version in the **Versions** panel (or press **Switch**) to edit it. The Workbench marks a photo that has copies with **x2** (or x3 and so on), and an export preset can include the versions, adding the copy's name to its file name so the files do not collide.

Anything that describes the *photograph* rather than the *edit* is shared by all its versions: **ratings, flags and tags** belong to the photo, so they are the same whichever version you are looking at.

NOTE: A **snapshot** is a memory of one edit that you return to; a virtual copy is a second edit that exists **alongside**. See [[snapshots-lesson]] for the difference.
""", keywords=("virtual copy", "version", "duplicate", "variant", "alternative", "two edits"), module="Versions", see=("snapshots-lesson", "exporting")),

    Lesson("tags-and-collections", "roll", "Tags and smart collections", "Learn how nested tags and saved searches turn a big library into something you can ask questions of.",
           r"""
A library of thousands of photographs is only as useful as your ability to find the one you want. **Tags** and **smart collections** are the two tools for that.

## Tags

A **tag** is a keyword you attach to a photograph: `family`, `holiday`, `Paris`. Tags **nest**: put a `/` between levels (`People/Family`) and searching for `People` finds everything inside it as well. You can add tags in the **Tags** module (the Roll Card tab), in the **Tagging** panel, or with the **quick tag bar**: press `T` anywhere, type a few letters and press Enter to add the best match. The drop-down under the box lists every tag you have made, so you pick rather than type, which keeps spelling consistent.

The **Tagging** panel works like darktable's: the top list is the tags on the photo (or in the Workbench, on the selected photos, with how many have each); the dictionary below is every tag that exists, which you filter by typing. A check mark is a tag on all of the photos, a dash is on some. **Suggest** lists tags that usually go with the ones attached; right-click a tag to rename it, change its path, delete it, or see its photos. **Import** and **Export** read and write a Lightroom keyword file.

Tags are saved with the photo and in its **.xmp sidecar**, where Lightroom and darktable read them as keywords. In the Workbench you search them with `tag:family`, and exported JPEGs carry them as Windows tags.

## Smart collections

A **smart collection** is a *saved search*: your search words together with the Collection, Date, Rating and Sort settings, stored under a name. It is **not a list of photos**. Each time you pick it, it re-runs on the whole library, so a photograph that fits the search appears in it automatically, including ones you add next year. **Save Current** stores what the panel shows now; to replace a collection, choose it and Save Current again with the same name.

Useful examples: `flag:keeper edited:no` (keepers you have not worked on), `film:portra rating:>=4` (your best Portra frames), `error:scratch` (frames to rescan or repair).
""", keywords=("tag", "keyword", "collection", "smart collection", "search", "organise", "xmp", "lightroom", "tagging"), module="Tags", see=("workbench-lesson",)),

    Lesson("hotstack-lesson", "roll", "Hotstack: shooting tethered", "Understand how a watched folder shows each photo as it arrives, how a retake replaces a frame, and how a finished session is filed.",
           r"""
**Tethered shooting** means the camera is connected to the computer, and you take the picture *from the computer*. Canon's free **EOS Utility** does this over USB or Wi-Fi, and it saves each picture straight into a folder on the computer as you shoot. EFAS cannot control the camera, but it can **watch that folder**, and that is what a **hotstack** is.

## Marking a hotstack

Right-click the folder in a **Library** list (in the editor or the Workbench) and choose **Mark as Hotstack**. Its icon and name turn **red**, the choice is saved, and the folder is watched from then on, every time the editor is open. Right-click it again to **Remove Hotstack Mark**. Any folder can be marked, more than one can be, and the folders inside a hotstack (EOS Utility makes a sub-folder for each day) are watched too.

## What happens to each photo

EFAS checks the folder a few times a second. A new photograph is only reported once its file has **stopped growing**, so a large RAW file coming over Wi-Fi is never opened half-written; that usually means about two seconds after the shot. The photo is read into the library and selected in the Workbench. With **Show Each New Photo in the Editor** on (the default, in the menu of the flame button), it is opened in the editor with the negative already converted, so you can check **focus** (peaking: `Ctrl+Shift+F`), **exposure** (the histogram) and the **edges** before you advance the film. Photographs already in the folder when you mark it are loaded into the Workbench but are not 'new'.

## Retaking a frame

If a frame came out wrong, select it, open the flame button's menu in the top bar and choose **Retake This Photo**. Shoot it again, and the next photograph to arrive **takes the old one's name and place**. The old photo is **set aside, not deleted**: it goes into a `Retakes` folder beside where it was, with its sidecars, and is taken off the Workbench (bring it back from Removed Photos). The retake starts from the old photo's edits, so a roll that is set up is not set up again, but its rating and flag are cleared, because they judged the old photograph.

## Finishing the session

Every photo that arrives in a hotstack is part of the **session**, until you finish it. When you are done shooting, go to the hotstack folder (browse it in the Library, select one of its photos, or open one in the editor) and press **Finish Session (n)**. EFAS moves the session's photos into a folder named for the day (`DD-MM-YYYY`, the same format the Export panel uses) inside the hotstack, with **everything that belongs to them going too**: edits, ratings, flags, tags, and the folder's flat field and Roll Card. Nothing is deleted or overwritten, and the session is remembered if you close the editor, so you can finish it tomorrow.
""", keywords=("hotstack", "tether", "eos utility", "retake", "finish session", "live", "watch folder", "dated folder", "tethered"), see=("scanning-tethered", "recipe-tether-session")),

    Lesson("slideshow-lesson", "roll", "Slideshows", "Learn how the slideshow shows your edited photos, with music, and how to turn it into a video.",
           r"""
The **Slideshow** (the first of the view buttons) plays photographs full screen. What makes it more than a viewer is that it shows each photograph **with its saved edits**, converted and finished as you left it, not as the raw scan.

## What it plays

You choose the source: the photos the **Workbench is showing** (so its search and filters apply), the ones you have **selected** in it, or the **editor's open folder**. Each is made at the size your screen needs on a background thread, with the next few made ahead, so the show never stalls.

## The controls

Choose the **seconds per photo** (1 to 120), a **cut or a crossfade**, **shuffle**, **loop**, and **captions** (file name, film, roll and day). A **progress bar** along the bottom fills as a photo's time runs out and holds when you pause. **Choose photos...** opens a grid of thumbnails with ticks, with Select all, none and Invert, to leave photographs out; `X` leaves out the one on screen. **Start over** (or `Home`) goes back to the first photograph and the start of the music. `Space` plays and pauses, the arrow keys step, `F` or a double-click goes full screen, and `C` toggles the captions.

## Music and video

Music plays **looped**, at a volume you set: three built-in pieces, composed inside EFAS from sine waves, plucked strings and an electric-piano voice, so there is nothing to license, or your own **.wav and .mp3** files, which **Add music...** copies into EFAS's folder. **Export video...** turns the show into an **MP4**, at a size from 720p to 4K and 24 to 30 frames a second, with crossfades, captions burned in and the music looped to the length of the video and faded out over the last two seconds. With **ffmpeg** installed it is H.264 video with AAC sound; without it, a silent MPEG-4 file.
""", keywords=("slideshow", "music", "video", "mp4", "present", "show", "export video", "full screen"), see=("exporting",)),

    Lesson("whole-roll-tools", "roll", "Tools that act on a whole roll", "Understand which measurements belong to a folder, and the tools that apply one fix to every frame.",
           r"""
Some things about a roll are true of every frame, and EFAS has tools that take advantage of that by measuring once and applying to all.

## Shared measurements

The **film base** is the same film on every frame, so **Find Film Base for the Whole Roll** reads the clear border of several frames and combines them into one base, which steadies the colour from frame to frame ([[sample-film-base]]). The **flat field** is the same light in every frame, so a reference, or **Auto (Roll)**, is saved for the folder and used for each ([[flat-field-module]]). Both are saved with the **folder**, which is why a folder per roll matters.

## Whole-roll actions

**Crop Roll** (in the filmstrip) crops every frame, optionally to the same size, each centred on where its own border was found. **Reset Crops** takes the crops off. Because these change many photographs, they have a dedicated **undo** in the filmstrip.

**File > Check Roll Consistency...** reads the RAW scans in the folder and finds frames whose film base reads brighter, darker or tinted compared with the rest, meaning the light, the exposure or the white balance changed during the scan. Each is listed with how far it differs (in stops) and why. Nothing is changed; its dialog can then offer to **Even Out Roll**, with a confirmation, to bring the frames together.

**File > Merge Scans...** combines an exposure bracket, or red-, green- and blue-lit scans, of one frame into one measured 16-bit scan, for scans where a single exposure cannot hold the whole range (see [[advanced-mode]]).

## One look for the whole roll

For the *look*, rather than the measurements, use copy and paste: perfect one frame and paste its settings onto the others in the Workbench ([[presets-lesson]]).
""", keywords=("roll", "batch", "whole roll", "crop roll", "even out", "consistency", "film base", "undo roll", "merge"), see=("sample-film-base", "flat-field-module", "crop-and-rotate")),

    Lesson("data-safety", "roll", "Backups, and where your data lives", "Know exactly what EFAS stores and where, how it protects it, and what you still need to back up yourself.",
           r"""
EFAS keeps your edits in a small local **database** in its own data folder, and it **never changes your scan files**. Your work therefore lives in two places: your scans, wherever you saved them, and EFAS's data folder. Both need a backup.

## What EFAS does for you

**Automatic backups** of the edit database are made and kept for a number of days; **Settings > Data & backup** sets how many and where. A **health check** at startup compares the live database with the backups, and if the database looks far emptier than a backup, it offers to restore it (what is there now is kept in the backups folder, and the restore takes effect the next time the editor starts). **Export / import all data** in the same page packs everything into one file to move to another computer.

**Sidecar files** (`.xmp`) are written next to each photograph and hold its tags and ratings in a form Lightroom and darktable read, so that information is not locked inside EFAS.

## What stays on your computer

**Nothing is sent anywhere.** EFAS goes online in only two cases: to check for a new version (which you can switch off) and, if you allow it, for the Film Colour Reference. No data about you or your photographs is sent in either case.

## What is up to you

A backup that lives on the same disk as the original is not a backup. Copy your **scans** and EFAS's **data folder** to a second drive, and check now and then that you can read it. The film itself, the only true original, deserves proper storage too ([[film-care]]).
""", keywords=("backup", "data", "safety", "restore", "export", "move", "database", "sidecar", "xmp", "privacy"), see=("settings-guide",)),
]
