"""Measure the conversions against pictures they were made from: python tools/benchmark_conversion.py picture.jpg [more pictures ...] [--sheet out.png]

Each picture is exposed onto a modelled colour negative (several films, exposure errors and lights), scanned, converted by each engine, and compared with the picture
(see features/negative/filmsim.py). Lower is better. This measures how well an engine undoes the negative the model describes; it is not a test on real film."""
import itertools
import os
import sys
import tempfile

import numpy as np
from PIL import Image


def load_scene(path: str, width: int = 480) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    img.thumbnail((width, width))
    return np.array(img)


def converters() -> dict:
    """name -> function(scan uint16 (h, w, 3) srgb-encoded, scan_info) -> 8-bit RGB."""
    from photoeditor.features.negative import logic

    def standard(scan16, info):
        lut = logic.compute_invert_lut(scan16)
        out = np.empty(scan16.shape, np.uint8)
        for c in range(3):
            out[..., c] = np.clip(np.rint(lut[c][scan16[..., c]]), 0, 255)
        return out

    found = {"standard": standard}
    try:
        from photoeditor.features.negative import printengine

        found.update(printengine.benchmark_converters())
    except ImportError:
        pass
    return found


def main(argv: list[str]) -> int:
    sheet = None
    if "--sheet" in argv:
        i = argv.index("--sheet")
        sheet = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    paths = [a for a in argv[1:] if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return 2
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(here, "src"))
    os.environ.setdefault("PHOTOEDITOR_DATA_DIR", tempfile.mkdtemp())
    from photoeditor.features.negative import filmsim

    engines = converters()
    cases = list(itertools.product(("standard", "flat", "contrasty"), (-1.0, 0.0, 1.5), ((1, 1, 1), (1.5, 1.0, 0.6))))
    totals = {n: [] for n in engines}
    rows = []
    for path in paths:
        original = load_scene(path)
        scene = filmsim.srgb_to_linear(original)
        for film_name, stops, light in cases:
            density = filmsim.expose(scene, filmsim.FILMS[film_name], stops, light)
            scan16 = filmsim.scan(density, encode="srgb")
            for name, convert in engines.items():
                result = convert(scan16, {"density": density, "film": filmsim.FILMS[film_name]})
                s = filmsim.score(result, original)
                totals[name].append(s)
                rows.append((os.path.basename(path), film_name, stops, light, name, s))
    print(f"{len(paths)} pictures x {len(cases)} negatives each")
    print(f"{'engine':<22}{'colour':>9}{'tone':>9}{'cast':>9}{'clipped':>9}{'total':>9}")
    for name, scores in totals.items():
        print(f"{name:<22}{np.mean([s.chroma_error for s in scores]):9.2f}{np.mean([s.tone_error for s in scores]):9.2f}{np.mean([s.cast for s in scores]):9.2f}"
              f"{100 * np.mean([s.clipped for s in scores]):8.1f}%{np.mean([s.total() for s in scores]):9.2f}")
    print("\nby light (colour error / cast):")
    for light in sorted({r[3] for r in rows}):
        print(f"  light {light}:", "  ".join(f"{n}: {np.mean([r[5].chroma_error for r in rows if r[4] == n and r[3] == light]):.1f}/{np.mean([r[5].cast for r in rows if r[4] == n and r[3] == light]):.1f}" for n in engines))
    print("by film (colour error):")
    for film in sorted({r[1] for r in rows}):
        print(f"  {film}:", "  ".join(f"{n}: {np.mean([r[5].chroma_error for r in rows if r[4] == n and r[1] == film]):.1f}" for n in engines))
    print("by exposure error (colour error, tone):")
    for stops in sorted({r[2] for r in rows}):
        print(f"  {stops:+}:", "  ".join(f"{n}: {np.mean([r[5].chroma_error for r in rows if r[4] == n and r[2] == stops]):.1f}/{np.mean([r[5].tone_error for r in rows if r[4] == n and r[2] == stops]):.1f}" for n in engines))
    if sheet:
        original = load_scene(paths[0], 320)
        scene = filmsim.srgb_to_linear(original)
        rows_img = []
        for film_name, stops, light in (("standard", 0.0, (1, 1, 1)), ("contrasty", 1.5, (1.5, 1.0, 0.6)), ("flat", -1.0, (1, 1, 1))):
            density = filmsim.expose(scene, filmsim.FILMS[film_name], stops, light)
            scan16 = filmsim.scan(density, encode="srgb")
            tiles = [original] + [convert(scan16, {"density": density}) for convert in engines.values()]
            rows_img.append(np.concatenate(tiles, axis=1))
        Image.fromarray(np.concatenate(rows_img, axis=0)).save(sheet)
        print("sheet:", sheet, "columns: original,", ", ".join(engines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
