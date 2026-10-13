"""The plugin documentation and examples must stay true: every code block parses, every link and anchor exists, every function the docs promise exists, and the bundled
example plugins load and run against a fake window."""
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))

from photoeditor.plugins import api as plugin_api  # noqa: E402
from photoeditor.plugins import manifest as plugin_manifest  # noqa: E402
from photoeditor.plugins import measure, templates  # noqa: E402
from plugin_fakes import make_manager  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "plugins"
FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.S | re.M)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _blocks(language: str):
    found = []
    for path in sorted(DOCS.glob("*.md")) + [ROOT / "README.md"]:
        for match in FENCE.finditer(path.read_text(encoding="utf-8")):
            if match.group(1) == language:
                found.append(pytest.param(match.group(2), id=f"{path.name}:{match.start()}"))
    return found


@pytest.mark.parametrize("code", _blocks("python"))
def test_python_blocks_in_the_docs_compile(code):
    compile(code, "<doc>", "exec")


@pytest.mark.parametrize("code", _blocks("lua"))
def test_lua_blocks_in_the_docs_parse(code):
    from lupa.lua54 import LuaRuntime

    lua = LuaRuntime(register_eval=False, register_builtins=False)
    result = lua.eval("function(src) return load(src, '=doc', 't') end")(code)
    assert callable(result) or not isinstance(result, tuple), result


@pytest.mark.parametrize("code", _blocks("json"))
def test_json_blocks_in_the_docs_parse(code):
    json.loads(code)


def _slug(heading: str) -> str:
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower().replace("`", ""))
    return text.replace(" ", "-")


def test_links_and_anchors_in_the_plugin_docs_resolve():
    pages = {p.name: p for p in DOCS.glob("*.md")}
    assert {"README.md", "getting-started.md", "manifest.md", "api-reference.md", "ui-and-modules.md", "events.md", "lua.md", "python.md", "plugin-output.md",
            "security.md", "examples.md"} <= set(pages)
    for page in list(pages.values()) + [ROOT / "README.md"]:
        text = page.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if target.startswith(("http://", "https://", "mailto:")) or (page.name == "README.md" and page.parent == ROOT and "docs/plugins" not in target):
                continue
            file_part, _, anchor = target.partition("#")
            destination = page if not file_part else (page.parent / file_part).resolve()
            assert destination.exists(), f"{page.name}: {target} does not exist"
            if anchor and destination.suffix == ".md":
                headings = [_slug(h) for h in re.findall(r"^#+\s+(.*)$", destination.read_text(encoding="utf-8"), re.M)]
                assert anchor in headings, f"{page.name}: {target}: no heading '{anchor}' in {destination.name}"


def test_every_function_in_the_api_is_documented():
    text = (DOCS / "api-reference.md").read_text(encoding="utf-8") + (DOCS / "ui-and-modules.md").read_text(encoding="utf-8")
    for name in plugin_api.FUNCTIONS:
        assert re.search(rf"`{name}\b", text), f"{name} is not in the plugin docs"
    for name in plugin_api.MODULE_METHODS + plugin_api.WIDGET_METHODS:
        assert re.search(rf"`{name}\b", text), f"{name} is not in the plugin docs"
    events = (DOCS / "events.md").read_text(encoding="utf-8")
    for event in plugin_api.EVENTS:
        assert f"`{event}`" in events, event
    for tab in plugin_api.TABS:
        assert f'`"{tab}"`' in (DOCS / "ui-and-modules.md").read_text(encoding="utf-8"), tab
    for key in plugin_api.EDIT_KEYS:
        assert f"`{key}`" in (DOCS / "api-reference.md").read_text(encoding="utf-8"), key
    assert f"(version {plugin_api.API_VERSION})" in (DOCS / "api-reference.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ the bundled examples
def test_the_example_plugins_are_all_valid_and_the_doc_lists_them():
    folders = templates.example_folders()
    assert len(folders) == 5
    ids = set()
    for folder in folders:
        manifest, error = plugin_manifest.load_manifest(str(folder))
        assert manifest is not None, f"{folder.name}: {error}"
        assert manifest.api <= plugin_api.API_VERSION
        ids.add(manifest.id)
        assert manifest.name in (DOCS / "examples.md").read_text(encoding="utf-8"), manifest.name
    assert len(ids) == 5


def test_install_examples_copies_once_and_never_overwrites(tmp_path):
    target = tmp_path / "plugins"
    assert len(templates.install_examples(str(target))) == 5
    (target / "hello-lua" / "main.lua").write_text("-- mine", encoding="utf-8")
    assert templates.install_examples(str(target)) == []
    assert (target / "hello-lua" / "main.lua").read_text(encoding="utf-8") == "-- mine"
    assert not list(target.rglob("__pycache__"))


def test_the_examples_load_and_work_against_the_fake_window(qapp, tmp_path):
    manager, host, _store = make_manager(tmp_path)
    templates.install_examples(manager.folder())
    manager.refresh()
    for entry in manager.entries():
        manager.set_enabled(entry.id, True)
    assert {e.id: (e.state, e.error) for e in manager.entries()} == {e.id: ("loaded", "") for e in manager.entries()}
    titles = {m.title: m for m in host.modules}
    assert {"Hello (Lua)", "Hello (Python)", "Exposure steps"} <= set(titles)
    assert titles["Exposure steps"].tab == "exposure"
    # Exposure Steps: the Brighter button raises the exposure by a third of a stop
    brighter = [w for w in titles["Exposure steps"].widgets if w.text.startswith("Brighter")][0]
    brighter.press()
    assert host.edits[-1] == {"exposure_ev": pytest.approx(1 / 3)}
    # Hello (Lua): the button counts, and remembers the count
    click = [w for w in titles["Hello (Lua)"].widgets if w.text == "Click me"][0]
    click.press(); click.press()
    assert [w for w in titles["Hello (Lua)"].widgets if w.text.startswith("Pressed")]
    # Tag by Exposure tags the open photo
    items = {i.label: i for i in host.menu_items}
    items["Tag this photo"].trigger()
    assert any(t.startswith("Exposure/") for t in host.tags[1:])
    # Photo Report shows a report, and asks where to save
    items["Report on this photo"].trigger()
    assert host.messages and "a.tif" in host.messages[-1][1]
    host.dialog_answers["save_path"] = str(tmp_path / "report.txt")
    items["Save a report..."].trigger()
    assert "a.tif" in (tmp_path / "report.txt").read_text(encoding="utf-8")
    assert manager.logbook.error_count() == 0, [r.line() for r in manager.logbook.records(minimum="error")]


# ------------------------------------------------------------------ new-plugin templates
@pytest.mark.parametrize("language", ["python", "lua"])
def test_a_new_plugin_template_is_valid_and_loads(qapp, tmp_path, language):
    manager, host, _store = make_manager(tmp_path)
    folder = templates.create_template(manager.folder(), 'My "Cool" Tool', language, author="Me")
    manifest, error = plugin_manifest.load_manifest(folder)
    assert manifest is not None and manifest.language == language and manifest.name == 'My "Cool" Tool' and manifest.id == "user.my-cool-tool", error
    manager.refresh()
    manager.set_enabled(manifest.id, True)
    assert manager.entry(manifest.id).state == "loaded", manager.entry(manifest.id).error
    assert host.menu_items and host.menu_items[0].label == "Do something"


def test_new_plugin_template_refuses_bad_or_taken_names(tmp_path):
    with pytest.raises(ValueError):
        templates.create_template(str(tmp_path), "!", "lua")
    with pytest.raises(ValueError):
        templates.create_template(str(tmp_path), "Fine name", "ruby")
    templates.create_template(str(tmp_path), "Fine name", "lua")
    with pytest.raises(ValueError, match="already"):
        templates.create_template(str(tmp_path), "fine  name", "lua")


# ------------------------------------------------------------------ measuring the picture
def test_statistics_describe_the_picture():
    grey = np.full((40, 60, 3), 128, np.uint8)
    stats = measure.statistics(grey)
    assert stats["mean"] == pytest.approx(128, abs=0.5) and stats["median"] == pytest.approx(128, abs=0.5)
    assert stats["midtones_pct"] == 100 and stats["shadows_pct"] == 0 and stats["blown_pct"] == 0 and stats["saturation"] == 0
    half = np.zeros((10, 10, 3), np.uint8)
    half[:, 5:] = 255
    s = measure.statistics(half)
    assert s["blocked_pct"] == 50 and s["blown_pct"] == 50 and s["shadows_pct"] == 50 and s["highlights_pct"] == 50 and s["midtones_pct"] == 0
    red = np.zeros((4, 4, 3), np.uint8)
    red[:, :, 0] = 200
    assert measure.statistics(red)["saturation"] == 1 and measure.statistics(red)["r"] == 200
    assert measure.statistics(None) is None and measure.statistics(np.zeros((0, 0, 3), np.uint8)) is None


def test_sampling_and_scaling_the_picture():
    img = np.arange(5 * 7 * 3, dtype=np.uint8).reshape(5, 7, 3)
    assert measure.sample(img, 0, 0) == {"r": 0, "g": 1, "b": 2} and measure.sample(img, 7, 0) is None and measure.sample(img, -1, 0) is None and measure.sample(None, 0, 0) is None
    big = np.zeros((1000, 2000, 3), np.uint8)
    small = measure.scaled(big, 500)
    assert small.shape == (250, 500, 3) and small.dtype == np.uint8
    assert measure.scaled(img, 500).shape == (5, 7, 3) and measure.scaled(None, 500) is None
    copy = measure.scaled(img, 500)
    copy[:] = 0
    assert img.max() > 0, "a plugin changing the array must not change the picture"
