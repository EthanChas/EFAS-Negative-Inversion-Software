# EFAS Tier 2: sensitometric curve fitting, calibration workflows, film profiles, and curve-informed inversion

Status: design, written before the implementation and updated to match what was built (section 13 records the result). It builds on `docs/scientific-inversion-design.md` (Tier 1); read that first for the density equations and the evidence tags used here.

Evidence tags: **[S]** sourced (read in a document or page during research, listed in section 14), **[K]** standard knowledge not re-read from a source, **[D]** EFAS design decision, **[?]** not established.

## 0. Principles

1. **A measurement needs known inputs.** A characteristic curve is density against *known* exposure. EFAS never creates a measured curve from arbitrary image samples. Every curve carries its provenance, and the user interface says whether it is *measured*, *supplied*, *fitted* or *model*.
2. **Separate four things** and never blur them: measured optical density; estimated exposure (density pushed through a curve); reconstructed positive values (exposure normalised to a white reference); aesthetic rendering (tone curve, colour).
3. **Uncertainty is reported, not hidden.** Every fitted or derived number gets an uncertainty or a validity range, and a plain-language confidence label.
4. **Optional until validated.** The curve-informed inversion is off by default, per photo, and cannot change an existing project or preset.
5. **One engine, two presentations.** Everyday Mode shows guidance; Advanced Mode shows the data. Both read the same objects.

## 1. What Tier 1 already provides (audit)

| Capability | State in the code | Tier 2 action |
|---|---|---|
| Linear RAW normalisation, noise floor, saturation (`linear.py`, `processor.py`) | Implemented, verified against sensor data | Reuse. Add flare-fraction correction (section 8). |
| Density, density above base, absolute density with a clear sample | Implemented | Reuse. |
| Per-channel Dmin from a sampled patch (`base.py`) | Implemented, stored per folder | Reuse. |
| Dmax percentile with "limited by the scan" (`dmax.py`) | Implemented but **conflates causes** (noise floor, sensor clipping, film limit) | Replace the labelling with a cause classification (section 7). |
| Density histogram, Density/Calibration panels | Implemented | Extend. |
| `ModelCurve` (softplus knees), `straight_line`, `average_gradient`, `analyse_curve` (`hd.py`) | Implemented. The straight-line finder is a heuristic (longest run within 90% of peak slope) with no uncertainty. | Keep as the *model* family; add fitting with uncertainty and model comparison; derive gamma from fits. |
| User curve files (`profiles.py`: `CurveSet`) | Implemented, JSON/CSV, flat | Superseded by the versioned film profile (section 6); old files still load and convert. |
| Curve-informed inversion | **Not implemented** (Tier 1 stated this) | New (section 9). |
| Calibration of the camera as an instrument | Black/white/saturation/noise only | New (section 8). |

Tier 1's average-gradient end points (density 0.10 above base, +1.30 log H) are now tied to a source: they are the geometry of the ISO 6 speed criterion for **black-and-white** negatives. [S: secondary description of ISO 6:1993 in search results; the standard is paywalled] It must not be presented as the colour-negative criterion. ISO 5800 (colour negative speed) uses a different construction that EFAS cannot verify. [?]

## 2. Research findings

### 2.1 How a real characteristic curve is made

A characteristic curve comes from a **sensitometric exposure**: film is exposed to a series of known exposures, processed in a controlled way, and the resulting densities are measured. In a type Ib (intensity scale) sensitometer the usual modulator is a **step tablet in contact with the emulsion** (with a thin acetate cover), the shutter admits light for a set time, and the exposure at each step depends on the step's transmittance; density, the log of reciprocal transmittance, is the convenient way to describe each step. [S: SMPTE RP 14-1997] Therefore at step *i* with tablet density `D_i`:

`log10 H_i = log10 H_0 - D_i`

where `H_0` is the exposure through a clear aperture. The *relative* log-exposure scale (`-D_i`) is known from the tablet alone; the *absolute* scale (`H_0`, in lux-seconds) needs a calibrated light source and time. [D: follows from the cited relation] A curve on a relative scale still gives Dmin, Dmax, gamma, any gradient, and the shape; it does not give film speed.

Facts from the same practice [S: SMPTE RP 14-1997], used as validation rules in EFAS:

- Typical tablet increment is 0.15 diffuse transmission density, but real tablets deviate, so densities must be taken from the calibration chart or measured with a calibrated densitometer, and the data plotted against **actual** step densities, not nominal ones.
- Tolerance for a tablet to be treated as nominal: adjacent increment 0.150 ± 0.015; any step within 0.02 density or 2% of nominal; no step more than 0.02 from the best linear fit through all steps. Cumulative errors in one direction matter and can mislead.
- Step tablets are delicate and drift slowly; they should be checked from time to time.

Kodak's No. 2 tablet has 21 steps of about 0.15 density, ranging from about 0.05 to 3.05, with individual steps varying slightly. [S: forum and vendor-level description in search results] Kodak's own data for negative film are published as characteristic curves in **Status M** against log exposure in lux-seconds for a stated exposure (E-4050: daylight, 1/50 s). [S] Colour negative film has separate curves for its three dye layers. [S]

### 2.2 What an ordinary camera step-wedge photograph can and cannot do

Photographing a backlit step tablet with a camera tests the **camera as a densitometer**, not the film. It shows whether the camera's response follows `v = k T + f` (linear, with an offset `f` from flare and black-level error) and how far down in transmission it stays accurate. Veiling glare limits the measurable range of real imaging systems well below sensor capability. [S: Imatest, ISO 18844 discussion] Masking the light box and keeping the tablet slightly out of focus reduce stray light and lens artefacts. [S: practitioner method, W. L. Castleman's step-tablet dynamic-range tests]

It does **not** characterise a film. To characterise a film the film must have been exposed through the tablet (or another known-exposure series) and developed; the *scan of that strip* is then measured. A tablet photographed through a camera lens as the subject also exposes the film with lens flare mixed in, so its exposures are not those of the tablet. [D: follows from the flare statement above]

### 2.3 Sensor linearity

EMVA 1288 defines **linearity error** from a linear regression of signal against exposure (here, exposure time at constant light), as the mean of the most positive and most negative deviation in percent, over an illumination range from 5% to 95% of saturation. [S: Wikipedia "EMVA1288" and Imatest/arXiv descriptions] EFAS adopts the same statistic for its optional linearity test, with the caveat that EFAS does not control the light source's stability (flicker, LED pulsing) and relies on the shutter-time metadata being accurate. [D]

### 2.4 Curve representations

- **Logistic.** Logistic functions fitted by least squares have long been used for characteristic curves, including colour negatives (Bayer, Simonds and Williams, 1961, is cited as the early attempt). [S: search results] A plain logistic is symmetric, so it cannot give a toe different from the shoulder; a generalised (Richards) logistic adds an asymmetry parameter. [K]
- **Toe / straight line / shoulder with soft knees** (the structure NegPy documents, and EFAS's Tier 1 `ModelCurve`): a straight line of slope gamma bounded below at Dmin and above at Dmax by softplus knees of separate sharpness. [S: NegPy PIPELINE.md]
- **Monotone piecewise cubic interpolation** (Fritsch and Carlson, 1980): an interpolant through data that preserves monotonicity and does not overshoot; derivatives from a weighted harmonic mean of adjacent slopes, set to zero where the slope changes sign or vanishes. [S: SLATEC/SciPy PCHIP documentation] It assumes no universal shape, so it is the right *non-parametric* representation of a measured curve. [D]

EFAS therefore offers **three representations** and chooses between them with cross-validation instead of imposing one:

1. `pchip`: always available; passes through the measured points; gives derivatives; no uncertainty beyond measurement error.
2. `softplus`: the Tier 1 model, now fitted; five shape parameters (Dmin, Dmax, gamma, a position, plus two knee sharpnesses).
3. `richards`: five-parameter generalised logistic for asymmetric curves.

Leave-one-out cross-validation error, residual structure and parameter uncertainty decide which parametric model, if any, is *supported* by the data. If none passes the quality gates, EFAS reports PCHIP only. [D]

### 2.5 Gradients

- **Local gradient** `G(x) = dD / d log10 H`. It is zero at the base, rises through the toe to the straight-line gamma, and falls through the shoulder. [S: consistent with Wikipedia "Characteristic curve" and Kodak-style descriptions of the regions]
- **Gamma** is the slope of the straight-line portion. [S]
- **Average gradient** is the slope of the straight line joining the two end points of a chosen segment. [S: forum-level]
- **ISO 6 geometry** for black-and-white negatives: the speed point is 0.10 above base plus fog, and the curve must reach 0.80 more density 1.30 log H units to the right (average gradient 0.80 / 1.30 ≈ 0.615). [S: secondary]
- Kodak's **contrast index** uses its own construction, whose exact definition I could not obtain. [?] EFAS does not compute it.

Gradients are dimensionless (density per unit of log10 exposure). EFAS always reports the exposure interval used.

### 2.6 Uncertainty and robust statistics

First-order propagation of a linear-signal uncertainty into density: `sigma_D = sigma_v / (v ln 10)`. [K, the usual propagation of uncertainty for `D = -log10 v`] Parameter uncertainty of a least-squares fit from the Jacobian: `Cov = s^2 (J^T J)^-1`. [K] For useful density bounds, EFAS uses percentiles with a **block bootstrap** over image tiles (resampling tiles, not pixels, so spatial correlation is respected) to give a confidence interval, and median-absolute-deviation outlier screening for patches. [D, standard methods]

### 2.7 How other software handles it

| Software | What it does | Source |
|---|---|---|
| darktable negadoctor | Film base, Dmin/Dmax, scan exposure bias, then a printing model `(RGB*exposure + black)^grade`; no measured curve of the film. | [S] manual |
| RawTherapee Film Negative | Per-channel power law with a reference exponent and R/B ratios; exponents can be derived from two neutral picks. | [S] RawPedia |
| NegPy | Density-space print model with an H&D-style curve; cast removal per channel; no measured film characterisation. | [S] PIPELINE.md |

None of them characterise the film from known exposures. EFAS Tier 2 does, when the user supplies the data. For ordinary scans without that data it keeps the existing method.

## 3. What can and cannot be done from ordinary camera scans

| Feature | Ordinary scan of a photo | Needs known exposures / calibrated target |
|---|---|---|
| Density, film-base Dmin, Dmax with cause analysis, histograms | Yes | No |
| Camera noise floor, saturation, headroom advice | Yes | No |
| Sensor linearity test | Needs a bracketed series of one static backlit scene | A series of exposures (times from metadata) |
| Camera flare fraction `phi`, offset `f`, usable density range | No | A calibrated transmission step tablet backlit |
| Film characteristic curve, gamma, gradients, shape | **No** | A developed strip exposed through a step tablet (or other known-exposure series) |
| Film speed | No | Calibrated absolute exposure |
| Status M density | No | Spectral data or a calibrated densitometer |
| Curve-informed inversion | Only with a profile that holds a measured or supplied curve | Same |

## 4. Fitting (`fit.py`)

Inputs: `x_i` = relative log10 exposure (or absolute if known), `y_i` = density above base per channel, `sigma_i` = per-point density uncertainty (from patch spread and the noise floor, floor 0.005 density). Weighted least squares, Levenberg-Marquardt written in numpy (no scipy; the packaged build excludes it). Parameters are transformed to keep Dmax above Dmin, gamma and the sharpnesses positive.

Outputs (`FitResult`): the chosen representation, parameters with standard errors, `rms`, `max_abs_residual`, reduced chi-square against the stated uncertainties, a runs test on residual signs (a systematic bend shows as long runs), leave-one-out cross-validation RMS, the **supported range** (min to max measured log exposure), a quality label (`good`, `fair`, `poor`), and reasons. Poor fits are named (for example "the residuals form two long runs: the model is too stiff for this curve") and PCHIP is recommended instead.

Fits are per channel and independent; EFAS does not tie the three layers together.

## 5. Gradient analysis (`gradient.py`)

- `local_gradient(curve, x)` from the analytic derivative of a fit or from PCHIP.
- `average_gradient(curve, x1, x2)`: chord slope over a stated interval, with the interval returned.
- `iso6_geometry(curve)`: density at `Dmin + 0.10`, the exposure 1.30 higher, the density rise and the implied average gradient, labelled B&W-negative speed-criterion geometry; not computed for colour negative curves unless the user asks.
- `gamma(curve)`: the maximum local gradient within the supported range, with the exposure interval where the gradient is within 90% of it.
- `regions(curve)`: toe, straight, shoulder boundaries from the gradient profile.
- `guidance(curve)`: plain-language **shadow separation / midtone contrast / highlight compression** from the gradient in the lowest, middle and highest thirds of the density range, relative to gamma. The text states that it describes the film's response over the measured range, not the scene.

## 6. Film sensitometry profiles (`film_profile.py`)

A versioned JSON document (`format: "efas-film-profile"`, `version: 1`) with these sections:

- `identity`: id (uuid), name, film stock (optional), process (optional), notes, created, modified, `derived_from`.
- `kind`: `measured`, `supplied`, `estimated` or `generic`. Only `measured` and `supplied` can feed the curve-informed inversion; `estimated` and `generic` never do. No `generic` data is bundled.
- `base`: per-channel Dmin, as camera-relative values with the set-up, or absolute density when a clear reference was used; the sampled patch statistics.
- `curves`: per channel, the measured samples `[x, y, sigma, used]`, the exposure scale (`relative` or `absolute` with unit), and for each fitted representation its parameters, standard errors and quality record.
- `gradients`: derived summaries with their intervals.
- `calibration`: target type, reference densities (actual and nominal), light source, camera and settings, processing conditions, tablet certificate reference, calibration date.
- `conditions`: reference illuminant or measurement description; densitometry type (always "camera-band" unless the user states otherwise).
- `validity`: supported exposure range, supported density range, scan set-up it was made with.
- `uncertainty`: aggregate numbers and the confidence label.

Rules: load validates every field and rejects unknown versions with a clear message; unknown fields are preserved; film identity is optional so an unknown-film user is never forced to assign one; a profile never claims that all rolls of a stock behave identically (the interface repeats this). The store lives in `profiles/` in the data folder (`ProfileStore`: list, load, save, duplicate, delete, import, export, compare). Tier 1 curve files convert to `supplied` profiles.

## 7. Density-based diagnostics (`diagnostics.py`)

For a measured scan EFAS classifies pixels, per channel, into mutually clear categories with an **evidence status** each:

| Category | Test | Evidence |
|---|---|---|
| Sensor clipped | `v >= saturation level` (thin areas of a negative) | measured (RAW) |
| Below the noise floor | `v <= floor` (dense areas) | measured; **cause unknown** unless headroom analysis points to the light/exposure |
| Noise limited | `floor < v <= snr_min * sigma` (signal-to-noise below a threshold, read noise only) | inferred (shot noise is not modelled: no gain data) |
| Usable | otherwise | measured |
| Invalid | non-finite, or a Dmin sample that failed | measured |

Cause statements follow only from evidence:

- **Headroom**: if the film base reads below about 70% of sensor saturation, raising the exposure by `log10(0.85 / v_base)` density-equivalents would extend the measurable density by that amount. EFAS states the number of stops and says the limit is *camera exposure / light level*, which the user can change. [D, from `v = k T + f`]
- **Film limit**: EFAS can only suggest the film's Dmax is being reached ("inferred") when the signal in the densest areas is **well above** the noise floor (at least 10 sigma) and the density histogram shows a plateau at the dense end; otherwise it says it cannot tell. It never reports an area as film-limited when the scan could be the cause. [D]
- Dmax and Dmin get **block-bootstrap confidence intervals** (tiles resampled), and isolated extremes are excluded by the percentile and by a MAD screen on tile statistics.
- The share of affected pixels is reported for each category.

## 8. Camera and scanning calibration (`scanner.py`, `setup_profile.py`)

What EFAS can calibrate with accessible equipment:

| Quantity | How | Reference needed |
|---|---|---|
| Black level, saturation, noise | From RAW metadata and optical-black margin (Tier 1) | none |
| Linearity error | Bracketed exposure times of one static backlit scene; EMVA-1288-style statistic (section 2.3) | stable light; trustworthy exposure times |
| Gain `k`, offset `f`, flare fraction `phi = f / k`, usable density range | Photograph a calibrated transmission step tablet; weighted fit of `v = k * 10^-D + f` per channel against the **actual** tablet densities | calibrated tablet densities (certificate or densitometer) |
| Illumination uniformity | Statistics of a clear-light frame | none |
| Lens transmission, spectral response of the light source/camera bands | not measurable with EFAS | spectral equipment or manufacturer data |

What this does **not** establish: white balance is not spectral calibration; normalised RAW values are not absolute transmission unless a clear reference is used, and then only in the camera's bands; a tablet's visual density is not guaranteed equal in the camera's bands (it is nearly so for a neutral tablet). [D] Results from the calibration are labelled "camera-band, calibrated against the stated tablet", never "Status M" and never "laboratory grade".

Flare correction (optional): with the clear value `v_clear = k + f` and `phi` from the setup profile, `T = (1 + phi) * v / v_clear - phi` and the density follows from `T`. Veiling glare depends on the scene, so this is valid only for a set-up like the one calibrated and is off by default. [D]

A **setup profile** stores camera, lens, light source description, settings, black/saturation/noise, linearity error, `phi`, usable density range and the date; it can be reused for later rolls.

## 9. Curve-informed inversion (`inversion.py`)

Chain, each step labelled by what it is:

1. **Measured**: `dD_c = log10(v_base,c / v_c)` per channel (flare-corrected if a setup profile with `phi` and a clear sample are in use).
2. **Estimated exposure**: `x_c = f_c^-1(dD_c)`, the inverse of the profile's monotone curve for that channel (PCHIP or a supported fit). Density below the curve's lowest measured value or above its highest is **out of support**: it is clamped to the supported end (never extrapolated silently) and counted.
3. **Reconstructed positive**: `E_c = 10^(x_c)`, divided by a white reference per channel (the 99.5th percentile of `E_c` over the picture region by default, or a user-picked neutral). The white reference is an *assumption*, because the original scene and light are unknown, and it is the part that fixes colour balance.
4. **Aesthetic rendering**: the sRGB OETF for display. [D]

What this does not recover: layer spectral sensitivities, dye cross-talk, processing differences from the profile's, the light source of the original scene. The result is **film-band relative exposure**, not scene colorimetry. Where no usable profile is selected the engine is unavailable and the existing inversion runs, with the reason shown.

Integration: the engine choice (`classic` default, `curve`) and the profile id are stored per photo; edit states without the keys are `classic`, so no existing project or preset changes. Look and module presets do not contain the keys. The curve result enters the pipeline as the picture the edits start from (like a positive), so crop, rotation, tone and colour edits work unchanged. Export computes the same result at full resolution. An **A/B comparison** shows both inversions with numbers.

Validation (synthetic, section 11): a scene with known relative exposures passes through known per-channel curves; the curve-informed result recovers the exposures to numerical precision when the profile matches, and EFAS reports the error of the existing method against the same truth. The classic method is a display-referred stretch whose purpose is a pleasing picture, so the comparison metric is the error in relative exposure and L*, not a verdict on its usefulness.

## 10. User interface

Everyday Mode: nothing new is required. If a profile is applied, one line of guidance appears under the film base (from `guidance()`), and a single option offers **Inversion method: Standard (default) / Curve-informed (experimental)**, enabled only with a usable profile and always showing how much of the picture lies outside the profile's measured range.

Advanced Mode additions (inside the existing Sensitometry panel and a new dialog):

- **Film Characterization dialog** (button in Sensitometry): tabs for *Scanner calibration (step tablet)*, *Film characterization (exposure strip)* and *Linearity test*. It shows the raw scan, takes two clicks (first and last patch centre), lays out evenly spaced patches, samples each, flags invalid ones (clipped, below noise floor, uneven, out of order) with reasons, takes tablet densities (start and increment, or a pasted list of actual densities with a warning when nominal), shows results and quality, and saves a profile.
- **Sensitometry plot**: measured points with error bars, fitted curve, supported range, residual strip, gradient plot, quality label.
- **Profile manager**: list, duplicate, rename/edit, import, export, delete, compare, apply.
- **Diagnostics**: the category table of section 7 with cause statements and the headroom advice.
- **A/B comparison** dialog.

## 11. Validation plan

Synthetic references with known truth (no tolerance guessed from appearance):

- **Curves**: curves generated from each representation with known parameters; recovery of parameters within the reported standard errors; noisy data (known sigma) gives coverage of the true value in about 95% of repeated trials for 2-sigma intervals; a deliberately wrong model (symmetric logistic data fitted by softplus and vice versa) is flagged by the residual-structure and cross-validation checks.
- **Gradients**: straight line gives its slope exactly; a logistic has the analytic derivative; average gradient equals the chord; ISO 6 geometry on a curve built to satisfy it.
- **Density**: `D = -log10 T` pairs, known per-channel base offsets, known `k` and `f`; flare correction recovers `T` exactly.
- **Calibration**: synthetic tablet photographs with known `k`, `f`, noise; recovered to within the fit's stated errors; tablets violating the RP 14 tolerances are warned; wrong ordering and clipped patches are rejected.
- **Linearity**: a perfectly linear series gives zero error; a series with known compression gives the known error by the EMVA-style statistic.
- **Diagnostics**: controlled clipping (known fractions), noise-limited areas, light-limited versus film-limited cases; the film-limit claim must *not* be made for a scan limited by the camera.
- **Profiles**: round trip, unknown fields preserved, version rejection, bad data rejected, Tier 1 files convert.
- **Inversion**: matching profile recovers relative exposure to numerical precision; out-of-support fraction is correct; classic versus curve error on identical synthetic scenes; state and presets without the new keys behave as before.
- **Regression**: all Tier 1 and existing tests; the classic inversion output bit-identical on a fixed array before and after.
- **Real data**: the CR2 scans in the test machine's film folder exercise the diagnostics and the linear decode (skipped elsewhere). No published sensitometric data could be fetched as numbers (Kodak and Fujifilm give curves as graphics), so there is no real-curve comparison; this is stated plainly in the report.

## 12. Failure cases handled

Too few patches, patches not monotonic in the expected direction, clipped or noise-floor patches, a tablet entered with nominal densities, a curve with a plateau at both ends (fit not unique), a Dmin patch that is not film base, a profile made at a different exposure than the scan being converted (EFAS warns when the base level differs strongly from the profile's), a profile whose supported range barely covers the picture, and a missing or deleted profile (the photo falls back to the standard inversion with a note).

## 13. Implementation status

Filled in after the build (section 13a).

## 14. Sources consulted

- SMPTE RP 14-1997 (reaffirmed 2004), *Plotting Data from Sensitometric Strips Exposed on Type Ib (Intensity Scale) Sensitometers*: step-tablet exposure in contact, 0.15 increments, tolerances, use of actual densities. Text extracted from the PDF.
- Kodak Professional Portra 400, E-4050 (January 2025): Status M characteristic curves against log exposure (lux-seconds), daylight, 1/50 s; spectral sensitivity and dye density curves (Tier 1 reading, reused).
- ISO 6:1993 (B&W negative speed), ISO 5800:1987 (colour negative speed), ISO 5-2 and 5-3: catalogue entries and secondary descriptions only; the standards are paywalled.
- EMVA 1288 (linearity error): Wikipedia, Imatest, arXiv lab-testing descriptions.
- Imatest, flare and dynamic range; W. L. Castleman, step-tablet camera dynamic-range method (practitioner).
- Fritsch and Carlson, *Monotone piecewise cubic interpolation*, SIAM J. Numer. Anal. 17(2), 1980: via SLATEC/SciPy PCHIP documentation.
- Logistic characteristic-curve fitting literature (Bayer, Simonds and Williams 1961, and later colour-negative studies): via search summaries only.
- darktable negadoctor manual, RawPedia Film Negative, NegPy PIPELINE.md (Tier 1 reading, reused).
- Fujifilm: product pages and datasheet listings located, but the numeric curve data are graphics, so no Fujifilm data are used. [?]
