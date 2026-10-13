"""Plugins in Python and Lua: the manifest, the Plugin Output log, the Lua sandbox, the API, and loading / running / unloading plugins - all against a fake window."""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from plugin_fakes import FakeHost, MemoryStore, make_manager, write_plugin  # noqa: E402

from photoeditor.plugins import manifest as M  # noqa: E402
from photoeditor.plugins.logbook import Logbook  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def pump(app, until, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until():
            return True
        time.sleep(0.005)
    return False


def logs(manager, plugin=None, minimum="debug"):
    return [(r.level, r.text) for r in manager.logbook.records(plugin, minimum)]


# ------------------------------------------------------------------ the manifest
def test_a_good_manifest_is_read(tmp_path):
    write_plugin(tmp_path, "hello", "lua", "print('x')", id="com.example.hello", name="Hello", version="1.2", author="Me", description="Says hi")
    manifest, error = M.load_manifest(str(tmp_path / "hello"))
    assert error == "" and (manifest.id, manifest.name, manifest.version, manifest.language, manifest.entry, manifest.api) == ("com.example.hello", "Hello", "1.2", "lua", "main.lua", 1)
    assert manifest.entry_path == str(tmp_path / "hello" / "main.lua") and manifest.author == "Me"


def test_the_entry_defaults_to_main_py_or_main_lua_and_names_default_to_the_id(tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "plugin.json").write_text(json.dumps({"id": "plain.one"}), encoding="utf-8")
    (folder / "main.py").write_text("def register(api): pass", encoding="utf-8")
    manifest, error = M.load_manifest(str(folder))
    assert error == "" and manifest.entry == "main.py" and manifest.language == "python" and manifest.name == "plain.one" and manifest.version == "0"


@pytest.mark.parametrize("data, fragment", [
    ({"name": "x"}, '"id"'), ({"id": "Bad Id!"}, '"id"'), ({"id": "a"}, '"id"'), ({"id": "ok.id", "entry": "main.rb"}, ".py"),
    ({"id": "ok.id", "entry": "../evil.lua"}, "inside the plugin"), ({"id": "ok.id", "entry": "/abs/main.lua"}, "inside the plugin"),
    ({"id": "ok.id", "entry": "missing.lua"}, "is not in the plugin"), ({"id": "ok.id", "entry": "main.lua", "language": "python"}, "does not match"),
    ({"id": "ok.id", "entry": "main.lua", "api": 99}, "update EFAS"), ({"id": "ok.id", "entry": "main.lua", "api": "one"}, '"api"'),
    ([], "one JSON object"),
])
def test_a_bad_manifest_says_what_is_wrong(tmp_path, data, fragment):
    (tmp_path / "main.lua").write_text("", encoding="utf-8")
    manifest, error = M.parse_manifest(data, str(tmp_path))
    assert manifest is None and fragment in error, error


def test_discovery_lists_good_and_bad_folders_and_skips_hidden_ones(tmp_path):
    write_plugin(tmp_path, "good", "lua", "")
    write_plugin(tmp_path, "twin", "lua", "", id="good")  # the same id as the first
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "plugin.json").write_text("{ nope", encoding="utf-8")
    (tmp_path / "empty").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "_private").mkdir()
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    found = {os.path.basename(f.folder): f for f in M.discover(str(tmp_path))}
    assert set(found) == {"broken", "empty", "good", "twin"}
    assert found["good"].manifest.id == "good" and found["twin"].manifest is None and "already uses the id" in found["twin"].error
    assert "could not be read" in found["broken"].error and "no plugin.json" in found["empty"].error
    assert M.discover(str(tmp_path / "nowhere")) == []


# ------------------------------------------------------------------ the log
def test_the_logbook_keeps_filters_and_notifies():
    book = Logbook(limit=5)
    heard = []
    book.subscribe(heard.append)
    book.subscribe(lambda r: 1 / 0)  # a broken listener changes nothing
    for i in range(7):
        book.add("Alpha" if i % 2 else "Beta", ["debug", "info", "warn", "error"][i % 4], f"m{i}")
    assert [r.text for r in book.records()] == ["m2", "m3", "m4", "m5", "m6"], "the oldest drop off"
    assert [r.text for r in book.records("Alpha")] == ["m3", "m5"] and [r.text for r in book.records(minimum="warn")] == ["m2", "m3", "m6"]
    assert book.plugins() == ["Alpha", "Beta"] and book.error_count() == 1 and len(heard) == 7
    assert book.add("X", "nonsense", "t").level == "info"
    assert "[Alpha]" in book.records("Alpha")[0].line() and "ERROR" in book.records(minimum="error")[0].line()
    book.clear()
    assert book.records() == []


# ------------------------------------------------------------------ the Lua box
@pytest.fixture
def sandbox(tmp_path):
    from photoeditor.plugins.lua_sandbox import LuaSandbox

    out = []
    box = LuaSandbox(lambda level, text: out.append((level, text)), str(tmp_path), cpu_seconds=0.6)
    box.out = out
    box.root = tmp_path
    return box


def run(box, source):
    from photoeditor.plugins.lua_sandbox import LuaError

    path = box.root / "t.lua"
    path.write_text(source, encoding="utf-8")
    try:
        box.run_file(str(path))
        return ""
    except LuaError as exc:
        return str(exc)


def test_print_goes_to_the_log_and_the_ordinary_language_works(sandbox):
    assert run(sandbox, "print('a', 1, nil, true); local t = {} for i = 1, 3 do t[#t+1] = i * i end print(table.concat(t, ','), #'héllo', math.floor(2.7), string.format('%.1f', 2))") == ""
    assert sandbox.out == [("info", "a\t1\tnil\ttrue"), ("info", "1,4,9\t6\t2\t2.0")]
    assert run(sandbox, "print(os.time() > 0, type(os.clock()), os.date('%Y') ~= nil, utf8.len('añb'))") == "" and sandbox.out[-1][1] == "true\tnumber\ttrue\t3"


@pytest.mark.parametrize("code", [
    "os.execute('echo hi')", "os.remove('x')", "io.open('x')", "return package.loaded", "dofile('x')", "loadfile('x')", "debug.getinfo(1)", "python.eval('1')",
    "string.dump(print)", "require('os')", "require('../x')", "require('c:/windows/x')", "return collectgarbage()", "os.getenv('PATH')", "os.exit()",
])
def test_the_dangerous_parts_of_lua_are_missing(sandbox, code):
    assert run(sandbox, code) != "", code


def test_load_takes_text_only(sandbox):
    assert run(sandbox, "local f = load(string.char(27) .. 'Lua'); assert(f == nil)") == ""
    assert run(sandbox, "local f = load('return 1 + 1'); assert(f() == 2)") == ""
    assert run(sandbox, "load(print)") != ""


def test_require_loads_other_files_in_the_plugins_own_folder_only(sandbox):
    (sandbox.root / "util").mkdir()
    (sandbox.root / "util" / "math2.lua").write_text("local M = {} function M.twice(x) return x * 2 end return M", encoding="utf-8")
    (sandbox.root / "helper.lua").write_text("count = (count or 0) + 1 return { n = count }", encoding="utf-8")
    assert run(sandbox, "local m = require('util.math2'); print(m.twice(21)); local a, b = require('helper'), require('helper'); print(a == b, a.n)") == ""
    assert sandbox.out[-2:] == [("info", "42"), ("info", "true\t1")]
    assert "not found" in run(sandbox, "require('nothere')")
    assert "bad module name" in run(sandbox, "require('a/../../b')")
    (sandbox.root / "broken.lua").write_text("local = ", encoding="utf-8")
    assert "broken.lua" in run(sandbox, "require('broken')")


@pytest.mark.parametrize("code", ["while true do end", "local co = coroutine.wrap(function() while true do end end) co()", "repeat local x = 1 until false"])
def test_a_loop_that_never_ends_is_stopped(sandbox, code):
    started = time.time()
    assert "ran for too long" in run(sandbox, code)
    assert time.time() - started < 5
    assert run(sandbox, "print('still fine')") == "", "and the next call works"


def test_errors_carry_the_file_and_line_and_a_syntax_error_is_reported(sandbox):
    assert "t.lua:2" in run(sandbox, "local x = 1\nerror('boom')")
    assert "unexpected symbol" in run(sandbox, "local x = 5 +")


def test_python_objects_stay_out_of_reach(sandbox):
    probe = sandbox.lua.eval("function(f) return f.__class__ end")
    with pytest.raises(AttributeError):
        probe(print)


def test_values_cross_between_lua_and_python(sandbox):
    assert sandbox.to_python(sandbox.lua.eval("{1, 2, {a = 1}}")) == [1, 2, {"a": 1}]
    assert sandbox.to_python(sandbox.lua.eval("{a = 1, b = {2, 3}, [5] = true}")) == {"a": 1, "b": [2, 3], 5: True}
    assert sandbox.to_python(sandbox.lua.eval("{}")) == {} and sandbox.to_python(7) == 7 and sandbox.to_python("s") == "s"
    table = sandbox.to_lua({"x": [1, 2], "y": {"z": 1.5}, "s": "t", "n": None})
    assert sandbox.to_python(table) == {"x": [1, 2], "y": {"z": 1.5}, "s": "t"}


# ------------------------------------------------------------------ loading and running plugins
def test_every_plugin_starts_switched_off_and_switching_on_is_remembered(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "alpha", "lua", "print('alpha loaded')")
    manager, host, store = make_manager(tmp_path)
    manager.load_enabled()
    entry = manager.entry("alpha")
    assert entry.state == "disabled" and not entry.enabled and logs(manager, "alpha") == [], "nothing runs until the user switches it on"
    manager.set_enabled("alpha", True)
    assert entry.state == "loaded" and store.enabled == {"alpha": True} and ("info", "alpha loaded") in logs(manager, "alpha")
    again, _h, _s = make_manager(tmp_path, store=store)
    again.load_enabled()
    assert again.entry("alpha").state == "loaded", "the next run loads it by itself"
    manager.set_enabled("alpha", False)
    assert entry.state == "disabled" and store.enabled == {"alpha": False}
    manager.shutdown()
    again.shutdown()


def test_a_python_plugin_registers_and_can_be_unloaded(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "pyhello", "python", """
        import helper
        calls = []
        def register(api):
            api.log("registered, helper says " + helper.HELLO)
            api.add_menu_item("Say hi", lambda: api.notify("hi from " + api.plugin_id), shortcut="Ctrl+Alt+H")
            module = api.add_module("My module")
            module.add_button("Press", on_click=lambda: api.log("pressed"))
        def unregister():
            import sys
            sys.modules["builtins"].__dict__.setdefault("_efas_test_unregistered", []).append(1)
    """)
    (tmp_path / "plugins" / "pyhello" / "helper.py").write_text("HELLO = 'sibling import works'", encoding="utf-8")
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    manager.set_enabled("pyhello", True)
    assert manager.entry("pyhello").state == "loaded", manager.entry("pyhello").error
    assert ("info", "registered, helper says sibling import works") in logs(manager, "pyhello")
    item = host.menu_items[0]
    assert (item.label, item.shortcut, item.plugin_name) == ("Say hi", "Ctrl+Alt+H", "pyhello")
    item.trigger()
    assert host.notices == ["hi from pyhello"]
    host.modules[0].widgets[0].press()
    assert ("info", "pressed") in logs(manager, "pyhello")
    assert "efas_plugin_pyhello" in sys.modules and "helper" in sys.modules
    manager.set_enabled("pyhello", False)
    assert item.removed and host.modules[0].removed, "its menu items and modules go with it"
    assert "efas_plugin_pyhello" not in sys.modules and "helper" not in sys.modules
    import builtins

    assert builtins._efas_test_unregistered == [1]
    del builtins._efas_test_unregistered


def test_a_plugin_that_fails_to_load_is_reported_and_nothing_else_stops(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "badpy", "python", "raise RuntimeError('oops at load')")
    write_plugin(tmp_path / "plugins", "noreg", "python", "x = 1")
    write_plugin(tmp_path / "plugins", "badlua", "lua", "local x = 1\nerror('lua oops')")
    write_plugin(tmp_path / "plugins", "syntax", "lua", "local = ")
    write_plugin(tmp_path / "plugins", "exiter", "python", "import sys\nsys.exit(3)")
    write_plugin(tmp_path / "plugins", "fine", "lua", "efas.add_menu_item{label = 'ok', on_click = function() end}")
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    for pid in ("badpy", "noreg", "badlua", "syntax", "exiter", "fine"):
        manager.set_enabled(pid, True)
    states = {e.id: e.state for e in manager.entries()}
    assert states == {"badpy": "error", "noreg": "error", "badlua": "error", "syntax": "error", "exiter": "error", "fine": "loaded"}
    assert "oops at load" in manager.entry("badpy").error and "register(api)" in manager.entry("noreg").error and "lua oops" in manager.entry("badlua").error
    assert any("could not be loaded" in t and "oops at load" in t for _l, t in logs(manager, "EFAS", "error"))
    assert len(host.menu_items) == 1 and manager.logbook.error_count() >= 5
    manager.shutdown()


def test_a_callback_that_raises_is_logged_with_the_plugins_name_and_the_program_goes_on(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "flaky", "python", """
        def register(api):
            api.add_menu_item("Break", lambda: 1 / 0)
            api.add_menu_item("Misuse", lambda: api.set_edit({"nonsense": 1}))
    """)
    write_plugin(tmp_path / "plugins", "flakylua", "lua", """
        efas.add_menu_item{label = "Break", on_click = function() local t = nil; return t.x end}
        efas.add_menu_item{label = "Misuse", on_click = function() efas.set_edit{nonsense = 1} end}
        efas.add_menu_item{label = "Spin", on_click = function() while true do end end}
    """)
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    manager.set_enabled("flaky", True)
    manager.set_enabled("flakylua", True)
    for item in host.menu_items:
        item.trigger()  # none of these may raise
    errors = [t for _l, t in logs(manager, minimum="error")]
    assert any("menu item 'Break'" in t and "division by zero" in t for t in errors)
    assert any("menu item 'Misuse'" in t and "'nonsense' is not an edit value" in t for t in errors)
    assert any("menu item 'Break'" in t and "attempt to index a nil value" in t for t in errors)
    assert any("menu item 'Misuse'" in t and "not an edit value" in t for t in errors)
    assert any("menu item 'Spin'" in t and "ran for too long" in t for t in errors)
    assert {r.plugin for r in manager.logbook.records(minimum="error")} == {"flaky", "flakylua"}
    manager.shutdown()


# ------------------------------------------------------------------ the API, from both languages
LUA_API = """
efas.log("hello " .. efas.plugin_id)
efas.warn("careful")
efas.debug("detail")
print("api", efas.api_version, efas.version, efas.language, type(efas.data_dir))
efas.settings_set("count", (efas.settings_get("count", 0)) + 1)
efas.settings_set("list", {1, 2, 3})
efas.settings_set("table", {a = 1, b = {true, "x"}})
local photo = efas.photo()
print("photo", photo.name, photo.width, photo.inverted, photo.film_type)
local applied = efas.set_edit{exposure_ev = 0.5, inverted = false, film_type = "bw"}
table.sort(applied)
print("edit", table.concat(applied, ","))
print("pixel", efas.sample_pixel(5, 5).g, efas.sample_pixel(-1, 0) == nil, efas.image_size().width, efas.statistics().mean)
print("presets", table.concat(efas.presets(), "+"), efas.apply_preset("Warm"), efas.apply_preset("Nope"))
print("tags", table.concat(efas.photo_tags(), ","), efas.add_tags({"A/B"}), efas.view())
print("photos", #efas.photos(), efas.open_photo("x.tif"), efas.open_photo("x.png"))
print("confirm", efas.confirm("sure?"), efas.ask_text{prompt = "name?", default = "d"}, efas.pick_file{title = "t"} == nil)
efas.notify("done")
efas.message("text", "title")
"""


def test_the_lua_api(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "luaapi", "lua", LUA_API)
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    manager.set_enabled("luaapi", True)
    assert manager.entry("luaapi").state == "loaded", manager.entry("luaapi").error
    lines = dict((t.split("\t")[0], t) for _l, t in logs(manager, "luaapi") if "\t" in t)
    assert ("info", "hello luaapi") in logs(manager, "luaapi") and ("warn", "careful") in logs(manager, "luaapi") and ("debug", "detail") in logs(manager, "luaapi")
    assert lines["api"].split("\t")[1:4] == ["1", "0.6.1", "lua"]
    assert lines["photo"] == "photo\ta.tif\t400\ttrue\tc41"
    assert lines["edit"] == "edit\texposure_ev,film_type,inverted" and host.edits == [{"exposure_ev": 0.5, "inverted": False, "film_type": "bw"}]
    assert lines["pixel"] == "pixel\t20\ttrue\t400\t120.5"
    assert lines["presets"] == "presets\tWarm+Cool\ttrue\tfalse" and host.applied == ["Warm"]
    assert lines["tags"] == "tags\tFilm/Portra\ttrue\teditor" and host.tags == ["Film/Portra", "A/B"]
    assert lines["photos"] == "photos\t2\ttrue\tfalse" and host.opened == ["x.tif", "x.png"]
    assert lines["confirm"] == "confirm\ttrue\ttyped\ttrue"
    assert host.notices == ["done"] and host.messages == [("title", "text")]
    settings = json.loads((tmp_path / "plugin-data" / "luaapi" / "settings.json").read_text(encoding="utf-8"))
    assert settings == {"count": 1, "list": [1, 2, 3], "table": {"a": 1, "b": [True, "x"]}}
    manager.shutdown()
    manager.load_enabled()  # a new run reads the settings back
    manager.set_enabled("luaapi", True)
    assert json.loads((tmp_path / "plugin-data" / "luaapi" / "settings.json").read_text(encoding="utf-8"))["count"] == 2
    manager.shutdown()


PY_API = """
def register(api):
    api.info("py " + api.plugin_id + " " + api.language if hasattr(api, "language") else "py " + api.plugin_id)
    api.settings_set("n", api.settings_get("n", 0) + 5)
    photo = api.photo()
    api.log("photo %s %s %s" % (photo["name"], photo["width"], photo["film_type"]))
    api.log("edit %s" % api.set_edit({"contrast": 0.2, "flip_h": True}))
    api.log("size %s %s" % (api.image_size(), api.sample_pixel(1, 1)))
    api.log("img %s" % (api.image(256).shape,))
    api.log("tags %s %s" % (api.photo_tags(), api.presets()))
"""


def test_the_python_api(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "pyapi", "python", PY_API)
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    manager.set_enabled("pyapi", True)
    assert manager.entry("pyapi").state == "loaded", manager.entry("pyapi").error
    text = [t for _l, t in logs(manager, "pyapi")]
    assert "photo a.tif 400 c41" in text and "edit ['contrast', 'flip_h']" in text and "img (30, 40, 3)" in text
    assert "size {'width': 400, 'height': 300} {'r': 10, 'g': 20, 'b': 30}" in text and "tags ['Film/Portra'] ['Warm', 'Cool']" in text
    assert host.edits == [{"contrast": 0.2, "flip_h": True}]
    manager.shutdown()


@pytest.mark.parametrize("call, fragment", [
    ('set_edit({"exposure_ev": "high"})', "must be a number"), ('set_edit({"film_type": "xyz"})', "film_type must be one of"), ('set_edit({"inverted": 1})', "true or false"),
    ("set_edit({})", "needs a table"), ("set_edit(5)", "needs a table"), ('on("nothing", print)', "There is no event"), ('on("photo_opened", 5)', "must be a function"),
    ('add_module("")', "cannot be empty"), ('add_module("x", tab="nowhere")', "There is no tab"), ('add_menu_item("", print)', "cannot be empty"),
    ('add_menu_item("x", None)', "must be a function"), ('after("soon", print)', "must be a number"), ("add_tags([])", "needs a list"), ("add_tags('x')", "needs a list"),
    ('settings_set("k", object())', "can only hold"), ('settings_get("")', "cannot be empty"), ("image(5)", "from 16 to 8192"), ('read_text("C:/Windows/win.ini")', "may only read"),
    ('write_text("../escape.txt", "x")', "may only read"), ('write_text("/etc/passwd", "x")', "may only read"),
])
def test_api_mistakes_raise_a_sentence_the_author_can_act_on(qapp, tmp_path, call, fragment):
    from photoeditor.plugins.api import PluginError

    write_plugin(tmp_path / "plugins", "mistakes", "python", "def register(api): pass")
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    manager.set_enabled("mistakes", True)
    api = manager.entry("mistakes").core
    with pytest.raises(PluginError, match=fragment):
        eval("api." + call, {"api": api, "print": print, "object": object, "None": None})
    manager.shutdown()


def test_the_plugins_files_are_its_own_folder_and_what_the_user_picked(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "files", "python", "def register(api): pass")
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    manager.set_enabled("files", True)
    api = manager.entry("files").core
    api.write_text("notes/a.txt", "hello")
    assert api.read_text("notes/a.txt") == "hello" and (tmp_path / "plugin-data" / "files" / "notes" / "a.txt").read_text(encoding="utf-8") == "hello"
    api.write_text(os.path.join(api.data_dir, "b.txt"), "by absolute path")
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("user file", encoding="utf-8")
    from photoeditor.plugins.api import PluginError

    with pytest.raises(PluginError, match="may only read"):
        api.read_text(str(outside))
    host.dialog_answers["pick_file"] = str(outside)
    assert api.pick_file("x") == str(outside)
    assert api.read_text(str(outside)) == "user file", "a file the user picked in a dialog is allowed"
    target = tmp_path / "saved.txt"
    host.dialog_answers["save_path"] = str(target)
    assert api.save_path("x") == str(target)
    api.write_text(str(target), "saved")
    assert target.read_text(encoding="utf-8") == "saved"
    manager.shutdown()


def test_timers_run_and_stop_with_the_plugin(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "timers", "lua", """
        ticks = 0
        efas.after(20, function() print("once") end)
        local id
        id = efas.every(15, function() ticks = ticks + 1; if ticks == 3 then efas.cancel(id); print("stopped at 3") end end)
        efas.after(10, function() error("timer failed") end)
    """)
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    manager.set_enabled("timers", True)
    assert pump(qapp, lambda: any(t == "stopped at 3" for _l, t in logs(manager, "timers")))
    text = [t for _l, t in logs(manager, "timers")]
    assert text.count("once") == 1 and text.count("stopped at 3") == 1
    assert any("timer: " in t and "timer failed" in t for _l, t in logs(manager, "timers", "error"))
    write_plugin(tmp_path / "plugins", "tickpy", "python", "def register(api):\n    api.every(10, lambda: api.log('tick'))")
    manager.refresh()
    manager.set_enabled("tickpy", True)
    assert pump(qapp, lambda: len([1 for _l, t in logs(manager, "tickpy") if t == "tick"]) >= 2)
    manager.set_enabled("tickpy", False)
    count = len([1 for _l, t in logs(manager, "tickpy") if t == "tick"])
    pump(qapp, lambda: False, 0.15)
    assert len([1 for _l, t in logs(manager, "tickpy") if t == "tick"]) == count, "turning the plugin off stops its timers"
    manager.shutdown()


def test_events_reach_the_plugins_that_listen(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "listen", "lua", """
        efas.on("photo_opened", function(info) print("opened", info.name, info.size.w) end)
        local sub = efas.on("edit_changed", function(info) print("edit") end)
        efas.off(sub)
        efas.on("theme_changed", function(info) error("handler broke") end)
    """)
    write_plugin(tmp_path / "plugins", "listenpy", "python", """
        def register(api):
            api.on("photo_opened", lambda info: api.log("py opened %s" % info["name"]))
    """)
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    manager.set_enabled("listen", True)
    manager.set_enabled("listenpy", True)
    manager.emit("photo_opened", {"name": "a.tif", "size": {"w": 400, "h": 300}})
    manager.emit("edit_changed", {})
    manager.emit("theme_changed", {"theme": "modern"})
    manager.emit("not_an_event", {})
    assert ("info", "opened\ta.tif\t400") in logs(manager, "listen") and ("info", "py opened a.tif") in logs(manager, "listenpy")
    assert not any(t == "edit" for _l, t in logs(manager, "listen")), "after off() the handler is not called"
    assert any("on 'theme_changed'" in t and "handler broke" in t for _l, t in logs(manager, "listen", "error"))
    manager.shutdown()


def test_modules_and_controls_from_lua(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "ui", "lua", """
        local mod = efas.add_module{title = "Tone helper", tab = "exposure", expanded = false}
        mod:add_label{text = "Pick an amount"}
        local slider = mod:add_slider{label = "Amount", min = -1, max = 1, value = 0.25, step = 0.05, decimals = 2,
            on_change = function(v) print("slider", v) end}
        local combo = mod:add_combo{label = "Mode", options = {"soft", "hard"}, current = "hard", on_change = function(v) print("combo", v) end}
        local check = mod:add_checkbox{label = "Enabled", checked = true, on_change = function(v) print("check", v) end}
        local text = mod:add_text{label = "Name", text = "abc", on_change = function(v) print("text", v) end}
        local button = mod:add_button{label = "Go", on_click = function()
            slider:set_value(0.5); combo:set_options({"a", "b", "c"}, "b"); check:set_enabled(false); text:set_text("typed"); mod:set_title("Renamed")
            print("go", slider:get_value(), combo:get_value())
        end}
        mod:add_separator()
        local bar = mod:add_progress{label = "Work", value = 0.3}
        bar:set_value(0.9)
        mod:add_button("Positional", function() print("positional") end)
        _G.mod = mod
    """)
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    manager.set_enabled("ui", True)
    assert manager.entry("ui").state == "loaded", manager.entry("ui").error
    module = host.modules[0]
    assert (module.title, module.tab, module.expanded) == ("Tone helper", "exposure", False)
    kinds = [w.spec["type"] for w in module.widgets]
    assert kinds == ["label", "slider", "combo", "checkbox", "text", "button", "separator", "progress", "button"]
    slider, combo, check, text, button, _sep, bar, positional = module.widgets[1], module.widgets[2], module.widgets[3], module.widgets[4], module.widgets[5], module.widgets[6], module.widgets[7], module.widgets[8]
    assert (slider.spec["min"], slider.spec["max"], slider.spec["value"], slider.spec["step"]) == (-1.0, 1.0, 0.25, 0.05) and combo.spec["current"] == "hard" and bar.value == 0.9
    slider.user_sets(0.75)
    combo.user_sets("soft")
    check.user_sets(False)
    text.user_sets("hello")
    assert [t for _l, t in logs(manager, "ui")][-4:] == ["slider\t0.75", "combo\tsoft", "check\tfalse", "text\thello"]
    button.press()
    assert (slider.value, combo.options, combo.value, check.enabled, text.text, module.title) == (0.5, ["a", "b", "c"], "b", False, "typed", "Renamed")
    assert ("info", "go\t0.5\tb") in logs(manager, "ui")
    positional.press()
    assert ("info", "positional") in logs(manager, "ui")
    manager.set_enabled("ui", False)
    assert module.removed
    manager.shutdown()


def test_modules_and_controls_from_python_and_their_checks(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "pyui", "python", """
        def register(api):
            m = api.add_module("Py module")
            api.mod = m
            s = m.add_slider("Amount", min=0, max=10, value=3, on_change=lambda v: api.log("slid %s" % v))
            m.add_combo("Mode", ["x", "y"], on_change=lambda v: api.log("combo %s" % v))
            c = m.add_checkbox("On", True)
            api.slider, api.checkbox = s, c
    """)
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    manager.set_enabled("pyui", True)
    api = manager.entry("pyui").core
    module = host.modules[0]
    module.widgets[0].user_sets(4.5)
    module.widgets[1].user_sets("y")
    assert ("info", "slid 4.5") in logs(manager, "pyui") and ("info", "combo y") in logs(manager, "pyui")
    from photoeditor.plugins.api import PluginError

    for bad, fragment in ((lambda: api.mod.add_slider("x", min=5, max=1), "min must be less"), (lambda: api.mod.add_slider("x", decimals=9), "decimals"),
                          (lambda: api.mod.add_combo("x", []), "1 to 200"), (lambda: api.mod.add_button(""), "cannot be empty"),
                          (lambda: api.mod.add_checkbox("x", checked="yes"), "true or false"), (lambda: api.slider.set_options(["a"]), "Only a combo"),
                          (lambda: api.checkbox.set_value(3), "true or false"), (lambda: api.mod.add_slider("x", on_change=5), "must be a function"),
                          (lambda: api.mod.add_widget(object()), "PyQt6 widget")):
        with pytest.raises(PluginError, match=fragment):
            bad()
    api.mod.remove()
    with pytest.raises(PluginError, match="removed"):
        api.mod.add_label("late")
    manager.shutdown()


def test_the_lua_side_cannot_reach_more_than_the_allow_list(qapp, tmp_path):
    write_plugin(tmp_path / "plugins", "probe", "lua", """
        local ok, err = pcall(function() return efas.nonexistent() end)
        print("a", ok)
        local mod = efas.add_module{title = "t"}
        print("b", pcall(function() return mod:remove_everything() end))
        print("c", pcall(function() return mod._h.__class__ end))
        print("d", pcall(function() return efas.add_menu_item{label = "m", on_click = function() end}._inner end))
    """)
    manager, host, _store = make_manager(tmp_path)
    manager.load_enabled()
    manager.set_enabled("probe", True)
    assert manager.entry("probe").state == "loaded", manager.entry("probe").error
    out = {t.split("\t")[0]: t for _l, t in logs(manager, "probe") if "\t" in t}
    assert out["a"] == "a\tfalse" and out["b"].startswith("b\tfalse") and out["c"].startswith("c\tfalse") and out["d"].startswith("d\ttrue\tnil") or out["d"].startswith("d\tfalse")
    manager.shutdown()
