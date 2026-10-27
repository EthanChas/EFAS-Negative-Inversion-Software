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
