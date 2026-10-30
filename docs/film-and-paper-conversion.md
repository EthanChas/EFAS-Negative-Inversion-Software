# NegPy Conversion (film & paper)

Convert tab > Conversion > **Method**. Four choices: **NegPy Conversion (film & paper)**, the default, **Original (stretch)**, the conversion EFAS used before, **NegPy 0.56 (old)**, NegPy's own conversion as that version made it, and the **Noritsu look**, a port of noritsu-tool (the last sections). Photos that were edited before NegPy Conversion existed keep Original; photos that were only opened, never edited, and new photos get NegPy Conversion. The choice is saved per photo and goes into presets with the rest of the metering. This page says what NegPy Conversion does, why, and how far to trust it.

## Why a second conversion

The Original conversion stretches each colour channel in a straight line between its darkest and lightest reading. It is robust and it is what most quick tools do, but it treats three different things as one:

- **the film**, whose density does not follow the light in a straight line (the toe flattens the shadows, the shoulder the highlights) and whose three dye layers absorb in each other's bands;
- **the scene**, whose own range and middle differ from frame to frame;
- **the paper**, which has a white and a black that are not the ends of the scan, and whose curve rolls highlights and shadows off instead of clipping them.

NegPy Conversion keeps them apart, in the order a darkroom meets them.

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

On the simulator, NegPy Conversion and Original are close in colour, and NegPy Conversion clips far fewer pixels (a fraction of a percent against several percent) and keeps highlight detail. That is a statement about the simulator's film, which uses the same kind of S-shaped curve the conversion assumes, so it shows the maths is consistent, not that it is right for every stock. Two limits are worth knowing:

- Balancing from the picture's own range means a scene dominated by one colour is pulled toward neutral a little. The film base, when sampled, does not fix this by itself; it improves the film-curve step only.
- The film curve uses one generic S-shape for every stock. Stock-specific curves would do better; the sensitometry tools (Advanced mode) can measure a real film's curves if you have a step tablet.

On real scans it gives smoother highlights and less clipping than Original, with somewhat lower contrast out of the box; **Grade** and **Print density** are there for taste. Judge it on your own film.

## Checked against the Pakon reference

Ali Bosworth's Pakon F-X35 reference (documentation, CC BY 4.0, https://github.com/alibosworth/pakon-reference) records how the Pakon scanners turn a raw colour-negative scan into a positive, from reverse engineering and checks on real scanners. EFAS never talks to a scanner, so almost all of it (the USB protocol, the firmware, the calibration data) does not matter here. Its colour-pipeline page is a useful outside check on NegPy Conversion's first steps, and it agrees:

- The scanner's negative-to-positive step is a pure log conversion of the linear scan code, D = 3500 x log10(16383 / x): density, with no tone shaping in it. NegPy Conversion's density step is the same function (D = -log10 of the linear value; only the scale differs), and a test checks that the two agree to 0.00002.
- The film base must be compensated once, in one place: doing it both in the linear domain and in the density domain applies it twice. NegPy Conversion uses a sampled base in one place (the film-curve step), so a scan and its sampled film base can be scaled together (an exposure change) without changing the print. A test checks that, and checks that scaling the scan alone does change it.
- The off-diagonal terms of the scanner's 3 x 3 matrix are the dye crosstalk correction in density, each row summing to about 1 so neutrals stay neutral. That is what NegPy Conversion's crosstalk step does with the film profiles.

Two things are deliberately not taken from it. The matrix is documented as the F-235 engine's, and the 135-line scanners (F-135 and F-135+) are reported to use a different, per-unit colour transform, so it is not a general film profile and EFAS does not ship it as one. And the reference documents the scanner's inversion, not its look, so it says nothing about how big the Pakon response in the Lab Look module should be: those sizes stay estimates from published descriptions.

## Benchmark

```
python tools/benchmark_conversion.py picture.jpg [more pictures] [--sheet out.png]
```

Each picture is exposed onto three modelled films, at three exposure errors, under neutral and tungsten light, converted by each engine, and compared with the picture. The columns are the mean colour error (distance in a/b from the original), the tone error after the best straight-line fit of lightness, the average colour cast, and the share of pixels pushed to pure black or white that the original does not have there.

## Controls that belong to Original

Range clip, Colour cast, the white and black points and their droppers are Original's way of setting black and white. Under NegPy Conversion they are greyed out; Grade and Print density do that job. Margin and Draw Region still choose which part of the picture is measured.

## Scan encoding

Step 1 turns the scan back into light, so it has to use the curve the scan was made with. **Convert tab > Conversion > Encoding** says which: **Automatic** (the default) reads it from the file: a RAW file EFAS decodes carries libraw's own curve, which is Rec. BT.709, and any other file is read as sRGB. Choose **Linear** for a 16-bit TIFF from scanner software that saved the scan without a curve, or **sRGB** or **BT.709** to override the guess. The choice is saved per photo and is not part of a preset or pasted settings, because it belongs to the file.

The curves differ most in the darkest codes, which on a negative are the densest parts and become the positive's highlights. Reading a BT.709 scan as sRGB overstates density there by up to 0.46, and by about 0.2 at the median of a typical frame.

A photo edited before this was a setting keeps sRGB, the reading it was edited with, so its picture does not change. To move it to the correct curve, set Encoding to **Automatic** (or press Reset Metering); the picture will change, and Grade and Print density may need a touch. The film curve defaults (Film curve 0.4, the generic S-shape) were tuned before this fix; judge them on your own RAW scans.

## NegPy 0.56 (old)

**NegPy 0.56 (old)** is a numpy port of NegPy 0.56.0's conversion (`features/negative/negpy056.py`), kept beside the NegPy Conversion because NegPy changed this part later (0.58 retuned the print tone, made Auto Grade and Auto Density read textured parts only, and added a shadow reach floor) and a photo converted with 0.56 has a look of its own. It follows NegPy's own code, and is checked against it: the same scene through NegPy 0.56.0's normalization and print stages and through the port gives the same picture to float precision, for colour and black-and-white negatives.

- **Bounds, not a film model.** Each channel is stretched between the 0.01st and 99.99th percentile of its log density (the dense end read from a chroma-gated set of neutral pixels), so the film's orange mask is gone whatever its strength. There is no crosstalk matrix, film curve or sampled film base: the bounds come from the picture.
- **The metering region matters.** Black and white are read from the metering region (the frame less its Margin, or a region you draw), as NegPy reads its analysis area. For a scan with the film's rebate in it, draw the region on the picture only, or the clear rebate and the sprocket holes set the bounds and the picture comes out dark.
- **Cast Removal, Auto Density and Auto Grade** are NegPy's: red and blue are fitted to green through the picture's own neutral greys (Color cast 1 is NegPy's default strength of 0.5), the picture's middle is metered over the whole region, and the grade is a literal ISO-R value of 115 that the picture's range adjusts.
- **Controls.** Encoding, Grade (each +0.1 is 7 ISO-R points harder), Print density, Paper toe, Paper shoulder, Color cast, and the Margin and Draw Region of the metering. Choosing the method puts those at NegPy's own defaults.
- **A RAW file in the camera's own primaries.** NegPy works on the sensor's own channels, never converted to a colour space, so for NegPy's look tick Settings > Image decoding > **Invert negatives before the camera's colour matrix** (it opens a RAW file in the camera's own primaries). This conversion then does not apply the camera's colour matrix afterwards, as NegPy does not.
- **Not available for slides** (they keep the other methods).

## Noritsu look

The **Noritsu look** is a numpy port of [noritsu-tool](https://github.com/rohanpandula/noritsu-tool) (MIT; `features/negative/noritsu.py`), a tool that inverts a C-41 scan the way a Noritsu LS-600 minilab scanner does and renders it with a Noritsu-flavoured tone curve. It follows noritsu-tool's modules one for one, with the same names, maths and numbers, and is checked against its own code: the same scan through noritsu-tool's `process_negative` and through the port gives the same picture to within 4e-6 of full scale, for every combination of options tried (default, lab mode, real curve, each stock profile, no rebate, no auto white balance, other percentiles).

1. **Density.** The scan is read as density, D = -log10(transmittance) (EFAS holds the scan as density codes already, and takes out its scan encoding first, so this is the same step).
2. **The film.** The statistics come from the whole film, cropped to the film frame (the clear margins and the black scan bars are dropped, as noritsu-tool's `crop_to_film` does), not from a metering region; only a region you draw narrows them.
3. **Dmin and Dmax.** Dmin, the orange mask, is the median of the film's rebate (the outer 3%) when that looks like mask (uniform, blue densest), otherwise a low percentile (0.5) of the film; Dmax is a high percentile (99.8, lower for a thin negative) of the film. Each channel is normalized from [Dmin, Dmax] to [0, 1].
4. **White balance.** The residual cast is neutralized so that the picture's average is neutral (Automatic white balance).
5. **The tone curve.** A synthetic Noritsu S-curve (contrast 1.05, toe 0.02, gamma 0.98), or the LS-600's own 20-point curve (Real LS-600 tone curve), or - when a **Stock** is chosen - the per-stock profile noritsu-tool fitted to real LS-600 scans (Portra 160, Portra 400, Superia 800), which replaces the white balance and the curve. **Lab mode** is contrast 0.90, gamma 0.90, toe 0.04, saturation 0.95 and the real curve.
6. **Saturation** around luma (a BT.601 Y, Cb, Cr), after the tone curve.

**Suggest** is noritsu-tool's `autoparam`: it reads the scan's density range (thin below 0.9, dense above 1.5) and sets Gamma, Dmax %, Contrast, Saturation and Toe for the look chosen beside it (Balanced, Punchy or Soft).

What is not ported: reading an LS-600 RAW dump, its ICE (infrared dust) clean-up, and fitting a profile from a pair of pictures (EFAS has its own RAW decoding and dust tools). Statistics from a scan bigger than two million pixels are read at every k-th pixel of every k-th row, which gives the same percentiles and means. As noritsu-tool does not apply a camera colour matrix, neither does this conversion; its output is used as the display picture (it is not encoded again), so the real curve and lab mode, which expect linear input, come out dark on a scan that is not linear.

## Curve: a film profile in Original and the Noritsu look

Original and the Noritsu look stretch density in a straight line, so a film's toe and shoulder go into the picture as they are. The **Curve** menu takes a film profile (`features/negative/filmcurve.py`: the maker's published curve, such as the Fomapan 100 data-sheet curves that come with EFAS, or one measured from a step tablet) and does what the curve-informed inversion does, inside these two conversions:

1. Each channel's density above the film base is taken through the profile's curve **backwards**, to the log exposure it implies (clamped to the measured range, never extrapolated), and laid on the straight line through the curve's steepest point. The result is a density again: the one an ideal film with no toe and no shoulder, and the same gradient, would have made. It is a table over density, so it costs nothing per pixel.
2. The conversion's own readings are taken on that straightened density: Original's floor and ceiling (its percentiles), the Noritsu look's Dmin and Dmax. A percentile keeps its place through a rising curve, so these are the same pixels as before.
3. The picture is **printed in light**: the ceiling is white and the floor is black in exposure, not in density, and the display encoding comes last (`FilmCurve.print_positive`). This is the same reconstruction as the curve-informed method, which is why it is the film-accurate reference: on the Fomapan test scan (scan_0010) Original with the profile has a median of 109 against the reference's 107, and p25, p75 and p95 within a few levels, where plain Original is 97 and sits lower and flatter. The Noritsu look then applies its tone curve to that picture, with its white balance, as before.

The profile counts fully with a **sampled film base** and about a third as much with an estimated one (the NegPy Conversion's own trust, `UNSURE_BASE`). A base sample whose density is under 0.05 reads as clear light, which means the picture's own white clipped it; it counts as no sample (the sampled base on that Fomapan roll was 254, 254, 254). None of this applies to NegPy Conversion or NegPy 0.56 (old), which have their own film curve. The droppers read the scan as it is, so with a profile they say so and the white and black point sliders are used.

What it does not do: change the Noritsu look's character. The percentile range (Dmax at 99.8) and the synthetic curve still make the Noritsu look darker than the film-accurate print of the same scan (median 80 against 107 on the test scan), and the **Real LS-600 tone curve** still crushes it (median 10, a third of the picture near black): that curve is the LS-600's own and expects linear input.
