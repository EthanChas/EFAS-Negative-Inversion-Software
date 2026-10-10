"""A conversion record: everything that produced an exported picture, written beside it as JSON so a conversion can be reproduced or audited later.
Standard library only, no Qt/UI.

It records what the app knew when it exported: the source file (with a SHA-256 of its bytes), the inversion method and profile, the film base, the saved
edits, the export options and the version. It records nothing about the person.
"""

import datetime as dt
import hashlib
import json
import os

FORMAT = "efas-conversion-record"
VERSION = 1


def file_sha256(path: str, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
    except ImportError:
        pass
    return str(value)


def build_record(app_version: str, source: str, output: str, kind: str, options: dict, edits: dict | None, inversion: dict | None, film_base: dict | None,
                 profile: dict | None, scan: dict | None, notes: list[str] | None = None) -> dict:
    """Assemble the record. Anything unknown is left out, not invented."""
    rec = {
        "format": FORMAT, "version": VERSION, "made": dt.datetime.now().replace(microsecond=0).isoformat(), "app": {"name": "EFAS Negative Inversion Software", "version": app_version},
        "source": {"file": os.path.basename(source), "path": source, "sha256": file_sha256(source) if os.path.isfile(source) else None},
        "output": {"file": os.path.basename(output), "kind": kind},
        "export_options": options, "saved_edits": edits, "inversion": inversion or {"engine": "classic"}, "film_base": film_base, "film_profile": profile, "scan": scan,
        "notes": notes or [],
    }
    return _jsonable(rec)


def write_record(dest_picture: str, record: dict) -> str:
    """Write the record next to the picture as `<picture>.efas.json`; returns its path."""
    path = dest_picture + ".efas.json"
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return path
