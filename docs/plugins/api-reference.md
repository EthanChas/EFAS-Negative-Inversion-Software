# API reference (version 1)

Everything a plugin can do is a function of one object: **`efas`** in Lua, the **`api`** argument of `register(api)` in Python. The names and behaviour are the same in both languages. Differences are marked **Lua** or **Python**.

Conventions:

- **Lua** calls functions with a dot: `efas.notify("hi")`. Functions marked *(table)* take a **single table of named values**: `efas.add_menu_item{ label = "Go", on_click = f }`. Modules and controls are objects: call their methods with a colon, `module:add_label{ text = "hi" }`.
- **Python** calls functions normally, with positional or keyword arguments: `api.add_menu_item("Go", f)`.
- A mistake in how you call a function (a wrong type, an unknown name, a missing photo) raises an error whose message says what to change. EFAS catches it, writes it to **View > Plugin Output** with your plugin's name, and carries on. See [Plugin Output and debugging](plugin-output.md).
- Everything runs on EFAS's main thread, one thing at a time. Keep callbacks short. Only `log` may be called from a thread of your own (Python).
- Lua tables that are lists (`{1, 2, 3}`) arrive in Python as lists; other tables arrive as dictionaries. Python lists and dictionaries become Lua tables.

## About the plugin

| Lua | Python | Value |
|---|---|---|
| `efas.api_version` | `api.api_version` | The plugin API version of this EFAS (1) |
| `efas.version` | `api.app_version` | The EFAS version, like `0.7.0` |
| `efas.plugin_id` | `api.plugin_id` | The `id` from `plugin.json` |
| `efas.plugin_name` | `api.plugin_name` | The `name` from `plugin.json` |
| `efas.plugin_dir` | `api.plugin_dir` | The plugin's folder |
| `efas.data_dir` | `api.data_dir` | The plugin's own data folder (made when first written to) |
| `efas.language` | `api.language` | `"lua"` or `"python"` |

## Output

| Function | What it does |
|---|---|
| `log(message, level)` | Write a line to the Plugin Output window. `level` is `"debug"`, `"info"` (default), `"warn"` or `"error"`. |
| `debug(message)`, `info(message)`, `warn(message)`, `error(message)` | The same, with the level in the name. |
| `notify(text)` | Show a short line in the status area at the bottom of the editor. |

**Lua:** `print(...)` writes an `info` line, with its arguments joined by tabs. **Python:** `print` goes to the console of the person who started EFAS from a terminal, not to the Plugin Output window; use `api.info`.

## Settings and files

A plugin remembers things between runs in its own folder, `plugin-data\<id>`. Nothing else on the computer can be read or written (see [Security](security.md)).

| Function | What it does |
|---|---|
| `settings_get(key, default)` | The value saved under `key`, or `default` (nil/`None` if you give none). |
| `settings_set(key, value)` | Save a value: a number, text, true/false, or a list/table of those. Setting nil/`None` removes the key. Saved to `settings.json` at once. |
| `settings_all()` | A table/dictionary of everything saved. |
| `read_text(path)` | The text of a file (UTF-8, at most 8 MB). A relative path starts in the plugin's data folder. |
| `write_text(path, text)` | Write a text file. A relative path starts in the data folder; folders are made as needed. |
| `pick_file(...)`, `save_path(...)` | See [Dialogs](#dialogs): the files you pick there may be read or written too. |

`read_text` and `write_text` only accept paths **inside the plugin's data folder** or a path the user **just chose** in a `pick_file` or `save_path` dialog. Anything else raises an error.

## Timers

| Function | What it does |
|---|---|
| `after(milliseconds, callback)` | Run `callback()` once. At least 10 ms. Returns an id. |
| `every(milliseconds, callback)` | Run `callback()` again and again until cancelled or the plugin is switched off. At least 10 ms. Returns an id. |
| `cancel(id)` | Stop a timer. |

A plugin may have 50 timers at most. When the plugin is switched off all its timers stop.

## Events

| Function | What it does |
|---|---|
| `on(event, callback)` | Run `callback(info)` when the event happens. Returns an id. See [Events](events.md) for the list and what `info` holds. |
| `off(id)` | Stop listening. |

## Menu items

### `add_menu_item(label, on_click, shortcut, submenu)` *(table in Lua)*

Adds an item to **Plugins > (your plugin's name)**. `on_click()` runs when it is chosen.

- `label`: the text of the item.
- `on_click`: a function with no arguments.
- `shortcut` (optional): a key sequence such as `"Ctrl+Shift+K"`. A bad one raises an error. EFAS does not check for clashes with its own shortcuts.
- `submenu` (optional): puts the item under a submenu of your plugin's menu.

Returns an object with `remove()` in Python. (In Lua the item is removed when the plugin is switched off.) All of a plugin's menu items are removed when it is switched off or reloaded.

## Modules

### `add_module(title, tab, expanded)` *(table in Lua)*

Adds a module (a collapsible panel like EFAS's own) to a tool tab and returns it.

- `title`: the module's heading.
- `tab` (optional): where it goes. `"plugins"` (the default, a tab of its own that appears while some plugin has a module in it), `"negative"` (Convert), `"correction"` (Frame & Clean), `"exposure"` (Tone), `"color"` (Color), `"detail"` (Detail), `"watermark"` (Finish) or `"metadata"` (Roll Card).
- `expanded` (optional): open at first. The default is closed, like EFAS's own modules, so a tab is tidy when it opens.

The module's methods, its controls and what they return are in [UI and modules](ui-and-modules.md). All of a plugin's modules are removed when it is switched off.

## Dialogs

| Function | What it does |
|---|---|
| `message(text, title)` *(table in Lua)* | A message box. |
| `confirm(text, title)` *(table in Lua)* | A Yes/No question; returns true for Yes. |
| `ask_text(prompt, default, title)` *(table in Lua)* | Asks for a line of text; returns it, or nil/`None` if cancelled. |
| `pick_file(title, filter, start)` *(table in Lua)* | An Open dialog; returns the path, or nil/`None`. `filter` is like `"Text (*.txt);;All files (*)"`. The chosen file may then be read with `read_text`. |
| `pick_folder(title, start)` *(table in Lua)* | A folder dialog; returns the folder, or nil/`None`. |
| `save_path(title, name, filter)` *(table in Lua)* | A Save dialog; returns the path, or nil/`None`. The chosen file may then be written with `write_text`. |

Where a function has a `title` and you leave it out, your plugin's name is used.

Dialogs stop everything until closed, as in any program. Do not open them from a timer that fires often.

## The photo and its edit

All of these work on the **photo open in the editor**. Without one, the functions that need it say so, or return nil/`None`.

### `photo()`

A table of the open photo, or nil/`None`:

| Key | Meaning |
|---|---|
| `path`, `name`, `folder` | Where the file is |
| `width`, `height` | Size in pixels of the picture on screen (after crop and rotation) |
| `inverted` | true when the negative is being inverted to a positive |
| `film_type` | `"auto"`, `"c41"` (colour negative), `"bw"` (black and white negative) or `"e6"` (slide) |
| `hq` | true when working at full resolution |
| `rotation` | 0, 90, 180 or 270 |
| `flip_h`, `flip_v` | mirrored |
| `crop` | A list of four numbers, `left, top, right, bottom`, in pixels of the uncropped picture EFAS is working on; nil/`None` when the photo is not cropped |
| `exposure_ev`, `contrast`, `saturation`, `temperature`, `tint`, `shadows`, `highlights`, `local_contrast`, `chroma_denoise`, `fine_rotation` | The edit values, as shown by the sliders |

### `photos()`

The paths of the photos in the open photo's folder, in the filmstrip's order.

### `open_photo(path)`

Opens a photo in the editor (switching to the editor if the Workbench was showing). Returns true, or false if the file is missing or not an image EFAS can open. The photo loads in the background; read it with `photo()` after the `photo_opened` event, not straight after this call.

### `set_edit(values)` *(a table/dictionary of named values)*

Changes the open photo's edit **exactly as the sliders do**, so each call makes history steps you can undo, and the tool panels follow. `values` may hold any of:

| Key | Type |
|---|---|
| `exposure_ev`, `contrast`, `saturation`, `temperature`, `tint`, `shadows`, `highlights`, `local_contrast`, `chroma_denoise`, `fine_rotation` | numbers (the same ranges as the sliders; out-of-range values are limited the way the sliders limit them) |
| `inverted`, `flip_h`, `flip_v` | true / false |
| `film_type` | `"auto"`, `"c41"`, `"bw"` or `"e6"` |

Returns the list of names that were applied. An unknown name raises an error naming the ones that exist. With no photo open it raises an error.

**Lua:** `efas.set_edit{ exposure_ev = 0.3, contrast = 10 }`. **Python:** `api.set_edit({"exposure_ev": 0.3})`.

Edits a plugin makes with `set_edit` do **not** send the `edit_changed` event, so a plugin that reacts to `edit_changed` cannot trigger itself.

### Presets and tags

| Function | What it does |
|---|---|
| `presets()` | The names of the saved looks (presets). |
| `apply_preset(name)` | Applies a saved look to the open photo. Returns false when there is no photo or no such look. |
| `photo_tags()` | The open photo's tags (text like `"Film/Portra"`). |
| `add_tags(tags)` | Adds tags (a list of text; `/` nests them) to the open photo. Returns true, or false with no photo. |
| `view()` | `"editor"` or `"workbench"`: which view is showing. |

## Measuring the picture

These look at **the picture on screen**: the result of the edit, cropped and rotated, at the resolution EFAS is working at.

| Function | Result |
|---|---|
| `image_size()` | `{width, height}`, or nil/`None`. |
| `sample_pixel(x, y)` | `{r, g, b}` (0-255) of the pixel at x, y (counting from the top left, from 0), or nil/`None` outside the picture. |
| `statistics()` | A table of figures about the picture, or nil/`None` with no photo (below). |
| `image(max_dim)` **Python only** | The picture as a numpy array of shape (height, width, 3) and type `uint8`, scaled down so its long side is at most `max_dim` (16 to 8192, default 1024); `None` with no photo. A copy: changing it changes nothing. |

`statistics()` returns:

| Key | Meaning |
|---|---|
| `mean`, `median` | Brightness, 0 (black) to 255 (white) |
| `p1`, `p99` | The brightness below which 1% / 99% of the pixels lie |
| `shadows_pct`, `midtones_pct`, `highlights_pct` | Percent of pixels darker than 64, between, and 192 or brighter |
| `blocked_pct`, `blown_pct` | Percent of pixels at brightness 3 or less / 252 or more |
| `saturation` | Average colour saturation, 0 to 1 |
| `r`, `g`, `b` | Average of each colour channel |

On big pictures the figures are worked out on a sample of about 400,000 pixels.

## Python only

- `module.add_widget(widget)` puts any PyQt6 widget in a module. See [Python plugins](python.md).
- `api.image(max_dim)`, above.
- Optional `unregister()` function in `main.py`, called when the plugin is switched off.
