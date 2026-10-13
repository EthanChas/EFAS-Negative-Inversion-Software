"""The Lua flavour of the plugin API: builds the `efas` table a Lua plugin sees, over the same PluginCore a Python plugin gets.

Lua calls efas.something(...) -> call("something", ...) here -> PluginCore.something(...). A single table argument to the functions that take keyword arguments is
spread into keywords, so Lua reads naturally: efas.add_module{title = "Hi"}, mod:add_slider{label = "Amount", min = 0, max = 1, on_change = function(v) ... end}.
Modules and widgets are Lua objects (use `:`); everything the Lua side may call is on an allow-list in api.py, nothing else on the Python side is reachable."""
from .api import (
    FUNCTIONS, KEYWORD_FUNCTIONS, KEYWORD_METHODS, MODULE_METHODS, MODULE_WIDGET_METHODS, WIDGET_METHODS, MenuItem, ModuleHandle, PluginCore, PluginError, WidgetHandle,
)
from .lua_sandbox import LuaSandbox

_PRELUDE = r"""
local call, callh, funcs, module_methods, widget_makers, widget_methods, info = ...
local efas = {}
for key, value in pairs(info) do efas[key] = value end
for _, name in ipairs(funcs) do
    efas[name] = function(...) return call(name, ...) end
end

local Module, Widget = {}, {}
Module.__index, Widget.__index = Module, Widget
local function wrap(mt, handle)
    if handle == nil then return nil end
    return setmetatable({ _h = handle }, mt)
end
efas.add_module = function(...) return wrap(Module, call("add_module", ...)) end
for _, name in ipairs(module_methods) do
    local makes_widget = widget_makers[name]
    Module[name] = function(self, ...)
        local result = callh(self._h, name, ...)
        if makes_widget then return wrap(Widget, result) end
        return result
    end
end
for _, name in ipairs(widget_methods) do
    Widget[name] = function(self, ...) return callh(self._h, name, ...) end
end
return efas
"""


class LuaBridge:
    def __init__(self, core: PluginCore, sandbox: LuaSandbox):
        self._core, self._sb = core, sandbox
        core._is_lua_function = sandbox.is_function
        core._lua_call = lambda fn, *args: sandbox.call(fn, *[sandbox.to_lua(a) for a in args])
        info = {
            "api_version": core.api_version, "version": core.app_version, "plugin_id": core.plugin_id, "plugin_name": core.plugin_name,
            "plugin_dir": core.plugin_dir, "data_dir": core.data_dir, "language": "lua",
        }
        build = sandbox.lua.eval("function(...) local f = load(...) return f end")
        makers = sandbox.lua.table_from({name: True for name in MODULE_WIDGET_METHODS})
        chunk = build(_PRELUDE, "=efas-prelude", "t", sandbox.lua.globals())
        table = chunk(
            self._call, self._call_handle, sandbox.lua.table_from(list(FUNCTIONS)), sandbox.lua.table_from(list(MODULE_METHODS)), makers,
            sandbox.lua.table_from(list(WIDGET_METHODS)), sandbox.to_lua(info),
        )
        sandbox.set_global("efas", table)

    # ------------------------------------------------------------ the two entry points the Lua side calls
    def _call(self, name, *args):
        if name not in FUNCTIONS:
            raise PluginError(f"There is no function efas.{name}.")
        return self._invoke(getattr(self._core, name), name in KEYWORD_FUNCTIONS, args)

    def _call_handle(self, handle, method, *args):
        if isinstance(handle, ModuleHandle):
            allowed = MODULE_METHODS
        elif isinstance(handle, WidgetHandle):
            allowed = WIDGET_METHODS
        else:
            raise PluginError("That is not a module or a control.")
        if method not in allowed:
            raise PluginError(f"There is no method '{method}' here.")
        return self._invoke(getattr(handle, method), method in KEYWORD_METHODS, args)

    def _invoke(self, fn, keyword: bool, args):
        converted = [self._sb.to_python(a) for a in args]
        if keyword and len(converted) == 1 and isinstance(converted[0], dict):
            kwargs = {k: v for k, v in converted[0].items() if isinstance(k, str)}
            result = fn(**kwargs)
        else:
            result = fn(*converted)
        if isinstance(result, (ModuleHandle, WidgetHandle)):
            return result
        if isinstance(result, MenuItem):
            return None  # a Lua plugin has no use for it, and Python objects stay out of Lua
        return self._sb.to_lua(result)
