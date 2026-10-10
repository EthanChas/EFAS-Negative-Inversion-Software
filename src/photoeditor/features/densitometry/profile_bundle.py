"""Sharing a film profile (and optionally the camera set-up it was made with) as one `.efasprofile` file, and checking such a file before using it.

The bundle is a zip holding manifest.json, profile.json and optionally setup.json. The manifest records a SHA-256 of every other file, who shared it and
what it claims to be. Checking a bundle proves it is intact and that its numbers are physically sensible. It does not prove who made it or that the
measurement was done well: anyone can write a consistent bundle. The fingerprint (a SHA-256 of the manifest) is meant to be passed on through a second
channel, so the receiver can compare it with the one shown on opening. A profile that arrives this way is always marked as supplied by someone else, never as
measured here. Standard library and numpy only, no Qt.
"""

import hashlib
import json
import os
import uuid
import zipfile
from dataclasses import dataclass, field

import numpy as np

from . import film_profile as fp

FORMAT = "efas-profile-bundle"
VERSION = 1
EXTENSION = ".efasprofile"
FILES = ("manifest.json", "profile.json", "setup.json")
MAX_FILE_BYTES = 2_000_000
MAX_DIP = 0.03
MAX_DENSITY = 6.5


class BundleError(ValueError):
    """The bundle cannot be written or read."""


@dataclass
class BundleReport:
    ok: bool
    problems: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    manifest: dict = field(default_factory=dict)
    profile: fp.FilmProfile | None = None
    setup: fp.CameraSetup | None = None
    fingerprint: str = ""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump(obj) -> bytes:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")


def fingerprint_of(manifest_bytes: bytes) -> str:
    """A short, groupable form of the manifest's SHA-256 for reading out or pasting into a message."""
    h = _sha(manifest_bytes)[:24].upper()
    return "-".join(h[i:i + 6] for i in range(0, 24, 6))


def export_bundle(profile: fp.FilmProfile, path: str, setup: fp.CameraSetup | None = None, author: str = "", note: str = "", version: str = "") -> str:
    """Write `profile` (and `setup`) to `path`. Returns the fingerprint."""
    files = {"profile.json": _dump(profile.to_dict())}
    if setup is not None:
        files["setup.json"] = _dump(setup.to_dict())
    manifest = {
        "format": FORMAT, "version": VERSION, "created": fp.now_iso(), "efas_version": version, "author": author.strip(), "note": note.strip(),
        "profile": {"name": profile.name, "kind": profile.kind, "film": profile.identity_text()},
        "files": {name: {"sha256": _sha(data), "bytes": len(data)} for name, data in files.items()},
    }
    manifest_bytes = _dump(manifest)
    if os.path.splitext(path)[1].lower() != EXTENSION:
        path += EXTENSION
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".part"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", manifest_bytes)
            for name, data in files.items():
                z.writestr(name, data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return fingerprint_of(manifest_bytes)


def _read_members(path: str, problems: list) -> dict:
    out = {}
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            for info in infos:
                if info.filename not in FILES:
                    problems.append(f"The bundle contains an unexpected item ({info.filename[:60]}), so it was not trusted.")
                    return {}
                if info.file_size > MAX_FILE_BYTES:
                    problems.append(f"{info.filename} is unreasonably large.")
                    return {}
            if len({i.filename for i in infos}) != len(infos):
                problems.append("The bundle lists the same file twice.")
                return {}
            for info in infos:
                with z.open(info) as f:
                    out[info.filename] = f.read(MAX_FILE_BYTES + 1)
    except zipfile.BadZipFile:
        problems.append("This is not a valid EFAS profile bundle (the file is damaged or not a bundle).")
    except OSError as exc:
        problems.append(f"The file could not be read: {exc}")
    return out


def _json(data: bytes, name: str, problems: list):
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        problems.append(f"{name} is not valid.")
        return None


def _sanity(profile: fp.FilmProfile, warnings: list, problems: list) -> None:
    for ch, cc in profile.curves.items():
        try:
            curve = cc.curve()
            lo, hi = cc.supported()
        except (fp.ProfileError, ValueError, KeyError, TypeError) as exc:
            problems.append(f"The {ch} curve cannot be rebuilt ({exc}).")
            continue
        if not hi > lo:
            problems.append(f"The {ch} curve has no usable exposure range.")
            continue
        keep = np.array(cc.used, dtype=bool)
        px, py = np.array(cc.x)[keep], np.array(cc.y)[keep]
        if px.size >= 3 and np.ptp(px) > 0 and np.ptp(py) > 0 and np.corrcoef(px, py)[0, 1] < 0:
            problems.append(f"The {ch} curve's measured points fall as exposure rises, which a film's curve does not do. It would invert wrongly.")
            continue
        xs = np.linspace(lo, hi, 60)
        try:
            ys = np.asarray(curve(xs), dtype=np.float64)
        except Exception as exc:
            problems.append(f"The {ch} curve cannot be evaluated ({type(exc).__name__}).")
            continue
        if not np.isfinite(ys).all():
            problems.append(f"The {ch} curve gives values that are not numbers.")
        elif ys.max() > MAX_DENSITY or ys.min() < -0.5:
            problems.append(f"The {ch} curve reaches densities no film can have ({ys.min():.2f} to {ys.max():.2f}).")
        elif (np.diff(ys) < -MAX_DIP).any():
            problems.append(f"The {ch} curve falls as exposure rises, which a film's curve does not do. It would invert wrongly.")
        elif ys[-1] - ys[0] < 0.1:
            problems.append(f"The {ch} curve is almost flat, so it cannot be used to recover exposure.")
        poor = [n for n, f in cc.fits.items() if isinstance(f, dict) and f.get("quality") == "poor"]
        if poor and cc.chosen in poor:
            warnings.append(f"The {ch} curve uses a fit that was rated poor.")
    if profile.kind in ("estimated", "generic"):
        warnings.append(f"The sender marked this profile as '{profile.kind}', so it was not measured from film.")
    tablet = (profile.calibration or {}).get("tablet") or {}
    if profile.kind == "measured" and not tablet.get("densities_are_actual"):
        warnings.append("The step densities behind this profile were nominal, not calibrated, so the curve's absolute scale is approximate.")
    if profile.validity:
        warnings.append("It describes the roll, exposure and processing it was made from. Other rolls of the same film can behave differently.")


def inspect_bundle(path: str) -> BundleReport:
    """Check a bundle without changing anything: integrity, structure, the profile's own validation and the physical sense of its curves."""
    problems: list = []
    warnings: list = []
    members = _read_members(path, problems)
    rep = BundleReport(False, problems, warnings)
    if problems or "manifest.json" not in members:
        if not problems:
            problems.append("The bundle has no manifest.")
        return rep
    manifest = _json(members["manifest.json"], "The manifest", problems)
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        problems.append("This is not an EFAS profile bundle.")
        return rep
    version = manifest.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        problems.append("The bundle has no valid version.")
        return rep
    if version > VERSION:
        problems.append(f"This bundle is version {version}; this copy of EFAS reads up to version {VERSION}. Update EFAS to open it.")
        return rep
    rep.manifest = manifest
    rep.fingerprint = fingerprint_of(members["manifest.json"])
    listed = manifest.get("files")
    if not isinstance(listed, dict) or "profile.json" not in listed:
        problems.append("The manifest does not list a profile.")
        return rep
    for name in members:
        if name == "manifest.json":
            continue
        entry = listed.get(name)
        if not isinstance(entry, dict) or entry.get("sha256") != _sha(members[name]):
            problems.append(f"{name} does not match its checksum. It was damaged or changed after it was shared.")
    for name in listed:
        if name not in members:
            problems.append(f"{name} is listed but missing from the bundle.")
    if problems:
        return rep
    prof_data = _json(members["profile.json"], "The profile", problems)
    if prof_data is not None:
        try:
            rep.profile = fp.FilmProfile.from_dict(prof_data)
        except fp.ProfileError as exc:
            problems.append(str(exc))
    if "setup.json" in members:
        setup_data = _json(members["setup.json"], "The camera set-up", problems)
        if setup_data is not None:
            try:
                rep.setup = fp.CameraSetup.from_dict(setup_data)
            except fp.ProfileError as exc:
                problems.append(str(exc))
    if rep.profile is not None:
        _sanity(rep.profile, warnings, problems)
    rep.ok = not problems
    return rep


@dataclass
class ImportResult:
    profile: fp.FilmProfile
    setup: fp.CameraSetup | None
    report: BundleReport


def import_bundle(path: str, profiles: fp.ProfileStore, setups: fp.SetupStore | None = None, include_setup: bool = True) -> ImportResult:
    """Add the bundle's profile (and set-up) to the data folder as new records, marked as received from someone else. Raises BundleError if the check fails."""
    rep = inspect_bundle(path)
    if not rep.ok or rep.profile is None:
        raise BundleError(" ".join(rep.problems) or "The bundle could not be checked.")
    p = rep.profile
    original = {"kind": p.kind, "id": p.id, "name": p.name, "author": str(rep.manifest.get("author", "")), "shared": str(rep.manifest.get("created", "")),
                "note": str(rep.manifest.get("note", "")), "fingerprint": rep.fingerprint, "checksums_verified": True, "imported": fp.now_iso()}
    p.derived_from = p.derived_from or p.id
    p.id = uuid.uuid4().hex
    if p.kind == "measured":
        p.kind = "supplied"
    p.extras = {**p.extras, "received": original}
    p.created = p.modified = fp.now_iso()
    profiles.save(p)
    s = None
    if include_setup and rep.setup is not None and setups is not None:
        s = rep.setup
        s.extras = {**s.extras, "received": {**original, "kind": "camera set-up"}}
        s.id = uuid.uuid4().hex
        s.created = s.modified = fp.now_iso()
        setups.save(s)
    return ImportResult(p, s, rep)


def describe(rep: BundleReport) -> str:
    """The plain-language summary shown before anything is imported."""
    if not rep.ok:
        return "This bundle failed its checks and will not be imported:\n- " + "\n- ".join(rep.problems)
    m, p = rep.manifest, rep.profile
    lines = [f"Profile: {p.name} ({p.identity_text()})", f"Kind claimed by the sender: {fp.KIND_LABELS.get(p.kind, p.kind)}"]
    if m.get("author"):
        lines.append(f"Shared by: {m['author']}")
    if m.get("created"):
        lines.append(f"Shared on: {m['created']}")
    if m.get("note"):
        lines.append(f"Note: {m['note']}")
    if rep.setup is not None:
        lines.append(f"Includes the camera set-up: {rep.setup.name}")
    lines.append(f"Fingerprint: {rep.fingerprint}")
    lines.append("Checks passed: the files are intact and the curves are physically sensible. This does not show who made it or how carefully it was measured. "
                 "If it matters, ask the sender to read you the fingerprint above.")
    lines.extend("Note: " + w for w in rep.warnings)
    if p.kind == "measured":
        lines.append("It will be added as 'supplied by someone else', not as measured by you.")
    return "\n".join(lines)
