"""The slideshow's music: the three built-in pieces (made once, kept as WAV files) and the person's own .wav and .mp3 files, which are copied into the app's folder - no Qt.

A choice is a short text: "off", "builtin:<id>" for a built-in piece, or "user:<file name>" for one the person added."""
import os
import shutil

from ..datadir import app_data_dir
from . import synth

MUSIC_DIR = "slideshow-music"
BUILTIN_SUBDIR = "built-in"
USER_SUBDIR = "yours"
ALLOWED = (".wav", ".mp3")
BUILTIN_VERSION = 1          # raise it when a piece is changed, so the old file is made again
OFF = "off"
MAX_IMPORT_BYTES = 200 * 1024 * 1024   # a song or an hour of ambience; anything bigger is probably not what was meant


def music_dir() -> str:
    return os.path.join(app_data_dir(), MUSIC_DIR)


def _builtin_dir() -> str:
    return os.path.join(music_dir(), BUILTIN_SUBDIR)


def _user_dir() -> str:
    return os.path.join(music_dir(), USER_SUBDIR)


def builtin_path(track_id: str) -> str:
    return os.path.join(_builtin_dir(), f"{track_id}-v{BUILTIN_VERSION}.wav")


def builtin_ready(track_id: str) -> bool:
    return os.path.isfile(builtin_path(track_id))


def ensure_builtin(track_id: str) -> str:
    """The WAV file of a built-in piece, made now if it is not there yet (a few seconds)."""
    path = builtin_path(track_id)
    if not os.path.isfile(path):
        os.makedirs(_builtin_dir(), exist_ok=True)
        tmp = path + ".part"
        synth.write_wav(tmp, synth.make_track(track_id))
        os.replace(tmp, path)
    return path


def ensure_all_builtin() -> None:
    for track_id in synth.TRACKS:
        ensure_builtin(track_id)


def is_valid(path: str) -> str:
    """"" when this looks like a .wav or .mp3 file the slideshow can play, else the reason it does not."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in ALLOWED:
        return "Only .wav and .mp3 files can be added."
    try:
        size = os.path.getsize(path)
        if size < 1024:
            return "That file is too small to be music."
        if size > MAX_IMPORT_BYTES:
            return "That file is bigger than 200 MB."
        with open(path, "rb") as f:
            head = f.read(12)
    except OSError as exc:
        return f"It could not be read ({exc.strerror or 'error'})."
    if ext == ".wav" and not (head[:4] == b"RIFF" and head[8:12] == b"WAVE"):
        return "That does not look like a WAV file."
    if ext == ".mp3" and not (head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)):
        return "That does not look like an MP3 file."
    return ""


def user_tracks() -> list[str]:
    """The file names of the music the person has added, in alphabetical order."""
    try:
        names = [n for n in os.listdir(_user_dir()) if os.path.splitext(n)[1].lower() in ALLOWED]
    except OSError:
        return []
    return sorted(names, key=str.casefold)


def import_files(paths: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Copy these files into the music folder. -> (the names now in the library, [(path, why it was not added)]). A name already taken gets " (2)" and so on."""
    added: list[str] = []
    refused: list[tuple[str, str]] = []
    os.makedirs(_user_dir(), exist_ok=True)
    for path in paths:
        reason = is_valid(path)
        if reason:
            refused.append((path, reason))
            continue
        base, ext = os.path.splitext(os.path.basename(path))
        name, n = base + ext.lower(), 1
        while os.path.exists(os.path.join(_user_dir(), name)):
            n += 1
            name = f"{base} ({n}){ext.lower()}"
        try:
            shutil.copyfile(path, os.path.join(_user_dir(), name))
        except OSError as exc:
            refused.append((path, f"It could not be copied ({exc.strerror or 'error'})."))
            continue
        added.append(name)
    return added, refused


def remove_user_track(name: str) -> bool:
    """Take a track out of the library (the app's own copy; the original file is not touched). False when it is not there."""
    path = os.path.join(_user_dir(), os.path.basename(name))
    if os.path.basename(name) != name or not os.path.isfile(path):
        return False
    os.remove(path)
    return True


def choices() -> list[tuple[str, str]]:
    """[(choice, label)] for the music drop-down: off, the built-in pieces, then the person's own."""
    out = [(OFF, "No music")]
    out += [(f"builtin:{track_id}", label) for track_id, label in synth.TRACKS.items()]
    out += [(f"user:{name}", f"{os.path.splitext(name)[0]}  (yours)") for name in user_tracks()]
    return out


def path_for(choice: str, make: bool = False) -> str | None:
    """The file a choice plays, or None for "off", a track that is not there, or a built-in piece not made yet (make=True makes it now)."""
    if choice.startswith("builtin:"):
        track_id = choice.split(":", 1)[1]
        if track_id not in synth.TRACKS:
            return None
        if make:
            return ensure_builtin(track_id)
        return builtin_path(track_id) if builtin_ready(track_id) else None
    if choice.startswith("user:"):
        name = choice.split(":", 1)[1]
        path = os.path.join(_user_dir(), os.path.basename(name))
        return path if os.path.basename(name) == name and os.path.isfile(path) else None
    return None


def clean_choice(choice) -> str:
    """A saved choice made safe: "off" unless it names something that exists."""
    if not isinstance(choice, str):
        return OFF
    if choice.startswith("builtin:") and choice.split(":", 1)[1] in synth.TRACKS:
        return choice
    if choice.startswith("user:") and path_for(choice) is not None:
        return choice
    return OFF
