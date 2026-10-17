"""What a camera has to be for the tether window: a live picture, a focus drive and a shutter. No Qt.

The window and the live-view pipeline only ever talk to this interface, so the Canon backend (Canon's EDSDK, over USB) and the practice camera (a made-up film negative, for trying
everything without a camera) are interchangeable, and another make could be added behind it later.
"""

from dataclasses import dataclass, field
from typing import Callable, Protocol

NameFor = Callable[[str], str]   # the file name the camera gave a file -> the name to save it under


class TetherError(RuntimeError):
    """Something went wrong with the camera; the text is fit to show a person."""


@dataclass(frozen=True)
class CameraInfo:
    model: str
    lens: str = ""
    backend: str = ""


@dataclass(frozen=True)
class Capabilities:
    """What the camera can do just now, asked of it and not assumed. `notes` says why a thing is off, so a button that does nothing can explain itself."""

    focus_drive: bool = False
    notes: dict = field(default_factory=dict)

    def note(self, name: str) -> str:
        return self.notes.get(name, "")


class CameraBackend(Protocol):
    """A camera, real or practice. Every method may be called from any thread."""

    def open(self) -> None:
        """Connect and start the live picture. Raises TetherError, with what to check, when it cannot."""

    def close(self) -> None:
        """Stop the live picture and let go of the camera. Safe to call twice, and after a failure."""

    @property
    def info(self) -> CameraInfo: ...

    @property
    def capabilities(self) -> Capabilities: ...

    def live_frame(self) -> tuple[int, bytes | None]:
        """(a number that changes with every new picture, the newest live picture as JPEG bytes - None before the first)."""

    def focus(self, direction: str, size: int = 2, steps: int = 1) -> None:
        """Drive the lens "near" or "far": `size` 1 (finest) to 3 (coarsest), `steps` times. One step can be smaller than the picture's own noise, so a move you can see takes several."""

    def shoot(self, folder: str, name_for: NameFor, settle_s: float = 1.0) -> list[str]:
        """Wait `settle_s` seconds (for the rig to stop shaking), release the shutter without focusing, and save every file it makes into `folder` under the names `name_for` gives
        (one release can make several: RAW and JPEG). Returns their paths; a file is never overwritten."""
