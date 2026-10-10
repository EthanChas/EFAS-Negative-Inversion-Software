"""Running the roll consistency check over a folder's RAW scans (features/densitometry/rollcheck.py)."""

import os

from . import rollcheck
from .processor import decode_linear_raw, is_measurable


def measurable_paths(paths: list[str]) -> list[str]:
    return [p for p in paths if is_measurable(p)]


def run(paths: list[str], reference=None, progress=None) -> rollcheck.RollReport:
    """Read each scan at half size (fast, and plenty for a film-base reading) and compare the frames."""
    stats = []
    for i, p in enumerate(paths):
        if progress:
            progress(i, len(paths), os.path.basename(p))
        try:
            scan = decode_linear_raw(p, half_size=True)
        except Exception:
            continue
        stats.append(rollcheck.frame_stats(os.path.basename(p), scan.rgb, scan.info))
    return rollcheck.compare(stats, reference)
