import sys


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-psn")]
    if args and args[0] == "--startup-screen":     # a packaged program starts its startup screen with its own executable (see startup_screen.py)
        from .splash_process import main as splash_main

        sys.exit(splash_main(args[1:]))
    if args:
        from . import cli

        sys.exit(cli.main(sys.argv[1:]))
    # the startup screen comes first and runs in a process of its own: the imports below take several seconds, and it plays all through them
    from . import startup_screen
    from .features.settings import logic as settings

    splash = startup_screen.launch(settings.load())

    from PyQt6 import sip
    from PyQt6.QtWidgets import QApplication

    from .desktop.view.app_icon import APP_NAME, app_icon
    from .desktop.view.app_window import AppWindow
    from .theme import runtime as theme_runtime

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
    startup_screen.dismiss(splash)     # the screen finishes its sequence and fades away
    exit_code = app.exec()
    sip.delete(window)
    sip.delete(app)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
