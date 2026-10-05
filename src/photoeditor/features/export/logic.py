"""Export options and file writing - Pillow + numpy only, no Qt/UI imports.

Covers what the export panel offers: JPEG/PNG/TIFF/WebP encoders with their
own settings, resizing (original / long edge / percent / fit box), DPI,
sRGB profile embedding, grayscale, EXIF copy, and the destination rules
(custom folder or beside the original, optional subfolder and date folders,
filename pattern, conflict handling). The pipeline is 8-bit throughout, so
there is no 16-bit option."""

import os
import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime

import numpy as np
from PIL import Image, ImageFile

FORMATS = ("jpeg", "png", "tiff", "webp")
FORMAT_LABELS = {"jpeg": "JPEG", "png": "PNG", "tiff": "TIFF", "webp": "WebP"}
EXTENSIONS = {"jpeg": ".jpg", "png": ".png", "tiff": ".tif", "webp": ".webp"}

TIFF_COMPRESSIONS = {"none": None, "lzw": "tiff_lzw", "zip": "tiff_adobe_deflate", "packbits": "packbits"}
TIFF_LABELS = {"none": "None", "lzw": "LZW", "zip": "ZIP (Deflate)", "packbits": "PackBits"}
JPEG_SUBSAMPLING = {"444": 0, "422": 1, "420": 2}
JPEG_SUBSAMPLING_LABELS = {"444": "4:4:4 (best)", "422": "4:2:2", "420": "4:2:0 (smallest)"}

SIZE_MODES = ("original", "long_edge", "percent", "fit")
SIZE_MODE_LABELS = {
    "original": "Original size",
    "long_edge": "Long edge (px)",
    "percent": "Scale (%)",
    "fit": "Fit within box (px)",
}
RESAMPLING = {
    "lanczos": Image.Resampling.LANCZOS,
    "bicubic": Image.Resampling.BICUBIC,
    "bilinear": Image.Resampling.BILINEAR,
}
RESAMPLING_LABELS = {"lanczos": "Lanczos (sharpest)", "bicubic": "Bicubic", "bilinear": "Bilinear (softest)"}

DEST_MODES = ("folder", "beside")
DEST_LABELS = {"folder": "A folder", "beside": "Next to each original"}
CONFLICTS = ("rename", "overwrite", "skip")
CONFLICT_LABELS = {"rename": "Add a number", "overwrite": "Overwrite", "skip": "Skip the file"}

SCOPES = ("current", "keepers", "not_rejected", "folder", "edited")
SCOPE_LABELS = {
    "current": "Current image",
    "keepers": "Keepers in the filmstrip folder",
    "not_rejected": "Everything not rejected",
    "folder": "All photos in the filmstrip folder",
    "edited": "Photos with saved edits",
}

_BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TOKEN = re.compile(r"\{(name|n|date|w|h|format|roll|frame)\}")


@dataclass
class ExportOptions:
    fmt: str = "jpeg"
    jpeg_quality: int = 90
    jpeg_progressive: bool = False
    jpeg_subsampling: str = "444"
    png_compress: int = 6
    tiff_compression: str = "lzw"
    webp_quality: int = 90
    webp_lossless: bool = False
    webp_method: int = 4

    size_mode: str = "original"
    long_edge: int = 2048
    percent: float = 50.0
    fit_w: int = 2048
    fit_h: int = 2048
    no_upscale: bool = True
    resample: str = "lanczos"
    dpi: int = 300

    embed_srgb: bool = True
    grayscale: bool = False
    copy_exif: bool = True

    dest_mode: str = "folder"
    folder: str = ""
    subfolder: str = "Export"
    date_folders: bool = False
    pattern: str = "{name}"  # the original file's name, unchanged
    on_conflict: str = "rename"
    preset_folders: bool = False  # one subfolder per export preset
    suffix: str = ""  # per preset: appended to the name, e.g. "_web"
    prefix: str = ""  # per preset: put in front of the name, e.g. "SOCIAL_"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ExportOptions":
        """Tolerant of missing/unknown keys, so saved settings from an older
        or newer version still load."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


PRESETS: dict[str, dict] = {
    "Web (2048 px JPEG)": dict(fmt="jpeg", jpeg_quality=85, jpeg_subsampling="420", size_mode="long_edge", long_edge=2048, dpi=72, embed_srgb=True),
    "Social (1080 px JPEG)": dict(fmt="jpeg", jpeg_quality=90, jpeg_subsampling="420", size_mode="long_edge", long_edge=1080, dpi=72, embed_srgb=True, prefix="SOCIAL_"),
    "High quality JPEG (full size)": dict(fmt="jpeg", jpeg_quality=95, jpeg_subsampling="444", size_mode="original", dpi=300),
    "Print (full-size TIFF)": dict(fmt="tiff", tiff_compression="lzw", size_mode="original", dpi=300),
    "Archive (full-size PNG)": dict(fmt="png", png_compress=6, size_mode="original", dpi=300),
    "Modern web (WebP)": dict(fmt="webp", webp_quality=85, webp_lossless=False, size_mode="long_edge", long_edge=2560, dpi=72),
}


def target_size(width: int, height: int, opts: ExportOptions) -> tuple[int, int]:
    """The output (w, h) for a source of width x height under opts.size_mode."""
    if opts.size_mode == "long_edge":
        scale = max(1, int(opts.long_edge)) / max(width, height)
    elif opts.size_mode == "percent":
        scale = max(0.1, float(opts.percent)) / 100.0
    elif opts.size_mode == "fit":
        scale = min(max(1, int(opts.fit_w)) / width, max(1, int(opts.fit_h)) / height)
    else:
        return width, height
    if opts.no_upscale:
        scale = min(scale, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


def render_filename(
    pattern: str, name: str, index: int, size: tuple[int, int], fmt: str, now: datetime | None = None,
    roll: str = "", frame: int | None = None,
) -> str:
    """Expands {name} {n} {date} {w} {h} {format} {roll} {frame} in pattern (unknown text is
    kept as-is; roll and frame come from the photo's Metadata, empty when unset) and strips
    characters Windows forbids in file names."""
    now = now or datetime.now()
    values = {
        "name": name,
        "n": f"{index:03d}",
        "date": now.strftime("%Y-%m-%d"),
        "w": str(size[0]),
        "h": str(size[1]),
        "format": FORMAT_LABELS[fmt].lower(),
        "roll": roll,
        "frame": "" if frame is None else str(frame),
    }
    text = _TOKEN.sub(lambda m: values[m.group(1)], pattern or "{name}")
    text = _BAD_FILENAME_CHARS.sub("_", text).strip(" .")
    return text or name


# Fields that describe where/how files are named, shared by every preset in a run;
# everything else on ExportOptions belongs to one preset.
GLOBAL_FIELDS = ("dest_mode", "folder", "subfolder", "date_folders", "pattern", "on_conflict", "preset_folders")


def merge_global(preset_options: "ExportOptions", shared: "ExportOptions") -> "ExportOptions":
    """A preset's own settings with the shared destination/naming settings applied."""
    merged = preset_options.to_dict()
    merged.update({name: getattr(shared, name) for name in GLOBAL_FIELDS})
    return ExportOptions.from_dict(merged)


def resolve_directory(source_path: str, opts: ExportOptions, preset_name: str | None = None) -> str:
    base = os.path.dirname(source_path) if opts.dest_mode == "beside" else opts.folder
    if opts.dest_mode == "beside" and opts.subfolder.strip():
        base = os.path.join(base, _BAD_FILENAME_CHARS.sub("_", opts.subfolder.strip()))
    if opts.preset_folders and preset_name:
        base = os.path.join(base, _BAD_FILENAME_CHARS.sub("_", preset_name.strip()) or "preset")
    if opts.date_folders:
        try:
            stamp = datetime.fromtimestamp(os.path.getmtime(source_path)).strftime("%d-%m-%Y")
        except OSError:
            stamp = datetime.now().strftime("%d-%m-%Y")
        base = os.path.join(base, stamp)
    return base


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{stem}_{n}{ext}"):
        n += 1
    return f"{stem}_{n}{ext}"


def resolve_output_path(
    source_path: str, index: int, size: tuple[int, int], opts: ExportOptions, preset_name: str | None = None,
    roll: str = "", frame: int | None = None,
) -> str | None:
    """Full output path for a source, or None if it should be skipped
    (file exists and on_conflict is 'skip'). With the default pattern the
    name is the original file's own name. An export never overwrites the
    source file itself, whatever on_conflict says."""
    name = os.path.splitext(os.path.basename(source_path))[0]
    stem = (
        _BAD_FILENAME_CHARS.sub("_", opts.prefix)
        + render_filename(opts.pattern, name, index, size, opts.fmt, roll=roll, frame=frame)
        + _BAD_FILENAME_CHARS.sub("_", opts.suffix)
    )
    path = os.path.join(resolve_directory(source_path, opts, preset_name), stem + EXTENSIONS[opts.fmt])
    if os.path.abspath(path).lower() == os.path.abspath(source_path).lower():
        return unique_path(path)
    if os.path.exists(path):
        if opts.on_conflict == "skip":
            return None
        if opts.on_conflict == "rename":
            return unique_path(path)
    return path


def srgb_profile_bytes() -> bytes | None:
    try:
        from PIL import ImageCms

        return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    except Exception:
        return None


def read_exif_bytes(source_path: str) -> bytes | None:
    """EXIF from a standard-format source (not RAW), minus the Orientation
    tag: the app shows and edits the pixels as stored, so a viewer applying
    the old tag on top would turn exported edits sideways."""
    try:
        with Image.open(source_path) as img:
            exif = img.getexif()
            if not exif:
                return None
            exif.pop(274, None)
            return exif.tobytes()
    except Exception:
        return None


def prepare_pixels(pixels: np.ndarray, opts: ExportOptions) -> Image.Image:
    img = Image.fromarray(np.ascontiguousarray(pixels))
    w, h = img.size
    new_size = target_size(w, h, opts)
    if new_size != (w, h):
        img = img.resize(new_size, RESAMPLING.get(opts.resample, Image.Resampling.LANCZOS))
    if opts.grayscale:
        img = img.convert("L")
    return img


def save_image(pixels: np.ndarray, dest_path: str, opts: ExportOptions, exif: bytes | None = None) -> tuple[int, int]:
    """Writes pixels (uint8 RGB) to dest_path with opts; returns the (w, h)
    written. Creates the destination folder. Written to a temp name and
    renamed, so a crash never leaves a truncated file under the final name."""
    img = prepare_pixels(pixels, opts)
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)

    params: dict = {"dpi": (int(opts.dpi), int(opts.dpi))}
    if opts.embed_srgb and not opts.grayscale:
        icc = srgb_profile_bytes()
        if icc:
            params["icc_profile"] = icc
    if opts.copy_exif and exif and opts.fmt in ("jpeg", "tiff", "webp", "png"):
        params["exif"] = exif

    if opts.fmt == "jpeg":
        params.update(
            quality=int(opts.jpeg_quality),
            progressive=bool(opts.jpeg_progressive),
            subsampling=JPEG_SUBSAMPLING.get(opts.jpeg_subsampling, 0),
            optimize=True,
        )
        pil_format = "JPEG"
    elif opts.fmt == "png":
        params.update(compress_level=int(opts.png_compress))
        pil_format = "PNG"
    elif opts.fmt == "tiff":
        compression = TIFF_COMPRESSIONS.get(opts.tiff_compression)
        if compression:
            params["compression"] = compression
        pil_format = "TIFF"
    else:
        params.update(quality=int(opts.webp_quality), lossless=bool(opts.webp_lossless), method=int(opts.webp_method))
        pil_format = "WEBP"

    # Pillow's JPEG optimize/progressive modes encode in one pass and fail with
    # "broken data stream" when the image outgrows its write buffer.
    ImageFile.MAXBLOCK = max(ImageFile.MAXBLOCK, img.size[0] * img.size[1] * 4)
    tmp = dest_path + ".part"
    try:
        img.save(tmp, format=pil_format, **params)
        os.replace(tmp, dest_path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return img.size
