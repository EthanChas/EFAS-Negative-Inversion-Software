# How the plugin system is built (for EFAS developers)

You do not need this page to write a plugin. It is for people changing EFAS itself.

```
src/photoeditor/plugins/          no Qt widgets here; everything below is testable without a window
  manifest.py      plugin.json: Manifest, parse/load, discover() the folders
  logbook.py       the Plugin Output lines (thread-safe), Record, Logbook
  api.py           PluginCore: the whole API in plain Python types; the HOST protocol; allow-lists
  lua_sandbox.py   one Lua 5.4 runtime (lupa) per plugin, with the dangerous parts removed and a CPU limit
  lua_bridge.py    builds the `efas` table in Lua over a PluginCore
  manager.py       PluginManager: finds, loads, unloads plugins; safe_call; events; timers; enabled list
  measure.py       statistics / sample / scaled copy of the picture
  templates.py     install the bundled examples; make an empty plugin
src/photoeditor/desktop/view/
  plugin_host.py        WindowPluginHost: the HOST protocol for the real window (menus, modules, photo, edit)
  plugin_widgets.py     the controls a module can show, built from spec dictionaries
  plugin_log_window.py  View > Plugin Output
  settings_dialog.py    Settings > Plugins page
src/photoeditor/assets/plugin-examples/   the five examples
```

## One implementation, two languages

`PluginCore` is the API. A Python plugin gets the object itself. A Lua plugin gets a table built by `lua_bridge.py`, whose functions call `PluginCore` methods by **name**, but only names on the lists in `api.py` (`FUNCTIONS`, `MODULE_METHODS`, `WIDGET_METHODS`). Lua values are converted to plain Python values on the way in (`LuaSandbox.to_python`) and back on the way out (`to_lua`); a single table argument to a function on `KEYWORD_FUNCTIONS` / `KEYWORD_METHODS` is spread into keyword arguments.

So the two languages cannot drift apart: add a method to `PluginCore`, add its name to the right list, document it, and both languages have it.

## The host

`PluginCore` never touches Qt or the controller. It checks its arguments and calls a **host**; the HOST docstring in `api.py` lists every call. `WindowPluginHost` is the real one; `tests/plugin_fakes.py` has a recording fake, so the API, both languages and the example plugins are tested without a window (`tests/test_plugins_core.py`, `tests/test_plugins_docs.py`). `tests/test_plugins_window.py` runs a real `AppWindow` (offscreen) for the menu, the Plugins tab, View > Plugin Output, Settings > Plugins and `set_edit`.

## Adding an API function

1. Write it on `PluginCore` (validate with `_need` / `_text` / `_number`; raise `PluginError` with a sentence an author can act on).
2. If it needs the program, add a call to the host: the HOST docstring, `WindowPluginHost`, and `FakeHost` in `tests/plugin_fakes.py`.
3. Add its name to `FUNCTIONS` (and `KEYWORD_FUNCTIONS` if it takes named values) in `api.py`.
4. Document it in `api-reference.md` (or `ui-and-modules.md` for modules and controls). `test_every_function_in_the_api_is_documented` fails until you do.
5. If it can break an existing plugin, raise `API_VERSION` in `api.py` and `manifest.py` and say so in the docs.

## Safety rules the code keeps

- **Everything a plugin calls is on the main thread**, except `log`. Callbacks are wrapped by `PluginCore._wrap_callback` into `PluginManager.safe_call`, which catches `Exception` and `SystemExit`, logs the error with the plugin's name and carries on.
- **Lua**: `io`, `package`, `dofile`, `loadfile`, `debug`, `collectgarbage`, `python`, `string.dump` and most of `os` are removed; `load` takes text only; `require` reads only inside the plugin's folder; Python attribute access from Lua is refused for names starting with `_`; a debug hook stops a call after 3 CPU seconds (coroutines get the hook too).
- **Files**: `read_text` / `write_text` check every path against the plugin's data folder and the files the user chose in a dialog this session.
- **Nothing starts on its own**: every plugin is off until the user ticks it (`plugins_enabled` in the settings file), and a plugin that fails to load is unloaded completely (menu items, modules, timers, listeners).
- **Edits go through the controller's setters** (the sliders' own), so they are history steps; after them `AppWindow._on_reverted()` makes the tool panels follow, and `plugin_edit_made()` keeps the plugin's own edit from coming back as `edit_changed`.

## Packaging

`lupa` is a dependency in `pyproject.toml`; `tools/build_app.py` adds `--hidden-import lupa.lua54 --collect-all lupa` so the .exe carries the interpreter. The example plugins are inside `assets/`, which is already bundled.
