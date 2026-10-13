# UI and modules

A plugin shows itself in two ways: **menu items** in the Plugins menu, and **modules** in the editor's tool tabs. Modules are the collapsible panels EFAS itself uses (Exposure, Tone Curve, Export and so on); a plugin's module looks and behaves the same: click its header to open or close it, and it follows the current theme.

## Where modules go

`add_module` takes a `tab`:

| `tab` | Where |
|---|---|
| `"plugins"` | The **Plugins** tab. It has its own button in the tool strip, which only shows while at least one plugin has a module in it. This is the default. |
| `"exposure"` | The WB Correction tab |
| `"correction"` | The Correction tab |
| `"negative"` | The Negative tab |
| `"watermark"` | The Watermark tab |
| `"metadata"` | The Roll Card tab |

A module goes at the bottom of its tab, after EFAS's own modules. When the setting **Close a tab's modules when I switch to another tab** is on (Settings > General), a plugin's modules fold up with the rest.

## Making a module

**Lua**

```lua
local module = efas.add_module{ title = "My tool", tab = "plugins", expanded = false }
local note = module:add_label{ text = "Ready." }
module:add_button{ label = "Go", on_click = function() note:set_text("Done.") end }
```

**Python**

```python
def register(api):
    module = api.add_module("My tool", tab="plugins", expanded=False)
    note = module.add_label("Ready.")
    module.add_button("Go", on_click=lambda: note.set_text("Done."))
```

## The module's methods

| Method | What it does |
|---|---|
| `add_label(text)` | Some text (wraps, and can be selected with the mouse). |
| `add_button(label, on_click)` | A button. `on_click()` runs when it is pressed. |
| `add_checkbox(label, checked, on_change)` | A check box. `on_change(checked)` runs when it is ticked or unticked. |
| `add_slider(label, min, max, value, step, decimals, on_change)` | A slider with a number box beside it. `on_change(value)` runs as it moves. Defaults: `min` 0, `max` 1, `value` = `min`, `step` 0.01, `decimals` 2. Double-click the slider to go back to the first `value`. |
| `add_combo(label, options, current, on_change)` | A drop-down. `options` is a list of text (1 to 200). `on_change(option)` runs when another is chosen. |
| `add_text(label, text, on_change)` | A one-line text box. `on_change(text)` runs when the user presses Enter or clicks elsewhere. |
| `add_separator()` | A thin line. |
| `add_progress(label, value)` | A progress bar, `value` 0 to 1, with an optional caption. |
| `set_title(title)` | Rename the module. |
| `clear()` | Remove every control (to build the module again). |
| `expand()`, `collapse()` | Open or close the module. |
| `remove()` | Take the module out of the tab. |
| `add_widget(widget)` | **Python only.** Put your own PyQt6 widget in the module. |

In **Lua** the methods that take several named values take one table: `module:add_slider{ label = "Amount", min = 0, max = 1, on_change = f }`. `add_label`, `add_button`, `add_checkbox`, `add_slider`, `add_combo`, `add_text`, `add_progress` and `set_title` do; `add_separator`, `clear`, `expand`, `collapse` and `remove` take nothing.

All of them are checked: a missing label, `min` not less than `max`, an option list that is empty or not a list, a callback that is not a function, all raise an error that says what is wrong.

## Controls

Each `add_...` returns the control. Its methods:

| Method | Works on | What it does |
|---|---|---|
| `get_value()` | label, checkbox, slider, combo, text, progress | The current value: text, true/false, a number, or the chosen option. |
| `set_value(value)` | the same | Change the value **without** calling `on_change`. |
| `set_text(text)` | label, button, checkbox, text, combo, progress | A label's text, a button's or check box's caption, a text box's content, or the caption of a combo / progress bar. |
| `set_enabled(enabled)` | all | Grey a control out (false) or restore it (true). |
| `set_visible(visible)` | all | Hide or show it. |
| `set_options(options, current)` | combo | Replace the list (and say which is chosen). |
| `set_range(min, max)` | slider | Change the lowest and highest value. The current value is kept if it still fits. |

Using a method on the wrong kind of control is an error where it would otherwise be silently lost: `set_options` on anything but a combo, `set_range` on anything but a slider, `set_value` on a button or separator. A value is checked too: a slider's `set_value` needs a number, a check box's needs true/false.

## Callbacks

- Callbacks run on EFAS's main thread. EFAS is unresponsive while one runs, so keep them short; start a timer for something slow.
- If a callback raises an error, EFAS writes it to the Plugin Output window (with the plugin's name and which control it was) and carries on. The control keeps working.
- A **slider's** `on_change` runs for every step of a drag. If each call is expensive (for example a `set_edit`), remember the value and apply it with `after(150, ...)` instead, or use a button.
- Changing a control from your own code with `set_value` does not call `on_change`, so a plugin cannot loop on itself.

## Menu items

```lua
efas.add_menu_item{ label = "Reset exposure", on_click = function() efas.set_edit{ exposure_ev = 0 } end, shortcut = "Ctrl+Alt+0" }
efas.add_menu_item{ label = "Report", submenu = "Reports", on_click = function() efas.message("Report") end }
```

Items appear under **Plugins > (plugin name)**. With `submenu`, they sit in a submenu of that. A shortcut is a text like `Ctrl+Shift+K`.

## A tidy rebuild

To change what a module shows (for example a list that depends on the photo), keep the module and `clear()` it, then add controls again:

```lua
local module = efas.add_module{ title = "Presets" }

local function rebuild()
    module:clear()
    for _, name in ipairs(efas.presets()) do
        module:add_button{ label = name, on_click = function() efas.apply_preset(name) end }
    end
end

rebuild()
efas.on("photo_opened", rebuild)
```

## Your own Qt widgets (Python)

A Python plugin can put any PyQt6 widget in a module:

```python
from PyQt6.QtWidgets import QTextEdit


def register(api):
    module = api.add_module("Notes")
    box = QTextEdit()
    box.setPlainText(api.settings_get("notes", ""))
    box.textChanged.connect(lambda: api.settings_set("notes", box.toPlainText()))
    module.add_widget(box)
```

The widget belongs to EFAS's window: it follows the theme's colours, and it is deleted when the module is removed. Do not keep using it after `module.remove()` or when the plugin is switched off.
