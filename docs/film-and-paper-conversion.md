# Modern conversion (film & paper)

Convert tab > Conversion > **Method**. Two choices: **Modern (film & paper)**, the default, and **Original (stretch)**, the conversion EFAS used before. Photos that were edited before Modern existed keep Original; photos that were only opened, never edited, and new photos get Modern. The choice is saved per photo and goes into presets with the rest of the metering. This page says what Modern does, why, and how far to trust it.

## Why a second conversion

The Original conversion stretches each colour channel in a straight line between its darkest and lightest reading. It is robust and it is what most quick tools do, but it treats three different things as one:

- **the film**, whose density does not follow the light in a straight line (the toe flattens the shadows, the shoulder the highlights) and whose three dye layers absorb in each other's bands;
- **the scene**, whose own range and middle differ from frame to frame;
- **the paper**, which has a white and a black that are not the ends of the scan, and whose curve rolls highlights and shadows off instead of clipping them.

Modern keeps them apart, in the order a darkroom meets them.

## The steps

1. **Density.** The scan is made linear (the display encoding undone) and turned into optical density, `D = -log10(T)`. Equal steps in density are equal steps of the film's response.
2. **Crosstalk.** A dye layer also absorbs in its neighbours' bands, so the three measured densities are mixed copies of the three dye densities. Beer-Lambert makes that mixing linear in density, so a 3x3 matrix applied to the densities takes it out. Every row of the matrix sums to 1, so a grey stays grey. The **Film** menu picks the matrix: a generic colour negative (the default), none, one of sixteen film profiles, or your own. The **Crosstalk** slider sets how much is taken out (the matrix is blended toward the identity).

   The sixteen film profiles (Kodak Portra 160/400/800, Ektar 100, Gold 200, Ultra Max 400, Aerocolor IV, VISION3 250D and 500T, Fujicolor 200, 400, C200, Natura 1600, Pro 400H, Superia X-TRA 400, Harman Phoenix II) are the matrices from NegPy's profile gallery, bundled unchanged under the GPL-3.0 (`src/photoeditor/assets/crosstalk/`). They are read off the makers' published spectral dye-density curves, so they describe the dyes alone and are approximations; your scanning light and camera mix the channels a little too. To add your own, put a `.toml` file (`name = "..."` and a 3x3 `matrix`, rows out red / green / blue) in the `crosstalk` folder of the EFAS data folder; it appears in the menu.
3. **Film curve.** Density above the film's base is not proportional to log exposure. The inverse of an S-shaped (logistic) characteristic curve puts the toe and shoulder back, giving log exposure, the scene as the film saw it. The **Film curve** slider sets how much. The inverse needs the base density, so the amount is scaled down to about a third when the base is only estimated; sample the rebate (Sample Film Base, or Find Film Base for the Whole Roll) for the full effect.
4. **Balance.** Each channel's log exposure is scaled and shifted so the three channels cover the same range (the picture's 2nd to 98th percentile). This removes the orange mask and the difference between the layers.
5. **Print.** Log exposure goes through a paper curve: a straight line of slope `k` (the grade) between a toe that rolls the shadows into paper black and a shoulder that rolls the highlights into paper white. The slope is chosen so the picture's own range fills the paper's usable range, and the picture's middle prints near a middle grey, both only partly (80% and 65%), so a plainly dark or bright picture keeps its mood. **Grade** adds to the automatic slope, **Print density** shifts the print darker or lighter, **Paper toe** and **Paper shoulder** shape the two roll-offs. A *shadow reach* rule raises the slope (by at most a quarter) when the picture's darkest tail would otherwise print grey, which is what a flat negative needs. **Red / Green / Blue grade** change one layer's contrast around the picture's middle, which corrects colour crossover (shadows leaning one colour and highlights the opposite) without moving the middle tones.
6. **Light.** The print density becomes reflectance measured against the paper itself (paper white is 1, paper black is 0, as a display treats them), and is encoded for the display.

Steps 3 to 6 are one curve per channel of the unmixed density, so they are built as a lookup table, which is how the rest of the editor applies tone. Exposure, Contrast, colour balance, the tone curve and every other module work on the result as before.

## What it is based on, and what is new

The approach (density in, characteristic curve, grade, automatic density and grade that move the print only part of the way) follows the print stage of NegPy (GPL-3, https://github.com/marcinz606/NegPy), and the film crosstalk profiles are NegPy's own data files. The conversion code is EFAS's own numpy code on EFAS's lookup-table pipeline, and its constants are EFAS's. Two things are different:

- the film's own toe and shoulder are put back before the paper's are applied (NegPy's paper curve is applied to the stretched density directly);
- the conversion can be measured: `src/photoeditor/features/negative/filmsim.py` is a forward model of colour negative film (per-layer S-shaped curves, the orange mask, dye crosstalk, a camera scan), and `tools/benchmark_conversion.py` exposes pictures onto it and scores each conversion against the original picture.

## How far to trust it

On the simulator, Modern and Original are close in colour, and Modern clips far fewer pixels (a fraction of a percent against several percent) and keeps highlight detail. That is a statement about the simulator's film, which uses the same kind of S-shaped curve the conversion assumes, so it shows the maths is consistent, not that it is right for every stock. Two limits are worth knowing:

- Balancing from the picture's own range means a scene dominated by one colour is pulled toward neutral a little. The film base, when sampled, does not fix this by itself; it improves the film-curve step only.
- The film curve uses one generic S-shape for every stock. Stock-specific curves would do better; the sensitometry tools (Advanced mode) can measure a real film's curves if you have a step tablet.

On real scans it gives smoother highlights and less clipping than Original, with somewhat lower contrast out of the box; **Grade** and **Print density** are there for taste. Judge it on your own film.

## Benchmark

```
python tools/benchmark_conversion.py picture.jpg [more pictures] [--sheet out.png]
```

Each picture is exposed onto three modelled films, at three exposure errors, under neutral and tungsten light, converted by each engine, and compared with the picture. The columns are the mean colour error (distance in a/b from the original), the tone error after the best straight-line fit of lightness, the average colour cast, and the share of pixels pushed to pure black or white that the original does not have there.

## Controls that belong to Original

Range clip, Colour cast, the white and black points and their droppers are Original's way of setting black and white. Under Modern they are greyed out; Grade and Print density do that job. Margin and Draw Region still choose which part of the picture is measured.

## Scan encoding

Step 1 turns the scan back into light, so it has to use the curve the scan was made with. **Convert tab > Conversion > Encoding** says which: **Automatic** (the default) reads it from the file: a RAW file EFAS decodes carries libraw's own curve, which is Rec. BT.709, and any other file is read as sRGB. Choose **Linear** for a 16-bit TIFF from scanner software that saved the scan without a curve, or **sRGB** or **BT.709** to override the guess. The choice is saved per photo and is not part of a preset or pasted settings, because it belongs to the file.

The curves differ most in the darkest codes, which on a negative are the densest parts and become the positive's highlights. Reading a BT.709 scan as sRGB overstates density there by up to 0.46, and by about 0.2 at the median of a typical frame.

A photo edited before this was a setting keeps sRGB, the reading it was edited with, so its picture does not change. To move it to the correct curve, set Encoding to **Automatic** (or press Reset Metering); the picture will change, and Grade and Print density may need a touch. The film curve defaults (Film curve 0.4, the generic S-shape) were tuned before this fix; judge them on your own RAW scans.
