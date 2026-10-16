"""The Classroom's last two sections: worked examples that bring the tools together in the way an experienced person thinks about a job, and a reference (shortcuts, glossary, troubleshooting, settings)."""
from .logic import Lesson, Section

SECTIONS = [
    Section("recipes", "Worked examples", "How to think through common jobs, tying the tool guides together: a first roll, a colour cast, uneven light, dust, black and white, slide film and more."),
    Section("reference", "Reference", "Keyboard shortcuts, a glossary, troubleshooting, the settings and the command line."),
]

LESSONS = [
    # ------------------------------------------------------------------ worked examples
    Lesson("recipe-first-roll", "recipes", "Working through your first roll", "Follow the thinking of an experienced editor as they take a folder of scans to finished pictures.",
           r"""
You have a folder of scans of one roll and you want finished pictures. An experienced editor does not start by adjusting sliders; they start by getting oriented, and this is how that goes.

## Look first, then describe

Open the folder ([[opening-photos]]) and **look through the whole roll** before you touch anything. Step through with the arrow keys and flag as you go: `K` for the frames you love, `R` for the ones that failed ([[filmstrip-and-culling]]). That single pass tells you how much work the roll needs and which frames deserve it. While you are in the folder, fill in the **Roll Card**: film, camera, lens and dates ([[roll-card-lesson]]). It takes a minute and everything you export later benefits.

## Start with one good frame

Pick the best frame, or the most typical one, and work on that first, because what you learn on it applies to the rest. Go to the **Convert** tab. Check that the film type is right, then **sample the film base** by clicking a bit of clear film border ([[sample-film-base]]); every photograph in the folder is now measured against the true colour of the film, which is the single biggest step towards consistent colour across the roll.

Then **crop**, a little inside the frame, so the border is out and the conversion measures only the picture ([[crop-and-rotate]], [[metering]]). Straighten if the horizon needs it. At this point the picture is usually already close to right.

## Tone, colour, clean, detail

Look at the histogram ([[histogram-panel]]) and settle the **tone**: Exposure until the middle of the picture is the brightness you want, a touch of Contrast ([[exposure-module]], [[contrast-module]]). Then **colour**: find something that should be neutral, a grey road or a white shirt, and adjust until it is ([[color-module]]). If something is off that the simple controls cannot fix, the other tools are there for it. Then **dust**: let Auto Dust Removal take the specks, and heal what is left by hand ([[dust-auto]]). Last, a little **sharpening** at 100% zoom ([[sharpening-module]]).

## Carry it across

That one frame now encodes most of what the roll needs. Copy its settings (`Ctrl+Shift+C`), select the other keepers in the Workbench and paste ([[presets-lesson]]). Then walk through the roll and adjust what differs from frame to frame: the exposure, the crop, the dust. Judging frames against each other is easier than judging one at a time, so it often pays to do the whole roll once at speed and then go round again for refinement.

## Export

When the keepers look right, export them as a batch ([[exporting]]). The originals are untouched, so you can come back to any frame next year and refine it.
""", keywords=("first roll", "tutorial", "walkthrough", "beginner", "start", "workflow", "step by step", "getting started", "example"), see=("workflow-overview", "recipe-colour-cast")),

    Lesson("recipe-colour-cast", "recipes", "Removing a colour cast", "Work out where a cast comes from, because the right fix depends on the cause.",
           r"""
A **cast** is an unwanted tint over the picture, and the tools that fix it are different depending on *where it comes from*. The skill is in working out the cause first, so you fix it in the right place and do not fight it later.

## Is it the conversion?

A cast that is the same on every frame of a roll usually comes from the conversion, and the first suspect is the **film base**. If it has not been sampled, EFAS is guessing the colour of the film from each picture, and any picture with an unusual colour balance throws the guess off. **Sample the film base** ([[sample-film-base]]) or, for a steadier result across a roll, use **Find Film Base for the Whole Roll**. Next, check the **film type**: a colour negative taken for something else, or the reverse, gives wildly wrong colour ([[film-type-setting]]).

## Is it the light?

A tint that appears on *everything you scan*, from every roll, is your backlight. Tell EFAS about it with **Scanning light...** ([[colour-trim-and-scanning-light]]), or correct it once and for all in a permanent flat field.

## Which way to move?

If it is neither, you have a cast to correct by eye, and the question is *in which direction*. This is the **Ring-Around**'s job (`Shift+F`): it steps the colour balance round the picture in a 5 by 5 mosaic, and the tile where the cast disappears shows you which way to go. Then make the correction with **Temperature and Tint** ([[color-module]]), or the Convert tab's colour trim.

## Where in the picture is it?

A cast that is only in the **shadows** (or only in the highlights), the opposite of the cast in the other end, is **crossover**, and no single colour slider can fix it without disturbing the midtones. Use the Modern conversion's **Red, Green and Blue grade** ([[modern-conversion-controls]]) or the Tone Curve's colour curves ([[tone-curve-module]]). A cast that is only at the **edges** is not a white balance problem at all: see [[recipe-flat-light]].

## The golden rule

Find something that **should** be neutral (a grey road, a white shirt, an overcast sky) and make *that* neutral. Then look at skin tones. If the greys are right and the skin looks odd, the cast is not the problem, and adding more correction will only make things worse.
""", keywords=("colour cast", "color cast", "tint", "green", "blue", "orange", "white balance", "ring around", "fix colour", "wrong colours", "crossover"), see=("colour-basics", "color-module")),

    Lesson("recipe-flat-light", "recipes", "Uneven light: dark corners, bright edges, green edges", "Tell four look-alike edge problems apart, because each has a different cause and a different fix.",
           r"""
The edges and corners of a scan can go wrong in four different ways, and they look similar enough to be confused. Each has a different cause, so each has a different cure, and choosing the right one is the whole skill.

## The corners are darker than the middle, the same on every frame

If the corners fall off smoothly and gradually, and it happens on every frame of the roll in the same way, the cause is **uneven scanning light or lens vignetting**. This is what **Flat Field** is for ([[flat-field-module]]). Give it a reference shot: for colour negatives the best is a scan of clear developed film in the same holder, with the same camera, lens, aperture and light. The correction is saved for the whole folder.

## The edges are brighter, with a bright band along a side

If the edges are *lifted* rather than darkened, and especially if the brightness is worst beside a sprocket hole or the gap between frames, the cause is **edge bleed**: light from the clear border or the holder's gaps spilling into the picture. Flat Field cannot help, because this is local and differs from frame to frame. Use **Edge Bleed** ([[edge-bleed-module]]), and crop to the picture first: Fill holder removes the cause, Bleed repair with Auto strength takes off what has scattered in, and Edge dodge flattens what remains.

## The edges are a different colour, and not the same on every frame

If the edges have a colour cast (green, orange) that varies from frame to frame, and the picture was taken with a flash or under mixed light, the cause is **in the picture itself**: the flash lit the middle strongly and left the edges to the room's own light. Neither of the scan-light tools can see that. Use **Edge Color** ([[edge-color-module]]) with **Auto match the colour**.

## A hard strip of colour along one side

A hard-edged strip is almost always the **film's own clear border** inside the crop. No correction will hide it properly. Crop it off.

## Prevent it first

All of these are far easier prevented than cured. Mask off the light, keep the film flat, and shoot in a dim room ([[scanning-flat-and-clean]]). And remember what **Flat Field** cannot do: it corrects the *scanner's* light, so a difference that is in the photograph itself is not in its reference and is left alone.
""", keywords=("edges", "corners", "dark corners", "vignetting", "green edges", "bright edges", "flat field", "edge bleed", "edge color", "uneven"), see=("flat-field-module", "edge-bleed-module", "edge-color-module")),

    Lesson("recipe-dust", "recipes", "Cleaning a dusty scan", "Decide how much to automate and how much to do by hand, and in what order.",
           r"""
A dusty scan can be cleaned in a few minutes, or in an hour, and the difference is mostly in the order you do things and in how much you leave to the automatic tools.

## Prepare the picture

**Crop first.** Repair works on the picture you will keep, so there is no point repairing marks you are about to crop away. Zoom to **100%**, because dust is invisible at any smaller size and every judgement you make about it must be made at full size.

## Let the automatic tools take most of it

Turn on **Show Detections** in the Dust & Scratches module: green marks are specks, magenta marks are hairs. Adjust the **Threshold** until the real dust is marked and the grain is not: lower it if dust is missed, raise it if fine detail is being marked ([[dust-auto]]). Then switch on **Auto Dust Removal**. If the scan has many fine scratches or hairs lying across textured areas, try **AI Dust Detection** as well ([[ai-dust]]): it understands what a defect looks like and may find what the threshold cannot.

## Finish by hand

Then walk across the picture and look for what is left. A few remaining specks are best healed with **Smart Heal** (one click each); a scratch is better traced with the **Scratch Tool** than painted; a mark over real detail, like a face, is a job for **Clone** ([[dust-manual]]). If the automatic repair has damaged something real (a star in a night sky, a catchlight in an eye), use **Delete Repair** on it and it is left alone.

## Mark what cannot be fixed

Some faults are beyond repair: a deep scratch that took the picture with it, a light leak. Mark them with **Error marking** so you can find those frames later and decide whether to rescan ([[error-marking]]).

## Prevent first

A minute with a blower before scanning saves ten minutes of retouching. See [[film-care]] and [[scanning-flat-and-clean]].
""", keywords=("dust", "scratches", "hairs", "clean", "retouch", "spots", "specks", "remove"), see=("dust-and-scratches-origins", "dust-auto")),

    Lesson("recipe-bw", "recipes", "Converting black-and-white film", "Understand what is different about a black-and-white negative, and where its character comes from.",
           r"""
A black-and-white negative has no colour to balance, so you might expect it to be simpler to convert. In one way it is: there is no orange base to remove, no crosstalk between dye layers, and no colour cast to hunt. But the picture is *all* tone, so what matters most is the tone.

Start in the **Negative** module by setting **Film type** to **Black & white negative** ([[film-type-setting]]). That does two things: it applies the reversal, and it turns the scan strictly monochrome, replacing the three channels with the picture's brightness, so any tint from the film base or the scanning light disappears. If the scan has a clear border, **sample the film base** anyway: black-and-white film's base is pale grey or clear, but sampling still tells the conversion where the black is. And **crop** before you judge, so the border does not set the metering ([[metering]]).

## Where the character comes from

With no colour, the picture's look is made of **tone** and **grain**. Take your time on the Tone tab. Set the overall brightness with **Exposure** and the punch with **Contrast**, then shape the picture with a gentle S in the **Tone Curve** and open the ends with **Shadows & Highlights** ([[tone-curve-module]]). A lifted black in the curve gives a soft, faded look; a deep black and bright highlight gives a graphic one. **Print Response** gives the film-like roll-off ([[print-response-module]]).

To add feeling, **Color Toning** can put a subtle warm or cool tint in the highlights or shadows at a low strength, in the tradition of toned darkroom prints ([[color-toning-module]]).

**Grain** is a big part of black-and-white's appeal, and the Detail tools affect it: **Sharpening** crisps it, **Local Contrast** exaggerates it. Use them with a light hand, and judge at 100%.

NOTE: The histogram's Color graph is greyed out for a black-and-white negative, because there is only brightness. Use the Exposure graph.
""", keywords=("black and white", "b&w", "monochrome", "grayscale", "bw", "hp5", "tri-x", "ilford"), see=("film-types", "tone-curve-module")),

    Lesson("recipe-slide", "recipes", "Working with slide film", "Understand what is different about a transparency, which is already a positive.",
           r"""
A slide (E-6) is a **positive**: it already looks like the picture when held to the light. EFAS therefore does not reverse it, and the orange mask is not there to remove. Most of the Convert tab's machinery does not apply, and the picture is edited like any ordinary photograph.

Open the scan and check that **Film type** says **Slide film (E6)**. If EFAS guessed that it was a negative, set the type yourself ([[film-type-setting]]).

## The scan is critical

Slides hold a **narrow range** of brightness compared with a negative: they have far less latitude, and a slide scanned with the highlights clipped has lost them for good. Exposing the scan so that the brightest highlight *just* does not clip is the one decision that matters ([[scanning-exposure]]). The deep shadows of a slide are also very dense, so a slide benefits from a good, clean light.

## The edit

After that the work is the same as for any picture: crop and straighten, tone, colour, dust and detail. Slide colours are already strong, so go easily on saturation: **Vibrance** in the Color Mixer is safer than Saturation, because it leaves the already-vivid colours alone ([[color-mixer-module]]).

NOTE: A slide's mount edge and a slide's sprocket-hole border are black or clear, not orange, and there is no film base colour to sample.
""", keywords=("slide", "e6", "transparency", "positive", "velvia", "ektachrome", "reversal"), see=("film-types", "scanning-exposure")),

    Lesson("recipe-flat-scan", "recipes", "A flat, dull scan", "Work out why a scan is flat, and bring it to life in the order that costs least.",
           r"""
A flat scan has a histogram squeezed into the middle: nothing near black, nothing near white, everything a hazy grey. The remedies are many, and the way to choose is to work from the **cause** towards the finish, so you use as little processing as you can.

## Is it the conversion?

First, check the conversion's range. In the **Modern** method, raise **Grade** a little so the picture's own range fills the paper's; in the **Original** method, use the white and black points ([[modern-conversion-controls]], [[white-black-points]]). A picture that is flat because the conversion did not spread it properly is cured here, at the source, without touching anything later in the chain.

## Then the tone

If the range is right but the picture still lacks punch, add a little **Contrast** ([[contrast-module]]), then a gentle S in the **Tone Curve**, which lets you put the extra contrast exactly where you want it ([[tone-curve-module]]).

## Then local texture

If skies and flat areas lack texture, a touch of **Local Contrast** brings it out without clipping the highlights ([[local-contrast-module]]). Add just a little: it is easy to overdo.

## Then colour

A flat scan is often pale as well. A little **Vibrance** adds colour without harming skin ([[color-mixer-module]]).

## Watch the ends

Keep an eye on the corner triangles of the histogram: stop before they climb. If the cause is that the negative was under-exposed, or the scan was, no editing will give back what was never recorded; see [[film-latitude]] and [[scanning-exposure]].
""", keywords=("flat", "dull", "low contrast", "hazy", "pale", "muddy", "washed out", "no punch"), see=("contrast-module", "tone-curve-module")),

    Lesson("recipe-batch", "recipes", "One look across a whole roll", "Learn the efficient way to bring a roll to a consistent finish.",
           r"""
The efficient way to finish a roll is to do the hard thinking once, on one frame, and spread what you learn. The frames of one roll share their film, their light and often their subject, so most of the work *is* shared.

Choose a typical frame and make it look right: the conversion, the tone, the colour and the sharpening. When you are happy, **copy its settings** (`Ctrl+Shift+C`). Cropping, rotation and dust repairs are not copied, because they belong to that one frame. Then go to the **Workbench** (`W`), select the other frames (click the first, `Shift`-click the last) and **Paste Settings to Selected**.

That gives every frame the same *look*, and your remaining work is the part that genuinely differs from frame to frame: the **exposure** (frames vary), the **crop**, and the **dust**. Open each frame in turn and adjust those. Measurements that belong to the whole folder (the film base, the flat field) already apply to every frame without being pasted ([[whole-roll-tools]]).

If you want the same look on *many rolls*, save it as a **preset** instead of pasting between photos, and apply the preset to each new roll ([[presets-lesson]]).
""", keywords=("batch", "copy settings", "paste", "sync", "roll", "same look", "consistent", "whole roll"), see=("presets-lesson", "whole-roll-tools")),

    Lesson("recipe-tether-session", "recipes", "A tethered scanning session", "Understand how a whole tethered session runs, from the first frame to the filed roll.",
           r"""
A tethered session lets you scan a roll without ever touching the camera, and see each frame as it is taken. Here is how it unfolds.

## Setting up

First the physical rig ([[scanning-setup]]): camera square to the film, an even masked light, the camera's exposure and focus set and *left alone* for the whole roll ([[scanning-exposure]]). Connect the camera to the computer (a USB cable is best) and open Canon's **EOS Utility**. In its preferences, set the **Destination Folder** so it saves to the computer, and make a folder for this roll. In EFAS, find that folder in the **Library** list (add it with **+** if it is not there) and **right-click it and choose Mark as Hotstack**. Its icon and name turn red, and it is now being watched ([[hotstack-lesson]]).

## Shooting

Take the first frame from EOS Utility. About two seconds after the file is complete it appears in EFAS, converted. This first frame is a calibration: check the **focus** by zooming in (and turning on focus peaking with `Ctrl+Shift+F`), the **exposure** against the histogram, and the **edges** for stray light. If all is well, **sample the film base** on this frame's border: the rest of the roll is calibrated to it.

Advance the film and take the next. Each frame lands, converts and opens. If one is wrong, select it, open the flame button's menu and choose **Retake This Photo**, then shoot it again; the new frame takes the old one's name and place, and the bad one is kept aside in a `Retakes` folder.

## Filing

When the roll is done, go to the hotstack folder and press **Finish Session**. The session's frames are moved into a folder named for the day, with their edits and the folder's measurements, and the hotstack stays marked, ready for the next roll.

Then edit as in [[recipe-first-roll]]. The calibration you did on the first frame has already done much of the work.
""", keywords=("tether", "hotstack", "eos utility", "session", "retake", "live", "canon", "workflow"), see=("scanning-tethered", "hotstack-lesson")),

    # ------------------------------------------------------------------ reference
    Lesson("shortcuts", "reference", "Keyboard shortcuts", "Look up every shortcut, exactly as it is set up on this computer.",
           r"""
These are the shortcuts as they are bound now. You can change any of them in **Settings > Keybinds**, and this table follows. Press `?` or `F1` anywhere in the editor for the same list.

@shortcuts

NOTE: Some shortcuts only work in the editor, some in the Workbench (the rating and flag keys act on the selection there).
""", keywords=("keyboard", "shortcuts", "keys", "hotkeys", "keybinds", "ctrl", "bindings"), level="Beginner", see=("how-this-guide-works",)),

    Lesson("glossary", "reference", "Glossary", "Look up a word you have met in EFAS or in photography.",
           r"""
- **Aperture**: the adjustable opening in a lens, written as an f-number. [[aperture-and-depth-of-field]]
- **Base (film base)**: the clear, unexposed film. Orange in colour negatives. [[sample-film-base]]
- **Bit depth**: how many levels each colour channel holds: 8-bit has 256, 16-bit has 65,536. [[raw-and-bit-depth]]
- **Bleed**: light spilling into the picture's edges from the film border, holder gaps or sprocket holes. [[edge-bleed-module]]
- **Blown highlights**: bright areas clipped to pure white with no detail. [[clipping]]
- **C-41**: the chemistry that processes colour negative film. [[film-types]]
- **CLAHE**: contrast-limited adaptive histogram equalization: the technique behind Local Contrast. [[local-contrast-module]]
- **Clipping**: a tone that has hit pure black or pure white and lost detail. [[clipping]]
- **Colour cast**: an unwanted tint over the whole picture. [[recipe-colour-cast]]
- **Colour temperature**: the colour of light, in kelvin: low is warm, high is cool. [[colour-temperature-and-white-balance]]
- **Crosstalk**: the way a film's dye layers also absorb in each other's colours. [[modern-conversion-controls]]
- **Density (D)**: how much light film stops, as a logarithm: 0 passes everything, 1 a tenth, 2 a hundredth. [[convert-overview]]
- **Dmin / Dmax**: the density of the film base / the densest part of the picture.
- **Dynamic range**: the span from the darkest to the brightest tone that holds detail. [[dynamic-range-contrast]]
- **E-6**: the chemistry that processes slide film. [[film-types]]
- **EV (exposure value) / stop**: a doubling or halving of light. [[stops-and-ev]]
- **Flat field**: a correction for uneven backlight, from a reference shot. [[flat-field-module]]
- **Gain**: a multiplier. Flat Field and Shadows & Highlights both work by gain.
- **Grade**: the contrast of the 'paper' in the Modern conversion. [[modern-conversion-controls]]
- **Grain**: the texture of silver or dye in film. [[film-speed-and-grain]]
- **Halo**: a bright or dark rim next to an edge, caused by too much sharpening or local contrast. [[sharpening-module]]
- **Histogram**: a graph of how many pixels have each brightness. [[histogram-basics]]
- **Hotstack**: a folder you mark to be watched for photos as they arrive. [[hotstack-lesson]]
- **ISO**: the sensitivity of a sensor or film. [[iso-and-noise]]
- **Keystone**: converging lines caused by a tilted camera. [[distortion-and-keystone]]
- **Latitude**: how much over- or under-exposure a film forgives. [[film-latitude]]
- **Lookup table (LUT)**: a table that maps each input level to an output level; how EFAS makes tone changes instant.
- **Metering**: measuring the picture to decide what counts as black and white. [[metering]]
- **Negative / positive**: reversed in brightness (and colour) / as it should look.
- **Noise**: random speckle from a digital sensor at high ISO. [[iso-and-noise]]
- **OKLCH**: a colour model where equal steps look equal; the Color Mixer works in it. [[color-mixer-module]]
- **Percentile**: the value below which a given share of the pixels fall; how the conversion finds the picture's range. [[metering]]
- **Pipeline**: the chain of modules a picture goes through. [[order-of-operations]]
- **RAW**: the sensor's own, barely processed data. [[raw-and-bit-depth]]
- **Rebate**: the unexposed border round a frame. [[film-formats]]
- **Shoulder / toe**: where highlights roll off into white / shadows fade into black. [[print-response-module]]
- **Sidecar (.xmp)**: a small file beside a photo that holds its tags and ratings. [[data-safety]]
- **Snapshot**: a saved, named copy of one photo's edit. [[snapshots-lesson]]
- **Tether**: shooting with the camera connected to the computer. [[scanning-tethered]]
- **TIFF**: a lossless picture format that can be 16-bit. [[export-formats]]
- **Vibrance**: a colour boost that favours muted colours and spares skin. [[color-mixer-module]]
- **Vignette**: darkening toward the corners. [[finishing-module]]
- **White balance**: the correction that makes white things white under any light. [[colour-temperature-and-white-balance]]
""", keywords=("glossary", "terms", "definitions", "dictionary", "meaning", "what is", "jargon"), see=("how-this-guide-works",)),

    Lesson("troubleshooting", "reference", "Troubleshooting: when something looks wrong", "Match a symptom to its likely cause and the guide that explains the fix.",
           r"""
## The colours look wrong

A strong cast on every frame points at the conversion: sample the film base, check the film type, then use the Ring-Around. See [[recipe-colour-cast]].

## Dark corners, bright edges or green edges

Flat field, edge bleed and edge colour each fix a different cause, and it matters which you pick: [[recipe-flat-light]].

## The picture is dark, flat or washed out

Look at the histogram, the scan quality verdict and the conversion's Grade. See [[recipe-flat-scan]] and [[scan-quality-check]].

## Banding in skies or gradients

The scan lost levels. Scan in RAW, and export a 16-bit TIFF. An 8-bit JPEG cannot hold a strongly stretched negative smoothly. See [[raw-and-bit-depth]].

## Dust everywhere

Clean the film before you scan, then see [[recipe-dust]].

## Sharpening looks crunchy, or the grain is too strong

Lower Amount and Radius, raise Masking, and judge at 100%. See [[sharpening-module]].

## Editing feels slow on big scans

Work on the fast preview and switch **HQ** on (`Ctrl+H`) only to check. Make sure **Settings > Graphics card** is on: the colour work then runs on your graphics card. Local Contrast, Denoise and Sharpening still run on the processor, so use them last.

## A photo is missing in the Workbench

Press **Refresh**, check the folder is under a Library root, clear the search and filters, and look in **Removed Photos...**. See [[workbench-lesson]].

## My edits are gone after I moved or renamed a file

EFAS keeps a photo's edits against **where the file is**. Moving or renaming a file in Explorer breaks that link, and the photo opens as a fresh scan. Where you can, move photos inside EFAS: **Finish Session** moves them *with* their edits. The backups (Settings > Data & backup) still hold the old edits.

## The export does not look like the screen

Switch **HQ** on to see the full-resolution picture the export is made from, and remember that exports are saved in sRGB and that different viewers show colour differently.

## Photos from my camera do not appear in the hotstack

Check the folder is the one the camera software really saves into, and that it is marked. See [[hotstack-lesson]].

## Something else

**Info > Report a Problem** writes a report you can read, save and attach to a GitHub issue. Nothing is sent automatically.
""", keywords=("troubleshooting", "problem", "fix", "wrong", "slow", "error", "help", "not working", "missing", "banding"), level="Beginner", see=("recipe-colour-cast", "recipe-flat-light")),

    Lesson("settings-guide", "reference", "The Settings, page by page", "Know what each page of Settings controls, and which options are worth changing.",
           r"""
Open **Settings > Preferences**. The pages are listed down the left.

**General** holds the habits of the program: whether flagging a frame moves on to the next, whether it checks for a new version, whether it checks the quality of each RAW scan as you open it, whether the Workbench shows the Library list, whether HQ is on for every photo, whether modules fold shut when you change tabs, whether presets preview under the mouse, the Film Colour Reference's permission to go online, hover-to-open modules, and colour-coded modules. Turn off the scan-quality check and hover preview on a slow computer.

**Themes** is for the look of the program. **Modern** is the default; Default, Midnight, Graphite, Darkroom and High contrast are alternatives. You can choose an **accent colour** and the **text size**, or import your own theme as a CSS file. Restyling the whole program takes a few seconds, so it happens only when you press Apply.

**Image decoding** is how RAW files are developed into a picture: the **demosaic method** (how the two colours each sensor pixel did not record are filled in: AHD is the usual all-rounder, DCB gives cleaner edges and DHT finer detail), whether to **auto-brighten**, and an option to **invert negatives before the camera's colour matrix**, which can help the colour of difficult negatives. RAW files and 16-bit scans are read at 16 bits. The open photo reopens when you save a change here.

**Graphics card** lets EFAS use your graphics card, through Vulkan, for the heaviest colour work, and sets a **limit** on how much of the card's time it may take. The page names the card. At 100% the card works flat out; lower it and the card rests between short bursts, which keeps it cooler and quieter and leaves time for the screen and other programs.

**Keybinds** lets you change any shortcut: see [[shortcuts]]. **Data & backup** is automatic backups, how many to keep, where, and exporting or importing all your data: see [[data-safety]]. **Storage** shows how much room the thumbnail cache and the AI dust analysis take, and has a button to clear each; both are made again as needed, and your edits, ratings and presets are not touched. **Plugins** switches plugins on and off, and can make a new one.
""", keywords=("settings", "preferences", "options", "themes", "decoding", "gpu", "graphics card", "keybinds", "backup", "storage", "plugins", "demosaic"), see=("data-safety", "shortcuts")),

    Lesson("advanced-mode", "reference", "Advanced mode: the scientific panels", "Know what the extra measurement tools are for, and that you can ignore them entirely.",
           r"""
EFAS has an **Advanced mode** (a button in the Negative module) that adds scientific measurement panels. You can use EFAS for years without it. It is for people who want *numbers*: how dense is this film, how well exposed is this scan, what does this film's response curve actually look like.

The **Density** and **Density Histogram** panels show the optical density of the film base (Dmin) and of the densest part of the picture (Dmax), measured from the **linear RAW data**, not from the picture you see on screen. The **Sensitometry (H&D)** panel plots a film's characteristic curve, but only from a film profile: a photograph records densities, not the exposures behind them, so EFAS cannot draw this curve from an ordinary picture. **Film characterization** lets you calibrate your camera against a step tablet, fit a film's curves from a strip exposed through one, and save the result as a film profile. **Calibration and Diagnostics** explains exactly how every number was obtained and what could make it unreliable.

Two file operations belong here too: **File > Merge Scans** combines an exposure bracket, or red-, green- and blue-lit scans, into one measured 16-bit scan, for frames a single exposure cannot hold; and the Export panel's **flat, linear-light and density** outputs write the conversion alone as 16-bit TIFFs for other software.

NOTE: Nothing here changes how an existing photo is converted unless you choose it. For the film and paper conversion used every day, see [[inversion-method]].
""", keywords=("advanced", "scientific", "density", "h&d", "sensitometry", "calibration", "film profile", "merge", "dmin", "dmax"), level="Advanced", see=("scan-quality-check", "export-formats")),

    Lesson("command-line", "reference", "The command line", "Convert, list presets and check a roll without opening the window.",
           r"""
EFAS can run from a terminal, using the editor's own data folder, so the presets and edits it uses are the ones you have made in the window:

```
python -m photoeditor convert | presets | info | check-roll | merge
```

It is meant for batch work and automation: converting a whole folder overnight, say, or checking a roll's scan consistency from a script. Run a command with `--help` to see what it takes.

NOTE: You do not need this to use EFAS. Everything the command line does is available in the window.
""", keywords=("command line", "cli", "terminal", "batch", "script", "automation"), level="Advanced", see=("whole-roll-tools",)),
]
