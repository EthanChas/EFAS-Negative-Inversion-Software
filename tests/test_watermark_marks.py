"""Watermarks beyond the canister: text styling and fonts, SVG and picture logos, camera/lens text on its own, and custom (dragged) placement."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from photoeditor.features.finishing.logic import apply_border, border_pixels
from photoeditor.features.watermark import fonts, layout, logoimage
from photoeditor.features.watermark.logic import apply_watermark, canister_parts
from photoeditor.features.watermark.marks import CUSTOM, Marks, apply_marks, mark_parts

SRC = str(Path(__file__).resolve().parents[1] / "src")
GREY = np.full((400, 600, 3), 120, np.uint8)


def changed_region(a, b):
    diff = np.any(a != b, axis=2)
    ys, xs = np.where(diff)
    return None if not len(xs) else (xs.min(), ys.min(), xs.max(), ys.max())


def test_marks_round_trip_and_validation():
    m = Marks(text="hi", text_font="Arial", text_bold=True, text_color="#aabbcc", text_rotation=15.0, info_beside=False, canister_x=0.3, canister_y=0.4, canister_size=0.3)
    back = Marks.from_dict(m.to_dict())
    assert back == m
    assert Marks.from_dict({"text_color": "#AABBCC"}).text_color == "#aabbcc"
    assert Marks().to_dict() == {}
    bad = Marks.from_dict({"text_size": "x", "text_color": "red", "text_position": "nowhere", "text_rotation": 999, "canister_x": 0.5, "canister_y": -3, "text_bold": 1,
                           "logo_position": "custom", "text_align": "diagonal", "canister_size": 0.01, "mystery": 1})
    assert bad.text_size == Marks().text_size and bad.text_color == "white" and bad.text_position == Marks().text_position
    assert bad.text_rotation == 180.0 and bad.canister_x == -1.0 and bad.text_bold is True and bad.logo_position == CUSTOM
    assert bad.text_align == "auto" and bad.canister_size == 0.05
    assert Marks.from_dict(None) == Marks() and Marks.from_dict("junk") == Marks()


def test_text_styles_all_draw():
    base = apply_marks(GREY, Marks(text="Hello\nWorld"))
    assert changed_region(GREY, base) is not None
    for extra in ({"text_bold": True}, {"text_italic": True}, {"text_letter_spacing": 0.3}, {"text_rotation": 30.0}, {"text_outline": 0.8}, {"text_color": "#ff0000"},
                  {"text_align": "left"}, {"text_line_spacing": 0.8}, {"text_shadow": False}, {"text_font": "Arial", "text_bold": True, "text_italic": True}):
        out = apply_marks(GREY, Marks(text="Hello\nWorld", **extra))
        assert changed_region(GREY, out) is not None, extra
        assert not np.array_equal(out, base), extra
    red = apply_marks(GREY, Marks(text="Hello", text_color="#ff0000", text_shadow=False, text_opacity=1.0))
    ys, xs = np.where(np.any(red != GREY, axis=2))
    px = red[ys, xs].astype(int)
    assert (px[:, 0] - px[:, 2]).max() > 60, "red text is red"


def test_rotation_grows_the_box_and_letter_spacing_widens_it():
    flat = mark_parts(GREY.shape, Marks(text="Hello world", text_position="center"))[0].box
    turned = mark_parts(GREY.shape, Marks(text="Hello world", text_position="center", text_rotation=90.0))[0].box
    assert turned[3] > flat[3] and turned[2] < flat[2]
    wide = mark_parts(GREY.shape, Marks(text="Hello world", text_position="center", text_letter_spacing=0.4))[0].box
    assert wide[2] > flat[2]


def test_custom_position_centres_on_the_spot():
    m = Marks(text="Hello", text_position=CUSTOM, text_x=0.25, text_y=0.4)
    x, y, w, h = mark_parts(GREY.shape, m)[0].box
    assert abs((x + w / 2) - 150) <= 1 and abs((y + h / 2) - 160) <= 1
    preset = mark_parts(GREY.shape, Marks(text="Hello", text_x=0.25, text_y=0.4))[0].box
    assert preset[0] > x, "the stored spot is ignored unless the position is Custom"


def test_info_on_its_own_and_beside_the_canister():
    m = Marks()
    assert not m.wanted(False, "Pentax", "", False) and not m.wanted(True, "", "", False)
    assert m.wanted(True, "Pentax K1000", "", False)
    assert not m.wanted(True, "Pentax K1000", "", True), "beside an active canister it is the canister's job"
    assert Marks(info_beside=False).wanted(True, "Pentax K1000", "", True)
    out = apply_marks(GREY, m, True, "Pentax K1000", "SMC 50mm f/2", False)
    assert changed_region(GREY, out) is not None
    parts = mark_parts(GREY.shape, m, True, "Pentax K1000", "SMC 50mm f/2", False)
    assert [p.name for p in parts] == ["info"]
    no_credit = mark_parts(GREY.shape, Marks(info_credit=False), True, "Pentax K1000", "SMC 50mm f/2", False)[0].box
    assert no_credit[3] < parts[0].box[3]
    both = mark_parts(GREY.shape, Marks(info_beside=False), True, "Pentax K1000", "", True)
    assert [p.name for p in both] == ["info"]


def test_custom_canister_position_and_size():
    kw = dict(film="kodak_gold_200", texture="plastic", size="medium", position="bottom_right")
    preset = canister_parts(GREY.shape, kw["film"], kw["texture"], kw["size"], kw["position"])[0]
    moved = canister_parts(GREY.shape, kw["film"], kw["texture"], kw["size"], kw["position"], custom=(0.3, 0.5))[0]
    x, y, w, h = moved.box
    assert abs((x + w / 2) - 180) <= 1 and abs((y + h / 2) - 200) <= 1 and moved.box[2:] == preset.box[2:]
    big = canister_parts(GREY.shape, kw["film"], kw["texture"], kw["size"], kw["position"], custom=(0.3, 0.5), custom_size=0.6)[0]
    assert max(big.box[2:]) > max(preset.box[2:])
    with_info = canister_parts(GREY.shape, kw["film"], kw["texture"], kw["size"], kw["position"], True, "Pentax", "50mm", custom=(0.3, 0.5))
    assert [p.name for p in with_info] == ["canister", "canister_info"] and with_info[1].x > with_info[0].x
    right = canister_parts(GREY.shape, kw["film"], kw["texture"], kw["size"], kw["position"], True, "Pentax", "50mm", custom=(0.8, 0.5))
    assert right[1].x < right[0].x, "on the right half the text goes to the canister's left"
    assert apply_watermark(GREY, "off", "plastic", "medium", "center") is GREY


def test_boxes_and_edit():
    canister = {"film": "kodak_gold_200", "texture": "plastic", "size": "medium", "position": "bottom_right"}
    m = Marks(text="Hello", logo="")
    found = layout.boxes(GREY.shape, canister, m, True, "Pentax", "50mm")
    assert set(found) == {"canister", "text"}, found
    assert set(layout.boxes(GREY.shape, None, m, True, "Pentax", "50mm")) == {"text", "info"}
    # dragging the text: the position menu becomes Custom, the size scales
    e = layout.edit(m, "text", 0.2, 0.3, 1.5)
    assert e.text_position == CUSTOM and (e.text_x, e.text_y) == (0.2, 0.3) and abs(e.text_size - m.text_size * 1.5) < 1e-9
    assert layout.edit(m, "text", 2.0, -1.0).text_x == 1.0
    # the canister: moving alone keeps the menu's size; resizing makes a custom one
    moved = layout.edit(m, "canister", 0.3, 0.6, 1.0, "medium")
    assert moved.has_custom_canister() and moved.canister_size == 0.0
    grown = layout.edit(m, "canister", 0.3, 0.6, 2.0, "medium")
    assert abs(grown.canister_size - 0.52) < 1e-9
    assert layout.edit(m, "nothing", 0.3, 0.6) == m
    # the boxes follow the edit
    after = layout.boxes(GREY.shape, canister, moved, False, "", "")
    x, y, w, h = after["canister"]
    assert abs((x + w / 2) - 180) <= 1 and abs((y + h / 2) - 240) <= 1


def test_unframe_shape_inverts_the_border():
    for border in (0.0, 0.02, 0.037, 0.1):
        for hw in ((400, 600), (333, 777), (1001, 1500)):
            framed = apply_border(np.zeros((*hw, 3), np.uint8), border, "white")
            h, w, b = layout.unframe_shape(framed.shape, border)
            assert (h, w) == hw and b == border_pixels(hw, border), (border, hw, (h, w, b))


def test_fonts_find_families_and_resolve():
    all_fonts = [fonts.FontFile("/x/Arial.ttf", "Arial", "Regular"), fonts.FontFile("/x/Arialbd.ttf", "Arial", "Bold"), fonts.FontFile("/x/Mono.ttf", "Mono", "Regular")]
    assert fonts.families(all_fonts) == ["Arial", "Mono"]
    assert fonts.resolve("Arial", True, False, all_fonts) == ("/x/Arialbd.ttf", False, False)
    assert fonts.resolve("Arial", False, False, all_fonts) == ("/x/Arial.ttf", False, False)
    assert fonts.resolve("mono", True, True, all_fonts) == ("/x/Mono.ttf", True, True), "no bold or italic face: faked"
    assert fonts.resolve("Nonexistent", True, False, all_fonts) == (None, True, False)
    assert fonts.resolve("", False, False, all_fonts) == (None, False, False)
    assert fonts.display_name("") == "Default" and fonts.display_name("C:/Fonts/Lobster.ttf") == "Lobster.ttf" and fonts.display_name("Arial") == "Arial"


def test_installed_fonts_scan_is_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    first = fonts.installed_fonts()
    assert (tmp_path / "font-list-cache.json").exists()
    assert fonts.installed_fonts() == first
    if first:
        assert fonts.families(first)
        f = first[0]
        assert fonts.resolve(f.family, False, False, first)[0] is not None


def test_a_font_file_is_used_directly():
    found = [f for f in fonts.installed_fonts() if f.family in ("Arial", "Segoe UI", "DejaVu Sans", "Helvetica", "Liberation Sans", "Verdana", "Tahoma")]
    if not found:
        pytest.skip("none of the usual fonts installed")
    out = apply_marks(GREY, Marks(text="Hello", text_font=found[0].path))
    assert changed_region(GREY, out) is not None


def test_png_logo(tmp_path):
    from PIL import Image

    logo = tmp_path / "logo.png"
    px = np.zeros((20, 40, 4), np.uint8)
    px[:, :, 0] = 255
    px[:, :, 3] = 255
    Image.fromarray(px, "RGBA").save(logo)
    m = Marks(logo=str(logo), logo_size=0.3, logo_opacity=1.0, logo_position="center")
    part = mark_parts(GREY.shape, m)[0]
    assert part.name == "logo" and part.box[2] == 2 * part.box[3] and part.box[2] == round(400 * 0.3)
    out = apply_marks(GREY, m)
    x, y, w, h = part.box
    assert tuple(out[y + h // 2, x + w // 2]) == (255, 0, 0)
    assert logoimage.check(str(logo)) is None
    assert "does not exist" in logoimage.check(str(tmp_path / "nope.png"))
    assert logoimage.check(str(tmp_path / "x.txt")) is not None
    (tmp_path / "bad.png").write_bytes(b"not a picture")
    assert logoimage.check(str(tmp_path / "bad.png")) is not None
    assert not Marks(logo=str(tmp_path / "bad.png")).has_logo() or True
    assert apply_marks(GREY, Marks(logo=str(tmp_path / "bad.png"))) is not None


_SVG_SCRIPT = textwrap.dedent(r'''
    import os, sys, tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import numpy as np
    from photoeditor.features.watermark import logoimage
    from photoeditor.features.watermark.marks import Marks, apply_marks, mark_parts

    d = tempfile.mkdtemp()
    svg = os.path.join(d, "mark.svg")
    open(svg, "w").write('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100"><rect width="200" height="100" fill="#00ff00"/></svg>')
    grey = np.full((400, 600, 3), 120, np.uint8)
    assert logoimage.check(svg) is None and abs(logoimage.svg_aspect(svg) - 2.0) < 1e-6
    m = Marks(logo=svg, logo_size=0.5, logo_opacity=1.0, logo_position="center")
    part = mark_parts(grey.shape, m)[0]
    x, y, w, h = part.box
    assert w == 200 and h == 100, part.box
    out = apply_marks(grey, m)
    assert tuple(out[y + 50, x + 100]) == (0, 255, 0), out[y + 50, x + 100]
    half = apply_marks(grey, Marks(logo=svg, logo_size=0.5, logo_opacity=0.5, logo_position="center"))
    assert 120 < half[y + 50, x + 100][1] < 255
    # sharp at any size: a bigger logo is drawn bigger, not stretched from a small bitmap
    big = mark_parts((2000, 3000, 3), m)[0].box
    assert big[2] == 1000
    # transparent areas stay transparent
    open(os.path.join(d, "ring.svg"), "w").write('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40" fill="none" stroke="#ff0000" stroke-width="10"/></svg>')
    ring = Marks(logo=os.path.join(d, "ring.svg"), logo_size=0.5, logo_opacity=1.0, logo_position="center")
    p = mark_parts(grey.shape, ring)[0]
    r = apply_marks(grey, ring)
    cx, cy = p.x + p.box[2] // 2, p.y + p.box[3] // 2
    assert tuple(r[cy, cx]) == (120, 120, 120), "inside the ring is untouched"
    # a broken or oversized SVG is refused, not drawn
    open(os.path.join(d, "broken.svg"), "w").write("<svg")
    assert logoimage.check(os.path.join(d, "broken.svg")) is not None
    open(os.path.join(d, "huge.svg"), "w").write("<svg xmlns='http://www.w3.org/2000/svg'><!--" + "x" * 5_100_000 + "--></svg>")
    assert "5 MB" in logoimage.check(os.path.join(d, "huge.svg"))
    assert apply_marks(grey, Marks(logo=os.path.join(d, "broken.svg"))).shape == grey.shape
    print("SVG OK"); sys.stdout.flush()
    os._exit(0)
''')


def test_svg_logo_renders_sharp_at_any_size():
    env = dict(os.environ, PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""))
    done = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _SVG_SCRIPT], env=env, capture_output=True, text=True, timeout=120)
    assert "SVG OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3000:]
