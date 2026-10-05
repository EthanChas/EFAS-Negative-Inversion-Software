"""The Roll Card tab: one card per roll of film.

A ticket at the top (the canister, the roll's name, its film and camera, and a FRAME n / N stamp) is what the folder's photos have
in common, and the sections under it fill it in: ROLL (film, camera, lens, the dates it was shot, how it was developed and scanned -
every frame in the folder inherits it), THIS FRAME (the details only this photo has) and EXPORT (what goes into the files).
Nothing here changes the picture, so edits only save."""

import os
from typing import Callable, Optional

from PyQt6.QtCore import QRectF, QStringListModel, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPaintEvent, QPen, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import dataclasses

from ...features.metadata import presets as autofill
from ...features.metadata import suggest
from ...features.metadata.capture import parse_capture_date, place_summary
from ...features.metadata.models import FORMAT_OPTIONS, MetadataConfig, format_label
from ...features.metadata.payload import build_metadata_payload
from ...features.metadata.roll import CANISTER_KEYS, KNOWN_FILMS, RollCard, frame_date, summary
from ...features.watermark.logic import ASSET_DIR
from ...theme.tokens import THEME
from .collapsible_panel import CollapsiblePanel

_COMMIT_MS = 500
_LABEL_W = 78
_TICKET_H = 112
_pixmaps: dict[str, QPixmap] = {}


def _canister_pixmap(film: str) -> Optional[QPixmap]:
    key = CANISTER_KEYS.get(film.strip())
    if key is None:
        return None
    if key not in _pixmaps:
        path = os.path.join(str(ASSET_DIR), f"{key}__plastic.png")
        _pixmaps[key] = QPixmap(path) if os.path.exists(path) else QPixmap()
    px = _pixmaps[key]
    return None if px.isNull() else px


class RollTicket(QWidget):
    """The card's header, painted by hand: a strip of film's perforations along the top and bottom, the canister of the roll's film
    on the left (a plain one when the film has no art), the roll's name and details beside it, and a FRAME stamp."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._roll = RollCard()
        self._frame: Optional[int] = None
        self._total = 0
        self.setMinimumHeight(_TICKET_H)
        self.setMaximumHeight(_TICKET_H)

    def set_data(self, roll: RollCard, frame: Optional[int], total: int) -> None:
        self._roll, self._frame, self._total = roll, frame, total
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(THEME.bg_input))
        # the sunken bevel, like the app's other canvases
        for i in range(THEME.border_width):
            p.setPen(QColor(THEME.border_color)); p.drawLine(i, i, w - 1 - i, i); p.drawLine(i, i, i, h - 1 - i)
            p.setPen(QColor(THEME.bevel_light)); p.drawLine(w - 1 - i, i, w - 1 - i, h - 1 - i); p.drawLine(i, h - 1 - i, w - 1 - i, h - 1 - i)
        # film perforations along the top and bottom edges
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(THEME.bg_app))
        x = 8
        while x < w - 12:
            p.drawRoundedRect(QRectF(x, 5, 6, 4), 1, 1); p.drawRoundedRect(QRectF(x, h - 9, 6, 4), 1, 1)
            x += 12
        # the canister
        box = QRectF(12, 14, 64, h - 28)
        art = _canister_pixmap(self._roll.film)
        if art is not None:
            scaled = art.scaled(int(box.width()), int(box.height()), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(box.x() + (box.width() - scaled.width()) / 2), int(box.y() + (box.height() - scaled.height()) / 2), scaled)
        else:
            self._paint_plain_canister(p, box)
        # the words
        left = int(box.right()) + 12
        right = w - 12
        name = self._roll.name.strip()
        big = QFont(self.font()); big.setBold(True); big.setPointSize(self.font().pointSize() + 3)
        small = QFont(self.font())
        p.setFont(big)
        p.setPen(QColor(THEME.text_primary if name else THEME.text_muted))
        fm = QFontMetrics(big)
        p.drawText(left, 18 + fm.ascent(), fm.elidedText(name or "Untitled roll", Qt.TextElideMode.ElideRight, right - left))
        p.setFont(small); fm = QFontMetrics(small)
        y = 18 + QFontMetrics(big).height() + 2
        line = summary(self._roll)
        p.setPen(QColor(THEME.text_secondary if line else THEME.text_muted))
        p.drawText(left, y + fm.ascent(), fm.elidedText(line or "Film, ISO and format", Qt.TextElideMode.ElideRight, right - left))
        y += fm.height() + 1
        rig = " · ".join(t for t in (self._roll.camera.strip(), self._roll.lens.strip()) if t)
        p.setPen(QColor(THEME.text_secondary if rig else THEME.text_muted))
        p.drawText(left, y + fm.ascent(), fm.elidedText(rig or "Camera and lens", Qt.TextElideMode.ElideRight, right - left))
        # the stamp: FRAME n / N, a little crooked, like a lab's rubber stamp
        number = str(self._frame) if self._frame is not None else "—"
        label = f"FRAME {number}" + (f" / {self._total}" if self._total else "")
        stamp = QFont(self.font()); stamp.setBold(True); stamp.setStyleHint(QFont.StyleHint.Monospace); stamp.setFamily("Consolas")
        sfm = QFontMetrics(stamp)
        sw, sh = sfm.horizontalAdvance(label) + 16, sfm.height() + 8
        p.save()
        p.translate(w - 18 - sw / 2, h - 18 - sh / 2); p.rotate(-3.0)
        p.setFont(stamp)
        warn = QColor(THEME.status_warning)
        p.setPen(QPen(warn, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(-sw / 2, -sh / 2, sw, sh), 2, 2)
        p.drawText(QRectF(-sw / 2, -sh / 2, sw, sh), Qt.AlignmentFlag.AlignCenter, label)
        p.restore()
        if self._roll.keep_original_exif:
            tag = "ORIGINAL EXIF KEPT"
            p.setFont(small); p.setPen(QColor(THEME.text_hint))
            p.drawText(left, int(h - 14), tag)
        p.end()

    def _paint_plain_canister(self, p: QPainter, box: QRectF) -> None:
        """A generic 35mm cartridge: a body, a cap and the spool's stub, in the app's own greys."""
        cx = box.center().x(); bw = box.width() * 0.62
        body = QRectF(cx - bw / 2, box.y() + 14, bw, box.height() - 14)
        p.setPen(QPen(QColor(THEME.border_color), 1)); p.setBrush(QColor(THEME.text_muted))
        p.drawRoundedRect(body, 3, 3)
        p.setBrush(QColor(THEME.text_secondary))
        p.drawRoundedRect(QRectF(cx - bw / 2 - 2, box.y() + 8, bw + 4, 7), 2, 2)
        p.drawRect(QRectF(cx - 4, box.y() + 1, 8, 8))
        p.setBrush(QColor(THEME.accent_primary)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(body.x() + 4, body.y() + body.height() * 0.3, body.width() - 8, body.height() * 0.32))


def _row(body: QVBoxLayout, label: str, widget: QWidget, tip: str = "") -> None:
    row = QHBoxLayout()
    name = QLabel(label)
    name.setFixedWidth(_LABEL_W)
    row.addWidget(name)
    if tip:
        widget.setToolTip(tip)
    row.addWidget(widget, 1)
    body.addLayout(row)


class RollCardTab(QWidget):
    """The ticket plus its sections. `roll_edited` carries the whole RollCard and `frame_edited` this frame's own MetadataConfig,
    each after a short pause, so typing never saves per keystroke."""

    roll_edited = pyqtSignal(object)   # RollCard
    frame_edited = pyqtSignal(object)  # MetadataConfig

    def __init__(
        self,
        effective: Optional[Callable[[], MetadataConfig]] = None,
        source_exif: Optional[Callable[[], Optional[dict]]] = None,
        other_rolls: Optional[Callable[[], list]] = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._effective = effective or (lambda: MetadataConfig())
        self._source_exif = source_exif or (lambda: None)
        self._other_rolls = other_rolls or (lambda: [])
        self._roll = RollCard()
        self._frame = MetadataConfig()
        self._position: tuple[Optional[int], int] = (None, 0)
        self._folder = ""
        self._place_edited = False
        self._auto_iso: Optional[int] = None  # the ISO a film preset filled in, which a different film may replace
        self._completers: dict[str, QStringListModel] = {}

        self._roll_timer = QTimer(self); self._roll_timer.setSingleShot(True); self._roll_timer.setInterval(_COMMIT_MS)
        self._roll_timer.timeout.connect(self._commit_roll)
        self._frame_timer = QTimer(self); self._frame_timer.setSingleShot(True); self._frame_timer.setInterval(_COMMIT_MS)
        self._frame_timer.timeout.connect(self._commit_frame)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(THEME.space_sm)
        self._ticket = RollTicket()
        col.addWidget(self._ticket)
        col.addWidget(self._build_roll())
        col.addWidget(self._build_frame())
        col.addWidget(self._build_export())
        col.addWidget(self._build_presets())

    # ---- sections ----
    def _panel(self, title: str, help_text: str) -> tuple[CollapsiblePanel, QVBoxLayout]:
        panel = CollapsiblePanel(title, help_text=help_text, collapsible=True, start_expanded=False)
        body = panel.body()
        body.setSpacing(THEME.space_sm)
        return panel, body

    def _text(self, kind: Optional[str], placeholder: str, on_change) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        if kind:
            model = QStringListModel(suggest.suggestions(kind), edit)
            comp = QCompleter(model, edit)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            edit.setCompleter(comp)
            self._completers[kind] = model
        edit.textChanged.connect(on_change)
        return edit

    def _build_roll(self) -> CollapsiblePanel:
        panel, body = self._panel(
            "Roll",
            "What this whole roll has in common - its film, camera, lens, the days it was shot, how it was developed and scanned. "
            "It belongs to the folder: every photo in it inherits it, so you fill it in once. Type anything; names you have used "
            "before are suggested. Give a first and a last day and the frames are dated evenly across them.",
        )
        self._roll_hint = QLabel("")
        self._roll_hint.setWordWrap(True)
        self._roll_hint.setStyleSheet(f"color: {THEME.text_hint};")
        body.addWidget(self._roll_hint)
        self._name = self._text(None, "e.g. Roll 07, Tokyo trip", self._roll_dirty)
        _row(body, "Name", self._name)
        film_row = QHBoxLayout()
        flabel = QLabel("Film"); flabel.setFixedWidth(_LABEL_W)
        film_row.addWidget(flabel)
        self._film = QComboBox(); self._film.setEditable(True); self._film.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._film.addItems(suggest.suggestions("film"))
        self._film.setCurrentText("")
        self._film.lineEdit().setPlaceholderText("e.g. Kodak Gold 200")
        self._film.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)  # the default inline mode splices a half-typed name onto its match
        self._film.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self._film.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._film.setToolTip("Pick a film or type your own. The canisters the Canister Watermark has art for are listed first.")
        self._film.editTextChanged.connect(self._on_film_changed)
        film_row.addWidget(self._film, 1)
        isolabel = QLabel("ISO")
        film_row.addWidget(isolabel)
        self._iso = QSpinBox(); self._iso.setRange(0, 25600); self._iso.setSpecialValueText("—"); self._iso.setFixedWidth(64)
        self._iso.valueChanged.connect(self._roll_dirty)
        film_row.addWidget(self._iso)
        body.addLayout(film_row)
        self._format = QComboBox(); self._format.addItems(FORMAT_OPTIONS); self._format.setItemText(0, "not set")
        self._format.currentIndexChanged.connect(self._roll_dirty)
        _row(body, "Format", self._format)
        self._camera = self._text("camera", "e.g. Pentax K1000", self._roll_dirty)
        self._camera.editingFinished.connect(self._on_camera_finished)
        self._camera.completer().activated.connect(lambda _t: self._on_camera_finished())
        _row(body, "Camera", self._camera, "The body the roll was shot on.")
        self._lens = self._text("lens", "e.g. SMC Pentax-M 50mm f/2", self._roll_dirty)
        _row(body, "Lens", self._lens)
        shot = QHBoxLayout()
        slabel = QLabel("Shot"); slabel.setFixedWidth(_LABEL_W)
        shot.addWidget(slabel)
        self._from = self._text(None, "from  YYYY-MM-DD", self._on_roll_date_changed)
        self._to = self._text(None, "to  YYYY-MM-DD", self._on_roll_date_changed)
        shot.addWidget(self._from, 1); shot.addWidget(self._to, 1)
        self._from.setToolTip("The first day this roll was shot. A year or a year-month is fine.")
        self._to.setToolTip("The last day. With both full dates, frames are dated evenly from the first to the last.")
        body.addLayout(shot)
        self._developed = self._text("developed", "lab, or developer and time", self._roll_dirty)
        _row(body, "Developed", self._developed, "Where or how the film was developed, in your own words.")
        self._scanned = self._text("scanned", "e.g. DSLR copy-stand", self._roll_dirty)
        _row(body, "Scanned with", self._scanned)
        for edit in (self._name, self._film.lineEdit(), self._camera, self._lens, self._from, self._to, self._developed, self._scanned, self._iso):
            edit.editingFinished.connect(self._commit_now)  # leaving a field (clicking another photo, say) saves what was typed in it
        buttons = QHBoxLayout()
        self._copy_btn = QToolButton(); self._copy_btn.setText("Copy another roll…")
        self._copy_btn.setToolTip("Start from the card of a roll you have already filled in")
        self._copy_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._copy_menu = QMenu(self._copy_btn); self._copy_menu.aboutToShow.connect(self._fill_copy_menu)
        self._copy_btn.setMenu(self._copy_menu)
        clear = QPushButton("Clear card"); clear.setToolTip("Empty this roll's card (the photos' own details stay)")
        clear.clicked.connect(self._clear_roll)
        buttons.addWidget(self._copy_btn); buttons.addStretch(1); buttons.addWidget(clear)
        body.addLayout(buttons)
        return panel

    def _build_frame(self) -> CollapsiblePanel:
        panel, body = self._panel(
            "This frame",
            "Only this photo's own details. Frame is its number on the roll - left on auto it follows its place in the folder's "
            "filmstrip. Date overrides the roll's dates for this frame. Place is free text. Note is yours.",
        )
        self._frame_no = QSpinBox(); self._frame_no.setRange(0, 9999); self._frame_no.setSpecialValueText("auto")
        self._frame_no.valueChanged.connect(self._frame_dirty)
        _row(body, "Frame", self._frame_no, "Its number on the roll. Auto follows its place in the folder.")
        self._date = self._text(None, "uses the roll's dates", self._on_frame_date_changed)
        _row(body, "Date", self._date, "When this frame was shot (YYYY, YYYY-MM, YYYY-MM-DD, optionally with a time).")
        self._place = self._text(None, "e.g. Shibuya, Tokyo", self._on_place_changed)
        _row(body, "Place", self._place)
        self._exposure = self._text(None, "e.g. 1/125 f/8", self._frame_dirty)
        _row(body, "Exposure", self._exposure, "What the camera was set to, if you know it. Written as it is.")
        self._note = QPlainTextEdit(); self._note.setPlaceholderText("a line about the frame")
        self._note.setFixedHeight(54); self._note.textChanged.connect(self._frame_dirty)
        _row(body, "Note", self._note)
        return panel

    def _build_export(self) -> CollapsiblePanel:
        panel, body = self._panel(
            "Export",
            "What goes into your exported files. Write roll card puts the roll's details and this frame's into the EXIF and XMP of "
            "each file; Keep original EXIF leaves the scan's own EXIF untouched and writes nothing of the card.",
        )
        seg = QHBoxLayout(); seg.setSpacing(0)
        self._write_btn = QPushButton("Write roll card"); self._keep_btn = QPushButton("Keep original EXIF")
        for b in (self._write_btn, self._keep_btn):
            b.setCheckable(True)
        self._write_btn.setChecked(True)
        group = QButtonGroup(self); group.setExclusive(True); group.addButton(self._write_btn); group.addButton(self._keep_btn)
        group.buttonToggled.connect(lambda *_: self._roll_dirty())
        seg.addWidget(self._write_btn); seg.addWidget(self._keep_btn)
        body.addLayout(seg)
        head = QLabel("Goes into the file")
        head.setStyleSheet(f"color: {THEME.text_secondary}; font-weight: bold;")
        body.addWidget(head)
        self._preview = QLabel("")
        self._preview.setWordWrap(True)
        self._preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.addWidget(self._preview)
        return panel

    # ---- presets ----
    def _build_presets(self) -> CollapsiblePanel:
        panel, body = self._panel(
            "Presets",
            "Your own cameras, lenses and films - the names the fields above suggest and fill in while you type. A camera preset can remember "
            "its usual lens (picking the camera fills the lens in, if the lens is empty); a film preset remembers its ISO and format. "
            "Pick one in the list to edit it, Save to add or update, Remove to delete.",
        )
        self._pkind = QComboBox(); self._pkind.addItems(["Cameras", "Lenses", "Film"])
        self._pkind.currentIndexChanged.connect(lambda _i: self._reload_presets())
        _row(body, "Edit", self._pkind)
        self._plist = QListWidget(); self._plist.setFixedHeight(112)
        self._plist.currentItemChanged.connect(self._on_preset_picked)
        body.addWidget(self._plist)
        self._pname = QLineEdit(); self._pname.setPlaceholderText("name, e.g. Pentax K1000")
        _row(body, "Name", self._pname)
        self._plens_row = QWidget(); lens_lay = QVBoxLayout(self._plens_row); lens_lay.setContentsMargins(0, 0, 0, 0)
        self._plens = QLineEdit(); self._plens.setPlaceholderText("optional")
        _row(lens_lay, "Usual lens", self._plens, "Filled in when you pick this camera, if the lens field is empty.")
        body.addWidget(self._plens_row)
        self._pfilm_row = QWidget(); film_lay = QHBoxLayout(self._pfilm_row); film_lay.setContentsMargins(0, 0, 0, 0)
        il = QLabel("ISO"); il.setFixedWidth(_LABEL_W); film_lay.addWidget(il)
        self._piso = QSpinBox(); self._piso.setRange(0, 25600); self._piso.setSpecialValueText("\u2014"); self._piso.setFixedWidth(64)
        film_lay.addWidget(self._piso); film_lay.addWidget(QLabel("Format"))
        self._pfmt = QComboBox(); self._pfmt.addItems(FORMAT_OPTIONS); self._pfmt.setItemText(0, "not set")
        film_lay.addWidget(self._pfmt, 1)
        body.addWidget(self._pfilm_row)
        buttons = QHBoxLayout()
        save = QPushButton("Save preset"); save.clicked.connect(self._save_preset)
        new = QPushButton("New"); new.setToolTip("Clear the fields to start a new preset"); new.clicked.connect(self._new_preset)
        remove = QPushButton("Remove"); remove.clicked.connect(self._remove_preset)
        for b in (save, new, remove):
            buttons.addWidget(b)
        body.addLayout(buttons)
        self._pstatus = QLabel(""); self._pstatus.setWordWrap(True); self._pstatus.setStyleSheet(f"color: {THEME.text_hint};")
        body.addWidget(self._pstatus)
        self._pbundled = QCheckBox("Also suggest the built-in lists")
        self._pbundled.setToolTip("The bundled cameras, lenses and film stocks. Off: only your own presets.")
        self._pbundled.setChecked(autofill.use_bundled())
        self._pbundled.toggled.connect(self._on_bundled_toggled)
        body.addWidget(self._pbundled)
        self._reload_presets()
        return panel

    def _preset_kind(self) -> str:
        return ("camera", "lens", "film")[self._pkind.currentIndex()]

    def _reload_presets(self, select: str = "") -> None:
        kind = self._preset_kind()
        self._plist.blockSignals(True)
        self._plist.clear()
        for e in autofill.entries(kind):
            if kind == "camera":
                detail = f"{e['name']}  \u2192  {e['lens']}" if e.get("lens") else e["name"]
            elif kind == "film":
                detail = " \u00b7 ".join(t for t in (e["name"], f"ISO {e['iso']}" if e.get("iso") else "", e.get("format", "")) if t)
            else:
                detail = e["name"]
            item = QListWidgetItem(detail); item.setData(Qt.ItemDataRole.UserRole, e["name"])
            self._plist.addItem(item)
            if select and e["name"].casefold() == select.casefold():
                self._plist.setCurrentItem(item)
        if self._plist.count() == 0:
            empty = QListWidgetItem("no presets yet - add one below"); empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._plist.addItem(empty)
        self._plist.blockSignals(False)
        self._plens_row.setVisible(kind == "camera"); self._pfilm_row.setVisible(kind == "film")
        self._pname.setPlaceholderText({"camera": "name, e.g. Pentax K1000", "lens": "name, e.g. SMC Pentax-M 50mm f/2", "film": "name, e.g. Kodak Gold 200"}[kind])
        if not select:
            self._clear_preset_fields()

    def _clear_preset_fields(self) -> None:
        self._pname.clear(); self._plens.clear(); self._piso.setValue(0); self._pfmt.setCurrentIndex(0)

    def _on_preset_picked(self, current, _previous) -> None:
        name = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        entry = autofill.find(self._preset_kind(), name) if name else None
        if entry is None:
            return
        self._pname.setText(entry["name"])
        self._plens.setText(entry.get("lens", ""))
        self._piso.setValue(entry.get("iso") or 0)
        self._pfmt.setCurrentIndex(FORMAT_OPTIONS.index(entry["format"]) if entry.get("format") in FORMAT_OPTIONS else 0)

    def _save_preset(self) -> None:
        kind, name = self._preset_kind(), self._pname.text().strip()
        if not name:
            self._pstatus.setText("Give the preset a name first.")
            return
        existed = autofill.find(kind, name) is not None
        autofill.upsert(kind, name, lens=self._plens.text(), iso=self._piso.value() or None, format="" if self._pfmt.currentIndex() == 0 else self._pfmt.currentText())
        self._reload_presets(select=name)
        self.refresh_suggestions()
        self._pstatus.setText(f"{'Updated' if existed else 'Saved'} '{name}'.")

    def _new_preset(self) -> None:
        self._plist.clearSelection(); self._plist.setCurrentItem(None); self._clear_preset_fields(); self._pstatus.setText("")
        self._pname.setFocus()

    def _remove_preset(self) -> None:
        name = self._pname.text().strip()
        if autofill.remove(self._preset_kind(), name):
            self._reload_presets(); self.refresh_suggestions()
            self._pstatus.setText(f"Removed '{name}'.")
        else:
            self._pstatus.setText("Pick a preset in the list to remove it.")

    def _on_bundled_toggled(self, on: bool) -> None:
        autofill.set_use_bundled(on)
        self.refresh_suggestions()

    # ---- state in ----
    def set_state(self, roll: RollCard, frame: MetadataConfig, position: tuple[Optional[int], int], folder: str) -> None:
        """Show a photo (its folder's card and its own details) without emitting - a photo was opened."""
        self._roll_timer.stop(); self._frame_timer.stop()
        self._roll, self._frame, self._position, self._folder = roll, frame, position, folder
        self._place_edited = False
        self._fill_roll_fields(roll)
        self._block(True)
        try:
            self._frame_no.setValue(frame.capture_frame or 0)
            self._date.setText(frame.capture_date)
            self._place.setText(place_summary(frame.location_city, frame.location_state, frame.location_country, frame.gps_latitude, frame.gps_longitude))
            self._exposure.setText(frame.exposure_override)
            self._note.setPlainText(frame.note)
        finally:
            self._block(False)
        self._refresh_views()

    def refresh_roll(self, roll: RollCard) -> None:
        """The folder's card changed under us (copied in, or edited elsewhere): show it."""
        self._roll_timer.stop(); self._roll = roll
        self._fill_roll_fields(roll)
        self._refresh_views()

    def refresh_suggestions(self) -> None:
        for kind, model in self._completers.items():
            model.setStringList(suggest.suggestions(kind))
        text = self._film.currentText()
        self._film.blockSignals(True)
        self._film.clear(); self._film.addItems(suggest.suggestions("film")); self._film.setCurrentText(text)
        self._film.blockSignals(False)

    def _block(self, on: bool) -> None:
        for w in (self._name, self._film, self._iso, self._format, self._camera, self._lens, self._from, self._to, self._developed, self._scanned,
                  self._write_btn, self._keep_btn, self._frame_no, self._date, self._place, self._exposure, self._note):
            w.blockSignals(on)

    def _fill_roll_fields(self, roll: RollCard) -> None:
        self._block(True)
        try:
            self._name.setText(roll.name)
            self._film.setCurrentText(roll.film)
            self._iso.setValue(roll.iso or 0)
            self._format.setCurrentIndex(FORMAT_OPTIONS.index(format_label(roll.format)))
            self._camera.setText(roll.camera); self._lens.setText(roll.lens)
            self._from.setText(roll.shot_from); self._to.setText(roll.shot_to)
            self._developed.setText(roll.developed); self._scanned.setText(roll.scanned_with)
            (self._keep_btn if roll.keep_original_exif else self._write_btn).setChecked(True)
            for edit in (self._from, self._to):
                edit.setStyleSheet("")
        finally:
            self._block(False)

    # ---- state out ----
    def _roll_from_fields(self) -> RollCard:
        keep_date = lambda text, old: text.strip() if not text.strip() or parse_capture_date(text) is not None else old
        film = self._film.currentText().strip()
        return RollCard(
            name=self._name.text().strip(), film=film, iso=self._iso.value() or None, format="" if self._format.currentIndex() == 0 else self._format.currentText(),
            camera=self._camera.text().strip(), lens=self._lens.text().strip(),
            shot_from=keep_date(self._from.text(), self._roll.shot_from), shot_to=keep_date(self._to.text(), self._roll.shot_to),
            developed=self._developed.text().strip(), scanned_with=self._scanned.text().strip(), keep_original_exif=self._keep_btn.isChecked(),
        )

    def _frame_from_fields(self) -> MetadataConfig:
        f = self._frame
        date_text = self._date.text().strip()
        parsed = parse_capture_date(date_text)
        date = parsed.xmp_text() if parsed else ("" if not date_text else f.capture_date)
        changes = dict(capture_frame=self._frame_no.value() or None, capture_date=date, exposure_override=self._exposure.text().strip(), note=self._note.toPlainText().strip())
        if self._place_edited:  # typed text is the place now; coordinates from an earlier version stay
            changes.update(location_city=self._place.text().strip(), location_state="", location_country="")
        return dataclasses.replace(f, **changes)

    def _roll_dirty(self, *_args) -> None:
        self._roll_timer.start(); self._refresh_ticket_only()

    def _frame_dirty(self, *_args) -> None:
        self._frame_timer.start()

    def _commit_roll(self) -> None:
        card = self._roll_from_fields()
        if card == self._roll:
            return
        self._roll = card
        self.roll_edited.emit(card)
        self._refresh_views()

    def _commit_frame(self) -> None:
        cfg = self._frame_from_fields()
        if cfg == self._frame:
            return
        self._frame = cfg
        self.frame_edited.emit(cfg)
        self._refresh_views()

    # ---- handlers ----
    def _on_film_changed(self, text: str) -> None:
        iso, fmt = autofill.film_info(text)   # a film preset (or a film the app knows) fills in its ISO and format...
        if iso and self._iso.value() in (0, self._auto_iso):   # ...unless a different ISO was typed by hand
            self._iso.blockSignals(True); self._iso.setValue(iso); self._iso.blockSignals(False)
            self._auto_iso = iso
        if fmt in FORMAT_OPTIONS[1:] and self._format.currentIndex() == 0:
            self._format.blockSignals(True); self._format.setCurrentIndex(FORMAT_OPTIONS.index(fmt)); self._format.blockSignals(False)
        self._roll_dirty()

    def _on_camera_finished(self) -> None:
        """Picking a camera preset fills in its usual lens - only into an empty lens field, so a lens already typed is never overwritten."""
        if not self._lens.text().strip():
            lens = autofill.camera_lens(self._camera.text())
            if lens:
                self._lens.setText(lens)

    def _on_roll_date_changed(self, *_args) -> None:
        for edit in (self._from, self._to):
            ok = not edit.text().strip() or parse_capture_date(edit.text()) is not None
            edit.setStyleSheet("" if ok else f"border: 1px solid {THEME.status_critical};")
        self._roll_dirty()

    def _on_frame_date_changed(self, text: str) -> None:
        ok = not text.strip() or parse_capture_date(text) is not None
        self._date.setStyleSheet("" if ok else f"border: 1px solid {THEME.status_critical};")
        self._frame_dirty()

    def _on_place_changed(self, *_args) -> None:
        self._place_edited = True
        self._frame_dirty()

    def _fill_copy_menu(self) -> None:
        self._copy_menu.clear()
        rolls = self._other_rolls()
        if not rolls:
            self._copy_menu.addAction("No other roll has a card yet").setEnabled(False)
            return
        for folder, card in rolls[:15]:
            label = os.path.basename(folder.rstrip("\\/")) or folder
            what = card.name.strip() or summary(card) or "roll card"
            self._copy_menu.addAction(f"{label}  —  {what}").triggered.connect(lambda _c=False, c=card: self._apply_card(c))

    def _commit_now(self) -> None:
        if self._roll_timer.isActive():
            self._roll_timer.stop()
            self._commit_roll()

    def flush(self) -> None:
        """Save anything typed that is still waiting out the short typing delay - before an export reads it, or the window closes."""
        self._commit_now()
        if self._frame_timer.isActive():
            self._frame_timer.stop()
            self._commit_frame()

    def _apply_card(self, card: RollCard) -> None:
        self._fill_roll_fields(card)
        self._roll_timer.stop()
        self._commit_roll()

    def _clear_roll(self) -> None:
        self._apply_card(RollCard())

    # ---- views ----
    def _refresh_ticket_only(self) -> None:
        self._ticket.set_data(self._roll_from_fields(), self._position[0], self._position[1])

    def _refresh_views(self) -> None:
        index, total = self._position
        card = self._roll
        self._ticket.set_data(card, index, total)
        folder = os.path.basename(self._folder.rstrip("\\/")) or self._folder
        self._roll_hint.setText(f"Applies to all {total} photos in '{folder}'." if total else "Open a photo to fill in its roll.")
        auto = frame_date(card, index, total)
        self._date.setPlaceholderText(auto or "uses the roll's dates")
        self._frame_no.setSpecialValueText(f"auto ({index})" if index else "auto")
        self._update_preview()

    def _update_preview(self) -> None:
        cfg = self._effective()
        if cfg.protect_original_metadata:
            self._preview.setText("Nothing from the card: the file keeps the scan's own EXIF.")
            return
        pl = build_metadata_payload(cfg, None, self._source_exif())
        dot = " · "
        lines = []
        if pl.capture_roll or pl.capture_frame is not None:
            lines.append("Roll: " + dot.join(t for t in (pl.capture_roll, f"frame {pl.capture_frame}" if pl.capture_frame is not None else "") if t))
        if pl.capture_date is not None:
            lines.append(f"Date: {pl.capture_date.xmp_text()}")
        film = dot.join(t for t in (pl.film_stock, f"ISO {pl.iso}" if pl.iso else "", pl.film_format) if t)
        for label, value in (("Film", film), ("Camera", pl.camera_display()), ("Lens", pl.lens_display()), ("Place", pl.place_display()),
                             ("Exposure", pl.capture_exposure), ("Developed", pl.developer_display()), ("Scanned", pl.scan_method), ("Note", pl.notes)):
            if value:
                lines.append(f"{label}: {value}")
        self._preview.setText(chr(10).join(lines) if lines else "Nothing yet - fill in the roll above.")
