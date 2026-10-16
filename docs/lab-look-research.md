# What a "lab look" is

Notes behind the **Lab Look** module and the Scanners (EFAS Original) presets: what a minilab's scan adds to a negative, from what labs, photographers and the scanners' makers have published. Most of it is hands-on description, not measurement, and it varies from lab to lab (an operator stands at the machine and nudges frames), so read it as tendencies.

## A lab scan is a finished print, not a measurement

A minilab scanner (Fuji Frontier SP-3000, Noritsu HS-1800, Pakon) does not hand back the negative's densities. It hands back the picture a print would have been: it analyses the frame, balances it, applies a tone curve tuned to the paper it was built to print on, and sharpens and cleans it. Labs describe a flat scan as "deliberately neutral, preserving as much data as possible", and a lab scan as technicians' adjustments to contrast, saturation and colour balance; the lab scan's histogram reaches closer to pure black and white.

Four ingredients recur in what people report:

1. **A tone curve with a soft black.** The printed black is not pure black: paper has a maximum density, and a lab scan's black is often "capped at dark grey". Photographers matching lab scans reach for lifted blacks and slightly lowered whites first.
2. **Compressed highlights.** The Frontier's HyperTone is reported to be heavy software tone mapping that makes it "virtually impossible to burn highlights" (one blogger, citing the SP-3000 manual, says it is the same thing as Fujifilm's D-Range Priority: a tone curve that compresses highlights and opens shadows, with a slight mid-contrast boost). The Noritsu applies lighter luminosity tone mapping.
3. **A colour interpretation, not neutrality.** Described consistently, though not measured: the Frontier is more saturated, favours the yellow-blue axis (cooler, cyan-blue shadows, golden skin tones) and is tuned to Fujifilm Crystal Archive paper; the Noritsu is softer in colour, favours the magenta-green axis (more neutral black, peach or pink skin, and a tendency toward green in the shadows of underexposed frames).
4. **Clean-up.** Grain suppression (smooth on the Frontier, sharper and more monochromatic on the Noritsu), sharpening, and dust removal.

## Frontier against Noritsu, as labs describe them

| | Frontier SP-3000 | Noritsu HS-1800 |
|---|---|---|
| Contrast | steeper curve, "punchy", "pre-graded" | flatter, "like a RAW file" |
| Black point | deep, rich, bluer; deep shadows can look slightly crushed | more neutral or muted; shadows sometimes slightly lifted; can go green on underexposed frames |
| Highlights | strongly compressed, hard to burn; "bloomy" in one lab's words | gentle roll-off, minimal clipping |
| Saturation | high | softer and lighter |
| Colour | cooler shadows (cyan / blue), golden skin | warmer midtones, peach or pink skin, magenta or green tint |
| Grain | smooth, suppressed | sharper |

A Harman guide for scanning its Phoenix film shows how far a lab can steer a scanner from its defaults: for the Frontier it recommends Hypertone on, a gradation (gamma) change of +4 in the shadows and -2 in the midtones, and saturation -3, because the defaults give "high contrast, high saturation scans"; for the Noritsu it recommends gradation correction on, Chroma 90 (a ten per cent saturation cut), and Auto Contrast settings around -3 and 5. The look is a set of knobs, not a fixed fingerprint.

## What the Fade and Glow sliders are

The program the built-in presets were converted from describes its two lab sliders as tonal compression at the two ends of the scale, added "for emulating historic lab scanners": **Fade compresses the tonality of the shadows** (positive: smoother shadows, less detail, no pure black; negative: expands the shadows, more contrast), and **Glow compresses the tonality of the highlights** (positive: smoother highlights with less visible detail, the brightest white a little darker; negative: a starker look with more highlight detail). Its author says a small amount of Fade matched a Noritsu scan's compressed shadows, and that the sliders can also help thin negatives. That agrees with the measurement of its output behind EFAS's curves (docs/presets.md): at the ends of the Glow slider the highlights bunch up or spread out while the midtones move to make room, and at the ends of the Fade slider the black rises into grey or sinks to pure black.

## What this means for EFAS

- **Lab Look is the right shape.** A soft black (Fade), highlight compression (Glow) and a colour balance that differs between shadows, midtones and highlights are the three things the sources agree a lab adds. Fade and Glow are tone curves of the ramp, in the 16-bit chain.
- **The presets' colour is only half the story.** The converted Frontier and Gold presets carry the original presets' slider values, which were set *on top of* a colour table (the original names a "Frontier" table for both). EFAS has no such table. The Frontier table is described as cooling the shadows and warming skin, so the sliders alone, which add warmth to the shadows, come out warmer than the real scanner. EFAS now has a stand-in for each table, **Lab Look > Scanner colour** (docs/color-mixer.md): a small cast per tonal range plus a chroma change, in the directions the sources describe. The sizes are estimates, because the sources agree on direction but give no numbers; the honest way to improve them is a measurement from side-by-side output of the same picture through each table.
- **Not covered.** HyperTone's scene analysis, the paper curve of Crystal Archive (no published curve was found), grain suppression, and the lab operator's own tweaks.

## Sources

- Carmencita Film Lab, "Frontier vs Noritsu: Round 2": https://carmencitafilmlab.com/blog/frontier-vs-noritsu-round-2/
- Optik Oldschool, "Frontier vs Noritsu: Why Film Scans Look Different": https://www.optik-oldschool.com/blogs/blog/why-we-prefer-frontier-scans-for-opticolour200
- J. B. Flanc, "The Art of Film Scanning: Frontier vs. Noritsu": https://jbflanc.substack.com/p/the-art-of-film-scanning-frontier
- Sebastian Schlueter, "The magic Fuji Frontier SP-3000": https://www.sebastian-schlueter.com/blog/2018/3/7/the-magic-fuji-frontier-sp-3000
- Fuji X Weekly, "Fujifilm Frontier Scanners & Dynamic Range Priority": https://fujixweekly.com/2021/09/12/fujifilm-frontier-scanners-dynamic-range-priority/
- Harman Photo, "Recommended scanning parameters, Phoenix 200" (Oct 2024): https://harmanphoto.co.uk/wp/wp-content/uploads/sites/3/2024/10/Phoenix-Scanning-Parameters-011024.pdf
- Fujifilm, Image Intelligence (ICIS 2006 paper): https://www.imaging.org/common/uploaded%20files/pdfs/Papers/2006/ICIS-0-736/33740.pdf
- The Find Lab, "Noritsu vs. Frontier": https://thefindlab.com/2015/02/23/noritsu-vs-frontier/
