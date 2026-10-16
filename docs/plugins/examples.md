# Examples

**Settings > Plugins > Install examples** copies these five plugins into your plugins folder (they start switched off). The source is also in the repository under `src/photoeditor/assets/plugin-examples/`. Read them, change them, and use **New plugin...** to start your own.

| Plugin | Language | Shows |
|---|---|---|
| Hello (Lua) | Lua | A menu item, a module with a button, saved settings, `print` |
| Hello (Python) | Python | `register(api)`, a menu item with a shortcut, a slider and a check box |
| Exposure Steps (Lua) | Lua | A module in the Tone tab, `set_edit`, events |
| Photo Report (Python) | Python | `photo()`, `statistics()`, a submenu, a Save dialog and `write_text` |
| Tag by Exposure (Lua) | Lua | `statistics()` and `add_tags()` |

## Hello (Lua)

`plugin.json`

```json
{
  "id": "efas.example.hello-lua",
  "name": "Hello (Lua)",
  "version": "1.0",
  "author": "EFAS",
  "description": "The smallest useful Lua plugin.",
  "entry": "main.lua",
  "api": 1
}
```

`main.lua`

```lua
print("Hello from " .. efas.plugin_name .. " (EFAS " .. efas.version .. ")")

efas.add_menu_item{
    label = "Say hello",
    on_click = function()
        efas.message("Hello from Lua!")
    end,
}

local module = efas.add_module{ title = "Hello (Lua)" }
local label = module:add_label{ text = "Press the button." }

local clicks = efas.settings_get("clicks", 0)
if clicks > 0 then label:set_text("You have pressed it " .. clicks .. " times before.") end

module:add_button{
    label = "Click me",
    on_click = function()
        clicks = clicks + 1
        efas.settings_set("clicks", clicks)
        label:set_text("Pressed " .. clicks .. " times.")
        efas.notify("Hello button pressed")
    end,
}
```

## Exposure Steps (Lua)

A module in the **Tone** tab with three buttons. It reads the photo's exposure and sets it with `set_edit`, then keeps its reading right by listening for events.

```lua
local STEP = 1 / 3

local module = efas.add_module{ title = "Exposure steps", tab = "exposure" }
local reading = module:add_label{ text = "Open a photo." }

local function show()
    local photo = efas.photo()
    if photo then
        reading:set_text(string.format("Exposure: %+.2f EV", photo.exposure_ev))
    else
        reading:set_text("Open a photo.")
    end
end

local function nudge(amount)
    local photo = efas.photo()
    if not photo then
        efas.notify("Open a photo first")
        return
    end
    efas.set_edit{ exposure_ev = photo.exposure_ev + amount }
    show()
end

module:add_button{ label = "Darker (-1/3 EV)", on_click = function() nudge(-STEP) end }
module:add_button{ label = "Brighter (+1/3 EV)", on_click = function() nudge(STEP) end }
module:add_button{ label = "Back to 0", on_click = function() efas.set_edit{ exposure_ev = 0 } show() end }

efas.on("photo_opened", show)
efas.on("edit_changed", show)
show()
```

## Photo Report (Python)

```python
def build_report(api):
    photo = api.photo()
    if photo is None:
        return None
    lines = [
        f"{photo['name']}  ({photo['width']} x {photo['height']} px)",
        f"Film type: {photo['film_type']}, inverted: {photo['inverted']}",
        f"Exposure {photo['exposure_ev']:+.2f} EV, contrast {photo['contrast']:+.2f}",
    ]
    stats = api.statistics()
    if stats:
        lines += [
            "",
            f"Brightness: mean {stats['mean']:.0f}, median {stats['median']:.0f} (0 black, 255 white)",
            f"Tones: {stats['shadows_pct']:.1f}% shadows, {stats['midtones_pct']:.1f}% midtones, {stats['highlights_pct']:.1f}% highlights",
            f"Clipping: {stats['blocked_pct']:.1f}% blocked, {stats['blown_pct']:.1f}% blown",
        ]
    return "\n".join(lines)


def register(api):
    def save():
        report = build_report(api)
        if report is None:
            api.notify("Open a photo first")
            return
        path = api.save_path("Save report", "photo-report.txt", "Text (*.txt)")
        if path:
            api.write_text(path, report)
            api.notify(f"Saved {path}")

    api.add_menu_item("Save a report...", save, submenu="Photo Report")
```

## Tag by Exposure (Lua)

```lua
local function tag_this_photo()
    local stats = efas.statistics()
    if not stats then
        efas.notify("Open a photo first")
        return
    end
    local tags = {}
    if stats.mean < 80 then
        tags[#tags + 1] = "Exposure/Dark"
    elseif stats.mean > 170 then
        tags[#tags + 1] = "Exposure/Bright"
    else
        tags[#tags + 1] = "Exposure/Normal"
    end
    if stats.blown_pct > 1 then tags[#tags + 1] = "Exposure/Blown highlights" end
    efas.add_tags(tags)
    efas.notify("Tagged: " .. table.concat(tags, ", "))
end

efas.add_menu_item{ label = "Tag this photo", submenu = "Tag by Exposure", on_click = tag_this_photo }
```

## More ideas

- **Apply a preset to every photo you open**: listen for `photo_opened`, call `apply_preset("My look")` (but only if the photo has not been edited: check `photo().exposure_ev == 0`).
- **A warning light**: a label that turns the text red-worded when `statistics().blown_pct` is over 2%, updated on `edit_changed`.
- **A step-through viewer**: buttons using `photos()` and `open_photo()` to go to the next and previous photo.
- **A notes box** (Python): a `QTextEdit` in a module, saved with `settings_set` per photo path.
