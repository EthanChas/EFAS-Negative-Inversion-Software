"""The Classroom's lessons: what a lesson is, how its text is written, how it is searched and put on the page - no Qt.

A lesson is a short piece of plain writing in a small mark-up, so that it is easy to read in the source and to check:

* paragraphs are separated by a blank line;
* `## Heading` is a heading; `- item` lines are a bulleted list; `1. item` lines are a numbered list;
* `TIP:`, `TRY:`, `NOTE:` and `CAREFUL:` at the start of a paragraph make a coloured box;
* inline: `**bold**`, `*italic*`, `code` between backticks, and `[[lesson-id]]` or `[[lesson-id|words to show]]` for a link to another lesson;
* a line that is only `@shortcuts` is replaced by the table of keyboard shortcuts as they are bound now (the window supplies it).

Sections are in the order a new person needs them: the basics of photography first, then film, then scanning, then the editor tab by tab in the order a picture is worked on."""
import html
import re
from dataclasses import dataclass, field

from ..find.logic import SYNONYMS

LEVELS = ("Beginner", "Next step", "Advanced")


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    blurb: str


@dataclass(frozen=True)
class Lesson:
    id: str
    section: str
    title: str
    summary: str                      # one sentence: what you will be able to do after it
    text: str                         # the lesson, in the mark-up above
    keywords: tuple[str, ...] = ()    # other words people search for it by
    module: str = ""                  # the title of the module it is about: the Show me button goes to it
    see: tuple[str, ...] = ()         # ids of lessons to read next or alongside
    level: str = "Beginner"


@dataclass(frozen=True)
class Block:
    kind: str                         # "p", "h", "ul", "ol", "tip", "try", "note", "careful", "shortcuts"
    items: tuple[str, ...]            # one paragraph or heading: one item; a list: its items


@dataclass(frozen=True)
class Hit:
    lesson: Lesson
    score: int
    snippet: str


CALLOUTS = {"TIP:": "tip", "TRY:": "try", "NOTE:": "note", "CAREFUL:": "careful"}
CALLOUT_LABELS = {"tip": "Tip", "try": "Try it", "note": "Note", "careful": "Careful"}
_BULLET = re.compile(r"^- +")
_NUMBER = re.compile(r"^\d+\. +")


def blocks(text: str) -> list[Block]:
    """The blocks a lesson's text is made of."""
    out: list[Block] = []
    for raw in re.split(r"\n\s*\n", text.strip()):
        lines = [ln.rstrip() for ln in raw.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        if lines == ["@shortcuts"]:
            out.append(Block("shortcuts", ()))
        elif lines[0].startswith("## "):
            out.append(Block("h", (lines[0][3:].strip(),)))
            if len(lines) > 1:
                out.extend(blocks("\n".join(lines[1:])))
        elif all(_BULLET.match(ln) for ln in lines):
            out.append(Block("ul", tuple(_BULLET.sub("", ln) for ln in lines)))
        elif all(_NUMBER.match(ln) for ln in lines):
            out.append(Block("ol", tuple(_NUMBER.sub("", ln) for ln in lines)))
        else:
            paragraph = " ".join(lines)
            for marker, kind in CALLOUTS.items():
                if paragraph.startswith(marker):
                    out.append(Block(kind, (paragraph[len(marker):].strip(),)))
                    break
            else:
                out.append(Block("p", (paragraph,)))
    return out


def _strip(flat: str) -> str:
    flat = re.sub(r"\[\[([^\]|]+)\|?([^\]]*)\]\]", lambda m: m.group(2) or m.group(1), flat)
    return re.sub(r"[*`]", "", flat)


def plain(text: str) -> str:
    """A lesson's text without its mark-up, for searching."""
    return _strip(" ".join(" ".join(b.items) for b in blocks(text)))


def headings(text: str) -> list[str]:
    """The headings of a lesson, in order, without mark-up: the page's outline."""
    return [_strip(b.items[0]) for b in blocks(text) if b.kind == "h"]


def heading_anchor(n: int) -> str:
    """The name of the anchor in the page for the n-th heading (render_html puts one in front of each)."""
    return f"h{n}"


def words(query: str) -> list[str]:
    return [w for w in (query or "").lower().replace("&", " ").replace("/", " ").split() if w]


def _haystack(lesson: Lesson, sections: dict[str, Section]) -> tuple[str, str, str, str]:
    """(title, keywords, summary, body) in lower case; the module's common words (Find's synonyms: "brightness" is Exposure) count as keywords."""
    extra = SYNONYMS.get(lesson.module.lower(), "") if lesson.module else ""
    section = sections[lesson.section].title if lesson.section in sections else ""
    return lesson.title.lower(), " ".join([*lesson.keywords, lesson.module, extra, section]).lower(), lesson.summary.lower(), plain(lesson.text).lower()


def search(lessons: list[Lesson], sections: dict[str, Section], query: str) -> list[Hit]:
    """The lessons that have every word of the query somewhere, best first: a title that starts with the words, a title that has them, a keyword or the module's name, the summary, then
    the text. Lessons of equal score stay in the order of the Classroom."""
    ws = words(query)
    if not ws:
        return []
    hits = []
    for order, lesson in enumerate(lessons):
        title, keys, summary, body = _haystack(lesson, sections)
        everything = " ".join((title, keys, summary, body))
        if any(w not in everything for w in ws):
            continue
        if all(w in title for w in ws):
            score = 0 if title.startswith(ws[0]) else 1
        elif all(w in title + " " + keys for w in ws):
            score = 2
        elif all(w in title + " " + keys + " " + summary for w in ws):
            score = 3
        else:
            score = 4
        hits.append((score, order, Hit(lesson, score, snippet(lesson, ws))))
    return [h for _s, _o, h in sorted(hits, key=lambda t: (t[0], t[1]))]


def snippet(lesson: Lesson, ws: list[str], width: int = 150) -> str:
    """A line from the lesson around the first of the words, for the results list (the summary when the words are only in the title or keywords)."""
    body = plain(lesson.text)
    low = body.lower()
    for w in ws:
        at = low.find(w)
        if at >= 0:
            start = max(0, at - width // 3)
            text = body[start:start + width].strip()
            return ("..." if start else "") + text + ("..." if start + width < len(body) else "")
    return lesson.summary


def neighbours(lessons: list[Lesson], lesson_id: str) -> tuple[Lesson | None, Lesson | None]:
    """The lesson before and the lesson after, in the order of the Classroom."""
    ids = [lesson.id for lesson in lessons]
    if lesson_id not in ids:
        return None, None
    i = ids.index(lesson_id)
    return (lessons[i - 1] if i > 0 else None), (lessons[i + 1] if i + 1 < len(lessons) else None)


# ------------------------------------------------------------------ putting a lesson on the page
def inline(text: str, titles: dict[str, str]) -> str:
    """One run of text as HTML: escaped, with **bold**, *italic*, `code` and [[links]] made."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])", r"<i>\1</i>", out)

    def link(m: re.Match) -> str:
        target = m.group(1).strip()
        label = (m.group(2) or "").strip() or titles.get(target, target)
        return f'<a href="lesson:{html.escape(target, quote=True)}">{label}</a>'

    return re.sub(r"\[\[([^\]|]+)\|?([^\]]*)\]\]", link, out)


def style_sheet(palette: dict[str, str]) -> str:
    """The page's CSS from the theme's colours: text, muted, accent, and the callout colours."""
    return (
        f"body {{ color: {palette['text']}; font-size: 14px; }} "
        f"p {{ margin: 0 0 10px 0; line-height: 150%; }} "
        f"h2 {{ color: {palette['text']}; font-size: 17px; margin: 18px 0 6px 0; }} "
        f"ul, ol {{ margin: 0 0 10px 0; }} li {{ margin-bottom: 4px; line-height: 145%; }} "
        f"a {{ color: {palette['accent']}; }} "
        f"code {{ background-color: {palette['code']}; font-family: Consolas, monospace; }} "
        f"table {{ border-collapse: collapse; margin: 4px 0 12px 0; }} td {{ padding: 3px 14px 3px 0; }} th {{ text-align: left; color: {palette['muted']}; padding: 8px 14px 3px 0; }} "
        f".muted {{ color: {palette['muted']}; }}"
    )


def callout_html(kind: str, body: str, palette: dict[str, str]) -> str:
    """A Tip / Try / Note / Careful box: a coloured edge, then the words on a slightly different ground (the table attributes are what Qt's rich text understands)."""
    colour = palette.get(kind, palette["accent"])
    return (f'<table width="100%" cellspacing="0" cellpadding="0" bgcolor="{palette["box"]}"><tr><td width="4" bgcolor="{colour}"></td>'
            f'<td bgcolor="{palette["box"]}" style="padding: 9px 14px 9px 12px;"><b style="color: {colour};">{CALLOUT_LABELS[kind]}</b><br>{body}</td></tr></table>'
            f'<p style="margin: 0; font-size: 6px;">&nbsp;</p>')


def render_html(lesson: Lesson, titles: dict[str, str], palette: dict[str, str], extras: dict[str, str] | None = None) -> str:
    """The body of a lesson as HTML. `extras` supplies the pieces the window makes ("shortcuts")."""
    parts = []
    heading = 0
    for block in blocks(lesson.text):
        if block.kind == "h":
            parts.append(f'<a name="{heading_anchor(heading)}"></a><h2>{inline(block.items[0], titles)}</h2>')
            heading += 1
        elif block.kind == "p":
            parts.append(f"<p>{inline(block.items[0], titles)}</p>")
        elif block.kind in ("ul", "ol"):
            tag = block.kind
            parts.append(f"<{tag}>" + "".join(f"<li>{inline(i, titles)}</li>" for i in block.items) + f"</{tag}>")
        elif block.kind == "shortcuts":
            parts.append((extras or {}).get("shortcuts", ""))
        else:
            parts.append(callout_html(block.kind, inline(block.items[0], titles), palette))
    return "".join(parts)


@dataclass
class Course:
    """The sections and lessons together, in order, with a way to find a lesson by its id."""
    sections: list[Section]
    lessons: list[Lesson]
    _by_id: dict[str, Lesson] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {lesson.id: lesson for lesson in self.lessons}

    def get(self, lesson_id: str) -> Lesson | None:
        return self._by_id.get(lesson_id)

    def section_map(self) -> dict[str, Section]:
        return {s.id: s for s in self.sections}

    def titles(self) -> dict[str, str]:
        return {lesson.id: lesson.title for lesson in self.lessons}

    def in_section(self, section_id: str) -> list[Lesson]:
        return [lesson for lesson in self.lessons if lesson.section == section_id]

    def problems(self) -> list[str]:
        """What is wrong with the course as written (an empty list when nothing): the tests read this."""
        found = []
        ids = [lesson.id for lesson in self.lessons]
        sections = self.section_map()
        for lesson_id in {i for i in ids if ids.count(i) > 1}:
            found.append(f"two lessons are called {lesson_id}")
        order = {s.id: n for n, s in enumerate(self.sections)}
        last = -1
        for lesson in self.lessons:
            if lesson.section not in sections:
                found.append(f"{lesson.id}: no section {lesson.section}")
                continue
            if order[lesson.section] < last:
                found.append(f"{lesson.id} is out of order: its section {lesson.section} comes earlier")
            last = max(last, order[lesson.section])
            if lesson.level not in LEVELS:
                found.append(f"{lesson.id}: level {lesson.level}")
            for target in lesson.see:
                if target not in ids:
                    found.append(f"{lesson.id}: see {target} does not exist")
            for target in re.findall(r"\[\[([^\]|]+)", lesson.text):
                if target.strip() not in ids:
                    found.append(f"{lesson.id}: link to {target.strip()} does not exist")
            if not lesson.summary.strip() or not lesson.text.strip():
                found.append(f"{lesson.id}: empty")
        for section in self.sections:
            if not self.in_section(section.id):
                found.append(f"section {section.id} has no lessons")
        return found
