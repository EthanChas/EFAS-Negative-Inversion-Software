"""A film profile's own curve in the Original and Noritsu conversions: the table that straightens density, the print it makes, and the Curve menu."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from photoeditor.features.densitometry.fit import SoftplusCurve  # noqa: E402
from photoeditor.features.densitometry.inversion import ChannelModel  # noqa: E402
from photoeditor.features.negative import filmcurve  # noqa: E402
from photoeditor.features.negative.metering import ENGINES, Metering  # noqa: E402


def _models():
    curve = SoftplusCurve(gamma=1.1, x0=-2.0, dmax=3.0, toe=4.0, shoulder=1.2)
    return {ch: ChannelModel(curve, (-3.2, -0.5)) for ch in "RGB"}


def test_the_profile_is_kept_with_the_photo():
    m = Metering(engine="standard", film_profile="foma-fomapan-100-microphen-5min")
    assert Metering.from_dict(m.to_dict()) == m
    assert Metering(engine="standard").to_dict() == {"engine": "standard", "transfer": "auto"}
    assert Metering.from_dict({"engine": "noritsu", "film_profile": 5}).film_profile == "" and "noritsu" in ENGINES


def test_the_table_straightens_the_toe_and_keeps_the_order_of_tones():
    base = (0.1, 0.1, 0.1)
    full = filmcurve.build(_models(), base, True, "x")
    grid = np.arange(0.0, 5.0, 0.01, dtype=np.float32)
    for c in range(3):
        out = full(grid, c)
        assert (np.diff(out) >= -1e-6).all(), "tones never change order"
    # in the toe a density change means less exposure change than in the straight section, so straightening spreads it: the same step of density becomes a bigger one
    toe = full(np.float32(0.5), 0) - full(np.float32(0.4), 0)
    mid = full(np.float32(1.6), 0) - full(np.float32(1.5), 0)
    assert toe > mid * 1.1 and abs(mid - 0.1) < 0.02, "the straight section is left as it is; the bend of the toe is opened out"
    guess = filmcurve.build(_models(), base, False, "x")
    d = np.float32(0.3)
    assert abs(float(guess(d, 0)) - float(d)) < abs(float(full(d, 0)) - float(d)), "a base that was only estimated is trusted less"


def test_the_print_puts_white_and_black_where_asked_and_is_display_encoded():
    f = filmcurve.build(_models(), (0.1, 0.1, 0.1), True, "x")
    floor, ceil = 0.5, 2.0
    d = np.linspace(floor, ceil, 50, dtype=np.float32)
    p = f.print_positive(d, floor, ceil, 0)
    assert p[0] == 0.0 and abs(float(p[-1]) - 1.0) < 1e-6 and (np.diff(p) >= 0).all()
    assert f.print_positive(np.float32(ceil + 1), floor, ceil, 0) == 1.0 and f.print_positive(np.float32(floor - 1), floor, ceil, 0) == 0.0
    assert 0.45 < float(f.print_positive(np.float32(floor + 0.9 * (ceil - floor)), floor, ceil, 0)) < 1.0, "light, not density: the display encoding lifts the middle"


_SCRIPT = textwrap.dedent(r"""
    import os, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    import numpy as np
    from PyQt6.QtWidgets import QApplication
    app = QApplication([])
    from photoeditor.features.densitometry import bundled, film_profile as fpmod
    from photoeditor.features.datadir import app_data_dir
    store = fpmod.ProfileStore(fpmod.profiles_dir(app_data_dir()))
    bundled.install(store)
    ident = "foma-fomapan-100-microphen-5min"
    assert store.exists(ident)
    from photoeditor.features.negative.metering import Metering
    from photoeditor.desktop.render import EditParams, Renderer, film_curve_wanted
    from photoeditor.desktop.session import AppState
    rng = np.random.default_rng(1)
    ramp = np.linspace(0.18, 0.95, 600)[None, :, None] * np.ones((400, 1, 3))
    codes = np.clip(ramp * 65535 * (0.97 + 0.03 * rng.random((400, 600, 3))), 0, 65535).astype(np.uint16)
    def render(m):
        st = AppState(); st.negative_inverted = True; st.film_type = "bw"; st.metering = m
        return Renderer().render(codes, EditParams.from_state(st), ("fc", str(m)), codes.shape[1], None, want_stats=False, overlay=False, flatfield=None)[0]
    for engine in ("standard", "noritsu"):
        plain, with_curve = Metering(engine=engine, transfer="bt709"), Metering(engine=engine, transfer="bt709", film_profile=ident)
        assert not film_curve_wanted(plain) and film_curve_wanted(with_curve)
        assert not film_curve_wanted(Metering(engine=engine, film_profile="no-such-profile")), "a profile that is not there is ignored"
        a, b = render(plain), render(with_curve)
        assert a.shape == b.shape and not np.array_equal(a, b), engine
        assert np.array_equal(render(Metering(engine=engine, transfer="bt709", film_profile="no-such-profile")), a), "a missing profile leaves the conversion as it was"
        m = b[..., 1].astype(float).mean(axis=0)
        assert m[:30].mean() > m[-30:].mean() + 20, "the denser part of the negative (the left, where the scan is darker) is still the brighter part of the positive"
    assert film_curve_wanted(Metering(engine="print", film_profile=ident)), "the NegPy Conversion puts a profile's real curve back in place of its own S-curve"
    from photoeditor.desktop.view.negative_tool_panel import NegativeToolPanel
    panel = NegativeToolPanel()
    panel.set_inversion({"engine": "classic", "profile_id": "", "error": "", "covered": None, "base_ready": False, "bw": True}, store.list(), [])
    panel.set_metering(Metering(engine="standard", film_profile=ident))
    assert panel._film_profile.currentData() == ident
    assert panel._collect().film_profile == ident
    assert panel._film_profile.itemData(0) == ""
    panel.set_metering(Metering(engine="standard", film_profile="gone"))
    assert panel._collect().film_profile == "gone" and "missing" in panel._film_profile.currentText()
    panel.set_metering(Metering(engine="print"))
    assert not panel._film_profile.isHidden() and not panel._curve_label.isHidden()
    panel.set_metering(Metering(engine="noritsu"))
    assert not panel._film_profile.isHidden()
    print("OK film curve")
""")


def test_the_conversions_use_the_profile_and_the_curve_menu_follows_the_method():
    r = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0 and "OK film curve" in r.stdout, r.stdout[-1500:] + r.stderr[-3000:]
