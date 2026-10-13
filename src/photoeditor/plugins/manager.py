"""Finding, loading, running and unloading plugins.

Plugins live in the plugins folder (inside the data folder), one folder each with a plugin.json and its program. Every plugin starts switched OFF: turning one on
(Settings > Plugins) is the user's decision, and is remembered. A plugin that fails to load, or whose callbacks raise, is reported in the Plugin Output window with its
name and the program carries on: nothing a plugin does inside its own code can stop EFAS (a Python plugin that crashes the interpreter or never returns is the one
thing that can; see docs/plugins/security.md)."""
import importlib.util
import os
import sys
import traceback
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..features.datadir import PLUGIN_DATA_DIR, PLUGINS_DIR, app_data_dir
from .api import EVENTS, MIN_TIMER_MS, PluginCore, PluginError
from .logbook import SYSTEM, Logbook
from .manifest import Found, discover

MAX_TIMERS = 50
STATE_DISABLED, STATE_LOADED, STATE_ERROR, STATE_INVALID = "disabled", "loaded", "error", "invalid"


@dataclass
class Entry:
    """One plugin folder, as the Plugins page lists it."""
    found: Found
    enabled: bool = False
    state: str = STATE_DISABLED
    error: str = ""
    core: PluginCore | None = field(default=None, repr=False)
    module: object = field(default=None, repr=False)
    sandbox: object = field(default=None, repr=False)
    imported: list = field(default_factory=list, repr=False)  # the modules a Python plugin imported, forgotten when it is unloaded

    @property
    def id(self) -> str:
        return self.found.manifest.id if self.found.manifest else os.path.basename(self.found.folder)

    @property
    def name(self) -> str:
        return self.found.manifest.name if self.found.manifest else os.path.basename(self.found.folder)


class SettingsStore:
    """Which plugins are switched on, kept in the program's settings file (key plugins_enabled: {plugin id: true})."""

    def get(self) -> dict:
        from ..features.settings import logic as settings

        return dict(settings.get("plugins_enabled"))

    def set(self, enabled: dict) -> None:
        from ..features.settings import logic as settings

        settings.save({"plugins_enabled": {k: bool(v) for k, v in enabled.items()}})


class PluginManager(QObject):
    plugins_changed = pyqtSignal()
    record_added = pyqtSignal(object)  # a logbook Record, emitted on the main thread however it was logged

    def __init__(self, host, version: str, plugins_dir: str | None = None, data_root: str | None = None, store=None, parent: QObject | None = None):
        super().__init__(parent)
        self.host = host
        self.version = version
        self._plugins_dir = plugins_dir
        self._data_root = data_root
        self._store = store or SettingsStore()
        self.logbook = Logbook()
        self.logbook.subscribe(self.record_added.emit)
        self._entries: list[Entry] = []

    # ------------------------------------------------------------ places
    def folder(self) -> str:
        return self._plugins_dir or os.path.join(app_data_dir(), PLUGINS_DIR)

    def data_dir_for(self, plugin_id: str) -> str:
        return os.path.join(self._data_root or os.path.join(app_data_dir(), PLUGIN_DATA_DIR), plugin_id)

    def log(self, level: str, text: str, plugin: str = SYSTEM) -> None:
        self.logbook.add(plugin, level, text)

    # ------------------------------------------------------------ the list
    def entries(self) -> list[Entry]:
        return list(self._entries)

    def entry(self, plugin_id: str) -> Entry | None:
        return next((e for e in self._entries if e.id == plugin_id), None)

    def refresh(self) -> list[Entry]:
        """Look in the plugins folder again: new folders appear, removed ones go (their plugin is unloaded); loaded plugins stay as they are."""
        os.makedirs(self.folder(), exist_ok=True)
        enabled = self._store.get()
        previous = {e.found.folder: e for e in self._entries}
        fresh: list[Entry] = []
        for found in discover(self.folder()):
            old = previous.pop(found.folder, None)
            if old is not None and old.found.manifest == found.manifest:
                old.found = found
                fresh.append(old)
                continue
            if old is not None:
                self._unload(old)
            entry = Entry(found)
            if found.manifest is None:
                entry.state, entry.error = STATE_INVALID, found.error
            else:
                entry.enabled = bool(enabled.get(found.manifest.id))
            fresh.append(entry)
        for gone in previous.values():
            self._unload(gone)
        self._entries = fresh
        self.plugins_changed.emit()
        return list(fresh)

    # ------------------------------------------------------------ on and off
    def load_enabled(self) -> None:
        """At start: find the plugins and load the ones that are switched on."""
        self.refresh()
        for entry in self._entries:
            if entry.enabled and entry.state == STATE_DISABLED:
                self._load(entry)
        self.plugins_changed.emit()

    def set_enabled(self, plugin_id: str, on: bool) -> None:
        entry = self.entry(plugin_id)
        if entry is None or entry.found.manifest is None:
            return
        entry.enabled = bool(on)
        enabled = self._store.get()
        enabled[plugin_id] = bool(on)
        self._store.set(enabled)
        if on:
            if entry.state != STATE_LOADED:
                self._load(entry)
        else:
            self._unload(entry)
            entry.state, entry.error = STATE_DISABLED, ""
        self.plugins_changed.emit()

    def reload_all(self) -> None:
        """Unload everything and load the switched-on plugins again (after editing a plugin)."""
        for entry in self._entries:
            self._unload(entry)
            if entry.found.manifest is not None:
                entry.state, entry.error = STATE_DISABLED, ""
        self.load_enabled()

    def shutdown(self) -> None:
        for entry in self._entries:
            self._unload(entry)

    # ------------------------------------------------------------ loading
    def _load(self, entry: Entry) -> None:
        manifest = entry.found.manifest
        entry.error = ""
        core = PluginCore(self, manifest, self.host, self.data_dir_for(manifest.id), self.version)
        entry.core = core
        self.log("info", f"Loading {manifest.name} {manifest.version} ({manifest.language})")
        try:
            if manifest.language == "python":
                self._load_python(entry, core)
            else:
                self._load_lua(entry, core)
        except BaseException as exc:  # a plugin's own mistakes, including SystemExit
            if isinstance(exc, KeyboardInterrupt):
                raise
            entry.state, entry.error = STATE_ERROR, _short(exc)
            self.log("error", f"{manifest.name} could not be loaded: {_short(exc)}")
            self.log("debug", _trace(exc), manifest.name)
            self._unload(entry, keep_state=True)
            return
        entry.state = STATE_LOADED

    def _load_python(self, entry: Entry, core: PluginCore) -> None:
        manifest = entry.found.manifest
        name = "efas_plugin_" + "".join(c if c.isalnum() else "_" for c in manifest.id)
        spec = importlib.util.spec_from_file_location(name, manifest.entry_path)
        module = importlib.util.module_from_spec(spec)
        before = set(sys.modules)
        sys.modules[name] = module
        sys.path.insert(0, manifest.folder)
        try:
            # compiled from the source each time: a cached .pyc is trusted by size and second, so a quick same-size edit would otherwise reload the old code
            with open(manifest.entry_path, "r", encoding="utf-8") as fh:
                source = fh.read()
            module.__file__ = manifest.entry_path
            exec(compile(source, manifest.entry_path, "exec"), module.__dict__)
            register = getattr(module, "register", None)
            if not callable(register):
                raise PluginError("The plugin must define register(api).")
            entry.module = module
            register(core)
        finally:
            try:
                sys.path.remove(manifest.folder)
            except ValueError:
                pass
            entry.imported = [m for m in set(sys.modules) - before if m != name]

    def _load_lua(self, entry: Entry, core: PluginCore) -> None:
        from .lua_bridge import LuaBridge
        from .lua_sandbox import LuaSandbox

        manifest = entry.found.manifest
        sandbox = LuaSandbox(lambda level, text: self.logbook.add(manifest.name, level, text), manifest.folder)
        entry.sandbox = sandbox
        LuaBridge(core, sandbox)
        sandbox.run_file(manifest.entry_path)

    def _unload(self, entry: Entry, keep_state: bool = False) -> None:
        core, module = entry.core, entry.module
        if core is not None and module is not None:
            unregister = getattr(module, "unregister", None)
            if callable(unregister):
                try:
                    unregister()
                except Exception as exc:
                    self.log("warn", f"{entry.name}: unregister() failed: {_short(exc)}")
        if core is not None:
            core._cleanup()
        if entry.found.manifest is not None and entry.found.manifest.language == "python" and module is not None:
            name = getattr(module, "__name__", "")
            sys.modules.pop(name, None)
            for imported in entry.imported:
                sys.modules.pop(imported, None)
        entry.core = entry.module = entry.sandbox = None
        entry.imported = []
        if not keep_state and entry.state == STATE_LOADED:
            self.log("info", f"Unloaded {entry.name}")
            entry.state = STATE_DISABLED

    # ------------------------------------------------------------ running plugin code safely
    def safe_call(self, plugin_id: str, fn, *args, what: str = "callback", lua=None):
        """Run a plugin's function; any error is logged (with the plugin's name) instead of raised. Returns the result, or None after an error."""
        try:
            return lua(fn, *args) if lua is not None else fn(*args)
        except (Exception, SystemExit) as exc:  # a plugin calling sys.exit() must not close EFAS
            entry = self.entry(plugin_id)
            name = entry.name if entry else plugin_id
            self.log("error", f"{what}: {_short(exc)}", name)
            self.log("debug", _trace(exc), name)
            return None

    def emit(self, event: str, payload: dict | None = None) -> None:
        """Tell every loaded plugin that listens for `event` (payload is a dict of plain values)."""
        if event not in EVENTS:
            return
        for entry in list(self._entries):
            core = entry.core
            if core is None or entry.state != STATE_LOADED:
                continue
            for _sub, callback in core._dispatch(event, payload or {}):
                self.safe_call(entry.id, callback, dict(payload or {}), what=f"on '{event}'", lua=core._lua_call if core._is_lua_function(callback) else None)

    # ------------------------------------------------------------ timers
    def start_timer(self, core: PluginCore, milliseconds: float, callback, repeat: bool) -> int:
        if len(core._timers) >= MAX_TIMERS:
            raise PluginError(f"A plugin may have {MAX_TIMERS} timers at most.")
        timer = QTimer(self)
        timer.setSingleShot(not repeat)
        timer.setInterval(int(max(MIN_TIMER_MS, milliseconds)))
        timer_id = core._id()
        lua = core._lua_call if core._is_lua_function(callback) else None

        def fire() -> None:
            self.safe_call(core.plugin_id, callback, what="timer", lua=lua)
            if not repeat:
                core._timers.pop(timer_id, None)
                timer.deleteLater()

        timer.timeout.connect(fire)
        core._timers[timer_id] = timer
        timer.start()
        return timer_id

    def stop_timer(self, core: PluginCore, timer_id) -> None:
        timer = core._timers.pop(timer_id, None)
        if timer is not None:
            self.discard_timer(timer)

    @staticmethod
    def discard_timer(timer) -> None:
        timer.stop()
        timer.deleteLater()


def _short(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text if len(text) < 600 else text[:600] + "..."


def _trace(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-2500:]
