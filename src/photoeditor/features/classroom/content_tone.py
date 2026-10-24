"""Tool guides for the Tone, Color and Detail tabs: what each tool does, how it works inside, what each control does to the picture, and how to use it well."""
from .logic import Lesson, Section

SECTIONS = [
    Section("tone", "Tone: brightness and contrast", "Exposure, contrast, shadows and highlights, the tone curve and the print response, each explained from the inside."),
    Section("color", "Color", "White balance, saturation, the Color Mixer, toning, the lab look and the edge colour: how colour is changed, and why it is done the way it is."),
    Section("detail", "Detail", "Noise, local contrast and sharpening: what they do to the pixels and how to use them without spoiling the picture."),
]

LESSONS = [
    # ------------------------------------------------------------------ Tone
    Lesson("tone-overview", "tone", "Tone: how the tools relate", "See where each tone tool sits in the chain, and how to choose between them.",
           r"""
**Tone** is how light or dark things are, and how the lights and darks relate to each other. The Tone tab holds five tools, and they differ in *how precisely* they let you reshape the brightness. At one end, **Exposure** moves everything together. **Contrast** pushes the lights and darks apart or together around the middle. **Shadows & Highlights** lifts or lowers one end of the range and leaves the other alone. The **Tone Curve** lets you draw any reshaping you like, for the whole picture or for one colour. **Print Response** shapes the way the shadows and highlights fade into black and white, as a print's characteristic curve does.

## Where they sit in the chain

The order in which the work is done matters, so here it is. First the conversion and the colour trims and the Color module's Temperature and Tint. Then **Exposure**, then **Contrast**, then **Print Response**. After that come saturation and **Shadows & Highlights** (and the Detail tab's denoise and local contrast). Then the **Tone Curve** (the master curve, then the red, green and blue curves), and the Lab Look. The colour work in the Color Mixer comes after all of that, and sharpening comes near the end.

That order gives each tool a job. Exposure and Contrast are the broad strokes, done early on the raw tones. The Tone Curve is a finishing hand, so it sees the picture *after* the others and shapes the final result. Because most of these are per-channel lookups, changing them is instant even on a large photograph.

## Choosing between them

If the whole picture is too dark or light, use **Exposure**. If it is flat or too harsh, use **Contrast**. If one end is the trouble (blocked shadows, or bright areas that have lost detail), use **Shadows & Highlights**, which can open one end without disturbing the other. When you want a specific shape (a lifted black, a gentle S, a cool tint in the shadows only), draw it in the **Tone Curve**. When you want the *character* of the roll-off (soft and filmic, or hard and graphic), use **Print Response**.

Work with the histogram in view: it shows where the tones are, and the clipped-share triangles tell you the moment a change starts losing the ends. (The Tone tab also holds a **Masking** placeholder for selective editing, which is not built yet.)
""", keywords=("tone", "brightness", "contrast", "overview", "tab", "light", "dark", "order", "chain"), see=("exposure-module", "order-of-operations", "histogram-panel")),

    Lesson("exposure-module", "tone", "Exposure", "Understand exactly what the Exposure slider does to the pixels, why it differs from a camera's stop, and how to use the test strip.",
           r"""
**Exposure** makes the whole picture lighter or darker, and it is the simplest tool in the program. It also has a quirk worth understanding, because the word 'stop' means something slightly different here from what it means on a camera.

## How it works

The slider is in **EV**, with a range of two EV either way. Each EV **multiplies every pixel value by 2 to the power of the setting**: +1 doubles the numbers, -1 halves them, +0.5 multiplies by about 1.41. The result is clipped at the top, so anything pushed past white stays white. The multiplication is done directly on the **display-encoded values**, the numbers you actually see, and not on the amount of light. That is a simplification, and the consequence is that one EFAS stop is a **stronger** change than a camera's stop: a real stop doubles the light, which is only about a 1.4 times change in the encoded value. Treat the slider's numbers as a convenient scale, not as camera stops.

Two things follow from multiplying. Pure black stays pure black, because zero times anything is zero: Exposure cannot lift a blocked shadow. And pushing up drives the brightest tones into white quickly, since they have the most headroom to lose: raise a bright sky by a stop and it clips.

## Using it

Treat it as the **first and broad** adjustment: get the middle of the picture to the brightness you want, a small move of 0.2 to 0.5 usually being enough. Large moves (more than about 1.5) reveal the limits of the scan: the shadows get noisy when lifted and the highlights clip when pushed. If you need that much, the scan itself was probably under- or over-exposed (see [[scanning-exposure]]), and a better scan is worth more than any slider.

When the picture needs *the middle* lighter but the ends left alone, Exposure is the wrong tool; use the Tone Curve. When only the shadows or only the highlights are the problem, use [[shadows-highlights-module]].

## Test Strip and Ring-Around

Choosing exposure by eye from a single preview is hard, so the Tone tab can show you alternatives. **Test Strip** (`Shift+T`) prints the photo at **25 exposure and contrast steps** side by side, like the test strips of a darkroom, and you pick the one that looks right. **Ring-Around** (`Shift+F`) does the same for colour: it steps the colour balance in a 5 by 5 mosaic, so you can pick the tile where a cast disappears. See [[proofing-tools]].

NOTE: Exposure works with the conversion's own black and white points. Under the NegPy Conversion, **Print density** in the Convert tab shifts the print darker or lighter in a more film-like way, so use Exposure for a broad nudge and Print density for tuning the print itself.
""", keywords=("exposure", "brightness", "ev", "stops", "lighter", "darker", "test strip", "ring-around", "multiply", "clip"), module="Exposure", see=("stops-and-ev", "proofing-tools")),

    Lesson("contrast-module", "tone", "Contrast", "Learn what the Contrast slider does to the tones, why the middle stays put and the ends roll off, and how it differs from Grade.",
           r"""
**Contrast** is the distance between the lights and the darks. Raise it and the picture gets punchier: darks go darker, lights go lighter. Lower it and it flattens towards grey. It is one slider, but it is built carefully, and knowing how explains why it behaves well.

## How it works

The slider runs from -1 to +1. Each pixel's value, scaled to the range 0 to 1, is blended between **itself** and a smooth S-shaped version of itself (the smoothstep curve, which is steepest in the middle and flat at both ends). At 0 you get the picture unchanged; at +1 you get the full S; at -1 the curve is run *backwards*, which flattens the middle of the range. Three things follow from that shape:

- the **midpoint does not move**: a mid grey stays mid grey, so contrast does not change the overall brightness;
- the **ends roll off** instead of clipping hard, because the S flattens near black and white, so even a strong contrast setting keeps a gradual shadow and highlight;
- it acts on **each colour channel separately**, so strongly coloured areas gain saturation as well as contrast, as they do in a darkroom print.

Contrast is a pointwise change, so it costs nothing per pixel: it folds into the same lookup table as Exposure and the Tone Curve.

## Using it

Film scans often start a little **flat**, because the conversion has to squeeze a wide range into a screen's range. A small positive contrast usually helps. If you find yourself pushing it far, check whether the real problem is the conversion's range ([[white-black-points]] in Original, **Grade** in NegPy Conversion) or an end that needs opening up ([[shadows-highlights-module]]).

Too much contrast clips the ends, even with the roll-off: watch the histogram's corner triangles. For finer control of particular tones use the [[tone-curve-module]], which can bend the middle and the ends independently.

NOTE: In the NegPy Conversion **Grade** also sets contrast, but as part of the conversion itself, before the picture reaches this slider. Use Grade for the broad contrast of the print and this slider for taste afterwards.
""", keywords=("contrast", "punch", "flat", "soft", "pop", "s-curve", "smoothstep", "midpoint"), module="Contrast", see=("dynamic-range-contrast", "tone-curve-module")),

    Lesson("shadows-highlights-module", "tone", "Shadows & Highlights", "See how Shadows & Highlights opens up one end of the range by gain, why it keeps colour, and what its limits are.",
           r"""
Sometimes only one end of the picture is wrong: a dark foreground you want to see into, or a sky that has gone too bright. Moving Exposure or Contrast would fix one end and spoil the other. **Shadows & Highlights** is built for exactly this: each slider changes its own end and leaves the midtones close to where they were.

## How it works

An older way to do this adds the same number to red, green and blue for every pixel of a given brightness. That lifts black, so nothing is black any more, and it drains colour. This tool works by **gain** instead. It first builds a brightness curve that bends only the shadow end or only the highlight end, with black held at black and white held at white, and which never runs backwards, so no tones swap places. Then it multiplies each pixel by **the new brightness divided by the old**, the same factor on red, green and blue. Because all three channels are scaled together, a pixel keeps its **hue and saturation**: a lifted shadow keeps its colour instead of turning grey. And the factor is capped so that no channel is pushed past white, which stops a bright, saturated colour from shifting hue as it clips.

The reach is bounded: at full strength the **Shadows** curve can lift the darkest tones by about 1.2 stops, tapering to almost nothing by the midtones; the **Highlights** curve can change the brightest tones by about 0.65 of a stop, with its biggest effect three quarters of the way to white.

## The controls

**Shadows** positive brightens the darkest tones; negative deepens them. **Highlights** positive brightens the brightest tones; negative darkens them. The sign always means *brighter* or *darker*, so a darker sky is a negative Highlights value. Double-click either slider to reset it.

## Using it

The shadows slider is the quickest way to open up a dark foreground or a backlit face. The highlights slider darkens a bright sky until its detail returns. Using both flattens a contrasty scene, and it is best done **gently**: a little of each often looks more natural than a lot of one.

If you find yourself pushing both sliders to their ends, the cause is usually upstream: the scan clipped, or the negative simply holds more range than a screen can show ([[dynamic-range-contrast]]). Remember too that lifted shadows lift their **noise**: a dark area opened up by a stop or more shows grain that was invisible before, and **Chroma Denoise** can help ([[chroma-denoise-module]]).
""", keywords=("shadows", "highlights", "lift", "recover", "dark", "bright", "fill light", "gain", "tone"), module="Shadows & Highlights", see=("clipping", "tone-curve-module")),

    Lesson("tone-curve-module", "tone", "The Tone Curve", "Learn how to read the curve, how the four curves combine, and what each button and picker does.",
           r"""
The **Tone Curve** is the most flexible tone tool, and the way to get any precise shape you can imagine. It is a graph, and reading it is the whole skill.

## Reading the graph

The line along the bottom is the brightness going **in**, from black on the left to white on the right. The line up the side is the brightness coming **out**. A straight diagonal changes nothing: what goes in comes out. Anywhere you bend the line *above* the diagonal, that range of tones comes out **brighter**; where it dips *below*, they come out **darker**. Where the line is steep, nearby tones are pulled further apart, so **contrast** increases; where it is flat, tones are squeezed together and contrast falls. That is why an **S-shaped** curve (low in the shadows, high in the highlights, steep through the middle) adds contrast, and why lifting the bottom-left end of the curve produces a **faded, matte black**.

## The four curves

There are four curves, each with its own tab. **RGB** changes the whole picture. **Red**, **Green** and **Blue** each change one channel on its own, and are applied **after** the RGB curve. A colour curve is how you change colour *by brightness*: lift the blue curve in the shadows and the dark tones turn cool; pull the red down in the highlights and the bright tones turn cyan. This is something the Color tab's sliders cannot do, and it is the classic way to give shadows and highlights different colours.

## Working the curve

**Click** an empty spot on the line to add a point; **drag** a point to move it; **double-click** a point to remove it (the two end points cannot be removed). The curve is a smooth spline through your points, kept between 0 and 255, so a few points make a gentle shape and many points make a tight one. The **In** and **Out** boxes show the selected point's values and let you type exact numbers.

**Black**, **Grey** and **White** are point pickers, each waiting for one click on the picture. **Black** and **White** set every channel's end point from the spot you click, so that spot becomes pure black or pure white. **Grey** makes the spot **neutral**, correcting a cast through the middle tones. They are the same idea as the white and black dropper in the Convert tab, but acting on the finished picture.

**Auto** sets each channel's black and white points from the picture itself, using its 0.5th and 99.5th percentiles, so the histogram fills the range. **Reset** returns the curve you are looking at to a straight line; **Reset All** does it for all four.

## Using it

A small smooth S is the classic way to add 'pop', and it is gentler than Contrast because you choose where the steep part is. A lifted black point gives a filmic fade. Make **few, gentle** moves: sharp kinks in a curve show up as strange tones in smooth gradients, such as a sky. For a curve that is a deliberate look, save it as a preset ([[presets-lesson]]).
""", keywords=("tone curve", "curve", "s-curve", "rgb", "levels", "points", "channel", "black point", "grey point", "spline", "fade"), module="Tone Curve", see=("white-black-points", "contrast-module")),

    Lesson("print-response-module", "tone", "Print Response", "Understand Snap, Toe and Shoulder as the shape of a print's characteristic curve, and how they differ from the Tone Curve.",
           r"""
When a photographic print is made, the paper does not turn light into brightness in a straight line. Its response has a distinctive S-shape: the shadows fade slowly into the paper's black (the **toe**), the middle is steeper, and the highlights roll off gently into the paper's white (the **shoulder**). That curve, named after Hurter and Driffield, is a large part of why prints look the way they do. **Print Response** lets you shape it.

## How it works

The module does not work on brightness directly. It converts the tones to **density**, the logarithm of how much light is blocked, because a paper's response is naturally described there. The three controls then change the density:

- **Snap** steepens or flattens the **midtones** around mid grey (an 18% grey), with the two ends left to roll off on their own;
- **Toe** takes density away at the high-density (shadow) end, which compresses the shadows;
- **Shoulder** adds density at the low-density (highlight) end, which compresses the highlights.

Each is zero when its slider is zero, so neutral settings change nothing, bit for bit. The curve is kept rising, so no tones ever swap order, as long as the sliders stay in their ranges. It is folded into the per-channel lookup table, so it costs nothing per pixel. The small graph in the module draws the result; the diagonal is *no change*.

## The controls

**Snap** (-0.5 to +0.5): positive makes the midtones punchier, negative gentler, with black and white left where they are.

**Toe** (-1 to +1): positive gives a gentler, film-like **fade** into the shadows, which keeps shadow detail visible longer; negative sends the shadows to black faster. **Toe Width** says how far into the picture that roll-off reaches.

**Shoulder** (-1 to +1): positive protects highlight detail by easing it into white; negative pushes the highlights harder towards white. **Shoulder Width** sets its reach.

## Using it, and how it differs from the Tone Curve

The **Tone Curve** lets you place points anywhere; Print Response gives you three controls tied to the *physics of a print*, so its results look photographic with little effort. It is the better tool for the **character** of the roll-off: soft and filmic, or hard and graphic. Start by raising **Shoulder** if the highlights look harsh, **Toe** if the blacks look crushed, and use **Snap** for overall punch. Under the NegPy Conversion there are also **Paper toe** and **Paper shoulder** in the Convert tab, which do something similar inside the conversion; use those to set the paper, and this module to fine-tune the picture ([[modern-conversion-controls]]).
""", keywords=("print response", "toe", "shoulder", "snap", "roll off", "filmic", "characteristic curve", "hurter driffield", "density", "paper"), module="Print Response", see=("modern-conversion-controls", "tone-curve-module")),

    # ------------------------------------------------------------------ Color
    Lesson("color-overview", "color", "Color: correcting, then styling", "Understand the two jobs colour tools do, and where each tool sits in the chain.",
           r"""
Colour work has two quite different jobs, and mixing them up is the commonest cause of muddy results. **Correcting** is making colours *accurate*: greys that are grey, skin that is skin-coloured, a white shirt that is white. **Styling** is making them *beautiful*: richer greens, a warmer glow, a particular film look. Correct first. Styling on top of a cast just fights the cast.

## The tools

For **correcting**: the **Color** module has Temperature and Tint, the two directions of white balance, and a Saturation slider. **Edge Color** corrects a colour cast that grows towards the edges. In the Convert tab, the colour trims and the film base do the first, broad correction.

For **styling**: the **Color Mixer** changes one range of colour at a time and adds Vibrance. **Color Toning** tints the shadows, midtones and highlights. **Lab Look** adds the character of a lab's scanner. The Tone Curve's red, green and blue curves are also a styling tool.

## Where colour is changed in the chain

Temperature and Tint come early, right after the conversion, so they correct the picture before Exposure and Contrast shape it. Saturation comes after those, with Shadows & Highlights. The Color Mixer, Vibrance, the scanner colour response and Color Toning come **last**, after the tone curve, working on the finished tones. The order matters because the later colour tools work on a picture whose brightness is already settled.

## A note on how colour is changed

The simple tools (Temperature, Tint, Saturation) work directly on red, green and blue, which is quick but crude: strong moves shift lightness and hue as a side effect. The newer ones (Color Mixer, Vibrance, toning and the scanner response) work in **OKLCH**, a colour model designed so that equal steps look equal. In it, changing a colour's saturation does not drag its lightness or hue along with it, which is why the mixer can deepen a blue sky without turning it purple.
""", keywords=("colour", "color", "overview", "tab", "correct", "grade", "white balance", "oklch", "styling"), see=("color-module", "recipe-colour-cast")),

    Lesson("color-module", "color", "Color: Temperature, Tint and Saturation", "Understand what each of the three sliders does to the pixels, and why Temperature and Tint are not kelvin.",
           r"""
The **Color** module holds the three simplest colour controls: the two directions of white balance, and saturation.

## Temperature and Tint

These correct an overall colour cast. **Temperature** moves the picture between **cool** (blue) and **warm** (yellow-orange): positive warms, negative cools. **Tint** moves it between **green** and **magenta**: positive goes towards magenta, negative towards green. Between them they cover almost every cast: a picture that looks too yellow wants a lower temperature; one that looks too green wants a positive tint.

The method is a **simple per-channel offset**, not a physical kelvin model. At the end of the slider a unit of temperature adds about 50 levels (out of 255) of red and takes 50 away from blue; a unit of tint takes 50 off green and adds 25 to both red and blue. That means the sliders are **not** in kelvin: do not expect +1 to equal a particular colour temperature. It also means the offset is the same for every pixel, so it lifts or lowers the whole range, including the blacks, slightly. It is applied **early**, straight after the conversion, before Exposure and Contrast shape the picture.

For a negative, the conversion has already balanced the channels, and the Convert tab's **Colour trim** ([[colour-trim-and-scanning-light]]) offers a similar correction at 64 levels per unit. Use whichever is nearer to hand; use Temperature and Tint for taste and the trim for the base correction.

## Saturation

**Saturation** runs from **-1** (greyscale) through 0 (unchanged) to **+1** (colour twice as far from grey). Each pixel is compared with its own **luma grey**, the brightness it would have as a grey, using the usual weights (0.299 red, 0.587 green, 0.114 blue), and its colour is pushed away from, or pulled towards, that grey. It is applied after Exposure and Contrast, with Shadows & Highlights.

Because it works on red, green and blue directly, a strong push on a vivid colour can drive one channel against its limit while the others keep going, which changes the colour's hue as well as its intensity (an orange turns slightly yellow, a red slightly orange). It also treats every colour alike, including skin and including colours that are already vivid. **Vibrance** and the **Color Mixer** are gentler for that reason ([[color-mixer-module]]).

## A reliable way to correct a cast

Find something that *should* be neutral: a grey road, white clothing, an overcast sky. Adjust **Temperature** until it stops looking warm or cool, then **Tint** until it stops looking green or magenta. The **Ring-Around** (`Shift+F`) shows a 5 by 5 mosaic of balance changes, so you can see which direction removes the cast instead of guessing. Add saturation last, and only as much as the picture needs.
""", keywords=("saturation", "temperature", "tint", "white balance", "cast", "warm", "cool", "colour balance", "kelvin", "grey"), module="Color", see=("colour-temperature-and-white-balance", "recipe-colour-cast")),

    Lesson("color-mixer-module", "color", "Color Mixer and Vibrance", "See how the mixer separates colours into eight ranges, why it works in OKLCH, and how Vibrance protects skin.",
           r"""
The **Color Mixer** answers a question the simple colour sliders cannot: how do I change *only the blues*, or only the greens? It also holds **Vibrance**, a smarter way to add colour.

## How it works

Every pixel is converted into **OKLCH**: **L** is its lightness, **C** its chroma (how colourful it is) and **h** its hue (which colour). It is a model built so that equal steps look equal to the eye, and that is the reason to use it. When saturation is changed in RGB or HSV, lightness and hue wander as well (a more saturated blue also gets darker). Here, a change to C alone *is* a change to colourfulness alone.

The mixer has **eight colour ranges**, centred on hues of **red 29 degrees, orange 55, yellow 100, green 145, aqua 195, blue 262, purple 305 and magenta 345** (these are OKLCH hues, not the same wheel as in other programs). Each range has a smooth window 60 degrees either side of its centre, shaped like a raised cosine. The windows are normalised so they always add up to one, so every hue belongs to its neighbouring ranges in proportion, with no gaps and no double counting. The windows also fade out for **near-greys**: below a small chroma a pixel is untouched, so a grey can never pick up a colour. A pixel's change is the sum of every range's change weighted by how much the pixel belongs to that range.

After the change, colours that fall outside what a screen can show are brought back by **reducing their chroma**, not by clipping channels (which would shift hue).

## The controls

Pick a range, and move its three sliders. **Hue** turns the colour along the wheel, by up to 30 degrees at the ends of the slider (a sky a little more cyan, foliage a little more yellow). **Saturation** scales the chroma, so -1 removes the colour from that range and +1 doubles it. **Lightness** moves the brightness of that range by up to about 0.12 on the OKLab lightness scale, which deepens or lightens it. A **dot** by a swatch means that range has been changed. Double-click a slider to reset it.

## Vibrance

**Vibrance** raises the colour of the **muted** parts of the picture more than the vivid ones: a pixel that is already strongly coloured barely moves, a pale one moves a lot. It also **protects skin**: around the skin hues of roughly 30 to 75 degrees the effect is reduced by up to 60%, and greys are left alone. Negative values mute instead. It is the safe way to add colour to a pale scan, where plain Saturation would push skin tones to orange.

## Using it

Make **small** moves: a few hundredths on a slider is usually enough, and strong changes in a single range show as a hard edge where the range ends in a smooth gradient. To darken a blue sky, pick **blue** and lower its Lightness a little, then raise its Saturation just enough to keep it rich. To rescue a green that looks too yellow, move **green's** Hue towards aqua. The mixer works late in the chain, on the finished tones, so make tone and white balance decisions first. See [[color-toning-module]] for tinting by brightness instead of by colour.
""", keywords=("color mixer", "hsl", "vibrance", "hue", "saturation", "lightness", "oklch", "skin tones", "sky", "ranges", "blue sky", "greens"), module="Color Mixer", see=("colour-basics", "color-toning-module")),

    Lesson("color-toning-module", "color", "Color Toning", "Learn how split toning tints the shadows, midtones and highlights separately, and how to keep it subtle.",
           r"""
In a darkroom, **toning** a print soaks it in a chemical that tints it: a sepia bath turns a black-and-white print warm brown. **Split toning** goes further and tints the dark and light parts *differently*: say, cool blue in the shadows and warm yellow in the highlights. **Color Toning** does this for a picture, with three regions instead of two.

## How it works

The picture's tones are divided into **shadows**, **midtones** and **highlights** by smooth, overlapping weights based on lightness, so there are no hard boundaries: a tone partly belongs to two regions at once. For each region you choose a **Hue** and a **Strength**. The tint is added to the picture's colour in OKLab (the same perceptual space the Color Mixer uses) as a shift towards that hue, scaled by the region's strength, by how much each pixel belongs to the region, and by a maximum chroma of 0.08. Because it is added to the colour components only, **the lightness does not change**: toning changes colour, never brightness.

Toning is applied **last** in the colour chain, after the Color Mixer and the Lab Look's scanner colour, so it sits on top of them.

## The controls

**Hue** (in degrees round the colour wheel) picks the tint. The swatch shows it: 0 is a red-magenta, 90 a yellow, 180 a cyan-green and 270 a blue. **Strength** (0 to 1) is how much. A region whose strength is **zero is left alone**, whatever its hue is set to. Each of the three regions, **Shadows**, **Midtones** and **Highlights**, has its own pair.

## Classic looks

A **warm highlight and a cool shadow** (an orange-yellow in the highlights, teal or blue in the shadows) gives the much-copied cinematic look, and it works because warm and cool are opposites that both read as natural. A **single warm hue at low strength in all three** regions gives a sepia-style tone. Cooling the **shadows only** is a clean, modern touch.

## Using it well

Keep the strengths low, from about 0.05 to 0.2: a little toning is atmosphere, but a lot makes the picture look tinted rather than photographed. Look at the neutral areas (a grey wall, a white cloud): they are where toning shows first, and where you can judge it. Since the tint ignores brightness, it is gentler than the Tone Curve's colour channels, which also change the tones; use toning when you want colour *only*, and the curves when you want both together. See also [[lab-look-module]], whose balance sliders do a related job in a different way.
""", keywords=("color toning", "split toning", "tint", "shadows", "highlights", "midtones", "sepia", "teal orange", "oklab", "cinematic"), module="Color Toning", see=("color-mixer-module", "lab-look-module")),

    Lesson("lab-look-module", "color", "Lab Look", "Understand what a lab's scanner does to a print, and how Fade, Glow, the balance sliders and the scanner colour reproduce it.",
           r"""
When a photo lab scans your negatives, its machine adds a **character** of its own. Blacks are often a little lifted and matte. Highlights are gently compressed. Colours lean in a way people recognise: a Frontier scan looks different from a Noritsu one. People often like that look, and **Lab Look** reproduces it. It is a *taste* tool: the effects are estimates built from how labs and their owners describe the machines, not measurements of any one scanner.

## How it works

Fade, Glow and the balance sliders are all **curves of the tones**, so they cost nothing per picture and keep the 16-bit tonal precision. They sit after the Tone Curve in the chain. The shapes were set from the output of a lab-look program at the ends of its sliders (see the presets notes), and the sliders run from -1 to +1.

## Fade and Glow

**Fade** works on the **shadows**. Positive Fade **compresses** them: the black is **lifted** (by up to about 50 levels at the extreme, with the lift dying away quickly with brightness), giving a soft, matte black with no pure black in the picture. Negative Fade **expands** them: the darkest tones sink and the lower midtones rise a little, for a deeper black and more shadow contrast.

**Glow** works on the **highlights**. Positive Glow compresses them (smoother, softer, less highlight detail), and because the black and the top are held, squeezing the highlights makes the midtones **rise** to make room. Negative Glow expands them: a starker look with more highlight detail. Glow is **not** a blur, despite the name: it is a change in tonality, not in sharpness.

## Balance by tone

Six sliders warm or cool, and shift towards magenta or green, the **shadows**, the **midtones** and the **highlights** *separately*. This is the heart of a lab look: it is rarely one cast over everything. A typical lab scan is cooler in the shadows and warmer in the midtones. The three tonal ranges are smooth overlapping weights (shadows and highlights at the ends, midtones between) and the colour changes use the same simple offset model as Temperature and Tint.

## Scanner colour

**Scanner** adds the colour response of a lab machine, in the OKLab colour space, scaled by **Amount**. Each machine is a small cast added in the shadows, midtones and highlights plus a change of overall colourfulness. **Frontier** has more colour (about 10% more), cooler cyan-blue shadows and golden midtones. **Noritsu** has softer colour (about 8% less), a faint green in the shadows and peach midtones. **Pakon** is clean and neutral with slightly more colour. **Crystal Archive**, a paper, adds more colour and a touch of warmth. The directions come from published descriptions; the sizes are estimates.

## Using it

Treat it as a finishing touch: get the picture right first (conversion, tone, white balance), then add a lab look for character. Use the **Amount** slider to dial the scanner colour back to a taste rather than leaving it at full. Many of EFAS's built-in presets (the Scanners and Film Stocks sets) are made from these controls: they are good places to see what each does.
""", keywords=("lab look", "fade", "glow", "frontier", "noritsu", "pakon", "scanner colour", "matte", "film look", "crystal archive", "lifted blacks"), module="Lab Look", see=("presets-lesson", "color-toning-module")),

    Lesson("edge-color-module", "color", "Edge Color", "See why a flash or a lens puts a cast at the edges, and how Tint, Warmth, Light, Size and Shape correct it.",
           r"""
Look at a flash photograph's corners and you may find they are a different colour from its middle. The explanation is physical. A flash lights the **middle of a frame strongly and its edges weakly**, so the edges are left to whatever else was lighting the room: fluorescent tubes put a **green** cast there, tungsten bulbs an **orange** one. And the edges are usually darker too. A lens that darkens its corners produces a similar, plainer effect.

This is a problem *in the picture*, which makes it a different problem from the others in the Convert tab. **Flat Field** corrects the *scanner's* light, using a reference shot that does not contain this effect. **Edge Bleed** removes light spilling in from the film border. Neither can see it. **Edge Color** corrects it directly.

## How it works

The correction is a shift of the picture's colour and lightness that **grows smoothly from the centre towards the edges**: nothing happens in the middle, and the full amount is reached at the edge. It is done in OKLab, the perceptual colour space, so it moves colour without dragging brightness along. At the ends of the sliders, **Tint** shifts the green-magenta value by 0.06, **Warmth** shifts the yellow-blue value by 0.06 and **Light** shifts the lightness by 0.15, all at full weight at the edge.

## The controls

**Tint** moves the edges towards magenta (positive) or green (negative); a green cast from fluorescent light wants a **positive** tint. **Warmth** moves them towards yellow (positive) or blue (negative); an orange cast wants a **negative** warmth. **Light** makes the edges brighter (positive) or darker (negative).

**Size** is where the correction starts, from the centre (0) to the edge (1). A bigger Size leaves more of the middle alone and confines the correction to the outer ring. **Shape** says what that region looks like: 0 follows an **ellipse**, which is what a flash's falloff looks like, reaching furthest into the corners; 1 follows the picture's **rectangle**, an even band round all four sides.

**Auto match the colour** measures the colour of the outer 8% band against the middle of the picture (30% to 70% of each side) and sets Tint and Warmth so the edges match the middle. Press it again to refine. It deliberately **leaves Light to you**, because a picture often has genuinely bright or dark things at its edges, and matching them to the middle would darken or brighten real content.

## Using it

It works on the **cropped** picture, so **crop off the film's border first**. The clear film base at the edge of a frame is a hard-edged strip of a different colour; a soft correction cannot hide it, and Auto would chase it. Start with Auto, then judge by eye: a correction that is a little too weak is nearly always better than one that is too strong, because an over-corrected edge looks like a tinted frame. See [[recipe-flat-light]] for how Edge Color fits with the other edge tools.
""", keywords=("edge color", "flash", "green edges", "fluorescent", "tungsten", "cast", "corners", "vignette", "orange edges", "auto match"), module="Edge Color", see=("recipe-flat-light", "flat-field-module")),

    # ------------------------------------------------------------------ Detail
    Lesson("detail-overview", "detail", "Detail: noise, texture and sharpness", "Understand what the detail tools do to a picture's fine structure, and why they are used in a particular order.",
           r"""
The tools in the **Detail** tab all work on a picture's *fine structure*, and they pull in different directions, which is why the order matters. **Chroma Denoise** removes something: the coloured speckle of grain. **Local Contrast** adds something: texture, by stretching contrast within small areas. **Sharpening** adds something else: crispness along edges. **Grain Sharpening** does the same for the film's own grain, at the grain's size. Remove first, add second, sharpen last, so that adding and sharpening do not amplify what you have just removed.

## The reasoning

Every enhancement of detail also enhances noise: they look the same to an algorithm, which sees only small differences between neighbouring pixels. Film grain is exactly that. If you sharpen first and denoise afterwards, the sharpening has already made the colour speckle crisper and harder to remove. So the sequence is: denoise the colour, boost local texture, and finish with sharpening, which is also the stage where the result is most sensitive to resolution.

## Judge at 100%

Fine structure can only be judged at **100% zoom**. At the fit-to-window size a preview is a shrunken copy, which hides grain and halos alike. Press `Z` for 100%, and switch **HQ** on (`Ctrl+H`) so you are looking at the full-resolution picture the export will be made from.

## A note on grain

Grain is part of film's look, and many people value it. These tools do not remove grain: Chroma Denoise takes out the *coloured* part and leaves the brightness texture. If you like grain, keep the other two gentle, because Local Contrast and Sharpening both exaggerate it.
""", keywords=("detail", "sharpen", "noise", "texture", "overview", "tab", "grain", "order"), see=("viewing-tools", "film-speed-and-grain")),

    Lesson("chroma-denoise-module", "detail", "Chroma Denoise", "See how only the colour channels are smoothed, why that spares detail, and how the radius is kept consistent between preview and export.",
           r"""
Film grain, and noise from a camera's sensor, come in two parts. There is a **brightness** part: the texture of lighter and darker dots, which many people like and which carries the sense of detail. And there is a **colour** part: random coloured specks, red and green and blue dots with no meaning at all, which almost nobody likes. **Chroma Denoise** removes the second and leaves the first.

## How it works

The picture is converted into **Lab**, a colour model that separates brightness (L) from two colour axes (a and b). Only the **a and b** channels are smoothed; the brightness channel is not touched, so the picture stays as sharp as it was. The smoothing is **edge-aware** (a bilateral filter): each pixel is averaged with its neighbours, but only with those whose colour is close to its own, so colour is never smeared across a real boundary. A red object next to a green one stays red and green; the speckle inside each is averaged away. The colour tolerance is fixed (15 units in Lab), and the **radius** you choose sets how wide an area is averaged.

The radius is scaled to the picture's size relative to the 1600-pixel preview, so smoothing covers the **same part of the picture** at full resolution as it did in the preview. A change you judged in the preview behaves the same in the export. For large radii the filter works on a shrunken copy and enlarges the result, which is the same effect, much faster.

## The control

**Amount** runs from 0 (off) to 5 and is the radius of the smoothing. Double-click to reset.

## Using it

Zoom to 100% and look at the shadows and the smooth areas such as skies and skin, where colour speckle shows most. Raise the amount just until the speckle disappears. Too much and fine colour detail goes too: very small coloured things (a distant sign, a flower in a meadow) fade towards their surroundings, and colours near edges look slightly washed out.

Use it **before** sharpening, so sharpening has no speckle to enhance. It is also the right companion to **Shadows & Highlights**: lifting a dark area lifts its noise, and colour noise in lifted shadows is the first thing you will see ([[shadows-highlights-module]]). It does nothing about the brightness grain by design: if grain is too strong for your taste, that is part of the film.
""", keywords=("denoise", "chroma", "colour noise", "speckle", "grain", "smooth", "noise reduction", "bilateral", "lab"), module="Chroma Denoise", see=("iso-and-noise", "sharpening-module")),

    Lesson("local-contrast-module", "detail", "Local Contrast", "Learn how CLAHE stretches contrast tile by tile, what the single Amount slider controls, and why a little goes a long way.",
           r"""
Ordinary contrast treats the whole picture the same way: one setting, applied everywhere. But a picture is rarely uniform. A hazy sky has low contrast within it, a sunlit wall has plenty. Raising the global contrast enough to bring out the sky's texture would blow the wall out. **Local Contrast** raises contrast **locally**: each part of the picture is stretched against *its own surroundings*.

## How it works

The technique is **CLAHE**, contrast-limited adaptive histogram equalisation, applied to **lightness only** (the L of Lab), so colours are untouched. The picture is divided into an **8 by 8 grid of tiles**. For each tile, EFAS builds the histogram of its brightnesses and *equalises* it: it spreads the tones out so the tile uses its whole range. Left alone that would turn flat areas into noise, so the histogram is first **clipped**: no brightness level may hold more than a limit, and the excess is redistributed evenly. The limit is set by the Amount (the Amount multiplied by 2.5 times the average count per level), which is what *limits* the contrast.

Each pixel is then remapped, not by its own tile's curve alone, but by a **smooth blend of the four nearest tiles' curves**, with smoothstepped weights, so no seams show where the tiles meet. Finally the result is **mixed with the original** by the Amount: at 0.3 you get 30% of the equalised look and 70% of the original.

## The control

**Amount** (0 is off) sets both the clip limit and the mix. Double-click to reset.

## Using it well

A little goes a long way. At small values it makes texture in skies, clouds, stone and foliage stand out; pushed far it looks **'HDR'**: crunchy, with glowing halos around edges and exaggerated grain. It tends to flatten the large-scale light and shade of the picture (the very thing it was built to do) which can make a picture look unnatural if you overdo it.

It suits a **flat scan** that needs life but would clip with plain contrast, and **textured subjects**. It is not kind to faces, because it emphasises skin texture. Judge it at 100% (see [[detail-overview]]), and use it before sharpening, since both add texture.

NOTE: Local Contrast is the heaviest of the three Detail tools on a big photograph, since it analyses the whole picture rather than working a pixel at a time. If a large photo feels slow to edit, use it last, and judge the rest first.
""", keywords=("local contrast", "clahe", "clarity", "texture", "hdr", "haze", "structure", "equalization", "tile"), module="Local Contrast", see=("contrast-module", "sharpening-module")),

    Lesson("sharpening-module", "detail", "Sharpening", "Learn how each of the four methods works, what Amount, Radius and Masking change, and how EFAS keeps halos and noise in check.",
           r"""
Every digital picture is a little soft: the sensor, the lens and the conversion all blur fine detail slightly, and a film scan especially. **Sharpening** compensates by increasing contrast along edges so detail looks crisper. It cannot add detail that was never recorded, only emphasise what is there, which is why it is the *last* of the detail tools.

## How the default method works

**Unsharp Mask** is the classic. EFAS works on the **lightness** of the picture (L of Lab), so colour is never shifted. It makes a blurred copy of the lightness (a Gaussian blur whose width is the **Radius**), and subtracts it from the original. What is left, the *difference*, is the fine detail. It then adds a scaled amount of that difference back. Three refinements make the result cleaner than a plain unsharp mask:

- A **noise gate**: differences smaller than about a quarter of a lightness unit are not boosted at all, so the faintest texture (grain at its smallest) is not sharpened.
- A **shadow guard**: the boost is cut to a third in the very darkest tones and rises to full strength by a mid-shadow lightness, so noise in the shadows is not amplified.
- **Halo control**: the sharpened lightness is clamped to stay within a little of the local minimum and maximum of its 3 by 3 neighbourhood (allowing about 2 units of overshoot on the dark side and 1 on the light), which is what limits the bright and dark rims along edges.

## The four methods

**Unsharp Mask** is the all-purpose default. **Deconvolution** tries to *reverse* the blur rather than fake crispness: it runs a Richardson-Lucy iteration on the linear luminance, assuming the blur was a Gaussian of the Radius, with the number of passes set by the radius (from 5 to 20), and the result is applied as a ratio on red, green and blue so colour is preserved. It is the one to try for a scan that is genuinely soft from a known blur, with the Radius set to the width of that blur, and it applies **when you release the slider**. **Surface Blur** is Unsharp Mask using an *edge-preserving* blur as the reference, so smooth areas (skin, a clean sky) are left clean while edges are sharpened. **Wavelet** splits the picture into scales (blurs at 2, 8 and 32 times the Radius) and boosts the middle and large structures while leaving the finest scale, the grain, alone.

## The controls

**Amount** is the strength: 0 is off, and values up to 1. **Radius** is the size, in pixels, of the detail being sharpened: a small radius crisps fine detail, a large one sharpens broader forms. **Masking** protects flat and noisy areas by applying the sharpening only where the picture has real edges; at 0 everything is sharpened equally, and raising it keeps the sharpening off skies and skin.

## Using it well

Sharpen **last**, after tone and colour, and judge at **100%**. Bright halos along high-contrast edges mean it is too much: reduce Amount or Radius. If the grain is becoming the subject, raise Masking, or switch to Wavelet. The export panel has its own **output sharpening**, a final touch for the size and format of the finished file, so avoid doing the same job twice ([[export-formats]]).
""", keywords=("sharpen", "unsharp mask", "usm", "deconvolution", "wavelet", "surface blur", "halo", "radius", "masking", "amount", "richardson lucy"), module="Sharpening", see=("focus-and-sharpness", "export-formats")),

    Lesson("grain-sharpening-module", "detail", "Grain Sharpening", "Understand what it does to the film's grain, what Amount, Size and Midtones change, and why it is judged at 100%.",
           r"""
A camera scan of a negative often records the grain soft. The grain is a texture only a pixel or two wide, and the lens, the sensor's own filter and the demosaicing each blur it a little. **Grain Sharpening** makes the grain that is already in the scan crisper. It does not add grain: where the scan shows a flat grey there is nothing to sharpen, and it cannot show detail the capture did not record.

## How it works

EFAS takes the **lightness** of the picture and separates the narrow band of texture at the size of the grain: what is left between a blur a little narrower than the grain and one a little wider. It raises the contrast of that band and puts it back, so the grain gets crisper and a touch narrower, and nothing larger changes. The picture's own tones and edges are the job of Sharpening, which this leaves alone. Colour is never touched, because only the lightness is changed. The boost to any one pixel is eased off past a small limit, so a hard edge is not given a halo.

## The controls

**Amount** is how much crisper the grain is made: 0 is off, and a full Amount raises the grain's contrast to roughly two and a half times what it was. **Size** is the width of the grain in *scan* pixels. **Match My Grain** measures it for you, the same way the Grain Report does, and sets Size to the number; for most camera scans it is between one and two. A Size that is too large treats broader texture as grain and starts to look like Local Contrast. **Midtones** is 0 to treat every tone alike and 1 to leave the deepest shadows and the highlights as they were, which is usually kinder to the shadows, where sensor noise sits.

## Judge it at 100%

Size is measured in pixels of the scan, and the editing preview is the scan made smaller, so on the fitted preview the grain is under a pixel and nothing shows. Zoom to 100% (and switch **HQ** on), or look at the export, which is made from the scan itself. The Grain Report counts this module among the ones it compares, and with it on tells you the grain is *crisper*, not that sharpening is too strong.

TIP: Use Grain Sharpening for the grain and Sharpening for the picture. If the Grain Report says your capture does not resolve the grain, no setting here will find it; a closer capture or a sharper aperture will.
""", keywords=("grain", "grain sharpening", "sharpen grain", "crisp", "texture", "film grain", "match my grain", "size", "midtones"), module="Grain Sharpening", see=("sharpening-module", "grain-report", "detail-overview")),
]
