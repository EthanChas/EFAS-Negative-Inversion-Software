"""XMP sidecar read/write - stdlib only, no Qt/UI imports.

Edits are saved next to the photo as `<filename>.<ext>.xmp` (darktable's
naming: IMG_0001.CR2 -> IMG_0001.CR2.xmp), so they travel with the files
and survive a lost or copied database. Two groups of properties are written:

* Lightroom/Camera Raw (`crs:`) equivalents for the settings that map
  cleanly (exposure, saturation, shadows, highlights, sharpening, crop, tone
  curve) - best-effort interoperability; other tools may render them
  differently than this app does, since the pipelines aren't identical.
* A private `pe:` namespace carrying this app's exact values, which is what
  read_sidecar restores from - lossless round trip, including the settings
  with no crs: counterpart (temperature/tint offsets, invert, flips).

An existing sidecar is merged into, not replaced - ratings, keywords or
other tools' develop settings already in it are kept. If it can't be parsed,
it's left untouched rather than overwritten."""

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

NS_X = "adobe:ns:meta/"
NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NS_XMP = "http://ns.adobe.com/xap/1.0/"
NS_CRS = "http://ns.adobe.com/camera-raw-settings/1.0/"
NS_PE = "http://ns.photoeditor.local/1.0/"

for _prefix, _uri in (("x", NS_X), ("rdf", NS_RDF), ("xmp", NS_XMP), ("crs", NS_CRS), ("pe", NS_PE)):
    ET.register_namespace(_prefix, _uri)

_PE_ATTRS = (
    "ExposureEV", "Inverted", "RotationQuarterTurns", "FlipH", "FlipV",
    "Saturation", "Temperature", "Tint", "Shadows", "Highlights",
    "SharpenAmount", "SharpenRadius", "SharpenMasking", "SharpenMethod",
    "DustAuto", "DustThreshold", "DustSize", "ScratchLines", "ScratchSensitivity", "HealStrokes", "FilmType", "InvertR", "InvertG", "InvertB", "Contrast", "FineRotation", "Distortion", "ChromaDenoise", "WmFilm", "WmTexture", "WmSize", "WmPosition", "WmInfo", "WmCamera", "WmLens", "Metadata",
    "CropLeft", "CropTop", "CropRight", "CropBottom",
)
_CRS_ATTRS = (
    "HasSettings", "HasCrop", "Exposure2012", "Contrast2012", "Saturation", "Shadows2012", "Highlights2012",
    "Sharpness", "SharpenRadius", "SharpenEdgeMasking",
    "CropLeft", "CropTop", "CropRight", "CropBottom",
)


def crop_from_fractions(fractions, preview_hw: tuple[int, int], rotation_quarter_turns: int):
    """0..1 crop fractions -> a crop rect in preview-frame pixels (the frame
    is rotated, so its dimensions swap for an odd number of quarter turns)."""
    if fractions is None:
        return None
    h0, w0 = preview_hw
    h, w = (w0, h0) if rotation_quarter_turns % 2 else (h0, w0)
    left, top, right, bottom = fractions
    return (round(left * w), round(top * h), round(right * w), round(bottom * h))


def sidecar_path(image_path: str) -> str:
    return image_path + ".xmp"


def _q(ns: str, name: str) -> str:
    return f"{{{ns}}}{name}"


def _fmt(value: float) -> str:
    return f"{value:.6g}"


def _description(root: ET.Element) -> ET.Element | None:
    rdf = root.find(_q(NS_RDF, "RDF"))
    return rdf.find(_q(NS_RDF, "Description")) if rdf is not None else None


def _new_document() -> ET.Element:
    root = ET.Element(_q(NS_X, "xmpmeta"))
    rdf = ET.SubElement(root, _q(NS_RDF, "RDF"))
    ET.SubElement(rdf, _q(NS_RDF, "Description"), {_q(NS_RDF, "about"): ""})
    return root


def _set_curve(desc: ET.Element, tag: str, points: list[tuple[int, int]], sep: str) -> None:
    for old in desc.findall(tag):
        desc.remove(old)
    holder = ET.SubElement(desc, tag)
    seq = ET.SubElement(holder, _q(NS_RDF, "Seq"))
    for x, y in points:
        ET.SubElement(seq, _q(NS_RDF, "li")).text = f"{x}{sep}{y}"


def apply_edits_to_document(root: ET.Element, state: dict, frame_size: tuple[int, int]) -> None:
    """state: edit_store's dict shape. frame_size: (height, width) of the
    pre-crop frame the crop rect is expressed in - turned into 0..1
    fractions so the saved crop doesn't depend on this app's preview
    resolution."""
    desc = _description(root)
    for name in _PE_ATTRS:
        desc.attrib.pop(_q(NS_PE, name), None)
    for name in _CRS_ATTRS:
        desc.attrib.pop(_q(NS_CRS, name), None)

    pe = lambda name, value: desc.set(_q(NS_PE, name), value)  # noqa: E731
    crs = lambda name, value: desc.set(_q(NS_CRS, name), value)  # noqa: E731

    desc.set(_q(NS_XMP, "CreatorTool"), "PhotoEditor")
    desc.set(_q(NS_XMP, "ModifyDate"), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    pe("ExposureEV", _fmt(state["exposure_ev"]))
    pe("Inverted", str(bool(state["negative_inverted"])))
    pe("RotationQuarterTurns", str(int(state["rotation_quarter_turns"])))
    pe("FlipH", str(bool(state["flip_h"])))
    pe("FlipV", str(bool(state["flip_v"])))
    pe("Saturation", _fmt(state["saturation"]))
    pe("Temperature", _fmt(state["temperature"]))
    pe("Tint", _fmt(state["tint"]))
    pe("Shadows", _fmt(state["shadows"]))
    pe("Highlights", _fmt(state["highlights"]))
    pe("SharpenAmount", _fmt(state["sharpen_amount"]))
    pe("SharpenRadius", _fmt(state["sharpen_radius"]))
    pe("SharpenMasking", _fmt(state["sharpen_masking"]))
    pe("SharpenMethod", state["sharpen_method"])
    pe("DustAuto", str(bool(state["dust_auto"])))
    pe("DustThreshold", _fmt(state["dust_threshold"]))
    pe("DustSize", str(int(state["dust_size"])))
    pe("ScratchLines", json.dumps(state["scratch_lines"]))
    pe("ScratchSensitivity", _fmt(state["scratch_sensitivity"]))
    pe("HealStrokes", json.dumps(state["heal_strokes"]))
    pe("CloneStrokes", json.dumps(state.get("clone_strokes", [])))
    pe("AiDust", str(bool(state.get("ai_dust", False))))
    pe("AiThreshold", _fmt(state.get("ai_threshold", 0.3)))
    pe("AiGrow", str(int(state.get("ai_grow", 1))))
    pe("Marks", json.dumps(state.get("marks", {})))
    pe("FilmType", state["film_type"])
    pe("InvertR", _fmt(state["invert_r"]))
    pe("InvertG", _fmt(state["invert_g"]))
    pe("InvertB", _fmt(state["invert_b"]))
    pe("Contrast", _fmt(state["contrast"]))
    pe("FineRotation", _fmt(state["fine_rotation"]))
    pe("Distortion", _fmt(state["distortion"]))
    pe("ChromaDenoise", _fmt(state["chroma_denoise"]))
    pe("LocalContrast", _fmt(state.get("local_contrast", 0.0)))
    pe("Metering", json.dumps(state.get("metering", {})))
    pe("WmFilm", state["wm_film"])
    pe("WmTexture", state["wm_texture"])
    pe("WmSize", state["wm_size"])
    pe("WmPosition", state["wm_position"])
    pe("WmInfo", str(bool(state["wm_info"])))
    pe("WmCamera", state["wm_camera"])
    pe("WmLens", state["wm_lens"])
    pe("Metadata", json.dumps(state["metadata"], ensure_ascii=False))
    _set_curve(desc, _q(NS_PE, "ToneCurve"), state["tone_curve_points"], ",")

    crs("HasSettings", "True")
    crs("Exposure2012", f"{state['exposure_ev']:+.2f}")
    crs("Contrast2012", str(round(state["contrast"] * 100)))
    crs("Saturation", str(round(state["saturation"] * 100)))
    crs("Shadows2012", str(round(state["shadows"] * 100)))
    crs("Highlights2012", str(round(state["highlights"] * 100)))
    crs("Sharpness", str(round(state["sharpen_amount"] * 150)))
    crs("SharpenRadius", f"{state['sharpen_radius']:+.1f}")
    crs("SharpenEdgeMasking", str(round(state["sharpen_masking"] * 100)))
    _set_curve(desc, _q(NS_CRS, "ToneCurvePV2012"), state["tone_curve_points"], ", ")

    rect = state["crop_rect"]
    crs("HasCrop", str(rect is not None))
    if rect is not None:
        h, w = frame_size
        x1, y1, x2, y2 = rect
        fractions = {"Left": x1 / w, "Top": y1 / h, "Right": x2 / w, "Bottom": y2 / h}
        for name, value in fractions.items():
            crs(f"Crop{name}", _fmt(value))
            pe(f"Crop{name}", _fmt(value))


def write_sidecar(image_path: str, state: dict, frame_size: tuple[int, int]) -> bool:
    """True if written. False (nothing touched) when the folder isn't
    writable or an existing sidecar can't be parsed."""
    path = sidecar_path(image_path)
    root = None
    if os.path.exists(path):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return False
        if _description(root) is None:
            return False
    if root is None:
        root = _new_document()

    apply_edits_to_document(root, state, frame_size)
    tmp = path + ".tmp"
    try:
        ET.indent(root)
        ET.ElementTree(root).write(tmp, encoding="utf-8", xml_declaration=True)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def read_sidecar(image_path: str) -> dict | None:
    """The edit state saved by write_sidecar, in edit_store's dict shape
    except crop_rect is replaced by crop_fractions ((l, t, r, b) in 0..1, or
    None) - the caller knows the current frame size. None if there's no
    sidecar, it isn't parseable, or it has no pe: settings (e.g. written
    by another tool)."""
    try:
        desc = _description(ET.parse(sidecar_path(image_path)).getroot())
    except (ET.ParseError, OSError):
        return None
    if desc is None or desc.get(_q(NS_PE, "ExposureEV")) is None:
        return None

    def get(name: str) -> str:
        return desc.get(_q(NS_PE, name))

    try:
        points = [
            (int(float(x)), int(float(y)))
            for x, y in (li.text.split(",") for li in desc.findall(f"{_q(NS_PE, 'ToneCurve')}/{_q(NS_RDF, 'Seq')}/{_q(NS_RDF, 'li')}"))
        ]
        crop = None
        if get("CropLeft") is not None:
            crop = tuple(float(get(f"Crop{n}")) for n in ("Left", "Top", "Right", "Bottom"))
        return {
            "exposure_ev": float(get("ExposureEV")),
            "tone_curve_points": points or [(0, 0), (255, 255)],
            "negative_inverted": get("Inverted") == "True",
            "rotation_quarter_turns": int(get("RotationQuarterTurns")) % 4,
            "flip_h": get("FlipH") == "True",
            "flip_v": get("FlipV") == "True",
            "crop_fractions": crop,
            "saturation": float(get("Saturation")),
            "temperature": float(get("Temperature")),
            "tint": float(get("Tint")),
            "shadows": float(get("Shadows")),
            "highlights": float(get("Highlights")),
            "sharpen_amount": float(get("SharpenAmount")),
            "sharpen_radius": float(get("SharpenRadius")),
            "sharpen_masking": float(get("SharpenMasking")),
            "sharpen_method": get("SharpenMethod") or "usm",
            "dust_auto": get("DustAuto") == "True",
            "dust_threshold": float(get("DustThreshold") or 0.66),
            "dust_size": int(get("DustSize") or 4),
            "scratch_lines": [tuple(line) for line in json.loads(get("ScratchLines") or "[]")],
            "scratch_sensitivity": float(get("ScratchSensitivity") or 0.5),
            "heal_strokes": json.loads(get("HealStrokes") or "[]"),
            "clone_strokes": json.loads(get("CloneStrokes") or "[]"),
            "ai_dust": get("AiDust") == "True",
            "ai_threshold": float(get("AiThreshold") or 0.3),
            "ai_grow": int(get("AiGrow") or 1),
            "marks": json.loads(get("Marks") or "{}"),
            "film_type": get("FilmType") or "auto",
            "invert_r": float(get("InvertR") or 0.0),
            "invert_g": float(get("InvertG") or 0.0),
            "invert_b": float(get("InvertB") or 0.0),
            "contrast": float(get("Contrast") or 0.0),
            "fine_rotation": float(get("FineRotation") or 0.0),
            "distortion": float(get("Distortion") or 0.0),
            "chroma_denoise": float(get("ChromaDenoise") or 0.0),
            "local_contrast": float(get("LocalContrast") or 0.0),
            "metering": json.loads(get("Metering") or "{}"),
            "wm_film": get("WmFilm") or "off",
            "wm_texture": get("WmTexture") or "plastic",
            "wm_size": get("WmSize") or "medium",
            "wm_position": get("WmPosition") or "bottom_right",
            "wm_info": get("WmInfo") == "True",
            "wm_camera": get("WmCamera") or "",
            "wm_lens": get("WmLens") or "",
            "metadata": json.loads(get("Metadata") or "{}"),
        }
    except (TypeError, ValueError, AttributeError):
        return None


_FLAG_ATTRS = ("Flag",)


def write_flag(image_path: str, flag: str | None) -> bool:
    """Records the keeper/rejected mark in the sidecar without touching the
    edit data: a rejected photo gets xmp:Rating -1 (the Lightroom/darktable
    convention for rejected) and a keeper a green xmp:Label; the exact mark
    is also kept in pe:Flag. An existing rating that isn't -1 is left alone."""
    path = sidecar_path(image_path)
    root = None
    if os.path.exists(path):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return False
        if _description(root) is None:
            return False
    if root is None:
        if flag is None:
            return True  # nothing to record, and no sidecar to clean up
        root = _new_document()
    desc = _description(root)

    rating, label, mark = _q(NS_XMP, "Rating"), _q(NS_XMP, "Label"), _q(NS_PE, "Flag")
    stars_attr = _q(NS_PE, "Stars")
    if desc.get(rating) == "-1":
        desc.attrib.pop(rating)
        if desc.get(stars_attr):  # un-rejecting gives the star rating back
            desc.set(rating, desc.get(stars_attr))
    if desc.get(label) == "Green":
        desc.attrib.pop(label)
    desc.attrib.pop(mark, None)
    if flag == "rejected":
        desc.set(rating, "-1")
        desc.set(mark, flag)
    elif flag == "keeper":
        desc.set(label, "Green")
        desc.set(mark, flag)

    tmp = path + ".tmp"
    try:
        ET.indent(root)
        ET.ElementTree(root).write(tmp, encoding="utf-8", xml_declaration=True)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def write_rating(image_path: str, stars: int) -> bool:
    """Records the 1-5 star rating in the sidecar: xmp:Rating (what Lightroom and darktable read) unless the photo is rejected, which
    owns that field as -1, and always pe:Stars, so the stars survive a reject and an un-reject."""
    path = sidecar_path(image_path)
    root = None
    if os.path.exists(path):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return False
        if _description(root) is None:
            return False
    if root is None:
        if stars <= 0:
            return True
        root = _new_document()
    desc = _description(root)
    rating, stars_attr = _q(NS_XMP, "Rating"), _q(NS_PE, "Stars")
    desc.attrib.pop(stars_attr, None)
    if stars > 0:
        desc.set(stars_attr, str(stars))
    if desc.get(rating) != "-1":
        desc.attrib.pop(rating, None)
        if stars > 0:
            desc.set(rating, str(stars))
    tmp = path + ".tmp"
    try:
        ET.indent(root)
        ET.ElementTree(root).write(tmp, encoding="utf-8", xml_declaration=True)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def read_rating(image_path: str) -> int:
    try:
        desc = _description(ET.parse(sidecar_path(image_path)).getroot())
    except (ET.ParseError, OSError):
        return 0
    if desc is None:
        return 0
    for value in (desc.get(_q(NS_PE, "Stars")), desc.get(_q(NS_XMP, "Rating"))):
        if value and value.isdigit() and 1 <= int(value) <= 5:
            return int(value)
    return 0


def read_flag(image_path: str) -> str | None:
    try:
        desc = _description(ET.parse(sidecar_path(image_path)).getroot())
    except (ET.ParseError, OSError):
        return None
    if desc is None:
        return None
    mark = desc.get(_q(NS_PE, "Flag"))
    if mark in ("keeper", "rejected"):
        return mark
    return "rejected" if desc.get(_q(NS_XMP, "Rating")) == "-1" else None
