"""Find: reaching any module, slider, button or menu action by name or by a common word for it ("brightness" finds Exposure). The matching, no Qt."""

from dataclasses import dataclass, field

# What people call things, by the name EFAS gives them. Looked up by the entry's own title, so a new control with a known name is found by its synonyms too.
SYNONYMS = {
    "exposure": "brightness lighter darker light ev stops",
    "contrast": "punch grade iso-r flat harsh",
    "tone curve": "curves levels brightness contrast shadows highlights",
    "color": "colour saturation temperature tint white balance hue vibrance",
    "white balance": "temperature tint warmth cast kelvin",
    "saturation": "colour color intensity vibrance muted vivid",
    "temperature": "warmth warm cool white balance kelvin blue orange",
    "tint": "magenta green cast white balance",
    "shadows & highlights": "lift recover dark bright detail",
    "shadows": "lift dark blacks fill",
    "highlights": "recover bright whites blown",
    "sharpening": "sharpness sharpen detail crisp unsharp",
    "chroma denoise": "noise grain colour speckle",
    "local contrast": "clarity texture punch clahe",
    "crop & rotate": "crop straighten rotate flip distortion keystone perspective aspect ratio",
    "angle": "straighten level horizon tilt rotate",
    "distortion": "lens barrel pincushion bend",
    "keystone": "perspective converging verticals tilt camera",
    "vertical": "keystone perspective converging lines",
    "horizontal": "keystone perspective converging lines",
    "dust & scratches": "spots specks hairs clean retouch heal clone remove",
    "ai dust detection": "spots specks clean automatic retouch",
    "flat field": "vignette vignetting falloff uneven light backlight shading",
    "negative": "invert inversion film base orange mask metering convert",
    "film base": "orange mask rebate border dmin",
    "finishing": "vignette border frame carrier",
    "watermark": "logo text signature stamp",
    "export": "save output jpeg tiff png size resize format quality sharpen bit depth",
    "presets": "looks styles apply saved",
    "snapshots": "versions save state compare",
    "versions": "virtual copies copy alternate",
    "history": "undo steps log",
    "library": "folders roots roll browse",
    "tags": "keywords labels",
    "density": "optical density dmin dmax measure",
    "sensitometry (h&d)": "characteristic curve film profile",
    "search": "filter find photos query",
    "smart collections": "saved searches filters",
    "rating & status": "stars flag keeper rejected edited",
    "date": "when taken range",
    "check roll consistency": "scan differences light colour drift",
    "merge scans": "bracket hdr combine exposures",
    "find duplicates": "copies identical similar",
    "crop roll": "auto crop every photo bulk",
    "reset crops": "remove crops bulk",
}


@dataclass
class Entry:
    kind: str
    title: str
    where: str = ""
    keywords: str = ""
    target: object = None
    extra: dict = field(default_factory=dict)

    def haystack(self) -> str:
        return f"{self.title} {self.keywords} {SYNONYMS.get(self.title.casefold(), '')}".casefold()


KIND_BONUS = {"control": 6, "module": 4, "action": 2}


def _words(text: str) -> list[str]:
    out, word = [], []
    for ch in text.casefold():
        if ch.isalnum():
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def score(entry: Entry, tokens: list[str]) -> int:
    """How well an entry matches every typed word (0 = it does not): the title beats a synonym, a word start beats the middle of a word."""
    title = entry.title.casefold()
    title_words = _words(title)
    hay = entry.haystack()
    hay_words = _words(hay)
    total = 0
    for t in tokens:
        if title == t:
            total += 120
        elif title.startswith(t):
            total += 100
        elif any(w.startswith(t) for w in title_words):
            total += 80
        elif t in title:
            total += 55
        elif any(w.startswith(t) for w in hay_words):
            total += 40
        elif t in hay:
            total += 20
        elif entry.where and t in entry.where.casefold():
            total += 8
        else:
            return 0
    return total + KIND_BONUS.get(entry.kind, 0)


def search(entries: list[Entry], query: str, limit: int = 14) -> list[Entry]:
    """The entries that match every word of `query`, best first. An empty query matches nothing."""
    tokens = _words(query)
    if not tokens:
        return []
    ranked = []
    for i, e in enumerate(entries):
        s = score(e, tokens)
        if s:
            ranked.append((-s, i, e))
    ranked.sort(key=lambda r: (r[0], r[1]))
    seen, out = set(), []
    for _s, _i, e in ranked:
        key = (e.kind, e.title.casefold(), e.where.casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
        if len(out) >= limit:
            break
    return out
