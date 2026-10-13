"""The plugin API's host (see HOST in plugins/api.py) for the real window: puts plugins' menu items in the Plugins menu and their modules in the tool tabs, shows
their dialogs, and reads and changes the open photo through the controller - the same calls the sliders make, so every change is a history step."""
import os

from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMenu, QMessageBox, QVBoxLayout

from ...features.open_image.logic import SUPPORTED_EXTS
from ...plugins import measure
from ...plugins.api import PluginError
from .collapsible_panel import CollapsiblePanel
from .plugin_widgets import ModuleView


class _MenuHandle:
    """One plugin menu item; remove() takes it (and an emptied submenu) out of the Plugins menu."""

    def __init__(self, host: "WindowPluginHost", plugin_id: str, action: QAction, plugin_menu: QMenu, nested: QMenu | None):
        self._host, self._plugin_id, self._action, self._plugin_menu, self._nested = host, plugin_id, action, plugin_menu, nested

    def remove(self) -> None:
        (self._nested or self._plugin_menu).removeAction(self._action)
        self._action.deleteLater()
        if self._nested is not None and not self._nested.actions():
            self._plugin_menu.removeAction(self._nested.menuAction())
            self._nested.deleteLater()
        self._host._prune_plugin_menu(self._plugin_id)


class WindowPluginHost:
    def __init__(self, window, plugins_menu: QMenu, anchor: QAction, tab_columns: dict[str, QVBoxLayout], tab_changed):
        self._window = window
        self._menu = plugins_menu
        self._anchor = anchor  # plugin submenus go in front of this (the fixed items under them)
        self._columns = tab_columns
        self._tab_changed = tab_changed  # called (tab, module count) when a tab gains its first or loses its last plugin module
        self._plugin_menus: dict[str, QMenu] = {}
        self._modules: dict[str, list[ModuleView]] = {tab: [] for tab in tab_columns}

    @property
    def controller(self):
        return self._window.controller

    # ------------------------------------------------------------ the status line and dialogs
    def notify(self, text: str) -> None:
        self._window._coord_label.setText(text)

    def message(self, text: str, title: str) -> None:
        QMessageBox.information(self._window, title, text)

    def confirm(self, text: str, title: str) -> bool:
        return QMessageBox.question(self._window, title, text) == QMessageBox.StandardButton.Yes

    def ask_text(self, prompt: str, default: str, title: str):
        text, ok = QInputDialog.getText(self._window, title, prompt, text=default)
        return text if ok else None

    def pick_file(self, title: str, filter: str, start: str):
        path, _ = QFileDialog.getOpenFileName(self._window, title, start, filter)
        return path or None

    def pick_folder(self, title: str, start: str):
        path = QFileDialog.getExistingDirectory(self._window, title, start)
        return path or None

    def save_path(self, title: str, name: str, filter: str):
        path, _ = QFileDialog.getSaveFileName(self._window, title, name, filter)
        return path or None

    # ------------------------------------------------------------ the Plugins menu
    def _plugin_menu(self, plugin_id: str, plugin_name: str) -> QMenu:
        menu = self._plugin_menus.get(plugin_id)
        if menu is None:
            menu = QMenu(plugin_name, self._menu)
            self._menu.insertMenu(self._anchor, menu)
            self._plugin_menus[plugin_id] = menu
        return menu

    def add_menu_item(self, plugin_id: str, plugin_name: str, label: str, on_click, shortcut: str, submenu: str):
        plugin_menu = menu = self._plugin_menu(plugin_id, plugin_name)
        nested = None
        if submenu:
            nested = next((a.menu() for a in menu.actions() if a.menu() is not None and a.text() == submenu), None)
            if nested is None:
                nested = menu.addMenu(submenu)
            menu = nested
        action = QAction(label, menu)
        if shortcut:
            sequence = QKeySequence(shortcut)
            if sequence.isEmpty():
                raise PluginError(f"'{shortcut}' is not a keyboard shortcut. Write it like Ctrl+Shift+K.")
            action.setShortcut(sequence)
        action.triggered.connect(lambda _checked=False: on_click())
        menu.addAction(action)
        return _MenuHandle(self, plugin_id, action, plugin_menu, nested)

    def _prune_plugin_menu(self, plugin_id: str) -> None:
        menu = self._plugin_menus.get(plugin_id)
        if menu is not None and not menu.actions():
            self._menu.removeAction(menu.menuAction())
            menu.deleteLater()
            del self._plugin_menus[plugin_id]

    # ------------------------------------------------------------ modules in the tool tabs
    def add_module(self, plugin_id: str, plugin_name: str, title: str, tab: str, expanded: bool) -> ModuleView:
        column = self._columns[tab]
        panel = CollapsiblePanel(title, start_expanded=expanded)
        panel.setToolTip(f"Added by the plugin {plugin_name}")
        column.insertWidget(max(0, column.count() - 1), panel)  # in front of the tab's trailing stretch
        view = ModuleView(panel, lambda v, tab=tab: self._module_removed(tab, v))
        self._modules[tab].append(view)
        self._tab_changed(tab, len(self._modules[tab]))
        return view

    def _module_removed(self, tab: str, view: ModuleView) -> None:
        if view in self._modules[tab]:
            self._modules[tab].remove(view)
            self._tab_changed(tab, len(self._modules[tab]))

    # ------------------------------------------------------------ the open photo
    def photo_info(self):
        s = self.controller.state
        if s.image_path is None:
            return None
        image = s.image_rgb
        height, width = (image.shape[:2] if image is not None else (0, 0))
        return {
            "path": s.image_path, "name": os.path.basename(s.image_path), "folder": os.path.dirname(s.image_path), "width": int(width), "height": int(height),
            "inverted": bool(s.negative_inverted), "film_type": s.film_type, "hq": bool(s.hq_enabled), "rotation": int(s.rotation_quarter_turns) * 90,
            "flip_h": bool(s.flip_h), "flip_v": bool(s.flip_v), "crop": list(s.crop_rect) if s.crop_rect else None,
            "exposure_ev": float(s.exposure_ev), "contrast": float(s.contrast), "saturation": float(s.saturation), "temperature": float(s.temperature),
            "tint": float(s.tint), "shadows": float(s.shadows), "highlights": float(s.highlights), "local_contrast": float(s.local_contrast),
            "chroma_denoise": float(s.chroma_denoise), "fine_rotation": float(s.fine_rotation),
        }

    def photos(self) -> list[str]:
        return list(self.controller.state.image_paths)

    def open_photo(self, path: str) -> bool:
        if not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in SUPPORTED_EXTS:
            return False
        self._window.set_view("editor")
        self.controller.open_file(path)
        return True

    def set_edit(self, values: dict) -> list[str]:
        c = self.controller
        s = c.state
        if s.image_path is None or s.preview_rgb is None:
            raise PluginError("No photo is open: open one first (efas.open_photo) before changing its edit.")
        applied: list[str] = []

        def one(key, fn, *args):
            if key in values:
                fn(*args)
                applied.append(key)

        if "film_type" in values:
            c.set_film_type(values["film_type"])
            applied.append("film_type")
        if "inverted" in values:
            c.set_negative_inverted(values["inverted"])
            applied.append("inverted")
        one("exposure_ev", c.set_exposure_ev, values.get("exposure_ev"))
        one("contrast", c.set_contrast, values.get("contrast"))
        if {"saturation", "temperature", "tint"} & set(values):
            c.set_color(values.get("saturation", s.saturation), values.get("temperature", s.temperature), values.get("tint", s.tint))
            applied += [k for k in ("saturation", "temperature", "tint") if k in values]
        if {"shadows", "highlights"} & set(values):
            c.set_shadows_highlights(values.get("shadows", s.shadows), values.get("highlights", s.highlights))
            applied += [k for k in ("shadows", "highlights") if k in values]
        one("local_contrast", c.set_local_contrast, values.get("local_contrast"))
        one("chroma_denoise", c.set_chroma_denoise, values.get("chroma_denoise"))
        one("fine_rotation", c.set_fine_rotation, values.get("fine_rotation"))
        one("flip_h", c.set_flip_h, values.get("flip_h"))
        one("flip_v", c.set_flip_v, values.get("flip_v"))
        self._window._on_reverted()  # the tool panels show what the edit now is
        self._window.plugin_edit_made()  # so the plugins are not told about a change one of them just made
        return applied

    def view(self) -> str:
        return "workbench" if self._window.lighttable_active() else "editor"

    # ------------------------------------------------------------ the picture on screen
    def _rgb(self):
        return self.controller.state.image_rgb

    def sample_pixel(self, x: int, y: int):
        return measure.sample(self._rgb(), x, y)

    def image_size(self):
        image = self._rgb()
        return (int(image.shape[1]), int(image.shape[0])) if image is not None else None

    def statistics(self):
        return measure.statistics(self._rgb())

    def image(self, max_dim: int):
        return measure.scaled(self._rgb(), max_dim)

    # ------------------------------------------------------------ looks and tags
    def presets(self) -> list[str]:
        return self.controller.look_presets()

    def apply_preset(self, name: str) -> bool:
        if self.controller.state.image_path is None or name not in self.controller.look_presets():
            return False
        return bool(self.controller.apply_look_preset(name))

    def photo_tags(self) -> list[str]:
        path = self.controller.state.image_path
        if path is None:
            return []
        return list(self.controller.tagging_data([path])[0].get(path, []))

    def add_tags(self, tags: list[str]) -> bool:
        path = self.controller.state.image_path
        if path is None:
            return False
        self.controller.set_tags_for([path], add=tags)
        return True

