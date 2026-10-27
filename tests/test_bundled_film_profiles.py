"""The Fomapan 100 characteristic curves from the maker's data sheet come with EFAS as supplied film profiles, installed once into the person's folder."""
import numpy as np

from photoeditor.features.densitometry import bundled
from photoeditor.features.densitometry.film_profile import ProfileStore


def test_the_three_fomapan_100_curves_are_there_and_read_right():
    profiles = {p.id: p for p in bundled.available()}
    assert set(profiles) == {"foma-fomapan-100-microphen-5min", "foma-fomapan-100-microphen-7min", "foma-fomapan-100-microphen-11min"}
    at = {}
    for ident, p in profiles.items():
        assert p.kind == "supplied" and p.usable_for_inversion() and set(p.curves) == {"K"} and "Foma" in p.film_stock
        c = p.curves["K"].curve()
        at[ident] = [float(c(x)) for x in (-3.0, -2.0, -1.0, -0.5)]
    five, seven, eleven = (at[f"foma-fomapan-100-microphen-{m}min"] for m in (5, 7, 11))
    # the data sheet's chart: at log exposure -2 the curves are at about 1.0, 1.4 and 1.75, and at -0.5 about 2.05, 2.55 and 2.9
    for got, want in ((five[1], 1.0), (seven[1], 1.4), (eleven[1], 1.73), (five[3], 2.05), (seven[3], 2.55), (eleven[3], 2.9)):
        assert abs(got - want) < 0.08, (got, want)
    assert all(a < b < c for a, b, c in zip(five, seven, eleven)), "a longer development gives more density everywhere"
    for curve in (five, seven, eleven):
        assert np.all(np.diff(curve) > 0), "density rises with exposure"


def test_they_are_installed_once_and_not_put_back(tmp_path):
    store = ProfileStore(str(tmp_path / "film-profiles"))
    added = bundled.install(store)
    assert len(added) == 3 and len(store.ids()) == 3 and all(r["usable"] for r in store.list())
    assert bundled.install(store) == [], "a second look adds nothing"
    store.delete("foma-fomapan-100-microphen-7min")
    assert bundled.install(store) == [] and len(store.ids()) == 2, "a profile the person deleted is not put back"


def test_a_black_and_white_profile_is_offered_only_for_a_black_and_white_negative():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from photoeditor.desktop.view.negative_tool_panel import NegativeToolPanel

    profiles = [
        {"id": "k", "name": "Fomapan 100 - Microphen 7 min", "kind": "supplied", "film": "Foma Fomapan 100", "usable": True, "bw_only": True},
        {"id": "rgb", "name": "My colour film", "kind": "measured", "film": "Portra", "usable": True, "bw_only": False},
    ]
    panel = NegativeToolPanel()
    status = {"engine": "classic", "profile_id": "", "error": "", "covered": None, "base_ready": True}
    panel.set_inversion({**status, "bw": False}, profiles, [])
    assert [panel._engine_profile.itemData(i) for i in range(panel._engine_profile.count())] == ["rgb"], "a colour negative is offered the colour profile only"
    assert panel._engine_profile.isHidden() and panel._ab_btn.isHidden(), "the profile is chosen once Curve-informed is"
    panel.set_inversion({**status, "bw": True}, profiles, [])
    assert [panel._engine_profile.itemData(i) for i in range(panel._engine_profile.count())] == ["k", "rgb"]
    only_k = [profiles[0]]
    panel.set_inversion({**status, "bw": False}, only_k, [])
    assert panel._engine_profile.count() == 0 and not panel._engine.model().item(1).isEnabled() and "black-and-white" in panel._engine_note.text()
    panel.set_inversion({**status, "engine": "curve", "profile_id": "k", "bw": False}, only_k, [])
    assert panel._engine_profile.count() == 1, "a photo already using it keeps it in the list"
    app.processEvents()
