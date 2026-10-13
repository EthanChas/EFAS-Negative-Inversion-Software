# Python plugins

A Python plugin is a `plugin.json` plus a `main.py` (or another `.py` file named by `entry`). The file must define:

```python
def register(api):
    ...
```

EFAS calls `register(api)` once when the plugin is switched on. `api` is the whole [API](api-reference.md). Add your menu items and modules there and register your callbacks; they run later.

An optional function runs when the plugin is switched off or reloaded:

```python
def unregister():
    ...
```

You do **not** need to remove your menu items, modules, timers or event listeners there: EFAS removes them. Use `unregister` for things only you know about (closing a file or a window of your own).

## Minimal plugin

```python
def register(api):
    api.info(f"{api.plugin_name} loaded")
    api.add_menu_item("Count the photos", lambda: api.message(f"{len(api.photos())} photos in this folder"))
```

## Importing

- The plugin's own folder is on the import path while the plugin loads, so `import helpers` loads `helpers.py` beside `main.py`.
- Modules a plugin imports are forgotten when it is switched off, so a reload picks up your edits.
- **In the downloaded program (the Windows .exe)** a plugin can import only what the program was built with: the Python standard library modules EFAS itself uses, plus `numpy`, `PIL` (Pillow), `cv2` (OpenCV), `PyQt6` and `rawpy`. A plugin that needs another library works when EFAS is run from source (see the main README) with that library installed, but not in the .exe.

## The picture as an array

```python
import numpy as np


def register(api):
    def report():
        rgb = api.image(512)  # height x width x 3, uint8, long side at most 512
        if rgb is None:
            api.notify("Open a photo first")
            return
        warm = float(rgb[:, :, 0].mean() - rgb[:, :, 2].mean())
        api.message(f"Red is {warm:+.1f} above blue on average")

    api.add_menu_item("Warmth", report)
```

`api.image()` returns a copy; changing it changes nothing. To change the photo use `api.set_edit`.

## Your own Qt widgets

`module.add_widget(widget)` puts a PyQt6 widget in a module (see [UI and modules](ui-and-modules.md#your-own-qt-widgets-python)). You may also open your own windows (a `QDialog`): keep a reference to it so it is not collected, and close it in `unregister`.

## Rules for Python plugins

- **Never block.** A Python plugin runs on EFAS's main thread. A `while True:` loop, a long calculation or `time.sleep(5)` in a callback freezes the whole editor until it finishes, and EFAS cannot stop it. Do long work in small pieces with `api.after`, or in a `threading.Thread` of your own (see below).
- **Threads:** a thread of your own may call `api.log(...)` and nothing else from the API. To change anything in the editor from a thread, store the result and let a timer started with `api.every` pick it up on the main thread.
- **Errors are caught.** An exception in `register` shows the plugin as *error* in Settings and writes the traceback to the Plugin Output window (turn on **Everything** in its level box to see the traceback lines). An exception in a callback is written there too and nothing else is affected. `SystemExit` is caught as well.
- **Python plugins are not sandboxed.** They can read and write any file you can, start programs and use the internet. Only switch on Python plugins you trust. See [Security](security.md).

## Using a thread

```python
import threading


def register(api):
    result = {}

    def work():
        total = sum(i * i for i in range(2_000_000))
        result["total"] = total
        api.log("The thread finished")  # log is the one call that is safe from a thread

    def check():
        if "total" in result:
            api.cancel(timer)
            api.message(f"Total: {result['total']}")

    threading.Thread(target=work, daemon=True).start()
    timer = api.every(200, check)
```

## Testing a plugin without EFAS

Everything a plugin does goes through `api`, so the logic can be tested with a stand-in object. Keep the logic in functions that take `api` as an argument (like `build_report(api)` in the Photo Report example) and test them with a small class that has the methods you use.
