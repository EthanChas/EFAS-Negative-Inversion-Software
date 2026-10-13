import sys

from PyQt6 import sip
from PyQt6.QtWidgets import QApplication

from . import cli
from .desktop.view.app_icon import APP_NAME, app_icon
from .desktop.view.app_window import AppWindow
from .theme import runtime as theme_runtime


def main() -> None:
    if [a for a in sys.argv[1:] if not a.startswith("-psn")]:
        sys.exit(cli.main(sys.argv[1:]))
    from . import __version__
    from .features.support import applog

    applog.install(__version__)
    from .features import datadir

    if datadir.last_move:
        applog.logger().info("Moved the old data folder: %s", {k: v for k, v in datadir.last_move.items() if k != "copied"})
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EFAS.NegativeInversionSoftware")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    theme_runtime.apply(app)  # the saved theme (Settings > Themes): colours, font, stylesheet

    window = AppWindow()
    window.controller.daily_backup()
    window.showMaximized()
    window.restore_session()
    exit_code = app.exec()
    sip.delete(window)
    sip.delete(app)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
