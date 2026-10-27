"""Where each module comes from: a module's header says (darktable), (NegPy), (EFAS) or, for a module with a part of each, (NegPy & EFAS). No logic of the module is here, only its name.

(darktable) and (NegPy) mean the module is ported from, or follows closely, that program's module (see the table in docs/module-origins.md for what each one took); (EFAS) means it was
made for EFAS, even where its layout follows darktable's, as the whole interface does. The tag is shown in the header only: the module's own title (which picks its icon and its colour, and
which the search and the Classroom use) is unchanged.
"""

DARKTABLE, NEGPY, EFAS = "darktable", "NegPy", "EFAS"
BOTH = "NegPy & EFAS"     # a module with a part of each: Negative has NegPy's conversion and EFAS's own Original one; Sharpening has NegPy's methods and EFAS's own ways of using them

ORIGINS: dict[str, str] = {
    # ported from darktable
    "Retouch": DARKTABLE, "Masks": DARKTABLE, "Watermark": DARKTABLE, "Tagging": DARKTABLE, "Tags": DARKTABLE, "Diffuse or Sharpen": DARKTABLE, "Tone Equalizer": DARKTABLE, "Color Balance RGB": DARKTABLE,
    # ported from NegPy
    "Negative": BOTH, "Sharpening": BOTH, "Chroma Denoise": NEGPY, "Dust & Scratches": NEGPY, "Local Contrast": NEGPY, "Flat Field": NEGPY, "Print Response": NEGPY, "Color Toning": NEGPY,
    # made for EFAS
    "Exposure": EFAS, "Tone Curve": EFAS, "Color": EFAS, "White Balance": EFAS, "Contrast": EFAS, "Shadows & Highlights": EFAS, "Color Mixer": EFAS, "Halation": EFAS,
    "Grain Sharpening": EFAS, "Canister Watermark": EFAS, "Edge Bleed": EFAS, "Edge Color": EFAS, "Lab Look": EFAS, "AI Dust Detection": EFAS, "Error marking": EFAS, "Crop & Rotate": EFAS, "Finishing": EFAS,
}

_WORDS = {DARKTABLE: "Ported from darktable", NEGPY: "Ported from NegPy", EFAS: "Made for EFAS"}
_BOTH_WORDS = {
    "Negative": "The NegPy Conversion and NegPy 0.56 (old) are ported from NegPy; the Original conversion was made for EFAS",
    "Sharpening": "The four sharpening methods are ported from NegPy; masks, copies and the 16-bit path were made for EFAS",
}


def origin_of(title: str) -> str:
    """"darktable", "NegPy" or "EFAS" for a module's title; "" for a title that is not a module (a list or a section)."""
    return ORIGINS.get(title, "")


def display_title(title: str) -> str:
    """The title with its origin: "Retouch (darktable)"."""
    origin = ORIGINS.get(title, "")
    return f"{title} ({origin})" if origin else title


def with_origin(shown: str, title: str) -> str:
    """A name shown instead of the module's title (a copy's "Exposure 2 - skin") with the origin of the module it is a copy of."""
    origin = ORIGINS.get(title, "")
    return f"{shown} ({origin})" if origin else shown


def tooltip(title: str) -> str:
    origin = ORIGINS.get(title, "")
    words = _BOTH_WORDS[title] if origin == BOTH else _WORDS.get(origin, "")
    return words + (": see docs/module-origins.md for what it took" if origin in (DARKTABLE, NEGPY, BOTH) else "")
