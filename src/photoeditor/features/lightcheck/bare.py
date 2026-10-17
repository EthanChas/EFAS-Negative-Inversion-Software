"""The bare-light check: how steady and how even is the light a negative is scanned with? No Qt.

The light is photographed with no film in the holder, a few times over an hour or so, with the camera on manual. Each shot is read from the sensor's own values and compared with the
first: how bright the light is (it often dims and cools as it warms up), its colour (red and blue each compared with green, which exposure does not change), how even it is
across the frame (the middle against the corners), whether anything is blown out, and whether the camera settings stayed the same. Adapted from lightdrift by David Esquivel
(MIT licence), https://github.com/davidesqalv/lightdrift.
"""

import csv
import io
import textwrap
from dataclasses import dataclass, field

import numpy as np

from .capture import CHANNELS, Cancelled, CaptureError, load_planes, read_exif

COLOR_TOL = 2.0     # % change in the light's colour that shows in scans
BRIGHT_STEADY = 2.0  # % a steady light moves over the whole session
SETTLED_BAND = 1.5   # % either side of the median once the light has settled
EVEN_LEVEL = 5.0     # % the middle may differ from the corners
EVEN_CHANGE = 2.0    # points that difference may change over the session
CLIP_SHARE = 0.001   # share of a channel at the sensor's maximum that counts as blown out
GRID_COLUMNS = 9
INSET = 0.05


@dataclass
class Shot:
    path: str
    name: str
    exif: dict
    time: object = None
    minutes: float = 0.0
    clip: dict = field(default_factory=dict)
    m: dict = field(default_factory=dict)
    row: dict = field(default_factory=dict)


@dataclass
class Finding:
    label: str
    status: str   # OK, SMALL, CHANGED, CHECK, FIX or ?
    text: str


@dataclass
class BareResult:
    shots: list
    have_times: bool
    box: tuple
    findings: list
    bottom: str
    differ: list = field(default_factory=list)    # indexes of the shots with other camera settings than the first
    clipped: list = field(default_factory=list)   # indexes of the shots with pixels at the sensor's maximum


# ---------------------------------------------------------------- measuring
def luminance(planes) -> np.ndarray:
    return (planes["R"] + 2 * planes["G"] + planes["B"]) / 4


def find_light_region(planes, inset: float) -> tuple:
    """(y0, y1, x0, x1) of the lit area (not the holder's dark border), trimmed by `inset` on each side."""
    lum = luminance(planes)
    thr = 0.5 * np.percentile(lum[::4, ::4], 99)
    mask = lum > thr
    rf, cf = mask.mean(axis=1), mask.mean(axis=0)
    rows = np.where(rf > 0.5 * rf.max())[0]
    cols = np.where(cf > 0.5 * cf.max())[0]
    h, w = lum.shape
    if len(rows) < 20 or len(cols) < 20:
        y0, y1, x0, x1 = 0, h, 0, w
    else:
        y0, y1, x0, x1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    dy, dx = int((y1 - y0) * inset), int((x1 - x0) * inset)
    return y0 + dy, y1 - dy, x0 + dx, x1 - dx


def grid_medians(plane: np.ndarray, box: tuple, ncols: int) -> np.ndarray:
    y0, y1, x0, x1 = box
    p = plane[y0:y1, x0:x1]
    h, w = p.shape
    nrows = max(1, round(ncols * h / w))
    out = np.empty((nrows, ncols))
    for i, rs in enumerate(np.array_split(np.arange(h), nrows)):
        for j, cs in enumerate(np.array_split(np.arange(w), ncols)):
            out[i, j] = np.median(p[rs[0]:rs[-1] + 1, cs[0]:cs[-1] + 1])
    return out


def center_value(cells: np.ndarray) -> float:
    r, c = cells.shape
    return float(cells[(r - 1) // 2:r // 2 + 1, (c - 1) // 2:c // 2 + 1].mean())


def corners_value(cells: np.ndarray) -> float:
    return float(np.mean([cells[0, 0], cells[0, -1], cells[-1, 0], cells[-1, -1]]))


def uniformity(cells: np.ndarray) -> dict:
    return {"min/max": 100 * cells.min() / cells.max(), "center/corners": 100 * center_value(cells) / corners_value(cells), "spread (CV)": 100 * cells.std() / cells.mean()}


def measure(planes, box: tuple, ncols: int = GRID_COLUMNS) -> dict:
    """Per colour and overall: the level of the lit area and its patch-by-patch medians; and red and blue against green."""
    y0, y1, x0, x1 = box
    m = {"cells": {}, "level": {}}
    for c in CHANNELS:
        m["cells"][c] = grid_medians(planes[c], box, ncols)
        m["level"][c] = float(np.median(planes[c][y0:y1, x0:x1]))
    m["cells"]["all"] = (m["cells"]["R"] + 2 * m["cells"]["G"] + m["cells"]["B"]) / 4
    m["level"]["all"] = (m["level"]["R"] + 2 * m["level"]["G"] + m["level"]["B"]) / 4
    for name, (num, den) in {"R/G": ("R", "G"), "B/G": ("B", "G")}.items():
        m["cells"][name] = m["cells"][num] / m["cells"][den]
        m["level"][name] = m["level"][num] / m["level"][den]
    return m


def pct(new: float, old: float) -> float:
    return 100 * (new / old - 1)


def summary_row(m: dict, ref: dict) -> dict:
    """The numbers tracked over the session, each against the first shot."""
    row = {k: pct(m["level"][k], ref["level"][k]) for k in ("R", "G", "B", "all", "R/G", "B/G")}
    ca, cr = m["cells"]["all"], ref["cells"]["all"]
    row["center"] = pct(center_value(ca), center_value(cr))
    row["corners"] = pct(corners_value(ca), corners_value(cr))
    row["ctr/crn"] = uniformity(ca)["center/corners"]
    row["CV"] = uniformity(ca)["spread (CV)"]
    return row


# ---------------------------------------------------------------- plain words
def _when(minutes, i: int, have_times: bool) -> str:
    return f"minute {minutes[i]:.0f}" if have_times else f"shot #{i}"


def brightness_story(t, a, have_times: bool):
    """Plain words for a brightness series (% against the first shot): (status, text, index it settled at or None, whether it jumps around)."""
    a = np.asarray(a, dtype=float)
    span = a.max() - a.min()
    if span <= BRIGHT_STEADY:
        return "OK", f"Steady: it moved less than {max(span, 0.1):.1f}% over the whole session.", None, False
    if len(a) == 2:
        return "CHANGED", f"{abs(a[1]):.1f}% {'brighter' if a[1] > 0 else 'dimmer'} in the second shot.", None, False
    steps = np.diff(a)
    jumps = steps[np.abs(steps) > 3]
    if len(jumps) >= 3 and (jumps > 0).any() and (jumps < 0).any():
        return "CHANGED", f"Jumpy: it went up and down {len(jumps)} times, between {a.min():+.1f}% and {a.max():+.1f}%. The chart shows when.", None, True
    for s in range(1, len(a) - 1):
        rest = a[s:]
        if np.all(np.abs(rest - np.median(rest)) <= SETTLED_BAND):
            return "CHANGED", f"Got {abs(a[s]):.0f}% {'brighter' if a[s] > 0 else 'dimmer'} by {_when(t, s, have_times)}, then held steady (ended at {a[-1]:+.1f}%).", s, False
    return "CHANGED", f"Kept changing: {abs(a[-1]):.1f}% {'brighter' if a[-1] > 0 else 'dimmer'} by the last shot, without settling.", None, False


def color_words(rg: float, bg: float, least: float = 0.5) -> str:
    """'2.6% bluer and 0.7% less red' for changes in B/G and R/G, in %."""
    parts = []
    if abs(bg) >= least:
        parts.append(f"{abs(bg):.1f}% {'bluer' if bg > 0 else 'less blue'}")
    if abs(rg) >= least:
        parts.append(f"{abs(rg):.1f}% {'redder' if rg > 0 else 'less red'}")
    return " and ".join(parts) or f"under {least:g}%"


def color_story(rg, bg):
    """(status, text) for the colour series (R/G and B/G, % against the first shot)."""
    rg, bg = np.asarray(rg, dtype=float), np.asarray(bg, dtype=float)
    r, b = rg[np.argmax(np.abs(rg))], bg[np.argmax(np.abs(bg))]
    big = max(abs(r), abs(b))
    if big < 1:
        return "OK", "Steady: it changed less than 1%."
    return ("SMALL" if big < COLOR_TOL else "CHANGED"), f"At most {color_words(r, b, 1.0)} than the first shot."


def evenness_story(ctr):
    """(status, text) for the middle-against-corners series (the middle as % of the corners)."""
    d = np.asarray(ctr, dtype=float) - 100
    level, change = d[0], float(np.abs(d - d[0]).max())
    text = "The middle and the corners are within 1% of each other" if abs(level) < 1 else f"The middle is {abs(level):.0f}% {'brighter' if level > 0 else 'darker'} than the corners"
    text += ", and that didn't change." if change <= EVEN_CHANGE else f", and that changed by up to {change:.1f} points."
    if abs(level) > EVEN_LEVEL:
        text += " That's uneven enough to show in scans (it includes the lens's own falloff toward the corners)."
    return ("OK" if abs(level) <= EVEN_LEVEL and change <= EVEN_CHANGE else "CHECK"), text


# ---------------------------------------------------------------- the check
def order_shots(shots: list) -> bool:
    """Put the shots in capture order when every one has a capture time, and give each its minutes since the first. Returns whether the times were there."""
    have_times = all(s.time for s in shots)
    if have_times:
        shots.sort(key=lambda s: s.time)
        t0 = shots[0].time
        for s in shots:
            s.minutes = (s.time - t0).total_seconds() / 60
    else:
        for i, s in enumerate(shots):
            s.minutes = float(i)
    return have_times


def start_shots(paths: list[str], exif_reader=read_exif) -> list:
    import os

    out = []
    for p in paths:
        ex = exif_reader(p)
        out.append(Shot(p, os.path.basename(p), ex, ex.get("time") if ex else None))
    return out


def analyse(paths: list[str], progress=None, cancelled=None, grid: int = GRID_COLUMNS, inset: float = INSET, full_frame: bool = False,
            loader=load_planes, exif_reader=read_exif) -> BareResult:
    """Read each capture and judge the light. `progress(done, total, name)` is called before each file; `cancelled()` stops the check (Cancelled)."""
    if len(paths) < 2:
        raise CaptureError(f"Choose at least two RAW photos of the bare light (you chose {len(paths)}).")
    shots = start_shots(paths, exif_reader)
    have_times = order_shots(shots)
    box, shape = None, None
    for i, s in enumerate(shots):
        if cancelled is not None and cancelled():
            raise Cancelled()
        if progress is not None:
            progress(i, len(shots), s.name)
        planes, s.clip = loader(s.path)
        if shape is None:
            shape = planes["R"].shape
            if full_frame:
                h, w = shape
                dy, dx = int(h * inset), int(w * inset)
                box = (dy, h - dy, dx, w - dx)
            else:
                box = find_light_region(planes, inset)
        elif planes["R"].shape != shape:
            raise CaptureError(f"{s.name} has different dimensions from {shots[0].name}; every photo has to come from the same camera.")
        s.m = measure(planes, box, grid)
        del planes
    ref = shots[0].m
    for s in shots:
        s.row = summary_row(s.m, ref)
    result = BareResult(shots, have_times, box, [], "")
    result.findings, result.bottom = verdict(result)
    return result


def verdict(result: BareResult):
    """The short answer (a Finding per check) and the bottom line."""
    shots, have_times = result.shots, result.have_times
    ref = shots[0]
    t = [s.minutes for s in shots]
    rows = [s.row for s in shots]
    b_status, b_text, settle, jumpy = brightness_story(t, [r["all"] for r in rows], have_times)
    c_status, c_text = color_story([r["R/G"] for r in rows], [r["B/G"] for r in rows])
    e_status, e_text = evenness_story([r["ctr/crn"] for r in rows])

    def settings(s):
        return tuple(s.exif.get(k) for k in ("Shutter", "Aperture", "ISO"))

    known = all(ref.exif.get(k, "?") != "?" for k in ("Shutter", "ISO"))
    result.differ = [i for i, s in enumerate(shots) if settings(s) != settings(ref)]
    if not known:
        s_row = Finding("Same settings", "?", "The camera settings aren't in the files, so it can't be checked that they stayed the same.")
    elif result.differ:
        s_row = Finding("Same settings", "CHECK", f"Shots {', '.join('#' + str(i) for i in result.differ)} used different settings, so their brightness can't be compared (colour and evenness still can).")
    else:
        s_row = Finding("Same settings", "OK", "Same shutter speed, aperture and ISO in every shot.")
    result.clipped = [i for i, s in enumerate(shots) if max(s.clip.values()) > CLIP_SHARE]
    if result.clipped:
        k_row = Finding("Blown out", "FIX", f"Shots {', '.join('#' + str(i) for i in result.clipped)} have pixels at the sensor's maximum, which can't be measured. Use a faster shutter speed.")
    else:
        k_row = Finding("Blown out", "OK", "Nothing blown out.")
    findings = [Finding("Brightness", b_status, b_text), Finding("Colour", c_status, c_text), Finding("Evenness", e_status, e_text), s_row, k_row]

    if jumpy:
        bottom = "The light's brightness jumps around. Check what happened at those times (switched off and on? charger plugged in?) in the chart."
    elif settle is not None:
        if settle == 1:   # settled by the very next shot, so it may well have settled sooner
            when = f"by minute {t[1]:.0f}" if have_times else "by the next shot"
            bottom = f"Let the light warm up before scanning. It had settled {when}, the first shot after the start, so it may need less. Shoot every minute or two at the start to find out."
        else:
            wait = f"about {t[settle]:.0f} minutes" if have_times else f"until shot #{settle}"
            bottom = f"Let the light warm up {wait} before scanning. After that it's steady."
    elif b_status != "OK":
        bottom = "The light kept changing through the whole session, so early and late scans will differ."
    else:
        bottom = "The light's brightness is steady."
    if c_status == "CHANGED":
        bottom += " Its colour shifts too, enough to tint scans slightly."
    if e_status == "CHECK":
        bottom += " It's not very even across the frame."
    return findings, bottom


# ---------------------------------------------------------------- saved report
def _wrap(text: str, indent: str = "  ", width: int = 100) -> list[str]:
    return textwrap.wrap(text, width, initial_indent=indent, subsequent_indent=indent)


def report_text(result: BareResult) -> str:
    """The whole report as plain text, for saving."""
    shots, have_times = result.shots, result.have_times
    when = f"over {shots[-1].minutes:.0f} minutes" if have_times else "in the order given (no capture times found)"
    lines = ["LIGHT CHECK (bare light, no film)", "=" * 70, f"{len(shots)} shots {when}, each compared with the first one ({shots[0].name}).", "", "THE SHORT ANSWER"]
    for f in result.findings:
        wrapped = textwrap.wrap(f.text, 70) or [""]
        lines.append(f"  {f.label:<16s}{f.status:<9s}{wrapped[0]}")
        lines += [" " * 27 + w for w in wrapped[1:]]
    lines += ["", *_wrap("Bottom line: " + result.bottom), "", "HOW IT WORKS (roughly)"]
    lines += _wrap("The bare light was photographed a few times. For each shot the sensor's values are read straight from the file, before any conversion, and compared with the first shot. "
                   "Only the lit area counts, not the dark edges around it.")
    for item in ("Brightness: the average level of the light. +5% means 5% more light than in the first shot.",
                 "Colour: red compared with green, and blue compared with green. Exposure doesn't change these, so if they move, the light's colour really changed.",
                 "Evenness: the lit area is cut into a grid of patches, and the middle patch is compared with the four corner patches.",
                 "Blown out: pixels at the sensor's maximum. Their real brightness is unknown.",
                 "Two shots taken back to back show how much the numbers wobble on their own. Ignore changes that small."):
        lines += textwrap.wrap(item, 100, initial_indent="  - ", subsequent_indent="    ")
    lines += ["", "SHOT BY SHOT (% change against the first shot)",
              f"  {'#':>3s}  {'file':14s} {'min':>6s} | {'brightness':>10s} {'bluer':>6s} {'redder':>6s} | {'middle vs corners':>17s} | note"]
    for i, s in enumerate(shots):
        r = s.row
        tm = f"{s.minutes:6.1f}" if have_times else f"{'#' + str(i):>6s}"
        note = ", ".join(n for n, on in (("settings differ", i in result.differ), ("blown out", i in result.clipped)) if on)
        lines.append(f"  {i:3d}  {s.name[:14]:14s} {tm} | {r['all']:+10.1f} {r['B/G']:+6.1f} {r['R/G']:+6.1f} | {r['ctr/crn'] - 100:+16.1f}% | {note}".rstrip())
    return "\n".join(lines) + "\n"


def results_csv(result: BareResult) -> str:
    keys = ("R", "G", "B", "all", "R/G", "B/G", "center", "corners", "ctr/crn", "CV")
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["index", "file", "capture_time", "minutes"] + [f"{k} %" if k not in ("ctr/crn", "CV") else k for k in keys])
    for i, s in enumerate(result.shots):
        w.writerow([i, s.name, s.time.isoformat(sep=" ") if s.time else "", f"{s.minutes:.2f}" if result.have_times else ""] + [f"{s.row[k]:.4f}" for k in keys])
    return out.getvalue()
