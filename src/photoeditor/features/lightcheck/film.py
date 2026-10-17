"""The film-scan check: was a roll of colour negatives scanned under a steady light, and was the exposure right? No Qt.

On every negative there is a strip of clear orange film around the picture (the film base), the bare light shows through the sprocket holes, and the holder is black. None of these
depend on the picture, so each is a test patch. For every scan the check finds them on the sensor's own values and reports how bright the clear film came out against what the
camera settings explain (a gap means the light, or the film, changed), the colour of the clear film and of the light in the holes (which tells a changed light from a different
film), how close the clear film is to blown out, how even it is toward the corners, and how much stray light reaches the black holder. Adapted from lightdrift by David Esquivel
(MIT licence), https://github.com/davidesqalv/lightdrift.
"""

import csv
import io
import os
import textwrap
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

from .bare import Finding, color_words, order_shots, pct, start_shots
from .capture import CHANNELS, Cancelled, CaptureError, load_planes, read_exif

FILM_BLOCK = 16             # block size, in per-channel pixels
FILM_EDGE = 0.08            # how far in from each side to look for the film base
CLIP_LEVEL = 0.98           # fraction of the white level counted as clipped
EXPOSURE_DIFF = 0.5         # stops brighter or darker than the reference worth noting
EXPOSURE_TOL = 0.15         # stops the settings don't explain, manual exposure
EXPOSURE_TOL_AUTO = 0.35    # the same with auto exposure, which records rounded shutter speeds
COLOR_TOL = 2.0             # % change in film base or light colour
UNDER_STOPS = 1.5           # film base this far below clipping counts as underexposed
NOISE_STOPS = 9.0           # densest film this far below clipping is in the sensor noise
EVEN_TOL = 5.0              # % points change in middle against corner (scan-to-scan noise is about 1-1.5)
STRAY_TOL = 0.5             # % points change in stray light
NEGATIVE_RB = 1.2           # a film base with R/B below this has no orange mask
SHUTTER_SPEEDS = ("1/8000", "1/6400", "1/5000", "1/4000", "1/3200", "1/2500", "1/2000", "1/1600", "1/1250", "1/1000", "1/800", "1/640", "1/500", "1/400", "1/320", "1/250",
                  "1/200", "1/160", "1/125", "1/100", "1/80", "1/60", "1/50", "1/40", "1/30", "1/25", "1/20", "1/15", "1/13", "1/10", "1/8", "1/6", "1/5", "1/4", "0.3", "0.4",
                  "0.5", "0.6", "0.8", "1", "1.3", "1.6", "2")


@dataclass
class FilmShot:
    path: str
    name: str
    exif: dict
    time: object = None
    minutes: float = 0.0
    f: dict = field(default_factory=dict)
    row: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)   # (kind, tag, text): what is worth a look about this scan


@dataclass
class FilmResult:
    shots: list
    ri: int                  # the index of the reference scan
    have_times: bool
    stops: object            # each scan's exposure from its camera settings, in stops (None when shutter or ISO are missing)
    use_aperture: bool
    findings: list          # Finding rows: the short answer
    bottom: str
    todo: list


# ---------------------------------------------------------------- settings
def _number(s):
    """'1/125', '5.6' or '100' as a float; None if missing or zero."""
    try:
        v = float(Fraction(str(s).strip()))
    except (ValueError, ZeroDivisionError):
        return None
    return v if v > 0 else None


def is_auto_exposure(exif) -> bool:
    return not exif or exif.get("Program") != "Manual"


def settings_stops(shots):
    """Each scan's exposure from its shutter, ISO and aperture, in stops. (None, False) if shutter or ISO are missing."""
    t, iso, n = ([_number((s.exif or {}).get(k)) for s in shots] for k in ("Shutter", "ISO", "Aperture"))
    if None in t or None in iso:
        return None, False
    use_n = None not in n
    return [float(np.log2(ti * si / (ni * ni if use_n else 1.0))) for ti, si, ni in zip(t, iso, n)], use_n


# ---------------------------------------------------------------- finding the parts of a scan
def film_blocks(planes):
    """Mean level and clipped fraction of each channel in each block."""
    b = FILM_BLOCK
    hb, wb = planes["R"].shape[0] // b, planes["R"].shape[1] // b
    split = {c: planes[c][:hb * b, :wb * b].reshape(hb, b, wb, b) for c in CHANNELS}
    return {c: split[c].mean(axis=(1, 3)) for c in CHANNELS}, {c: (split[c] >= CLIP_LEVEL).mean(axis=(1, 3)) for c in CHANNELS}


def _outer_ring(ok, n):
    """The first n ok blocks walking in from each side of the frame, along every row and column."""
    ring = np.zeros_like(ok)
    for axis in (0, 1):
        for flip in (False, True):
            o = np.flip(ok, axis) if flip else ok
            first = o & (np.cumsum(o, axis=axis) <= n)
            ring |= np.flip(first, axis) if flip else first
    return ring


def _grow(mask):
    """mask plus its eight neighbours."""
    p = np.pad(mask, 1)
    h, w = mask.shape
    return np.any([p[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3)], axis=0)


def _touching_edge(mask):
    """The parts of mask connected to the outside edge of the frame."""
    out = np.zeros_like(mask)
    out[0], out[-1], out[:, 0], out[:, -1] = mask[0], mask[-1], mask[:, 0], mask[:, -1]
    out &= mask
    while True:
        grown = _grow(out) & mask
        if (grown == out).all():
            return out
        out = grown


def find_film_parts(means, base_box=None):
    """Block masks for the film base, the bare light and the holder, plus the log2 brightness of every block and the film's own edges.

    On a negative the film base is the thinnest film, so the brightest film that is orange (bare light isn't). The holder is the dark area connected to the outside of the frame.
    The film base is then taken from the strip of film between the holder and the picture: the first few blocks in from each side of the film, past the holder and the sprocket
    holes, at the film base's level and colour. Thin parts of the picture can be as bright, but they sit further in. `base_box` (left, top, right, bottom as fractions of the
    frame) says where the clear film is, when it cannot be found by itself."""
    hb, wb = means["R"].shape
    lum = (means["R"] + 2 * means["G"] + means["B"]) / 4
    L = np.log2(np.maximum(lum, 1e-6))
    yy, xx = np.mgrid[0:hb, 0:wb]
    orange = means["R"] >= NEGATIVE_RB * means["B"]
    if orange.mean() < 0.05:   # not a colour negative; measure it anyway
        orange = np.ones_like(orange)
    near_bare = _grow(_grow(~orange & (L > np.median(L))))   # bright blocks that aren't orange are bare light; next to them is a blur of light and film
    film_like = orange & ~near_bare
    if not film_like.any():
        film_like = orange
    rough = np.percentile(L[film_like], 99)
    holder = _touching_edge(L < rough - 4.5)
    rows = np.where((~holder).mean(axis=1) > 0.2)[0]   # the film's own edges: rows and columns that are mostly not holder
    cols = np.where((~holder).mean(axis=0) > 0.2)[0]
    y0, y1, x0, x1 = (rows[0], rows[-1] + 1, cols[0], cols[-1] + 1) if len(rows) > 10 and len(cols) > 10 else (0, hb, 0, wb)
    ey, ex = FILM_EDGE * (y1 - y0), FILM_EDGE * (x1 - x0)
    inside = (yy >= y0) & (yy < y1) & (xx >= x0) & (xx < x1)
    border = inside & ((yy < y0 + ey) | (yy >= y1 - ey) | (xx < x0 + ex) | (xx >= x1 - ex))
    if base_box:
        bx0, by0, bx1, by1 = base_box
        base = (xx >= bx0 * wb) & (xx < bx1 * wb) & (yy >= by0 * hb) & (yy < by1 * hb)
        if not base.any():
            raise CaptureError("The area chosen for the clear film is too small; make it at least a few percent of the frame across.")
        even = base
    else:
        cand = border & film_like & ~holder
        seed = np.percentile(L[cand], 95) if cand.any() else rough
        ok = ~holder & film_like & (np.abs(L - seed) < 0.5)   # only the outermost film: skip holder (much darker) and bare light (brighter, not orange)
        ring = border & _outer_ring(ok, 4)
        for fallback in (cand, border):
            if not ring.any():
                ring = fallback
        seed = np.median(L[ring])
        base = ring & (np.abs(L - seed) <= 0.1)
        if base.sum() < 4:
            base = ring
        rg = means["R"] / np.maximum(means["G"], 1e-9)
        bg = means["B"] / np.maximum(means["G"], 1e-9)
        same_color = (np.abs(rg / np.median(rg[base]) - 1) < 0.03) & (np.abs(bg / np.median(bg[base]) - 1) < 0.03)
        even = ring & same_color & (np.abs(L - seed) <= 0.5)   # for evenness, allow a wider brightness range, or a strong hotspot would hide itself
        base &= same_color
    base_L = np.median(L[base])
    bare = L > base_L + 0.4
    holder = _touching_edge(L < base_L - 4.5)
    return base, even, bare, holder, L, (y0, y1, x0, x1)


def hole_light_rb(planes, bare, base_lum):
    """Red/blue balance of the bare light in the sprocket holes, or None if too little shows. Green is usually blown out there, so only red and blue are used, from the brightest
    pixels well above the film base where neither is."""
    if bare.sum() < 4:
        return None
    b = FILM_BLOCK
    hb, wb = bare.shape
    r, g, bl = (planes[c][:hb * b, :wb * b] for c in CHANNELS)
    lum = (r + 2 * g + bl) / 4
    mask = np.repeat(np.repeat(bare, b, axis=0), b, axis=1)
    mask &= (lum > 3 * base_lum) & (r < CLIP_LEVEL) & (bl < CLIP_LEVEL)
    if mask.sum() < 500:
        return None
    top = mask & (lum >= np.percentile(lum[mask], 80))
    return float(np.median(r[top]) / np.median(bl[top]))


def measure_film(planes, base_box=None) -> dict:
    means, clipped = film_blocks(planes)
    base, even, bare, holder, L, (y0, y1, x0, x1) = find_film_parts(means, base_box)
    film = ~_grow(bare) & ~holder   # the blurred edges of sprocket holes aren't film either
    lum = 2.0 ** L
    bb = {c: float(np.median(means[c][base])) for c in CHANNELS}
    bb["all"] = (bb["R"] + 2 * bb["G"] + bb["B"]) / 4
    f = {"base": bb, "R/G": bb["R"] / bb["G"], "B/G": bb["B"] / bb["G"]}
    f["negative"] = bb["R"] / max(bb["B"], 1e-9) >= NEGATIVE_RB
    f["headroom"] = {c: float(-np.log2(max(bb[c], 1e-6))) for c in CHANNELS}
    f["densest"] = {c: float(-np.log2(max(np.percentile(means[c][film], 0.5), 1e-6))) for c in CHANNELS}
    f["base_clip"] = {c: 100 * float(clipped[c][base].mean()) for c in CHANNELS}
    f["film_clip"] = {c: 100 * float(clipped[c][film].mean()) for c in CHANNELS}
    f["light R/B"] = hole_light_rb(planes, bare, bb["all"])
    f["bare %"] = 100 * float(bare.mean())
    f["stray"] = 100 * float(np.median(lum[holder]) / lum[film].mean()) if holder.mean() > 0.005 else None   # the black holder's brightness as % of the average light through the film
    # Evenness: how much brighter the clear film is at the middle of the film's edges than at its corners. A straight line through brightness against distance from the centre
    # (squared), fitted over all the clear film along the edges, is steadier than comparing a few corner blocks. r squared is 0.5 at the middle of an edge and 1 in a corner.
    yy, xx = np.mgrid[0:base.shape[0], 0:base.shape[1]]
    r2 = (np.hypot((xx + 0.5 - x0) / (x1 - x0) - 0.5, (yy + 0.5 - y0) / (y1 - y0) - 0.5) / np.hypot(0.5, 0.5)) ** 2
    if even.sum() >= 30 and np.ptp(r2[even]) >= 0.2:
        f["mid/corner"] = 100 * (2 ** (-0.5 * np.polyfit(r2[even], L[even], 1)[0]) - 1)
    else:
        f["mid/corner"] = None
    any_clip = np.max([clipped[c] for c in CHANNELS], axis=0) > 0
    f["masks"] = {"base": base, "bare": bare, "holder": holder, "clipped": film & any_clip}
    f["means"] = np.stack([means[c] for c in CHANNELS], axis=-1).astype(np.float32)   # what the masks are drawn over
    return f


# ---------------------------------------------------------------- judging
def film_rows(shots, ri: int, stops) -> None:
    """Each scan's numbers against the reference scan."""
    rf = shots[ri].f
    for i, s in enumerate(shots):
        f = s.f
        row = {"set": stops[i] - stops[ri] if stops else None, "measured": float(np.log2(f["base"]["all"] / rf["base"]["all"])),
               "R/G": pct(f["R/G"], rf["R/G"]), "B/G": pct(f["B/G"], rf["B/G"])}
        row["unexplained"] = row["measured"] - row["set"] if stops else None
        row["light"] = pct(f["light R/B"], rf["light R/B"]) if f["light R/B"] and rf["light R/B"] else None
        s.row = row


def suggest_exposure(negs):
    """The shutter speed that puts the clear film's brightest channel half a stop under blown out, at the usual ISO."""
    target = []
    for s in negs:
        ex = s.exif or {}
        t, iso = _number(ex.get("Shutter")), _number(ex.get("ISO"))
        if t and iso:
            target.append(t * iso * 2 ** (min(s.f["headroom"].values()) - 0.5))
    if not target:
        return None
    iso = Counter((s.exif or {}).get("ISO") for s in negs).most_common(1)[0][0]
    t = float(np.median(target)) / _number(iso)
    return f"{min(SHUTTER_SPEEDS, key=lambda v: abs(np.log2(_number(v) / t)))} s at ISO {iso}"


def film_findings(shots, ri: int) -> list:
    """For each scan a list of (kind, tag, text): what is worth a look, in plain words. kind is 'light' (the light or stray light changed), 'color' (the clear film changed colour
    but the light in the sprocket holes didn't: the film, or the light's green), 'exposure' or 'other'. tag is a word or two for the tables."""
    rf = shots[ri].f
    out = []
    for i, s in enumerate(shots):
        f, row, notes = s.f, s.row, []
        out.append(notes)
        if not f["negative"]:
            notes.append(("other", "skipped", "Not a colour negative (no orange film base): a slide, black and white film, or no film. Left out."))
            continue
        clipped = [ch for ch in CHANNELS if f["base_clip"][ch] > 1]
        if clipped:
            notes.append(("exposure", "blown out", f"The clear film is blown out in {'/'.join(clipped)}. The converter can't see its real colour, which usually gives a strong colour cast. Expose darker."))
        else:
            spots = [f"{f['film_clip'][ch]:.2f}% in {ch}" for ch in CHANNELS if f["film_clip"][ch] > 0.1]
            if spots:
                notes.append(("exposure", "blown out", f"Parts of the film are blown out ({', '.join(spots)}). Those spots lose their colour."))
        if i == ri:
            continue
        deep = max(CHANNELS, key=lambda ch: f["densest"][ch])
        extra = f["densest"][deep] - rf["densest"][deep]
        if f["densest"][deep] > NOISE_STOPS and extra > 1:
            notes.append(("exposure", "noisy", f"Its densest film is {extra:.1f} stops darker than in the reference, down in the sensor noise. That's the brightest part of the picture once "
                                              "converted, so expect noise and off colours there."))
        auto = is_auto_exposure(s.exif) or is_auto_exposure(shots[ri].exif)
        tol = EXPOSURE_TOL_AUTO if auto else EXPOSURE_TOL
        m, u = row["measured"], row["unexplained"]
        if u is not None and abs(u) > tol:
            notes.append(("light", "brightness", f"It came out {abs(u):.2f} stops {'brighter' if u > 0 else 'darker'} than its shutter speed and ISO explain. The light got "
                                                 f"{'brighter' if u > 0 else 'dimmer'}, or it's a different film."))
        elif abs(m) > EXPOSURE_DIFF:
            ex, rex = s.exif or {}, shots[ri].exif or {}
            changed = [f"{'' if k == 'Shutter' else k + ' '}{ex.get(k, '?')} instead of {rex.get(k, '?')}" for k in ("Shutter", "ISO", "Aperture") if ex.get(k) != rex.get(k)]
            why = (f"because the camera used {' and '.join(changed)}. Not the light." if u is not None and changed else "and the camera settings aren't in the file.")
            notes.append(("exposure", "exposure", f"It's {abs(m):.1f} stops {'brighter' if m > 0 else 'darker'} than the reference, {why}"))
        dl = row["light"]
        words = color_words(row["R/G"], row["B/G"])
        if max(abs(row["R/G"]), abs(row["B/G"])) > COLOR_TOL:
            if dl is None:
                notes.append(("light", "film color", f"The clear film changed colour ({words}). Either the light's colour changed or it's a different film; there are no sprocket holes to tell which."))
            elif abs(dl) > COLOR_TOL:
                notes.append(("light", "light color", f"The light's colour changed: the sprocket holes are {abs(dl):.1f}% {'warmer' if dl > 0 else 'cooler'}, and the clear film changed with them ({words})."))
            else:
                notes.append(("color", "film color", f"The clear film changed colour ({words}) but the light in the sprocket holes didn't. Either it's a different film or strip, or the light's green "
                                                     "shifted (green is blown out in the sprocket holes, so it can't show there). The second often happens right after the light is switched on."))
        elif dl is not None and abs(dl) > COLOR_TOL:
            notes.append(("light", "light color", f"The light in the sprocket holes got {abs(dl):.1f}% {'warmer' if dl > 0 else 'cooler'} but the clear film didn't. Check the sprocket holes in "
                                                  "the picture of what was measured; something may be partly covering them."))
        if f["mid/corner"] is not None and rf["mid/corner"] is not None:
            d = f["mid/corner"] - rf["mid/corner"]
            if abs(d) > EVEN_TOL:
                notes.append(("light", "evenness", f"The middle of the frame is lit {'more' if d > 0 else 'less'} strongly than in the reference: the clear film is {f['mid/corner']:+.0f}% brighter "
                                                   f"mid-edge than at the corners, against {rf['mid/corner']:+.0f}%. The light, or stray light, changed."))
        if f["stray"] is not None and rf["stray"] is not None and f["stray"] - rf["stray"] > STRAY_TOL:
            notes.append(("light", "stray light", f"More stray light: {f['stray']:.1f}% of the light lands on the black holder, against {rf['stray']:.1f}% in the reference. Light bouncing around "
                                                  "adds a haze, strongest in the middle."))
    return out


def _names(names, most=8):
    return ", ".join(names) if len(names) <= most else f"{len(names)} scans ({names[0]} to {names[-1]})"


def film_verdict(shots, ri: int, notes_per_shot, stops):
    """The short answer (Finding rows), the bottom line, and what to do."""
    negs = [s for s in shots if s.f["negative"]]
    if not negs:
        return [Finding("Colour negatives", "?", "None of the scans look like colour negatives, so there's nothing to check. This check is for colour negative film.")], "Nothing to check.", []
    others = [s for s in negs if s is not shots[ri]]

    def flagged(tag):
        return [s.name for s, notes in zip(shots, notes_per_shot) if any(t == tag for _, t, _ in notes)]

    rows, todo = [], []
    bad = flagged("brightness")
    if not stops:
        rows.append(Finding("Light brightness", "?", "Can't tell: the shutter speed or ISO is missing from the files."))
    elif bad:
        rows.append(Finding("Light brightness", "CHECK", f"Some scans came out brighter or darker than their camera settings explain: {_names(bad)}."))
    elif others:
        u = max(abs(s.row["unexplained"]) for s in others)
        rows.append(Finding("Light brightness", "OK", f"Steady. Every scan came out as bright as its camera settings say it should (within {u:.2f} stops)."))
    else:
        rows.append(Finding("Light brightness", "?", "Needs at least two colour negatives to compare."))

    light = [s.f["light R/B"] for s in negs if s.f["light R/B"]]
    bad = flagged("light color")
    if bad:
        rows.append(Finding("Light colour", "CHECK", f"Changed in {_names(bad)}."))
    elif len(light) >= 2:
        rows.append(Finding("Light colour", "OK", f"Steady. The light in the sprocket holes changed colour by {pct(max(light), min(light)):.1f}% at most."))
    else:
        rows.append(Finding("Light colour", "?", "Can't check directly: no sprocket holes in view, or they're blown out."))

    bad = flagged("film color")
    shift = max((max(abs(s.row["R/G"]), abs(s.row["B/G"])) for s in shots if s.name in bad), default=0)
    if bad:
        rows.append(Finding("Film base colour", "CHECK", f"Shifted by up to {shift:.1f}% in {_names(bad)}. A different film, or the light warming up."))
    else:
        rows.append(Finding("Film base colour", "OK", f"The same in every scan (within {COLOR_TOL:g}%)."))

    meas = [s.row["measured"] for s in negs]
    spread = max(meas) - min(meas)
    auto = sorted({(s.exif or {}).get("Program", "?") for s in negs if is_auto_exposure(s.exif)})
    if spread > 0.3 and auto:
        rows.append(Finding("Same exposure?", "FIX", f"No. The camera picked the exposure itself ({', '.join(auto)}), so the clear film came out up to {spread:.1f} stops brighter in some scans than in others."))
        todo.append("Put the camera in manual (M) and keep the same shutter speed and ISO for the whole roll.")
    elif spread > 0.3:
        rows.append(Finding("Same exposure?", "CHECK", f"No. The clear film came out up to {spread:.1f} stops brighter in some scans than in others."))
    else:
        rows.append(Finding("Same exposure?", "OK", f"Yes, within {spread:.2f} stops."))

    h = float(np.median([min(s.f["headroom"].values()) for s in negs]))
    if h > UNDER_STOPS:
        rows.append(Finding("Bright enough?", "FIX", f"No. The clear film sits about {h:.1f} stops below blown out, so there's about {h - 0.5:.1f} stops to spare. Brighter gives cleaner colour, especially in blue."))
        sugg = suggest_exposure(negs)
        todo.append(f"Expose about {h - 0.5:.1f} stops brighter" + (f", roughly {sugg} with your usual aperture" if sugg else "")
                    + ". The clear film between frames should end up bright but not blown out. The sprocket holes will blow out; that's fine.")
    else:
        rows.append(Finding("Bright enough?", "OK", f"Yes. The clear film sits {h:.1f} stops below blown out."))

    bad = flagged("blown out")
    if bad:
        rows.append(Finding("Blown out", "FIX", f"In {_names(bad)}."))
        todo.append("Expose a little darker for the scans with blown-out film.")
    else:
        rows.append(Finding("Blown out", "OK", "Nothing blown out."))

    noisy = [s for s in negs if max(s.f["densest"].values()) > NOISE_STOPS]
    if noisy:
        rows.append(Finding("Noise", "CHECK", f"In {len(noisy)} of {len(negs)} scans the densest film (the brightest parts once converted) is down in the sensor noise."))
    else:
        rows.append(Finding("Noise", "OK", "The densest film is above the sensor noise in every scan."))

    mc = [s.f["mid/corner"] for s in negs if s.f["mid/corner"] is not None]
    bad = flagged("evenness")
    if bad:
        rows.append(Finding("Evenness", "CHECK", f"Changed in {_names(bad)}."))
    elif mc:
        between = f" (between {min(mc):+.0f}% and {max(mc):+.0f}%)" if round(min(mc)) != round(max(mc)) else ""
        rows.append(Finding("Evenness", "OK", f"Steady. The clear film is {np.median(mc):+.0f}% brighter mid-edge than at the corners{between}, which is normal falloff from the light and lens."))
    else:
        rows.append(Finding("Evenness", "?", "Not enough clear film around the frame to measure."))

    st = [s.f["stray"] for s in negs if s.f["stray"] is not None]
    bad = flagged("stray light")
    if bad:
        rows.append(Finding("Stray light", "CHECK", f"Went up in {_names(bad)}."))
        todo.append("Cover the sprocket holes and any gaps around the film, so less bare light gets into the lens.")
    elif st:
        rows.append(Finding("Stray light", "OK", f"Steady at about {np.median(st):.1f}% of the light. (The black holder should be pitch black; light there is bouncing around inside the lens.)"))
    else:
        rows.append(Finding("Stray light", "?", "No black holder in view to measure."))

    skipped = [s.name for s in shots if not s.f["negative"]]
    if skipped:
        rows.append(Finding("Skipped", "", f"{_names(skipped)}: not {'a colour negative' if len(skipped) == 1 else 'colour negatives'}."))

    light_bad = any(k == "light" for notes in notes_per_shot for k, _, _ in notes)
    color_bad = any(k == "color" for notes in notes_per_shot for k, _, _ in notes)
    conversion = "the cause is in the conversion: the crop and white balance going into the converter, or its settings."
    if light_bad:
        which = [s.name for s, notes in zip(shots, notes_per_shot) if any(k == "light" for k, _, _ in notes)]
        bottom = f"The light (or stray light) seems to have changed in {_names(which)}. See the scans worth a look."
        todo.append("Photograph the bare light (no film) through a session and run the bare-light check on those shots to see what it's doing.")
    elif any(r.status == "FIX" for r in rows):
        bottom = "The light looks fine. Fix the exposure first. If a scan still converts badly after that, " + conversion
    else:
        bottom = "The captures look fine. If a scan converts badly, " + conversion
    if color_bad:
        if shift < 5:
            bottom += f" The film base colour shifts (up to {shift:.1f}%) are small: a slight tint at most, not a strongly orange frame."
        if not light_bad:
            todo.append("Let the light warm up a few minutes after switching it on. To see how long yours takes, photograph the bare light every minute or two and run the bare-light check on those shots.")
    if not todo:
        todo.append("Nothing to fix on the capture side.")
    return rows, bottom, todo


# ---------------------------------------------------------------- the check
def analyse(paths: list[str], reference: str = "", base_box=None, progress=None, cancelled=None, loader=load_planes, exif_reader=read_exif) -> FilmResult:
    """Read each scan and judge the roll. `reference` is the file name of the scan the others are compared with (the first colour negative when empty)."""
    if len(paths) < 2:
        raise CaptureError(f"Choose at least two RAW scans (you chose {len(paths)}).")
    shots = [FilmShot(s.path, s.name, s.exif, s.time) for s in start_shots(paths, exif_reader)]
    have_times = order_shots(shots)
    for i, s in enumerate(shots):
        if cancelled is not None and cancelled():
            raise Cancelled()
        if progress is not None:
            progress(i, len(shots), s.name)
        planes, _clip = loader(s.path)
        s.f = measure_film(planes, base_box)
        del planes
    if reference:
        match = [i for i, s in enumerate(shots) if reference in (s.name, os.path.splitext(s.name)[0])]
        if not match:
            raise CaptureError(f"{reference} is not one of the scans.")
        ri = match[0]
    else:
        ri = next((i for i, s in enumerate(shots) if s.f["negative"]), 0)
    stops, use_n = settings_stops(shots)
    film_rows(shots, ri, stops)
    notes = film_findings(shots, ri)
    for s, n in zip(shots, notes):
        s.notes = n
    findings, bottom, todo = film_verdict(shots, ri, notes, stops)
    return FilmResult(shots, ri, have_times, stops, use_n, findings, bottom, todo)


def overlay(shot: FilmShot, scale: int = 4) -> np.ndarray:
    """An 8-bit picture of what was measured in a scan: the scan (block averages), with the clear film green, the light in the sprocket holes red, the black holder blue and
    blown-out film pink."""
    means = shot.f["means"]
    lum = np.clip(means.max(axis=-1), 0, 1) ** 0.45
    img = np.repeat(lum[..., None], 3, axis=-1) * 255.0
    for key, colour in (("holder", (60, 100, 255)), ("bare", (255, 70, 70)), ("clipped", (255, 130, 220)), ("base", (80, 230, 80))):
        mask = shot.f["masks"][key]
        img[mask] = 0.45 * img[mask] + 0.55 * np.array(colour)
    img = img.astype(np.uint8)
    return np.repeat(np.repeat(img, scale, axis=0), scale, axis=1)


# ---------------------------------------------------------------- saved report
def report_text(result: FilmResult) -> str:
    shots, ri = result.shots, result.ri
    when = f"shot {shots[0].time:%Y-%m-%d %H:%M} to {shots[-1].time:%H:%M}" if result.have_times else "in the order given"
    lines = ["FILM SCAN CHECK", "=" * 70, f"{len(shots)} scans ({when}), each compared with {shots[ri].name} (the reference)."]
    if result.stops and not result.use_aperture:
        lines.append("The aperture isn't in the files (manual lens?), so it's assumed the same for every scan.")
    lines += ["", "THE SHORT ANSWER"]
    for f in result.findings:
        wrapped = textwrap.wrap(f.text, 70) or [""]
        lines.append(f"  {f.label:<18s}{f.status:<9s}{wrapped[0]}")
        lines += [" " * 29 + w for w in wrapped[1:]]
    lines += ["", *textwrap.wrap("Bottom line: " + result.bottom, 100, initial_indent="  ", subsequent_indent="  "), "", "WHAT TO DO"]
    for k, item in enumerate(result.todo, 1):
        lines += textwrap.wrap(item, 100, initial_indent=f"  {k}. ", subsequent_indent="     ")
    lines += ["", "SCAN BY SCAN", f"  {'#':>3s}  {'file':14s} {'min':>6s} {'shutter':>8s} {'ISO':>5s} | {'off by':>7s} {'light %':>7s} {'red %':>6s} {'blue %':>7s} {'below':>9s} | worth a look"]
    for i, s in enumerate(shots):
        f, r, ex = s.f, s.row, s.exif or {}
        tm = f"{s.minutes:6.1f}" if result.have_times else f"{'#' + str(i):>6s}"
        lead = f"  {i:3d}{'*' if i == ri else ' '} {s.name[:14]:14s} {tm} {ex.get('Shutter', '?'):>8s} {ex.get('ISO', '?'):>5s} |"
        if not f["negative"]:
            lines.append(lead + " not a colour negative, skipped")
            continue

        def num(v, spec, width):
            return f"{v:{spec}}" if v is not None else f"{'-':>{width}s}"

        tags = ", ".join(dict.fromkeys(t for _, t, _ in s.notes))
        lines.append(f"{lead} {num(r['unexplained'], '+7.2f', 7)} {num(r['light'], '+7.1f', 7)} {r['R/G']:+6.1f} {r['B/G']:+7.1f} {min(f['headroom'].values()):6.1f} st | {tags}".rstrip())
    lines += ["", "  * is the reference. off by: how much brighter (+) or darker (-) the clear film came out than the camera settings explain. light %: the light in the sprocket holes,",
              "  warmer (+) or cooler (-). red/blue %: the clear film against green. below: stops the clear film's brightest channel sits under blown out.", "", "SCANS WORTH A LOOK"]
    shown = False
    for i, s in enumerate(shots):
        if s.notes:
            shown = True
            lines.append(f"  #{i} {s.name}{' (the reference)' if i == ri else ''}")
            for _, _, text in s.notes:
                lines += textwrap.wrap(text, 100, initial_indent="    - ", subsequent_indent="      ")
    if not shown:
        lines.append("  None. Every scan matches the reference.")
    return "\n".join(lines) + "\n"


def results_csv(result: FilmResult) -> str:
    head = ["index", "file", "reference", "negative", "capture_time", "minutes", "shutter", "ISO", "program", "set_stops", "measured_stops", "unexplained_stops", "base_R", "base_G", "base_B",
            "base_R/G", "base_B/G", "R/G_change_%", "B/G_change_%", "light_R/B", "light_change_%", "headroom_R", "headroom_G", "headroom_B", "densest_R", "densest_G", "densest_B",
            "base_clip_R_%", "base_clip_G_%", "base_clip_B_%", "film_clip_R_%", "film_clip_G_%", "film_clip_B_%", "mid/corner_%", "stray_%", "bare_%"]

    def num(v):
        return "" if v is None else f"{v:.4f}"

    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(head)
    for i, s in enumerate(result.shots):
        f, r, ex = s.f, s.row, s.exif or {}
        w.writerow([i, s.name, int(i == result.ri), int(f["negative"]), s.time.isoformat(sep=" ") if s.time else "", f"{s.minutes:.2f}" if result.have_times else "",
                    ex.get("Shutter", ""), ex.get("ISO", ""), ex.get("Program", ""), num(r["set"]), num(r["measured"]), num(r["unexplained"]),
                    *(num(f["base"][ch]) for ch in CHANNELS), num(f["R/G"]), num(f["B/G"]), num(r["R/G"]), num(r["B/G"]), num(f["light R/B"]), num(r["light"]),
                    *(num(f["headroom"][ch]) for ch in CHANNELS), *(num(f["densest"][ch]) for ch in CHANNELS),
                    *(num(f["base_clip"][ch]) for ch in CHANNELS), *(num(f["film_clip"][ch]) for ch in CHANNELS), num(f["mid/corner"]), num(f["stray"]), num(f["bare %"])])
    return out.getvalue()
