"""Write the standard and the linear-camera-RGB conversions of one RAW negative side by side: python tools/compare_decode.py scan.ARW out.png

Both go through the same inversion with the default edits; only the RAW decoding differs (see Settings > RAW decoding). Use it to judge the option on your own scans."""
import dataclasses
import os
import sys
import tempfile

import numpy as np
from PIL import Image


def convert(path: str, linear: bool) -> np.ndarray:
    from photoeditor.desktop.render import EditParams, Renderer
    from photoeditor.desktop.session import AppState
    from photoeditor.features.open_image import processor
    from photoeditor.features.settings import logic as settings

    saved = settings.load()
    settings.save({**saved, "raw_linear": linear})
    try:
        preview = processor.make_preview_rgb(processor.load_image_rgb(path))
    finally:
        settings.save(saved)
    params = dataclasses.replace(EditParams.from_state(AppState()), negative_inverted=True)
    return Renderer().render(preview, params, path, preview.shape[1])[0]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(here, "src"))
    os.environ.setdefault("PHOTOEDITOR_DATA_DIR", tempfile.mkdtemp())  # never touch the real settings
    a, b = convert(argv[1], False), convert(argv[1], True)
    Image.fromarray(np.concatenate([a, b], axis=1)).save(argv[2])
    print(f"standard (left) and linear camera RGB (right) written to {argv[2]}; mean difference {np.abs(a.astype(float) - b.astype(float)).mean():.2f} levels")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
