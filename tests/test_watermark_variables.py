"""The $(NAME) variables of watermark text and SVG markers: darktable's syntax, and the names a film scanner can give."""
import datetime as dt

import pytest

from photoeditor.features.metadata.models import MetadataConfig
from photoeditor.features.watermark import variables as V

VARS = {"A": "hello world", "EMPTY": "", "FILE.NAME": "4N0A7862", "B": "x", "AMP": 'Tom & "Jerry" <b>'}


@pytest.mark.parametrize("text, expected", [
    ("plain text", "plain text"),
    ("$(A)", "hello world"),
    ("by $(B) and $(B)", "by x and x"),
    ("$(NOPE)|", "|"),
    ("$(a)", "hello world"),                      # a name is found in any case
    ("$(EMPTY-none)", "none"), ("$(A-none)", "hello world"),
    ("$(EMPTY-$(B))", "x"),                       # a default may hold a variable
    ("$(A+yes)", "yes"), ("$(EMPTY+yes)", ""), ("$(A+<$(B)>)", "<x>"),
    ("$(A:6)", "world"), ("$(A:0:5)", "hello"), ("$(A:-5)", "world"), ("$(A:-5:3)", "wor"), ("$(A:0:-6)", "hello"), ("$(A:99)", ""), ("$(A:x)", "hello world"),
    ("$(A^)", "Hello world"), ("$(A^^)", "HELLO WORLD"), ("$(A,)", "hello world"), ("$(A,,)", "hello world"),
    ("$(FILE.NAME,)", "4N0A7862"), ("$(AMP,,)", 'tom & "jerry" <b>'),
    ("$(A/o/0)", "hell0 world"), ("$(A//o/0)", "hell0 w0rld"), ("$(A/#hello/bye)", "bye world"), ("$(A/%world/there)", "hello there"), ("$(A/#nope/x)", "hello world"), ("$(A/o/)", "hell world"),
    ("$(A#hello )", "world"), ("$(A%orld)", "hello w"), ("$(A#nope)", "hello world"),
    ("$(unclosed", "$(unclosed"), ("$(A", "$(A"), ("$()", ""), ("$(1bad)", ""), ("cost $5 (or so)", "cost $5 (or so)"),
])
def test_the_syntax(text, expected):
    assert V.expand(text, VARS) == expected


def test_a_value_is_put_in_as_it_is_and_never_read_again():
    assert V.expand("$(A)", {"A": "$(B)", "B": "no"}) == "$(B)", "a value is not expanded for variables of its own"
    assert V.expand("$(A)", {"A": "$(A)"}) == "$(A)"


def test_a_template_cannot_run_away():
    deep = "$(E-$(E-$(E-$(E-$(E-end)))))"
    assert V.expand(deep, {"E": ""}) in ("", "end"), "defaults inside defaults stop after a few levels"
    assert len(V.expand("$(A)" * 5000, {"A": "x"})) <= V.MAX_SUBSTITUTIONS
    assert len(V.expand("$(A)", {"A": "y" * 50000})) == V.MAX_VALUE


def test_values_put_into_an_svg_are_made_safe_for_xml():
    out = V.expand('<text font-family="$(AMP)">$(AMP)</text>', VARS, V.xml_escape)
    assert out == '<text font-family="Tom &amp; &quot;Jerry&quot; &lt;b&gt;">Tom &amp; &quot;Jerry&quot; &lt;b&gt;</text>'
    assert V.expand("$(AMP,,)", VARS, V.xml_escape) == "tom &amp; &quot;jerry&quot; &lt;b&gt;", "made safe after the operators, so an entity is never cut in half"
    assert V.expand("$(EMPTY-<ok>)", VARS, V.xml_escape) == "<ok>", "the template's own default text is the template's: it is not touched"
    assert V.xml_escape("it's") == "it&apos;s"


def test_uses_tells_whether_an_svg_wants_a_variable():
    svg = '<text fill="$(WATERMARK_COLOR)">$(WATERMARK_TEXT-none)</text>'
    assert V.uses(svg, "WATERMARK_TEXT") and V.uses(svg, "WATERMARK_COLOR") and not V.uses(svg, "WATERMARK_FONT_FAMILY")


def test_the_variables_of_a_film_frame():
    meta = MetadataConfig(camera_make="Pentax", camera_model="K1000", lens_model="SMC Pentax-M 50mm f/2", focal_length_mm=50.0, max_aperture=2.0, film="Kodak Portra 400", film_iso=400,
                          film_manufacturer="Kodak", format="35mm", capture_date="2024-03-09 14:30", capture_roll="Holiday", capture_frame=7, developer="Rodinal", scanning="Canon R6 + macro",
                          location_city="Cape Town", note="sunset", push_pull=1)
    v = V.build(r"C:\scans\Holiday 2024\4N0A7862.CR2", meta, now=dt.datetime(2026, 10, 19, 15, 7), app_version="0.9.0")
    assert v["FILE.NAME"] == "4N0A7862" and v["FILE.EXTENSION"] == "CR2" and v["FILE.FOLDER"] == "Holiday 2024", "the folder's name, not the whole path"
    assert (v["YEAR"], v["YEAR.SHORT"], v["MONTH"], v["MONTH.LONG"], v["DAY"], v["HOUR"], v["MINUTE"]) == ("2026", "26", "10", "October", "19", "15", "07"), "today"
    assert (v["EXIF.YEAR"], v["EXIF.MONTH"], v["EXIF.MONTH.SHORT"], v["EXIF.DAY"], v["EXIF.HOUR"], v["EXIF.MINUTE"], v["EXIF.TIME.REGIONAL"]) == ("2024", "3", "Mar", "9", "14", "30", "14:30"), "the frame's date"
    assert v["EXIF.MAKER"] == v["MAKER"] == "Pentax" and v["EXIF.MODEL"] == "K1000" and v["CAMERA"] == "Pentax K1000" and v["LENS"] == "SMC Pentax-M 50mm f/2" == v["EXIF.LENS"]
    assert v["EXIF.ISO"] == "400" == v["FILM.ISO"] and v["FILM"] == "Kodak Portra 400" and v["ROLL.NAME"] == "Holiday" and v["EXIF.FOCAL.LENGTH"] == "50 mm" and v["EXIF.APERTURE"] == "f/2"
    assert v["ROLL.DEVELOPER"] == "Rodinal" and v["ROLL.SCANNED_WITH"] == "Canon R6 + macro" and v["FRAME"] == "7" and v["LOCATION.CITY"] == "Cape Town" and v["PUSH.PULL"] == "Push +1"
    assert v["EFAS.VERSION"] == "0.9.0" and v["NL"] == "\n"
    assert V.expand("(c) $(EXIF.YEAR) $(CAMERA) - $(FILM)", v) == "(c) 2024 Pentax K1000 - Kodak Portra 400"


def test_a_frame_that_knows_little_gives_empty_values_not_errors():
    v = V.build("", MetadataConfig(capture_date="1999"), now=dt.datetime(2026, 1, 2, 3, 4))
    assert v["FILE.NAME"] == "" and v["ROLL.NAME"] == "" and v["EXIF.YEAR"] == "1999" and v["EXIF.MONTH"] == "" and v["EXIF.DATE.REGIONAL"] == "1999"
    assert V.expand("$(EXIF.MONTH-?) $(CAMERA-no camera)", v) == "? no camera"
    assert V.build("x.jpg", MetadataConfig(capture_date="2024-03"), now=dt.datetime(2026, 1, 2))["EXIF.DATE.REGIONAL"] == "March 2024"
    assert V.build("x.jpg", MetadataConfig(capture_date="not a date"), now=dt.datetime(2026, 1, 2))["EXIF.YEAR"] == "", "listed, but empty"
    assert V.build("a/b/c.tif", MetadataConfig(), now=dt.datetime(2026, 1, 2))["ROLL.NAME"] == "b", "no roll name: the folder's"
