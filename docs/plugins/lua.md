# Lua plugins

EFAS has Lua 5.4 built in (through the `lupa` library), so a Lua plugin needs nothing installed. A Lua plugin is a `plugin.json` plus a `main.lua`. EFAS runs `main.lua` once when the plugin is switched on; the file builds the plugin's menu items and modules and registers its callbacks, then finishes. The callbacks run later, when the user clicks or an event happens.

Every plugin has its own Lua world: two Lua plugins cannot see each other's variables.

## The `efas` table

`efas` is a global table holding the whole [API](api-reference.md). Call functions with a dot, and methods of modules and controls with a colon:

```lua
efas.notify("hello")                                -- a function: dot
local module = efas.add_module{ title = "Tool" }    -- the braces pass named values
module:add_label{ text = "hi" }                     -- a method of the module: colon
```

Functions that take several optional settings take **one table** with the names (`efas.add_module{ title = "Tool", tab = "exposure" }`). The [API reference](api-reference.md) marks these. Functions with one or two plain arguments take them in order (`efas.notify("hi")`, `efas.settings_set("count", 3)`).

## What Lua can use

The whole core language and these libraries:

| Library | Notes |
|---|---|
| `string`, `table`, `math`, `utf8`, `coroutine` | All of them, except `string.dump` (compiled code is not allowed) |
| `os` | Only `os.time`, `os.date` and `os.clock` |
| `print` | Writes an `info` line to the Plugin Output window |
| `require` | Loads another `.lua` file **from the plugin's own folder**: `require("helpers")` loads `helpers.lua`, `require("util.math")` loads `util/math.lua` |
| `load` | Compiles a string of Lua text (not compiled code) |
| `pcall`, `error`, `assert`, `select`, `pairs`, `ipairs`, `tostring`, `tonumber`, `type`, `setmetatable`... | The ordinary base functions |

Not available: `io`, `package`, `dofile`, `loadfile`, `debug`, `collectgarbage`, `os.execute` and the rest of `os`, and any way to reach Python. A Lua plugin cannot touch files other than through `efas.read_text` / `efas.write_text` (see [Security](security.md)).

## Time limit

A single run of your code (loading the plugin, a button callback, a timer, an event) may use **3 seconds of processor time**. After that EFAS stops it with the error "the plugin ran for too long in one go and was stopped", and writes it to the Plugin Output window. The limit exists so a loop that never ends (`while true do end`) cannot freeze the editor. If a job really is long, split it into pieces and continue with `efas.after`:

```lua
local items = efas.photos()
local index = 1

local function step()
    local path = items[index]
    if not path then
        efas.notify("Finished")
        return
    end
    print("Looking at " .. path)
    index = index + 1
    efas.after(10, step)       -- come back soon; the editor stays responsive in between
end

step()
```

## Values

| Lua | Becomes in the API | Notes |
|---|---|---|
| number, string, boolean, `nil` | the same | |
| a table that is a list (`{1, 2, 3}`) | a list | keys must be exactly 1 to n |
| any other table (`{a = 1}`) | a dictionary | |
| a function | a callback | |

Tables coming back from the API (`efas.photo()`, `efas.statistics()`) are ordinary Lua tables: `efas.photo().name`. Lists (`efas.presets()`, `efas.photos()`) work with `ipairs` and `#`.

## Errors

- A syntax error or a runtime error while the plugin loads: the plugin shows as **error** in Settings > Plugins, the message (with the file and line, like `main.lua:12: attempt to ...`) is in the Plugin Output window, and nothing the plugin had added stays.
- An error inside a callback: written to the Plugin Output window, the callback is skipped, everything else carries on.
- Use `pcall` yourself if you want to handle an error:

```lua
local ok, problem = pcall(function() efas.set_edit{ exposure_ev = 99 } end)
if not ok then print("Could not set it: " .. tostring(problem)) end
```

## Splitting a plugin into files

```lua
-- helpers.lua
local M = {}

function M.clamp(value, low, high)
    return math.max(low, math.min(high, value))
end

return M
```

```lua
-- main.lua
local helpers = require("helpers")
efas.notify("Clamped: " .. helpers.clamp(5, 0, 1))
```

## Saving things

```lua
local runs = efas.settings_get("runs", 0) + 1
efas.settings_set("runs", runs)
print("This plugin has been switched on " .. runs .. " times")
```

Settings are saved at once, in `plugin-data/<id>/settings.json`.
