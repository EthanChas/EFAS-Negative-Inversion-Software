"""Rebuild the built-in "Film Stocks (DarkSlide)" presets from DarkSlide's source: python tools/build_darkslide_presets.py path/to/DarkSlide/src/constants.ts

DarkSlide (https://github.com/kilianvivien/DarkSlide, MIT licence, (c) 2026 Kilian Vivien) lists its film profiles in constants.ts as createBuiltinProfile({...}) blocks with a
tonal character looked up by name. This reads each profile's name, category, type, description, the settings it changes from the defaults and its tonal character, and
features/lookpresets/lookconvert.convert_darkslide_film turns them into EFAS sliders (the rule is in docs/presets.md). The file written is assets/presets/film-stocks-darkslide.json."""
import json
import os
import re
import sys

STRING = r": (?:'((?:[^'\\]|\\.)*)'|\"([^\"]*)\")"   # a TypeScript string in single or double quotes
SETTING_KEYS = ("exposure", "contrast", "saturation", "temperature", "tint", "redBalance", "greenBalance", "blueBalance", "highlightProtection", "blackPoint", "whitePoint")


def parse(source: str) -> list[dict]:
    characters = {}
    for m in re.finditer(r"^\s*(?:'([^']+)'|(\w+)): \{ shadowLift: ([\d.\-]+), highlightRolloff: ([\d.\-]+), midtoneAnchor: ([\d.\-]+) \}", source, re.M):
        characters[m.group(1) or m.group(2)] = {"shadowLift": float(m.group(3)), "highlightRolloff": float(m.group(4)), "midtoneAnchor": float(m.group(5))}
    start = source.index("export const FILM_PROFILES")
    block = source[start:source.index("\n];", start)]
    profiles = []
    for chunk in block.split("createBuiltinProfile({")[1:]:
        def text(key: str) -> str:
            found = re.search(key + STRING, chunk)
            return (found.group(1) or found.group(2) or "").replace("\\'", "'") if found else ""

        defaults = re.search(r"defaultSettings: createDefaultSettings\(\{(.*?)\}\)", chunk, re.S)
        settings = {k: float(v) for k, v in re.findall(r"(\w+): (-?[\d.]+)", defaults.group(1)) if k in SETTING_KEYS} if defaults else {}
        tonal = re.search(r"tonalCharacter: TONAL_CHARACTERS(?:\['([^']+)'\]|\.(\w+))", chunk)
        profiles.append({"id": text(r"\bid"), "name": text(r"\bname"), "type": text(r"\btype"), "filmType": text("filmType"), "category": text("category"),
                         "description": text("description"), "settings": settings, "tonal": characters.get((tonal.group(1) or tonal.group(2)) if tonal else None)})
    return profiles


def preset_name(profile: dict) -> str:
    """Folder by maker, then the stock's name without the maker's name in front: Kodak Portra 400 -> Kodak/Portra 400."""
    name, maker = profile["name"], profile["category"]
    if name.lower().startswith(maker.lower() + " "):
        name = name[len(maker) + 1:]
    return f"Film Stocks (DarkSlide)/{maker}/{name}"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(here, "src"))
    from photoeditor.features.lookpresets import lookconvert

    profiles = parse(open(argv[1], encoding="utf-8").read())
    presets = []
    for p in profiles:
        kind = "slide film (a positive: EFAS inverts negatives, so only the look applies)" if p["filmType"] == "slide" else "negative film"
        presets.append({
            "name": preset_name(p),
            "description": f"{p['description']} DarkSlide's profile for this {kind}: its contrast, saturation, temperature and tint, and its tonal character as Fade and Shoulder.",
            "look": lookconvert.convert_darkslide_film(p),
        })
    data = {
        "about": "The film profiles that ship with DarkSlide (github.com/kilianvivien/DarkSlide, MIT licence, (c) 2026 Kilian Vivien) as looks: contrast, saturation, temperature and tint carried "
                 "over, its tonal character (shadow lift and highlight roll-off) as Lab Look's Fade and the Print Response Shoulder. Its exposure, colour balance, black and white points, "
                 "highlight protection and colour matrices correct for DarkSlide's own inversion and are not carried over. See docs/presets.md.",
        "presets": presets,
    }
    path = os.path.join(here, "src", "photoeditor", "assets", "presets", "film-stocks-darkslide.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"{len(presets)} presets written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
