"""A Lua 5.4 interpreter (the lupa package) shut into a box for one plugin.

What a Lua plugin can use: the language (string, table, math, utf8, coroutine, pcall, ...), os.time / os.date / os.clock, print (which writes to the Plugin
Output window), require (only other .lua files inside the plugin's own folder) and the `efas` table the program hands it. What it cannot: files (no io), running
programs (no os.execute), loading libraries (no package, no C modules), the debugger, compiled chunks (load takes text only, string.dump is gone) or Python
itself. A plugin that runs for too long in one call is stopped (a hook counts instructions; it also covers coroutines), so a loop that never ends cannot freeze
EFAS - best effort: it is a safety net, not a security boundary against someone determined (see docs/plugins/security.md)."""
import os
import re

from lupa.lua54 import LuaError, LuaRuntime, lua_type

CPU_SECONDS = 3.0
HOOK_EVERY = 100_000  # instructions between the time checks
_MODULE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")

_SETUP = r"""
local py_log, py_read_module, hook_every = ...
local clock, time, date = os.clock, os.time, os.date
local sethook, tostring, select, type, error, pcall = debug.sethook, tostring, select, type, error, pcall
local create, resume, unpack, pack = coroutine.create, coroutine.resume, table.unpack, table.pack

local deadline = nil
local function hook()
    if deadline and clock() > deadline then
        deadline = nil
        error("the plugin ran for too long in one go and was stopped", 0)
    end
end
sethook(hook, "", hook_every)
coroutine.create = function(f)
    local co = create(f)
    sethook(co, hook, "", hook_every)
    return co
end
coroutine.wrap = function(f)
    local co = coroutine.create(f)
    return function(...)
        local r = pack(resume(co, ...))
        if not r[1] then error(r[2], 0) end
        return unpack(r, 2, r.n)
    end
end

os = { clock = clock, time = time, date = date }
io, package, dofile, loadfile, debug, collectgarbage, python = nil, nil, nil, nil, nil, nil, nil
string.dump = nil

print = function(...)
    local parts = {}
    for i = 1, select("#", ...) do parts[i] = tostring((select(i, ...))) end
    py_log("info", table.concat(parts, "\t"))
end

local real_load = load
load = function(chunk, chunkname, mode, env)
    if type(chunk) ~= "string" then error("load() only takes a string of Lua text", 2) end
    return real_load(chunk, chunkname or "=(load)", "t", env or _G)
end

local loaded = {}
require = function(name)
    if loaded[name] ~= nil then return loaded[name] end
    local source, err = py_read_module(name)
    if not source then error(err or ("module '" .. tostring(name) .. "' was not found in the plugin's folder"), 2) end
    local fn, lerr = real_load(source, "@" .. name .. ".lua", "t", _G)
    if not fn then error(lerr, 0) end
    local result = fn(name)
    if result == nil then result = true end
    loaded[name] = result
    return result
end

return {
    enter = function(seconds) deadline = clock() + seconds end,
    leave = function() deadline = nil end,
}
"""


class LuaSandbox:
    """One plugin's Lua world. `log(level, text)` receives its print output; `folder` is where require may read from."""

    def __init__(self, log, folder: str, cpu_seconds: float = CPU_SECONDS):
        self._folder = os.path.realpath(folder)
        self._cpu = cpu_seconds
        self.lua = LuaRuntime(unpack_returned_tuples=True, register_eval=False, register_builtins=False, encoding="utf-8", attribute_filter=_attribute_filter)
        guard = self.lua.execute(_SETUP, log, self._read_module, HOOK_EVERY)
        self._enter, self._leave = guard["enter"], guard["leave"]

    # ------------------------------------------------------------ running Lua
    def run_file(self, path: str) -> None:
        """Run the plugin's program (its top level); raises LuaError with the Lua message and position if it fails."""
        with open(path, "r", encoding="utf-8-sig") as f:
            source = f.read()
        chunk = self.lua.eval("load")(source, "@" + os.path.basename(path), "t", self.lua.globals())
        if isinstance(chunk, tuple):  # (nil, message): a syntax error
            raise LuaError(str(chunk[1]))
        self.call(chunk)

    def call(self, fn, *args):
        """Call a Lua function with the time limit; raises LuaError on failure."""
        self._enter(self._cpu)
        try:
            return fn(*args)
        finally:
            self._leave()

    def set_global(self, name: str, value) -> None:
        self.lua.globals()[name] = value

    # ------------------------------------------------------------ require
    def _read_module(self, name):
        """Lua's require: the text of <plugin folder>/<name>.lua (dots are folders), or (nil, why)."""
        if not isinstance(name, str) or not _MODULE_NAME.match(name) or ".." in name:
            return None, f"bad module name '{name}'"
        relative = name.replace(".", "/") + ".lua"
        path = os.path.realpath(os.path.join(self._folder, relative))
        if os.path.commonpath([self._folder, path]) != self._folder:
            return None, f"module '{name}' is outside the plugin's folder"
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return f.read()
        except OSError:
            return None, f"module '{name}' was not found in the plugin's folder"

    # ------------------------------------------------------------ values
    def to_python(self, value):
        """A Lua value as Python: a table that is a list 1..n becomes a list, any other table a dict; functions stay Lua functions."""
        if lua_type(value) == "table":
            keys = list(value.keys())
            if keys and all(isinstance(k, int) and not isinstance(k, bool) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
                return [self.to_python(value[i]) for i in range(1, len(keys) + 1)]
            return {(k if isinstance(k, (str, int, float, bool)) else str(k)): self.to_python(v) for k, v in value.items()}
        return value

    def to_lua(self, value):
        """A Python value as Lua: dict -> table, list/tuple -> a 1..n table; the rest as it is."""
        if isinstance(value, dict):
            return self.lua.table_from({k: self.to_lua(v) for k, v in value.items()})
        if isinstance(value, (list, tuple)):
            return self.lua.table_from([self.to_lua(v) for v in value])
        return value

    def is_function(self, value) -> bool:
        return lua_type(value) == "function"


def _attribute_filter(obj, attr_name, is_setting):
    """Lua code may only touch a Python object's public names (never __dict__, __class__, ...)."""
    if not isinstance(attr_name, str) or attr_name.startswith("_"):
        raise AttributeError("access denied")
    return attr_name


__all__ = ["LuaSandbox", "LuaError", "CPU_SECONDS"]
