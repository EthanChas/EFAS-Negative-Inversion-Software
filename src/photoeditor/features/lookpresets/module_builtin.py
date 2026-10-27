"""darktable's own presets for the three modules ported from it that come with some (Diffuse or Sharpen, Tone Equalizer, Color Balance RGB) - read-only, shown at the foot of the
module's Presets menu. Each is the module's fields (features/lookpresets/modules.py) as darktable sets them. No Qt imports."""
from ..colorbalancergb import logic as color_balance
from ..diffuse import logic as diffuse
from ..toneequalizer import logic as tone_eq
from .modules import panel_fields

_SOURCES = {"diffuse": diffuse.PRESETS, "toneequalizer": tone_eq.PRESETS, "colorbalancergb": color_balance.PRESETS}
_PAPERS = "Papers (NegPy)/"     # the paper simulations are Print Response's settings: they are listed in its menu too ("B&W | Ilford Multigrade RC" is Ilford Multigrade RC in a B&W submenu)


def _source(module: str) -> dict:
    if module == "printresponse":
        from . import builtin

        return {p["name"][len(_PAPERS):].replace("/", " | "): p["look"] for p in builtin.load() if p["name"].startswith(_PAPERS)}
    return _SOURCES.get(module, {})


def names(module: str) -> list[str]:
    return list(_source(module))


def get(module: str, name: str) -> dict | None:
    """The preset's values for the module's fields (what it does not set stays as the field's default is not touched: the caller starts from the module's defaults)."""
    preset = _source(module).get(name)
    if preset is None:
        return None
    keys = {f.key for f in panel_fields(module)}
    return {k: v for k, v in preset.items() if k in keys}
