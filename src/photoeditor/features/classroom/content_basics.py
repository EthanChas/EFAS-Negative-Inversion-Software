"""The Classroom's first four sections: start here, the basics of photography, how film works, and scanning film with a camera."""
from .logic import Lesson, Section

SECTIONS = [
    Section("start", "Start here", "What EFAS does, how this guide works, and the whole job at a glance."),
    Section("photo", "Photography basics", "Light, exposure, colour and sharpness: the ideas behind every slider, explained from nothing."),
    Section("film", "How film works", "Why a negative looks the way it does, and what to expect from different films."),
    Section("scan", "Scanning your film", "Photographing a negative with a camera so that EFAS has the best possible scan to work from."),
]

LESSONS = [
    # ------------------------------------------------------------------ start here
    Lesson("what-is-efas", "start", "What EFAS does", "Know what the program is for, and what it never does to your files.",
           r"""
EFAS turns **film negatives** into pictures you can look at, share and print. You photograph or scan a negative, open the scan in EFAS, and EFAS flips it from a negative into a positive, sets the colour and tone, cleans off the dust and exports a finished picture.

## What happens to your files

Nothing is ever written over your originals. Every change you make is a *recipe* saved next to the photo in EFAS's own database: the original scan is left alone, and the finished picture is made fresh each time you look at it or export it. That means you can undo anything, come back next year and carry on, and try three different looks of the same frame.

## Who it is for

Anyone with film and a camera or scanner. You do not need to know anything about editing software. If photography itself is new to you, start with the **Photography basics** section: it explains what exposure, contrast and white balance mean, so the sliders make sense.

TIP: The little **?** on every module's header explains that module in a sentence or two. This Classroom goes further: why the tool exists, what each slider really does, and when to reach for it.
""", keywords=("introduction", "overview", "beginner", "new", "about", "non-destructive"), see=("how-this-guide-works", "workflow-overview")),

    Lesson("how-this-guide-works", "start", "How the Classroom works", "Learn how the guides are organised, how to search them, and what the Show me button does.",
           r"""
The Classroom is a built-in manual, and a fuller one than the little **?** on each module's header. The **?** gives a sentence or two to remind you what a control is. The guides here explain the *idea* behind a tool, what it really does to your picture, what each of its controls means, and when to reach for it.

## Finding your way

On the left are the guides, grouped into sections in the order a newcomer needs them: the basics of photography first, then how film works and how to scan it, then the program, and then each tab of the editor in the order a picture is worked on, ending with whole-roll tools, worked examples and a reference. You can read straight through from the top, or pick any guide that interests you; each one stands on its own and links to the others it relies on.

The **search box** above the list looks through every guide. Type any word (`dust`, `grain`, `tint`, `flash`, `flat field`) and the list becomes the guides that mention it, best match first: a title that has your words ranks above a guide that only mentions them in passing. Every word you type has to be in the guide, so adding a word narrows the result. Pressing `Esc` clears the search, and `Enter` opens the first result.

## Moving about

**Previous** and **Next** at the bottom of a guide walk through the course in order, and the **Read next** list at the end of a guide, and the links in its text, go to related guides. The guide you were reading is remembered for next time.

## Show me

A guide about one tool has a **Show me** button. It takes you to that tool in the editor (or in the Workbench, for the library tools), opens its tab, opens the module and flashes it, so you can try what you have just read while it is fresh. Come back to the Classroom with its view button and you are where you left off.

TIP: If photography is new to you, read the **Photography basics** section before the tool guides. The tools are far easier to understand once you know what exposure, contrast and white balance are for.
""", keywords=("help", "guide", "search", "navigate", "tutorial", "show me"), see=("workflow-overview",)),

    Lesson("workflow-overview", "start", "The whole job, from film to finished picture", "See the path a roll takes through EFAS, and how the tabs follow it.",
           r"""
A roll of film goes through the same stages every time, and EFAS's tabs follow them in order, so working across the tabs from first to last *is* working through the job.

It starts with the **scan**. Everything else depends on it, because editing can only reveal what the scan captured: a negative photographed on a flat, clean, evenly lit surface at a good exposure gives EFAS a great deal to work with, and a poor one limits everything after. The Scanning section explains how.

Once the scans are in a folder, you **open the roll** and look through it, flagging the frames worth finishing ([[filmstrip-and-culling]]). Then you work on those frames. The **Convert** tab turns the negative into a positive and is where colour accuracy is won or lost; its first job is to know what kind of film it is dealing with and what colour the bare film base is. **Frame & Clean** is next: you crop and straighten so the picture is what you want it to be, and so the conversion measures the picture rather than the border, and you remove dust, hairs and scratches. The **Tone** tab sets how light or dark the picture is and how its tones relate. The **Color** tab balances the colour, then lets you give it a character. **Detail** adds a little noise reduction and sharpening. **Finish** adds a vignette, a border or a watermark if you want them, and then you **export**.

You will not need every step on every photograph. A good scan of a well-exposed negative often needs only the conversion, a crop and an export, and the later tabs are there for the times you want more. The tabs are a map of the possibilities, not a list of obligations.

Because the frames of one roll share so much (the film, the light, the camera), EFAS lets you do the common work once. A film base sampled on one frame can be used for all of them, a flat field covers the whole folder, and one frame's settings can be pasted on the rest ([[whole-roll-tools]]). The usual way of working is therefore to perfect *one* frame, apply what it has taught you to the rest of the roll, and then go through the frames adjusting what differs: exposure, crop, dust.
""", keywords=("workflow", "steps", "process", "order", "tabs", "overview", "roll"), see=("window-tour", "recipe-first-roll")),

    Lesson("window-tour", "start", "A tour of the window", "Name the main parts of the screen so the rest of the guide makes sense.",
           r"""
**The view buttons** (top right) switch between the program's pages: **Slideshow** plays your photos, **Maps** is still to come, **Classroom** is this guide, **Workbench** is the whole-library grid (press `W`), and **Editor** is where you edit one photo (press `D`).

## In the editor

- **The picture** fills the middle. Scroll to zoom, drag to move around, press `Z` to flip between fit-to-window and 100%.
- **The tool rail** (left of the modules) has the tabs: **Convert**, **Frame & Clean**, **Tone**, **Color**, **Detail**, **Finish**, **Roll Card** and **Plugins**. Click one to open its modules.
- **Modules** are the collapsible panels (Exposure, Contrast, Crop & Rotate...). Each has a header with a power light, a reset button and a **?**.
- **The module search box** above the tabs finds a module by name or by what it does.
- **The side panels** show the Library, Presets, History, Snapshots, Versions and Export, and, beside the picture, the **histogram** and its plain-words read-out.
- **The filmstrip** along the bottom shows the other frames of the roll.

TIP: `Tab` hides the side panels to give the picture the whole window, and shows them again. `Ctrl+K` finds any control or action by name.
""", keywords=("interface", "layout", "screen", "views", "ui", "panels", "tabs"), see=("modules-basics", "viewing-tools")),

    # ------------------------------------------------------------------ photography basics
    Lesson("light-and-exposure", "photo", "Light and exposure", "Understand that a photograph is a measurement of light, and what 'exposure' means.",
           r"""
A camera, or a piece of film, is a box that collects light for a moment. **Exposure** is how much light it collected. Too little and the picture is **underexposed**: dark, with the shadows lost in black. Too much and it is **overexposed**: pale, with the bright parts washed out to white.

Three things set the exposure: how wide the lens opening is (*aperture*), how long it stays open (*shutter speed*) and how sensitive the sensor or film is (*ISO*). They are the **exposure triangle**, explained in the next lessons.

## Why it matters when you edit

Editing can adjust a picture's brightness, but it cannot invent detail that was never recorded. A black patch with nothing in it stays black however far you lift it; a white patch with nothing in it stays white. So the rule of thumb is: **get the exposure right when you shoot or scan, and use the editor to refine, not to rescue.**

TRY: Open any photo and drag the **Exposure** module's slider both ways. Notice that dark areas fill in with noise when lifted, and bright areas turn flat white when pushed.
""", keywords=("brightness", "dark", "bright", "underexposed", "overexposed", "light"), see=("exposure-triangle", "stops-and-ev", "histogram-basics")),

    Lesson("exposure-triangle", "photo", "The exposure triangle", "Know the three controls that set a photograph's brightness and how they trade off.",
           r"""
Aperture, shutter speed and ISO all change brightness, but each has a side effect.

- **Aperture** changes how much of the scene is sharp (depth of field). See [[aperture-and-depth-of-field]].
- **Shutter speed** changes how motion looks: blurred or frozen. See [[shutter-speed]].
- **ISO** changes how grainy or noisy the picture is. See [[iso-and-noise]].

To keep the same brightness you trade one for another. Open the aperture by one **stop** (see [[stops-and-ev]]) and you must halve the shutter time, or lower the ISO by one stop, to stay the same brightness.

## For scanning film

When you photograph a negative on a copy stand nothing is moving, so you choose the settings for quality rather than for action: a middle aperture for sharpness, the camera's lowest ISO for the cleanest picture, and whatever shutter speed then gives the right brightness. [[scanning-exposure]] has the details.
""", keywords=("aperture", "shutter", "iso", "triangle", "camera settings"), see=("aperture-and-depth-of-field", "shutter-speed", "iso-and-noise")),

    Lesson("aperture-and-depth-of-field", "photo", "Aperture and depth of field", "Read an f-number and know how it affects sharpness.",
           r"""
The **aperture** is the adjustable opening in a lens. It is written as an **f-number**: f/2, f/2.8, f/4, f/5.6, f/8, f/11, f/16. A *smaller* f-number is a *bigger* opening, so f/2 lets in much more light than f/16.

## Depth of field

The aperture also decides **depth of field**: how much of the scene, front to back, looks sharp. A wide opening (f/1.8) gives a thin slice of sharpness and a soft, blurry background. A narrow opening (f/11) keeps much more in focus.

## The sweet spot

Most lenses are sharpest two or three stops down from wide open, around **f/5.6 to f/8**. Go much narrower (f/22) and a different problem, *diffraction*, softens the whole picture. That is why scanning guides recommend f/8 or so: a flat negative does not need depth, it needs the lens at its sharpest.
""", keywords=("f-stop", "f number", "bokeh", "blur", "lens", "sharp", "diffraction"), see=("exposure-triangle", "focus-and-sharpness")),

    Lesson("shutter-speed", "photo", "Shutter speed", "Understand how shutter time freezes or blurs movement, and why a tripod matters.",
           r"""
**Shutter speed** is how long the camera collects light: 1/1000 s, 1/125 s, 1 s, 30 s. A fast shutter freezes movement; a slow one lets moving things blur.

It also shows up as **camera shake**: if you hold the camera and the shutter is slow, your own hand's tremble blurs the whole picture. A rough rule is to keep the shutter no slower than 1 over the lens's focal length (1/100 s for a 100 mm lens) when handheld.

## For scanning film

A camera on a copy stand or tripod does not shake, so a slow shutter speed is fine, even 1/4 s. Use a remote release, or the camera's 2-second timer, so that pressing the button does not move the camera. A sharp scan starts with a still camera.
""", keywords=("shutter", "motion blur", "camera shake", "tripod", "speed"), see=("exposure-triangle", "scanning-setup")),

    Lesson("iso-and-noise", "photo", "ISO, noise and grain", "Know what ISO does and the difference between noise and film grain.",
           r"""
**ISO** is the sensitivity of the sensor or film. A higher number needs less light, but costs quality: **noise** (colourful speckle on a digital sensor) or **grain** (the texture of silver or dye in film).

- **Digital ISO**: the camera's lowest setting (often ISO 100) gives the cleanest picture. Raise it only if you must.
- **Film ISO** is fixed when you load the film: ISO 100 film is fine-grained and needs lots of light; ISO 800 film is grainier but copes with dim places.

Grain is part of film's character and many people love it. Noise from the *scanning camera* is not part of the film: that you want to avoid, by scanning at the camera's lowest ISO.

NOTE: Film grain can show up as blotchy coloured speckle in a scan. The **Chroma Denoise** module smooths that colour speckle without softening detail. See [[chroma-denoise-module]].
""", keywords=("noise", "grain", "sensitivity", "speckle", "film speed"), see=("film-speed-and-grain", "chroma-denoise-module")),

    Lesson("stops-and-ev", "photo", "Stops and EV", "Understand the 'stop', the unit EFAS's Exposure slider is measured in.",
           r"""
A **stop** is a doubling or halving of light. One stop brighter means twice the light; one stop darker means half. Three stops brighter is eight times the light.

Photographers measure brightness changes in stops because the eye judges brightness roughly the way stops work: the step from 1 to 2 looks about the same as the step from 4 to 8.

The same idea is written **EV** (exposure value). EFAS's **Exposure** slider is in EV: +1.00 doubles the brightness of the picture, -1.00 halves it, and the slider's double-click resets it to 0.

## Handy numbers

- **+/- 0.3 EV** is a gentle nudge: a third of a stop.
- **+/- 1 EV** is clearly brighter or darker.
- **+/- 2 EV** is a rescue, and will show noise or lose highlights.
""", keywords=("ev", "stop", "f-stop", "double", "brightness unit"), module="Exposure", see=("exposure-module",)),

    Lesson("histogram-basics", "photo", "Reading a histogram", "Read the graph that shows how a picture's tones are spread, and what a good one looks like.",
           r"""
A **histogram** is a graph of the picture's brightness. The left edge is black, the right edge is white, and the height at each point shows how many pixels have that brightness.

- A pile of **tall bars on the left** is a dark picture; a pile on the **right** is a bright one.
- A graph that **runs the whole width** has a full range from black to white: usually a rich, contrasty picture.
- A graph **squeezed into the middle** is flat and low-contrast: grey and hazy.
- A graph that is **cut off** at an edge, with a tall bar against the wall, is **clipped**: see [[clipping]].

There is no perfect shape: a snowy scene piles up on the right, a night scene on the left. The histogram tells you what is *there*, so you can tell whether what you see is what you intended.

## In EFAS

The histogram sits by the picture. **Color** shows red, green and blue separately; **Exposure** shows one brightness graph. Hover the picture and the graph marks that pixel's brightness. A line of plain words under it reads the graph out for you: exposure, contrast, range, clipping and colour.
""", keywords=("histogram", "graph", "tones", "levels", "distribution"), see=("clipping", "histogram-panel")),

    Lesson("clipping", "photo", "Clipping: blown highlights and blocked shadows", "Spot clipped tones and understand why they cannot be recovered.",
           r"""
**Clipping** means a tone has hit the end of the scale: pure white or pure black with no detail left. **Blown highlights** are clipped whites (a cloud with no texture). **Blocked shadows** are clipped blacks (a dark coat that is one flat black shape).

Clipped areas have lost their information. Dragging a slider afterwards only turns flat white into flat grey.

## Seeing it in EFAS

Under the histogram, a **triangle on each corner** gives the percentage of the picture that is blocked (left) or blown (right). Click one and EFAS marks those areas on the picture, so you can see exactly where they are.

## What to do about it

- If the clipping is already in the **scan**, it cannot be fixed afterwards: re-scan with an exposure that keeps the whole range. See [[scanning-exposure]].
- If you made it while **editing**, back off the contrast or brightness, or use **Shadows & Highlights** to pull the ends in: [[shadows-highlights-module]].
""", keywords=("blown", "blocked", "highlights", "shadows", "lost detail", "clip", "overexposed"), see=("histogram-basics", "scanning-exposure")),

    Lesson("dynamic-range-contrast", "photo", "Dynamic range and contrast", "Understand how much brightness a picture holds, and what contrast adds.",
           r"""
**Dynamic range** is the span from the darkest to the brightest tone that can be recorded with detail. A sunny scene with deep shade has a huge range; a foggy morning has a small one.

**Contrast** is how big the *difference* between dark and light is in a picture. High contrast looks punchy and dramatic; low contrast looks soft and gentle. Neither is wrong.

## Why film is special

Colour negative film records a very wide range, much more than a screen or a print can show. A good scan keeps all of it, and the **conversion** squeezes it into the range a screen can display. That is why a straight inversion can look flat or oddly coloured, and why EFAS's tone tools (Contrast, Shadows & Highlights, the Tone Curve, Print Response) matter so much.
""", keywords=("range", "latitude", "contrast", "flat", "punchy"), see=("film-latitude", "contrast-module")),

    Lesson("colour-temperature-and-white-balance", "photo", "Colour temperature and white balance", "Understand warm and cool light and what 'white balance' fixes.",
           r"""
Light has a colour. Candlelight is orange, a cloudy sky is blue. The scale for this is **colour temperature**, in kelvin: around 3000 K is warm (orange), 5500 K is daylight, 7500 K and up is cool (blue). It runs the 'wrong way' to what you might expect: warm colours have the *lower* numbers.

Our eyes quietly correct for it, so a white shirt looks white in any light. A camera or film does not, so a picture can come out too orange or too blue. **White balance** is the correction: telling the picture what 'white' should be, so a white thing is white.

## Temperature and tint

White balance has two directions. **Temperature** moves between blue (cool) and yellow-orange (warm). **Tint** moves between green and magenta. Between them they can fix almost any colour cast.

## In EFAS

The **Color** module's Temperature and Tint sliders do this. For a negative, much of the balancing happens during conversion, which reads the film base; see [[sample-film-base]]. For the scanning light itself see [[scanning-light]].
""", keywords=("white balance", "kelvin", "warm", "cool", "tint", "cast", "temperature", "wb"), module="Color", see=("colour-basics", "color-module", "recipe-colour-cast")),

    Lesson("colour-basics", "photo", "Hue, saturation and lightness", "Describe any colour in three numbers and use the colour wheel to fix casts.",
           r"""
Any colour can be described by three things.

- **Hue**: which colour it is (red, yellow, green, blue...), a position on the colour wheel.
- **Saturation**: how vivid it is. Zero saturation is grey; full is a pure, intense colour.
- **Lightness**: how bright it is, from black to white.

EFAS's Color Mixer has exactly these three controls, for each of eight colour ranges.

## The colour wheel and casts

Colours opposite each other on the wheel **cancel**: red and cyan, green and magenta, blue and yellow. That is the key to removing a **colour cast** (an unwanted overall tint). A picture too green needs more magenta; too blue needs more yellow; too red needs more cyan.

TIP: To fix a cast, move the colour sliders **towards the opposite colour** a little at a time, and stop as soon as greys look grey. Small moves go a long way.
""", keywords=("hue", "saturation", "lightness", "colour wheel", "cast", "complementary", "color"), see=("colour-temperature-and-white-balance", "color-mixer-module", "recipe-colour-cast")),

    Lesson("focus-and-sharpness", "photo", "Focus, sharpness and resolution", "Tell blur from softness, and understand pixels and sharpening.",
           r"""
**Focus** is whether the lens is set to the right distance. A badly focused picture cannot be rescued by editing: there is no detail to bring out. **Sharpness** is how crisp the detail looks, and depends on focus, the lens, the aperture and camera movement.

## Resolution

A digital picture is a grid of **pixels**. A 24-megapixel picture has 24 million of them. More pixels capture finer detail, up to what the lens and film can actually resolve. A 35 mm negative holds far more detail than most people expect, and a high-resolution camera scan reveals the grain.

## Sharpening

Every digital picture is a little soft, and film scans especially. **Sharpening** increases the contrast along edges so detail looks crisper. It cannot add detail that is not there, and too much creates ugly bright halos around edges and exaggerates grain. Sharpen **last**, lightly. See [[sharpening-module]].

TIP: Turn on **focus peaking** (`Ctrl+Shift+F`) to paint the sharply-focused edges of the picture, which makes it easy to check whether a scan is in focus.
""", keywords=("sharp", "blur", "soft", "pixels", "megapixels", "resolution", "focus peaking"), see=("sharpening-module", "scanning-exposure")),

    Lesson("raw-and-bit-depth", "photo", "RAW, JPEG and bit depth", "Know why scanning in RAW matters and what 8-bit and 16-bit mean.",
           r"""
A **JPEG** is a picture the camera has already processed and squashed: colours chosen, tones set, detail thrown away to save space. A **RAW** file is the sensor's own data, almost untouched, with the processing decisions left for you.

For editing a negative, RAW is much better. A negative has to be flipped and rebalanced strongly, and a JPEG has already lost the subtle information that needs. EFAS opens RAW files from most cameras (CR2, CR3, NEF, ARW, DNG and more), as well as TIFF, PNG and JPEG.

## Bit depth

**Bit depth** is how many levels of brightness each colour channel can hold. **8-bit** has 256 levels. **16-bit** has 65,536. In a normal picture 256 is plenty; but stretching a narrow range, as a negative needs, with only 256 levels leaves visible **banding** (steps where there should be a smooth gradient). EFAS reads RAW and 16-bit scans at 16 bits and keeps them through the inversion and every tone and colour edit, rounding to 8 bits only once, at the very end, so the narrow range of a negative is not left banded.

TIP: Scan in **RAW**, and export a 16-bit **TIFF** if you plan to edit the result further elsewhere.
""", keywords=("raw", "jpeg", "tiff", "16-bit", "8-bit", "banding", "bit depth", "file format"), see=("scanning-exposure", "export-formats")),

    Lesson("composition-and-cropping", "photo", "Composition and cropping", "Use crop, straightening and simple composition rules to improve a picture.",
           r"""
**Composition** is how things are arranged in the frame. You can improve it after the fact by **cropping**: cutting away the edges.

A few simple ideas help:

- **Rule of thirds**: imagine the frame divided into a 3 x 3 grid and place interesting things on the lines or where they cross, rather than dead centre.
- **Straight horizons and verticals**: a tilted horizon looks like a mistake. A building that leans inwards looks wrong too (see [[distortion-and-keystone]]).
- **Remove distractions** at the edges: a bright patch or half a stranger pulls the eye away.
- **Leave room** in the direction a person or thing is looking or moving.

## In EFAS

The **Crop & Rotate** module has composition **Guides** you can overlay on the crop (Thirds, Phi Grid, Diagonals, Golden Triangles, Golden Spiral and more), a **Ratio** setting to hold a classic shape (3:2, 4:3, 5:4, 6:7, 16:9...), and a **Straighten** tool for horizons. See [[crop-and-rotate]].
""", keywords=("crop", "composition", "rule of thirds", "straighten", "horizon", "framing"), module="Crop & Rotate", see=("crop-and-rotate", "straighten-and-auto-crop")),

    # ------------------------------------------------------------------ how film works
    Lesson("film-types", "film", "Colour negative, black & white and slide film", "Tell the three kinds of film apart and know how EFAS treats each.",
           r"""
- **Colour negative film** (processed in a chemistry called **C-41**: Kodak Portra, Fuji Superia, Kodak Gold...). The picture is recorded with every brightness and colour reversed, on an orange base. This is what most people shoot and the main reason EFAS exists.
- **Black & white negative film** (Ilford HP5, Kodak Tri-X...). Reversed in brightness only. No colour, and no orange base. It scans as a grey negative.
- **Slide film / transparency** (processed in **E6**: Fuji Velvia, Kodak Ektachrome). A *positive*: it already looks right when held to the light. Nothing needs inverting.

## How EFAS handles them

In the **Convert** tab, **Film type** is set to **Auto-detect** by default: EFAS reads the scan and decides. You can choose **Color negative (C41)**, **Black & white negative** or **Slide film (E6)** yourself if it guesses wrong. Negatives are inverted to a positive; a slide is left as it is; a black-and-white negative is treated as monochrome. See [[film-type-setting]].
""", keywords=("c41", "e6", "slide", "transparency", "negative", "black and white", "b&w", "film stock"), see=("negative-orange-mask", "film-type-setting")),

    Lesson("negative-orange-mask", "film", "Why a colour negative looks orange and backwards", "Understand the orange base, and why 'just invert it' is not enough.",
           r"""
A colour negative is reversed twice over: bright things are dark, and each colour is its opposite (blue sky is orange-brown, green grass is magenta).

On top of that, colour negative film has an **orange base**, a built-in tint. It is deliberate: it is a *mask* that corrects for imperfections in the film's dyes, so that a printer can make correct colours from it. It means the 'empty' parts of the film (the clear film between frames, and the border) are orange rather than clear.

## Why simple inversion goes wrong

If you just flip the picture, the orange base becomes a strong blue-green cast over everything, and the three colour layers invert to different contrasts, so the colours drift. A proper conversion has to:

- **measure the film base** and remove it;
- **balance the three colour channels** separately;
- allow for how the dyes overlap (*crosstalk*);
- shape the result like a print.

That is what EFAS's **Convert** tab does. The best starting point is always to **sample the film base** (see [[sample-film-base]]).
""", keywords=("orange mask", "film base", "inversion", "cast", "dmin", "negative", "blue cast"), module="Negative", see=("sample-film-base", "inversion-method")),

    Lesson("film-speed-and-grain", "film", "Film speed and grain", "Choose a film speed and know what grain is.",
           r"""
**Film speed** is its ISO: 50, 100, 200, 400, 800, 1600. Lower numbers need more light but give a finer, smoother picture; higher numbers cope with dim light and give more **grain**.

**Grain** is the texture you can see in a film picture: tiny clumps of silver (black & white) or dye (colour). It is more visible in fast films, in small formats, in underexposed frames, and when you enlarge a picture a lot. Grain is not a defect: it is part of the look. A high-resolution scan shows it clearly.

## What to do about grain in EFAS

- **Nothing**, if you like it.
- **Chroma Denoise** smooths just the coloured speckle, keeping the grain's texture in brightness.
- Be gentle with **Sharpening** and **Local Contrast**, which exaggerate grain.
""", keywords=("grain", "iso", "speed", "texture", "fine grain", "noise"), see=("iso-and-noise", "chroma-denoise-module", "sharpening-module")),

    Lesson("film-formats", "film", "Film formats: 35 mm, 120 and larger", "Know the common formats and what the borders of a frame are.",
           r"""
- **35 mm**: the classic roll with sprocket holes along both edges; frames 36 x 24 mm. 36 frames on a roll.
- **120 medium format**: wider paper-backed film with no sprocket holes; frames from 4.5 x 6 cm to 6 x 9 cm. 8 to 16 frames per roll.
- **Large format (4 x 5 inch and bigger)**: single sheets.

## The border (the rebate)

Around each frame is the **rebate**: the unexposed film edge, sometimes with printed edge numbers and codes. When you scan, it gives you something very useful: an area of **clear film base** that tells EFAS the exact colour of the film itself.

## Why it matters in EFAS

- You can **sample the film base** from the rebate. See [[sample-film-base]].
- The rebate and a film holder's edge can **bleed** light into the picture. See [[edge-bleed-module]].
- Crop a little inside the frame so the border is not in the finished picture. See [[crop-and-rotate]].
""", keywords=("35mm", "120", "medium format", "large format", "rebate", "sprocket", "frame", "border"), see=("sample-film-base", "crop-and-rotate")),

    Lesson("film-latitude", "film", "Exposure latitude: why negatives forgive", "Learn why a slightly over-exposed negative is better than an under-exposed one.",
           r"""
Colour negative film has a lot of **latitude**: it still gives a good picture if the shot was a stop or two too dark or too bright. It is not symmetrical:

- **Overexposed** negatives (more light) still hold detail in the shadows and look rich. A stop or two over is often *better* than spot-on.
- **Underexposed** negatives lose shadow detail for good: those parts are simply not recorded. The result is muddy, grainy shadows.

So the rule among film shooters is: **expose for the shadows**, and let the highlights take care of themselves.

## What it means in EFAS

A well-exposed or over-exposed negative converts easily. An under-exposed one converts, but its shadows will be noisy and may get a colour cast: use **Shadows & Highlights** and a gentle **Tone Curve** to bring them back, and accept some grain. For a poorly exposed frame, the **Test Strip** (`Shift+T`) shows 25 exposure and contrast choices side by side.
""", keywords=("latitude", "overexposed", "underexposed", "shadows", "forgiving", "exposure", "test strip"), see=("dynamic-range-contrast", "shadows-highlights-module")),

    Lesson("dust-and-scratches-origins", "film", "Dust, hairs and scratches", "Know where film defects come from, so you can prevent most of them.",
           r"""
Film picks up marks in several ways:

- **Dust and hairs** land on the film before and during scanning. They show up as bright specks and curly threads in a scan.
- **Scratches** come from grit in the camera or in the processing: long fine lines, often vertical.
- **Fingerprints** and **water marks** come from handling and drying.
- **Newton rings** are rainbow ripples where the film touches glass in a scanner holder.
- **Light leaks** are orange or red glows from light getting into a camera.

## Prevention first

Clean as much as you can **before** scanning: a puff from a blower (not your breath), a soft brush, handle film by its edges. Every speck you do not have to remove is a speck you do not have to repair.

## Repair in EFAS

For what remains, see the **Frame & Clean** tab: **Dust & Scratches** removes specks automatically and has tools to heal what is left by hand, **AI Dust Detection** finds them with a small neural network, and **Error marking** lets you note faults that you cannot repair.
""", keywords=("dust", "scratch", "hair", "fingerprint", "newton rings", "light leak", "defects"), see=("dust-auto", "dust-manual", "error-marking")),

    Lesson("film-care", "film", "Handling and storing negatives", "Look after the only true original, and prevent most of what you would otherwise have to repair.",
           r"""
Your negatives are the only original you have, and they are more fragile than they look. EFAS never changes your scan files, but only you can protect the film, and good handling also prevents most of the dust and scratches you would otherwise spend time removing.

Hold film by its **edges**, or wear cotton or nitrile gloves, because skin oil leaves fingerprints that show in a scan. Store strips in **archival sleeves**, made of polypropylene or polyester and not PVC, which gives off acids that damage film over the years, upright in a box in a cool, dark, dry place. Heat and damp are the enemies of film, and a hot loft or a damp cellar can ruin a collection.

Keep strips **flat**, since a curled strip is hard to scan sharply across the whole frame. To remove dust, use a **blower** first, then a soft brush; never wipe dry film with a cloth, which drags grit across the surface and scratches it. Leave cleaning fluids alone unless you know exactly what you are doing, since the wrong one can damage the film.

Make a good scan once, back it up, and the film can go back into safe storage for good.
""", keywords=("storage", "gloves", "sleeves", "archive", "cleaning", "handling", "curl", "pvc", "fingerprints"), see=("dust-and-scratches-origins", "scanning-setup")),

    # ------------------------------------------------------------------ scanning your film
    Lesson("scanning-setup", "scan", "Scanning with a camera: the setup", "Understand what each part of a camera-scanning rig has to do, and why alignment matters most.",
           r"""
Photographing your negatives with a digital camera is fast, and with a good macro lens it can match or beat a flatbed scanner. It also gives you control: the camera's RAW files hold far more tonal information than most flatbed scans. But it is a small optical system, and each part of it has a job.

The **camera** has to be rock steady and pointing exactly at the film. That usually means a **copy stand**, or a tripod with the camera pointing straight down, or a horizontal rig with the film on a light panel. The **lens** should be a **macro lens**, because it must focus close enough for the film to fill the frame, and because macro lenses are designed to be sharp and flat at close range; a 100 mm macro is a classic choice for 35 mm film. The **light** under the film must be even and clean (see [[scanning-light]]). A **film holder** keeps the film flat and, just as importantly, masks all the light around the frame so it cannot scatter into the picture. And a **remote release**, or the camera's two-second timer, means pressing the shutter does not shake the camera.

## Alignment is everything

The most important thing in the whole setup is that the camera's sensor and the film are **parallel**. If they are not, one side of the frame is slightly nearer than the other: it will be out of focus, and the picture will be keystoned, a trapezoid instead of a rectangle. You can check by looking at the film's straight edges and the rebate: they should be parallel to the edges of the picture. EFAS can correct small amounts of keystone ([[distortion-and-keystone]]), but each correction costs a little sharpness, so it is much better to get it right at the camera.

Everything else (the exposure, the light, the cleaning) is a matter of care. The alignment is the one thing that cannot be fixed afterwards without cost.

TIP: A black card or paper mask round the frame stops stray light bouncing about and lifting the contrast. If you see bright edges in your scans, [[recipe-flat-light]] shows how to tell what is causing them.
""", keywords=("scanning", "copy stand", "macro lens", "tripod", "camera scanning", "digitize", "setup", "holder", "parallel", "alignment"), see=("scanning-light", "scanning-exposure")),

    Lesson("scanning-light", "scan", "The backlight", "Understand what makes a good light source for scanning, and how to tell EFAS about yours.",
           r"""
The light behind the film matters as much as the camera, because the scan is a measurement of how much of that light each part of the film lets through. Three qualities matter.

The light must be **even**. A panel that is brighter in the middle than at the edges puts a gradient across every scan, which is exactly the kind of thing the conversion then has to guess its way around. A good flat LED panel is ideal. If yours is not perfectly even, EFAS's **Flat Field** module can measure the unevenness and divide it out ([[flat-field-module]]), but an even light needs no correction at all.

It must have a good **colour rendering index (CRI)**, around 95 or more. CRI is a measure of how completely a light contains all the colours of the spectrum: a low-CRI light is missing some, and a negative's dye layers can then not be measured faithfully, which shows up as colours that are stubbornly wrong however you adjust them.

And it must be **steady**. Some cheap LED panels flicker at a high rate, which the eye cannot see but a camera can, as bands across the picture at fast shutter speeds. Using a shutter slower than about 1/60 s, or a flicker-free light, avoids it.

It also needs to be **bright enough** that you can use the camera's lowest ISO and a sharp aperture without an exposure so long that vibration becomes a worry.

## Telling EFAS about your light

Every light has a colour, and it tints the scan. In the Convert tab, **Scanning light...** lets you enter the colour temperature of your backlight, and EFAS works out a starting colour trim to cancel the tint. The reasoning, and its limits, are explained in [[colour-trim-and-scanning-light]].
""", keywords=("light panel", "backlight", "cri", "led", "flicker", "even light", "colour temperature", "light source"), module="Negative", see=("flat-field-module", "colour-trim-and-scanning-light")),

    Lesson("check-your-light", "scan", "Checking your scanning light", "Measure whether your backlight is steady and even, and tell a changed light from a changed exposure.",
           r"""
You cannot judge a backlight by eye. A panel that has dimmed by 5%, or turned a little bluer, looks exactly the same to you, but your camera's sensor sees it, and the scans of a roll will then not match each other. The conversion cannot tell that the light moved from the film having changed, so you end up correcting colours that were never the film's fault. **Extra > Check My Scanning Light...** measures the light instead of leaving you to guess. It reads RAW photos straight from the sensor, before any conversion, and changes nothing.

## Checking the bare light

Take the film out and photograph the light itself, with the camera on manual so the shutter speed, aperture, ISO and focus never change, and the exposure bright but not blown out. Shoot twice straight after switching the light on, because those two shots show how much the numbers wobble on their own, then once every five to ten minutes for an hour. Choose those photos in the check and it compares each with the first.

It answers four questions. Does the light get brighter or dimmer, and when does it settle? Many panels need a few minutes to warm up, and the check says how long yours does. Does its colour move? Red and blue are each compared with green, which exposure cannot change, so a drift there really is the light. Is it even, meaning the middle of the frame against the corners? That figure includes your lens's own falloff, so judge the change rather than the level. And was anything blown out, or did the camera settings change between shots, which would make the comparison meaningless?

## Checking a roll of scans

The same measurements can be made on real negatives, because every frame has pieces that do not depend on the picture: the clear orange film between the frames, the bare light showing through the sprocket holes, and the black holder. Choose the RAW scans of one roll (one roll at a time, because every film is a slightly different orange) and the check compares each scan with a reference.

Its main trick is to tell the causes apart. If the clear film came out darker than the shutter speed and ISO explain, the light dimmed. If it came out darker and the camera used a faster shutter, that is exposure, not the light. If the film's colour changed but the light in the sprocket holes did not, it is a different film or strip, or the light had only just been switched on. It also says how many stops the clear film sits below blown out, whether the camera chose the exposure itself, how much stray light reaches the holder, and what to change. How it differs from **File > Check Roll Consistency...**: that finds which frames differ from the rest, and this explains why, from the camera's own settings.
""", keywords=("light check", "light drift", "backlight", "warm up", "flicker", "even light", "stray light", "sprocket holes", "film base", "exposure", "lightdrift", "scanning light"), see=("scanning-light", "scanning-exposure", "flat-field-module")),

    Lesson("scanning-exposure", "scan", "Exposure and focus for scanning", "Choose camera settings that capture the whole range of a negative cleanly, and focus them exactly.",
           r"""
Scanning is the one kind of photography where nothing moves and you control the light, so you choose every setting for *quality*. A few decisions do most of the work.

Shoot **RAW** and in **manual mode**, so the camera records the sensor's own data and nothing changes from one frame to the next. Use the camera's **lowest ISO** (usually ISO 100) for the cleanest data, an **aperture around f/8**, where most lenses are at their sharpest ([[aperture-and-depth-of-field]]), and then set the **shutter speed** (or the brightness of the light) to get the exposure right.

## Getting the exposure right

The exposure to aim for is as bright as you can make the *negative* without clipping. Look at the camera's **histogram** of the negative and make its right-hand end nearly reach the edge without touching it. Slight overexposure of the negative is fine; clipped highlights are not, because a clipped part of a negative is a part of the picture with no information left. This is sometimes called *exposing to the right*, and the reason is how a digital sensor records light: it records more distinct levels in its brightest part, so putting the negative as bright as you can without clipping captures the most information, and the least noise, in the thin parts of the negative that become the shadows of your picture.

## Focus

Focus **manually**, using live view magnified to see the film's grain. Grain is the best focus target there is: if the grain is crisp, the picture is sharp. Autofocus has nothing to lock on to in a smooth negative and will hunt. Check focus again if you change anything.

## Keep it the same

Once the settings are right, keep them **identical for the whole roll**. Then every frame sees the same light and the same exposure, and EFAS can give them all the same film base and flat field, which is why a roll's colour comes out consistent.

TIP: EFAS can check a RAW scan and tell you in plain words whether it was under-exposed or clipped, and by how many stops: see [[scan-quality-check]].
""", keywords=("exposure", "expose to the right", "ettr", "focus", "raw", "settings", "iso", "aperture", "grain", "histogram"), see=("raw-and-bit-depth", "scan-quality-check")),

    Lesson("scanning-flat-and-clean", "scan", "Flat, clean and masked", "Understand the four ways a scan is quietly spoiled before it is taken: curl, dust, stray light and reflections.",
           r"""
Most of what goes wrong with a scan goes wrong before the shutter is pressed, and most of it comes down to four causes.

**Curl.** Film that is not flat is out of focus somewhere. A strip that curls even gently puts part of the frame a fraction of a millimetre nearer the lens, which at close macro distances is enough to soften it. Use a holder or a glass carrier that keeps the strip flat across the whole frame.

**Dust.** Every speck on the film or on the glass is a speck in the scan, and a repair to make later. A puff from a blower just before you shoot, and a clean working area, save more time than any retouching tool.

**Stray light.** This is the subtle one. Light that does not pass through the frame (light round its edge, through gaps in the holder, through the sprocket holes) scatters inside the lens and camera and lifts the edges and the shadows of the picture. That is **edge bleed**, and it cannot be fully removed afterwards, only reduced ([[edge-bleed-module]]). A black card or mask cut to the frame size, so that the only light the camera sees is the light that goes through the picture, prevents nearly all of it.

**Reflections.** Film and holders are glossy. In a bright room the lens, your clothing and the lamps are reflected in them as faint colour patches. Shoot in a dim room with a dark background. If you use glass to flatten the film, you may see **Newton rings**, rainbow ripples where the film touches the glass; anti-Newton glass, which is very slightly roughened, or letting the film lie without glass, avoids them.

None of these is expensive to prevent, and all of them are tedious to repair.
""", keywords=("flat", "clean", "mask", "reflection", "stray light", "glass", "newton rings", "bleed", "curl", "dust"), see=("edge-bleed-module", "recipe-flat-light")),

    Lesson("scanning-tethered", "scan", "Scanning with the camera tethered", "Understand why shooting from the computer helps, and how EFAS works with the folder your camera software fills.",
           r"""
**Tethered shooting** means the camera is connected to the computer by USB cable or Wi-Fi and you take the picture from the computer. Canon's free **EOS Utility** does this for Canon cameras: it can show a live view on the computer, set the exposure, fire the shutter, and save each picture straight into a folder on the computer, so you never need to touch the camera. That matters for scanning for two reasons. The camera does not move when you press the button, and you see every frame the moment it is taken, large, on a proper screen, in time to retake it before you advance the film.

A USB cable is faster and steadier, and the better choice for a whole roll, because a RAW file is large. Wi-Fi works well for a few frames and for testing.

## How EFAS fits in

For a Canon camera on Windows, EFAS can drive the camera itself ([[tether-live-view]]). For any other camera it cannot, but it can watch the folder the camera software saves into. Mark that folder as a **Hotstack** and each photo that lands in it is read in, selected, and opened in the editor with the negative already converted, so you can check the **focus**, the **exposure** and the **edges** of each frame at once. If a frame is wrong, **Retake** it: the next photo replaces it. When the roll is finished, **Finish Session** files everything into a dated folder.

The details, and all the options, are in [[hotstack-lesson]], and a start-to-finish description of a session is in [[recipe-tether-session]].
""", keywords=("tethered", "eos utility", "wifi", "usb", "hotstack", "live", "canon", "remote"), see=("tether-live-view", "hotstack-lesson", "recipe-tether-session")),

    Lesson("tether-live-view", "scan", "Tethering a Canon camera in EFAS", "Use EFAS's own live view, lens drive and sharpness meter to focus once, check it, and shoot a roll.",
           r"""
For a Canon camera on Windows, EFAS can do what the camera's own software does and a little more: **Extra > Canon Tether and Live View...** shows the camera's live picture, drives the lens, and takes the picture into your roll folder. It is made for a copy stand, where you focus once and then shoot thirty-six frames that must all be focused the same.

## Connecting

EFAS cannot include Canon's SDK, which Canon licenses to each developer, so you get your own copy from Canon's developer site and choose its folder in the window. Put the camera's exposure on manual with a fixed shutter speed, aperture and ISO, because EFAS does not change the camera's exposure. Switch the camera's Wi-Fi and Bluetooth off, since a Canon body turns USB data off while wireless is on and the only symptom is that no camera is found. Close EOS Utility, and plug a data cable straight into the computer. If you want to look around first, the **practice camera** needs no camera at all: it is a made-up negative with a lens that goes out of focus as you drive it, and every control works on it.

## Focusing

The live picture is shown as a **positive**, converted by the same NegPy Conversion as the editor, so you judge focus on what you will see rather than on a murky orange negative. Click a patch of clear film and the conversion learns the film's colour. **Focus peaking** marks what is sharp in colour, and the **loupe** enlarges the camera's own pixels under the mouse. Drive the lens with the Left and Right keys (fine steps; Shift for medium, Alt for coarse). The **Peaking sensitivity** slider sets how much peaking marks, and holding **N** shows the other of positive and negative while you hold it. The **sharpness meter** is the part a screen alone cannot give you: a number that rises as focus improves, with the best so far kept beside it and a word for it (Sharpest, Sharp, Nearly there, Soft, Blurred). Go past the sharpest spot and back, and the meter peaks there. It is relative, so it means something within one focusing session only, and it measures a square you can move by clicking. **Corners** compares the middle with each corner: a soft corner on a copy stand means the camera is not parallel to the film.

## Exposure and zoom

The **Exposure** box shows the camera's ISO, aperture, shutter speed and exposure compensation, and lets you set the ones the camera will take: with the mode dial on **M** that is ISO, aperture and shutter speed, and on Av or Tv the camera sets one itself and the box says so. **Auto exposure** meters the film in the live picture, leaving out the black holder and the bare light of the sprocket holes, finds how bright the clear film base gets and moves the **shutter speed** until the base sits just short of clipping. That is the right place to stop for a negative: the conversion needs the base's colour to take out the orange, and the picture, which is denser than the base, comes out as bright as it can without losing it. It leaves the aperture and ISO alone, and says so if the shutter runs out of range. The **Zoom** slider under the picture enlarges the live picture up to 800%, the wheel zooms where the pointer is, and dragging moves it; it is software, so it shows the pixels the camera sent and no more.

## Taking the roll

**Capture** waits a moment for the rig to stop shaking, since vibration is the commonest cause of a soft scan, then releases the shutter without focusing, so focus cannot change between frames. Each picture is saved as your name and a frame number, and a RAW and its JPEG share the number. Each can open in the editor straight away, and the roll folder can be a hotstack ([[hotstack-lesson]]). The RAW files this makes are exactly what **Check My Scanning Light** reads ([[check-your-light]]).
""", keywords=("tether", "tethered", "canon", "live view", "focus", "sharpness", "peaking", "loupe", "edsdk", "shutter", "practice camera", "copy stand", "remote"), see=("scanning-tethered", "scanning-exposure", "hotstack-lesson", "check-your-light")),

    Lesson("grain-report", "scan", "The Grain Report", "Measure the film's real grain, learn whether your capture resolves it, and see whether your sharpening and denoise keep it.",
           r"""
EFAS never adds grain: a scan of film already has its own, and adding more would invent texture the film did not have. What it can do is **measure** the grain that is there. **Extra > Grain Report...** does that for the open photo and changes nothing.

## What your capture resolves

Film grain is a texture a few to a few tens of micrometres across. A scan whose pixels are about as big as the grain, or whose focus is soft, cannot show it, and what looks like grain is then mostly **sensor noise**. The report picks flat, mid-tone patches of the scan, takes out the slow variation under them and measures what is left: how **strong** it is, as a percentage of the brightness (per channel for a colour scan), and how **wide** it is in pixels, as the distance at which it stops resembling itself. Under one pixel wide the grain is **not resolved**; from two pixels up it is **resolved**; in between it is partly resolved. Each verdict comes with advice: a closer capture, your lens's sharpest aperture, careful focus and a low ISO resolve more. With the Roll Card's format set to 35mm it also says how much film one pixel covers.

The report states its limits: the camera's demosaicing makes noise about a pixel wide even when the film's grain is much finer, and it measures only the patches it picked.

## Whether your edits keep it

It then converts the same patches at the scan's own resolution with your **Sharpening**, **Chroma Denoise** and **Local Contrast**, and with them off, and compares the fine texture. The answer is in words: the edits keep it, remove some percentage of it, or raise it, which means sharpening is making the grain and the noise stronger, naming the module that did most. The first patch is shown at 100% both ways so you can see it.

TIP: Scan at the base ISO and the lens's sharpest aperture before blaming the film. If the report says the grain is not resolved, no amount of sharpening will find it.
""", keywords=("grain", "noise", "resolve", "resolution", "sharpening", "denoise", "scan quality", "iso", "focus", "report"), see=("scan-quality-check", "sharpening-module", "scanning-exposure")),

    Lesson("scan-quality-check", "scan", "The scan quality check", "Learn what EFAS measures to rate a scan, and how to read its verdict.",
           r"""
When you open a RAW scan, EFAS reads the file a second time in the background and gives you a plain-words verdict in the **Convert** tab, under **Scan quality**. It uses the same measurements as the Advanced mode (the film base, how much headroom there is before the sensor clips, and the amount of noise in the densest parts of the negative) and puts them in terms of **stops**, so you know exactly what to change.

The verdicts are simple to read. **Good** means the negative uses the sensor's range well and the numbers can be trusted. **Clipped** means part of the film base or the lightest areas reached the sensor's limit, so use a shorter exposure. **Under-exposed** means the film base sits well below the limit, so the thin parts of the negative (which become the shadows of the picture) carry more noise than they need to: use a longer exposure, or merge a bracket. A scan can also be **limited by the density of the film**, where the densest parts of the negative are lost in noise at this exposure, which a longer exposure or a bracket recovers.

The verdict needs a RAW file (or a scan merged within EFAS). It uses some extra memory and a few seconds of background work for each photo, so on a slow computer you can switch it off in **Settings > General**.

NOTE: The verdict is about the *scan*, not the picture. A technically perfect scan of a dull, flat negative is still a perfect scan, and a lovely picture can come from a technically poor one.
""", keywords=("scan quality", "verdict", "underexposed", "clipped", "check", "raw", "headroom", "stops"), module="Negative", see=("scanning-exposure", "clipping")),

]
