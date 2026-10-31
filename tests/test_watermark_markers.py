"""Markers the way darktable does them: a watermarks folder found by name, SVG files with $(NAME) variables (its WATERMARK_* ones and the film's), scaling on a side of the picture, rotation."""
import os

import numpy as np
import pytest

from photoeditor.features.watermark import dtmark, library, logoimage
from photoeditor.features.watermark import variables as V
from photoeditor.features.watermark.marks import Marks, apply_marks, marker_variables, mark_parts

SVG_TEXT = ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100" viewBox="0 0 400 100"><text x="10" y="70" font-family="$(WATERMARK_FONT_FAMILY)" font-weight="$(WATERMARK_FONT_WEIGHT)" '
            'font-style="$(WATERMARK_FONT_STYLE)" font-size="60" fill="$(WATERMARK_COLOR)">$(WATERMARK_TEXT)</text></svg>')
SVG_BOX = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100"><rect width="200" height="100" fill="#00ff00"/></svg>'
GREY = np.full((600, 900, 3), 128, np.uint8)


@pytest.fixture(autouse=True, scope="module")
def _qt_font():
    """An SVG's text is drawn with Qt's fonts, and an offscreen Qt (made by an earlier test) may have none: give it one that is on this computer."""
    from PyQt6.QtGui import QFontDatabase

    from photoeditor.features.watermark import fonts

    logoimage._ensure_qt()
    if not QFontDatabase.families():
        for f in fonts.installed_fonts():
            if f.family in ("Arial", "Segoe UI", "DejaVu Sans", "Liberation Sans", "Verdana", "Tahoma") and QFontDatabase.addApplicationFont(f.path) >= 0:
                break
    yield


@pytest.fixture
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _user(name):
    return os.path.join(library.user_dir(), name)


def _write(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


# ------------------------------------------------------------ the watermarks folder
def test_the_samples_that_come_with_efas_are_listed_and_work(folder):
    names = [m.name for m in library.list_markers()]
    assert {"simple-text.svg", "copyright-line.svg", "film-frame-info.svg", "efas-film-credit.svg"} <= set(names)
    assert all(m.bundled for m in library.list_markers())
    for m in library.list_markers():
        assert logoimage.check(m.path) is None, m.name
    assert logoimage.svg_variables(library.resolve("simple-text.svg")) == set(logoimage.MARKER_VARIABLES)
    assert "WATERMARK_TEXT" in logoimage.svg_variables(library.resolve("copyright-line.svg"))
    assert logoimage.svg_variables(library.resolve("film-frame-info.svg")) == set(logoimage.MARKER_VARIABLES) - {"WATERMARK_TEXT"}, "this one writes the film's details, not a text of your own"
    assert logoimage.svg_variables(library.resolve("efas-film-credit.svg")) == set(logoimage.MARKER_VARIABLES) - {"WATERMARK_TEXT"}


def test_a_marker_is_found_by_name_in_the_users_folder_first(folder):
    mine = _write(_user("signature.svg"), SVG_BOX)
    own_simple = _write(_user("simple-text.svg"), SVG_BOX)
    listed = {m.name: m for m in library.list_markers()}
    assert listed["signature.svg"].path == mine and not listed["signature.svg"].bundled and listed["signature.svg"].label() == "signature (svg)"
    assert listed["simple-text.svg"].path == own_simple, "a file of the person's hides the sample of the same name"
    assert [m.name for m in library.list_markers()].count("simple-text.svg") == 1
    assert library.resolve("signature.svg") == mine and library.resolve("copyright-line.svg") == os.path.join(library.bundled_dir(), "copyright-line.svg")
    assert library.resolve("nothing.svg") is None and library.resolve("") is None


def test_a_name_is_never_taken_as_a_path(folder):
    secret = _write(folder / "elsewhere" / "secret.svg", SVG_BOX)
    for ref in ("../elsewhere/secret.svg", "..\\elsewhere\\secret.svg", "sub/secret.svg", ".hidden.svg", "notes.txt", "C:secret.svg"):
        assert not library.is_name(ref), ref
        assert library.resolve(ref) is None or ref == secret
    assert library.resolve(secret) == secret, "a path chosen before markers had names still works where the file is"
    assert library.resolve(str(folder / "elsewhere" / "nope.svg")) is None
    assert Marks(logo="../elsewhere/secret.svg").has_logo() is False and Marks(logo=secret).has_logo() is True


def test_adding_a_file_copies_it_and_never_overwrites(folder):
    src = _write(folder / "pics" / "mark.svg", SVG_BOX)
    assert library.add(src) == "mark.svg" and os.path.isfile(os.path.join(library.user_dir(), "mark.svg"))
    assert library.add(src) == "mark_2.svg" and library.add(src) == "mark_3.svg"
    assert library.add(library.resolve("simple-text.svg")) == "simple-text_2.svg", "a sample's name is not taken over either"
    with pytest.raises(ValueError, match="does not exist"):
        library.add(str(folder / "missing.svg"))
    with pytest.raises(ValueError, match="SVG, PNG"):
        library.add(_write(folder / "pics" / "notes.txt", "x"))
    big = folder / "pics" / "big.svg"
    big.write_bytes(b"x" * (logoimage.MAX_SVG_BYTES + 1))
    with pytest.raises(ValueError, match="too big"):
        library.add(str(big))




# ------------------------------------------------------------ SVG variables
def _sprite(path, variables=None, size=400):
    """The marker drawn on a square picture so that its longer side fits it: (premultiplied RGB, alpha)."""
    part = dtmark.marker_part(path, variables, size, size, base="larger")
    return part.rgb, part.alpha


def test_an_svg_marker_is_drawn_with_the_text_colour_and_font_chosen(folder):
    svg = _write(_user("t.svg"), SVG_TEXT)
    red = Marks(logo="t.svg", logo_text="Hello", logo_color="#ff0000", logo_opacity=1.0, logo_bold=True, logo_italic=True, logo_font="Arial")
    v = marker_variables(red)
    assert (v["WATERMARK_TEXT"], v["WATERMARK_COLOR"], v["WATERMARK_FONT_FAMILY"], v["WATERMARK_FONT_STYLE"], v["WATERMARK_FONT_WEIGHT"]) == ("Hello", "#ff0000", "Arial", "italic", "700")
    rgb, alpha = _sprite(svg, v)
    solid = alpha > 0.95
    assert solid.any() and rgb[solid][:, 0].mean() > 240 and rgb[solid][:, 1].max() < 12, "the text is red"
    blue = _sprite(svg, marker_variables(Marks(logo_text="Hello", logo_color="#0000ff")))
    assert blue[0][blue[1] > 0.95][:, 2].mean() > 240
    nothing = _sprite(svg, marker_variables(Marks(logo_text="")))
    assert (nothing[1] > 0.1).sum() == 0, "no text: nothing is drawn"
    defaults = marker_variables(Marks())
    assert defaults["WATERMARK_FONT_FAMILY"] == "sans-serif" and defaults["WATERMARK_FONT_STYLE"] == "normal" and defaults["WATERMARK_FONT_WEIGHT"] == "400" and defaults["WATERMARK_COLOR"] == "#ffffff"


def test_text_with_markup_in_it_cannot_break_the_svg(folder):
    svg = _write(_user("t.svg"), SVG_TEXT)
    for text in ('Tom & Jerry <b>', '"quoted" \'single\'', '</text><rect width="400" height="100" fill="#f00"/><text>', "]]>&#x26;&lt;"):
        v = marker_variables(Marks(logo_text=text, logo_color="#00ff00", logo_font='Ar"ial'))
        rgb, alpha = _sprite(svg, v)
        solid = alpha > 0.95
        assert 0 < solid.mean() < 0.4, f"only the text is drawn, not an injected rectangle: {text!r}"
        assert rgb[solid][:, 0].max() == 0, "the injected red never appears"


def test_the_film_s_details_are_filled_in_and_a_value_is_not_read_again(folder):
    svg = _write(_user("t.svg"), SVG_TEXT)
    vars_ = {"CAMERA": "Pentax K1000", "EXIF.YEAR": "1987", "FILM": "$(CAMERA)"}
    plain = marker_variables(Marks(logo_text="$(CAMERA) $(EXIF.YEAR)"), vars_)
    assert plain["WATERMARK_TEXT"] == "Pentax K1000 1987"
    assert marker_variables(Marks(logo_text="$(FILM)"), vars_)["WATERMARK_TEXT"] == "$(CAMERA)", "a value that looks like a variable is just text"
    assert marker_variables(Marks(logo_text="$(MISSING-none)"), vars_)["WATERMARK_TEXT"] == "none"
    template = _write(_user("film.svg"), SVG_TEXT.replace("$(WATERMARK_TEXT)", "$(CAMERA) / $(EXIF.YEAR-no date)"))
    a = _sprite(template, marker_variables(Marks(logo_color="#ffffff"), vars_))
    b = _sprite(template, marker_variables(Marks(logo_color="#ffffff"), {}))
    assert (a[1] > 0.5).sum() != (b[1] > 0.5).sum(), "a different camera and year draw different letters"


def test_darktable_s_own_variable_names_work_in_a_text_watermark(folder):
    without = mark_parts(GREY.shape, Marks(text="(c) $(EXIF.YEAR) $(CAMERA)"))
    withvars = mark_parts(GREY.shape, Marks(text="(c) $(EXIF.YEAR) $(CAMERA)"), variables={"EXIF.YEAR": "1987", "CAMERA": "Pentax K1000"})
    assert len(without) == len(withvars) == 1 and withvars[0].box[2] > without[0].box[2], "the words are longer once the variables are filled in"
    assert mark_parts(GREY.shape, Marks(text="$(NOTHING)")) == [], "a text that comes to nothing draws nothing"
    assert not np.array_equal(apply_marks(GREY, Marks(text="$(CAMERA)"), variables={"CAMERA": "Pentax"}), GREY)



def test_variables_reach_the_picture_through_the_render_parameters(folder):
    from photoeditor.desktop.export_worker import default_edit_state
    from photoeditor.desktop.render import EditParams

    state = default_edit_state(True)
    assert EditParams.from_dict(state).wm_vars == (), "a photo with no variables"
    assert EditParams.from_dict({**state, "wm_vars": [["CAMERA", "Pentax K1000"]]}).wm_vars == (("CAMERA", "Pentax K1000"),)
    assert hash(EditParams.from_dict({**state, "wm_vars": [("A", "b")]})) is not None, "the parameters stay hashable: the renderer keys its caches on them"



def test_the_example_watermark_presets_are_complete_and_draw_the_pictures_own_details(folder):
    from photoeditor.features.lookpresets import builtin, share
    from photoeditor.features.metadata.models import MetadataConfig

    names = [n for n in builtin.names() if n.startswith("Watermarks (EFAS Examples)/")]
    assert len(names) >= 4
    portra = V.build("a/Roll 1/frame.jpg", MetadataConfig(camera_make="Pentax", camera_model="K1000", lens_model="SMC 50mm f/2", film="Kodak Portra 400", film_iso=400, capture_date="2024-03-09"))
    hp5 = V.build("a/Roll 1/frame.jpg", MetadataConfig(camera_make="Nikon", camera_model="FM2", film="Ilford HP5 Plus", film_iso=400, capture_date="2021-06-01"))
    for name in names:
        look = builtin.get(name)
        assert builtin.description(name), name
        assert look["wm_film"] == "off" and look["wm_info"] is False, "the preset sets the whole watermark: no canister, no camera text beside it"
        assert share.clean_look(look) == {k: v for k, v in look.items() if k != "marks"} | {"marks": share.clean_look(look)["marks"]}, "nothing in it is dropped by the checks a shared file goes through"
        marks = Marks.from_dict(look["marks"])
        assert marks.has_logo() or marks.has_text(), name
        if marks.logo:
            assert library.is_name(marks.logo) and library.resolve(marks.logo) == os.path.join(library.bundled_dir(), marks.logo), "it uses a sample marker that comes with EFAS: it works everywhere"
        a, b = apply_marks(GREY, marks, variables=portra), apply_marks(GREY, marks, variables=hp5)
        assert not np.array_equal(a, GREY), name
        if "Film" in name:   # the film and camera ones; the copyright line is the frame's year, and the last one the roll's name and the file's
            assert not np.array_equal(a, b), f"{name}: a different film and camera write different words"



# ------------------------------------------------------------ darktable's sizing, placing and drawing (dtmark.py)
def _box(name="box.svg", shape=GREY.shape, **kw):
    kw.setdefault("logo_opacity", 1.0)
    return mark_parts(shape, Marks(logo=name, **kw))[0].box


def test_a_markers_size_is_whole_pixels_as_darktable_counts_it():
    d = dtmark.svg_dimension
    assert d('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="5.5" viewBox="0 0 100 5.5"/>') == (100, 6), "the size the file states, rounded: a strip 5.5 high is 6"
    assert d('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 50 50"/>') == (200, 100)
    assert d('<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="5mm"/>') == (38, 19), "lengths in millimetres, at 96 dpi"
    assert d('<svg xmlns="http://www.w3.org/2000/svg" width="300" viewBox="0 0 40 10"/>') == (300, 75), "one side and the shape of the viewBox"
    assert d('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 10"/>') == (32767, 8192), "no size: the viewBox fitted into a 32767 pixel square"
    assert d('<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 40 10"/>') == (32767, 8192), "a percentage is no size either"
    assert d("<svg/>") == (512, 512)


def test_the_marker_is_sized_by_scale_on_the_way_darktable_does():
    iw, ih = 900, 600
    wide, tall = (200, 100), (40, 100)
    L = dtmark.layout
    # image: a wide marker's width is the picture's width, a tall one's height is the picture's height (and 100% fits)
    a = L(wide, iw, ih)
    assert (a.scale, a.width, a.height) == (4.5, 900, 450)
    b = L(tall, iw, ih)
    assert (b.scale, b.width, b.height) == (6.0, 240, 600)
    assert L(wide, iw, ih, scale_percent=50).width == 450 and L(wide, iw, ih, scale_percent=500).width == 4500
    # larger / smaller border: the marker's longer side is that border of the picture
    assert (L(wide, iw, ih, base="larger").width, L(wide, iw, ih, base="larger").height) == (900, 450)
    assert (L(wide, iw, ih, base="smaller").width, L(wide, iw, ih, base="smaller").height) == (600, 300)
    assert (L(tall, iw, ih, base="larger").width, L(tall, iw, ih, base="larger").height) == (360, 900)
    assert (L(tall, iw, ih, base="smaller").width, L(tall, iw, ih, base="smaller").height) == (240, 600)
    # height: the marker's height is the picture's height
    assert (L(wide, iw, ih, base="height").width, L(wide, iw, ih, base="height").height) == (1200, 600)
    # advanced: any picture dimension against either marker dimension
    for image_side, marker_side, expect in (("width", "width", (900, 450)), ("width", "height", (1800, 900)), ("height", "width", (600, 300)), ("height", "height", (1200, 600)),
                                            ("larger", "width", (900, 450)), ("larger", "height", (1800, 900)), ("smaller", "width", (600, 300)), ("smaller", "height", (1200, 600))):
        got = L(wide, iw, ih, base="advanced", image_side=image_side, marker_side=marker_side)
        assert (got.width, got.height) == expect, (image_side, marker_side)
    assert L(wide, iw, ih).wbase == 900 and L(wide, iw, ih).hbase == 600
    assert (L(wide, iw, ih, base="larger").wbase, L(wide, iw, ih, base="larger").hbase) == (900, 900), "on the larger border an offset is a share of that border both ways"
    assert (L(wide, iw, ih, base="smaller").wbase, L(wide, iw, ih, base="smaller").hbase) == (600, 600)


def test_a_marker_fits_the_cropped_picture_whatever_its_shape(folder):
    """The same marker and settings on a landscape, a portrait and a square crop: 100% of image fits the marker's longer side to the picture's width or height, as darktable's does."""
    _write(_user("strip.svg"), '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="5.5" viewBox="0 0 100 5.5"><rect width="100" height="5.5" fill="#fff"/></svg>')
    _write(_user("tall.svg"), '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="100" viewBox="0 0 40 100"><rect width="40" height="100" fill="#fff"/></svg>')
    for shape in ((600, 900, 3), (900, 600, 3), (700, 700, 3)):
        ih, iw = shape[:2]
        x, y, w, h = _box("strip.svg", shape, logo_align=6)
        assert (x, w) == (0, iw) and y + h == ih, ("a strip fits the picture's width and sits on its bottom edge", shape, (x, y, w, h))
        x, y, w, h = _box("tall.svg", shape)
        assert h == ih and w == round(ih * 0.4) and x == (iw - w) // 2 or abs(x - (iw - w) / 2) <= 1, ("a tall marker fits the height and is centred", shape, (x, y, w, h))


def test_alignment_keeps_a_turned_marker_inside_the_corner(folder):
    _write(_user("box.svg"), SVG_BOX)
    iw, ih = 900, 600
    corners = {0: (0, 0), 2: (iw, 0), 6: (0, ih), 8: (iw, ih)}
    for angle in (0, 20, 90, -135):
        for align, (cx, cy) in corners.items():
            x, y, w, h = _box(logo_base="smaller", logo_scale=40, logo_align=align, logo_rotation=angle)
            assert (x == 0 if cx == 0 else abs(x + w - iw) <= 1) and (y == 0 if cy == 0 else abs(y + h - ih) <= 1), (angle, align, (x, y, w, h))
    x, y, w, h = _box(logo_base="smaller", logo_scale=40, logo_align=4, logo_rotation=33)
    assert abs((x + w / 2) - iw / 2) <= 1 and abs((y + h / 2) - ih / 2) <= 1, "the middle is the picture's middle"
    x, y, w, h = _box(logo_base="smaller", logo_scale=40, logo_align=1)
    assert abs((x + w / 2) - iw / 2) <= 1 and y == 0, "top, centred"


def test_a_marker_is_moved_by_offsets_that_are_shares_of_the_base(folder):
    _write(_user("box.svg"), SVG_BOX)   # 200 by 100
    base = dict(logo_base="smaller", logo_scale=30, logo_align=6)
    x0, y0, w0, h0 = _box(**base)
    assert (x0, y0, w0, h0) == (0, 510, 180, 90), "bottom left, the marker's longer side 30% of the shorter side (600)"
    assert _box(**base, logo_xoff=0.1, logo_yoff=-0.2) == (60, 390, 180, 90), "an offset is a share of the base, which for the smaller border is 600 both ways"
    image = _box(logo_scale=50, logo_align=0, logo_xoff=0.1, logo_yoff=0.2)
    assert image[:2] == (90, 120), "on Image the base is the picture's own width and height"
    assert Marks.from_dict({"logo_xoff": 5, "logo_yoff": -5}).logo_xoff == 1.0 and Marks.from_dict({"logo_yoff": -5}).logo_yoff == -1.0
    assert Marks().to_dict() == {} and Marks(logo_xoff=0.25).to_dict() == {"logo_xoff": 0.25}


def test_dragging_a_marker_changes_its_offsets_and_keeps_its_alignment(folder):
    from photoeditor.features.watermark import layout

    _write(_user("box.svg"), SVG_BOX)
    m = Marks(logo="box.svg", logo_base="smaller", logo_scale=30, logo_opacity=1.0, logo_align=6)
    shape = GREY.shape
    x, y, w, h = mark_parts(shape, m)[0].box
    cx, cy = (x + w / 2) / 900, (y + h / 2) / 600
    same = layout.edit(m, "logo", cx, cy, 1.0, shape=shape)
    assert same.logo_align == 6 and abs(same.logo_xoff) < 0.002 and abs(same.logo_yoff) < 0.002, "dropped where it is: no offset"
    dragged = layout.edit(m, "logo", cx + 0.2, cy - 0.3, 1.0, shape=shape)
    assert dragged.logo_align == 6 and abs(dragged.logo_xoff - 0.3) < 0.002 and abs(dragged.logo_yoff + 0.3) < 0.002, "0.2 of the width is 180 pixels, 0.3 of the base (600)"
    nx, ny, nw, nh = mark_parts(shape, dragged)[0].box
    assert abs((nx + nw / 2) / 900 - (cx + 0.2)) < 0.003 and abs((ny + nh / 2) / 600 - (cy - 0.3)) < 0.003, "the marker is where it was dropped"
    bigger = layout.edit(m, "logo", cx, cy, 2.0, shape=shape)
    assert abs(bigger.logo_scale - 60.0) < 1e-9 and bigger.logo_align == 6
    assert layout.edit(m, "logo", cx, cy, 100.0, shape=shape).logo_scale == 500.0 and layout.edit(m, "logo", cx, cy, 0.001, shape=shape).logo_scale == 1.0, "inside darktable's 1-500%"
    assert layout.edit(m, "logo", 0.4, 0.6, 1.0).logo_scale == 30.0, "without the picture's shape only the size changes"
    edge = layout.edit(m, "logo", 5.0, -5.0, 1.0, shape=shape)
    assert 0 < edge.logo_xoff <= 1 and -1 <= edge.logo_yoff < 0, "the centre cannot be dragged off the picture"


def test_a_marker_the_older_way_is_the_same_marker_with_darktables_settings():
    old = {"logo": "x.svg", "logo_size": 0.5, "logo_scale_on": "long", "logo_position": "bottom_left", "logo_opacity": 0.8, "logo_rotation": 10.0}
    new = Marks.from_dict(old)
    assert (new.logo_scale, new.logo_base, new.logo_align, new.logo_opacity, new.logo_rotation) == (50.0, "larger", 6, 0.8, 10.0)
    assert abs(new.logo_xoff - 0.02) < 1e-9 and abs(new.logo_yoff + 0.02) < 1e-9, "the margin of 3% of the shorter side, as shares of the larger border (for a 3:2 picture)"
    for scale_on, base in (("fit", "image"), ("short", "smaller"), ("long", "larger"), ("width", "advanced"), ("height", "advanced")):
        assert Marks.from_dict({"logo": "x.svg", "logo_scale_on": scale_on}).logo_base == base, scale_on
    assert Marks.from_dict({"logo": "x.svg", "logo_scale_on": "width"}).logo_img == "width" and Marks.from_dict({"logo": "x.svg", "logo_scale_on": "height"}).logo_svg == "height"
    a = Marks.from_dict({"logo": "x.svg"})
    assert (a.logo_scale, a.logo_base, a.logo_align, a.logo_opacity) == (18.0, "smaller", 6, 0.9), "an old marker with nothing set had the old defaults"
    custom = Marks.from_dict({"logo": "x.svg", "logo_position": "custom", "logo_x": 0.25, "logo_y": 0.75, "logo_size": 1.0, "logo_scale_on": "fit"})
    assert custom.logo_align == 4 and abs(custom.logo_xoff + 0.25) < 1e-9 and abs(custom.logo_yoff - 0.25) < 1e-9
    assert Marks.from_dict({"logo": "x.svg", "logo_size": 50.0}).logo_scale == 500.0, "kept inside darktable's 1-500%"
    # what it stores now is read back as it is (the version says it is darktable's settings): the defaults of the new kind are not mistaken for the old
    again = Marks.from_dict(new.to_dict())
    assert again == new and Marks.from_dict(Marks(logo="x.svg").to_dict()) == Marks(logo="x.svg")
    assert Marks(logo="x.svg").to_dict() == {"logo": "x.svg", "v": 2} and Marks(logo="x.svg").logo_scale == 100.0 and Marks(logo="x.svg").logo_align == 4
    assert "v" not in Marks().to_dict()


def test_each_module_owns_its_own_part_of_the_marks():
    marks = Marks(logo="x.svg", logo_scale=40.0, text="old", info_size=0.05, canister_x=0.3, canister_y=0.4, canister_size=0.2)
    assert set(marks.part("watermark")) == {"logo", "logo_scale", "v"} and set(marks.part("canisterwm")) == {"text", "info_size", "canister_x", "canister_y", "canister_size"}
    assert marks.cleared("watermark").logo == "" and marks.cleared("watermark").text == "old" and marks.cleared("canisterwm").logo == "x.svg" and marks.cleared("canisterwm").text == ""
    other = Marks(logo="y.svg", logo_scale=70.0, text="other")
    taken = marks.with_part("watermark", other)
    assert (taken.logo, taken.logo_scale, taken.text, taken.canister_size) == ("y.svg", 70.0, "old", 0.2), "only the Watermark module's fields are taken"
    assert marks.with_part("canisterwm", other).text == "other" and marks.with_part("canisterwm", other).logo == "x.svg"
    assert marks.with_part("watermark", marks.part("watermark")) == marks and marks.with_part("canisterwm", {}).text == ""


def test_the_marker_is_blended_as_darktable_does(folder):
    _write(_user("box.svg"), SVG_BOX)   # solid green
    half = apply_marks(GREY, Marks(logo="box.svg", logo_opacity=0.5, logo_base="smaller", logo_scale=100, logo_align=4))
    x, y, w, h = _box(logo_base="smaller", logo_scale=100, logo_align=4)
    centre = half[y + h // 2, x + w // 2].astype(int)
    assert abs(centre[0] - 64) <= 1 and abs(centre[1] - (128 * 0.5 + 255 * 0.5)) <= 1 and abs(centre[2] - 64) <= 1, "out = (1 - alpha) x picture + opacity x marker colour"
    assert np.array_equal(half[0, 0], GREY[0, 0]) or half[0, 0, 1] != 255, "outside the marker nothing changes"
    full = apply_marks(GREY, Marks(logo="box.svg", logo_opacity=1.0, logo_base="smaller", logo_scale=100, logo_align=4))
    assert tuple(full[y + h // 2, x + w // 2]) == (0, 255, 0)
    assert np.array_equal(apply_marks(GREY, Marks(logo="box.svg", logo_opacity=0.0)), GREY)


def test_a_marker_looks_the_same_at_any_resolution(folder):
    """The preview and the export are the same layout at two sizes: the same marker settings give the same picture, one scaled."""
    import cv2

    _write(_user("box.svg"), SVG_BOX.replace('<rect width="200" height="100" fill="#00ff00"/>', '<rect width="200" height="100" fill="#00ff00"/><circle cx="50" cy="50" r="30" fill="#0000ff"/>'))
    m = Marks(logo="box.svg", logo_opacity=0.9, logo_base="smaller", logo_scale=45, logo_align=2, logo_xoff=-0.04, logo_yoff=0.05, logo_rotation=17.0)
    big = apply_marks(np.full((1200, 1800, 3), 128, np.uint8), m).astype(float)
    small = apply_marks(np.full((600, 900, 3), 128, np.uint8), m).astype(float)
    shrunk = cv2.resize(big, (900, 600), interpolation=cv2.INTER_AREA)
    assert np.abs(shrunk - small).mean() < 1.0 and (np.abs(shrunk - small) > 90).mean() < 0.003


def test_the_scale_has_darktables_range():
    from photoeditor.features.watermark import dtmark as d

    assert d.SCALE_RANGE == (1.0, 500.0) and d.OFFSET_RANGE == (-1.0, 1.0) and d.ROTATE_RANGE == (-180.0, 180.0)
    assert Marks.from_dict({"logo": "a.svg", "v": 2, "logo_scale": 3000}).logo_scale == 500.0 and Marks.from_dict({"logo": "a.svg", "v": 2, "logo_scale": 0}).logo_scale == 1.0
    assert Marks.from_dict({"logo": "a.svg", "v": 2, "logo_align": 12}).logo_align == 8 and Marks.from_dict({"logo": "a.svg", "v": 2, "logo_base": "diagonal"}).logo_base == "image"


def test_a_marker_many_times_the_picture_is_drawn_without_a_picture_that_size(folder):
    import time
    _write(_user("box.svg"), SVG_BOX)   # 2:1, solid green
    huge = Marks(logo="box.svg", logo_opacity=1.0, logo_base="larger", logo_scale=500, logo_align=4)   # 500% of the longer side: 4500 by 2250 pixels on a 900 by 600 picture
    began = time.time()
    part = mark_parts(GREY.shape, huge)[0]
    out = apply_marks(GREY, huge)
    assert time.time() - began < 10 and part.alpha.shape[0] <= 600 and part.alpha.shape[1] <= 900, "only the part on the picture is made"
    assert part.box[2] == 4500 and part.box[3] == 2250 and part.box[0] == (900 - 4500) // 2 and part.box[1] == (600 - 2250) // 2, ("its box is the whole marker, running off the picture", part.box)
    assert (out[..., 1].astype(int) - out[..., 0].astype(int) > 200).all(), "it covers the whole picture in its green"
    gone = Marks(logo="box.svg", logo_opacity=1.0, logo_scale=50, logo_xoff=1.0)   # moved a whole picture width to the right: all of it is off the picture
    assert np.array_equal(apply_marks(GREY, gone), GREY), "a marker moved wholly off the picture draws nothing"


def test_a_picture_marker_is_scaled_and_turned_smoothly(folder):
    import cv2
    os.makedirs(library.user_dir(), exist_ok=True)
    assert cv2.imwrite(_user("white.png"), np.full((20, 20, 4), 255, np.uint8))
    out = apply_marks(GREY, Marks(logo="white.png", logo_opacity=1.0, logo_base="larger", logo_scale=500, logo_rotation=45.0))
    assert out.min() >= 254, "a turned square many times the picture is white all over"
    picture = np.zeros((20, 40, 4), np.uint8); picture[..., 3] = 255; picture[:, :20, 0] = 255; picture[:, 20:, 2] = 255
    assert cv2.imwrite(_user("two.png"), picture)   # red left, blue right (BGR order in the file: so blue left, red right)
    x, y, w, h = _box("two.png", logo_base="smaller", logo_scale=100)
    assert (w, h) == (600, 300), "a picture marker is its pixel size, scaled like any other (40 by 20, longer side the shorter side of the picture)"
    out = apply_marks(GREY, Marks(logo="two.png", logo_opacity=1.0, logo_base="smaller", logo_scale=100))
    assert out[y + h // 2, x + 30].tolist() != out[y + h // 2, x + w - 30].tolist(), "the two halves are two colours"


def test_an_old_text_watermark_can_be_made_a_marker(folder):
    from photoeditor.features.watermark.marks import TEXT_MARKER, text_as_marker

    old = Marks(text="(c) Me\nline two", text_size=0.04, text_opacity=0.7, text_color="#ff0000", text_font="Arial", text_bold=True, text_italic=True, text_position="top_right", text_rotation=15.0)
    new = text_as_marker(old)
    assert new.text == "" and not new.has_text() and new.logo == TEXT_MARKER == "simple-text.svg" and new.has_logo()
    assert new.logo_text == "(c) Me line two" and new.logo_color == "#ff0000" and new.logo_font == "Arial" and new.logo_bold and new.logo_italic
    assert new.logo_align == 2 and new.logo_opacity == 0.7 and new.logo_rotation == 15.0 and new.logo_base == "smaller"
    old_height = mark_parts(GREY.shape, old)[0].box[3]
    new_height = mark_parts(GREY.shape, new)[0].box[3]
    assert 0.4 < new_height / old_height < 2.5, "about as tall as it was (one line, though)"
    assert abs(text_as_marker(Marks(text="x", text_size=0.15)).logo_scale - 198.0) < 1e-9 and text_as_marker(Marks(text="x", text_size=0.0001)).logo_scale == 1.0, "kept inside the marker's size range"


def test_the_new_settings_are_kept_safe_when_read_back():
    bad = Marks.from_dict({"logo": "a.svg", "v": 2, "logo_rotation": 999, "logo_base": "diagonal", "logo_text": "x" * 900, "logo_color": "javascript:1", "logo_font": "f" * 900, "logo_bold": 1})
    assert bad.logo_rotation == 180.0 and bad.logo_base == "image" and len(bad.logo_text) == 511 and bad.logo_color == "white" and len(bad.logo_font) == 260 and bad.logo_bold is True
    assert Marks().to_dict() == {}, "an untouched Marks stores nothing, so photos saved before these settings read back the same"
    assert Marks.from_dict(Marks(logo="a.svg", logo_base="advanced", logo_text="hi").to_dict()) == Marks(logo="a.svg", logo_base="advanced", logo_text="hi")


def test_a_hundred_variables_a_big_svg_and_a_slow_template_stay_bounded(folder):
    svg = _write(_user("loop.svg"), SVG_TEXT.replace("$(WATERMARK_TEXT)", "$(A)" * 3000))
    sprite = _sprite(svg, {"A": "x" * 5000})
    assert sprite[0].shape[1] == 400
    assert V.MAX_SUBSTITUTIONS < 3000


def test_a_darktable_style_exif_strip_fills_in_every_part(folder):
    """The shape of the strips a darktable user wrote: a white bar, a title from the text, the date and gear on the left, the settings in the middle and the author on the right,
    all in darktable's own spellings ($(EXIF_FOCAL_LENGTH), $(EXIF.DATE), $(Xmp.dc.creator))."""
    from photoeditor.features.metadata.models import MetadataConfig

    strip = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="5.5" viewBox="0 0 100 5.5"><rect width="100" height="5.5" fill="#FFFFFF"/>'
             '<text x="50" y="2" font-size="1.3" fill="#404040" text-anchor="middle">$(WATERMARK_TEXT)</text>'
             '<text x="2" y="4.2" font-size="0.7" fill="#505050">$(EXIF.DATE) - $(EXIF.MODEL) - $(EXIF.LENS)</text>'
             '<text x="50" y="4.2" font-size="0.7" fill="#505050" text-anchor="middle">$(EXIF_FOCAL_LENGTH)mm f/$(EXIF_APERTURE) $(EXIF_EXPOSURE)s ISO$(EXIF_ISO)</text>'
             '<text x="98" y="4.2" font-size="0.7" fill="#505050" text-anchor="end">$(Xmp.dc.creator)</text></svg>')
    svg = _write(_user("strip.svg"), strip)
    base = dict(camera_model="K1000", lens_model="SMC 50mm f/2", focal_length_mm=50.0, max_aperture=2.0, film_iso=400, exposure_override="1/125", capture_date="2024-03-09")

    def ink(exif=None, **changes):
        v = V.build("a/b.jpg", MetadataConfig(**{**base, **changes}), source_exif=exif)
        part = dtmark.marker_part(svg, marker_variables(Marks(logo_text="Lion", logo_color="#404040"), v), 1800, 108, base="image")
        rgb, alpha = part.rgb, part.alpha
        return ((rgb[..., 0] < 200) & (alpha > 0.5)).astype(np.uint8), alpha   # the dark letters on the white bar

    whole, alpha = ink({"0th": {315: b"Ethan"}})
    h, w = whole.shape
    assert w == 1800 and abs(int((alpha > 0.5).any(axis=1).sum()) - 99) <= 1, "the bar keeps its shape: 100 by 5.5, centred in the marker's 100 by 6"
    if int(whole.sum()) < 1000:      # (about 2200 pixels of ink where the text is drawn; Qt 6.12's offscreen platform on Windows draws almost none of the small text, which the real platform does)
        pytest.skip("this Qt platform draws almost none of the strip's small text, so there is no ink to compare")
    right, middle, left = whole[:, int(w * 0.80):], whole[:, int(w * 0.40):int(w * 0.60), ], whole[:, :int(w * 0.30)]
    assert right.sum() > 0 and not np.array_equal(ink(None)[0], whole), "the author on the right is the scan's own Artist"
    assert not np.array_equal(ink({"0th": {315: b"Ethan"}}, exposure_override="1/500")[0], whole), "the shutter in the middle comes from the Exposure box"
    assert not np.array_equal(ink({"0th": {315: b"Ethan"}}, focal_length_mm=85.0)[0], whole) and not np.array_equal(ink({"0th": {315: b"Ethan"}}, max_aperture=1.4)[0], whole)
    assert not np.array_equal(ink({"0th": {315: b"Ethan"}}, capture_date="1999")[0], whole), "the date on the left"
    assert not np.array_equal(ink({"0th": {315: b"Ethan"}}, camera_model="FM2")[0], whole)
    assert left.sum() > 0 and middle.sum() > 0
