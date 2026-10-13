# Events

An event tells a plugin that something happened. Listen with `on(event, callback)`; the callback receives one table/dictionary of details.

**Lua**

```lua
efas.on("photo_opened", function(info)
    print("Opened " .. info.name .. " from " .. info.folder)
end)
```

**Python**

```python
def register(api):
    api.on("photo_opened", lambda info: api.info(f"Opened {info['name']} from {info['folder']}"))
```

`on` returns an id; `off(id)` stops listening. When a plugin is switched off all its listeners are removed.

## The events

| Event | When | `info` holds |
|---|---|---|
| `app_started` | Just after EFAS has started, to the plugins that loaded with it. A plugin switched on later (in Settings) never gets it: do set-up in the main program, not in this event. | nothing |
| `app_closing` | EFAS is closing. Last chance to save something. | nothing |
| `photo_opened` | A photo has been opened in the editor. | `path`, `name`, `folder` |
| `edit_changed` | The edit moved (a slider, Undo, a preset, a crop...). Sent once the changes have settled (about a tenth of a second after the last one), and also shortly after a photo opens. **Not** sent for changes a plugin makes itself with `set_edit`. | `path` |
| `theme_changed` | A different theme was chosen and applied in Settings. | `theme`: the theme's id, like `"modern"` |
| `view_changed` | The user switched between the editor and the Workbench. | `view`: `"editor"` or `"workbench"` |

An unknown event name raises an error that lists the ones that exist.

## Good habits

- **Read, don't assume.** `edit_changed` says that *something* changed, not what. Call `photo()` to see the values.
- **Keep it quick.** `edit_changed` can come often while someone drags a slider (at most about ten times a second). A heavy calculation here makes the editor feel slow; do heavy work from a button or a timer.
- **Don't call `open_photo` from `photo_opened`** unless you check that it is a different photo. Opening a photo sends `photo_opened` again.
- A listener that raises an error is reported in the Plugin Output window and stays registered; the next event calls it again.

## A reading that follows the photo

```lua
local module = efas.add_module{ title = "Exposure reading" }
local reading = module:add_label{ text = "-" }

local function show()
    local photo = efas.photo()
    reading:set_text(photo and string.format("%s: %+.2f EV", photo.name, photo.exposure_ev) or "No photo open")
end

efas.on("photo_opened", show)
efas.on("edit_changed", show)
show()
```
