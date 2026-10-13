"""Hello (Python): a menu item, a module with a slider and a check box, and some output.

A Python plugin is a file with a register(api) function. EFAS calls it when the plugin is switched on (Settings > Plugins); `api` is everything the plugin can do.
An optional unregister() runs when it is switched off. Menu items, modules, timers and event listeners are removed for you.
"""


def register(api):
    api.info(f"Hello from {api.plugin_name} (EFAS {api.app_version})")  # shows in View > Plugin Output

    api.add_menu_item("Say hello", lambda: api.message("Hello from Python!"), shortcut="Ctrl+Alt+H")

    module = api.add_module("Hello (Python)")  # goes in the Plugins tab
    status = module.add_label("Move the slider.")

    def moved(value):
        api.settings_set("amount", value)  # saved between runs
        status.set_text(f"Amount is {value:.2f}")

    module.add_slider("Amount", min=0, max=1, value=api.settings_get("amount", 0.5), on_change=moved)
    module.add_checkbox("Shout", checked=False, on_change=lambda on: api.notify("HELLO!" if on else "hello"))
