# Film characterization: a practical guide

This guide is for the optional, advanced part of EFAS that measures how your film and your camera behave. You do **not** need any of it to convert a negative. Everyday conversion (open, sample the film base, invert, adjust, export) works without it and is unchanged.

Open it with **Advanced mode** (Convert tab), then **Sensitometry (H&D) > Film Characterization...**. Everything runs on your computer; nothing is sent anywhere.

## What it can and cannot do

| You want to know | What you need | What EFAS gives you |
|---|---|---|
| How much density is in a negative, and where the scan stops being reliable | Just a scan | Density, Dmin, Dmax with cause analysis (Density and Calibration panels) |
| How your camera behaves as a measuring instrument (flare, usable range) | A calibrated transmission step tablet on your light table | Gain, offset, flare fraction, usable density range, saved as a camera set-up |
| How linear your camera's sensor is | Several RAW photos of the same lit area at different exposure times | A linearity error |
| A film's characteristic (H&D) curve, its gamma and gradients | A film strip you exposed **through a step tablet** and developed | Curves for R, G and B with fit quality, uncertainty and the range actually measured |
| A converted picture that uses that film's measured curve | A film profile from the step above, plus a sampled film base | The curve-informed inversion (optional, experimental) |

**An ordinary photograph can never give you a characteristic curve.** A curve is density against *known* exposure, and a photograph does not record the exposures behind its densities. EFAS will not draw one from a picture, and will refuse to build a "measured" curve unless you confirm the strip was exposed through a known step series.

EFAS measures densities in the **camera's own red, green and blue bands**. They are not ISO Status M densities (the standard for colour negatives), and a camera scan is not a laboratory densitometer. Results describe the roll, exposure, processing and set-up they were made from; other rolls of the same film can behave differently.

## 1. Calibrate the camera with a step tablet (optional)

Needs a calibrated transmission step tablet (for example a 21-step tablet with 0.15 density steps) and your usual light table and camera set-up.

1. Mask the light table around the tablet so stray light does not reach the lens, and keep the tablet slightly out of focus. Expose so the clearest step is high but not clipped.
2. Open the RAW photo in EFAS. In Film Characterization choose the **Scanner calibration** tab.
3. Enter the tablet: number of steps, first step density and increment. **If you have the tablet's calibration chart, paste the actual densities.** Real tablets differ from nominal, and cumulative errors can mislead. EFAS warns when a tablet falls outside the SMPTE RP 14 tolerances (adjacent steps 0.150 ± 0.015; no step more than 0.02 from a straight line through all steps).
4. Choose whether the first patch is the clearest or the densest step. Press **Pick Patches on the Scan** and click the centre of the first patch, then the last. EFAS lays out the rest evenly.
5. Press **Sample Patches**. Orange boxes are patches EFAS will not use (clipped, below the noise floor, uneven, or off the picture); the table says why. Untick any you want to leave out.
6. Press **Calibrate the Camera**. For each colour EFAS fits `v = k x 10^-D + f`. `f` is the offset from flare and black-level error and `f/k` is the **flare fraction**. You also get the density the camera can reliably measure and whether flare or noise sets that limit.
7. **Save as a Camera Set-up.** Set-ups appear under Camera Set-ups and can be chosen in the Convert tab to remove the flare fraction before the curve-informed inversion.

If the result says the offset is negative or the points do not follow the model, suspect the backlight (uneven, flickering) or stray light before suspecting the camera.

## 2. Linearity test (optional)

Take several RAW photos of the same evenly lit area (no film), changing only the exposure time, with some frames between 5% and 95% of full scale. In the **Linearity test** tab add the files; EFAS reads exposure times from the files (you can type them if missing) and fits signal against time. A steady, flicker-free light is assumed: a pulsing LED backlight shows up as non-linearity that is not the camera's. The figure is EFAS's own statistic after EMVA 1288; the standard's exact normalisation was not verified.

## 3. Characterize a film (needs known exposures)

You need a strip of the film that has been **exposed through a step tablet**, with the film touching the tablet (or in a sensitometer), and then developed. The tablet's steps give the film known relative exposures: log H = log H0 − D. If you also know the exposure through the clear aperture (in lux-seconds), you can enter it and the curve is on an absolute scale; otherwise it is on a relative scale (shape, gamma, Dmin/Dmax and gradients are all still valid; film speed is not available).

Photographing a lit tablet through a camera lens as the subject also exposes the film, but lens flare is mixed in, so those exposures are not the tablet's. EFAS accepts it as a labelled method; prefer contact exposure.

1. Scan the developed strip as you would any negative and open it. Use **Sample Film Base** on the strip's clear border first: density is measured from the film base.
2. In Film Characterization choose the **Film characterization** tab. Enter the tablet and pick the patches as in step 1 above.
3. Tick **This film was exposed through this tablet, and I know the exposure steps**. Without it, EFAS will not fit anything.
4. Fill in what you know: exposure method, light source, processing, film stock and process (both optional: you can leave the film unidentified).
5. Press **Fit the Curves**. For each colour you see:
   - the measured points with their uncertainty;
   - the fitted curve with its 95% band, drawn dotted outside the exposures you actually measured;
   - the residuals (what the fit missed) and the gradient along the curve;
   - a quality label (good, fair, poor) with reasons, and an interpolated curve instead when no parametric model passes the checks.
6. **Save as a Film Profile.**

EFAS fits three representations (an interpolated curve, a toe/straight-line/shoulder model and an asymmetric logistic) and recommends one only if it passes the checks and predicts left-out points best. A film with an odd curve is shown as measured, not forced into a standard shape.

## Reading the results

- **Gradient** is density per unit of log exposure: the film's contrast. It rises through the toe, levels at **gamma** in the straight-line portion, and falls through the shoulder. EFAS always states the exposure interval behind a figure.
- **Average gradient** here is the slope of the chord over a stated interval. The ISO 6 speed-criterion geometry (0.10 above base, then 1.30 log exposure further, a density rise of 0.80) is shown for black-and-white negatives only, as the *curve's geometry*, not as a speed.
- **Shadow separation, midtone contrast, highlight compression** (also shown in the Convert tab once a profile is applied) describe the film's response over the measured exposures. They are not a reconstruction of your scene.
- **Where the measurement can be trusted** (Calibration and Diagnostics): the share of the picture that is clipped in the camera, below the noise floor, noise-limited or usable, with whether each is measured, inferred or unknown. If the densest areas are below the noise floor, EFAS tells you how many stops more light would extend the range, and never blames the film unless the signal there is strong and the histogram piles up.

## Film profiles

**Film Profiles...** lists, shows, duplicates, edits, imports, exports, compares and deletes profiles. A profile stores the measured points, the fits and their uncertainty, the range measured, and where it came from (tablet, exposure, processing, scan, date). Its *kind* is shown everywhere: *measured* (made here from known exposures), *supplied* (a curve file you imported; EFAS does not verify it), *estimated* or *generic* (never used to convert a picture). No film curves are bundled with EFAS.

Profiles are plain JSON files in the `film_profiles` folder of your data folder (`~/.photoeditor`), version 1. Unknown future fields are kept when a profile is opened and saved.

## The curve-informed inversion (optional)

In the Convert tab, **Inversion method** can be switched from *Standard* to *Curve-informed (experimental)* once a profile and a sampled film base exist.

It works in four labelled steps: measured density above the film base; estimated exposure through the profile's curve; a reconstructed positive using a white reference; then display encoding. Densities outside the profile's measured range are held at its ends and counted (never extrapolated). The white reference is an assumption about your scene's lighting and sets the colour balance. It does **not** recover film-layer spectral sensitivities, dye behaviour, processing differences or the scene's light.

- It is **off by default**, chosen per photo, and stored apart from your edits: presets, snapshots, history and sidecars are untouched. A photo with no choice uses the standard method exactly as before.
- **Compare Methods...** shows both conversions through identical settings, flipped at the same spot, with numbers, and changes nothing.
- Export uses the same method at full resolution. If a photo is saved with the curve method but its profile or film base is missing, the export for that photo **fails with the reason** instead of quietly using the other method.
- Not available with the curve method: AI dust detection, and flat-field correction (its gain acts on the negative).

## Known limits

- A camera cannot measure Status M density or the density of the very densest areas; flare lifts them. EFAS reports the limit and can remove a calibrated flare fraction, but veiling glare depends on the scene, so that correction is approximate.
- Spectral sensitivity of your camera's bands and of the light source are not measured.
- A profile measured under one development or on one roll is not guaranteed to match another.
- Fujifilm and Kodak publish film curves as graphics, so no published curve is built in or compared against.
