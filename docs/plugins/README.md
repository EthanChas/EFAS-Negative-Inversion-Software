# Plugins and add-ons

EFAS can be extended with plugins written in **Python** or **Lua**. A plugin can

- add **menu items** to the Plugins menu,
- add **modules** (the collapsible panels) with buttons, sliders, check boxes, drop-downs, text boxes and progress bars to a tool tab, or to the Plugins tab,
- read the open photo (its name, size, edit values, tags, the picture itself) and **change its edit**, as the sliders do,
- measure the picture (histogram figures, single pixels),
- apply saved looks (presets) and add tags,
- react to **events** (a photo opened, the edit changed, the theme changed, the view changed, the program starting or closing),
- keep its own settings and files, run timers, and show dialogs,
- write to the **Plugin Output** window (View > Plugin Output).

Plugins are optional. Every plugin starts **switched off**; you turn each one on in **Settings > Plugins**.

## Where to start

| I want to... | Read |
|---|---|
| write my first plugin in ten minutes | [Getting started](getting-started.md) |
| describe my plugin (`plugin.json`) | [The manifest](manifest.md) |
| look up a function | [API reference](api-reference.md) |
| add a module, buttons and sliders to the UI | [UI and modules](ui-and-modules.md) |
| react to what the user does | [Events](events.md) |
| write in Lua | [Lua plugins](lua.md) |
| write in Python | [Python plugins](python.md) |
| see what my plugin prints, and find its errors | [Plugin Output and debugging](plugin-output.md) |
| know what a plugin can and cannot do | [Security](security.md) |
| copy something that works | [Examples](examples.md) |
| change the plugin system itself | [How it is built](internals.md) |

## The short version

A plugin is a folder in EFAS's plugins folder (**Settings > Plugins > Open plugins folder**, usually `C:\Users\<you>\.EFAS\plugins`). It holds a `plugin.json` that names it and a program: `main.lua` or `main.py`.

```
plugins/
  my-plugin/
    plugin.json
    main.lua
```

`plugin.json`:

```json
{ "id": "user.my-plugin", "name": "My Plugin", "version": "1.0", "entry": "main.lua", "api": 1 }
```

`main.lua`:

```lua
efas.add_menu_item{ label = "Say hello", on_click = function() efas.message("Hello!") end }
```

Open **Settings > Plugins**, tick **My Plugin**, press **Save**, and **Plugins > My Plugin > Say hello** is there. The same plugin in Python:

```python
def register(api):
    api.add_menu_item("Say hello", lambda: api.message("Hello!"))
```

Press **Settings > Plugins > Install examples** to copy five working example plugins into the plugins folder, and **New plugin...** to make an empty one to start from.

## Lua or Python?

| | Lua | Python |
|---|---|---|
| Needs | nothing (Lua is built into EFAS) | nothing in the downloaded program; the modules a plugin may `import` are those the program ships with (see [Python plugins](python.md)) |
| Safety | runs in a **sandbox**: no files, no programs, no internet, time-limited | runs with the **same access as EFAS itself** |
| Own interface widgets | the controls the API offers | those, and any PyQt6 widget |
| The picture as an array | no (use `statistics` and `sample_pixel`) | yes (`api.image()` gives a numpy array) |
| Good for | small tools, buttons, batch-style actions, sharing with people you do not know | analysis, custom windows, anything that needs libraries |

Both languages use the **same API** with the same names and the same behaviour. Anything in the [API reference](api-reference.md) works in both unless it says otherwise.

## Versions

The plugin API has a version number (`api` in `plugin.json`). This EFAS has **API version 1**. A plugin that asks for a higher number is shown as unusable, with the message "update EFAS to use it". Changes that could break a plugin raise the number; adding new functions does not.
