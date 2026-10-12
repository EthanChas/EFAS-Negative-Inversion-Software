"""A problem report: what is needed to understand a bug, with personal details stripped, shown in full before anything leaves the program.

Nothing is sent by this module. The report is text and a zip file; the person reads it, saves it, and attaches it to a GitHub issue themselves. It never
contains photos, edit values, tags, notes or folder names (those are replaced by the file name alone), and it says exactly what it does contain.
"""

import json
import os
import platform
import re
import sys
import zipfile
from dataclasses import dataclass, field
from urllib.parse import quote

from ..datadir import BACKUP_DIR, EDITS_DB, FILM_PROFILES_DIR, LIBRARY_INDEX_DB, app_data_dir
from . import applog

REPO = "EthanChas/EFAS-Negative-Inversion-Software"
ISSUE_URL = f"https://github.com/{REPO}/issues/new"
MAX_URL_BODY = 3500
PACKAGES = ("PyQt6", "numpy", "opencv-python-headless", "Pillow", "rawpy", "onnxruntime", "send2trash")

_WIN_PATH = re.compile(r"[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n]+\\)*[^\\/:*?\"<>|\r\n\s]*")
_UNIX_PATH = re.compile(r"(?<![\w.:>])/(?:[\w.\- ]+/)+[\w.\- ]*[\w.\-]")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def redact(text: str) -> str:
    """Folders removed from every path (the file name is kept so a failure can be tied to its kind of file), and e-mail addresses blanked."""
    def shorten(match: re.Match) -> str:
        p = match.group(0).replace("\\", "/").rstrip("/")
        name = p.rsplit("/", 1)[-1]
        return f"<folder>/{name}" if name else "<folder>"

    text = _WIN_PATH.sub(shorten, text)
    text = _UNIX_PATH.sub(shorten, text)
    return _EMAIL.sub("<email>", text)


def package_versions() -> dict[str, str]:
    from importlib import metadata

    out = {}
    for name in PACKAGES:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = "not installed"
    return out


def system_info(app_version: str) -> dict[str, str]:
    info = {
        "EFAS": app_version, "Installed as": "packaged app" if getattr(sys, "frozen", False) else "source", "System": f"{platform.system()} {platform.release()}",
        "System version": platform.version(), "Machine": platform.machine(), "Python": platform.python_version(),
    }
    try:
        from PyQt6.QtCore import QT_VERSION_STR

        info["Qt"] = QT_VERSION_STR
    except Exception:
        pass
    return info


def settings_snapshot() -> dict:
    """The app's preferences (switches and choices), with any folder shortened. Keybindings are left out."""
    from ..settings import logic as settings

    data = {k: v for k, v in settings.load().items() if k != "keybinds"}
    return {k: (("<folder>" if ("/" in v or "\\" in v) else v) if isinstance(v, str) else v) for k, v in data.items()}


def data_summary() -> dict:
    """How big the data folder's parts are, never what is in them."""
    root = app_data_dir()

    def size(path: str) -> int | None:
        try:
            return os.path.getsize(path)
        except OSError:
            return None

    backups = os.path.join(root, BACKUP_DIR)
    count = len([f for f in os.listdir(backups)]) if os.path.isdir(backups) else 0
    profiles = os.path.join(root, FILM_PROFILES_DIR)
    return {"database_bytes": size(os.path.join(root, EDITS_DB)), "library_index_bytes": size(os.path.join(root, LIBRARY_INDEX_DB)),
            "backups": count, "film_profiles": len([f for f in os.listdir(profiles) if f.endswith(".json")]) if os.path.isdir(profiles) else 0}


@dataclass
class Report:
    title: str = ""
    what: str = ""
    steps: str = ""
    expected: str = ""
    system: dict = field(default_factory=dict)
    packages: dict = field(default_factory=dict)
    settings: dict | None = None
    data: dict | None = None
    log_lines: list | None = None

    def contents(self) -> list[str]:
        """Plain-language list of what this report holds (shown before saving)."""
        out = ["What you typed (title, what happened, steps, what you expected)", "Program, system and library versions"]
        if self.settings is not None:
            out.append("Your preference switches (no photo folders, no key bindings)")
        if self.data is not None:
            out.append("The sizes of the data files (not their contents)")
        if self.log_lines is not None:
            out.append(f"The last {len(self.log_lines)} lines of the program's log, with folders removed from paths")
        out.append("Never included: your photos, edits, tags, notes, roll cards or folder names")
        return out


def build(app_version: str, title: str = "", what: str = "", steps: str = "", expected: str = "", include_log: bool = True, include_settings: bool = True,
          include_data: bool = True, max_log_lines: int = 150) -> Report:
    return Report(
        title=title.strip(), what=what.strip(), steps=steps.strip(), expected=expected.strip(), system=system_info(app_version), packages=package_versions(),
        settings=settings_snapshot() if include_settings else None, data=data_summary() if include_data else None,
        log_lines=[redact(line) for line in applog.read_tail(max_log_lines)] if include_log else None,
    )


def _block(title: str, text: str) -> str:
    return f"### {title}\n{text.strip() or '(not given)'}\n"


def summary_markdown(r: Report) -> str:
    """The short part that goes in the issue itself."""
    system = "\n".join(f"- {k}: {v}" for k, v in r.system.items() if k in ("EFAS", "Installed as", "System", "Python", "Qt"))
    return "\n".join([_block("What happened", r.what), _block("Steps to reproduce", r.steps), _block("What I expected", r.expected), f"### Environment\n{system}\n",
                      "_A full report file (log and details) is attached below if I could add it._\n"])


def full_markdown(r: Report) -> str:
    parts = [f"# EFAS problem report\n\n{r.title}\n" if r.title else "# EFAS problem report\n", summary_markdown(r).rsplit("_A full report", 1)[0]]
    parts.append("### System\n" + "\n".join(f"- {k}: {v}" for k, v in r.system.items()) + "\n")
    parts.append("### Libraries\n" + "\n".join(f"- {k}: {v}" for k, v in r.packages.items()) + "\n")
    if r.settings is not None:
        parts.append("### Preferences\n```json\n" + json.dumps(r.settings, indent=2) + "\n```\n")
    if r.data is not None:
        parts.append("### Data files\n```json\n" + json.dumps(r.data, indent=2) + "\n```\n")
    if r.log_lines is not None:
        parts.append("### Log (latest lines)\n```\n" + "\n".join(r.log_lines) + "\n```\n")
    return "\n".join(parts)


def write_zip(r: Report, path: str) -> str:
    """Save the report as a zip (report.md, plus the log on its own for easy reading). Returns the path."""
    if not path.lower().endswith(".zip"):
        path += ".zip"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".part"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("report.md", full_markdown(r))
            if r.log_lines is not None:
                z.writestr("log.txt", "\n".join(r.log_lines))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return path


def issue_url(r: Report, attachment_name: str = "") -> str:
    """The GitHub new-issue page with the title and the short part of the report filled in. Opening it sends nothing: the person reads it and presses Submit."""
    body = summary_markdown(r)
    if attachment_name:
        body = body.replace("_A full report file (log and details) is attached below if I could add it._", f"_Full report: drag `{attachment_name}` into this box to attach it._")
    body = body[:MAX_URL_BODY]
    title = r.title or "Problem report"
    return f"{ISSUE_URL}?title={quote(title)}&body={quote(body)}"
