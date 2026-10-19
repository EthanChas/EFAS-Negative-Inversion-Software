"""The dialogs for sharing presets: choosing the file to export to or import from, saying what went in and what was left out, and asking what to do with names that are already taken.
The file format and every check on what comes out of a file are in features/lookpresets/share.py; the controller reads and writes the presets."""
import os
import re

from PyQt6.QtCore import QObject, QStandardPaths
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from ...features.lookpresets import share
from ...features.presettree import logic as tree
from ..controller import AppController

_NOT_IN_A_FILE_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _documents() -> str:
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or os.path.expanduser("~")


def _notes_text(notes: list[str]) -> str:
    return "\n".join("- " + n[:1].upper() + n[1:] + "." for n in notes)


def ask_import(parent: QWidget | None, pack: share.Pack, conflicts: int, filename: str) -> str | None:
    """What to do with the presets in a file the person chose: KEEP_BOTH, REPLACE or SKIP (when some names are already taken), or the first of these when none are. None: cancel."""
    box = QMessageBox(parent)
    box.setWindowTitle("Import Presets")
    box.setIcon(QMessageBox.Icon.Question)
    text = f"{filename} has {pack.describe()}" + (f", made by {pack.made_by}" if pack.made_by else "") + "."
    if pack.folders and pack.looks:
        text += f"\nThey go in {len(pack.folders)} folder{'s' if len(pack.folders) != 1 else ''}, which are made if you do not have them."
    if pack.dropped:
        text += f"\n{pack.dropped} preset{'s' if pack.dropped != 1 else ''} in the file could not be used and will be left out."
    if pack.notes:
        text += "\n\nPlease note:\n" + _notes_text(pack.notes)
    answers: dict = {}
    if conflicts:
        text += f"\n\n{conflicts} of them {'has a name' if conflicts == 1 else 'have names'} you already use. What should happen to {'it' if conflicts == 1 else 'those'}?"
        answers[box.addButton("Keep Both", QMessageBox.ButtonRole.AcceptRole)] = share.KEEP_BOTH
        answers[box.addButton("Replace Mine", QMessageBox.ButtonRole.DestructiveRole)] = share.REPLACE
        answers[box.addButton("Skip Those", QMessageBox.ButtonRole.ActionRole)] = share.SKIP
        text += "\n\nKeep Both adds the new one beside yours with ' (imported)' on its name. Nothing of yours is changed unless you choose Replace Mine."
    else:
        answers[box.addButton("Import", QMessageBox.ButtonRole.AcceptRole)] = share.KEEP_BOTH
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(next(iter(answers)))
    box.setEscapeButton(cancel)
    box.setText(text)
    box.exec()
    return answers.get(box.clickedButton())


class PresetSharing(QObject):
    """Export presets to a file and import them from one, with the questions in between."""

    def __init__(self, controller: AppController, parent: QObject | None = None):
        super().__init__(parent)
        self._controller = controller

    def _default_name(self, kind: str, target: str) -> str:
        if kind in ("preset", "folder"):
            stem = tree.leaf(target) or "presets"
        elif kind == "module":
            stem = self._controller.module_title(target) + " presets"
        else:
            stem = "My EFAS presets"
        return _NOT_IN_A_FILE_NAME.sub("_", stem).strip(" .") + share.EXTENSION

    def export_presets(self, parent: QWidget | None, kind: str, target: str = "") -> bool:
        """Export a preset ("preset"), a folder of My Presets ("folder"), everything ("all") or one module's presets ("module", with its id as the target). True when a file was written."""
        c = self._controller
        names, modules, _folders = c.preset_share_scope(kind, target)
        if not names and not modules:
            c.notice.emit("There are no presets to export")
            return False
        path, _filter = QFileDialog.getSaveFileName(parent, "Export Presets", os.path.join(_documents(), self._default_name(kind, target)), share.FILE_FILTER)
        if not path:
            return False
        if not os.path.splitext(path)[1]:
            path += share.EXTENSION
        try:
            pack = c.export_presets(path, kind, target)
        except (OSError, share.ShareError) as exc:
            QMessageBox.warning(parent, "Export Presets", f"The presets could not be exported: {exc}")
            return False
        if pack.notes or pack.dropped:
            extra = f"\n\n{pack.dropped} preset{'s' if pack.dropped != 1 else ''} held nothing that could be shared and {'was' if pack.dropped == 1 else 'were'} left out." if pack.dropped else ""
            QMessageBox.information(parent, "Export Presets", f"Exported {pack.describe()} to {path}.\n\nPlease note:\n{_notes_text(pack.notes)}{extra}" if pack.notes else f"Exported {pack.describe()} to {path}.{extra}")
        return True

    def import_presets(self, parent: QWidget | None) -> bool:
        """Choose a file, say what is in it, and add the presets. True when something was imported."""
        c = self._controller
        path, _filter = QFileDialog.getOpenFileName(parent, "Import Presets", _documents(), share.FILE_FILTER)
        if not path:
            return False
        try:
            pack = c.read_preset_file(path)
        except share.ShareError as exc:
            QMessageBox.warning(parent, "Import Presets", str(exc))
            return False
        except OSError as exc:
            QMessageBox.warning(parent, "Import Presets", f"The file could not be read: {exc}")
            return False
        policy = ask_import(parent, pack, c.preset_import_conflicts(pack), os.path.basename(path))
        if policy is None:
            return False
        result = c.import_presets(pack, policy)
        return bool(result.total() or result.folders)
