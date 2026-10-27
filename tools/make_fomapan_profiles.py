"""Reads the three characteristic curves off a picture of Foma's Fomapan 100 technical data sheet (the middle chart: daylight, 1/20 s, Microphen at 20 C, 5, 7 and 11 minutes)
and writes them as EFAS film profiles of the kind "supplied" into src/photoeditor/assets/film_profiles/.

    python tools/make_fomapan_profiles.py PATH_TO_CHART_IMAGE

The picture is the datasheet page's chart as the vendor publishes it (for instance the one at digitaltruth.com/products/foma_tech/Fomapan_100.pdf). It is read, not
bundled: only the numbers read from it are kept. The axes are found from the grid (the vertical lines at log exposure -3, -2, -1 and the horizontal lines at density 1, 2, 3),
each curve's centre is taken along every pixel column, and the three curves are told apart by their order.
"""
import json
import os
import sys
import uuid

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from photoeditor.features.densitometry import film_profile as fp   # noqa: E402
from photoeditor.features.densitometry import fit                  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "photoeditor", "assets", "film_profiles")
SIGMA = 0.03          # density: the width of the lines, and reading the vendor's chart
STEP_PX = 5           # one sample every this many pixel columns
DEVELOPMENTS = {1: 5, 2: 7, 3: 11}     # the numbers on the chart's curves -> minutes in Microphen
# fixed ids, so the same profile is never installed twice
IDS = {5: "foma-fomapan-100-microphen-5min", 7: "foma-fomapan-100-microphen-7min", 11: "foma-fomapan-100-microphen-11min"}


def _lines(dark: np.ndarray, rows: slice, cols: slice) -> tuple[list[int], list[int]]:
    sub = dark[rows, cols]
    v = [i + cols.start for i, c in enumerate(sub.sum(axis=0)) if c > 0.7 * sub.shape[0]]
    h = [i + rows.start for i, c in enumerate(sub.sum(axis=1)) if c > 0.7 * sub.shape[1]]
    return v, h


def digitise(path: str) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    g = np.asarray(Image.open(path).convert("L")).astype(float)
    dark = g < 140
    # the middle chart: its frame has vertical grid lines and horizontal lines every unit of density
    v, h = _lines(dark, slice(160, 450), slice(20, 280))
    h = sorted(set(h))
    d0 = [y for y in h if 380 < y < 430][0]          # density 0 is the bottom line of the plot
    unit = (d0 - min(y for y in h if y > 150)) / 3.0  # three units up to the top line
    ticks = sorted(x for x in v if 30 < x < 250)       # log exposure -3, -2, -1
    x3 = ticks[0]
    px = (ticks[-1] - ticks[0]) / 2.0
    grid_rows = {round(d0 - unit * k) for k in (1, 2)}
    ink = 255.0 - g
    for r in grid_rows:                               # a curve crossing a grid line: use the rows on either side
        ink[r - 1:r + 2] = (ink[r - 2] + ink[r + 2]) / 2.0
    grid_cols = set(ticks)
    found: dict[int, list[tuple[float, float]]] = {1: [], 2: [], 3: []}
    for x in range(int(x3) - 12, int(x3 + 3 * px) - 28):
        if any(abs(x - c) <= 1 for c in grid_cols):
            continue
        col = ink[int(d0 - 3 * unit) + 3:int(d0) - 1, x]
        ys = np.arange(len(col)) + int(d0 - 3 * unit) + 3
        mask = col > 90
        clusters, cur = [], []
        for y, m in zip(ys, mask):
            if m:
                cur.append(y)
            elif cur:
                clusters.append(cur)
                cur = []
        if cur:
            clusters.append(cur)
        centres = []
        for c in clusters:
            w = ink[c, x]
            centres.append(float((np.array(c) * w).sum() / w.sum()))
        dens = [(d0 - y) / unit for y in centres]
        if x > x3 + 2.1 * px:                          # the legend (1-5 min ...) is in the lower right
            dens = [d for d in dens if d > 0.8]
        if len(dens) == 3:
            for number, d in zip((1, 2, 3), sorted(dens)):
                found[number].append(((x - x3) / px - 3.0, d))
    out = {}
    for number, pts in found.items():
        arr = np.array(pts)
        keep = arr[:: STEP_PX]
        out[DEVELOPMENTS[number]] = (keep[:, 0], keep[:, 1])
    return out


def build(minutes: int, x: np.ndarray, y: np.ndarray) -> fp.FilmProfile:
    report = fit.fit_curve(x, y, sigma=np.full(len(x), SIGMA))
    curve = fp.curve_from_report(report, scale="relative", unit="log relative exposure")
    name = f"Fomapan 100 - Microphen {minutes} min (Foma data sheet)"
    p = fp.new_profile(
        name, "supplied", {"K": curve}, film_stock="Foma Fomapan 100", process=f"Microphen at 20 C, {minutes} min",
        notes=("The characteristic curve of Foma's Fomapan 100 technical data sheet for this development, read off the printed chart (+-0.03 density): daylight 5500 K, 1/20 s, Microphen at 20 C, "
               f"{minutes} minutes. The density includes base and fog. Supplied by the maker's chart, not measured by EFAS, and other rolls and developers differ."),
        conditions={"illuminant": "Daylight 5500 K, 1/20 s", "densitometry": "as printed on the data sheet (diffuse visual density)", "developer": "Microphen 20 C", "minutes": minutes},
        calibration={"origin": "manufacturer data sheet, digitised from the printed chart", "source": "Foma Bohemia, Fomapan 100 technical data sheet", "tool": "tools/make_fomapan_profiles.py"},
    )
    p.id = IDS[minutes]
    p.base = {"dmin_from_curve": [float(y.min())]}
    p.validity = {"log_exposure_range": [float(x.min()), float(x.max())], "density_range": [float(y.min()), float(y.max())]}
    return p


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    os.makedirs(OUT, exist_ok=True)
    for minutes, (x, y) in sorted(digitise(sys.argv[1]).items()):
        p = build(minutes, x, y)
        fn = os.path.join(OUT, f"{IDS[minutes]}.json")
        with open(fn, "w", encoding="utf-8", newline="\n") as f:
            json.dump(p.to_dict(), f, indent=1, ensure_ascii=False)
            f.write("\n")
        g = p.gradients()["K"]
        print(f"{minutes:>2} min: {len(x)} points, log E {x.min():.2f} to {x.max():.2f}, D {y.min():.2f} to {y.max():.2f}, chosen {p.curves['K'].chosen}, "
              f"gamma {g['gamma']:.2f}, usable for inversion {p.usable_for_inversion()}")


if __name__ == "__main__":
    main()
