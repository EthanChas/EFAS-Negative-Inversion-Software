"""The Presets menu of a module lists darktable's own presets: "lens deblur | soft" and "lens deblur | hard" share ONE "lens deblur" submenu."""

import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMenu, QPushButton, QWidget

from photoeditor.desktop.view.module_menu import ModuleMenus


def test_built_in_presets_with_one_head_share_one_submenu(monkeypatch):
    app = QApplication.instance() or QApplication([])
    built = ["lens deblur | soft", "lens deblur | medium", "lens deblur | hard", "dehaze | default", "dehaze | strong", "surface blur"]
    controller = types.SimpleNamespace(
        module_preset_names=lambda key: [],
        module_darktable_presets=lambda key: built,
        module_active_preset=lambda key: None,
        module_preset_modified=lambda key: False,
        apply_darktable_module_preset=lambda key, name: None,
        state=types.SimpleNamespace(image_path="photo.jpg"),
    )
    shown = []

    def fake_exec(self, *args, **kwargs):
        shown.append([(a.text(), a.menu()) for a in self.actions() if a.text()])

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    panel = QWidget()
    panel.presets_button = QPushButton(panel)
    ModuleMenus(controller, QWidget())._show_menu(panel, "diffuse")
    entries = shown[0]
    heads = [text for text, sub in entries if sub is not None]
    assert heads == ["lens deblur", "dehaze"], heads
    submenu = {text: sub for text, sub in entries if sub is not None}
    assert [a.text() for a in submenu["lens deblur"].actions()] == ["soft", "medium", "hard"]
    assert [a.text() for a in submenu["dehaze"].actions()] == ["default", "strong"]
    assert "surface blur" in [text for text, sub in entries if sub is None]
    del app
