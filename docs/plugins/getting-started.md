# Getting started

This page takes you from nothing to a plugin that adds a module with a slider to the editor, first in Lua and then in Python.

## 1. Make the plugin folder

In EFAS open **Settings > Plugins** and press **New plugin...**. Give it a name and pick Python or Lua. EFAS makes a folder in the plugins folder with a `plugin.json` and a short program, and opens it for you.

Or do it by hand: make a folder (any name that does not start with `.` or `_`) in the plugins folder, with these two files in it.

`plugin.json`

```json
{
  "id": "user.slider-demo",
  "name": "Slider Demo",
  "version": "0.1",
  "author": "You",
  "description": "A module with a slider that changes the exposure.",
  "entry": "main.lua",
  "api": 1
}
```

## 2. Write the program

### In Lua (`main.lua`)

```lua
print("Slider Demo is on")                                   -- shows in View > Plugin Output

local module = efas.add_module{ title = "Slider demo" }      -- a module in the Plugins tab
local reading = module:add_label{ text = "Move the slider." }

module:add_slider{
    label = "Exposure",
    min = -2, max = 2, value = 0, step = 0.1, decimals = 1,
    on_change = function(value)
        if efas.photo() then
            efas.set_edit{ exposure_ev = value }             -- changes the open photo, like the real slider
            reading:set_text(string.format("Exposure set to %+.1f EV", value))
        else
            reading:set_text("Open a photo first.")
        end
    end,
}
```

### In Python (`main.py`, with `"entry": "main.py"` in `plugin.json`)

```python
def register(api):
    api.info("Slider Demo is on")  # shows in View > Plugin Output

    module = api.add_module("Slider demo")  # a module in the Plugins tab
    reading = module.add_label("Move the slider.")

    def moved(value):
        if api.photo():
            api.set_edit({"exposure_ev": value})  # changes the open photo, like the real slider
            reading.set_text(f"Exposure set to {value:+.1f} EV")
        else:
            reading.set_text("Open a photo first.")

    module.add_slider("Exposure", min=-2, max=2, value=0, step=0.1, decimals=1, on_change=moved)
```

## 3. Switch it on

Open **Settings > Plugins**. If the window was already open, press **Look for plugins again**. Tick **Slider Demo** and press **Save**. A new **Plugins** tab appears in the tool strip on the right of the editor; the module is inside it (click its header to open it; modules start closed, like EFAS's own, unless the plugin asks for `expanded`).

Open a photo and move the slider. Every move is a history step, so Undo works.

## 4. See what happened

Open **View > Plugin Output**. You will see `Slider Demo is on` and any error the plugin raised, with the plugin's name in front. See [Plugin Output and debugging](plugin-output.md).

## 5. Change it and try again

Edit the file, then use **Plugins > Reload Plugins** (or untick and tick the plugin in Settings). EFAS unloads the plugin, removes its menu items and modules, and loads it again from disk.

## What next

- [UI and modules](ui-and-modules.md): every control a module can have, and where modules can go.
- [API reference](api-reference.md): everything `efas` / `api` can do.
- [Events](events.md): run code when a photo opens or the edit changes.
- [Examples](examples.md): five complete plugins to read and copy.
