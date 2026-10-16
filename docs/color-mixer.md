# Color Mixer, Vibrance and the scanner colour response

## Why OKLCH

Colour sliders that work on RGB or HSV values move lightness and hue along with the thing they were asked to move: raising the saturation of a blue darkens it, turning yellow toward green changes how bright it looks, and pushing a saturated colour past the edge of the screen's range by clipping one channel shifts its hue. The modules below work in **OKLab** (Björn Ottosson, 2020), a colour space built so that equal numerical steps are equal *perceived* steps, and in its polar form **OKLCH**:

- **L**, lightness;
- **C**, chroma, how colourful;
- **h**, hue, the angle around the colour wheel.

Vibrance, the mixer and the scanner response change C, h and L directly. A colour that ends up outside the sRGB gamut is brought back by **reducing its chroma**, a few steps at a time, so it keeps its hue; clipping is only the last, tiny correction. Greys have no chroma, so nothing here can tint them (the scanner response is the one exception, because a lab's cast is meant to show up in near-greys).

The picture is processed in pieces of about a megapixel, so a full-size export needs no more memory than a preview, and the pieces have no seams.

## Vibrance

**Color Mixer > Vibrance** raises (+) or lowers (-) chroma, but not evenly. The muted colours gain the most; colours that are already vivid (chroma above about 0.22) hardly move, so nothing clips into a flat blob; skin hues (about 30 to 75 degrees of hue) are protected, with about 60% of the effect held back; and near-greys are left alone. Plain saturation (Color > Saturation) scales everything the same; use Vibrance for the pictures where that over-cooks the colour that was already strong or the faces.

## The eight colour ranges

Pick one of eight swatches (red, orange, yellow, green, aqua, blue, purple, magenta). Each range has three sliders, each from -1 to +1:

| Slider | What it does at +1 |
|---|---|
| Hue | turns the range 30 degrees along the colour wheel |
| Saturation | doubles the chroma of the range (-1 removes it) |
| Lightness | raises OKLab lightness by 0.12 (about a fifth of the way from mid grey to white) |

The ranges are smooth windows on the hue wheel (a raised cosine, 60 degrees either side of the centre), **normalised so the eight always add up to one**: every hue belongs to its neighbours in proportion, with no gap between ranges and no double counting where they overlap. Each range also fades out toward grey (chroma below about 0.01 takes none of its effect), so a grey can never pick up a colour from a neighbour. A ring around a swatch means that range has been changed.

## Scanner colour response (Lab Look)

**Lab Look > Scanner colour** adds a small stand-in for what a lab scanner's colour table does: a cast in the shadows, midtones and highlights (added to OKLab a and b), and a change of overall chroma, scaled by **Amount**.

| Scanner | Shadows | Midtones | Highlights | Colourfulness |
|---|---|---|---|---|
| Frontier | cooler: toward cyan-blue | golden | a hint of yellow | +10% |
| Noritsu | a faint green | peach | neutral | -8% |
| Pakon | clean | clean | a hint of yellow | +6% |
| Crystal Archive | a touch cooler | a little warm | a hint of yellow | +12% |

**These are estimates.** The directions follow how labs, photographers and the scanners' makers describe each machine (docs/lab-look-research.md): the Frontier cooler and more saturated with golden skin, the Noritsu softer with a tendency toward green in the shadows. Nothing published gives the sizes, so they are kept small (a cast of 0.01 in OKLab is a gentle tint) and open to change as better measurements come in; the Amount slider lets you take as much or as little as you like. They are not a copy of any scanner's or program's colour tables.

The Lab Scanners and Film Stocks presets set the scanner colour from the colour table named in the preset they were converted from (Frontier, Crystal and Pakon have stand-ins; Natural is none), so, for example, Kodak Gold and the Frontier look come with the Frontier response.

## Where it sits in the picture's chain

Vibrance, the mixer and the scanner response are applied to the finished tones: after the tone curve and Lab Look's tone shaping, before sharpening and the finishing steps. Because they need the 8-bit picture, a picture with any of them switched on is made at 8 bits (like Shadows & Highlights, Saturation and Local Contrast do), so a 16-bit export falls back to 8 bits with the note.

Each module has the usual on/off light, a reset button, module presets, undo and per-photo saving, and both can be part of a preset.
