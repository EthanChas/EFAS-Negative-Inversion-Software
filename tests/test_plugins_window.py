"""Plugins in the real window: the Plugins menu and tab, modules in the tool tabs, View > Plugin Output, Settings > Plugins, and a plugin changing the open photo.
Each scenario runs in its own process (a real AppWindow, offscreen, with its own data folder)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")

_PRELUDE = textwrap.dedent(r'''
    import os, sys, tempfile, time, json
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    data = tempfile.mkdtemp()
    os.environ["PHOTOEDITOR_DATA_DIR"] = data
    work = tempfile.mkdtemp()
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    from photoeditor.plugins import templates
    S.save({"scan_quality": False})
    p = os.path.join(work, "a.png")
    cv2.imwrite(p, np.random.default_rng(0).integers(30, 220, (200, 300, 3), dtype=np.uint8))
    app = QApplication([])
    from photoeditor.desktop.view import app_window as aw
    win = aw.AppWindow(); win.show(); win.open_folder(work, prefer=p)

    def pump(s):
        end = time.time() + s
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)

    def plugin(folder, entry, source, **manifest):
        d = os.path.join(m.folder(), folder)
        os.makedirs(d, exist_ok=True)
        meta = {"id": "t." + folder, "name": folder, "version": "1", "entry": entry, **manifest}
        open(os.path.join(d, "plugin.json"), "w", encoding="utf-8").write(json.dumps(meta))
        open(os.path.join(d, entry), "w", encoding="utf-8").write(source)

    pump(1.5)
    m = win._plugin_manager
''')


def _run(body: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return subprocess.run([sys.executable, "-X", "faulthandler", "-c", _PRELUDE + textwrap.dedent(body)], env=env, capture_output=True, text=True, timeout=240)


def _ok(result: subprocess.CompletedProcess) -> None:
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-3000:]


def test_plugins_menu_tab_and_modules_follow_the_plugins_that_are_on():
    _ok(_run(r'''
        assert [a.text() for a in win._plugins_menu.actions() if a.text()] == ["Manage Plugins...", "Reload Plugins", "Open Plugins Folder"]
        assert not win._tool_rail._frames["plugins"].isVisible(), "no plugin, no Plugins tab"
        added = templates.install_examples(m.folder()); m.refresh()
        assert len(added) == 5 and all(not e.enabled for e in m.entries()), "examples start switched off"
        assert not [a for a in win._plugins_menu.actions() if a.menu()], "nothing is added by a switched-off plugin"
        for e in m.entries():
            m.set_enabled(e.id, True)
        pump(0.4)
        assert all(e.state == "loaded" for e in m.entries()), [(e.id, e.error) for e in m.entries()]
        names = {a.text(): [x.text() for x in a.menu().actions()] for a in win._plugins_menu.actions() if a.menu()}
        assert names["Hello (Lua)"] == ["Say hello"] and names["Photo Report (Python)"] == ["Photo Report"], names
        assert win._tool_rail._frames["plugins"].isVisible(), "the Plugins tab shows while a plugin has a module in it"
        # a module in another tab: the exposure example
        assert len(m.host._modules["exposure"]) == 1 and len(m.host._modules["plugins"]) == 2
        # the tab opens and holds the modules
        win._tool_rail._buttons["plugins"].click(); pump(0.7)
        assert win._plugins_panel._is_open and win._open_tab == "plugins"
        win._tool_rail._buttons["exposure"].click(); pump(0.7)
        assert not win._plugins_panel._is_open, "opening another tab closes the Plugins tab"
        # switching them off takes everything away again
        for e in m.entries():
            m.set_enabled(e.id, False)
        pump(0.3)
        assert [a.text() for a in win._plugins_menu.actions() if a.text()] == ["Manage Plugins...", "Reload Plugins", "Open Plugins Folder"]
        assert not win._tool_rail._frames["plugins"].isVisible() and not m.host._modules["exposure"] and not m.host._modules["plugins"]
        # the state is remembered
        assert S.get("plugins_enabled")["efas.example.hello-lua"] is False
        print("ok")
    '''))


def test_view_plugin_output_opens_and_closes_the_log_window():
    _ok(_run(r'''
        view = [a for a in win._menubar.actions() if a.text() == "View"][0].menu()
        action = [a for a in view.actions() if a.text() == "Plugin Output"][0]
        assert action.isCheckable() and not action.isChecked() and win._plugin_log is None
        plugin("chatty", "main.lua", "print('first line')\nefas.warn('careful')\nefas.debug('detail')")
        m.refresh(); m.set_enabled("t.chatty", True)
        action.setChecked(True); pump(0.3)
        log = win._plugin_log
        assert log is not None and log.isVisible() and action.isChecked()
        text = "\n".join(log.lines())
        assert "[chatty] first line" in text and "WARN" in text and "detail" not in text, text   # debug is hidden at "Info and up"
        # lines written while it is open appear
        m.log("error", "live line", "chatty"); pump(0.2)
        assert any("live line" in l for l in log.lines()) and "live line" in log._view.toPlainText()
        # filters
        log._level_box.setCurrentIndex(0); pump(0.1)
        assert any("detail" in l for l in log.lines())
        log._level_box.setCurrentIndex(3); pump(0.1)
        assert all("ERROR" in l for l in log.lines()) and log.lines()
        log._level_box.setCurrentIndex(1)
        log._plugin_box.setCurrentIndex(log._plugin_box.findText("chatty")); pump(0.1)
        assert log.lines() and all("[chatty]" in l for l in log.lines())
        log._plugin_box.setCurrentIndex(0)
        # un-ticking closes it; ticking again opens it with the old lines
        action.setChecked(False); pump(0.2)
        assert not log.isVisible() and not action.isChecked()
        m.log("info", "while closed", "chatty")
        action.setChecked(True); pump(0.2)
        assert log.isVisible() and any("while closed" in l for l in log.lines())
        # closing the window with its own X un-ticks the menu item
        log.close(); pump(0.2)
        assert not action.isChecked()
        action.setChecked(True); pump(0.2); log._clear(); pump(0.1)
        assert log.lines() == [] and m.logbook.records() == []
        print("ok")
    '''))


def test_errors_in_plugins_reach_the_log_and_do_not_stop_the_program():
    _ok(_run(r'''
        plugin("bad-lua", "main.lua", "error('lua went wrong')")
        plugin("bad-py", "main.py", "def register(api):\n    raise RuntimeError('py went wrong')\n")
        plugin("exits", "main.py", "import sys\ndef register(api):\n    api.add_menu_item('Quit', lambda: sys.exit(3))\n")
        plugin("loops", "main.lua", "efas.add_menu_item{label='Spin', on_click=function() while true do end end}")
        m.refresh()
        for pid in ("t.bad-lua", "t.bad-py", "t.exits", "t.loops"):
            m.set_enabled(pid, True)
        states = {e.id: e.state for e in m.entries()}
        assert states == {"t.bad-lua": "error", "t.bad-py": "error", "t.exits": "loaded", "t.loops": "loaded"}, states
        win.set_plugin_output_visible(True); pump(0.2)
        text = "\n".join(win._plugin_log.lines())
        assert "lua went wrong" in text and "py went wrong" in text
        menus = {a.text(): a.menu().actions()[0] for a in win._plugins_menu.actions() if a.menu()}
        menus["exits"].trigger(); pump(0.1)           # SystemExit from a plugin does not close the program
        assert win.isVisible()
        t0 = time.time(); menus["loops"].trigger(); pump(0.1)
        assert time.time() - t0 < 15 and "too long" in "\n".join(win._plugin_log.lines())
        print("ok")
    '''))


def test_a_plugin_reads_and_changes_the_open_photo_like_the_sliders():
    _ok(_run(r'''
        plugin("editor", "main.lua", """
            seen = {}
            efas.on('edit_changed', function(info) seen[#seen + 1] = 'edit' end)
            efas.on('photo_opened', function(info) print('opened ' .. info.name) end)
            efas.add_menu_item{label='Brighter', on_click=function()
                local before = efas.photo()
                print('before ' .. before.exposure_ev)
                efas.set_edit{exposure_ev = 0.7, contrast = 12, saturation = 5}
                print('size ' .. efas.image_size().width .. 'x' .. efas.image_size().height)
                print('mean ' .. math.floor(efas.statistics().mean))
                local px = efas.sample_pixel(0, 0)
                print('px ' .. (px and 'yes' or 'no'))
                print('tags ' .. tostring(efas.add_tags({'Test/One'})))
            end}
        """)
        m.refresh(); m.set_enabled("t.editor", True)
        c = win.controller
        host = m.host
        assert host.photo_info()["name"] == "a.png" and host.view() == "editor"
        win.open_folder(work, prefer=p); pump(1.0)
        action = [a for a in win._plugins_menu.actions() if a.menu()][0].menu().actions()[0]
        steps_before = len(c.state.history)
        win.set_plugin_output_visible(True)
        seen = lambda: len(list(m.entry("t.editor").sandbox.lua.globals()["seen"].keys()))
        before_edit = seen()
        action.trigger(); pump(1.2)
        st = c.state
        assert (st.exposure_ev, st.contrast, st.saturation) == (0.7, 12, 5), (st.exposure_ev, st.contrast, st.saturation)
        assert len(st.history) > steps_before, "the changes are history steps"
        text = "\n".join(win._plugin_log.lines())
        assert "before 0" in text and "size 300x200" in text and "mean " in text and "px yes" in text, text
        # nothing here was announced as edit_changed (the plugin's own edit), but a real slider move is
        assert seen() == before_edit, "the plugin's own edit was not announced to it"
        c.set_exposure_ev(1.0); pump(1.0)
        assert seen() > before_edit, "a slider move is announced"
        # errors: nothing open / unknown value
        assert host.set_edit({"exposure_ev": 0.1}) == ["exposure_ev"]
        print("ok")
    '''))


def test_settings_plugins_page_lists_and_applies_choices():
    _ok(_run(r'''
        from photoeditor.desktop.view.settings_dialog import SettingsDialog
        plugin("alpha", "main.lua", "print('alpha on')", description="Does alpha things", author="Me")
        os.makedirs(os.path.join(m.folder(), "broken"), exist_ok=True)
        m.refresh()
        dialog = SettingsDialog(win, win.controller, plugins=m, start_page="Plugins")
        assert dialog._categories.currentItem().text() == "Plugins"
        assert set(dialog.plugin_choices()) == {"t.alpha"}, "only usable plugins have a check box"
        box = dialog._plugin_checks["t.alpha"]
        assert not box.isChecked() and "Me" in box.text()
        box.setChecked(True)
        win._apply_plugin_choices(dialog.plugin_choices())
        assert m.entry("t.alpha").state == "loaded" and S.get("plugins_enabled") == {"t.alpha": True}
        # a rescan keeps what was ticked and shows the example plugins once installed
        added = templates.install_examples(m.folder()); dialog._rescan_plugins()
        assert len(dialog.plugin_choices()) == 6 and dialog._plugin_checks["t.alpha"].isChecked()
        # without a manager the page still builds
        bare = SettingsDialog(win, win.controller)
        assert bare.plugin_choices() == {}
        # the General page values still come back
        assert "hq_always" in dialog.values()
        print("ok")
    '''))


def test_app_closing_is_sent_and_a_reload_picks_up_edits():
    _ok(_run(r'''
        marker = os.path.join(data, "closing.txt")
        plugin("bye", "main.py", "def register(api):\n    api.on('app_closing', lambda info: open(" + repr(marker) + ", 'w').write('bye'))\n    api.info('v1')\n")
        m.refresh(); m.set_enabled("t.bye", True)
        win.set_plugin_output_visible(True)
        assert any("v1" in l for l in win._plugin_log.lines())
        plugin("bye", "main.py", "def register(api):\n    api.on('app_closing', lambda info: open(" + repr(marker) + ", 'w').write('bye'))\n    api.info('v2')\n")
        m.reload_all(); pump(0.2)
        assert any("v2" in l for l in win._plugin_log.lines()), "reload runs the edited file"
        win.close(); pump(0.3)
        assert os.path.isfile(marker) and open(marker).read() == "bye"
        print("ok")
    '''))
