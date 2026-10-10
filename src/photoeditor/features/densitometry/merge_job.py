"""Running a merge from files: decode each RAW scan to linear light, merge, save the merged scan beside a sidecar, and describe the result in plain words."""

import os

from . import merge
from .capture import capture_info
from .processor import decode_linear_raw

MODES = ("bracket", "channels")


def suggested_output(first_path: str, mode: str) -> str:
    stem = os.path.splitext(os.path.basename(first_path))[0]
    return os.path.join(os.path.dirname(first_path), f"{stem}_{'merged' if mode == 'bracket' else 'merged-colour'}.tif")


def read_times(paths: list[str]) -> list[float | None]:
    """The exposure time (seconds) each file states, or None where it does not say."""
    return [capture_info(p)["exposure_time"] for p in paths]


def run(mode: str, paths: list[str], times: list[float] | None, out_path: str, align: bool = True, progress=None) -> dict:
    """Merge `paths` into `out_path`. Returns {'path', 'sidecar', 'result', 'summary'}; raises merge.MergeError with a plain message when the input cannot be merged."""
    if mode not in MODES:
        raise merge.MergeError("Unknown merge mode.")
    if mode == "channels" and len(paths) != 3:
        raise merge.MergeError("Choose the red-lit, green-lit and blue-lit scans.")
    if mode == "bracket" and (len(paths) < 2 or not times or len(times) != len(paths) or any(t is None or t <= 0 for t in times)):
        raise merge.MergeError("Give at least two scans, each with its exposure time in seconds.")
    if os.path.normcase(os.path.abspath(out_path)) in {os.path.normcase(os.path.abspath(p)) for p in paths}:
        raise merge.MergeError("The merged scan cannot overwrite one of the scans being merged.")
    scans = []
    for i, p in enumerate(paths):
        if progress:
            progress(i, len(paths) + 2, f"Reading {os.path.basename(p)}")
        try:
            scans.append(decode_linear_raw(p))
        except Exception as exc:
            raise merge.MergeError(f"{os.path.basename(p)} could not be read as a RAW file ({exc}).") from exc
    labels = [os.path.basename(p) for p in paths] if mode == "bracket" else ["red-lit scan", "green-lit scan", "blue-lit scan"]
    if progress:
        progress(len(paths), len(paths) + 2, "Aligning and merging")
    result = merge.merge_exposures(scans, list(times), labels, align=align) if mode == "bracket" else merge.merge_channels(*scans, labels=labels, align=align)
    if progress:
        progress(len(paths) + 1, len(paths) + 2, "Saving")
    sidecar = merge.save_merged(result, out_path)
    return {"path": out_path, "sidecar": sidecar, "result": result, "summary": summarise(result)}


def summarise(result: "merge.MergeResult") -> str:
    lines = [f"Merged {len(result.sources)} scans into one 16-bit linear scan."]
    if result.kind == "bracket":
        lines.append("Share of the picture taken from each exposure: " + ", ".join(f"{s} {c * 100:.0f}%" for s, c in zip(result.sources, result.contribution)) + ".")
        lines.append(f"Noise in the shadows is about {result.noise_gain:.1f} times lower than the shortest exposure alone.")
    moved = [(s, v) for s, v in zip(result.sources, result.shifts) if max(abs(v[0]), abs(v[1])) > 0.05]
    if moved:
        lines.append("Alignment: " + ", ".join(f"{s} moved {v[0]:+.1f}, {v[1]:+.1f} px" for s, v in moved) + ".")
    lines.extend(result.warnings)
    return "\n".join(lines)
