import json

from PyQt6.QtCore import QSettings, QStandardPaths, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...features.export import logic as X
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel
from .slider_row import SliderRow

_LABEL_WIDTH = 80
_GLOBAL_KEY = "export/options"
_PRESETS_KEY = "export/presets"
_SELECTED_KEY = "export/selected"  # name of the preset the controls were last editing
_DEFAULT_CHECKED = "High quality JPEG (full size)"


def _default_folder() -> str:
    pictures = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    return (pictures or "") + "/PhotoEditor Export"


def describe(o: X.ExportOptions) -> str:
    """A one-line summary of a preset: format, quality/compression, size."""
    if o.fmt == "jpeg":
        fmt = f"JPEG {o.jpeg_quality}%"
    elif o.fmt == "webp":
        fmt = "WebP lossless" if o.webp_lossless else f"WebP {o.webp_quality}%"
    elif o.fmt == "tiff":
        fmt = f"TIFF {X.TIFF_LABELS.get(o.tiff_compression, o.tiff_compression)}"
    else:
        fmt = f"PNG level {o.png_compress}"
    size = {
        "original": "full size",
        "long_edge": f"{o.long_edge} px long edge",
        "percent": f"{o.percent:.0f}%",
        "fit": f"fit {o.fit_w}×{o.fit_h}",
    }[o.size_mode]
    return f"{fmt}, {size}" + (", grayscale" if o.grayscale else "")


class ExportPanel(CollapsiblePanel):
    """Export section under History, in the spirit of darktable's export
    module and NegPy's export presets.

    Presets are named sets of format + encoder settings (a quality slider for
    JPEG/WebP, TIFF compression...) + size. Tick any number of them and one
    click exports every photo in the chosen scope once per ticked preset -
    JPEG and TIFF together, say - so a batch of keepers can go out in several
    formats at once. The controls below the list edit the highlighted preset
    (saved as you change them); the destination and filename settings are
    shared by every preset. With nothing ticked, Export uses the highlighted
    preset's settings as they are. Everything persists between sessions."""

    export_requested = pyqtSignal(str, object)  # scope, [(preset name, ExportOptions)]
    cancel_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Export",
            help_text=(
                "Exports photos at their full original resolution with all their saved edits applied.\n\n"
                "Presets: tick the ones to export - each ticked preset writes its own file per photo "
                "(e.g. JPEG and TIFF). Click a preset's name to edit its format, quality and size; "
                "changes save automatically. New / Rename / Delete manage the list.\n\n"
                "Files keep the original photo's name by default. Add a Suffix to a preset or turn on "
                "'Folder per preset' to keep presets that share a format apart.\n\n"
                "Choose a scope - the current image, the keepers (K) in the filmstrip folder, and so on - "
                "then click Export."
            ),
            collapsible=True,
            start_expanded=False,
            parent=parent,
        )
        self.setMinimumWidth(220)
        body = self.body()
        body.setSpacing(THEME.space_sm)
        self._loading = True
        self._presets: list[dict] = []
        self._current = -1

        # ---- presets ----
        body.addWidget(self._section("PRESETS (tick to export)"))
        self._preset_list = QListWidget()
        self._preset_list.setMaximumHeight(150)
        self._preset_list.setToolTip("Tick the presets to export. Click a name to edit its settings below.")
        self._preset_list.itemChanged.connect(self._on_preset_checked)
        self._preset_list.currentRowChanged.connect(self._on_preset_selected)
        body.addWidget(self._preset_list)
        preset_buttons = QHBoxLayout()
        preset_buttons.setSpacing(THEME.space_sm)
        for text, slot, tip in (
            ("New...", self._on_new_preset, "Save the current settings as a new preset."),
            ("Rename", self._on_rename_preset, "Rename the highlighted preset."),
            ("Delete", self._on_delete_preset, "Remove the highlighted preset."),
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            preset_buttons.addWidget(button)
        body.addLayout(preset_buttons)

        # ---- format ----
        body.addWidget(self._section("FORMAT"))
        self._format = QComboBox()
        for fmt in X.FORMATS:
            self._format.addItem(X.FORMAT_LABELS[fmt], fmt)
        self._format.currentIndexChanged.connect(self._on_changed)
        body.addLayout(self._row("Format", self._format))

        self._jpeg_box = QWidget()
        jv = QVBoxLayout(self._jpeg_box)
        jv.setContentsMargins(0, 0, 0, 0)
        jv.setSpacing(THEME.space_sm)
        self._jpeg_quality = SliderRow("Quality", min_value=1, max_value=100, reset_value=90, decimals=0, step=1)
        self._jpeg_quality.set_value(90)
        self._jpeg_quality.value_changed.connect(self._on_changed)
        self._jpeg_quality.setToolTip("JPEG quality: higher is larger and cleaner. 90-95 is visually lossless for most photos.")
        jv.addWidget(self._jpeg_quality)
        self._jpeg_sub = QComboBox()
        for key, label in X.JPEG_SUBSAMPLING_LABELS.items():
            self._jpeg_sub.addItem(label, key)
        self._jpeg_sub.currentIndexChanged.connect(self._on_changed)
        jv.addLayout(self._row("Chroma", self._jpeg_sub))
        self._jpeg_progressive = QCheckBox("Progressive")
        self._jpeg_progressive.toggled.connect(self._on_changed)
        jv.addWidget(self._jpeg_progressive)
        body.addWidget(self._jpeg_box)

        self._png_box = QWidget()
        pv = QVBoxLayout(self._png_box)
        pv.setContentsMargins(0, 0, 0, 0)
        self._png_compress = SliderRow("Compression", min_value=0, max_value=9, reset_value=6, decimals=0, step=1)
        self._png_compress.set_value(6)
        self._png_compress.value_changed.connect(self._on_changed)
        self._png_compress.setToolTip("PNG is always lossless; higher compression is just slower and smaller.")
        pv.addWidget(self._png_compress)
        body.addWidget(self._png_box)

        self._tiff_box = QWidget()
        tv = QVBoxLayout(self._tiff_box)
        tv.setContentsMargins(0, 0, 0, 0)
        self._tiff_comp = QComboBox()
        for key, label in X.TIFF_LABELS.items():
            self._tiff_comp.addItem(label, key)
        self._tiff_comp.currentIndexChanged.connect(self._on_changed)
        tv.addLayout(self._row("Compression", self._tiff_comp))
        body.addWidget(self._tiff_box)

        self._webp_box = QWidget()
        wv = QVBoxLayout(self._webp_box)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(THEME.space_sm)
        self._webp_quality = SliderRow("Quality", min_value=1, max_value=100, reset_value=90, decimals=0, step=1)
        self._webp_quality.set_value(90)
        self._webp_quality.value_changed.connect(self._on_changed)
        wv.addWidget(self._webp_quality)
        self._webp_lossless = QCheckBox("Lossless")
        self._webp_lossless.toggled.connect(self._on_changed)
        wv.addWidget(self._webp_lossless)
        self._webp_method = SliderRow("Effort", min_value=0, max_value=6, reset_value=4, decimals=0, step=1)
        self._webp_method.set_value(4)
        self._webp_method.value_changed.connect(self._on_changed)
        self._webp_method.setToolTip("Higher effort is slower and gives smaller files.")
        wv.addWidget(self._webp_method)
        body.addWidget(self._webp_box)

        self._suffix = QLineEdit()
        self._suffix.setPlaceholderText("(none)")
        self._suffix.setToolTip("Added to the file name for this preset, e.g. _web. Keeps two presets of one format apart.")
        self._suffix.textChanged.connect(self._on_changed)
        body.addLayout(self._row("Suffix", self._suffix))

        # ---- size ----
        body.addWidget(self._section("SIZE"))
        self._size_mode = QComboBox()
        for mode in X.SIZE_MODES:
            self._size_mode.addItem(X.SIZE_MODE_LABELS[mode], mode)
        self._size_mode.currentIndexChanged.connect(self._on_changed)
        body.addLayout(self._row("Size", self._size_mode))

        self._long_edge = QSpinBox()
        self._long_edge.setRange(16, 20000)
        self._long_edge.setSingleStep(100)
        self._long_edge.setSuffix(" px")
        self._long_edge.valueChanged.connect(self._on_changed)
        self._long_edge_row = self._row("Long edge", self._long_edge)
        self._percent = QDoubleSpinBox()
        self._percent.setRange(1, 400)
        self._percent.setDecimals(0)
        self._percent.setSuffix(" %")
        self._percent.valueChanged.connect(self._on_changed)
        self._percent_row = self._row("Scale", self._percent)
        self._fit_w = QSpinBox()
        self._fit_w.setRange(16, 20000)
        self._fit_w.setSuffix(" px")
        self._fit_w.valueChanged.connect(self._on_changed)
        self._fit_h = QSpinBox()
        self._fit_h.setRange(16, 20000)
        self._fit_h.setSuffix(" px")
        self._fit_h.valueChanged.connect(self._on_changed)
        self._fit_row = self._row("Box", self._fit_w, self._fit_h)
        for layout in (self._long_edge_row, self._percent_row, self._fit_row):
            body.addLayout(layout)

        self._no_upscale = QCheckBox("Never enlarge")
        self._no_upscale.setToolTip("Keep photos smaller than the target at their own size.")
        self._no_upscale.toggled.connect(self._on_changed)
        body.addWidget(self._no_upscale)

        self._resample = QComboBox()
        for key, label in X.RESAMPLING_LABELS.items():
            self._resample.addItem(label, key)
        self._resample.currentIndexChanged.connect(self._on_changed)
        self._resample_row = self._row("Resample", self._resample)
        body.addLayout(self._resample_row)

        self._dpi = QSpinBox()
        self._dpi.setRange(1, 1200)
        self._dpi.setSuffix(" dpi")
        self._dpi.setToolTip("Written into the file's metadata (print size); doesn't change the pixel count.")
        self._dpi.valueChanged.connect(self._on_changed)
        body.addLayout(self._row("Resolution", self._dpi))

        self._size_hint = QLabel("")
        self._size_hint.setProperty("role", "hint")
        body.addWidget(self._size_hint)

        # ---- color / metadata ----
        body.addWidget(self._section("COLOR & METADATA"))
        self._srgb = QCheckBox("Embed sRGB profile")
        self._srgb.toggled.connect(self._on_changed)
        body.addWidget(self._srgb)
        self._gray = QCheckBox("Convert to grayscale")
        self._gray.toggled.connect(self._on_changed)
        body.addWidget(self._gray)
        self._exif = QCheckBox("Copy EXIF from the original")
        self._exif.setToolTip("Camera data from standard-format originals (not RAW files).")
        self._exif.toggled.connect(self._on_changed)
        body.addWidget(self._exif)

        # ---- destination (shared by every preset) ----
        body.addWidget(self._section("DESTINATION (all presets)"))
        self._dest_mode = QComboBox()
        for mode in X.DEST_MODES:
            self._dest_mode.addItem(X.DEST_LABELS[mode], mode)
        self._dest_mode.currentIndexChanged.connect(self._on_changed)
        body.addLayout(self._row("Save to", self._dest_mode))

        self._folder = QLineEdit()
        self._folder.textChanged.connect(self._on_changed)
        self._browse = QPushButton("...")
        self._browse.setFixedWidth(28)
        self._browse.clicked.connect(self._on_browse)
        self._folder_row = self._row("Folder", self._folder, self._browse)
        body.addLayout(self._folder_row)

        self._subfolder = QLineEdit()
        self._subfolder.setPlaceholderText("(none)")
        self._subfolder.textChanged.connect(self._on_changed)
        self._subfolder_row = self._row("Subfolder", self._subfolder)
        body.addLayout(self._subfolder_row)

        self._preset_folders = QCheckBox("Folder per preset")
        self._preset_folders.setToolTip("Put each preset's files in a subfolder named after it.")
        self._preset_folders.toggled.connect(self._on_changed)
        body.addWidget(self._preset_folders)

        self._date_folders = QCheckBox("Date subfolders (DD-MM-YYYY)")
        self._date_folders.toggled.connect(self._on_changed)
        body.addWidget(self._date_folders)

        self._pattern = QLineEdit()
        self._pattern.setToolTip(
            "{name} is the original photo's file name (RAW or not), unchanged - the default. "
            "Other tokens: {n} number in the batch, {date}, {w}, {h}, {format}, {roll} and {frame} (from the Metadata tab)"
        )
        self._pattern.textChanged.connect(self._on_changed)
        body.addLayout(self._row("Filename", self._pattern))
        self._name_preview = QLabel("")
        self._name_preview.setProperty("role", "hint")
        self._name_preview.setWordWrap(True)
        body.addWidget(self._name_preview)

        self._conflict = QComboBox()
        for key, label in X.CONFLICT_LABELS.items():
            self._conflict.addItem(label, key)
        self._conflict.setToolTip("What to do when a file with that name already exists. An export never overwrites the original photo.")
        self._conflict.currentIndexChanged.connect(self._on_changed)
        body.addLayout(self._row("If exists", self._conflict))

        # ---- run ----
        body.addWidget(self._section("EXPORT"))
        self._scope = QComboBox()
        for scope in X.SCOPES:
            self._scope.addItem(X.SCOPE_LABELS[scope], scope)
        self._scope.setToolTip(
            "Batch scopes use the folder loaded into the filmstrip (click a folder in the Library). "
            "Press K on an open photo to mark a keeper, R to reject it."
        )
        self._scope.currentIndexChanged.connect(self._on_changed)
        body.addLayout(self._row("What", self._scope))

        buttons = QHBoxLayout()
        buttons.setSpacing(THEME.space_sm)
        self._export_btn = QPushButton("Export")
        self._export_btn.setToolTip("Export with the settings shown above (the highlighted preset), ignoring the ticks.")
        self._export_btn.clicked.connect(self._on_export_clicked)
        buttons.addWidget(self._export_btn)
        self._export_presets_btn = QPushButton("Export Presets")
        self._export_presets_btn.setToolTip("Export once for every ticked preset - e.g. JPEG and TIFF together.")
        self._export_presets_btn.clicked.connect(self._on_export_presets_clicked)
        buttons.addWidget(self._export_presets_btn)
        body.addLayout(buttons)

        self._batch_keepers_btn = QPushButton("Batch Export Keepers")
        self._batch_keepers_btn.setToolTip(
            "Export every photo marked as a keeper (K) in the filmstrip folder, once for each ticked preset "
            "(or the highlighted preset if none are ticked). Doesn't depend on the scope menu."
        )
        self._batch_keepers_btn.clicked.connect(self._on_batch_keepers_clicked)
        body.addWidget(self._batch_keepers_btn)

        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        self._progress.setFormat("%p% done")
        self._progress.hide()
        body.addWidget(self._progress)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.cancel_requested)
        self._cancel_btn.hide()
        body.addWidget(self._cancel_btn)
        self._status = QLabel("")
        self._status.setProperty("role", "hint")
        self._status.setWordWrap(True)
        body.addWidget(self._status)
        self._result_folder: str | None = None
        self._open_btn = QPushButton("Show in Folder")
        self._open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._result_folder or "")))
        self._open_btn.hide()
        body.addWidget(self._open_btn)

        self._source_size: tuple[int, int] | None = None
        self._example_name = "IMG_0001"
        self._load_settings()
        self._loading = False
        self._refresh_visibility()
        self._refresh_hints()

    # ---- small builders ----
    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "subtitle")
        return label

    @staticmethod
    def _row(label: str, *widgets: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(THEME.space_sm)
        name = QLabel(label)
        name.setFixedWidth(_LABEL_WIDTH)
        row.addWidget(name)
        for i, widget in enumerate(widgets):
            row.addWidget(widget, 1 if i == 0 else 0)
        return row

    @staticmethod
    def _set_row_visible(row: QHBoxLayout, visible: bool) -> None:
        for i in range(row.count()):
            item = row.itemAt(i).widget()
            if item is not None:
                item.setVisible(visible)

    # ---- options <-> widgets ----
    def options(self) -> X.ExportOptions:
        """Everything the controls show right now: the highlighted preset's
        settings plus the shared destination/naming ones."""
        return X.ExportOptions(
            fmt=self._format.currentData(),
            jpeg_quality=int(self._jpeg_quality.value()),
            jpeg_progressive=self._jpeg_progressive.isChecked(),
            jpeg_subsampling=self._jpeg_sub.currentData(),
            png_compress=int(self._png_compress.value()),
            tiff_compression=self._tiff_comp.currentData(),
            webp_quality=int(self._webp_quality.value()),
            webp_lossless=self._webp_lossless.isChecked(),
            webp_method=int(self._webp_method.value()),
            size_mode=self._size_mode.currentData(),
            long_edge=self._long_edge.value(),
            percent=self._percent.value(),
            fit_w=self._fit_w.value(),
            fit_h=self._fit_h.value(),
            no_upscale=self._no_upscale.isChecked(),
            resample=self._resample.currentData(),
            dpi=self._dpi.value(),
            embed_srgb=self._srgb.isChecked(),
            grayscale=self._gray.isChecked(),
            copy_exif=self._exif.isChecked(),
            suffix=self._suffix.text(),
            dest_mode=self._dest_mode.currentData(),
            folder=self._folder.text().strip(),
            subfolder=self._subfolder.text(),
            date_folders=self._date_folders.isChecked(),
            pattern=self._pattern.text() or "{name}",
            on_conflict=self._conflict.currentData(),
            preset_folders=self._preset_folders.isChecked(),
        )

    def _preset_fields(self) -> dict:
        return {k: v for k, v in self.options().to_dict().items() if k not in X.GLOBAL_FIELDS}

    def _set_preset_fields(self, o: X.ExportOptions) -> None:
        self._loading = True

        def pick(combo: QComboBox, value) -> None:
            combo.setCurrentIndex(max(0, combo.findData(value)))

        pick(self._format, o.fmt)
        self._jpeg_quality.set_value(o.jpeg_quality)
        pick(self._jpeg_sub, o.jpeg_subsampling)
        self._jpeg_progressive.setChecked(o.jpeg_progressive)
        self._png_compress.set_value(o.png_compress)
        pick(self._tiff_comp, o.tiff_compression)
        self._webp_quality.set_value(o.webp_quality)
        self._webp_lossless.setChecked(o.webp_lossless)
        self._webp_method.set_value(o.webp_method)
        self._suffix.setText(o.suffix)
        pick(self._size_mode, o.size_mode)
        self._long_edge.setValue(int(o.long_edge))
        self._percent.setValue(float(o.percent))
        self._fit_w.setValue(int(o.fit_w))
        self._fit_h.setValue(int(o.fit_h))
        self._no_upscale.setChecked(o.no_upscale)
        pick(self._resample, o.resample)
        self._dpi.setValue(int(o.dpi))
        self._srgb.setChecked(o.embed_srgb)
        self._gray.setChecked(o.grayscale)
        self._exif.setChecked(o.copy_exif)
        self._loading = False

    def _set_global_fields(self, o: X.ExportOptions) -> None:
        self._loading = True
        self._dest_mode.setCurrentIndex(max(0, self._dest_mode.findData(o.dest_mode)))
        self._folder.setText(o.folder or _default_folder())
        self._subfolder.setText(o.subfolder)
        self._date_folders.setChecked(o.date_folders)
        self._pattern.setText(o.pattern)
        self._conflict.setCurrentIndex(max(0, self._conflict.findData(o.on_conflict)))
        self._preset_folders.setChecked(o.preset_folders)
        self._loading = False

    # ---- presets ----
    def _default_presets(self) -> list[dict]:
        return [
            {"name": name, "checked": name == _DEFAULT_CHECKED, "options": X.ExportOptions.from_dict(values).to_dict()}
            for name, values in X.PRESETS.items()
        ]

    def _load_settings(self) -> None:
        settings = QSettings("PhotoEditor", "PhotoEditor")
        try:
            presets = json.loads(settings.value(_PRESETS_KEY, "") or "null")
        except (TypeError, ValueError):
            presets = None
        if not isinstance(presets, list) or not all(isinstance(p, dict) and "name" in p for p in presets):
            presets = self._default_presets()
        self._presets = presets
        try:
            shared = json.loads(settings.value(_GLOBAL_KEY, "") or "{}")
        except (TypeError, ValueError):
            shared = {}
        self._set_global_fields(X.ExportOptions.from_dict(shared))
        # Reopen on the preset that was being edited, so the quality slider (and
        # everything else) shows what the user left it at - not the first preset's.
        last = str(settings.value(_SELECTED_KEY, "") or "")
        names = [p["name"] for p in self._presets]
        self._rebuild_list(select=names.index(last) if last in names else 0)

    def _save_settings(self) -> None:
        settings = QSettings("PhotoEditor", "PhotoEditor")
        settings.setValue(_PRESETS_KEY, json.dumps(self._presets))
        shared = {k: v for k, v in self.options().to_dict().items() if k in X.GLOBAL_FIELDS}
        settings.setValue(_GLOBAL_KEY, json.dumps(shared))
        if 0 <= self._current < len(self._presets):
            settings.setValue(_SELECTED_KEY, self._presets[self._current]["name"])

    def _rebuild_list(self, select: int) -> None:
        self._loading = True
        self._preset_list.clear()
        for preset in self._presets:
            item = QListWidgetItem(preset["name"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if preset.get("checked") else Qt.CheckState.Unchecked)
            item.setToolTip(describe(X.ExportOptions.from_dict(preset.get("options", {}))))
            self._preset_list.addItem(item)
        self._loading = False
        self._current = -1
        self._update_preset_button()
        if self._presets:
            self._preset_list.setCurrentRow(max(0, min(select, len(self._presets) - 1)))
        else:
            self._on_preset_selected(-1)

    def _on_preset_selected(self, row: int) -> None:
        if self._loading:
            return
        self._current = row
        if 0 <= row < len(self._presets):
            self._set_preset_fields(X.ExportOptions.from_dict(self._presets[row].get("options", {})))
            self._save_settings()  # remembers which preset is being edited
        self._refresh_visibility()
        self._refresh_hints()

    def _on_preset_checked(self, item: QListWidgetItem) -> None:
        if self._loading:
            return
        row = self._preset_list.row(item)
        if 0 <= row < len(self._presets):
            self._presets[row]["checked"] = item.checkState() == Qt.CheckState.Checked
            self._update_preset_button()
            self._save_settings()

    def _unique_name(self, name: str) -> str:
        taken = {p["name"] for p in self._presets}
        candidate, n = name, 2
        while candidate in taken:
            candidate, n = f"{name} {n}", n + 1
        return candidate

    def _on_new_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "New export preset", "Preset name:", text="My preset")
        if not ok or not name.strip():
            return
        self._presets.append({"name": self._unique_name(name.strip()), "checked": True, "options": self._preset_fields()})
        self._save_settings()
        self._rebuild_list(select=len(self._presets) - 1)

    def _on_rename_preset(self) -> None:
        if not 0 <= self._current < len(self._presets):
            return
        name, ok = QInputDialog.getText(self, "Rename preset", "Preset name:", text=self._presets[self._current]["name"])
        if not ok or not name.strip() or name.strip() == self._presets[self._current]["name"]:
            return
        row = self._current
        self._presets[row]["name"] = self._unique_name(name.strip())
        self._save_settings()
        self._rebuild_list(select=row)

    def _on_delete_preset(self) -> None:
        if not 0 <= self._current < len(self._presets):
            return
        row = self._current
        del self._presets[row]
        self._save_settings()
        self._rebuild_list(select=row)

    def current_job(self) -> list[tuple[str, X.ExportOptions]]:
        """What the Export button writes per photo: the settings as shown."""
        name = self._presets[self._current]["name"] if 0 <= self._current < len(self._presets) else "Current settings"
        return [(name, self.options())]

    def preset_jobs(self) -> list[tuple[str, X.ExportOptions]]:
        """What Export Presets writes per photo: one (name, options) per
        ticked preset, each with the shared destination applied."""
        shared = self.options()
        return [
            (p["name"], X.merge_global(X.ExportOptions.from_dict(p.get("options", {})), shared))
            for p in self._presets
            if p.get("checked")
        ]

    # ---- behavior ----
    def _on_export_clicked(self) -> None:
        self.export_requested.emit(self._scope.currentData(), self.current_job())

    def _on_export_presets_clicked(self) -> None:
        jobs = self.preset_jobs()
        if not jobs:
            self.show_message("Tick at least one preset in the list first.")
            return
        self.export_requested.emit(self._scope.currentData(), jobs)

    def _on_batch_keepers_clicked(self) -> None:
        self.export_requested.emit("keepers", self.preset_jobs() or self.current_job())

    def _update_preset_button(self) -> None:
        ticked = sum(1 for p in self._presets if p.get("checked"))
        self._export_presets_btn.setText(f"Export Presets ({ticked})" if ticked else "Export Presets")

    def _on_browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Export folder", self._folder.text())
        if chosen:
            self._folder.setText(chosen)

    def _on_changed(self, *_args) -> None:
        if self._loading:
            return
        if 0 <= self._current < len(self._presets):  # the controls edit the highlighted preset
            self._presets[self._current]["options"] = self._preset_fields()
            item = self._preset_list.item(self._current)
            if item is not None:
                item.setToolTip(describe(X.ExportOptions.from_dict(self._presets[self._current]["options"])))
        self._refresh_visibility()
        self._refresh_hints()
        self._save_settings()

    def _refresh_visibility(self) -> None:
        fmt = self._format.currentData()
        self._jpeg_box.setVisible(fmt == "jpeg")
        self._png_box.setVisible(fmt == "png")
        self._tiff_box.setVisible(fmt == "tiff")
        self._webp_box.setVisible(fmt == "webp")
        self._webp_quality.setEnabled(not self._webp_lossless.isChecked())

        mode = self._size_mode.currentData()
        self._set_row_visible(self._long_edge_row, mode == "long_edge")
        self._set_row_visible(self._percent_row, mode == "percent")
        self._set_row_visible(self._fit_row, mode == "fit")
        self._no_upscale.setVisible(mode != "original")
        self._set_row_visible(self._resample_row, mode != "original")
        self._srgb.setEnabled(not self._gray.isChecked())

        beside = self._dest_mode.currentData() == "beside"
        self._set_row_visible(self._folder_row, not beside)
        self._set_row_visible(self._subfolder_row, beside)

    def _refresh_hints(self) -> None:
        o = self.options()
        if self._source_size:
            w, h = X.target_size(self._source_size[0], self._source_size[1], o)
            self._size_hint.setText(f"Current image exports at {w} × {h} px.")
            size = (w, h)
        else:
            self._size_hint.setText("Open an image to see its export size.")
            size = (0, 0)
        stem = X.render_filename(o.pattern, self._example_name, 1, size, o.fmt)
        names = [stem + o.suffix + X.EXTENSIONS[o.fmt]]
        self._name_preview.setText(f"e.g. {names[0]}")

    # ---- driven by the window ----
    def set_source_info(self, name: str | None, size: tuple[int, int] | None) -> None:
        """The open image's file stem and full-resolution (cropped) size, for the hints."""
        self._example_name = name or "IMG_0001"
        self._source_size = size
        self._refresh_hints()

    def set_busy(self, busy: bool) -> None:
        self._export_btn.setEnabled(not busy)
        self._export_presets_btn.setEnabled(not busy)
        self._batch_keepers_btn.setEnabled(not busy)
        self._progress.setVisible(busy)
        self._cancel_btn.setVisible(busy)
        if busy:
            self._progress.setRange(0, 100)
            self._progress.setValue(0)
            self._progress.setFormat("%p% done")
            self._status.setText("Starting...")
            self._open_btn.hide()

    def set_progress(self, done: int, total: int, name: str) -> None:
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(done)
        self._progress.setFormat("%p% done")
        self._status.setText(f"{name}")

    def show_message(self, text: str, folder: str | None = None) -> None:
        self._status.setText(text)
        self._result_folder = folder
        self._open_btn.setVisible(bool(folder))
