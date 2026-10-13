"""The plugin API: what a plugin gets as `efas` (Lua) or as the `api` argument of register(api) (Python). One implementation, PluginCore, in plain Python types; the
Lua flavour (lua_bridge.py) is a thin skin over the same methods, so the two languages can never drift apart.

A plugin only ever touches the program through a *host* (see HOST below): the real one (desktop/view/plugin_host.py) drives the window and the editor, a test one
records. Every method that a plugin calls checks its arguments and raises PluginError with a sentence the author can act on; the manager logs it in the Plugin
Output window with the plugin's name, and carries on.

Methods are called from the program's main thread. Only log() may be called from another thread."""
import json
import os
import re
from typing import Any, Callable

from .logbook import LEVELS

API_VERSION = 1
EVENTS = ("app_started", "app_closing", "photo_opened", "edit_changed", "theme_changed", "view_changed")
TABS = ("plugins", "exposure", "correction", "negative", "watermark", "metadata")
EDIT_KEYS = (
    "exposure_ev", "contrast", "saturation", "temperature", "tint", "shadows", "highlights", "local_contrast", "chroma_denoise", "fine_rotation",
    "inverted", "film_type", "flip_h", "flip_v",
)
FILM_TYPES = ("auto", "c41", "bw", "e6")
WIDGET_TYPES = ("label", "button", "checkbox", "slider", "combo", "text", "separator", "progress")
MIN_TIMER_MS = 10
MAX_TEXT = 4000
MAX_OPTIONS = 200
MAX_FILE_BYTES = 8 * 1024 * 1024

# Names a plugin may call, by group. The Lua bridge builds its `efas` table from these lists; a Python plugin calls the same names on the api object.
FUNCTIONS = (
    "log", "debug", "info", "warn", "error", "notify", "settings_get", "settings_set", "settings_all", "after", "every", "cancel", "on", "off",
    "add_menu_item", "add_module", "message", "confirm", "ask_text", "pick_file", "pick_folder", "save_path", "read_text", "write_text",
    "photo", "photos", "open_photo", "set_edit", "sample_pixel", "image_size", "statistics", "presets", "apply_preset", "photo_tags", "add_tags", "view",
)
KEYWORD_FUNCTIONS = ("add_menu_item", "add_module", "message", "confirm", "ask_text", "pick_file", "pick_folder", "save_path")  # a Lua table argument means keyword arguments
MODULE_METHODS = ("add_label", "add_button", "add_checkbox", "add_slider", "add_combo", "add_text", "add_separator", "add_progress",
                  "set_title", "clear", "expand", "collapse", "remove")
MODULE_WIDGET_METHODS = MODULE_METHODS[:8]  # the ones that return a widget
WIDGET_METHODS = ("get_value", "set_value", "set_text", "set_enabled", "set_visible", "set_options", "set_range")
KEYWORD_METHODS = ("add_label", "add_button", "add_checkbox", "add_slider", "add_combo", "add_text", "add_progress", "set_title")


class PluginError(Exception):
    """A mistake in how a plugin used the API; the message says what to change."""


HOST = """The host a PluginCore talks to (all on the main thread; a missing capability raises or returns None as noted):
    notify(text)                                    show a line in the status area
    message(text, title) / confirm(text, title)->bool / ask_text(prompt, default, title)->str|None
    pick_file(title, filter, start)->str|None / pick_folder(title, start)->str|None / save_path(title, name, filter)->str|None
    add_menu_item(plugin_id, plugin_name, label, on_click, shortcut, submenu)->handle with remove()
    add_module(plugin_id, plugin_name, title, tab, expanded)->ModuleView: add_widget(spec)->WidgetView, set_title, clear, expand, collapse, remove
    photo_info()->dict|None, photos()->list[str], open_photo(path)->bool, set_edit(values)->list[str], view()->str
    sample_pixel(x, y)->dict|None, image_size()->(w, h)|None, statistics()->dict|None, image(max_dim)->ndarray|None
    presets()->list[str], apply_preset(name)->bool, photo_tags()->list[str], add_tags(tags)->bool"""


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise PluginError(message)


def _text(value, name: str, limit: int = MAX_TEXT, allow_empty: bool = True) -> str:
    _need(isinstance(value, str), f"{name} must be text.")
    _need(allow_empty or value.strip() != "", f"{name} cannot be empty.")
    return value[:limit]


def _number(value, name: str) -> float:
    _need(isinstance(value, (int, float)) and not isinstance(value, bool) and value == value, f"{name} must be a number.")
    return float(value)


def _callable(value, name: str, check) -> Callable:
    _need(value is not None and (callable(value) or check(value)), f"{name} must be a function.")
    return value


class WidgetHandle:
    """A control a module shows (a slider, a button, ...)."""

    def __init__(self, core: "PluginCore", view, spec: dict):
        self._core, self._view, self.kind = core, view, spec["type"]
        self._spec = spec

    def get_value(self):
        """The control's current value: the slider's number, the checkbox's true/false, the combo's chosen option, the text box's text."""
        return self._view.get_value()

    def set_value(self, value) -> None:
        """Change the value without calling the control's on_change."""
        kind = self.kind
        if kind == "slider" or kind == "progress":
            value = _number(value, "The value")
        elif kind == "checkbox":
            _need(isinstance(value, bool), "A checkbox's value must be true or false.")
        elif kind in ("combo", "text", "label"):
            value = _text(value, "The value")
        else:
            raise PluginError(f"A {kind} has no value to set.")
        self._view.set_value(value)

    def set_text(self, text: str) -> None:
        """A label's text, a button's or checkbox's caption, or a text box's text."""
        self._view.set_text(_text(text, "The text"))

    def set_enabled(self, enabled: bool) -> None:
        _need(isinstance(enabled, bool), "enabled must be true or false.")
        self._view.set_enabled(enabled)

    def set_visible(self, visible: bool) -> None:
        _need(isinstance(visible, bool), "visible must be true or false.")
        self._view.set_visible(visible)

    def set_options(self, options: list, current: str | None = None) -> None:
        """A combo box's list of choices (and which one is chosen)."""
        _need(self.kind == "combo", "Only a combo box has options.")
        self._view.set_options(_options(options), current)

    def set_range(self, minimum: float, maximum: float) -> None:
        """A slider's lowest and highest value."""
        _need(self.kind == "slider", "Only a slider has a range.")
        low, high = _number(minimum, "min"), _number(maximum, "max")
        _need(low < high, "min must be less than max.")
        self._view.set_range(low, high)


class MenuItem:
    """An item the plugin added to the Plugins menu; remove() takes it out again."""

    def __init__(self, inner):
        self._inner = inner

    def remove(self) -> None:
        self._inner.remove()


def _options(options) -> list[str]:
    _need(isinstance(options, (list, tuple)) and 0 < len(options) <= MAX_OPTIONS, f"options must be a list of 1 to {MAX_OPTIONS} items.")
    return [_text(str(o), "An option", 200) for o in options]


class ModuleHandle:
    """A module (a collapsible section) the plugin put in one of the editor's tool tabs; add controls to it."""

    def __init__(self, core: "PluginCore", view, title: str):
        self._core, self._view, self.title = core, view, title
        self._removed = False

    def _add(self, spec: dict) -> WidgetHandle:
        _need(not self._removed, "This module has been removed.")
        callback = spec.get("on_change") or spec.get("on_click")
        if callback is not None:
            _callable(callback, spec["type"] + " callback", self._core._is_lua_function)
            wrapper = self._core._wrap_callback(callback, f"{spec['type']} '{spec.get('label') or spec.get('text') or ''}'")
            spec = {**spec, "callback": wrapper}
        return WidgetHandle(self._core, self._view.add_widget(spec), spec)

    def add_label(self, text: str = "", **_ignored) -> WidgetHandle:
        """Some text."""
        return self._add({"type": "label", "text": _text(text, "The text")})

    def add_button(self, label: str, on_click=None) -> WidgetHandle:
        """A button; on_click() runs when it is pressed."""
        return self._add({"type": "button", "label": _text(label, "The label", 200, False), "on_click": on_click})

    def add_checkbox(self, label: str, checked: bool = False, on_change=None) -> WidgetHandle:
        """A check box; on_change(checked) runs when it is ticked or unticked."""
        _need(isinstance(checked, bool), "checked must be true or false.")
        return self._add({"type": "checkbox", "label": _text(label, "The label", 200, False), "checked": checked, "on_change": on_change})

    def add_slider(self, label: str, min: float = 0.0, max: float = 1.0, value: float | None = None, step: float = 0.01, decimals: int = 2, on_change=None) -> WidgetHandle:
        """A slider with a number box; on_change(value) runs when it moves (while it is dragged, then settled)."""
        low, high = _number(min, "min"), _number(max, "max")
        _need(low < high, "min must be less than max.")
        start = low if value is None else _number(value, "value")
        _need(isinstance(decimals, int) and 0 <= decimals <= 6, "decimals must be a whole number from 0 to 6.")
        return self._add({"type": "slider", "label": _text(label, "The label", 200, False), "min": low, "max": high, "value": min_max(start, low, high),
                          "step": _number(step, "step"), "decimals": decimals, "on_change": on_change})

    def add_combo(self, label: str, options: list, current: str | None = None, on_change=None) -> WidgetHandle:
        """A drop-down list; on_change(option) runs when another is chosen."""
        opts = _options(options)
        chosen = opts[0] if current is None else _text(str(current), "current", 200)
        return self._add({"type": "combo", "label": _text(label, "The label", 200, False), "options": opts, "current": chosen if chosen in opts else opts[0], "on_change": on_change})

    def add_text(self, label: str, text: str = "", on_change=None) -> WidgetHandle:
        """A text box; on_change(text) runs when you finish typing (Enter, or clicking elsewhere)."""
        return self._add({"type": "text", "label": _text(label, "The label", 200, False), "text": _text(text, "The text"), "on_change": on_change})

    def add_separator(self) -> WidgetHandle:
        """A thin line."""
        return self._add({"type": "separator"})

    def add_progress(self, label: str = "", value: float = 0.0) -> WidgetHandle:
        """A progress bar, 0 to 1 (set_value moves it)."""
        return self._add({"type": "progress", "label": _text(label, "The label", 200), "value": min_max(_number(value, "value"), 0.0, 1.0)})

    def add_widget(self, widget) -> None:
        """Python plugins only: put your own PyQt6 widget in the module."""
        _need(not self._removed, "This module has been removed.")
        _need(hasattr(widget, "sizeHint"), "add_widget needs a PyQt6 widget.")
        self._view.add_widget({"type": "qt", "widget": widget})

    def set_title(self, title: str) -> None:
        self.title = _text(title, "The title", 120, False)
        self._view.set_title(self.title)

    def clear(self) -> None:
        """Remove every control from the module (to rebuild it)."""
        self._view.clear()

    def expand(self) -> None:
        self._view.expand()

    def collapse(self) -> None:
        self._view.collapse()

    def remove(self) -> None:
        """Take the module out of the tab."""
        if not self._removed:
            self._removed = True
            self._view.remove()
            self._core._modules.discard(self)


def min_max(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class PluginCore:
    """The API for one plugin."""

    def __init__(self, manager, manifest, host, data_dir: str, version: str):
        self._manager, self._manifest, self._host = manager, manifest, host
        self._data_dir = data_dir
        self._menu_items: list = []
        self._modules: set[ModuleHandle] = set()
        self._timers: dict[int, Any] = {}
        self._subscriptions: dict[int, tuple[str, Callable]] = {}
        self._next_id = 1
        self._settings: dict | None = None
        self._allowed_paths: set[str] = set()  # files the user picked in a dialog this session: the plugin may read or write them
        self._is_lua_function: Callable[[Any], bool] = lambda value: False  # replaced by the Lua bridge
        self._lua_call: Callable | None = None
        self.api_version = API_VERSION
        self.app_version = version
        self.plugin_id = manifest.id
        self.plugin_name = manifest.name
        self.plugin_dir = manifest.folder
        self.language = manifest.language
        self.data_dir = data_dir

    # ------------------------------------------------------------ plumbing
    def _wrap_callback(self, fn, what: str) -> Callable:
        """A function the host can call with plain Python values: runs the plugin's function safely (errors go to the Plugin Output window, with the plugin's name)."""
        return lambda *args: self._manager.safe_call(self._manifest.id, fn, *args, what=what, lua=self._lua_call if self._is_lua_function(fn) else None)

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id - 1

    # ------------------------------------------------------------ output
    def log(self, message, level: str = "info") -> None:
        """Write a line to View > Plugin Output (level: debug, info, warn or error). Safe to call from any thread."""
        self._manager.logbook.add(self._manifest.name, level if level in LEVELS else "info", str(message))

    def debug(self, message) -> None:
        self.log(message, "debug")

    def info(self, message) -> None:
        self.log(message, "info")

    def warn(self, message) -> None:
        self.log(message, "warn")

    def error(self, message) -> None:
        self.log(message, "error")

    def notify(self, text) -> None:
        """Show a short line in the editor's status area."""
        self._host.notify(_text(str(text), "The text", 300))

    # ------------------------------------------------------------ settings (kept between runs, in the plugin's own folder under plugin-data)
    def _load_settings(self) -> dict:
        if self._settings is None:
            try:
                with open(os.path.join(self._data_dir, "settings.json"), "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._settings = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError):
                self._settings = {}
        return self._settings

    def settings_get(self, key: str, default=None):
        """A value this plugin saved earlier (numbers, text, true/false, lists and tables of those), or `default`."""
        return self._load_settings().get(_text(key, "The key", 200, False), default)

    def settings_set(self, key: str, value) -> None:
        """Save a value that is still there next time EFAS runs. Setting nil/None removes it."""
        key = _text(key, "The key", 200, False)
        settings = self._load_settings()
        if value is None:
            settings.pop(key, None)
        else:
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                raise PluginError("A setting can only hold numbers, text, true/false, lists and tables of those.") from None
            settings[key] = value
        os.makedirs(self._data_dir, exist_ok=True)
        tmp = os.path.join(self._data_dir, "settings.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=1)
        os.replace(tmp, os.path.join(self._data_dir, "settings.json"))

    def settings_all(self) -> dict:
        return dict(self._load_settings())

    # ------------------------------------------------------------ timers and events
    def after(self, milliseconds: float, callback) -> int:
        """Run callback() once, after the time (milliseconds, at least 10). Returns an id for cancel()."""
        return self._manager.start_timer(self, _number(milliseconds, "milliseconds"), _callable(callback, "callback", self._is_lua_function), repeat=False)

    def every(self, milliseconds: float, callback) -> int:
        """Run callback() again and again, every so many milliseconds (at least 10), until cancel() or the plugin is turned off."""
        return self._manager.start_timer(self, _number(milliseconds, "milliseconds"), _callable(callback, "callback", self._is_lua_function), repeat=True)

    def cancel(self, timer_id: int) -> None:
        self._manager.stop_timer(self, timer_id)

    def on(self, event: str, callback) -> int:
        """Run callback(info) when something happens (see EVENTS). Returns an id for off()."""
        _need(event in EVENTS, f"There is no event '{event}'. The events are: {', '.join(EVENTS)}.")
        _callable(callback, "callback", self._is_lua_function)
        sub = self._id()
        self._subscriptions[sub] = (event, callback)
        return sub

    def off(self, subscription_id: int) -> None:
        self._subscriptions.pop(subscription_id, None)

    # ------------------------------------------------------------ the window
    def add_menu_item(self, label: str, on_click, shortcut: str = "", submenu: str = ""):
        """Add an item to the Plugins menu (under this plugin's name, or under a submenu of it); on_click() runs when it is chosen."""
        label = _text(label, "The label", 120, False)
        _callable(on_click, "on_click", self._is_lua_function)
        wrapper = self._wrap_callback(on_click, f"menu item '{label}'")
        handle = self._host.add_menu_item(self._manifest.id, self._manifest.name, label, wrapper, _text(shortcut, "The shortcut", 40), _text(submenu, "The submenu", 60))
        self._menu_items.append(handle)
        return MenuItem(handle)

    def add_module(self, title: str, tab: str = "plugins", expanded: bool = False) -> ModuleHandle:
        """Add a module (a collapsible section) to a tool tab: "plugins" (the tab for plugins, the default), or one of "exposure" (WB Correction), "correction",
        "negative", "watermark", "metadata" (Roll Card). Fill it with add_label, add_button, add_slider and so on."""
        title = _text(title, "The title", 120, False)
        _need(tab in TABS, f"There is no tab '{tab}'. The tabs are: {', '.join(TABS)}.")
        module = ModuleHandle(self, self._host.add_module(self._manifest.id, self._manifest.name, title, tab, bool(expanded)), title)
        self._modules.add(module)
        return module

    # ------------------------------------------------------------ dialogs
    def message(self, text: str, title: str = "") -> None:
        """Show a message box."""
        self._host.message(_text(str(text), "The text"), _text(title, "The title", 120) or self._manifest.name)

    def confirm(self, text: str, title: str = "") -> bool:
        """Ask a yes/no question; true when the answer is yes."""
        return bool(self._host.confirm(_text(str(text), "The text"), _text(title, "The title", 120) or self._manifest.name))

    def ask_text(self, prompt: str, default: str = "", title: str = ""):
        """Ask for a line of text; returns it, or nil/None when cancelled."""
        return self._host.ask_text(_text(str(prompt), "The prompt"), _text(str(default), "The default"), _text(title, "The title", 120) or self._manifest.name)

    def pick_file(self, title: str = "Choose a file", filter: str = "All files (*)", start: str = ""):
        """Show an Open dialog; returns the chosen path (which the plugin may then read_text), or nil/None."""
        path = self._host.pick_file(_text(title, "The title", 120), _text(filter, "The filter", 200), _text(start, "The start folder", 500))
        if path:
            self._allowed_paths.add(os.path.normcase(os.path.abspath(path)))
        return path or None

    def pick_folder(self, title: str = "Choose a folder", start: str = ""):
        """Show a folder dialog; returns the chosen folder, or nil/None."""
        path = self._host.pick_folder(_text(title, "The title", 120), _text(start, "The start folder", 500))
        return path or None

    def save_path(self, title: str = "Save as", name: str = "", filter: str = "All files (*)"):
        """Show a Save dialog; returns the chosen path (which the plugin may then write_text), or nil/None."""
        path = self._host.save_path(_text(title, "The title", 120), _text(name, "The file name", 200), _text(filter, "The filter", 200))
        if path:
            self._allowed_paths.add(os.path.normcase(os.path.abspath(path)))
        return path or None

    # ------------------------------------------------------------ files (the plugin's own folder, and what the user picked)
    def _checked_path(self, path: str, write: bool) -> str:
        path = _text(path, "The path", 1000, False)
        full = path if os.path.isabs(path) else os.path.join(self._data_dir, path)
        full = os.path.abspath(full)
        key = os.path.normcase(full)
        data = os.path.normcase(os.path.abspath(self._data_dir))
        inside = key == data or key.startswith(data + os.sep)
        _need(inside or key in self._allowed_paths, "A plugin may only read and write files in its own data folder (efas.data_dir) and files you picked with pick_file or save_path.")
        return full

    def read_text(self, path: str) -> str:
        """The text of a file in the plugin's data folder (a relative path starts there) or one the user picked."""
        full = self._checked_path(path, False)
        _need(os.path.getsize(full) <= MAX_FILE_BYTES, "That file is too big to read as text (8 MB at most).")
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def write_text(self, path: str, text: str) -> None:
        """Write text to a file in the plugin's data folder (a relative path starts there) or one the user chose with save_path."""
        full = self._checked_path(path, True)
        text = _text(text, "The text", MAX_FILE_BYTES)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)

    # ------------------------------------------------------------ the photo and its edit
    def photo(self):
        """The open photo: a table with path, name, folder, width and height of the picture on screen, inverted, film_type, hq, rotation, flip_h, flip_v, crop
        and the edit values (exposure_ev, contrast, saturation, temperature, tint, shadows, highlights, local_contrast, chroma_denoise, fine_rotation). nil/None
        with no photo open."""
        return self._host.photo_info()

    def photos(self) -> list:
        """The paths of the photos in the open photo's folder, in the filmstrip's order."""
        return list(self._host.photos())

    def open_photo(self, path: str) -> bool:
        """Open a photo in the editor; false when it cannot be opened."""
        return bool(self._host.open_photo(_text(path, "The path", 1000, False)))

    def set_edit(self, values: dict) -> list:
        """Change the open photo's edit, as the sliders would (each change is a history step you can undo). `values` holds any of: exposure_ev, contrast, saturation,
        temperature, tint, shadows, highlights, local_contrast, chroma_denoise, fine_rotation (numbers), inverted, flip_h, flip_v (true/false) and film_type
        ("auto", "c41", "bw", "e6"). Returns the names that were applied."""
        _need(isinstance(values, dict) and values, "set_edit needs a table of values, like {exposure_ev = 0.3}.")
        clean: dict[str, Any] = {}
        for key, value in values.items():
            _need(key in EDIT_KEYS, f"'{key}' is not an edit value. The ones set_edit knows: {', '.join(EDIT_KEYS)}.")
            if key in ("inverted", "flip_h", "flip_v"):
                _need(isinstance(value, bool), f"{key} must be true or false.")
            elif key == "film_type":
                _need(value in FILM_TYPES, f"film_type must be one of {', '.join(FILM_TYPES)}.")
            else:
                value = _number(value, key)
            clean[key] = value
        return list(self._host.set_edit(clean))

    def sample_pixel(self, x: int, y: int):
        """The red, green and blue (0-255) of the pixel at x, y of the picture on screen, as {r, g, b}; nil/None outside it."""
        return self._host.sample_pixel(int(_number(x, "x")), int(_number(y, "y")))

    def image_size(self):
        """The size of the picture on screen as {width, height}, or nil/None."""
        size = self._host.image_size()
        return {"width": size[0], "height": size[1]} if size else None

    def statistics(self):
        """How the picture on screen reads: a table with mean, median, p1, p99, shadows_pct, midtones_pct, highlights_pct, blocked_pct, blown_pct, saturation, r, g, b
        (the figures behind the histogram's read-out); nil/None with no photo."""
        return self._host.statistics()

    def presets(self) -> list:
        """The names of the saved looks (presets)."""
        return list(self._host.presets())

    def apply_preset(self, name: str) -> bool:
        """Apply a saved look to the open photo; false when there is no such look."""
        return bool(self._host.apply_preset(_text(name, "The name", 200, False)))

    def photo_tags(self) -> list:
        """The tags on the open photo."""
        return list(self._host.photo_tags())

    def add_tags(self, tags: list) -> bool:
        """Add tags (a list of text, nested with /) to the open photo."""
        _need(isinstance(tags, (list, tuple)) and tags, "add_tags needs a list of tags, like {\"Film/Portra\"}.")
        return bool(self._host.add_tags([_text(str(t), "A tag", 200, False) for t in tags]))

    def view(self) -> str:
        """Which view is showing: "editor" or "workbench"."""
        return self._host.view()

    def image(self, max_dim: int = 1024):
        """Python plugins only: the picture on screen as a numpy array (height, width, 3) of uint8, scaled so its long side is at most max_dim; None with no photo."""
        _need(isinstance(max_dim, int) and 16 <= max_dim <= 8192, "max_dim must be a whole number from 16 to 8192.")
        return self._host.image(max_dim)

    # ------------------------------------------------------------ the manager's side
    def _dispatch(self, event: str, payload: dict) -> list:
        return [(sub, cb) for sub, (name, cb) in list(self._subscriptions.items()) if name == event]

    def _cleanup(self) -> None:
        for timer in list(self._timers.values()):
            self._manager.discard_timer(timer)
        self._timers.clear()
        self._subscriptions.clear()
        for module in list(self._modules):
            try:
                module.remove()
            except Exception:
                pass
        for item in self._menu_items:
            try:
                item.remove()
            except Exception:
                pass
        self._menu_items.clear()
