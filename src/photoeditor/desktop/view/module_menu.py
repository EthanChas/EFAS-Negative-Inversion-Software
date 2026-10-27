from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QInputDialog, QMenu, QMessageBox, QWidget

from ...features.lookpresets.modules import SWITCHABLE
from ..controller import AppController
from .collapsible_panel import CollapsiblePanel


class ModuleMenus(QObject):
    """The Reset and Presets buttons in a module's header, darktable-style."""

    def __init__(self, controller: AppController, parent: QWidget | None = None, sharing=None):
        super().__init__(parent)
        self._controller = controller
        self._sharing = sharing   # exports and imports presets as files (PresetSharing); without it the menu has no such entries
        self._panels: dict[str, CollapsiblePanel] = {}

    def attach(self, panel: CollapsiblePanel, key: str) -> None:
        panel.enable_module_buttons()
        self._panels[key] = panel
        panel.reset_button.clicked.connect(lambda _c=False, k=key: self._controller.reset_module(k))
        panel.presets_button.clicked.connect(lambda _c=False, p=panel, k=key: self._show_menu(p, k))
        panel.update_preset_button.clicked.connect(lambda _c=False, k=key: self._controller.update_module_preset(k))
        if key in SWITCHABLE:
            panel.enable_power_switch()
            panel.power_toggled.connect(lambda on, k=key: self._controller.set_module_enabled(k, on))

    def refresh(self, *_args) -> None:
        """Show or hide every panel's Update Preset button: it is there while the preset loaded on the module has been changed."""
        for key, panel in self._panels.items():
            if key in SWITCHABLE:
                panel.set_power(self._controller.module_enabled(key))
            name = self._controller.module_active_preset(key)
            panel.set_preset_status(name, bool(name) and self._controller.module_preset_modified(key))

    def _show_menu(self, panel: CollapsiblePanel, key: str) -> None:
        c = self._controller
        names = c.module_preset_names(key)
        has_photo = c.state.image_path is not None
        menu = QMenu(panel)
        active = c.module_active_preset(key)
        for name in names:
            action = menu.addAction(name)
            action.setEnabled(has_photo)
            action.setCheckable(True)
            action.setChecked(name == active)
            action.triggered.connect(lambda _c=False, n=name: c.apply_module_preset(key, n))
        built = c.module_darktable_presets(key)
        if not names and not built:
            menu.addAction("No presets yet").setEnabled(False)
        if built:     # darktable's own presets for this module, read-only: "lens deblur | soft" is "soft" in a "lens deblur" submenu
            if names:
                menu.addSeparator()
            groups: dict[str, QMenu] = {}
            for name in built:
                head, _, tail = name.partition(" | ")
                if tail and head not in groups:
                    groups[head] = menu.addMenu(head)
                target = groups[head] if tail else menu
                action = target.addAction(tail or name)
                action.setEnabled(has_photo)
                action.setToolTip(f"Built-in preset '{name}'" + (" (ported from darktable)" if key in ("diffuse", "toneequalizer", "colorbalancergb") else ""))
                action.triggered.connect(lambda _c=False, n=name: c.apply_darktable_module_preset(key, n))
        menu.addSeparator()
        if active is not None and c.module_preset_modified(key):
            update = menu.addAction(f"Update preset '{active}'")
            update.triggered.connect(lambda _c=False: c.update_module_preset(key))
        store = menu.addAction("Store new preset...")
        store.setEnabled(has_photo)
        store.triggered.connect(lambda _c=False: self._store(panel, key, names))
        if names:
            delete = menu.addMenu("Delete preset")
            for name in names:
                delete.addAction(name).triggered.connect(lambda _c=False, n=name: self._delete(panel, key, n))
        if self._sharing is not None:
            menu.addSeparator()
            export = menu.addAction("Export this module's presets...")
            export.setEnabled(bool(names))
            export.triggered.connect(lambda _c=False: self._sharing.export_presets(panel, "module", key))
            menu.addAction("Import presets...").triggered.connect(lambda _c=False: self._sharing.import_presets(panel))
        button = panel.presets_button
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _store(self, panel: CollapsiblePanel, key: str, names: list[str]) -> None:
        title = self._controller.module_title(key)
        name, ok = QInputDialog.getText(panel, f"Store {title} Preset", "Name for these settings:")
        name = " ".join(name.split())
        if not ok or not name:
            return
        if any(n.casefold() == name.casefold() for n in names):
            answer = QMessageBox.question(
                panel, f"Store {title} Preset", f"A {title} preset called '{name}' already exists. Replace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._controller.store_module_preset(key, name)

    def _delete(self, panel: CollapsiblePanel, key: str, name: str) -> None:
        title = self._controller.module_title(key)
        answer = QMessageBox.question(
            panel, f"Delete {title} Preset", f"Delete the {title} preset '{name}'? Photos it was applied to keep their edits.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.delete_module_preset(key, name)
