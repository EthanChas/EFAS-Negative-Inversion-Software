"""The Classroom's course: its lessons are well-formed and in a logical order, the mark-up becomes the right blocks and HTML, and the search finds and ranks lessons."""
import pytest

from photoeditor.features.classroom import logic as L
from photoeditor.features.classroom.content import COURSE, SECTION_ORDER


# ------------------------------------------------------------------ the course as written
def test_the_course_has_no_broken_links_empty_lessons_or_out_of_order_sections():
    assert COURSE.problems() == []
    assert [s.id for s in COURSE.sections] == list(SECTION_ORDER)
    assert len(COURSE.lessons) >= 100


def test_the_sections_run_from_the_basics_to_the_tools_to_the_reference():
    first = {s: next(n for n, lesson in enumerate(COURSE.lessons) if lesson.section == s) for s in SECTION_ORDER}
    assert COURSE.lessons[0].id == "what-is-efas" and COURSE.lessons[0].section == "start"
    assert [first[s] for s in SECTION_ORDER] == sorted(first[s] for s in SECTION_ORDER), "each section starts after the one before it"
    order = {s: n for n, s in enumerate(SECTION_ORDER)}
    assert order["photo"] < order["film"] < order["scan"] < order["tour"] < order["convert"] < order["frame"] < order["tone"] < order["color"] < order["detail"] < order["finish"] < order["roll"]
    assert order["roll"] < order["recipes"] < order["reference"]


def test_every_lesson_has_real_content_and_a_one_line_summary():
    for lesson in COURSE.lessons:
        words = len(L.plain(lesson.text).split())
        assert words >= 55, f"{lesson.id} is only {words} words"
        assert 20 <= len(lesson.summary) <= 140 and lesson.summary.endswith("."), lesson.id
        assert lesson.title and lesson.title == lesson.title.strip()
        assert lesson.level in L.LEVELS


def test_the_tool_guides_are_in_depth_explanations_and_not_checklists():
    for section in ("convert", "frame", "tone", "color", "detail", "finish"):
        for lesson in COURSE.in_section(section):
            blocks = L.blocks(lesson.text)
            words = len(L.plain(lesson.text).split())
            needed = 280 if lesson.module else 200   # a guide to one tool says a lot; a tab overview can be shorter
            assert words >= needed, f"{lesson.id} is only {words} words"
            assert sum(1 for b in blocks if b.kind == "h") >= 1, f"{lesson.id} has no headings to find your way by"
    for lesson in COURSE.lessons:
        if lesson.section in ("start", "photo", "film", "scan", "reference"):
            continue   # the basics and the reference tables are naturally lists of kinds, formats and terms
        blocks = L.blocks(lesson.text)
        listed = sum(len(" ".join(b.items).split()) for b in blocks if b.kind in ("ul", "ol"))
        total = max(1, len(L.plain(lesson.text).split()))
        assert listed / total <= 0.35, f"{lesson.id} is mostly a list ({listed} of {total} words)"
        assert not any(b.kind == "ol" for b in blocks), f"{lesson.id} has numbered steps: the guides explain, they do not tick off"


def test_a_lesson_that_is_about_one_tool_names_it_and_the_others_do_not_pretend_to():
    assert COURSE.get("exposure-module").module == "Exposure"
    assert COURSE.get("flat-field-module").module == "Flat Field"
    assert COURSE.get("light-and-exposure").module == ""
    assert sum(1 for lesson in COURSE.lessons if lesson.module) >= 40


def test_the_course_covers_every_module_of_the_editor():
    modules = {lesson.module for lesson in COURSE.lessons if lesson.module}
    for title in ("Exposure", "Contrast", "Shadows & Highlights", "Tone Curve", "Print Response", "Crop & Rotate", "Dust & Scratches", "AI Dust Detection", "Error marking", "Negative",
                  "Flat Field", "Edge Bleed", "Finishing", "Watermark", "Tags", "Color", "Color Mixer", "Color Toning", "Lab Look", "Edge Color", "Chroma Denoise", "Local Contrast",
                  "Sharpening", "Grain Sharpening", "Masks", "Retouch", "Roll", "Presets", "Export", "History", "Snapshots", "Versions", "Library"):
        assert title in modules, title


# ------------------------------------------------------------------ the mark-up
def test_text_becomes_headings_paragraphs_lists_and_boxes():
    text = """
Intro paragraph that
runs over two lines.

## A heading
Straight after it.

- one
- two **bold**

1. first
2. second

TIP: use the thing.

TRY: do the thing.

NOTE: mind the thing.

CAREFUL: not that thing.

@shortcuts
"""
    got = [(b.kind, b.items) for b in L.blocks(text)]
    assert got == [
        ("p", ("Intro paragraph that runs over two lines.",)), ("h", ("A heading",)), ("p", ("Straight after it.",)), ("ul", ("one", "two **bold**")), ("ol", ("first", "second")),
        ("tip", ("use the thing.",)), ("try", ("do the thing.",)), ("note", ("mind the thing.",)), ("careful", ("not that thing.",)), ("shortcuts", ()),
    ]


def test_inline_marks_are_made_and_everything_else_is_escaped():
    out = L.inline("Use **Exposure** & `Ctrl+K` <now>, *softly*; see [[a]] and [[b|the other]].", {"a": "Lesson A"})
    assert "<b>Exposure</b>" in out and "<code>Ctrl+K</code>" in out and "<i>softly</i>" in out
    assert "&amp;" in out and "&lt;now&gt;" in out and "<now>" not in out
    assert '<a href="lesson:a">Lesson A</a>' in out and '<a href="lesson:b">the other</a>' in out
    assert "2 * 3 * 4" in L.inline("2 * 3 * 4", {}), "stars with spaces are not italic"


def test_plain_text_for_searching_has_no_mark_up():
    flat = L.plain("## Head\nSome **bold** text and `code`.\n\n- item with [[x|a link]]\n\nTIP: a tip")
    assert "**" not in flat and "`" not in flat and "[[" not in flat and "a link" in flat and "a tip" in flat and "Head" in flat


def test_a_lesson_becomes_html_with_boxes_and_the_shortcut_table_put_in():
    lesson = L.Lesson("x", "start", "X", "A summary of x.", "## H\nText [[y]].\n\n- a\n\nTIP: tip\n\n@shortcuts")
    palette = {"text": "#fff", "muted": "#999", "accent": "#08f", "code": "#111", "box": "#222", "tip": "#08f", "try": "#0f0", "note": "#aaa", "careful": "#fa0"}
    html = L.render_html(lesson, {"y": "Why"}, palette, {"shortcuts": "<table id='keys'></table>"})
    assert "<h2>H</h2>" in html and "<ul><li>a</li></ul>" in html and 'href="lesson:y">Why</a>' in html and "Tip" in html and "<table id='keys'>" in html
    assert "#08f" in L.style_sheet(palette) and "code" in L.style_sheet(palette)


def test_every_lesson_renders_to_html():
    palette = {"text": "#fff", "muted": "#999", "accent": "#08f", "code": "#111", "box": "#222", "tip": "#08f", "try": "#0f0", "note": "#aaa", "careful": "#fa0"}
    titles = COURSE.titles()
    for lesson in COURSE.lessons:
        html = L.render_html(lesson, titles, palette, {"shortcuts": "<table></table>"})
        assert "<p>" in html or "<li>" in html, lesson.id
        assert "[[" not in html and "**" not in html, f"{lesson.id} has mark-up left over"


# ------------------------------------------------------------------ search
def _search(query):
    return [h.lesson.id for h in L.search(COURSE.lessons, COURSE.section_map(), query)]


def test_every_word_has_to_be_in_a_lesson_and_nothing_matches_nothing():
    assert _search("") == [] and _search("   ") == []
    assert _search("zzzzqqqq") == []
    assert _search("dust") and _search("dust scratches") and set(_search("dust scratches")) <= set(_search("dust"))
    assert _search("dust banana") == []


def test_the_best_lesson_comes_first():
    assert _search("flat field")[0] == "flat-field-module"
    assert _search("sharpening")[0] == "sharpening-module"
    assert _search("histogram")[0] == "histogram-basics"
    assert _search("vignette")[0] in ("finishing-module", "edge-color-module", "flat-field-module") and "finishing-module" in _search("vignette")[:3]
    assert _search("tether")[0] in ("tether-live-view", "scanning-tethered", "hotstack-lesson") and {"tether-live-view", "scanning-tethered"} <= set(_search("tether")[:4])
    assert _search("hotstack")[0] == "hotstack-lesson"


def test_a_common_word_for_what_a_tool_does_finds_the_tool_like_find_does():
    assert "exposure-module" in _search("brightness")[:6]
    assert "sharpening-module" in _search("sharpen")
    assert "shadows-highlights-module" in _search("shadows")


def test_a_title_beats_a_keyword_and_a_keyword_beats_the_text():
    hits = L.search(COURSE.lessons, COURSE.section_map(), "grain")
    scores = [h.score for h in hits]
    assert scores == sorted(scores), "best first"
    assert hits[0].lesson.id in ("iso-and-noise", "film-speed-and-grain", "grain-sharpening-module", "grain-report") and hits[0].score <= 1, "a title that has the word comes before a lesson that only mentions it"
    assert any(h.score >= 3 for h in hits), "and the lessons that only mention it come later"


def test_a_result_shows_the_words_in_their_place():
    hit = L.search(COURSE.lessons, COURSE.section_map(), "halo")[0]
    assert "halo" in hit.snippet.lower() or hit.snippet == hit.lesson.summary
    snippet = L.snippet(COURSE.get("glossary"), ["rebate"], 100)
    assert "ebate" in snippet and len(snippet) <= 110


# ------------------------------------------------------------------ order and outline
def test_the_outline_lists_the_headings_and_the_page_has_an_anchor_for_each():
    lesson = L.Lesson("x", "start", "X", "A guide.", "Intro with **bold**.\n\n## First part\nText.\n\n## The [[y|Why]] part with `code`\nMore.")
    assert L.headings(lesson.text) == ["First part", "The Why part with code"]
    palette = {"text": "#fff", "muted": "#999", "accent": "#08f", "code": "#111", "box": "#222", "tip": "#08f", "try": "#0f0", "note": "#aaa", "careful": "#fa0"}
    html = L.render_html(lesson, {"y": "Why"}, palette)
    assert html.index(f'name="{L.heading_anchor(0)}"') < html.index("First part") < html.index(f'name="{L.heading_anchor(1)}"')
    assert L.headings("Just a paragraph.") == []
    deep = COURSE.get("color-mixer-module")
    assert len(L.headings(deep.text)) >= 4, "the in-depth guides have parts to jump between"


def test_previous_and_next_walk_the_course_in_order():
    ids = [lesson.id for lesson in COURSE.lessons]
    assert L.neighbours(COURSE.lessons, ids[0]) == (None, COURSE.lessons[1])
    assert L.neighbours(COURSE.lessons, ids[-1]) == (COURSE.lessons[-2], None)
    before, after = L.neighbours(COURSE.lessons, ids[5])
    assert before.id == ids[4] and after.id == ids[6]
    assert L.neighbours(COURSE.lessons, "nope") == (None, None)


def test_a_course_with_a_broken_link_or_a_section_out_of_order_says_so():
    sections = [L.Section("a", "A", ""), L.Section("b", "B", "")]
    lessons = [L.Lesson("x", "b", "X", "Summary of x here.", "text [[nowhere]]", see=("also-nowhere",)), L.Lesson("y", "a", "Y", "Summary of y here.", "text")]
    problems = L.Course(sections, lessons).problems()
    assert any("nowhere" in p for p in problems) and any("also-nowhere" in p for p in problems) and any("out of order" in p for p in problems)
    assert L.Course([L.Section("a", "A", "")], []).problems() == ["section a has no lessons"]
