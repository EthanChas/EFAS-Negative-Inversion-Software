from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QInputDialog, QMenu, QMessageBox, QWidget

from ..controller import AppController
from .collapsible_panel import CollapsiblePanel


class ModuleMenus(QObject):
    """The Reset and Presets buttons in a module's header, darktable-style."""

    def __init__(self, controller: AppController, parent: QWidget | None = None):
        super().__init__(parent)
        self._controller = controller
        self._panels: dict[str, CollapsiblePanel] = {}

    def attach(self, panel: CollapsiblePanel, key: str) -> None:
        panel.enable_module_buttons()
        self._panels[key] = panel
        panel.reset_button.clicked.connect(lambda _c=False, k=key: self._controller.reset_module(k))
        panel.presets_button.clicked.connect(lambda _c=False, p=panel, k=key: self._show_menu(p, k))
        panel.update_preset_button.clicked.connect(lambda _c=False, k=key: self._controller.update_module_preset(k))

    def refresh(self, *_args) -> None:
        """Show or hide every panel's Update Preset button: it is there while the preset loaded on the module has been changed."""
        for key, panel in self._panels.items():
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
        if not names:
            menu.addAction("No presets yet").setEnabled(False)
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
