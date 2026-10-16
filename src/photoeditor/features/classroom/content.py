"""The whole Classroom course, in the order a new person needs it.

The sections are written in several files (the basics, the program, the tools tab by tab, the finishing and export guides, and the worked examples and reference) and put together here in one order:

  Start here -> Photography basics -> How film works -> Scanning your film -> Getting around EFAS -> Convert -> Frame & Clean -> Tone -> Color -> Detail -> Finish and export
  -> Working a whole roll -> Recipes -> Reference
"""
from . import content_app, content_basics, content_convert, content_finish, content_reference, content_tone
from .logic import Course, Lesson, Section

SECTION_ORDER = ("start", "photo", "film", "scan", "tour", "convert", "frame", "tone", "color", "detail", "finish", "roll", "recipes", "reference")


def build() -> Course:
    sections = {s.id: s for s in (*content_basics.SECTIONS, *content_app.SECTIONS, *content_convert.SECTIONS, *content_tone.SECTIONS, *content_finish.SECTIONS, *content_reference.SECTIONS)}
    lessons: list[Lesson] = [*content_basics.LESSONS, *content_app.LESSONS, *content_convert.LESSONS, *content_tone.LESSONS, *content_finish.LESSONS, *content_reference.LESSONS]
    position = {section_id: n for n, section_id in enumerate(SECTION_ORDER)}
    ordered = sorted(lessons, key=lambda lesson: position.get(lesson.section, len(position)))   # stable: lessons keep the order they were written in, inside a section
    return Course([sections[i] for i in SECTION_ORDER if i in sections], ordered)


COURSE = build()
