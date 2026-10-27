"""Every key EFAS ships with is one the Settings dialog accepts: a default that broke the dialog's own rule once kept Save greyed out on every page."""
import os

from photoeditor.features.keybinds import logic as binds


def test_no_default_key_has_a_problem_or_a_clash():
    current = binds.bindings({})
    assert binds.conflicts(current) == {}
    assert {i: binds.menu_key_problem(i, s) for i, s in current.items() if binds.menu_key_problem(i, s)} == {}
    assert binds.BY_ID["error_marks"].default == "Alt+E"


def test_save_is_available_in_the_settings_dialog_out_of_the_box():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from photoeditor.desktop.view.settings_dialog import SettingsDialog

    dialog = SettingsDialog()
    assert dialog._save.isEnabled(), dialog._key_problem.text()
    app.processEvents()
