"""The plugins' output: everything they print or log, and every error they raise, kept in order for the View > Plugin Output window. Thread-safe (a plugin may log
from its own thread); no Qt - listeners are plain functions."""
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

LEVELS = ("debug", "info", "warn", "error")
MAX_RECORDS = 5000
SYSTEM = "EFAS"  # the "plugin" name for the manager's own messages (loading, errors it caught)


@dataclass(frozen=True)
class Record:
    time: datetime
    plugin: str  # the plugin's name, or SYSTEM
    level: str
    text: str

    def line(self) -> str:
        return f"{self.time:%H:%M:%S}  {self.level.upper():<5}  [{self.plugin}] {self.text}"


def level_rank(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else 1


class Logbook:
    def __init__(self, limit: int = MAX_RECORDS):
        self._records: deque[Record] = deque(maxlen=limit)
        self._lock = threading.Lock()
        self._listeners: list = []

    def add(self, plugin: str, level: str, text: str) -> Record:
        level = level if level in LEVELS else "info"
        record = Record(datetime.now(), plugin, level, str(text))
        with self._lock:
            self._records.append(record)
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(record)
            except Exception:
                pass  # a broken listener must never stop a plugin logging
        return record

    def records(self, plugin: str | None = None, minimum: str = "debug") -> list[Record]:
        floor = level_rank(minimum)
        with self._lock:
            return [r for r in self._records if (plugin is None or r.plugin == plugin) and level_rank(r.level) >= floor]

    def plugins(self) -> list[str]:
        with self._lock:
            return sorted({r.plugin for r in self._records}, key=str.lower)

    def subscribe(self, listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def error_count(self) -> int:
        with self._lock:
            return sum(1 for r in self._records if r.level == "error")
