"""Tool guides for the Convert tab and the Frame & Clean tab: what each tool does, how it works inside, what each control does to the picture, and how to use it well."""
from .logic import Lesson, Section

SECTIONS = [
    Section("convert", "Convert: negative to positive", "The Convert tab in depth: telling EFAS what the film is, measuring it, and correcting the light it was scanned in."),
    Section("frame", "Frame & Clean", "Cropping, straightening and perspective, then removing dust, hairs and scratches: each tool explained from the inside."),
]

LESSONS = [
    # ------------------------------------------------------------------ Convert
    Lesson("convert-overview", "convert", "Convert: from a negative to a picture", "Understand what converting a negative involves, and how the three modules of the Convert tab share the work.",
           r"""
A scan of a colour negative does not look like a photograph, and the reasons are separate problems that have to be solved one after another. The tones are **reversed** (shadows bright, highlights dark). Every colour is replaced by its **opposite**. The whole thing sits on an **orange base**, the colour of the film itself. And the three colour layers of the film do not respond to light in exactly the same way, so even after flipping and removing the orange, the red, green and blue come out at slightly different strengths and the picture leans one way. Converting is the job of undoing all four.

The **Convert** tab holds the tools for it. **Negative** is the heart: it works out what kind of film you have, measures the film base and the range of the picture, and does the reversal. **Flat Field** and **Edge Bleed** come next because they are about the *scan* rather than the film: they correct unevenness in the backlight and light leaking into the picture's edges, both of which would otherwise fool the measuring.

## How the measuring works

Everything in the conversion rests on one idea: a negative's brightness is best handled as **density**, the logarithm of how much light the film stops. Equal steps in density are equal steps in how the film responded to the scene, so a straight line in density is a faithful way to bring the tones back. EFAS reads the density of each colour channel over the part of the picture you have cropped to, finds where the picture's darkest and lightest parts sit, and maps that range onto black and white.

## Why order matters

The measurement reads whatever is in front of it. Crop the film border off first, so the border does not count as the brightest part of the picture. Sample the film base so the measurement starts from the real colour of the film. Correct the backlight with Flat Field before you judge colours at the edges. Those three habits, in that order, do more for a conversion than any slider.
""", keywords=("convert", "negative", "invert", "overview", "tab", "density", "orange mask", "conversion"), module="Negative", see=("film-type-setting", "sample-film-base", "inversion-method")),

    Lesson("film-type-setting", "convert", "Film type and how EFAS detects it", "See how EFAS tells a colour negative, a black-and-white negative and a slide apart, and what each setting does to the scan.",
           r"""
The first decision in any conversion is what kind of film the scan came from, because the three kinds are treated completely differently. **Colour negative (C-41)** is reversed and has its orange base removed. **Black-and-white negative** is reversed and turned strictly monochrome. **Slide film (E-6)** is a positive already, so it is left exactly as it is and no reversal is applied. In the **Negative** module, **Film type** is set to **Auto-detect** by default and the other three let you decide for yourself.

## How the detection works

EFAS takes a small copy of the part of the picture you have cropped to (or, with no crop, the picture inside a margin of about 12% all round, so the film border does not count) and asks three questions of it. First: do the red, green and blue channels look like the *same picture*? If all three channels correlate to better than 0.99, there is no colour information worth keeping, and it is called black-and-white. Second: is the scan **orange**? A colour negative's base makes red much stronger than blue, so EFAS compares red to blue by the average, by the darker quarter of the picture and by the brightest parts, and if red beats blue by half again in any of those it is called a colour negative. A third, smaller test catches negatives with a purple tint, where green is weak against red and blue. A scan that passes none of the tests looks like an ordinary photograph, so it is called a slide.

## The controls

**Film type** is the choice itself. If you set it by hand, EFAS stops guessing, which is what you want when the detection is wrong.

**Detect** runs the detection again on the current crop and *reports* what it found without changing anything. That makes it a safe way to check what EFAS thinks it is looking at.

**Invert to Positive** switches the reversal on or off by hand. It is the escape hatch for a scan that comes out the wrong way round whatever the type says.

## When detection goes wrong

Detection reads statistics, so it can be fooled by a picture that does not look typical: a nearly black frame, a blank leader, a scene dominated by one colour, or a negative with a strong cast of its own. If a conversion looks inverted wrongly or oddly grey, set the film type yourself before touching anything else. A **black-and-white negative scanned in colour** deserves the explicit **Black & white** setting: the scan carries a faint colour tint from the film base and the light, and the monochrome setting replaces the three channels with the picture's brightness so the result is truly neutral.
""", keywords=("film type", "auto detect", "c41", "e6", "slide", "invert", "black and white", "b&w", "detect", "monochrome", "orange"), module="Negative", see=("film-types", "sample-film-base")),

    Lesson("sample-film-base", "convert", "The film base, and why you sample it", "Understand what the film base is, how a sample changes the conversion, and the three ways to find it.",
           r"""
Colour negative film is not clear: it is tinted orange all over, even where no light ever reached it. That tint is the **film base**, and it is the single most useful thing the conversion can know, because it is the one place on the roll where the film is guaranteed to hold *no picture at all*. The border around the frames, and the gap between them, shows it plainly.

## What a sample changes

Without a sample, EFAS has to guess where the picture's black is. In the standard conversion it measures each colour channel's density over the cropped picture and treats the darkest ordinary shadow it finds (the first percentile of the density) as the floor. That works for most pictures, because most pictures have a real shadow in them. It goes wrong when they do not: a foggy morning, a high-key portrait, a snow scene. The guessed floor is then too high, EFAS stretches the picture's shadows down to black, and the result is too contrasty and often leans a colour.

With a sample, the floor is the measured colour of the unexposed film. Black now means "no exposure at all" rather than "the darkest thing in this particular picture", and that does not depend on what the scene contained. EFAS only uses the sample when it is believable, that is when it sits clearly (more than 0.15 density) below the brightest part of the picture. In the **Modern** conversion the sample matters even more: the film's own curve can only be restored accurately when the base is known, so without it that step is scaled down to about a third.

## The three ways to find it

**Sample Film Base** shows you the raw scan. You click once on clear film (the rebate, the gap between frames) and the colour under your click becomes the base for **every photo in the folder**. **Clear** goes back to guessing. Click a spot that is clean: a speck of dust, or a patch where part of a frame bleeds into the gap, gives a wrong base.

**Find Film Base Automatically** hunts for a clear border in the open scan itself, marks the area it chose on the picture and tells you how confident it is and why. **Nothing changes until you press Use This Film Base**, so you can reject a bad find.

**Find Film Base for the Whole Roll** reads the border of up to a dozen frames along the folder and combines them. Because the border is the same film in every frame, combining many readings steadies the colour from frame to frame, and no single picture (a sunset, a snow field) can pull the result. It only offers a base when at least two frames have a clean border and most of them agree, and again nothing changes until you confirm.

## When there is no border

If your film holder masks the border away, you have no film base in the picture to sample. Shoot a frame of clear, developed film at the start of the roll (or the end) with the same holder and settings, and sample that.
""", keywords=("film base", "sample", "dmin", "orange", "calibrate", "rebate", "border", "eyedropper", "automatic", "whole roll"), module="Negative", see=("negative-orange-mask", "whole-roll-tools")),

    Lesson("inversion-method", "convert", "The two conversion methods: Modern and Original", "Understand how the Original stretch and the Modern film-and-paper conversion differ in what they assume, and when each is better.",
           r"""
The conversion has two engines, chosen with **Conversion > Method** in the **Negative** module. The difference is not cosmetic: they model the problem differently.

## Original: a straight stretch

The Original method treats each colour channel separately. It measures the channel's density at the dark end and the light end of the picture (the floor and the ceiling), and maps that span linearly onto black and white. In plain terms, it **stretches each channel until the picture fills the range**. This is simple, quick and forgiving, and it is what most quick conversion tools do. It handles three different things as one: the film, which does not respond in a straight line; the scene, whose own brightness range varies from frame to frame; and the paper (or screen) it will end up on.

Four controls belong to Original alone: **Range clip**, **Color cast**, and the **white and black points** with their droppers. They are its way of deciding where black and white land. Under Modern they are greyed out. See [[metering]] and [[white-black-points]].

## Modern: film and paper

The Modern method keeps those three things apart, in the order a darkroom meets them: the film, then the scene, then the paper. It works in density, takes out the overlap between the dye layers, puts back part of the film's S-shaped response, balances the channels, and then prints through a paper curve with its own toe and shoulder, so highlights **roll off** into white instead of clipping. The next guide explains each stage and its controls: [[modern-conversion-controls]].

## Which to use

New photos, and photos that were only opened and never edited, get **Modern**. Photos that were edited before Modern existed keep **Original**, so their look does not change underneath you. The choice is saved per photo and goes into presets.

On real scans Modern usually gives smoother highlights and clips far fewer pixels than Original, with a little less contrast out of the box. **Grade** and **Print density** are there to bring the contrast up to taste. Original remains the more predictable method when you want to push the range yourself with white and black points. Judge it on your own film: switch the **Method** menu and look.

There is one more button nearby, **Compare Methods...**, and it is about something else: in Advanced mode it shows the standard conversion beside the *curve-informed* one, which uses a film profile you measured yourself, with numbers. It changes nothing.
""", keywords=("modern", "original", "method", "conversion", "compare", "highlights", "clipping", "inversion", "stretch", "paper"), module="Negative", see=("modern-conversion-controls", "metering")),

    Lesson("modern-conversion-controls", "convert", "The Modern conversion, step by step", "Follow the six stages of the Modern conversion and see which control belongs to which stage.",
           r"""
The Modern conversion is a short chain of steps, and each of its controls adjusts exactly one of them. Knowing the chain tells you which slider to reach for when something looks wrong.

## 1. Density, then 2. crosstalk

First the scan is made **linear** (the display encoding undone) and turned into optical density, minus the log of the light that passed. Equal density steps are equal steps of the film's response. Then comes a correction most converters skip. A dye layer does not only absorb its own colour: it absorbs a little of its neighbours' too, so the three measured densities are *mixed copies* of the three real dye densities. Because the mixing is linear in density, a three-by-three matrix undoes it, with rows that each add up to one so that a grey stays grey.

Undoing the encoding means knowing which one the scan has. **Encoding** says: **Automatic** (the default) reads it from the file, since a RAW file that EFAS decodes carries libraw's own curve (Rec. BT.709) and any other file is read as sRGB. Choose **Linear** for a 16-bit TIFF from scanner software that saved the scan without a curve. The curves differ most in the darkest codes, which on a negative are the densest parts and become the positive's highlights, so reading BT.709 codes as sRGB overstates density there by up to 0.46 (about a stop and a half). A photo edited before this was a setting keeps sRGB, the reading it was edited with; set Encoding to Automatic to move it to the correct one, and expect the picture to change.

**Film** chooses the matrix: a generic colour negative (the default), none, one of about sixteen real stocks (Kodak Portra 160, 400 and 800, Ektar 100, Gold 200, Ultra Max 400, Fuji 200, 400, Superia X-TRA 400, Pro 400H and more), or a profile of your own. These are approximations read from the makers' published dye curves, so they describe the dyes but not your scanning light. **Crosstalk** sets how much of the unmixing is applied, from none to all of it.

## 3. The film's curve

A film's density does not rise in a straight line with the light: the **toe** flattens the shadows and the **shoulder** flattens the highlights. The inverse of an S-shaped curve puts that back, which gives log exposure, the scene as the film saw it. **Film curve** sets how much. It needs to know the base density, so it is scaled down to about a third when the base is only estimated: sample the film base ([[sample-film-base]]) for the full effect.

## 4. Balance

Each channel is scaled and shifted so all three cover the same range (from the picture's second to its ninety-eighth percentile). This is what removes the orange mask and the differences between the layers. It also means a scene dominated by one colour is pulled a little towards neutral, which is worth knowing when a sunset looks too grey.

## 5. Print

The log exposure now goes through a **paper curve**: a straight middle (its slope is the **grade**) between a toe that rolls shadows into paper black and a shoulder that rolls highlights into paper white. The slope is chosen so the picture's own range fills the paper's usable range, and the picture's middle prints near a mid grey, both only partly (80% and 65%), so a plainly dark picture keeps its mood. A *shadow reach* rule raises the slope by up to a quarter when the darkest tail would otherwise print grey, which is what a flat negative needs.

**Grade** adds to that automatic slope: positive is punchier, negative softer. **Print density** shifts the print darker or lighter, like exposing an enlarger longer or shorter. **Paper toe** and **Paper shoulder** shape the two roll-offs. **Red, Green and Blue grade** change the contrast of one colour layer around the picture's middle, which corrects **crossover**: a cast in the shadows that is the opposite of the cast in the highlights, which no single colour slider can fix without moving the middle tones.

## 6. Light

Finally the print density becomes reflectance measured against the paper (paper white is 1, paper black is 0) and is encoded for the screen.

Stages three to six are one curve per channel, so the whole thing is built as a lookup table: that is why changing Grade is instant.
""", keywords=("grade", "print density", "crosstalk", "film curve", "paper toe", "paper shoulder", "crossover", "modern", "film profile", "portra", "dye"), module="Negative", see=("inversion-method", "print-response-module")),

    Lesson("metering", "convert", "Metering: what the conversion measures", "See exactly which part of the picture sets black and white, and how Margin, Draw Region, Range clip and Colour cast change that.",
           r"""
The conversion needs to know what to treat as black and what as white, and it finds out by **metering** the picture, much as a camera does. Understanding what it reads explains most strange-looking conversions.

## What is read

By default EFAS measures the picture you have **cropped to**. With no crop it measures the picture inside a **margin** (12% all round to start with, adjustable up to 30%), so the border of the scan does not count. It does not look at every pixel: it works on a small copy, which is plenty for percentiles. For each colour channel it takes the density at the **1st percentile** (the floor: the thin, nearly clear parts of the negative, which are the scene's deepest shadows) and the **99th percentile** (the ceiling: the densest parts, which are the scene's brightest highlights). Percentiles rather than the extremes are used so a few stray pixels, a speck of dust or a pin-prick of light, cannot set the black and white.

## The controls

**Margin** sets how much of the picture's edge is ignored when there is no crop. Raise it if the edge of your scan has a bright border or a dark holder you cannot crop.

**Draw Region** replaces all that with a patch you drag out, and only that patch is measured. Use it to meter from a part of the picture that has the right range (a face, a sky and a shadow) when the whole frame is dominated by something misleading. The **X** beside it removes the region.

**Reset Metering** puts everything back to measuring the whole cropped picture.

**Range clip** moves the percentiles. Each unit of the slider shifts both ends by two percentage points, so +1 reads the 3rd and 97th percentile instead of the 1st and 99th. Positive values clip the extreme tails harder (more contrast, more clipped pixels); negative values leave more of the tails (a gentler look).

**Color cast** decides how independently the three channels are treated. At 1 each channel is stretched on its own, which removes any cast completely, including a real one such as the golden light of a sunset. Lower it and each channel's floor and ceiling are pulled back towards the average of all three, so the cast comes back in proportion.

## Why you crop first

The metering reads the crop. If a bright film border or a black holder edge is inside what is measured, it becomes the 'brightest' or 'darkest' thing in the picture and everything else is scaled to fit it. Crop to the picture before you judge a conversion, and the measuring becomes about the picture. (The **Edge Bleed** module's border mask has a switch to keep its band out of the measuring for the same reason.)

Under the Modern conversion, **Margin** and **Draw Region** still decide what is measured; **Range clip** and **Color cast** are Original's controls and are greyed out.
""", keywords=("metering", "margin", "region", "range clip", "color cast", "reset metering", "measure", "percentile", "crop"), module="Negative", see=("white-black-points", "crop-and-rotate")),

    Lesson("white-black-points", "convert", "White and black points, and the droppers", "Learn what the white and black points move, how the droppers set them, and why a dropper sometimes refuses.",
           r"""
In the Original conversion, the measured floor and ceiling of each channel are where black and white would land. The **white point** and **black point** let you move those landing places, so you decide how much of the range is thrown away at each end. They are Original's controls: under the Modern conversion they are greyed out, and **Grade** and **Print density** do the same job.

## What the sliders do

**Black point** moves where black lands. Raising it makes more of the shadows go to pure black (a deeper, contrastier picture, with more clipping); lowering it lifts the floor so the shadows stay open. **White point** does the same at the other end: raising it makes more of the highlights go to pure white. Each unit of the slider moves its end by a quarter of that channel's density span, and the sliders reach two units either way.

The **Channel** dropdown lets you move the points for **one colour channel at a time**. That is how a cast that only affects the highlights or only the shadows is corrected: pull the white point of the channel that is too strong, and only the highlights change colour.

## The droppers

The **White dropper** and **Black dropper** set the points from a spot you click on the picture. Click something that should be pure white, and EFAS moves each channel's white point to where that pixel's density is, so all three reach white together and **that pixel comes out neutral**. The overall slider gets the average and the per-channel trims get the differences. The black dropper does the mirror image for black.

A dropper can **refuse**. If you click the dark end of the picture with the white dropper, or the bright end with the black one, no setting of the sliders could do what you asked, and EFAS says so instead of producing nonsense. It also refuses when the result would leave white and black almost touching.

## Using them well

Click something that really is white or black: a specular highlight, a white shirt in full light, the deepest shadow. A cloud or a shirt in shade is only *nearly* white, and clicking it dims every white in the picture. Avoid anything with a colour of its own, because the dropper makes the clicked spot neutral and would drag the whole picture's colour with it.

For a more precise tool with the same goal in the finished picture, the **Tone Curve** has its own Black, Grey and White pickers: see [[tone-curve-module]].
""", keywords=("white point", "black point", "dropper", "eyedropper", "levels", "channel", "range", "neutral"), module="Negative", see=("metering", "tone-curve-module")),

    Lesson("colour-trim-and-scanning-light", "convert", "Colour trim and the scanning light", "Understand what the Red, Green and Blue trims do, and how EFAS works out a trim from the colour of your backlight.",
           r"""
Even after the film base is removed and the channels are balanced, a picture can lean slightly towards a colour. **Color trim** is the quick correction in the Convert tab: three sliders, **Red**, **Green** and **Blue**, applied to the *finished positive*. Dragging right adds that colour; dragging left takes it away. Each unit of a slider adds or removes 64 levels (out of 255) of that colour across the picture, and double-clicking a slider puts it back to zero.

Because the trim adds the same amount everywhere, it is a coarse tool, best for a cast that the base sample and the metering did not remove. For colour that needs a finer touch, the **Color** tab's Temperature and Tint, the Color Mixer, and the Tone Curve's colour channels all work in more refined ways: see [[color-module]] and [[recipe-colour-cast]].

## Scanning light...

The light behind the film tints the scan: a warm panel makes everything warmer, a cool one cooler. **Scanning light...** lets you tell EFAS what the light was, and it works out the trim that undoes the tint.

Here is how it reasons. It assumes the light is a **black-body radiator** at the colour temperature you give (the glow of a hot object, which is a good model for tungsten and a rougher one for LEDs), and that your camera's white balance was left at **daylight, 5500 K**. It works out how much red, green and blue that light adds compared with daylight, measured on a middle grey, and gives the trim that cancels it. The presets are: daylight or flash (5500 K, no correction), cool white LED panel or screen (6500 K), neutral white LED (4000 K), warm white LED (3000 K) and tungsten or halogen (3200 K). **Custom** takes any temperature from 2000 to 12000 K.

The result goes on the photo as an ordinary edit, so you can undo it and adjust it by eye. Treat it as a **starting point**: a real LED's stated colour temperature is a summary of its tint, not its spectrum, and nothing here is measured from your camera. If the same tint appears on every roll, it is probably your light, so set it once here (or capture it in a permanent flat field).
""", keywords=("color trim", "red green blue", "scanning light", "backlight", "temperature", "cast", "trim", "led", "black body", "kelvin"), module="Negative", see=("scanning-light", "colour-temperature-and-white-balance")),

    Lesson("flat-field-module", "convert", "Flat Field: correcting uneven light", "See how a reference shot becomes a correction map, what each reference option is for, and what Flat Field cannot fix.",
           r"""
No backlight is perfectly even, and no lens is either: lenses darken their corners, and light panels are usually brighter in the middle. The result is a scan that is brighter in the centre than at the edges, which then fools the conversion's measuring and leaves the corners of the finished picture too dark or off in colour. **Flat Field** corrects it by measuring the unevenness once, on a picture of *nothing*, and dividing it out of every scan.

## How it works

You give it a **reference**: a scan of the bare light, or better a scan of clear, unexposed film. EFAS makes a small, linear copy of it (no more than 256 pixels on the long side, with the display encoding undone). It filters out dust and specks on the light with a five-by-five median, blurs the map so only the slow, smooth unevenness is left and not the fine detail, and then works out, for each colour channel, a **gain** at every point: the average brightness of the whole map divided by the brightness at that point. A point that is 20% too dark gets a gain of 1.25; a hot spot 20% too bright gets 0.83. Gains are held between 0.25 and 4. That gain map is then multiplied into every scan in **linear light**, before the conversion, so it is also what the metering sees.

## Choosing the reference

**Select Reference for This Folder...** is the usual way. For colour negatives the best reference is **a scan of a clear, unexposed piece of developed film, in the same holder, with the same camera, lens, aperture and light**. It contains something a bare-light shot does not: the film's own colour at the edges and the holder's reflections. The correction is saved for the **whole folder** and applied to every photo in it, now and later, and to exports.

**Auto (Roll)** needs no reference at all. It builds the map from every frame in the folder (at least five): the light's falloff is identical in each frame, while the picture content is not, so the high-percentile level at each point across the roll estimates the light.

**Permanent (all photos)** is one flat field for your scanner's light that applies to every photo you ever open, in any folder, until you remove it. A folder with a flat field of its own uses that instead; the two never stack.

**Method** chooses how the map is smoothed. **EFAS (original)** and **NegPy** blur by 1/16 of the long side, which also flattens the steep falloff right at the borders and so leaves the edges about 13% dark (18% in the corners). **Improved** blurs by only 1/64, repeats the edge pixels outward rather than mirroring them, and keeps the falloff, leaving the edges within 1 to 3%. Switching the method rebuilds the map from the saved reference, so you do not have to pick it again. **Check Flat Field** reports how well it is working.

## What it cannot fix

Flat Field corrects the **scanner's** light. A difference that is in the picture itself, for instance a flash that lit only the middle of the frame, or the film's own border, is not in the reference, so Flat Field leaves it alone. For those see [[edge-color-module]] and [[edge-bleed-module]]. It also cannot correct a *different* light from the one the reference was shot in: if you change the aperture or the lamp, make a new reference.
""", keywords=("flat field", "vignetting", "uneven", "light", "corners", "hot spot", "reference", "gain", "dark corners", "auto roll", "permanent"), module="Flat Field", see=("recipe-flat-light", "edge-bleed-module")),

    Lesson("edge-bleed-module", "convert", "Edge Bleed: light spilling into the edges", "Understand what edge bleed is and how the four tools repair it, on the scan and on the finished picture.",
           r"""
Light does not only travel straight through the film frame. It also comes from **the clear film round the frame**, from **gaps in the holder** and from the **sprocket holes**, and some of it scatters into the camera and lifts the picture's edges. It looks like a bright band along a side or by a sprocket hole, and it makes the edges of the converted picture too bright and low in contrast.

**Flat Field cannot fix it.** Flat Field corrects light that falls off *smoothly and identically* across every frame; bleed is local, depends on what is at the border of each frame, and changes from frame to frame.

Edge Bleed has four tools. Three work **on the scan, before the conversion**; the fourth works on the finished picture.

## On the scan

**Fill holder** finds whatever lies outside the picture but is **not clear film** (the holder's dark edge, a bright hole) and paints it with the film base, so it can neither spill light inwards nor mislead the metering. It works from the edge of your crop, or with no crop from a clear film border found round the picture.

**Bleed repair** takes away the light the border scatters into the picture, in linear light. **Strength** is how much to remove. **Auto strength** estimates it from how the picture's own edge brightens towards the border. **Reach** is how far in from the edge the bleed travels.

**Edge dodge** flattens the brightness profile at each edge to the level just beyond Reach. It needs no clear border and no crop, but it cannot tell bleed from a bright thing in the scene: a window at the edge of the frame looks like bleed to it. Use it when the bleed is real and the scene's edges are plain.

## On the picture

**Border mask** lays a soft band of black, grey or white over the outer edge, to hide what the other tools could not fully repair. **Mask width** and **Mask feather** set its size and softness and **Mask colour** its colour. It can be kept **out of the metering**, so the band does not count as the darkest or lightest part of the picture.

## Working order

The fill and the repair read from the edge of your crop, so **crop to the picture first**. Then try the tools in turn: Fill holder first (it removes the cause), then Bleed repair with Auto strength, then Edge dodge if an edge is still bright, and the Border mask last as cover.

The best repair is prevention: mask off every bit of light that does not pass through the frame. A black card cut to the frame size cures most bleed at the camera. See [[scanning-flat-and-clean]].
""", keywords=("edge bleed", "light leak", "edges", "border", "holder", "sprocket", "mask", "dodge", "bright edges", "scatter", "flare"), module="Edge Bleed", see=("flat-field-module", "edge-color-module", "recipe-flat-light")),

    Lesson("film-colour-reference", "convert", "Film Colour Reference", "Compare your conversion with real photographs shot on the same film stock.",
           r"""
Converting a negative always involves judgement, because no scan comes with the answer to *what should this film's colours look like?* The **Film Colour Reference** helps you answer it. Open it from the **Extra** menu or from the Convert tab: search for a film stock, and it shows sample photographs shot on that film in a clean gallery, so you can hold your own conversion up against what the film really does.

The photographs come from **lomography.com**. That makes this one of only two places where EFAS goes online (the other is the update check). For that reason it asks permission the first time you open it, connects only while its window is open, and sends nothing about you or your photographs. **Settings > General** can switch it off entirely.

## What is in the window

On the left is a **search box** and the list of film stocks. The list is fetched once and kept for two weeks, so searching happens on your own computer and what you type is never sent anywhere; **Update the film list** fetches it again if a new stock is missing. Pick a stock and its photographs appear on the right as a gallery of thumbnails, and **Show** changes their order: *Most popular*, *Selected*, *Trending* or *Most recent*. The gallery loads a page at a time, so **Show more** brings in the next batch.

Click a thumbnail to see that photograph larger, with its title and the name of the person who took it. `Left` and `Right` (or **Previous** and **Next**) step through the gallery, and **Open on Lomography** opens the photograph's own page in your browser. Nothing is saved to your computer and nothing is edited, which is why the window states that the photos belong to their photographers and are shown only as a colour reference.

## Using it sensibly

Treat it as a **sanity check, not a target**. Lenses, scanners, labs and tastes all differ, and the photographs in a gallery have been through someone's own scanner. What it is good for is the broad questions: is this film's skin tone warm or neutral? Are its greens yellowish or blue-ish? Does it have a cool shadow or a warm one? If your skin tones are believable and your greys are grey, you are in the right region, and the rest is taste.

It is also a useful companion to the **Film** menu in the Modern conversion ([[modern-conversion-controls]]): pick the stock you shot, then check the result against the gallery for that same stock.
""", keywords=("film reference", "lomography", "gallery", "compare", "colour reference", "stock", "online"), module="Negative", see=("inversion-method",)),

    # ------------------------------------------------------------------ Frame & Clean
    Lesson("crop-and-rotate", "frame", "Crop & Rotate", "Learn how the crop is stored and used, what the ratios and guides are for, and how rotating and flipping carry a crop with them.",
           r"""
**Crop & Rotate** is the framing tool: it decides which part of the scan is the picture, and which way up it is. It is more than a cosmetic step, because everything downstream uses the crop.

## What a crop is in EFAS

A crop is a rectangle **remembered with the photo**, not a cut made in the file. Your scan is never touched. The crop is applied late in the chain, after the conversion and the tone work, and everything that measures the picture looks only inside it: the conversion's metering, the histogram, the film-type detection and the edge tools. That is why cropping off the film border *first* improves the conversion: the border stops being part of what is measured.

## The controls

**Crop** switches the crop tool on: drag a rectangle on the picture, drag its handles to adjust it, and toggle **Crop** off when you are done. **Clear Crop** removes it.

**Ratio** holds the shape while you drag: **Free**, **Original** (the frame's own shape), **1:1**, **3:2**, **4:3**, **5:4**, **6:7** (medium-format 6x7), **7:5**, **65:24** (a panoramic frame), **16:9**, **16:10** and **8.5:11**. A ratio turns to landscape or portrait to follow the direction of your drag.

**Guide** chooses the composition overlay drawn inside the crop while you work: **Thirds**, **Phi Grid**, **Diagonals**, **Golden Triangles**, **Golden Spiral**, **Armature**, **Diagonal Method**, **Grid**, or **Off**. They are aids for the eye and are never part of the picture. Thirds and the Phi Grid mark places to put the subject; the diagonal guides help to place a subject on a line.

**Rotate Left / Right** (`[` and `]`) turn the picture by quarter turns and **Flip Horizontal / Vertical** mirror it. An existing crop is **carried along** with the picture rather than cleared, so you can turn a scan upright after cropping it.

## Crop for the conversion

Crop *inside* the frame, a little in from the edge of the film, so no border, holder edge or sprocket hole is left in. Doing it before you judge the colour is the rule of thumb. Auto Crop and the other automatic tools in [[straighten-and-auto-crop]] can place the crop for you, and **Crop Roll** in the filmstrip can crop every frame of a roll (see [[whole-roll-tools]]).
""", keywords=("crop", "rotate", "flip", "ratio", "guide", "thirds", "aspect", "composition", "frame", "medium format", "golden"), module="Crop & Rotate", see=("straighten-and-auto-crop", "composition-and-cropping")),

    Lesson("straighten-and-auto-crop", "frame", "Straighten and the automatic crops", "Learn how straightening rotates and enlarges the picture, and how the Straighten Tool and Auto Crop find the frame.",
           r"""
A scan is rarely perfectly square to the camera. A slight tilt is easy to correct, but it is worth knowing what correcting it costs.

## How straightening works

The **Angle** slider rotates the picture about its centre by up to 45 degrees either way; a positive angle turns it clockwise. Rotating a rectangle leaves blank wedges at the corners, so EFAS **enlarges** the picture by exactly as much as is needed for the rotated picture to cover the frame again. At 3 degrees on an ordinary 3:2 frame that enlargement is about 8%. The frame keeps its size, which means a crop you have already made, and a quarter turn you make later, are unaffected. The price is small: a thin strip of the picture's edge is gone, and the pixels are interpolated once. That is another reason to get the camera square when you scan.

## The ways to set the angle

The **Angle** slider is manual: turn it until a horizon or a straight edge is level. Double-click to reset.

The **Straighten Tool** is quicker and more accurate. Click **two points** along something that should be level (a horizon, the film's own edge) or upright (a wall, a door frame), and the picture is turned so that line is level or plumb. `Esc` cancels the first point.

**Four-Corner Straighten** is for a scan with perspective as well as tilt: click the **four corners** of the photograph, and the Angle and the Keystone are set so those corners become a true rectangle, and the picture is cropped, all as one undoable step.

**Auto Crop & Straighten** (`Ctrl+Shift+A`) looks for the picture inside the scan, with its border, and sets the crop and angle itself. **Gradient Border Crop & Rotate** (`Ctrl+Shift+G`) finds the frame by following the gradient where the picture meets its border, which suits frames with a soft or uneven edge.

## Checking the automatic ones

Automatic tools are fast and usually good; they can be fooled by a frame whose edge is as dark as the border, or a picture with a very bright edge. Run them across a roll, then step through the filmstrip and adjust the few that are slightly off. Because the metering reads the crop ([[metering]]), a crop that is a little too loose and includes border will show up as a conversion that looks off.
""", keywords=("straighten", "level", "horizon", "angle", "auto crop", "four corner", "rotate", "tilt", "gradient crop", "fine rotation"), module="Crop & Rotate", see=("crop-and-rotate", "distortion-and-keystone")),

    Lesson("distortion-and-keystone", "frame", "Distortion and keystone", "Understand the two geometric corrections: bending curved lines straight, and stopping parallel lines from converging.",
           r"""
Two different geometric faults can show up in a scan, and the two sliders in **Crop & Rotate** fix them separately.

## Distortion Correction

Lenses bend straight lines near the edge of the frame. With **barrel** distortion, lines bow outwards like the side of a barrel; with **pincushion**, they bow inwards. **Distortion Correction** applies a **radial** correction: it moves each point along the line out from the centre of the picture by an amount that grows with its distance from the centre. **Positive** values correct barrel distortion and **negative** values correct pincushion. The slider's range is small by design, since real lenses bend lines only slightly, and after correcting, the picture is scaled up just enough that it still fills the frame with no empty or smeared border.

To set it, look for something that should be straight and near an edge. The film rebate, a ruler edge, or a building line works. Increase the correction until that line is straight.

## Keystone

**Keystone** is a different fault: **parallel lines that converge**. If the camera is tilted up at a building, its sides lean towards each other at the top. When *scanning*, it happens if the camera is not parallel to the film: then the whole frame is a trapezoid. **Vertical** widens the top of the picture (positive) or the bottom (negative); **Horizontal** does the same for the left and right. The correction is a perspective warp: the four corners of a smaller quadrilateral (inset by up to 30% of the frame at the slider's limit) are stretched back out to the corners of the picture, and the result is cut from inside the frame so there are no empty corners.

**Auto Keystone** looks for long straight lines in the picture and suggests values. It does well on architecture and film frames with a clear edge, and less well on scenes without straight lines.

## Using them

Both corrections resample the picture, softening it a little, so use as much as you need and no more. If a scan needs a lot of keystone, the camera was not square to the film, and re-shooting it parallel will give a sharper result than any correction: see [[scanning-setup]]. When you have several faults at once, correct them in this order: **angle first**, then keystone, then distortion.
""", keywords=("distortion", "barrel", "pincushion", "keystone", "perspective", "lens", "vertical", "lean", "converge", "straight lines"), module="Crop & Rotate", see=("straighten-and-auto-crop", "scanning-setup")),

    Lesson("dust-auto", "frame", "Dust & Scratches: how automatic removal works", "See how EFAS tells dust from detail, what Threshold and Size really do, and how the repair is made.",
           r"""
Dust, hairs and scratches show up in a scan as bright or dark marks that are not in the picture. **Auto Dust Removal** finds them and repairs them, and understanding how it *decides* is the way to tune it.

## How a mark is found

Detection works in **linear light** on a brightness-only version of the scan, so colour does not confuse it. For every spot it asks how much that spot differs from its surroundings **compared with how much the area normally varies**, a robust measure of the local noise level. A real speck stands out by many times that; grain does not. Areas that have **texture** (fine detail) raise the bar automatically, so a patch of foliage or a face is far less likely to be treated as dust than a clean sky. The marked area is then grown slightly so the edge of the mark is repaired too. Long, thin marks are classed as **hairs** and short ones as **specks**.

## The controls

**Threshold** sets how far above the noise a spot must stand out to be marked. Moving the slider towards *loose* lets in marks only about three times the local noise; the default is about nine times; moving towards *tight* demands nearly fifty. In other words, **higher is more conservative**: fewer marks, less risk of repairing real detail. If dust is being missed, lower it. If grain or fine detail is being repaired, raise it.

**Size** is the largest a speck is allowed to be (a small whole number, from 3 to 8). A bigger value catches larger blobs but makes it easier for a real feature, like a bright button, to be taken as a speck.

**Show Detections** paints what detection finds on the picture (a view only), **even while removal is off**: **green** for specks, **magenta** for hairs, **amber** for heals you made by hand, **blue** for clone strokes. It is the way to tune Threshold by eye: zoom to 100% and lower the Threshold until the real dust is marked and the grain is not.

**Delete Repair**: when automatic detection repairs something real (a star, a highlight in an eye), pick this tool and click the mark. Only that one is left alone. **Reset Deleted** brings all the deleted marks back.

## How the repair is made

Each marked area is filled from the clean pixels around it, not blurred. EFAS fills at several scales (a wide, a medium and a fine one) weighting each clean neighbour by how far it is from the mark and how much it is trusted, and then **borrows some of the surrounding grain** so the repaired spot has film texture and not a suspiciously smooth patch. Hairs are repaired with an inpainting pass instead, which suits a thin line better.

Automatic settings apply when you stop moving a slider, because the work is heavy. The repairs are made on the full-resolution scan and kept while you work, so a change you make to an unrelated slider does not repeat them.
""", keywords=("dust", "specks", "hairs", "auto", "threshold", "size", "detections", "repair", "clean", "inpaint", "noise", "delete repair"), module="Dust & Scratches", see=("dust-manual", "ai-dust")),

    Lesson("dust-manual", "frame", "Dust & Scratches: healing by hand", "Understand each manual tool, how you tell it where the mark is, and which to use for which kind of mark.",
           r"""
Automatic removal gets most of the marks. The tools under **Manual Heal** are for the rest, and each suits a different kind of mark. They all share one repair method, the same one the automatic tool uses: fill from the clean film around the mark and borrow a little of its grain, so you are not simply smudging. What differs between the tools is *how you tell EFAS where the mark is*.

## Pointing at the mark

**Heal Tool** is a brush. Paint over a defect and everything under the brush is repaired from the film around it. There is no detection involved, so you have to cover the whole mark. **Brush Size** is the diameter, shown by the on-screen cursor.

**Smart Heal** needs only a click. Click a speck or hair and it is found by its shape and healed, with no brush to size. It searches a generous fixed area round your click, and only rewrites what stands out from the film. **Smart Sens.** sets how readily a click commits: higher takes the click as a defect more eagerly; lower wants it to be clearer.

**Scratch Tool** heals a scratch or hair at any angle: click points along it, then double-click or press Enter to finish (Esc cancels, Backspace removes the last point). **Curved Scratch** does the same but draws a smooth curve through your points, for a scratch that bends.

**Smart Transport Line Selection** is for the long scratches film transport leaves along a roll: click once on one, and the whole line is found, traced and repaired. It only follows marks that run close to horizontal in the original scan; **Line Sens.** sets how readily it follows a line (lower repairs a wider band). If it cannot find one, **Manual Transport Line** has you click two points on the scratch, as far apart as you can, and the straight line through them is carried to both edges of the frame and repaired, as wide as the Brush Size. It goes exactly where you click.

## Copying instead of healing

**Clone** copies film from another area over a defect, for the cases where there is real detail under the mark that healing would smooth away: a face, lettering, a regular texture. Alt-click the area to copy from (or press **Set Source** and click it), then paint over the defect; the source follows your brush at the same distance. **Match Tone** keeps the source's texture but takes the brightness and colour of where it lands, so the patch does not show as lighter or darker. **Strength** is how much of the copy replaces what is there (1 replaces it fully), and **Feather** is the fade width at the brush edge as a share of its radius (0 is a hard edge).

## The Repair setting, and undoing

**Repair** chooses how a marked area is filled. **Auto** picks by each mark's shape. **Smooth fill** suits small specks. **Structure inpaint** follows a line through a textured or curved background, which suits a scratch crossing detail. **Undo Last** removes the last manual repair and **Clear All** removes every manual repair on the photo.

## Working method

Zoom to 100%: this is pixel-level work. Heal small and often: many small repairs look natural and one big smear looks like a patch. Use the scratch tools along a scratch instead of painting its length, which is both quicker and more accurate. Where a heal looks smoother than the grain around it, switch to Clone from a nearby area that has the same texture.
""", keywords=("heal", "clone", "scratch", "spot", "retouch", "brush", "transport line", "manual", "smart heal", "strength", "feather", "inpaint", "repair"), module="Dust & Scratches", see=("dust-auto", "ai-dust")),

    Lesson("ai-dust", "frame", "AI Dust Detection", "See how the neural network decides what is a defect, what Threshold and Grow change, and when it beats the ordinary detector.",
           r"""
The ordinary dust detector works on statistics: a speck is something that stands out from its surroundings by more than the noise explains. That is excellent for small dust on smooth areas, but a statistical rule struggles with marks that look like *picture*: a fine scratch through textured foliage, a hair lying across a detailed area. **AI Dust Detection** takes a different route.

## How it works

A small neural network, **FilmDefectNet**, has been trained to recognise what film defects look like: dust, hairs and scratches, bright and dark. EFAS runs it over the whole scan, once, at **full resolution**, which takes a few seconds per megapixel and happens in the background; the result is a map of *how likely each pixel is to belong to a defect*, and it is remembered with the photo, so you do not wait again. The same repair as the other dust tools then fills **only the pixels the network marked**, so grain and detail everywhere else are left exactly as they were.

## The controls

**AI Dust Removal** switches the repair on (and starts the analysis the first time). **Cancel Analysis** stops it.

**Threshold** turns the probability map into a decision. A lower threshold marks fainter, less certain defects, at the risk of taking grain for dust; a higher one is more cautious and only marks what the network is sure of. The default is 0.3.

**Grow** widens every marked area by that many pixels so the *edge* of a defect, which is usually softer than its middle, is repaired as well. A small mark with a fuzzy edge leaves a faint ring if it is repaired with too little grow.

To see what the network marked, turn on **Show Detections** in the Dust & Scratches module: AI marks are shown in amber.

## When to use it

It shines on scans with many scratches or fine hairs that a threshold cannot separate from grain without also removing grain. On a clean scan with a few specks, the ordinary **Auto Dust Removal** is faster and just as good. The two work together, and the manual tools sit on top of both, so you can use the AI to get most of the way and finish by hand. The analysis is cached (its size is shown, and can be cleared, under **Settings > Storage**).
""", keywords=("ai", "neural network", "dust", "scratches", "detection", "filmdefectnet", "machine learning", "probability"), module="AI Dust Detection", see=("dust-auto", "dust-manual")),

    Lesson("error-marking", "frame", "Error marking", "Use error marks to note faults that cannot be repaired, and find them again from the Workbench.",
           r"""
Not every fault can be fixed in software. A deep scratch that took the picture with it, a light leak that washed out a corner, a fingerprint on the film: some of these need a re-scan, or simply to be remembered. **Error marking** is a way to *note* faults, not repair them.

## How it works

Choose a kind of fault, then drag a box round it on the picture. Each kind has its own colour and a small tag with its name: **scratches** are red, **watermarks** yellow and **transport lines** dark navy, and there are also **Newton rings**, **light leaks**, **dust and hairs**, **fingerprints** and **unknown**. Right-click a mark to change what it is, or to take it off. **Clear all marks** removes them from the photo.

Marks are **notes kept with the photo**. They are stored relative to the picture, so they stay on the fault if you crop, rotate or straighten afterwards, and they are **never part of an exported picture**. Show or hide them on screen with **Shift+E** or **View > Error Marks**.

## Finding photos by fault

The marks feed the Workbench search. Search `error:yes` for every photo with any mark, `error:none` for those without, or `error:scratch` for one kind, and put a minus in front (`-error:scratch`) to leave a kind out. You can also choose **Errors** under Rating & Status, or save the search as a **smart collection**. That turns the marks into a to-do list: a collection of "photos with light leaks" is exactly the list to take back to the scanner.

## Why the kinds matter

Each kind points at a different cause, so marking them by kind tells you where to look. Fingerprints and dust say the film needs cleaning before another scan. **Newton rings**, the rainbow ripples where film touches glass, say the holder or the glass is at fault. **Transport lines** run along the scan direction and belong to the scanner, not the film. **Light leaks** happened in the camera or at development, so no re-scan will remove them. A roll that keeps collecting one kind of mark is telling you something about the process.

NOTE: Error marking records, it does not remove. Use [[dust-auto]], [[dust-manual]] and [[ai-dust]] to repair what can be repaired.
""", keywords=("error marks", "faults", "notes", "scratches", "light leak", "fingerprint", "newton rings", "mark", "tag", "annotate"), module="Error marking", see=("dust-and-scratches-origins", "workbench-lesson")),
]
