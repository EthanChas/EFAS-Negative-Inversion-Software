"""The standard inversion and the render pipeline give exactly the output they gave before Tier 2.

The fingerprints below were computed on commit ae7f9de (the last commit before Tier 2) and on the current code, and were identical. If one of these tests
fails, the standard method has changed: that must be a deliberate decision, never a side effect of work on the curve-informed method.
"""
import hashlib
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

PINNED = {
    "lut8": "2d302c81f572a416",
    "lut16": "7794a133c573ba48",
    "lut8_base": "e9002475e57d945d",
    "lut8_meter": "efd4c776d9174344",
    "invert8": "d27ed247a2348482",
    "mode": "c41",
    "params_inverted": "True",
    "render8": "d27ed247a2348482",
    "render8_hist": "51a6f3a59ff08335",
    "render16": "ee0827503a34af55",
    "render16_hist": "efe01638750ff677",
}

_SCRIPT = textwrap.dedent(r'''
    import hashlib, os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
    import numpy as np
    from photoeditor.features.negative.logic import compute_invert_lut, invert_negative, detect_process_mode
    from photoeditor.features.negative.metering import Metering
    rng = np.random.default_rng(42)
    base = np.linspace(40, 230, 120)[None, :, None] * np.array([1.0, 0.8, 0.55])[None, None, :]
    img8 = np.clip(np.repeat(base, 90, axis=0) + rng.normal(0, 3, (90, 120, 3)), 0, 255).astype(np.uint8)
    img16 = (img8.astype(np.uint16) * 257 + rng.integers(0, 200, img8.shape)).astype(np.uint16)
    h = lambda a: hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()[:16]
    out = {}
    out["lut8"] = h(compute_invert_lut(img8))
    lut16 = compute_invert_lut(img16)
    arrays = {"lut16": np.asarray(lut16)}
    out["lut16"] = h(lut16)
    out["lut8_base"] = h(compute_invert_lut(img8, None, (200, 150, 100)))
    out["lut8_meter"] = h(compute_invert_lut(img8, None, None, Metering(buffer=0.05, white=0.2, black=-0.1)))
    out["invert8"] = h(invert_negative(img8))
    out["mode"] = detect_process_mode(img8).value
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.desktop.render import EditParams, Renderer
    from photoeditor.desktop.session import AppState
    st = AppState(); st.negative_inverted = True
    params = EditParams.from_state(st)
    out["params_inverted"] = str(bool(params.negative_inverted))
    for tag, arr in (("render8", img8), ("render16", img16)):
        image, pre, stats, ov = Renderer().render(arr, params, ("fp", tag), arr.shape[1], None, want_stats=True, overlay=False, flatfield=None)
        out[tag] = h(image)
        hist = np.concatenate([np.asarray(stats["histogram"][k], dtype=np.float64).ravel() for k in ("r", "g", "b")])
        out[tag + "_hist"] = h(hist)
        arrays[tag] = np.asarray(image)
        arrays[tag + "_hist"] = hist
    if os.environ.get("EFAS_DUMP"):
        np.savez_compressed(os.environ["EFAS_DUMP"], **arrays)
    for k, v in out.items():
        print(f"{k}={v}")
''')


FLOAT_DEPENDENT = ("lut16", "render16", "render16_hist")
REFERENCE = Path(__file__).resolve().parent / "data" / "classic_16bit_reference.npz"


def test_the_standard_inversion_and_render_are_bit_identical_to_before_tier_2(tmp_path):
    """Everything made of integers is pinned exactly on every system. The 16-bit results come out of floating-point maths, whose last bit differs between
    versions of numpy and OpenCV and between processors, so they are compared with a stored reference to within two codes (they match exactly where the
    pinned fingerprints were made)."""
    import numpy as np

    dump = tmp_path / "dump.npz"
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""), EFAS_DUMP=str(dump))
    done = subprocess.run([sys.executable, "-c", _SCRIPT], env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    got = dict(line.split("=", 1) for line in done.stdout.strip().splitlines() if "=" in line)
    exact = {k: v for k, v in PINNED.items() if k not in FLOAT_DEPENDENT}
    assert {k: got.get(k) for k in exact} == exact, {k: (got.get(k), exact[k]) for k in exact if got.get(k) != exact[k]}
    mine, ref = np.load(dump), np.load(REFERENCE)
    for key in ("lut16", "render16"):
        assert mine[key].shape == ref[key].shape
        assert int(np.abs(mine[key].astype(np.int64) - ref[key].astype(np.int64)).max()) <= 2, key
    assert np.allclose(mine["render16_hist"], ref["render16_hist"], rtol=1e-6, atol=1e-9)
    if all(got.get(k) == PINNED[k] for k in FLOAT_DEPENDENT):
        assert all(np.array_equal(mine[k], ref[k]) for k in ref.files), "the fingerprints match, so the arrays must too"


def test_a_photo_without_a_curve_choice_renders_with_the_standard_method(tmp_path):
    """EditParams for a state with the default method still inverts exactly as before, and the curve switch only takes effect when it is on."""
    script = textwrap.dedent(r'''
        import os, tempfile
        os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp()
        from PyQt6.QtWidgets import QApplication
        app = QApplication([])
        from photoeditor.desktop.render import EditParams
        from photoeditor.desktop.session import AppState
        s = AppState(); s.negative_inverted = True
        assert s.inversion_engine == "classic" and EditParams.from_state(s).negative_inverted is True
        s.inversion_engine = "curve"
        assert EditParams.from_state(s).negative_inverted is False
        s.negative_inverted = False; s.inversion_engine = "classic"
        assert EditParams.from_state(s).negative_inverted is False
        print("OK")
    ''')
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and "OK" in done.stdout, done.stderr[-1500:]
