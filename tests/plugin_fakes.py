"""A stand-in for the window, for testing the plugin API without one: records what plugins ask for, and lets a test press a button or move a slider."""
import json
import os
import sys
import textwrap


class FakeWidget:
    def __init__(self, spec):
        self.spec = spec
        self.value = spec.get("value", spec.get("checked", spec.get("current", spec.get("text", ""))))
        self.text = spec.get("text") or spec.get("label") or ""
        self.enabled, self.visible = True, True
        self.options = spec.get("options")
        self.range = (spec.get("min"), spec.get("max"))

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value

    def set_text(self, text):
        self.text = text

    def set_enabled(self, enabled):
        self.enabled = enabled

    def set_visible(self, visible):
        self.visible = visible

    def set_options(self, options, current):
        self.options = options
        self.value = current if current in options else options[0]

    def set_range(self, low, high):
        self.range = (low, high)

    # what the user does
    def user_sets(self, value):
        self.value = value
        callback = self.spec.get("callback")
        if callback:
            callback(value)

    def press(self):
        callback = self.spec.get("callback")
        if callback:
            callback()


class FakeModule:
    def __init__(self, plugin_id, title, tab, expanded):
        self.plugin_id, self.title, self.tab, self.expanded = plugin_id, title, tab, expanded
        self.widgets: list[FakeWidget] = []
        self.removed = False

    def add_widget(self, spec):
        widget = FakeWidget(spec)
        self.widgets.append(widget)
        return widget

    def set_title(self, title):
        self.title = title

    def clear(self):
        self.widgets.clear()

    def expand(self):
        self.expanded = True

    def collapse(self):
        self.expanded = False

    def remove(self):
        self.removed = True


class FakeMenuItem:
    def __init__(self, plugin_id, plugin_name, label, on_click, shortcut, submenu):
        self.plugin_id, self.plugin_name, self.label, self.on_click, self.shortcut, self.submenu = plugin_id, plugin_name, label, on_click, shortcut, submenu
        self.removed = False

    def remove(self):
        self.removed = True

    def trigger(self):
        self.on_click()


class FakeHost:
    def __init__(self):
        self.notices: list[str] = []
        self.menu_items: list[FakeMenuItem] = []
        self.modules: list[FakeModule] = []
        self.dialog_answers = {"confirm": True, "ask_text": "typed", "pick_file": None, "pick_folder": None, "save_path": None}
        self.messages: list[tuple[str, str]] = []
        self.photo = {"path": "C:/photos/a.tif", "name": "a.tif", "folder": "C:/photos", "width": 400, "height": 300, "inverted": True, "film_type": "c41",
                      "hq": False, "rotation": 0, "flip_h": False, "flip_v": False, "crop": None, "exposure_ev": 0.0, "contrast": 0.0, "saturation": 0.0,
                      "temperature": 0.0, "tint": 0.0, "shadows": 0.0, "highlights": 0.0, "local_contrast": 0.0, "chroma_denoise": 0.0, "fine_rotation": 0.0}
        self.edits: list[dict] = []
        self.opened: list[str] = []
        self.preset_names = ["Warm", "Cool"]
        self.applied: list[str] = []
        self.tags: list[str] = ["Film/Portra"]
        self.view_name = "editor"

    def notify(self, text):
        self.notices.append(text)

    def message(self, text, title):
        self.messages.append((title, text))

    def confirm(self, text, title):
        return self.dialog_answers["confirm"]

    def ask_text(self, prompt, default, title):
        return self.dialog_answers["ask_text"]

    def pick_file(self, title, filter, start):
        return self.dialog_answers["pick_file"]

    def pick_folder(self, title, start):
        return self.dialog_answers["pick_folder"]

    def save_path(self, title, name, filter):
        return self.dialog_answers["save_path"]

    def add_menu_item(self, plugin_id, plugin_name, label, on_click, shortcut, submenu):
        item = FakeMenuItem(plugin_id, plugin_name, label, on_click, shortcut, submenu)
        self.menu_items.append(item)
        return item

    def add_module(self, plugin_id, plugin_name, title, tab, expanded):
        module = FakeModule(plugin_id, title, tab, expanded)
        self.modules.append(module)
        return module

    def photo_info(self):
        return dict(self.photo) if self.photo else None

    def photos(self):
        return ["C:/photos/a.tif", "C:/photos/b.tif"]

    def open_photo(self, path):
        self.opened.append(path)
        return path.endswith(".tif")

    def set_edit(self, values):
        self.edits.append(dict(values))
        self.photo.update(values)
        return list(values)

    def view(self):
        return self.view_name

    def sample_pixel(self, x, y):
        return {"r": 10, "g": 20, "b": 30} if 0 <= x < 400 and 0 <= y < 300 else None

    def image_size(self):
        return (400, 300) if self.photo else None

    def statistics(self):
        return {"mean": 120.5, "median": 118.0, "p1": 4.0, "p99": 250.0, "shadows_pct": 20.0, "midtones_pct": 60.0, "highlights_pct": 20.0, "blocked_pct": 0.5,
                "blown_pct": 1.5, "saturation": 0.3, "r": 125.0, "g": 120.0, "b": 115.0} if self.photo else None

    def image(self, max_dim):
        import numpy as np

        return np.zeros((30, 40, 3), np.uint8)

    def presets(self):
        return list(self.preset_names)

    def apply_preset(self, name):
        if name in self.preset_names:
            self.applied.append(name)
            return True
        return False

    def photo_tags(self):
        return list(self.tags)

    def add_tags(self, tags):
        self.tags.extend(tags)
        return True


class MemoryStore:
    """Stands in for the settings file's list of switched-on plugins."""

    def __init__(self):
        self.enabled: dict = {}

    def get(self):
        return dict(self.enabled)

    def set(self, enabled):
        self.enabled = dict(enabled)


def write_plugin(root, folder: str, language: str, source: str, **manifest):
    """Make <root>/<folder>/plugin.json and main.py or main.lua; returns the plugin's folder."""
    path = os.path.join(str(root), folder)
    os.makedirs(path, exist_ok=True)
    entry = "main.py" if language == "python" else "main.lua"
    data = {"id": folder.lower(), "name": folder, "version": "1.0", "entry": entry, **manifest}
    with open(os.path.join(path, "plugin.json"), "w", encoding="utf-8") as f:
        json.dump(data, f)
    with open(os.path.join(path, entry), "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(source))
    return path


def make_manager(tmp_path, host=None, store=None):
    """A PluginManager over a temporary plugins folder, a fake host and an in-memory enabled list (needs a QApplication)."""
    from photoeditor.plugins.manager import PluginManager

    host = host or FakeHost()
    store = store or MemoryStore()
    manager = PluginManager(host, "0.6.1", plugins_dir=str(tmp_path / "plugins"), data_root=str(tmp_path / "plugin-data"), store=store)
    return manager, host, store
