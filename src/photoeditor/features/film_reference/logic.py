"""Film Colour Reference - what lomography.com's film pages hold, read into plain data. No Qt and no network (desktop/film_reference_client.py fetches).

Lomography keeps a catalogue of film stocks (www.lomography.com/films, the whole list on one page) and, for each, the community's photos shot on it
(/films/<id>-<name>/photos, 50 to a page, in four orders). That is what a colour reference needs: pictures of a stock as it really comes out. Only these
pages are used, never /search, /browse or /api (lomography.com's robots.txt asks automated tools to stay out of those), so a film is found by searching the
catalogue here, on this computer, instead of asking the site to search."""
import difflib
import html
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

BASE = "https://www.lomography.com"
HOSTS = ("lomography.com", "www.lomography.com", "cdn.assets.lomography.com")
USER_AGENT = "EFAS-Negative-Inversion-Software (film colour reference; github.com/EthanChas/EFAS-Negative-Inversion-Software)"
# What lomography.com/robots.txt says not to fetch automatically (a leading "/" path prefix each).
ROBOTS_DISALLOWED = ("/api", "/backend", "/browse", "/clickme", "/colors", "/login", "/my", "/openme", "/search", "/photos/random", "/homes/random", "/homes/search")
ORDERS = (("popular", "Most popular"), ("selected", "Selected"), ("trending", "Trending"), ("recent", "Most recent"))
CATALOGUE_DAYS = 14


@dataclass(frozen=True)
class Film:
    path: str  # "/films/871910984-kodak-portra-400"
    name: str  # "Kodak Portra 400"
    popularity: int = 0  # Lomography's own 0-100ish measure of how many photos there are

    @property
    def url(self) -> str:
        return BASE + self.path


@dataclass(frozen=True)
class Photo:
    photo_id: str
    page_path: str  # the photo's own page on the site
    thumb_url: str
    width: int
    height: int


@dataclass(frozen=True)
class PhotoDetail:
    image_url: str  # the large picture
    author: str
    title: str
    description: str
    page_url: str


def path_allowed(path: str) -> bool:
    """False for the paths robots.txt disallows (and anything that is not a film page)."""
    p = urlsplit(path).path
    if not (p == "/films" or p.startswith("/films/")):
        return False
    return not any(p == d or p.startswith(d + "/") for d in ROBOTS_DISALLOWED)


def host_allowed(url: str, extra: tuple[str, ...] = ()) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("https", "http") and (parts.hostname or "") in (*HOSTS, *extra) and (parts.scheme == "https" or bool(extra))


# ------------------------------------------------------------------ the catalogue and searching it
_FILM_LINK = re.compile(r'<a\s+href="(/films/\d+-[^"#?/]+)"([^>]*)>\s*([^<]+?)\s*</a>', re.I)


def parse_catalogue(page: str) -> list[Film]:
    """Every film on lomography.com/films (name, page, how popular), without repeats."""
    seen: dict[str, Film] = {}
    for path, attrs, name in _FILM_LINK.findall(page):
        m = re.search(r'data-popularity="(\d+)"', attrs)
        film = Film(path, html.unescape(name).strip(), int(m.group(1)) if m else 0)
        if film.name and (path not in seen or film.popularity > seen[path].popularity):
            seen[path] = film
    return sorted(seen.values(), key=lambda f: f.name.lower())


def catalogue_to_json(films: list[Film], fetched_at: float) -> str:
    return json.dumps({"fetched_at": fetched_at, "films": [[f.path, f.name, f.popularity] for f in films]})


def catalogue_from_json(text: str | None) -> tuple[list[Film], float]:
    """(films, when fetched), or ([], 0) when the text is not a usable saved catalogue."""
    try:
        data = json.loads(text) if text else {}
        films = [Film(str(p), str(n), int(c)) for p, n, c in data["films"] if str(p).startswith("/films/")]
        return films, float(data["fetched_at"])
    except (TypeError, ValueError, KeyError):
        return [], 0.0


def fresh(fetched_at: float, now: float) -> bool:
    return fetched_at > 0 and 0 <= now - fetched_at < CATALOGUE_DAYS * 86400


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def search_films(films: list[Film], query: str, limit: int = 40) -> list[Film]:
    """Films whose name has every word you typed (a word may be the start of one: "port 400" finds Kodak Portra 400); the best match and the most
    photographed first. Nothing found: the closest spellings."""
    q = _norm(query)
    if not q:
        return sorted(films, key=lambda f: -f.popularity)[:limit]
    words = q.split()
    scored = []
    for f in films:
        name = _norm(f.name)
        tokens = name.split()
        if not all(any(t.startswith(w) for t in tokens) or (len(w) > 2 and w in name) for w in words):
            continue
        rank = 0 if name == q else 1 if name.startswith(q) else 2 if q in name else 3
        scored.append((rank, -f.popularity, f.name.lower(), f))
    if scored:
        return [f for *_k, f in sorted(scored, key=lambda s: s[:3])][:limit]
    close = []  # a misspelling: every word you typed is close to some word in the name
    for f in films:
        tokens = _norm(f.name).split()
        ratios = [max((difflib.SequenceMatcher(None, w, t).ratio() for t in tokens), default=0) for w in words]
        if ratios and min(ratios) >= 0.75:
            close.append((-sum(ratios), -f.popularity, f))
    return [f for *_k, f in sorted(close, key=lambda c: c[:2])][:8]


# ------------------------------------------------------------------ a film's photos
def photos_url(film: Film, order: str = "popular", page: int = 1) -> str:
    order = order if order in dict(ORDERS) else "popular"
    return f"{BASE}{film.path}/photos?order={order}" + (f"&page={page}" if page > 1 else "")


_PHOTO = re.compile(r'<a\s+href="([^"]*/photos/(\d+)[^"]*)">\s*<img([^>]*)>', re.I)


def parse_photos(page: str) -> tuple[list[Photo], bool]:
    """(the photos on one page of a film's gallery, whether there is a next page)."""
    photos, seen = [], set()
    for href, photo_id, attrs in _PHOTO.findall(page):
        src = re.search(r'\bsrc="(https?://[^"]+)"', attrs)  # (the fetcher only follows addresses on lomography.com's own hosts)
        w, h = re.search(r'\bwidth="(\d+)"', attrs), re.search(r'\bheight="(\d+)"', attrs)
        if photo_id in seen or not src or not w or not h:
            continue
        seen.add(photo_id)
        photos.append(Photo(photo_id, html.unescape(href), html.unescape(src.group(1)), int(w.group(1)), int(h.group(1))))
    return photos, bool(re.search(r'rel="next"', page))


def _meta(page: str, prop: str) -> str:
    m = re.search(rf'<meta\s+property="{re.escape(prop)}"\s+content="([^"]*)"', page, re.I)
    return html.unescape(m.group(1)) if m else ""


def parse_photo_detail(page: str) -> PhotoDetail | None:
    """The large picture, who took it and what they said about it, from a photo's own page."""
    image = _meta(page, "og:image")
    if not image.startswith(("https://", "http://")):  # (the fetcher only follows addresses on lomography.com's own hosts)
        return None
    author = ""
    m = re.search(r'"author":\{"@type":"Person","name":"([^"]+)"', page)
    if m:
        author = html.unescape(m.group(1))
    elif _meta(page, "og:title").startswith("Photo by "):
        author = _meta(page, "og:title")[len("Photo by "):]
    return PhotoDetail(image, author, _meta(page, "og:title"), _meta(page, "og:description"), _meta(page, "og:url"))


def credit(author: str) -> str:
    return f"Photo by {author} on Lomography" if author else "Photo from Lomography"


def tile_size(photo: Photo, height: int = 190) -> tuple[int, int]:
    """The size a photo is shown at in the gallery: a fixed height, its own width, within limits."""
    w = round(photo.width * height / photo.height) if photo.height else height
    return min(max(w, height // 2), height * 2), height
