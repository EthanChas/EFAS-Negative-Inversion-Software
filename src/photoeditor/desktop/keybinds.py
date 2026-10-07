"""The Qt side of the rebindable keys: turning a key event into the action it is bound to."""

from PyQt6.QtCore import QKeyCombination, Qt
from PyQt6.QtGui import QKeyEvent, QKeySequence

from ..features.keybinds import logic as binds
from ..features.settings import logic as app_settings

_MODS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
_MODIFIER_KEYS = {Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock, Qt.Key.Key_unknown}


def normalize(seq: str) -> str:
    """One spelling per key sequence ("ctrl+z" -> "Ctrl+Z")."""
    return QKeySequence(seq, QKeySequence.SequenceFormat.PortableText).toString(QKeySequence.SequenceFormat.PortableText)


def event_sequences(event: QKeyEvent) -> list[str]:
    """The key sequences this event could be bound as, most specific first."""
    try:
        key = Qt.Key(event.key())
    except ValueError:
        return []
    if key in _MODIFIER_KEYS:
        return []
    mods = event.modifiers() & _MODS
    fmt = QKeySequence.SequenceFormat.PortableText
    out = [QKeySequence(QKeyCombination(mods, key)).toString(fmt)]
    if mods & Qt.KeyboardModifier.ShiftModifier and not (Qt.Key.Key_0 <= key <= Qt.Key.Key_9 or Qt.Key.Key_A <= key <= Qt.Key.Key_Z):
        out.append(QKeySequence(QKeyCombination(mods & ~Qt.KeyboardModifier.ShiftModifier, key)).toString(fmt))
    return out


class KeyMap:
    """Which action each key press means."""

    def __init__(self) -> None:
        self._seq: dict[str, str] = {}
        self._by_seq: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self._seq = binds.bindings(app_settings.get("keybinds"))
        self._by_seq = {}
        for action in binds.ACTIONS:
            seq = self._seq.get(action.id, "")
            if seq and action.kind == "key":
                self._by_seq.setdefault(normalize(seq).casefold(), action.id)

    def sequence(self, action_id: str) -> str:
        return self._seq.get(action_id, "")

    def all(self) -> dict[str, str]:
        return dict(self._seq)

    def action_for(self, event: QKeyEvent) -> str | None:
        """The (non-menu) action bound to this key press, or None."""
        for seq in event_sequences(event):
            found = self._by_seq.get(seq.casefold())
            if found:
                return found
        return None
