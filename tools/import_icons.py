"""Copy icons from the Lucide set into src/photoeditor/assets/icon as plain .svg files: python tools/import_icons.py path/to/node_modules/lucide-react

Lucide (https://lucide.dev, ISC licence) is a set of 24x24 line icons. The names wanted are listed in src/photoeditor/desktop/view/panel_icons.py (NAMES). Each one is written
as an ordinary SVG with stroke="currentColor", which the app recolours when it loads the file to match the theme. Nothing is drawn in code: the app only loads these files."""
import json
import os
import re
import shutil
import sys

SKIP_KEYS = {"key"}


def load_node(js_path: str) -> list:
    text = open(js_path, encoding="utf-8").read()
    start = text.index("const __iconNode = ") + len("const __iconNode = ")
    end = text.index(";\n", start)
    literal = re.sub(r'([{,]\s*)([A-Za-z_][\w-]*)\s*:', r'\1"\2":', text[start:end])
    return json.loads(literal)


def to_svg(name: str, node: list) -> str:
    parts = []
    for tag, attrs in node:
        inner = " ".join(f'{k}="{v}"' for k, v in attrs.items() if k not in SKIP_KEYS)
        parts.append(f"  <{tag} {inner} />")
    body = "\n".join(parts)
    return (f'<!-- Lucide "{name}" (ISC licence, see LICENSE-lucide.txt) -->\n'
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round">\n' + body + "\n</svg>\n")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    package = argv[1]
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(here, "src"))
    from photoeditor.desktop.view import panel_icons

    out = os.path.join(here, "src", "photoeditor", "assets", "icon")
    missing = []
    for name in sorted(panel_icons.NAMES):
        source = os.path.join(package, "dist", "esm", "icons", name + ".js")
        if not os.path.isfile(source):
            missing.append(name)
            continue
        with open(os.path.join(out, name + ".svg"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(to_svg(name, load_node(source)))
    shutil.copyfile(os.path.join(package, "LICENSE"), os.path.join(out, "LICENSE-lucide.txt"))
    print(f"{len(panel_icons.NAMES) - len(missing)} icons written to {out}" + (f"; not found: {', '.join(missing)}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
