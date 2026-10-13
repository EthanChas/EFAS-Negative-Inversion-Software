# Plugin Output and debugging

**View > Plugin Output** opens a window that shows everything the plugins print or log, and the errors EFAS catches in them. Tick it to open the window, untick it (or close the window) to close it. It stays open beside the editor while you work.

The window keeps the last 5,000 lines, even while it is closed.

## What a line looks like

```
20:05:45  INFO   [Hello (Lua)] Hello from Hello (Lua) (EFAS 0.7.0)
20:06:02  ERROR  [Exposure Steps (Lua)] button 'Darker (-1/3 EV)': main.lua:21: attempt to perform arithmetic on a nil value (field 'exposure_ev')
```

The time, the level, the plugin's name in square brackets, and the text. Lines from EFAS itself (a plugin loading or failing to load) say `[EFAS]`.

## Levels

| Level | Written by | Colour |
|---|---|---|
| `debug` | `debug(...)`, and the long technical trace behind an error | grey |
| `info` | `info(...)`, `log(...)`, Lua `print`, EFAS's own "Loading..." lines | normal |
| `warn` | `warn(...)` | amber |
| `error` | `error(...)`, and every error EFAS catches in a plugin | red |

## The controls

- **Show**: all plugins, or one. The list holds the plugins that have written something.
- The level box hides the less important lines. It starts at *Info and up*; choose **Everything** to see debug lines, including the full traceback of a Python error.
- **Follow new output** keeps the newest line in view. Untick it to read in peace.
- **Copy** puts the lines now shown on the clipboard; **Save...** writes them to a text file; **Clear** forgets all output.

## What gets caught

A plugin can make mistakes in many places, and none of them can bring EFAS down:

| Where | What you see |
|---|---|
| Loading (syntax error, `register` missing, an exception) | The plugin is shown as *error* in Settings > Plugins. The Plugin Output window has `[EFAS] <name> could not be loaded: <reason>`, with the file and line for Lua, and the traceback at debug level for Python. Whatever the plugin had already added is removed. |
| A button, slider, menu item, timer or event callback | `[<name>] <what it was>: <reason>`. The rest of the plugin carries on. |
| A wrong call to the API (a bad argument, an unknown name) | The same line; the reason says what to change. |
| A Lua callback that runs for more than 3 seconds | "the plugin ran for too long in one go and was stopped". |

What cannot be caught: a Python plugin that never returns (an endless loop), or one that crashes the whole Python interpreter. EFAS freezes or closes. Remove the plugin's folder from the plugins folder (or move it to `_old`) to recover.

## Debugging tips

1. Put `print` / `api.info` lines in your callbacks and watch the window while you click.
2. Turn the level to **Everything** to see tracebacks.
3. After editing, use **Plugins > Reload Plugins**. Reloading clears the plugin's menu items and modules and starts it fresh, but keeps the Plugin Output window's lines.
4. If a plugin is *error* in Settings, hover its name for the folder, and read the red line under it.
5. In a Lua plugin, a message ending `(a nil value)` almost always means a name was spelled wrong, or a function returned nothing because there was no photo open.
