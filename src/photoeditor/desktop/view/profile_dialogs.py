"""Managing film profiles and comparing the two inversion methods (docs/sensitometry-tier2-design.md, sections 6, 9 and 10)."""

import os

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

import photoeditor
from ...features.densitometry import film_profile as fp, profile_bundle, view_model
from ...features.densitometry.film_profile import KIND_LABELS
from ...theme.tokens import THEME
from .characterization_dialog import _ask


def _text(p: fp.FilmProfile) -> str:
    lines = view_model.profile_lines(p)
    cal = p.calibration or {}
    if cal.get("tablet"):
        t = cal["tablet"]
        lines.append(f"Target: {t.get('name') or 'step tablet'}, {t.get('steps', len(t.get('densities', [])))} steps, "
                     f"{'actual (calibrated)' if t.get('densities_are_actual') else 'nominal'} densities")
    for key, label in (("exposure", "Exposure"), ("processing", "Processing"), ("light_source", "Light source")):
        v = cal.get(key)
        if isinstance(v, dict) and v.get("method"):
            lines.append(f"{label}: {v['method']}")
        elif isinstance(v, str) and v:
            lines.append(f"{label}: {v}")
    if cal.get("scan"):
        sc = cal["scan"]
        lines.append("Scanned with: " + ", ".join(str(x) for x in (sc.get("camera"), sc.get("lens"), f"ISO {sc['iso']}" if sc.get("iso") else None) if x))
    for ch, cc in p.curves.items():
        rec = cc.fits.get(cc.chosen)
        q = rec["quality"] if rec else "interpolated"
        lo, hi = cc.supported()
        lines.append(f"{ch}: {cc.chosen}, quality {q}, measured log exposure {lo:.2f} to {hi:.2f}, {sum(cc.used)} of {len(cc.used)} points used")
    g = p.gradients()
    for ch, v in g.items():
        if v["gamma"] is not None:
            lines.append(f"{ch}: gamma {v['gamma']:.2f}")
    if p.notes:
        lines.append(f"Notes: {p.notes}")
    if p.derived_from:
        lines.append(f"Copied from profile {p.derived_from[:8]}")
    got = p.extras.get("received") if isinstance(p.extras.get("received"), dict) else None
    if got:
        who = f" from {got['author']}" if got.get("author") else ""
        lines.append(f"Received{who} as a shared bundle (originally marked {got.get('kind', 'unknown')}; files checked intact; fingerprint {got.get('fingerprint', '')})")
    return "\n".join(lines)


class ProfilesDialog(QDialog):
    """List, inspect, duplicate, edit, import, export, compare, delete and apply film profiles."""

    use_for_photo = pyqtSignal(str)
    use_in_viewer = pyqtSignal(str)
    changed = pyqtSignal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Film Profiles")
        self.resize(760, 520)
        self.c = controller
        self.store = controller.profile_store()
        outer = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show)
        left.addWidget(self.list, 1)
        imp = QPushButton("Import...")
        imp.clicked.connect(self._import)
        left.addWidget(imp)
        outer.addLayout(left, 2)
        right = QVBoxLayout()
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        right.addWidget(self.detail, 1)
        self.buttons = {}
        for key, label, slot in (
            ("use", "Use for This Photo (curve-informed)", self._use), ("view", "Show in the H&D Viewer", self._view), ("dup", "Duplicate", self._duplicate),
            ("edit", "Edit Details...", self._edit), ("export", "Export...", self._export), ("share", "Share as Bundle...", self._share), ("compare", "Compare with Another...", self._compare), ("delete", "Delete", self._delete),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            self.buttons[key] = b
            right.addWidget(b)
        outer.addLayout(right, 3)
        self.refresh()

    def _current(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def refresh(self, select: str | None = None) -> None:
        keep = select or self._current()
        self.list.blockSignals(True)
        self.list.clear()
        for r in self.store.list():
            tag = "" if r["usable"] else "  (cannot drive an inversion)"
            item = QListWidgetItem(f"{r['name']}  -  {r['film']}  -  {KIND_LABELS[r['kind']].split(' (')[0]}{tag}")
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.list.addItem(item)
            if r["id"] == keep:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._show()

    def _show(self, *_a) -> None:
        ident = self._current()
        for b in self.buttons.values():
            b.setEnabled(ident is not None)
        if ident is None:
            self.detail.setPlainText("No film profiles yet. Make one with Film Characterization (Advanced mode > Sensitometry), or import one.")
            return
        try:
            p = self.store.load(ident)
        except fp.ProfileError as exc:
            self.detail.setPlainText(f"This profile cannot be read: {exc}")
            return
        self.detail.setPlainText(_text(p))
        self.buttons["use"].setEnabled(p.usable_for_inversion())
        self.buttons["use"].setToolTip("" if p.usable_for_inversion() else "Only measured or supplied profiles with R, G and B curves can drive an inversion.")

    def _use(self) -> None:
        ident = self._current()
        if ident:
            self.use_for_photo.emit(ident)

    def _view(self) -> None:
        ident = self._current()
        if ident:
            self.use_in_viewer.emit(ident)

    def _duplicate(self) -> None:
        ident = self._current()
        if ident:
            twin = self.store.duplicate(ident)
            self.refresh(twin.id)
            self.changed.emit()

    def _edit(self) -> None:
        ident = self._current()
        if not ident:
            return
        p = self.store.load(ident)
        vals = _ask(self, "Edit profile details", [("Name", p.name), ("Film stock (optional)", p.film_stock), ("Process (optional)", p.process), ("Notes", p.notes)])
        if vals is None:
            return
        p.name, p.film_stock, p.process, p.notes = vals[0] or p.name, vals[1], vals[2], vals[3]
        self.store.save(p)
        self.refresh(p.id)
        self.changed.emit()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import a film profile", "", "Film profiles (*.json *.efasprofile)")
        if not path:
            return
        if path.lower().endswith(profile_bundle.EXTENSION):
            self._import_bundle(path)
            return
        try:
            p = self.store.import_file(path)
        except fp.ProfileError as exc:
            QMessageBox.warning(self, "Film Profiles", str(exc))
            return
        self.refresh(p.id)
        self.changed.emit()

    def _import_bundle(self, path: str) -> None:
        """Check a shared bundle, show what it is and what the checks do and do not show, and import it only after a yes."""
        rep = profile_bundle.inspect_bundle(path)
        if not rep.ok:
            QMessageBox.warning(self, "Shared profile", profile_bundle.describe(rep))
            return
        ask = QMessageBox(QMessageBox.Icon.Question, "Import shared profile", profile_bundle.describe(rep), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        ask.button(QMessageBox.StandardButton.Yes).setText("Import")
        if ask.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            res = profile_bundle.import_bundle(path, self.store, self.c.setup_store())
        except (profile_bundle.BundleError, OSError, fp.ProfileError) as exc:
            QMessageBox.warning(self, "Shared profile", str(exc))
            return
        self.refresh(res.profile.id)
        self.changed.emit()

    def _share(self) -> None:
        ident = self._current()
        if not ident:
            return
        p = self.store.load(ident)
        vals = _ask(self, "Share this profile", [("Your name (optional)", ""), ("Note for the receiver (optional)", "")])
        if vals is None:
            return
        setup = None
        setups = self.c.setup_store().list()
        if setups and QMessageBox.question(self, "Share this profile", "Include a camera set-up with it?\n\nThe set-up holds the camera's measured black levels, noise and flare, which the receiver can use only if "
                                           "their equipment is the same.") == QMessageBox.StandardButton.Yes:
            names = [s["name"] for s in setups]
            name, ok = QInputDialog.getItem(self, "Share this profile", "Camera set-up:", names, 0, False)
            if ok:
                setup = self.c.setup_store().load(setups[names.index(name)]["id"])
        path, _ = QFileDialog.getSaveFileName(self, "Save the shared profile", f"{p.name}{profile_bundle.EXTENSION}", "Shared film profile (*.efasprofile)")
        if not path:
            return
        try:
            fingerprint = profile_bundle.export_bundle(p, path, setup, vals[0], vals[1], photoeditor.__version__)
        except (OSError, fp.ProfileError) as exc:
            QMessageBox.warning(self, "Share this profile", str(exc))
            return
        QMessageBox.information(self, "Share this profile", f"Saved. The fingerprint of this bundle is:\n\n{fingerprint}\n\nSend it to the receiver by a different route "
                                "(a message, say) so they can check the file they got is the one you made.")

    def _export(self) -> None:
        ident = self._current()
        if not ident:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export the film profile", f"{self.store.load(ident).name}.json", "Film profiles (*.json)")
        if path:
            try:
                self.store.export(ident, path)
            except (OSError, fp.ProfileError) as exc:
                QMessageBox.warning(self, "Film Profiles", str(exc))

    def _delete(self) -> None:
        ident = self._current()
        if not ident:
            return
        if QMessageBox.question(self, "Delete profile", "Delete this film profile? Photos set to use it fall back to the standard inversion.") != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(ident)
        self.refresh()
        self.changed.emit()

    def _compare(self) -> None:
        ident = self._current()
        others = [r for r in self.store.list() if r["id"] != ident]
        if not ident or not others:
            QMessageBox.information(self, "Film Profiles", "Needs a second profile to compare with.")
            return
        names = [r["name"] for r in others]
        name, ok = QInputDialog.getItem(self, "Compare profiles", "Compare with:", names, 0, False)
        if not ok:
            return
        other = others[names.index(name)]
        rows = fp.compare(self.store.load(ident), self.store.load(other["id"]))
        dlg = QDialog(self)
        dlg.setWindowTitle("Compare film profiles")
        dlg.resize(620, 420)
        col = QVBoxLayout(dlg)
        table = QTableWidget(len(rows), 4)
        table.setHorizontalHeaderLabels(["", self.store.load(ident).name, name, "Difference"])
        table.horizontalHeader().setStretchLastSection(True)
        for i, r in enumerate(rows):
            def fmt(v):
                return "-" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
            for j, v in enumerate((r["label"], fmt(r["a"]), fmt(r["b"]), fmt(r["difference"]))):
                item = QTableWidgetItem(v)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                table.setItem(i, j, item)
        col.addWidget(table)
        col.addWidget(QLabel("Profiles describe the roll, exposure and processing they were made from. A difference here is not necessarily a better or worse film."))
        dlg.exec()


def _pixmap(arr: np.ndarray) -> QPixmap:
    a = np.ascontiguousarray(arr)
    h, w = a.shape[:2]
    return QPixmap.fromImage(QImage(a.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy())


class ABCompareDialog(QDialog):
    """The standard inversion and the curve-informed one, flipped at the same spot, with numbers. Choosing the curve-informed one is a separate, explicit step."""

    adopt = pyqtSignal(str)

    def __init__(self, controller, profile_id: str, setup_id: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compare Inversion Methods")
        self.resize(980, 720)
        self.profile_id = profile_id
        col = QVBoxLayout(self)
        self.result = controller.compare_inversions(profile_id, setup_id)
        if "error" in self.result:
            col.addWidget(QLabel(self.result["error"]))
            close = QPushButton("Close")
            close.clicked.connect(self.reject)
            col.addWidget(close)
            return
        r = self.result
        row = QHBoxLayout()
        self.std_btn = QPushButton("Standard")
        self.std_btn.setCheckable(True)
        self.std_btn.setChecked(True)
        self.cur_btn = QPushButton(f"Curve-informed ({r['profile']})")
        self.cur_btn.setCheckable(True)
        self.std_btn.clicked.connect(lambda: self._show("classic"))
        self.cur_btn.clicked.connect(lambda: self._show("curve"))
        row.addWidget(self.std_btn)
        row.addWidget(self.cur_btn)
        col.addLayout(row)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(640, 420)
        col.addWidget(self.image, 1)
        m = r["metrics"]
        lines = [
            "Both pictures use the same neutral settings, size and framing: only the inversion differs.",
            f"RMS difference in lightness {m['rms_delta_lstar']:.1f} L*; {m['share_over_5_lstar'] * 100:.0f}% of the picture differs by more than 5 L*; "
            f"lightness correlation {m['luminance_correlation']:.3f}.",
            f"Lightness range (1st to 99th percentile): standard {m['lstar_range_a'][0]:.0f} to {m['lstar_range_a'][1]:.0f}, curve-informed {m['lstar_range_b'][0]:.0f} to {m['lstar_range_b'][1]:.0f}.",
            f"Mean colour shift (curve-informed minus standard), R/G/B: {m['mean_shift'][0]:+.3f} / {m['mean_shift'][1]:+.3f} / {m['mean_shift'][2]:+.3f}.",
            f"{r['covered'] * 100:.0f}% of the picture is inside the profile's measured density range.",
        ] + r["notes"] + [
            "The standard method is a display-referred stretch built to look good; the curve-informed one estimates exposure through a measured curve. A difference does not "
            "prove either is right. The curve-informed method is only as good as the profile and the film base sample."
        ]
        info = QPlainTextEdit("\n".join(lines))
        info.setReadOnly(True)
        info.setMaximumHeight(150)
        col.addWidget(info)
        tone = QTableWidget(len(r["tone"]), 4)
        tone.setHorizontalHeaderLabels(["Percentile of density", "Density above base (G)", "L* standard", "L* curve-informed"])
        tone.horizontalHeader().setStretchLastSection(True)
        tone.setMaximumHeight(170)
        for i, t in enumerate(r["tone"]):
            for j, v in enumerate((f"{t['quantile']}", f"{t['density_above_base']:.2f}", f"{t['lstar_a']:.1f}", f"{t['lstar_b']:.1f}")):
                item = QTableWidgetItem(v)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                tone.setItem(i, j, item)
        col.addWidget(tone)
        buttons = QHBoxLayout()
        use = QPushButton("Use Curve-Informed for This Photo")
        use.clicked.connect(self._adopt)
        keep = QPushButton("Keep the Standard Method")
        keep.clicked.connect(self.reject)
        buttons.addWidget(use)
        buttons.addWidget(keep)
        col.addLayout(buttons)
        self._pix = {"classic": _pixmap(r["classic"]), "curve": _pixmap(r["curve"])}
        self._show("classic")

    def _show(self, which: str) -> None:
        self.std_btn.setChecked(which == "classic")
        self.cur_btn.setChecked(which == "curve")
        pm = self._pix[which]
        self.image.setPixmap(pm.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_pix"):
            self._show("curve" if self.cur_btn.isChecked() else "classic")

    def _adopt(self) -> None:
        self.adopt.emit(self.profile_id)
        self.accept()


class SetupsDialog(QDialog):
    """Saved calibrations of the camera and backlight: look at them, rename them, delete them."""

    changed = pyqtSignal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camera Set-ups")
        self.resize(640, 440)
        self.store = controller.setup_store()
        outer = QHBoxLayout(self)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show)
        outer.addWidget(self.list, 2)
        right = QVBoxLayout()
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        right.addWidget(self.detail, 1)
        edit = QPushButton("Edit Details...")
        edit.clicked.connect(self._edit)
        delete = QPushButton("Delete")
        delete.clicked.connect(self._delete)
        right.addWidget(edit)
        right.addWidget(delete)
        outer.addLayout(right, 3)
        self.refresh()

    def _current(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def refresh(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for r in self.store.list():
            item = QListWidgetItem(f"{r['name']}  -  {r['camera'] or 'camera not named'}")
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._show()

    def _show(self, *_a) -> None:
        ident = self._current()
        if ident is None:
            self.detail.setPlainText("No camera set-ups yet. Make one in Film Characterization > Scanner calibration, by scanning a calibrated step tablet.")
            return
        try:
            s = self.store.load(ident)
        except fp.ProfileError as exc:
            self.detail.setPlainText(f"This set-up cannot be read: {exc}")
            return
        lines = [f"{s.name}", f"Camera: {s.camera or 'not recorded'}", f"Lens: {s.lens or 'not recorded'}", f"Light source: {s.light_source or 'not recorded'}"]
        if s.flare_fraction is not None:
            se = f" +/- {s.flare_fraction_se * 100:.3f}%" if s.flare_fraction_se is not None else ""
            lines.append(f"Flare fraction {s.flare_fraction * 100:.3f}%{se} (measured with a step tablet)")
        if s.usable_density_max:
            lines.append("Usable density range (R, G, B): " + ", ".join(f"{d:.2f}" for d in s.usable_density_max))
        if s.linearity_error_percent is not None:
            lines.append(f"Sensor linearity error {s.linearity_error_percent:.2f}%")
        if s.noise_sigma:
            lines.append("Read noise (share of range, R, G, B): " + ", ".join(f"{n:.5f}" for n in s.noise_sigma))
        if s.settings:
            lines.append("Settings: " + ", ".join(f"{k} {v}" for k, v in s.settings.items() if v is not None))
        if s.calibration.get("date"):
            lines.append(f"Calibrated {s.calibration['date']}")
        lines.append("This describes the set-up it was made in. Camera-band densities, not Status M.")
        if s.notes:
            lines.append(f"Notes: {s.notes}")
        self.detail.setPlainText("\n".join(lines))

    def _edit(self) -> None:
        ident = self._current()
        if not ident:
            return
        s = self.store.load(ident)
        vals = _ask(self, "Edit camera set-up", [("Name", s.name), ("Camera", s.camera), ("Lens", s.lens), ("Light source", s.light_source), ("Notes", s.notes)])
        if vals is None:
            return
        s.name, s.camera, s.lens, s.light_source, s.notes = vals[0] or s.name, vals[1], vals[2], vals[3], vals[4]
        self.store.save(s)
        self.refresh()
        self.changed.emit()

    def _delete(self) -> None:
        ident = self._current()
        if ident and QMessageBox.question(self, "Delete set-up", "Delete this camera set-up?") == QMessageBox.StandardButton.Yes:
            self.store.delete(ident)
            self.refresh()
            self.changed.emit()
