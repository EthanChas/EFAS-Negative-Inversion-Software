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
