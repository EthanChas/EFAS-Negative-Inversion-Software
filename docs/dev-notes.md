# Photo Editor

A PyQt6 desktop photo editor. Currently: a main window with a File/Settings/
Extra/Info menu bar, where File > Import Images opens a separate window to
pick a folder and browse its photos as a tile grid.

## Run

```
pip install -e .
python -m photoeditor
```

## Layout

```
src/photoeditor/
  theme/            design tokens + generated QSS stylesheet
  features/browse/  pure folder-scanning logic + thumbnail generation
  desktop/          AppState + AppController + the view layer
    view/
      app_window.py     root window: menu bar, File -> Import Images
      import_window.py  folder picker + tile grid
```

`AppController` is the only thing the UI calls into; it owns `AppState` and
emits `folder_changed` when it updates. Thumbnails are generated on a
background `QThread` (`desktop/workers.py`) so opening a folder never blocks
the UI.
