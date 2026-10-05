"""Entry point for the packaged .exe (PyInstaller can't run a package's __main__ with relative imports directly)."""

from photoeditor.__main__ import main

if __name__ == "__main__":
    main()
