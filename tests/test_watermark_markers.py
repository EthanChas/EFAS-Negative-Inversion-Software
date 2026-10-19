"""Markers the way darktable does them: a watermarks folder found by name, SVG files with $(NAME) variables (its WATERMARK_* ones and the film's), scaling on a side of the picture, rotation."""
import os

import numpy as np
import pytest

from photoeditor.features.watermark import library, logoimage
from photoeditor.features.watermark import variables as V
from photoeditor.features.watermark.marks import Marks, apply_marks, marker_variables, mark_parts

SVG_TEXT = ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100" viewBox="0 0 400 100"><text x="10" y="70" font-family="$(WATERMARK_FONT_FAMILY)" font-weight="$(WATERMARK_FONT_WEIGHT)" '
            'font-style="$(WATERMARK_FONT_STYLE)" font-size="60" fill="$(WATERMARK_COLOR)">$(WATERMARK_TEXT)</text></svg>')
SVG_BOX = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100"><rect width="200" height="100" fill="#00ff00"/></svg>'
GREY = np.full((600, 900, 3), 128, np.uint8)


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
def test_an_svg_marker_is_drawn_with_the_text_colour_and_font_chosen(folder):
    svg = _write(_user("t.svg"), SVG_TEXT)
    red = Marks(logo="t.svg", logo_text="Hello", logo_color="#ff0000", logo_size=0.5, logo_opacity=1.0, logo_position="center", logo_bold=True, logo_italic=True, logo_font="Arial")
    v = marker_variables(red)
    assert (v["WATERMARK_TEXT"], v["WATERMARK_COLOR"], v["WATERMARK_FONT_FAMILY"], v["WATERMARK_FONT_STYLE"], v["WATERMARK_FONT_WEIGHT"]) == ("Hello", "#ff0000", "Arial", "italic", "700")
    rgb, alpha = logoimage.marker_sprite(svg, "long", 400, 1.0, v)
    solid = alpha > 0.95
    assert solid.any() and rgb[solid][:, 0].mean() > 240 and rgb[solid][:, 1].max() < 12, "the text is red"
    blue = logoimage.marker_sprite(svg, "long", 400, 1.0, marker_variables(Marks(logo_text="Hello", logo_color="#0000ff")))
    assert blue[0][blue[1] > 0.95][:, 2].mean() > 240
    nothing = logoimage.marker_sprite(svg, "long", 400, 1.0, marker_variables(Marks(logo_text="")))
    assert (nothing[1] > 0.1).sum() == 0, "no text: nothing is drawn"
    defaults = marker_variables(Marks())
    assert defaults["WATERMARK_FONT_FAMILY"] == "sans-serif" and defaults["WATERMARK_FONT_STYLE"] == "normal" and defaults["WATERMARK_FONT_WEIGHT"] == "400" and defaults["WATERMARK_COLOR"] == "#ffffff"


def test_text_with_markup_in_it_cannot_break_the_svg(folder):
    svg = _write(_user("t.svg"), SVG_TEXT)
    for text in ('Tom & Jerry <b>', '"quoted" \'single\'', '</text><rect width="400" height="100" fill="#f00"/><text>', "]]>&#x26;&lt;"):
        v = marker_variables(Marks(logo_text=text, logo_color="#00ff00", logo_font='Ar"ial'))
        rgb, alpha = logoimage.marker_sprite(svg, "long", 400, 1.0, v)
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
    a = logoimage.marker_sprite(template, "long", 400, 1.0, marker_variables(Marks(logo_color="#ffffff"), vars_))
    b = logoimage.marker_sprite(template, "long", 400, 1.0, marker_variables(Marks(logo_color="#ffffff"), {}))
    assert (a[1] > 0.5).sum() != (b[1] > 0.5).sum(), "a different camera and year draw different letters"


def test_darktable_s_own_variable_names_work_in_a_text_watermark(folder):
    without = mark_parts(GREY.shape, Marks(text="(c) $(EXIF.YEAR) $(CAMERA)"))
    withvars = mark_parts(GREY.shape, Marks(text="(c) $(EXIF.YEAR) $(CAMERA)"), variables={"EXIF.YEAR": "1987", "CAMERA": "Pentax K1000"})
    assert len(without) == len(withvars) == 1 and withvars[0].box[2] > without[0].box[2], "the words are longer once the variables are filled in"
    assert mark_parts(GREY.shape, Marks(text="$(NOTHING)")) == [], "a text that comes to nothing draws nothing"
    assert not np.array_equal(apply_marks(GREY, Marks(text="$(CAMERA)"), variables={"CAMERA": "Pentax"}), GREY)


# ------------------------------------------------------------ size and rotation
def test_the_size_can_be_a_share_of_either_side_the_width_or_the_height(folder):
    svg = _write(_user("box.svg"), SVG_BOX)   # twice as wide as it is tall
    def box(**kw):
        return mark_parts(GREY.shape, Marks(logo="box.svg", logo_size=0.5, logo_opacity=1.0, logo_position="center", **kw))[0].box[2:]
    assert box() == (300, 150), "the default: the marker's longer side is half the picture's shorter side (600)"
    assert box(logo_scale_on="short") == (300, 150)
    assert box(logo_scale_on="long") == (450, 225), "half the picture's longer side (900)"
    assert box(logo_scale_on="width") == (450, 225), "the marker's width is half the picture's width"
    assert box(logo_scale_on="height") == (600, 300), "the marker's height is half the picture's height: 300 high, so 600 wide"
    portrait = np.full((900, 600, 3), 128, np.uint8)
    tall = mark_parts(portrait.shape, Marks(logo="box.svg", logo_size=0.5, logo_opacity=1.0, logo_position="center", logo_scale_on="height"))[0].box[2:]
    assert tall == (900, 450)


def test_a_marker_can_be_turned(folder):
    _write(_user("box.svg"), SVG_BOX)
    m = Marks(logo="box.svg", logo_size=0.5, logo_opacity=1.0, logo_position="center")
    flat = mark_parts(GREY.shape, m)[0]
    turned = mark_parts(GREY.shape, Marks(**{**m.to_dict(), "logo_rotation": 90.0}))[0]
    assert abs(turned.box[2] - flat.box[3]) <= 2 and abs(turned.box[3] - flat.box[2]) <= 2, "a quarter turn swaps the width and the height"
    assert mark_parts(GREY.shape, Marks(**{**m.to_dict(), "logo_rotation": 45.0}))[0].box[2] > flat.box[2]
    assert not np.array_equal(apply_marks(GREY, Marks(**{**m.to_dict(), "logo_rotation": 30.0})), apply_marks(GREY, m))


def test_the_new_settings_are_kept_safe_when_read_back():
    bad = Marks.from_dict({"logo_rotation": 999, "logo_scale_on": "diagonal", "logo_text": "x" * 900, "logo_color": "javascript:1", "logo_font": "f" * 900, "logo_bold": 1})
    assert bad.logo_rotation == 180.0 and bad.logo_scale_on == "short" and len(bad.logo_text) == 511 and bad.logo_color == "white" and len(bad.logo_font) == 260 and bad.logo_bold is True
    assert Marks().to_dict() == {}, "an untouched Marks stores nothing, so photos saved before these settings read back the same"
    assert Marks.from_dict(Marks(logo="a.svg", logo_scale_on="width", logo_text="hi").to_dict()) == Marks(logo="a.svg", logo_scale_on="width", logo_text="hi")


def test_variables_reach_the_picture_through_the_render_parameters(folder):
    from photoeditor.desktop.export_worker import default_edit_state
    from photoeditor.desktop.render import EditParams

    state = default_edit_state(True)
    assert EditParams.from_dict(state).wm_vars == (), "a photo with no variables"
    assert EditParams.from_dict({**state, "wm_vars": [["CAMERA", "Pentax K1000"]]}).wm_vars == (("CAMERA", "Pentax K1000"),)
    assert hash(EditParams.from_dict({**state, "wm_vars": [("A", "b")]})) is not None, "the parameters stay hashable: the renderer keys its caches on them"


def test_a_hundred_variables_a_big_svg_and_a_slow_template_stay_bounded(folder):
    svg = _write(_user("loop.svg"), SVG_TEXT.replace("$(WATERMARK_TEXT)", "$(A)" * 3000))
    sprite = logoimage.marker_sprite(svg, "long", 400, 1.0, {"A": "x" * 5000})
    assert sprite[0].shape[1] == 400
    assert V.MAX_SUBSTITUTIONS < 3000


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
        rgb, alpha = logoimage.marker_sprite(svg, "width", 1800, 1.0, marker_variables(Marks(logo_text="Lion", logo_color="#404040"), v))
        return (rgb[..., 0] < 200).astype(np.uint8)   # the dark letters on the white bar

    whole = ink({"0th": {315: b"Ethan"}})
    h, w = whole.shape
    assert w == 1800 and abs(h - 99) <= 1, "the bar keeps its shape: 100 by 5.5"
    right, middle, left = whole[:, int(w * 0.80):], whole[:, int(w * 0.40):int(w * 0.60), ], whole[:, :int(w * 0.30)]
    assert right.sum() > 0 and not np.array_equal(ink(None), whole), "the author on the right is the scan's own Artist"
    assert not np.array_equal(ink({"0th": {315: b"Ethan"}}, exposure_override="1/500"), whole), "the shutter in the middle comes from the Exposure box"
    assert not np.array_equal(ink({"0th": {315: b"Ethan"}}, focal_length_mm=85.0), whole) and not np.array_equal(ink({"0th": {315: b"Ethan"}}, max_aperture=1.4), whole)
    assert not np.array_equal(ink({"0th": {315: b"Ethan"}}, capture_date="1999"), whole), "the date on the left"
    assert not np.array_equal(ink({"0th": {315: b"Ethan"}}, camera_model="FM2"), whole)
    assert left.sum() > 0 and middle.sum() > 0


def test_an_svg_with_a_fractional_size_or_a_viewbox_of_another_shape_keeps_its_shape(folder):
    def aspect(svg_text):
        return logoimage.svg_aspect(_write(_user("shape.svg"), svg_text))
    assert abs(aspect('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="5.5" viewBox="0 0 100 5.5"/>') - 100 / 5.5) < 1e-6, "not rounded to 100 by 5"
    assert abs(aspect('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 331 130" width="331" height="130"/>') - 331 / 130) < 1e-6
    assert abs(aspect('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 50 50"/>') - 2.0) < 1e-6, "the size the file states, as a browser shows it"
    assert abs(aspect('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 10"/>') - 4.0) < 1e-6, "a viewBox and no size"
    sprite = logoimage.marker_sprite(_write(_user("shape.svg"), '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="5.5" viewBox="0 0 100 5.5"><rect width="100" height="5.5" fill="#f00"/></svg>'), "width", 1000, 1.0)
    assert sprite[0].shape[:2] == (55, 1000) and sprite[1].min() > 0.99, "drawn to fill its whole rectangle"


# ------------------------------------------------------------ moving a marker: Move X and Move Y, dragging, and the old Text mark
def test_a_marker_is_moved_from_where_its_position_puts_it(folder):
    _write(_user("box.svg"), SVG_BOX)
    base = Marks(logo="box.svg", logo_size=0.3, logo_opacity=1.0, logo_position="bottom_left")
    x0, y0, w0, h0 = mark_parts(GREY.shape, base)[0].box
    moved = mark_parts(GREY.shape, Marks(**{**base.to_dict(), "logo_dx": 0.1, "logo_dy": -0.2}))[0].box
    assert moved == (x0 + 90, y0 - 120, w0, h0), "a tenth of the width to the right, a fifth of the height up"
    custom = Marks(**{**base.to_dict(), "logo_position": "custom", "logo_x": 0.5, "logo_y": 0.5, "logo_dx": 0.1})
    box = mark_parts(GREY.shape, custom)[0].box
    assert abs((box[0] + box[2] / 2) - (450 + 90)) <= 1, "from the dragged-to spot of an earlier version too"
    assert Marks.from_dict({"logo_dx": 5, "logo_dy": -5}).logo_dx == 1.0 and Marks.from_dict({"logo_dy": -5}).logo_dy == -1.0
    assert Marks().to_dict() == {} and Marks(logo_dx=0.25).to_dict() == {"logo_dx": 0.25}


def test_dragging_a_marker_changes_its_offsets_and_keeps_its_position(folder):
    from photoeditor.features.watermark import layout

    _write(_user("box.svg"), SVG_BOX)
    m = Marks(logo="box.svg", logo_size=0.3, logo_opacity=1.0, logo_position="bottom_left")
    shape = GREY.shape
    x, y, w, h = mark_parts(shape, m)[0].box
    cx, cy = (x + w / 2) / 900, (y + h / 2) / 600
    same = layout.edit(m, "logo", cx, cy, 1.0, shape=shape)
    assert same.logo_position == "bottom_left" and abs(same.logo_dx) < 0.002 and abs(same.logo_dy) < 0.002, "dropped where it is: no offset"
    dragged = layout.edit(m, "logo", cx + 0.2, cy - 0.3, 1.0, shape=shape)
    assert dragged.logo_position == "bottom_left" and abs(dragged.logo_dx - 0.2) < 0.002 and abs(dragged.logo_dy + 0.3) < 0.002
    nx, ny, nw, nh = mark_parts(shape, dragged)[0].box
    assert abs((nx + nw / 2) / 900 - (cx + 0.2)) < 0.003 and abs((ny + nh / 2) / 600 - (cy - 0.3)) < 0.003, "the marker is where it was dropped"
    bigger = layout.edit(m, "logo", cx, cy, 2.0, shape=shape)
    assert abs(bigger.logo_size - 0.6) < 1e-9 and bigger.logo_position == "bottom_left"
    old_way = layout.edit(m, "logo", 0.4, 0.6, 1.0)
    assert old_way.logo_position == "custom" and (old_way.logo_x, old_way.logo_y) == (0.4, 0.6) and old_way.logo_dx == 0 == old_way.logo_dy, "without the picture's shape: the earlier behaviour"
    edge = layout.edit(m, "logo", 5.0, -5.0, 1.0, shape=shape)
    assert 0 < edge.logo_dx <= 1 and -1 <= edge.logo_dy < 0, "the centre cannot be dragged off the picture"


def test_an_old_text_watermark_can_be_made_a_marker(folder):
    from photoeditor.features.watermark.marks import TEXT_MARKER, text_as_marker

    old = Marks(text="(c) Me\nline two", text_size=0.04, text_opacity=0.7, text_color="#ff0000", text_font="Arial", text_bold=True, text_italic=True, text_position="top_right", text_rotation=15.0)
    new = text_as_marker(old)
    assert new.text == "" and not new.has_text() and new.logo == TEXT_MARKER == "simple-text.svg" and new.has_logo()
    assert new.logo_text == "(c) Me line two" and new.logo_color == "#ff0000" and new.logo_font == "Arial" and new.logo_bold and new.logo_italic
    assert new.logo_position == "top_right" and new.logo_opacity == 0.7 and new.logo_rotation == 15.0 and new.logo_scale_on == "short"
    old_height = mark_parts(GREY.shape, old)[0].box[3]
    new_height = mark_parts(GREY.shape, new)[0].box[3]
    assert 0.4 < new_height / old_height < 2.5, "about as tall as it was (one line, though)"
    assert abs(text_as_marker(Marks(text="x", text_size=0.15)).logo_size - 1.98) < 1e-9 and text_as_marker(Marks(text="x", text_size=0.0001)).logo_size == 0.01, "kept inside the marker's size range"



# ------------------------------------------------------------ the size has no limit
def test_the_markers_size_has_no_practical_limit():
    from photoeditor.features.watermark.marks import LOGO_SIZE_RANGE, LOGO_SIZE_SLIDER
    assert LOGO_SIZE_SLIDER == (0.01, 5.0) and LOGO_SIZE_RANGE == (0.01, 100.0), "the slider goes to 500%, the box beside it to 10000%"
    assert Marks.from_dict({"logo_size": 3.0}).logo_size == 3.0 and Marks.from_dict({"logo_size": 50}).logo_size == 50.0, "far beyond the old 80%"
    assert Marks.from_dict({"logo_size": 1e9}).logo_size == 100.0 and Marks.from_dict({"logo_size": 0}).logo_size == 0.01


def test_a_marker_many_times_the_picture_is_drawn_without_a_picture_that_size(folder):
    import time
    _write(_user("box.svg"), SVG_BOX)   # 2:1, solid green
    huge = Marks(logo="box.svg", logo_size=40.0, logo_opacity=1.0, logo_position="center")   # 4000% of the shorter side: 24000 by 12000 pixels on a 900 by 600 picture
    began = time.time()
    part = mark_parts(GREY.shape, huge)[0]
    out = apply_marks(GREY, huge)
    assert time.time() - began < 10, "only the part on the picture is made"
    assert part.alpha.shape[0] <= 600 and part.alpha.shape[1] <= 900, "the piece drawn is no bigger than the picture"
    assert part.box[2] == 24000 and part.box[3] == 12000 and part.box[0] == (900 - 24000) // 2 and part.box[1] == (600 - 12000) // 2, ("its box is the whole marker, running off the picture", part.box)
    assert (out[..., 1].astype(int) - out[..., 0].astype(int) > 200).all(), "it covers the whole picture in its green"
    gone = Marks(logo="box.svg", logo_size=0.5, logo_opacity=1.0, logo_position="center", logo_dx=1.0)   # moved a whole picture width to the right: all of it is off the picture
    assert np.array_equal(apply_marks(GREY, gone), GREY), "a marker moved wholly off the picture draws nothing"


def test_the_part_of_a_big_marker_that_is_drawn_matches_the_whole_one(folder, monkeypatch):
    """The same marker drawn whole and drawn as a window of itself (forced here with a tiny limit) must look the same, turned or not, SVG or picture."""
    import cv2
    _write(_user("box.svg"), SVG_BOX.replace('<rect width="200" height="100" fill="#00ff00"/>', '<rect width="200" height="100" fill="#00ff00"/><circle cx="50" cy="50" r="30" fill="#0000ff"/>'))
    picture = np.zeros((60, 100, 4), np.uint8); picture[..., 3] = 255; picture[:30, :50, 0] = 255; picture[30:, 50:, 2] = 255
    cv2.imwrite(_user("pic.png"), cv2.cvtColor(picture, cv2.COLOR_RGBA2BGRA))
    normal_limit = logoimage.FULL_SPRITE_PIXELS
    for name in ("box.svg", "pic.png"):
        for degrees in (0.0, 30.0, 90.0):
            m = Marks(logo=name, logo_size=0.5, logo_opacity=0.9, logo_position="center", logo_rotation=degrees, logo_dx=0.05)
            whole = apply_marks(GREY, m).astype(int)
            monkeypatch.setattr(logoimage, "FULL_SPRITE_PIXELS", 100)
            windowed_part = mark_parts(GREY.shape, m)[0]
            windowed = apply_marks(GREY, m).astype(int)
            monkeypatch.setattr(logoimage, "FULL_SPRITE_PIXELS", normal_limit)   # (monkeypatch.undo() would also put the data folder back)
            assert windowed_part.whole is not None, "the window path was taken"
            assert abs(windowed - whole).mean() < 1.5 and (abs(windowed - whole) > 60).mean() < 0.01, (name, degrees, abs(windowed - whole).mean())
            assert mark_parts(GREY.shape, m)[0].box[2:] == windowed_part.box[2:] or abs(mark_parts(GREY.shape, m)[0].box[2] - windowed_part.box[2]) <= 1, "the same box"


def test_a_picture_marker_many_times_the_picture_covers_it(folder):
    import cv2
    os.makedirs(library.user_dir(), exist_ok=True)
    assert cv2.imwrite(_user("white.png"), np.full((20, 20, 4), 255, np.uint8))
    out = apply_marks(GREY, Marks(logo="white.png", logo_size=30.0, logo_opacity=1.0, logo_position="center", logo_rotation=45.0))
    assert out.min() >= 254, "a turned square many times the picture is white all over"


def test_fit_the_picture_sizes_a_marker_the_way_darktable_does(folder):
    """darktable's default: a wide marker's width (a tall one's height) is the picture's width (height) times the scale, so 100% fits the picture."""
    _write(_user("strip.svg"), '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="5.5" viewBox="0 0 100 5.5"><rect width="100" height="5.5" fill="#fff"/></svg>')
    _write(_user("tall.svg"), '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="100" viewBox="0 0 40 100"><rect width="40" height="100" fill="#fff"/></svg>')
    for shape in (GREY.shape, (900, 600, 3)):   # landscape and portrait
        ih, iw = shape[:2]
        strip = mark_parts(shape, Marks(logo="strip.svg", logo_scale_on="fit", logo_size=1.0, logo_opacity=1.0, logo_position="bottom_left"))[0].box
        assert strip[2] == iw and strip[0] == 0 and strip[1] + strip[3] == ih - (ih - strip[1] - strip[3]), (shape, strip)
        assert abs(strip[2] / strip[3] - 100 / 5.5) < 0.2, "a strip that fits the width keeps its shape and sits square to the edges"
        half = mark_parts(shape, Marks(logo="strip.svg", logo_scale_on="fit", logo_size=0.5, logo_opacity=1.0))[0].box
        assert abs(half[2] - iw * 0.5) <= 1
        tall = mark_parts(shape, Marks(logo="tall.svg", logo_scale_on="fit", logo_size=1.0, logo_opacity=1.0))[0].box
        assert tall[3] == ih and abs(tall[2] / tall[3] - 0.4) < 0.01, "a tall marker fits the height"
    assert "fit" in logoimage.SCALE_ON and Marks.from_dict({"logo_scale_on": "fit"}).logo_scale_on == "fit"
    assert Marks().logo_scale_on == "short", "photos and presets made before keep their size"
