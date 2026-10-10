# EFAS scientific negative-inversion and sensitometry: research and technical design

Status: Tier 1 design (measurement stage). Written before the implementation, and updated to match what was built.

## 0. How to read this document

Every factual statement carries an evidence tag so that nothing here is presented as more certain than it is.

- **[S]** Sourced: read in a document or page during this research (listed in section 12).
- **[K]** Standard knowledge: well established in sensitometry/physics, but not re-read from a source in this research round. Worth verifying against a textbook before relying on it for anything critical.
- **[D]** EFAS design decision: a choice made here, with a reason. Not a claim about the world.
- **[?]** Not established: I could not find a primary source. The code is built so that nothing depends on it.

Items that could not be sourced are listed in section 11 rather than quietly assumed.

## 1. What Tier 1 is, and is not

Tier 1 adds a **scientific measurement stage** next to the existing editing pipeline. It reads the negative as a measuring instrument would: linear sensor values, transmission, optical density, per-channel film-base density (Dmin), per-channel maximum useful density (Dmax), a density histogram, and a sensitometric (H&D) viewer.

Tier 1 deliberately does **not** change how EFAS inverts the picture. The existing inversion keeps working exactly as before [D]. Re-routing the inversion itself through the density engine is Tier 2. The reason is safety: the measurement stage can be verified against synthetic data and known mathematics on its own, and the existing, tested editing behaviour stays intact.

Honest limitation up front: a DSLR/mirrorless scan is **not** a laboratory densitometer. Section 8 lists what it can and cannot measure.

## 2. Photographic science

### 2.1 Transmission and optical density

Transmittance is the fraction of incident radiant flux that passes through a sample: `T = Φt / Φi`. Optical density (absorbance) is `D = -log10(T)`. It is dimensionless; "density units" is a convention. [S: Wikipedia "Absorbance"]

For non-scattering homogeneous samples, density contributions add (Beer-Lambert), which is why density, not transmission, is the natural quantity for superposed dye layers. [S: same] Photographic emulsions scatter light, so this is an approximation, and measured density depends on the optical geometry (diffuse, projection). ISO 5-2 defines the geometric conditions for "diffuse" and f/4.5, f/1.6 projection transmittance densities. [S: ISO 5-2 catalogue entry]

Density is a logarithm of a ratio of light, so it is **not** ordinary image brightness. A display RGB value is a (usually gamma-encoded) number proportional to something like `T^(1/γ)`, so density computed from display RGB is distorted unless the encoding is undone first. [K]

### 2.2 The Hurter-Driffield (H&D) characteristic curve

The characteristic curve plots **density (y)** against the **logarithm of exposure (x)**, exposure being illuminance times time (lux-seconds). [S: Kodak E-4050 plots density against "LOG EXPOSURE (lux-seconds)"; NFSA; Wikipedia "Characteristic curve"]

Regions of a typical negative-film curve: D-min, toe, straight-line portion, shoulder, D-max. [S: search summary of Kodak-style descriptions; consistent with Wikipedia]

- **Base plus fog (D-min):** the density of unexposed, processed film: the support, any dyes/mask, and fog. [S]
- **D-max:** the highest density the material can produce; more exposure no longer increases density. [S]
- **Gamma:** the slope of the straight-line portion. [S]
- **Average gradient:** the slope of the straight line joining the two end points of a chosen segment of the curve. [S: forum-level source quoting this definition] The end points are defined differently by different standards and manufacturers (Kodak's "contrast index" uses its own construction). I could not obtain the primary text of those definitions. [?] **EFAS therefore does not claim a standard:** the average-gradient end points are configurable, with a documented default (section 6.4).
- Colour negative film has three dye-forming layers (yellow/blue-sensitive on top, then magenta/green, then cyan/red), each with its own characteristic curve; the three curves are offset vertically by the film base's orange colour and differ in shape and speed. [S: search summary, consistent with Kodak E-4050 which plots separate B, G and R curves]

Kodak's own Portra 400 sheet (E-4050) is a concrete example of the data format: characteristic curves for the B, G and R layers, daylight exposure, **Status M** densitometry, density axis 0.0-4.0, log-exposure axis in lux-seconds. [S]

### 2.3 Status M and printing density

Status M is the ISO-defined spectral response for measuring colour negatives and other originals meant to be printed rather than viewed. [S] Its spectral conditions are in ISO 5-3. [S: catalogue entry]

A camera's red, green and blue bands are **not** Status M bands. Densities measured through them are real and repeatable but are **camera-band densities**; converting them to Status M needs spectral data or a calibrated transform. The Cineon documentation notes that conversion between Cineon printing density and Status M is estimated with a 3x3 matrix or with Kodak's Digital LAD tables, i.e. it is an approximation even in a professional workflow. [S: Wikipedia "Cineon"] **EFAS labels all of its densities as camera-band densities and never as Status M.** [D]

### 2.4 Colour negative: the orange mask and D-min

Modern colour negative films carry an integral mask, usually red-orange, which compensates for the unwanted absorptions of the image dyes. [S] Masking couplers raise the blue density of the D-min region. [S: patent text in search results] The practical result is that the film base is **not** neutral: its three channel densities differ, typically with blue density highest. [S for the orange appearance; K for the ordering R < G < B]

Consequences for EFAS:

1. D-min must be measured **per channel**. A single RGB D-min is wrong for colour negative. [D, following the brief]
2. Kodak's LAD sheet for duplicate negatives gives Status M aims of 0.90 (R), 1.30 (G), 1.70 (B) for a *specific intermediate stock*, showing that channel densities differ by several tenths even in mid-scale. [S] These are **not** used as typical D-min values for camera films.
3. EFAS includes a plausibility check: for colour negative, `Dmin(B) >= Dmin(G) >= Dmin(R)` is expected, and a warning is shown if not (unusual film, a sampled patch that is not film base, or a backlight with an odd spectrum). **This check is only valid on absolute transmission densities** (those measured against a clear-light reference, section 4.2). On camera-relative densities it would be wrong: the camera's R, G and B channels have different gains for the same backlight, so `Dmin_rel` carries a different unknown constant in each channel and its ordering says nothing about the film. The check is therefore skipped, and the reason is displayed, when no clear reference has been sampled. [D]

### 2.5 Digital density scales, for scale

Kodak's Cineon system stores a negative's printing density in 10 bits at 0.002 density per code value, so the full 0-1023 range spans 2.046 density; reference black is conventionally code value 95 and reference white 685. [S: Wikipedia "Cineon", search results] This is a *scan encoding range*, not the film's D-max. It is useful context: professional film scanning works in about two density units above base, and a single-exposure camera scan has the same order of useful range (section 8).

## 3. How other software handles it (for comparison, not imitation)

| Software | Approach | Source |
|---|---|---|
| darktable *negadoctor* | Treats the scan as log-density data derived from Kodak Cineon: parameters for film-base colour, D min (per channel for colour), D max ("dynamic range of the film", sets the white point), scan exposure bias (black point), shadow/highlight colour correction, then print-like controls (paper black, paper grade/gamma, gloss, print exposure). Formula for the print stage: `RGB_out = (RGB_in * exposure + black)^grade`. Film base is sampled with a picker, which sets D min per channel. | [S] darktable manual |
| RawTherapee *Film Negative* | Power-law model: each channel of the negative is proportional to a power of the reciprocal of the original exposure, with a different exponent per channel. One reference exponent (green) plus red and blue ratios. Neutral spots are picked in a bright and a dark grey area to derive the exponents. Works on the raw data before white balance. | [S] RawPedia |
| NegPy | Density-space processing: raw signal to log (`E_log = log10(I_raw)`), percentile-based floor/ceiling per channel, then a print stage with an H&D-style curve (toe, straight section, shoulder; softplus knees), graded in ISO-R points. The orange mask is handled per channel. | [S] NegPy PIPELINE.md |

What EFAS takes from these: density space is the right place to work (all three); the film base is sampled and used per channel (negadoctor); per-channel behaviour differs and must not be assumed equal (RawTherapee, NegPy); a toe/straight/shoulder curve model is a recognised way to describe a characteristic curve (NegPy). Where EFAS differs: Tier 1 **measures and reports** rather than fitting parameters to make the picture look right, and it keeps unknowns visible.

## 4. The camera as a measurement system

### 4.1 RAW values must be linear and normalised

A camera sensor's photoelectric response is linear in light when read as RAW, apart from the black-level offset and saturation. Normalisation to linear sensor-referred values is, per colour channel `c`:

`v_c = (N_c - B_c) / (W_c - B_c)`

where `N_c` is the raw number, `B_c` the black level of that channel and `W_c` the white (saturation) level. EFAS uses the camera-reported saturation level when the file gives one, because it can lie well below the nominal white level (section 10a). [S: the DNG specification defines BlackLevel, WhiteLevel and linearization tags for this purpose (read via a search summary; the Adobe PDF itself returned HTTP 403); LibRaw documents `color.black`, `color.cblack`, `color.maximum`, `color.linear_max`] LibRaw's own post-processing scales `65535*(x-black)/(white-black)`, and applies white balance, colour matrix and a gamma curve unless told not to. [S: LibRaw forum/docs]

Things that silently break linearity if left at defaults, and what EFAS does about them [D, from LibRaw's documented parameters]:

| Default behaviour | Problem for measurement | EFAS setting |
|---|---|---|
| Output gamma curve (rawpy default tone curve) | Not linear | `gamma=(1, 1)` |
| Automatic brightness | Scene-dependent gain | `no_auto_bright=True`, `bright=1.0` |
| `adjust_maximum_thr=0.75` | LibRaw may lower the white level to the file's actual maximum, so scaling depends on image content | `adjust_maximum_thr=0` |
| Camera white balance multipliers | Channel-dependent gain; would shift per-channel D-min by `-log10(multiplier)` | `user_wb=[1,1,1,1]`, `use_camera_wb=False` |
| Colour matrix to sRGB | Mixes channels; densities of a band are no longer a single band | `output_color=raw` |
| 8-bit output | Quantisation | `output_bps=16` |
| Highlight reconstruction | Invents data | `highlight_mode=Clip` |

The display pipeline (existing, unchanged) keeps using camera white balance and the usual colour/gamma path. The two pipelines are separate: **the measurement pipeline never receives anything the editing pipeline does**, and nothing from the measurement pipeline is fed back into display edits in Tier 1. [D]

### 4.2 Camera response model

For one colour channel, ignoring sensor non-linearity:

`v_c = k_c * T_c + f_c`

where `T_c` is the film's transmittance in that camera band, `k_c` is a constant for a given set-up (backlight level x shutter x aperture x sensor gain x spectral overlap), and `f_c` is unwanted additive light: lens/box flare, light leaking around the frame, and residual black-level error. [D: the model; K for flare being additive and veiling [S: Imatest notes that veiling glare fogs images and limits real dynamic range]]

Define three densities:

1. **Camera-relative density** `D_rel,c = -log10(v_c)`. It equals the true band density plus an unknown constant, `D_c - log10(k_c)`, so it is **not** an absolute density. [D]
2. **Transmission density** `D_c = -log10(v_c / v_clear,c)`, valid only when `v_clear,c`, the value of the same light source with no film at the same exposure, is known. In EFAS this requires the user to sample a clear (no-film) area or supply a flat field; otherwise it is not computed, not guessed. [D]
3. **Density above film base** `ΔD_c = -log10(v_c / v_base,c) = D_c - Dmin_c`. The unknown `k_c` cancels exactly (when `f_c` is negligible), so it is independent of the light level and exposure. This is the quantity that inversion fundamentally needs, and it is what a sampled film base gives. [D, follows from the model]

### 4.3 Flare and noise define what can be measured

Veiling glare is stray light that fogs the image and reduces contrast in shadow areas, and it limits real-world dynamic range far below what the sensor alone could do. [S: Imatest, ISO 18844 discussion] For a negative, the **densest** areas transmit the least light and are the ones lifted by flare, so a camera scan under-reports the highest densities. EFAS cannot measure the flare of a particular rig without a test target, so it does not correct it; it reports the limit as a warning.

Quantisation and noise set a floor: the smallest `v` that can be distinguished from zero. EFAS defines `v_floor,c = max(n_sigma * sigma_c, 2 / (W_c - B_c))`, with `n_sigma = 3` (a conventional detection threshold [K]) and `sigma_c` the read-noise estimate when available (section 6.3), otherwise the quantisation floor alone. [D]

## 5. Quantities and their definitions in EFAS

| Quantity | Definition | When valid |
|---|---|---|
| `v_c` | linear normalised sensor value | RAW: measured. TIFF/PNG/JPEG: **assumed** transfer function (see below) |
| `T_c` | `v_c / v_clear,c` | only with a clear reference |
| `D_rel,c` | `-log10(max(v_c, v_floor,c))` | always (RAW) |
| `D_c` | `-log10(T_c)` | only with a clear reference |
| `Dmin_c` | density of the sampled film base | measured if the user sampled base; **estimated** otherwise |
| `ΔD_c` | `D_rel,c - Dmin_rel,c` | needs Dmin |
| `Dmax_c` | highest density above base, robustly estimated | measured or system-limited (flagged) |

Non-RAW inputs (16-bit TIFF/PNG from a scanner, JPEG): the encoding is not known. EFAS offers `linear`, `sRGB` or `gamma 2.2` and defaults to **sRGB, flagged "assumed"**. [D] A scanner's linear TIFF is common, and the user can switch it in Advanced Mode. 8-bit sources are also flagged for their coarse steps in dense areas.

## 6. Algorithms

### 6.1 Linear decode (`features/densitometry/linear.py`)

`decode_linear_raw(path)` calls LibRaw (via rawpy) with the settings in section 4.1, returns `float32` values in `[0, 1]` plus provenance: black levels, white level, per-channel camera white level when present, the list of steps, and the sensor's saturated-pixel fraction. It has the same orientation and size as the display decode so coordinates correspond. `from_display_referred(rgb, transfer)` linearises other inputs.

### 6.2 Film base, `Dmin` (`base.py`)

Input: the pixels of a user-picked patch (a small area of rebate). Method: per-channel **median of `v`**, then `Dmin_rel,c = -log10(median)`; with a clear reference the absolute `Dmin_c = -log10(median / v_clear,c)` is reported as well, and it is only then that the orange-mask ordering check runs. Dispersion is reported as the median absolute deviation in density; the pixel count and the fraction near the floor are reported. A patch whose spread is large (grain, dust, picture content) or that is saturated raises a warning. Automatic estimate (no sample): the low-density mode of the image, using per-channel low percentiles of density, always flagged **estimated**, with a lower confidence note. [D]

### 6.3 Dmax (`dmax.py`)

Dmax of *the film* is the highest density the material produces. A scan can only show the highest density it can *see*. EFAS therefore reports:

- `ΔD_p`, the density above base at a high percentile `p` (default 99.9) of the valid pixels, per channel, not the single darkest pixel. [D: robust against dust, sensor defects and noise]
- `ΔD_sys,c = log10(v_base,c / v_floor,c)`, the highest density above base the camera set-up could register above its floor.
- Status: **"measured"** if `ΔD_p` is below `ΔD_sys` by a margin (default 0.15), and the share of pixels at the floor is below 0.1 %; otherwise **"limited by the scan"**, and the value is a lower bound. [D]

Read-noise estimate `sigma_c`: from the sensor's optical-black margin when the RAW exposes one, else the quantisation floor. [D]

### 6.4 H&D tools (`hd.py`)

What can and cannot be known from a photograph: a photograph has densities but not the exposures that made them. EFAS therefore **never draws an H&D curve from a photograph**. The viewer shows three kinds of thing, each labelled differently:

1. **Measured / supplied curve**: points `(log10 H, D)` for R, G, B, read from a file the user supplies (for example from scanning a step tablet exposed with known steps, or a manufacturer's curve digitised by the user). Source and densitometry type are stored and displayed. EFAS ships **no** film curves, because I would have to invent numbers from images of plots. [D]
2. **Model curve**: a parametric toe/straight/shoulder curve, explicitly labelled "model (not measured)", for exploring how density range, gamma and knees interact. Structure (after NegPy's documented form [S]): straight line `v = D0 + γ (x - x0)`, then toe `v1 = Dmin + softplus(a_t (v - Dmin)) / a_t` and shoulder `D = Dmax - softplus(a_s (Dmax - v1)) / a_s`, with `softplus(z) = ln(1 + e^z)`. As `a -> infinity` these become hard limits at Dmin and Dmax.
3. **This photograph's occupied range**: a band marking the density interval the photograph occupies (Dmin..Dmax), drawn on the density axis only. When a curve is selected, the band is also converted to the log-exposure interval the curve implies, labelled "implied by the selected curve".

Curve analysis (`analyse_curve`): Dmin, Dmax, gamma from a straight-line fit over the most linear window, and average gradient between two configurable end points. **Default end points** [D]: the shadow end at density `Dmin + 0.10`, the highlight end 1.30 log-exposure units higher. This is a common convention in textbook-level descriptions [S, forum-level], is *not* asserted to be a Kodak or ISO standard, and is user-adjustable.

### 6.5 Density histogram (`histogram.py`)

Per-channel histograms of `D_rel` (and `ΔD` when Dmin is known) over valid pixels, with fixed bins in density units so histograms from different photos are comparable. Markers for Dmin and Dmax per channel. Pure functions.

## 7. Architecture

```
RAW file --(rawpy, linear settings)--> LinearScan (float32 v, provenance)   <- measurement pipeline
                                              |
                       user samples film base (framed like the picture)
                                              v
          densitometry.analyse() -> Measurement (Dmin, Dmax, ranges, histogram, diagnostics)
                                              |
           Simple Mode: "Film Base" status only        Advanced Mode: panels read Measurement

RAW file --(existing display decode)--> editing pipeline --> inversion --> export   <- UNCHANGED in Tier 1
```

- `features/densitometry/` is pure Python/numpy with no Qt imports, so Simple and Advanced Mode, tests and a future command-line tool all use the same engine. [D]
- The linear scan is decoded off the interface thread, once per photo, kept at preview size (area-averaged in the linear domain, which is the physically correct way to average light), and framed with the same rotation/flip as the picture so a click on the picture maps to the same place in the linear scan.
- The sampled film base, and the optional clear-light sample, are stored **in linear sensor units** per folder (a roll shares a rebate and, usually, a set-up), in a new table. Display-referred base colours already stored are untouched. This assumes the light and the camera exposure did not change across the roll; if some frames show areas *brighter than the film base*, which is physically impossible for a negative, a warning says the sample no longer matches. [D]
- No measurement result is written back into any edit.

## 8. What a DSLR scan can and cannot establish

| Quantity | Can EFAS establish it? |
|---|---|
| Linear sensor values | Yes for RAW (black/white normalisation, section 4.1). Assumed for other formats. |
| Per-channel density above film base | Yes, to the extent the sensor is linear and flare is small. |
| Absolute transmission density | Only with a clear-light reference at identical exposure. |
| Status M density | **No.** Camera bands differ; the app reports camera-band density. |
| Film D-min | Yes, if the user samples unexposed base. |
| Film D-max | Usually **no**: the scan limit (noise, flare, single exposure) is reached first. EFAS says which. |
| True H&D curve | Only from user-supplied exposure-density data. Never from a photograph alone. |
| Scene exposure / dynamic range | Only via a supplied curve. |

Scanning set-up factors that move the results: backlight spectrum (CRI, narrow-band LEDs), backlight uniformity, camera exposure (expose to the right without clipping, per darktable's guidance [S]), lens flare, film flatness, and film scattering (diffuse vs. collimated light changes measured density; the "Callier effect" [K]).

## 9. User interface

Progressive disclosure, one engine.

**Simple Mode (default)**: the Negative tab shows film type, **Sample Film Base** with a plain-language hint, and the existing Auto controls. No density terminology. A "Show details" link opens Advanced Mode. Hint text: *"Film Base: tell EFAS which part of the scan contains unexposed film. EFAS uses this to understand the colour of your film base and improve the inversion."* After sampling, a one-line status: "Film base measured".

**Advanced Mode** (a checkbox in the Negative tab, remembered): reveals expandable panels, each collapsed until opened:

1. **Density**: table: Dmin R/G/B, Dmax R/G/B, density range, transmission range, value under the cursor, and for each value whether it is measured, estimated or limited by the scan, with units and tooltips.
2. **Density histogram**: per-channel density histogram with Dmin/Dmax markers; a switch between camera-relative density and density above film base.
3. **Sensitometry**: the H&D viewer: supplied curve, model curve, occupied range; readouts of gamma and average gradient; a banner stating exactly what kind of curve is on screen.
4. **Calibration and diagnostics**: black/white levels, input encoding, processing steps, assumptions, warnings (clipping, noise floor, flare caveat, unusual D-min ordering), and a confidence summary.

Derived simple controls (Shadow Recovery, Highlight Recovery, linked to the model) are Tier 2, since they need the inversion to run on the density engine.

## 10. Verification plan

Automated, using synthetic data and exact mathematics:

- `v = (N-B)/(W-B)` against hand-computed values, per-channel black levels.
- `D = -log10(T)`: T = 1, 0.1, 0.01 give 0, 1, 2; density of stacked layers adds; known synthetic "film" with chosen densities and an arbitrary light level recovers `ΔD` exactly regardless of the level (the cancellation in section 4.2).
- Dmin: patch of known transmission with noise recovers the right density; wrong-ordering warning.
- Dmax: synthetic ramp reaching a known density is "measured"; one reaching below the noise floor is "limited by the scan"; single hot/dead pixels do not move the result.
- Histogram: counts conserve; known two-level image gives two peaks at known densities.
- H&D: model with large sharpness equals the clipped straight line; slope in the middle equals gamma; monotonic; analysis recovers gamma and Dmin/Dmax from a synthetic curve; average gradient equals the chord slope; profile files round-trip and reject bad data.
- Linear RAW: on a real CR2, the decoded values equal `(raw - black)/(white - black)` at raw green sites to within rounding (skipped when the file is absent).
- Regression: all existing tests, plus the existing inversion output is bit-identical before and after.

## 10a. Implementation status (Tier 1, as built)

| Objective | Status | Where |
|---|---|---|
| 1. Linear RAW, normalised | Done. Verified against the sensor data of a real Canon CR2: the decoded value equals `(N - black) / (saturation - black)` at the red, green and blue sites to within 5e-5 (16-bit rounding). | `features/densitometry/processor.py`, `linear.py` |
| 2. Optical density as the internal representation | Done: camera-relative density, density above base, and (with a clear sample) absolute density; transmission relative to base. | `linear.py`, `analysis.py` |
| 3. Per-channel Dmin | Done: sampled patch (median, spread, warnings) or an estimate flagged as such. Stored per folder in linear units. | `base.py`, `edit_store.py` |
| 4. Per-channel Dmax | Done: robust percentile; "measured" versus "limited by the scan" per channel. | `dmax.py` |
| 5. Density histogram | Done: separate from the RGB histogram; above-base and camera-relative views; Dmin/Dmax markers. | `histogram.py`, `scientific_panel.py` |
| 6. H&D viewer | Done for supplied curve data and the labelled model; never drawn from a photograph; curve analysis (gamma, average gradient). **No film curves are bundled.** | `hd.py`, `profiles.py` |
| 7. Scientific measurement UI | Done: Density, Density Histogram, Sensitometry and Calibration/Diagnostics panels, behind an Advanced Mode switch. | `scientific_panel.py` |
| Simple Mode wording | Sample Film Base, plain-language hint; no density terms unless Advanced Mode is on. | `negative_tool_panel.py` |
| Derived Shadow/Highlight Recovery controls | **Not done.** Needs the inversion to run on the density engine (Tier 2). | |
| "Inversion model" panel (channel parameters, crosstalk, film profile) | **Not done**, for the same reason; the Calibration panel states that the current inversion is the unchanged existing method. | |
| Film profile selection (e.g. a stock list) | **Not done**: bundling profiles would mean inventing numbers from graphs. User-supplied curve files are supported. | |

What validation found, and what changed because of it:

- **Saturation level.** On the real CR2, LibRaw reports `white_level` 16383 but the camera's own per-channel white level is 14008. Normalising to 16383 would make 1.0 unreachable and hide clipping, so EFAS divides by the camera-reported saturation level when the file provides one (section 4.1 originally said "white level"). Only a constant factor changes (identical in all channels), so density above base is unaffected.
- **Channel gains are real.** On the same file the camera-relative Dmin came out as roughly 0.72 / 0.49 / 0.82 for R / G / B. That is the backlight and sensor gain, not the film, which confirms why camera-relative values are never compared across channels and why the orange-mask check waits for a clear-light sample.
- **Scan limit is visible.** The test scan was exposed low (mean sensor value about 0.03 of full scale), and the engine correctly reported Dmax in two channels as limited by the scan, not by the film.
- **Expected differences** that are not bugs: the analysis leaves out a 12% margin (the same default as the existing metering), so the densest point at the very edge of a frame is not counted; the model curve's mid-slope equals gamma only when its knees are sharp.

Coordinates: the film-base click happens on the raw scan view. The linear scan is rotated, flipped and straightened with the same operations as that view, and a test asserts the two have identical dimensions, so a click maps to the same pixel in both.

## 11. Open items and limits

- [?] Primary definitions of Kodak "contrast index" and ISO average-gradient end points were not obtained. EFAS exposes configurable end points and says so.
- [?] The Adobe DNG specification PDF could not be fetched (HTTP 403); the black/white-level formula rests on LibRaw documentation and consistent secondary descriptions.
- [?] Typical D-min values per stock are not bundled. They would need Kodak/Fujifilm numeric data that was not available as text (the Kodak sheets contain the curves as graphics).
- Camera spectral sensitivities and backlight spectra are unknown; no Status M conversion is attempted.
- Flare is flagged, not corrected.
- 8-bit and unknown-encoding inputs give approximate results and are labelled.

## 12. Sources consulted

- Kodak Professional Portra 400 technical data, publication E-4050 (January 2025): characteristic curves in Status M, log-exposure axis in lux-seconds, spectral dye density curves, "judging negative exposures" with Status M red densities (gray card 0.77-0.87). Text extracted from the PDF.
- Kodak, "LAD for Duplicate Negatives" H-61D: Status M aim densities 0.90 R / 1.30 G / 1.70 B (±0.12), the orange-mask hue of D-min.
- darktable user manual, *negadoctor* module (5.0): https://docs.darktable.org/usermanual/5.0/en/module-reference/processing-modules/negadoctor/
- RawPedia, Film Negative: https://rawpedia.pixls.us/film_negative/
- NegPy: https://github.com/marcinz606/NegPy, `docs/PIPELINE.md`
- Wikipedia: Absorbance (optical density), Densitometer, Characteristic curve (photography), Cineon, Hurter and Driffield.
- LibRaw API documentation (data structures: black, cblack, maximum, data_maximum, linear_max; params gamm, no_auto_bright, no_auto_scale, user_black, user_sat, output_bps, output_color, highlight) and LibRaw forum discussions on linear output; rawpy documentation.
- ISO 5-2 (geometric conditions) and ISO 5-3 (spectral conditions): catalogue entries only; the standards themselves are paywalled.
- Imatest, "Measuring the impact of flare light on dynamic range" and ISO 18844 pages.
- Adobe DNG specification (not retrievable; secondary summaries only).
- Photrio / large-format forum threads on D-max, characteristic curves and Kodak contrast index (practitioner-level; used only where tagged "forum-level").

## 13. Scan merging, roll checks and colour targets (technical notes)

Details of the scanning tools in the [scanning guide](scanning-and-export-guide.md).

- **Bracket merge.** Each frame i is scaled to the shortest exposure's units by t_ref / t_i. A pixel is used from a frame only if it is below 0.95 (not clipped) and above 1.5 times the noise floor. Weights are the inverse of the variance in the scaled units, (t_ref / t_i)^2 (sigma^2 + 2e-5 v), where sigma is the frame's read noise and the second term is a shot-noise allowance. A pixel valid in no frame falls back to the shortest frame and is counted in the "lost" share. The reported shadow-noise gain is sigma_first divided by the effective sigma, with effective sigma^-2 = sum over frames of (t_i / t_ref)^2 sigma_i^-2.
- **Exposure-time check.** Where two frames are both mid-range, the median of (signal_i / signal_ref) (t_ref / t_i) should be 1. A deviation over 2% is reported; optionally the measured ratio replaces the stated time.
- **Alignment.** A shift is estimated on log density of the green channel (so exposure and colour do not matter), with blown or empty places filled smoothly from their surroundings (a flat patch stays put while the picture moves and biases the estimate). Phase correlation gives a coarse shift and enhanced correlation on high-passed images refines it, to about 0.03 pixel on synthetic fields. Only translation is modelled; shifts over 25 pixels are not applied.
- **Merged file.** A 16-bit TIFF scaled so the top of the data sits near 0.92 of the code range, plus a JSON sidecar with the scale back to linear values, the noise estimate and what was merged. Without the sidecar the file is read as an ordinary picture.
- **Roll consistency.** The film base of each frame (from its clear border where found, otherwise the thinnest 1% of the central picture) is compared with the median base of the roll in stops of brightness and in red/green and blue/green ratios. Notes at 0.12 stops (0.10 for colour), warnings at 0.25 (0.20); estimated bases are judged at twice those limits.
- **Colour target.** Transmittance t = patch / clear light is mapped to XYZ (D50, relative to clear light = white) by a matrix M with M(1,1,1) = white, which leaves six free numbers. They start from a least-squares fit and are refined by Levenberg-Marquardt on the Delta E 2000 of every patch. The baseline is the camera channels treated as sRGB primaries. A five-fold hold-out gives the error on unseen patches.
