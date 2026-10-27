"""A scanner's colour is Lab Look's Scanner colour, not a preset: the presets that come with EFAS carry no scanner (and no Noritsu preset: the Noritsu look is a conversion method), so a look
never stacks a second scanner response on top of Lab Look's."""
import json

from photoeditor.features.lookpresets import builtin


def _shipped():
    out = []
    for path in sorted(builtin.PRESET_DIR.glob("*.json")):
        out += json.loads(path.read_text(encoding="utf-8")).get("presets", [])
    return out


def test_the_presets_that_come_with_efas_have_no_scanner_or_noritsu_presets():
    shipped = _shipped()
    names = [p["name"] for p in shipped]
    assert names and not any(n.startswith("Scanners") or "noritsu" in n.casefold() for n in names), names
    for p in shipped:
        assert p["look"].get("lab_response", "none") == "none", p["name"]


def test_lab_look_keeps_its_scanner_colour():
    from photoeditor.features.colormix import logic as cm
    assert {"frontier", "pakon", "crystal"} <= set(cm.RESPONSES)


def test_an_extra_folder_of_presets_can_be_read(monkeypatch, tmp_path):
    (tmp_path / "x.json").write_text(json.dumps({"presets": [{"name": "Extra/One", "description": "d", "look": {"saturation": 0.2}}]}), encoding="utf-8")
    monkeypatch.setenv("PHOTOEDITOR_EXTRA_PRESETS", str(tmp_path))
    builtin.reload()
    try:
        assert "Extra/One" in builtin.names() and builtin.get("Extra/One") == {"saturation": 0.2} and "Film Stocks/Kodak/Portra" in builtin.names()
    finally:
        monkeypatch.undo()
        builtin.reload()
