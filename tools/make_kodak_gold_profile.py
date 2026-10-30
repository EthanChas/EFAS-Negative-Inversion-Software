"""Reads the three characteristic curves (red, green, blue) off Kodak's technical data sheet for KODAK GOLD 200 Film (E-7022) and writes them as an EFAS film profile of the kind
"supplied" into src/photoeditor/assets/film_profiles/.

    python tools/make_kodak_gold_profile.py PATH_TO_E7022_Gold_200.pdf

The sheet is at business.kodakmoments.com/sites/default/files/files/resources/E7022_Gold_200.pdf. Its chart (page 4, "CURVES": exposure daylight, Status M densitometry) is drawn as
vector lines, so the curves are read from the lines themselves, not from a picture: the axes come from the chart's frame and ticks (log exposure -3 to +1 across, density 0 to 4 up),
and each curve's path is sampled evenly along log exposure. The PDF is read, not bundled: only the numbers read from it are kept.
"""
import json
import os
import sys

import fitz          # PyMuPDF
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from photoeditor.features.densitometry import film_profile as fp   # noqa: E402
from photoeditor.features.densitometry import fit                  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "photoeditor", "assets", "film_profiles")
PAGE = 3                    # the "CURVES" page (0-based)
SIGMA = 0.03                # density: the width of the lines, and reading the vendor's chart
POINTS = 40                 # samples along each curve
ID = "kodak-gold-200-kodak-e7022"       # (the first version, "kodak-gold-200-data-sheet", kept the base density in the curves, which gave a colour cast: bundled.REPLACED removes it)
# The chart's frame in PDF points: left edge = log exposure -3, right edge = +1, bottom = density 0, top = density 4 (its ticks fall at 127.8, 173.9, 220.1 for -2, -1, 0 and at
# 239.7, 193.6, 147.4 for densities 1, 2, 3, which the check in `axes` confirms against the frame).
FRAME_WIDTH_PT = 0.43       # the frame is the one drawing stroked at this width with a rectangle of about 185 x 185 points
LAYERS = ("B", "G", "R")    # top to bottom on the chart, as it is labelled


def _find(page):
    drawings = page.get_drawings()
    frame = next(d for d in drawings if d.get("width") and abs(d["width"] - FRAME_WIDTH_PT) < 0.02 and d["items"] and d["items"][0][0] == "re" and d["rect"].width > 150 and d["rect"].width < 200
                 and d["rect"].y0 < 200)
    r = frame["rect"]
    curves = [d for d in drawings if d.get("width") and abs(d["width"] - 0.72) < 0.02 and r.x0 - 1 <= d["rect"].x0 and d["rect"].x1 <= r.x1 + 1 and len(d["items"]) > 10]
    curves.sort(key=lambda d: d["rect"].y0)       # the blue curve is the highest
    if len(curves) != 3:
        raise SystemExit(f"expected three curves inside the chart, found {len(curves)}")
    return r, curves


def _path_points(drawing) -> np.ndarray:
    pts = []
    for item in drawing["items"]:
        if item[0] == "l":
            pts += [(item[1].x, item[1].y), (item[2].x, item[2].y)]
        elif item[0] == "c":
            p0, p1, p2, p3 = item[1:5]
            for t in np.linspace(0.0, 1.0, 9):
                u = 1.0 - t
                pts.append((u ** 3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t ** 3 * p3.x, u ** 3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t ** 3 * p3.y))
    return np.array(pts)


def digitise(pdf: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    page = fitz.open(pdf)[PAGE]
    frame, curves = _find(page)
    unit = frame.width / 4.0                       # four decades of log exposure across, four units of density up: the same scale
    assert abs(frame.height - 4 * unit) < 1.0, (frame.width, frame.height)
    out = {}
    for layer, drawing in zip(LAYERS, curves):
        pts = _path_points(drawing)
        log_e = -3.0 + (pts[:, 0] - frame.x0) / unit
        dens = (frame.y1 - pts[:, 1]) / unit
        order = np.argsort(log_e, kind="stable")
        log_e, dens = log_e[order], dens[order]
        grid = np.linspace(log_e.min(), log_e.max(), POINTS)
        out[layer] = (grid, np.interp(grid, log_e, dens))
    return out


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    data = digitise(sys.argv[1])
    curves = {}
    for layer in "RGB":
        x, y = data[layer]
        # a profile's curves are the density ABOVE the film base (as the inversion and the film curve read them): each layer's lowest density, the orange mask, is taken off, or the
        # three layers would start at 0.25, 0.66 and 0.96 and a neutral scene would come out tinted
        curves[layer] = fp.curve_from_report(fit.fit_curve(x, y - y.min(), sigma=np.full(len(x), SIGMA)), scale="relative", unit="log relative exposure")
    p = fp.new_profile(
        "Kodak Gold 200 (Kodak data sheet)", "supplied", curves, film_stock="Kodak Gold 200", process="C-41",
        notes=("The characteristic curves of Kodak's technical data sheet E-7022 for KODAK GOLD 200 Film (February 2016), read off the vector chart (+-0.03 density): daylight exposure, Status M "
               "densitometry, red, green and blue. The curves are the density above the base (the orange mask, the lowest density of each layer, is taken off and kept as the profile's base). Supplied by the maker's chart, not measured by EFAS, and other rolls and processing differ."),
        conditions={"illuminant": "Daylight", "densitometry": "Status M", "process": "C-41", "log_h_ref": -1.14},
        calibration={"origin": "manufacturer data sheet, read from the printed vector chart", "source": "Kodak Alaris, KODAK GOLD 200 Film, Publication E-7022", "tool": "tools/make_kodak_gold_profile.py"},
    )
    p.id = ID
    base = [float(data[c][1].min()) for c in "RGB"]
    p.base = {"dmin_from_curve": base}
    p.validity = {"log_exposure_range": [float(min(data[c][0].min() for c in "RGB")), float(max(data[c][0].max() for c in "RGB"))],
                  "density_range": [0.0, float(max(data[c][1].max() - data[c][1].min() for c in "RGB"))]}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, ID + ".json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(p.to_dict(), f, indent=1, ensure_ascii=False)
        f.write("\n")
    for ch, g in p.gradients().items():
        x, y = data[ch]
        print(f"{ch}: log E {x.min():.2f} to {x.max():.2f}, D {y.min():.2f} to {y.max():.2f}, chosen {p.curves[ch].chosen}, gamma {g['gamma']:.2f}")
    print("usable for inversion:", p.usable_for_inversion())


if __name__ == "__main__":
    main()
