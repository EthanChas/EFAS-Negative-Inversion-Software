"""A small log file of what the app itself reports (start-up, and any error that would otherwise vanish in a window with no console), kept in the data folder.

It never records photo contents or edit values. Errors name the file they happened on, and the problem report strips folders from those before it is shared.
"""

import logging
import logging.handlers
import os
import sys
import threading

from ..datadir import app_data_dir

LOG_NAME = "efas.log"
MAX_BYTES = 400_000
BACKUPS = 2
_handler: logging.Handler | None = None
_old_hooks: tuple | None = None


def log_dir() -> str:
    return os.path.join(app_data_dir(), "logs")


def log_path() -> str:
    return os.path.join(log_dir(), LOG_NAME)


def logger() -> logging.Logger:
    return logging.getLogger("photoeditor")


def install(version: str = "") -> bool:
    """Start logging to the file, and record uncaught errors (in any thread) before passing them on. Safe to call twice; False if the file cannot be opened."""
    global _handler, _old_hooks
    if _handler is not None:
        return True
    try:
        os.makedirs(log_dir(), exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(log_path(), maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    except OSError:
        return False
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
    log = logger()
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    _handler = handler
    _old_hooks = (sys.excepthook, threading.excepthook)

    def on_error(exc_type, exc, tb):
        log.error("Uncaught error", exc_info=(exc_type, exc, tb))
        _old_hooks[0](exc_type, exc, tb)

    def on_thread_error(args):
        log.error("Uncaught error in thread %s", getattr(args.thread, "name", "?"), exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        _old_hooks[1](args)

    sys.excepthook = on_error
    threading.excepthook = on_thread_error
    log.info("EFAS %s started on %s (Python %s)", version or "?", sys.platform, sys.version.split()[0])
    return True


def uninstall() -> None:
    """Stop logging and put the previous error hooks back (for tests)."""
    global _handler, _old_hooks
    if _handler is not None:
        logger().removeHandler(_handler)
        _handler.close()
        _handler = None
    if _old_hooks is not None:
        sys.excepthook, threading.excepthook = _old_hooks
        _old_hooks = None


def read_tail(max_lines: int = 200, max_bytes: int = 80_000) -> list[str]:
    """The last lines of the log (the current file first, then the older one if more is needed)."""
    lines: list[str] = []
    for name in (log_path(), log_path() + ".1"):
        try:
            with open(name, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - max_bytes))
                text = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        lines = text.splitlines() + lines
        if len(lines) >= max_lines:
            break
    return lines[-max_lines:]
