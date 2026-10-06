"""A contact sheet: every frame of a roll as a small picture on printable pages, with its frame number, stars and flag, and the roll's
details at the top. Pillow only - no Qt. The pages are drawn here; the caller supplies the pictures (see desktop/contactsheet_worker.py)."""

import math
import os
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from ..metadata.roll import RollCard

PAGE_SIZES = {"Letter": (8.5, 11.0), "A4": (8.27, 11.69)}  # inches, portrait
MIN_COLUMNS, MAX_COLUMNS = 2, 10
DEFAULT_DPI = 150

_MARGIN_IN = 0.45
_GAP_IN = 0.14
_FIRST_HEADER_IN = 1.0      # the roll's details, on the first page
_RUNNING_HEADER_IN = 0.4    # a one-line header on every later page
_CELL_ASPECT = 3 / 2        # every cell is a landscape 3:2 box; portrait frames sit inside it
_PAPER = (255, 255, 255)
_INK = (30, 30, 30)
_MUTED = (110, 110, 110)
_CELL_BG = (236, 236, 236)
_STAR = (214, 160, 20)
_KEEP = (60, 160, 80)
_REJECT = (205, 60, 55)


@dataclass(frozen=True)
class SheetOptions:
    columns: int = 5
    page: str = "Letter"
    landscape: bool = True
    include_rejected: bool = False
    dpi: int = DEFAULT_DPI


@dataclass(frozen=True)
class SheetFrame:
    image: Image.Image
    number: int          # the frame's place on the roll (1-based), whatever was left out
    rating: int = 0      # 0-5
    flag: Optional[str] = None  # "keeper", "rejected" or None
    name: str = ""       # the file's name (without its extension), printed beside the number


def page_pixels(options: SheetOptions) -> tuple[int, int]:
    w_in, h_in = PAGE_SIZES.get(options.page, PAGE_SIZES["Letter"])
    if options.landscape:
        w_in, h_in = h_in, w_in
    return round(w_in * options.dpi), round(h_in * options.dpi)


def clamp_columns(columns: int) -> int:
    return max(MIN_COLUMNS, min(MAX_COLUMNS, int(columns)))


def cell_layout(options: SheetOptions, count: int) -> list[list[tuple[int, int, int, int]]]:
    """The picture box (x, y, w, h) of every frame, page by page. Each box is 3:2; a caption strip sits under it, inside the row's height.
    The first page has room for the roll's details, later pages for a single line."""
    page_w, page_h = page_pixels(options)
    dpi = options.dpi
    margin, gap = round(_MARGIN_IN * dpi), round(_GAP_IN * dpi)
    cols = clamp_columns(options.columns)
    cell_w = (page_w - 2 * margin - (cols - 1) * gap) // cols
    cell_h = round(cell_w / _CELL_ASPECT)
    caption = max(14, round(cell_w * 0.11))
    row_h = cell_h + caption + gap
    pages: list[list[tuple[int, int, int, int]]] = []
    placed = 0
    first = True
    while placed < count or not pages:
        top = margin + round((_FIRST_HEADER_IN if first else _RUNNING_HEADER_IN) * dpi)
        rows = max(1, (page_h - margin - top + gap) // row_h)
        boxes = []
        for r in range(rows):
            for c in range(cols):
                if placed + len(boxes) >= count:
                    break
                boxes.append((margin + c * (cell_w + gap), top + r * row_h, cell_w, cell_h))
        pages.append(boxes)
        placed += len(boxes)
        first = False
        if not boxes:
            break
    return pages


def header_text(roll: RollCard, folder_name: str, frames: int) -> tuple[str, list[str]]:
    """-> (title, detail lines) for the top of the first page. A blank roll card falls back to the folder's name."""
    title = roll.name.strip() or folder_name
    film = " ".join(p for p in (roll.film.strip(), f"ISO {roll.iso}" if roll.iso else "", roll.format.strip()) if p)
    gear = "  ·  ".join(p for p in (roll.camera.strip(), roll.lens.strip()) if p)
    if roll.shot_from and roll.shot_to and roll.shot_to != roll.shot_from:
        shot = f"{roll.shot_from} to {roll.shot_to}"
    else:
        shot = roll.shot_from or roll.shot_to
    process = "  ·  ".join(p for p in (f"Shot {shot}" if shot else "", f"Developed: {roll.developed.strip()}" if roll.developed.strip() else "",
                                           f"Scanned with {roll.scanned_with.strip()}" if roll.scanned_with.strip() else "") if p)
    lines = [film, gear, process, f"{frames} frame{'s' if frames != 1 else ''}"]
    return title, [ln for ln in lines if ln]


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = (["arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"] if bold else []) + ["arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    draw.polygon(pts, fill=fill)


def _fit(image: Image.Image, w: int, h: int) -> Image.Image:
    scale = min(w / image.width, h / image.height)
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)


def draw_pages(frames: list[SheetFrame], options: SheetOptions, title: str, lines: list[str]) -> list[Image.Image]:
    """The finished pages, as RGB images. frames are laid out in the order given."""
    layout = cell_layout(options, len(frames))
    page_w, page_h = page_pixels(options)
    dpi = options.dpi
    margin = round(_MARGIN_IN * dpi)
    title_font, body_font, tiny = _font(round(0.26 * dpi), True), _font(round(0.11 * dpi)), _font(round(0.085 * dpi))
    running_font = _font(round(0.13 * dpi))
    pages: list[Image.Image] = []
    n = 0
    for index, boxes in enumerate(layout):
        page = Image.new("RGB", (page_w, page_h), _PAPER)
        d = ImageDraw.Draw(page)
        if index == 0:
            d.text((margin, margin), title, fill=_INK, font=title_font)
            y = margin + round(0.34 * dpi)
            for line in lines:
                d.text((margin, y), line, fill=_MUTED, font=body_font)
                y += round(0.15 * dpi)
        else:
            d.text((margin, margin), title, fill=_MUTED, font=running_font)
        footer = f"page {index + 1} of {len(layout)}" if len(layout) > 1 else ""
        if footer:
            bbox = d.textbbox((0, 0), footer, font=tiny)
            d.text((page_w - margin - (bbox[2] - bbox[0]), page_h - margin + round(0.1 * dpi)), footer, fill=_MUTED, font=tiny)
        for (x, y, w, h) in boxes:
            frame = frames[n]
            n += 1
            d.rectangle((x, y, x + w - 1, y + h - 1), fill=_CELL_BG)
            thumb = _fit(frame.image, w, h)
            if frame.flag == "rejected":
                thumb = Image.blend(thumb, Image.new("RGB", thumb.size, _PAPER), 0.55)
            page.paste(thumb, (x + (w - thumb.width) // 2, y + (h - thumb.height) // 2))
            cap_y = y + h + 3
            label = str(frame.number)
            d.text((x, cap_y), label, fill=_INK, font=tiny)
            if frame.name:  # the file name after the number, cut to what the stars (right) leave of the width
                stars_w = round(frame.rating * (max(4.0, dpi * 0.032) * 2.1 + 1)) + 4 if frame.rating else 0
                room = w - (d.textbbox((0, 0), label + "  ", font=tiny)[2]) - stars_w
                name = frame.name
                while name and d.textbbox((0, 0), name, font=tiny)[2] > room:
                    name = name[:-1]
                if name and name != frame.name:
                    name = name[:-1] + "…" if len(name) > 1 else name
                if name:
                    d.text((x + d.textbbox((0, 0), label + "  ", font=tiny)[2], cap_y), name, fill=_MUTED, font=tiny)
            if frame.flag == "rejected":
                d.line((x + 6, y + 6, x + w - 7, y + h - 7), fill=_REJECT, width=max(2, dpi // 50))
                d.line((x + w - 7, y + 6, x + 6, y + h - 7), fill=_REJECT, width=max(2, dpi // 50))
            elif frame.flag == "keeper":
                s = max(7, dpi // 20)
                d.rectangle((x + w - s - 4, y + 4, x + w - 5, y + 3 + s), fill=_KEEP)
            if frame.rating:
                r = max(4.0, dpi * 0.032)
                for i in range(frame.rating):
                    _star(d, x + w - r - i * (r * 2.1 + 1), cap_y + r + 1, r, _STAR)
        pages.append(page)
    return pages


def save_pdf(pages: list[Image.Image], path: str, dpi: int = DEFAULT_DPI) -> None:
    """One PDF, one image per page. Written to a temporary name first, so a failed save never leaves a broken file where a good one was."""
    tmp = path + ".part"
    try:
        pages[0].save(tmp, "PDF", resolution=float(dpi), save_all=True, append_images=pages[1:])
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
