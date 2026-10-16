"""Rebuild the built-in Scanners (EFAS Original) and Film Stocks presets from a folder of scanner-look and film-look preset files: python tools/build_presets.py path/to/folder

Each source file is converted by src/photoeditor/features/lookpresets/lookconvert.py (the rule is in docs/presets.md); the names and descriptions stay as they are in the two JSON
files in src/photoeditor/assets/presets/, so only the slider values are rewritten."""
import json
import os
import sys

# preset name in EFAS -> the source file (without .json) in the folder
SOURCES = {
    "Scanners (EFAS Original)/Frontier 100": "Frontier",
    "Scanners (EFAS Original)/Crystal 100": "Fuji - Crystal Archive Paper",
    "Scanners (EFAS Original)/Pakon (Clean and Rich)": "Pakon---Clean---Rich",
    "Scanners (EFAS Original)/Noritsu (Green Shadows)": "Noritsu",
    "Film Stocks/Cinestill/Cinestill": "Cinestill",
    "Film Stocks/Fuji/Superia": "Fuji-Superia",
    "Film Stocks/Kodak/Gold": "Kodak-Gold",
    "Film Stocks/Kodak/Portra": "Kodak-Portra",
    "Film Stocks/Kodak/Portra Airy": "Kodak-Portra---Airy",
}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(here, "src"))
    from photoeditor.features.lookpresets import lookconvert

    folder = os.path.join(here, "src", "photoeditor", "assets", "presets")
    changed = 0
    for name in ("lab-scanners.json", "film-stocks.json"):
        path = os.path.join(folder, name)
        data = json.load(open(path, encoding="utf-8"))
        for item in data["presets"]:
            source = SOURCES.get(item["name"])
            if source is None:
                continue
            raw = json.load(open(os.path.join(argv[1], source + ".json"), encoding="utf-8"))
            item["look"] = lookconvert.convert(raw.get("settings", raw))
            changed += 1
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    print(f"{changed} presets rewritten")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
