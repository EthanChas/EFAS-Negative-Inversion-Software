"""EFAS from the command line: convert photos with their saved edits, list export presets, report on a photo or a roll, and merge scans, with no window.

    python -m photoeditor convert ROLL_FOLDER --preset "Print" --out OUT_FOLDER
    python -m photoeditor presets
    python -m photoeditor info IMG_0001.CR2
    python -m photoeditor check-roll ROLL_FOLDER
    python -m photoeditor merge --bracket A.CR2 B.CR2 C.CR2 --times 0.01 0.04 0.16 --out merged.tif

It reads the same data folder as the editor (edits, film bases, export presets), so a roll set up in the editor converts here exactly as it would
there. The packaged Windows app has no console, so use these from a source install. Exit status: 0 done, 1 some photos failed, 2 bad arguments.
"""

import argparse
import json
import os
import sys

COMMANDS = ("convert", "presets", "info", "check-roll", "merge", "version")


class UsageError(Exception):
    pass


def _out(text: str = "") -> None:
    print(text, flush=True)


def _collect(paths: list[str], recursive: bool) -> list[str]:
    from .features.browse.logic import list_images_in_folder
    from .features.open_image.logic import is_supported

    found: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            if recursive:
                for root, dirs, files in os.walk(p):
                    dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                    found.extend(list_images_in_folder(root))
            else:
                found.extend(list_images_in_folder(p))
        elif os.path.isfile(p):
            if not is_supported(p):
                raise UsageError(f"{p} is not a photo type EFAS opens.")
            found.append(p)
        else:
            raise UsageError(f"{p} does not exist.")
    return list(dict.fromkeys(os.path.abspath(p) for p in found))


def _saved_presets() -> list[dict]:
    """The presets as the editor's Export panel has them (your own and the built-in ones), or the built-in ones before the editor has been run."""
    from .features.export import logic as X

    presets = None
    try:
        from .desktop.settings_store import qsettings

        presets = json.loads(qsettings().value("export/presets", "") or "null")
    except Exception:
        presets = None
    if not isinstance(presets, list) or not all(isinstance(p, dict) and "name" in p for p in presets):
        presets = []
    have = {p["name"] for p in presets}
    presets += [{"name": n, "options": X.ExportOptions.from_dict(v).to_dict()} for n, v in X.PRESETS.items() if n not in have]
    return presets


def find_preset(query: str) -> tuple[str, dict]:
    """A preset by name: an exact match, else the only one whose name contains the text (case does not matter)."""
    presets = _saved_presets()
    exact = [p for p in presets if p["name"].lower() == query.lower()]
    near = exact or [p for p in presets if query.lower() in p["name"].lower()]
    if not near:
        raise UsageError(f"No export preset matches '{query}'. Run 'presets' to see them.")
    if len(near) > 1:
        raise UsageError(f"'{query}' matches several presets: " + "; ".join(p["name"] for p in near))
    return near[0]["name"], near[0].get("options") or {}


def build_jobs(args) -> list:
    from .features.export import logic as X

    chosen = [find_preset(q) for q in (args.preset or [])] or [("Command line", X.ExportOptions().to_dict())]
    jobs = []
    for name, values in chosen:
        o = X.ExportOptions.from_dict(values)
        if args.format:
            o.fmt = args.format
        if args.quality is not None:
            o.jpeg_quality = o.webp_quality = args.quality
        if args.long_edge:
            o.size_mode, o.long_edge = "long_edge", args.long_edge
        if args.kind:
            o.output_kind = args.kind
        if args.record:
            o.write_record = True
        if args.versions:
            o.include_versions = True
        if args.sharpen is not None:
            o.output_sharpen = max(0, min(100, args.sharpen))
        if args.bit_depth:
            o.bit_depth = args.bit_depth
        if args.out:
            o.dest_mode, o.folder = "folder", os.path.abspath(args.out)
        else:
            o.dest_mode = "beside"
            o.subfolder = o.subfolder or "Export"
        o.on_conflict = "overwrite" if args.overwrite else "skip" if args.skip_existing else "rename"
        if len(chosen) > 1:
            o.preset_folders = True
        jobs.append((name, o))
    return jobs


_scratch_db: list[str] = []


def _db_path() -> str:
    """The editor's database. Before the editor has ever run there is none, and nothing is created in its place: a throwaway empty one stands in."""
    import tempfile

    from .features.datadir import app_data_dir

    real = os.path.join(app_data_dir(), "photoeditor.db")
    if os.path.exists(real):
        return real
    if not _scratch_db:
        _scratch_db.append(os.path.join(tempfile.mkdtemp(prefix="efas-cli-"), "photoeditor.db"))
    return _scratch_db[0]


def cmd_convert(args) -> int:
    from .desktop.export_worker import export_photos

    paths = _collect(args.paths, args.recursive)
    if not paths:
        raise UsageError("No photos found.")
    jobs = build_jobs(args)
    if _db_path() in _scratch_db:
        _out("Note: no EFAS data folder was found, so photos are converted with default settings (no saved edits).")

    def progress(done, total, text):
        if not args.quiet:
            _out(f"[{done}/{total}] {text}")

    summary = export_photos(paths, jobs, _db_path(), progress=progress)
    _out(f"Wrote {len(summary['done'])} file(s); {len(summary['skipped'])} skipped; {len(summary['failed'])} failed.")
    for path, why in summary["failed"]:
        _out(f"  FAILED {path}: {why}")
    for path, why in summary.get("notes", []):
        _out(f"  NOTE {os.path.basename(path)}: {why}")
    if args.json:
        _out(json.dumps({"done": summary["done"], "skipped": summary["skipped"], "failed": [list(f) for f in summary["failed"]]}, indent=2))
    return 1 if summary["failed"] else 0


def cmd_presets(args) -> int:
    for p in _saved_presets():
        o = p.get("options") or {}
        kind = o.get("output_kind", "standard")
        size = f"{o['long_edge']} px long edge" if o.get("size_mode") == "long_edge" else "original size"
        _out(f"{p['name']}  [{o.get('fmt', 'jpeg')}, {size}{'' if kind == 'standard' else ', ' + kind}]")
    return 0


def cmd_info(args) -> int:
    from .features.persistence import edit_store

    conn = edit_store.connect(_db_path())
    code = 0
    try:
        for path in _collect(args.paths, False):
            _out(path)
            saved = edit_store.load_edit_state(conn, path)
            _out(f"  saved edits: {'yes' if saved else 'no'}")
            _out(f"  rating: {edit_store.get_rating(conn, path)}   flag: {edit_store.get_flag(conn, path) or '-'}   "
                 f"tags: {', '.join(edit_store.get_tags(conn, [path]).get(path, [])) or '-'}")
            _out(f"  hidden from the Workbench: {'yes' if os.path.normcase(os.path.abspath(path)) in edit_store.hidden_keys(conn) else 'no'}")
            base = edit_store.get_linear_ref(conn, edit_store.folder_key(path), "base")
            _out(f"  film base for this folder: {'sampled' if base else 'not sampled'}")
            from .features.densitometry import processor as dproc

            if dproc.is_measurable(path) and not args.fast:
                from .features.densitometry import analysis, base as dbase, quality

                scan = dproc.decode_linear(path)
                sample = dbase.from_reference(*base) if base else None
                q = quality.assess(analysis.analyse(scan.rgb, scan.info, sample))
                _out(f"  scan quality: {q.headline}. {q.detail}")
            else:
                _out("  scan quality: not measured" + (" (skipped with --fast)" if args.fast else " (needs a RAW file)"))
    finally:
        conn.close()
    return code


def cmd_check_roll(args) -> int:
    from .features.densitometry import roll_job
    from .features.persistence import edit_store

    paths = roll_job.measurable_paths(_collect(args.paths, False))
    if not paths:
        raise UsageError("No RAW scans found to check.")
    conn = edit_store.connect(_db_path())
    try:
        ref = edit_store.get_linear_ref(conn, edit_store.folder_key(paths[0]), "base")
    finally:
        conn.close()
    report = roll_job.run(paths, tuple(ref[0]) if ref else None, progress=None if args.quiet else (lambda i, n, name: _out(f"[{i + 1}/{n}] {name}")))
    _out(report.headline)
    _out(report.detail)
    for c in report.frames:
        _out(f"  {c.label}: {c.level}, light {c.light_stops:+.2f} stops, colour {c.tint_r:+.2f}/{c.tint_b:+.2f}" + ("  " + " ".join(c.notes) if c.notes else ""))
    return 1 if report.level == "warning" else 0


def cmd_merge(args) -> int:
    from .features.densitometry import merge, merge_job

    if bool(args.bracket) == bool(args.channels):
        raise UsageError("Give either --bracket or --channels.")
    if args.bracket:
        paths = _collect(args.bracket, False)
        times = args.times if args.times else merge_job.read_times(paths)
        if len(times) != len(paths):
            raise UsageError("Give one --times value per scan.")
        mode = "bracket"
    else:
        paths, times, mode = _collect(args.channels, False), None, "channels"
    out = args.out or merge_job.suggested_output(paths[0], mode)
    try:
        info = merge_job.run(mode, paths, times, out, align=not args.no_align, progress=None if args.quiet else (lambda i, n, text: _out(f"[{i + 1}/{n}] {text}")))
    except merge.MergeError as exc:
        _out(str(exc))
        return 1
    _out(info["summary"])
    _out(f"Saved {info['path']}")
    return 0


def cmd_version(args) -> int:
    import photoeditor

    _out(photoeditor.__version__)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="photoeditor", description="EFAS Negative Inversion Software, without the window.")
    p.add_argument("--data-dir", help="use this EFAS data folder instead of the default")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("convert", help="export photos with their saved edits")
    c.add_argument("paths", nargs="+", help="photos and/or folders")
    c.add_argument("--recursive", action="store_true", help="include subfolders of folders")
    c.add_argument("--preset", action="append", help="export preset name (repeat for several); see 'presets'")
    c.add_argument("--out", help="write here (default: an Export folder beside each photo)")
    c.add_argument("--format", choices=["jpeg", "png", "tiff", "webp"])
    c.add_argument("--quality", type=int, help="JPEG/WebP quality 1-100")
    c.add_argument("--long-edge", type=int, help="shrink so the long edge is this many pixels")
    c.add_argument("--kind", choices=["standard", "flat", "linear", "density"], help="export the conversion alone as a 16-bit TIFF")
    c.add_argument("--record", action="store_true", help="also write a conversion record (.json)")
    c.add_argument("--sharpen", type=int, help="sharpen the finished picture at its final size, 0-100")
    c.add_argument("--bit-depth", type=int, choices=[8, 16], help="16 writes a 16-bit TIFF when the photo's edits allow it")
    c.add_argument("--versions", action="store_true", help="also export each photo's virtual copies")
    mode = c.add_mutually_exclusive_group()
    mode.add_argument("--overwrite", action="store_true", help="replace files that already exist")
    mode.add_argument("--skip-existing", action="store_true", help="leave files that already exist")
    c.add_argument("--json", action="store_true", help="print the result as JSON as well")
    c.add_argument("--quiet", action="store_true")
    c.set_defaults(run=cmd_convert)
    sub.add_parser("presets", help="list export presets").set_defaults(run=cmd_presets)
    i = sub.add_parser("info", help="what EFAS knows about photos")
    i.add_argument("paths", nargs="+")
    i.add_argument("--fast", action="store_true", help="skip the scan-quality measurement")
    i.set_defaults(run=cmd_info)
    r = sub.add_parser("check-roll", help="find frames scanned differently from the rest of a roll")
    r.add_argument("paths", nargs="+", help="a folder of RAW scans")
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(run=cmd_check_roll)
    m = sub.add_parser("merge", help="merge scans into one measured 16-bit linear scan")
    m.add_argument("--bracket", nargs="+", help="scans of one frame at different exposure times")
    m.add_argument("--times", nargs="+", type=float, help="their exposure times in seconds (default: read from the files)")
    m.add_argument("--channels", nargs=3, metavar=("RED", "GREEN", "BLUE"), help="scans lit by red, green and blue light")
    m.add_argument("--out", help="the merged TIFF to write")
    m.add_argument("--no-align", action="store_true", help="do not correct small movements between scans")
    m.add_argument("--quiet", action="store_true")
    m.set_defaults(run=cmd_merge)
    sub.add_parser("version", help="print the version").set_defaults(run=cmd_version)
    return p


def main(argv: list[str] | None = None) -> int:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.data_dir:
            os.environ["PHOTOEDITOR_DATA_DIR"] = os.path.abspath(args.data_dir)
        return args.run(args)
    except UsageError as exc:
        print(f"photoeditor: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
