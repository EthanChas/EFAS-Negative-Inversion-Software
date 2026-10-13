"""Reaching lomography.com for the Film Colour Reference: polite, narrow and visible.

Only film pages are fetched (never /search, /browse or /api, which robots.txt asks automated tools to avoid), only from lomography.com and its picture server,
with a User-Agent that says what this is, a few at a time, and nothing is kept but the film list (names and page addresses). The photos are shown, not saved.
Nothing here runs until the Film Colour Reference window is opened, and only after you have agreed to it once (Settings > General)."""
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from PyQt6.QtCore import QObject, pyqtSignal

from ..features.datadir import FILM_REFERENCE_FILE, app_data_dir
from ..features.film_reference import logic as L

PAGE_LIMIT = 3 * 1024 * 1024
IMAGE_LIMIT = 12 * 1024 * 1024
CONNECTIONS = 4


class FilmReferenceError(Exception):
    """Something the window can tell you in a sentence (offline, a page that is not what was expected)."""


def base_url() -> str:
    return os.environ.get("EFAS_FILM_REFERENCE_URL", L.BASE).rstrip("/")


def _extra_hosts() -> tuple[str, ...]:
    """Only a test pointing the feature at a local server adds a host."""
    override = os.environ.get("EFAS_FILM_REFERENCE_URL")
    return (urlsplit(override).hostname or "",) if override else ()


def localise(url: str) -> str:
    """The address as it should be fetched (the same, but for a test's local server)."""
    return base_url() + url[len(L.BASE):] if url.startswith(L.BASE) else url


def fetch(url: str, image: bool = False, timeout: float = 20.0) -> bytes:
    """One request. Refuses a host that is not lomography.com's, a page robots.txt disallows, anything too large, and a redirect off the site."""
    url = localise(url)
    if not L.host_allowed(url, _extra_hosts()):
        raise FilmReferenceError("That address is not on lomography.com.")
    if not image and not L.path_allowed(urlsplit(url).path):
        raise FilmReferenceError("That page is one lomography.com asks programs not to read.")
    request = urllib.request.Request(url, headers={"User-Agent": L.USER_AGENT, "Accept": "image/*" if image else "text/html"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if not L.host_allowed(response.geturl(), _extra_hosts()):
                raise FilmReferenceError("lomography.com sent the request somewhere else.")
            limit = IMAGE_LIMIT if image else PAGE_LIMIT
            data = response.read(limit + 1)
    except FilmReferenceError:
        raise
    except Exception as exc:
        raise FilmReferenceError(f"Could not reach lomography.com ({exc}).") from exc
    if len(data) > limit:
        raise FilmReferenceError("That was larger than expected, so it was not used.")
    return data


def fetch_text(url: str) -> str:
    return fetch(url).decode("utf-8", "replace")


def _cache_path() -> str:
    return os.path.join(app_data_dir(), FILM_REFERENCE_FILE)


def load_catalogue(force: bool = False, now: float | None = None) -> tuple[list[L.Film], bool]:
    """(the films, whether they came from the saved copy). The saved list is used while it is under two weeks old; an out-of-date one still serves when
    lomography.com cannot be reached."""
    now = time.time() if now is None else now
    saved: list[L.Film] = []
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            saved, fetched_at = L.catalogue_from_json(f.read())
    except OSError:
        fetched_at = 0.0
    if saved and not force and L.fresh(fetched_at, now):
        return saved, True
    try:
        films = L.parse_catalogue(fetch_text(L.BASE + "/films"))
        if not films:
            raise FilmReferenceError("The film list was not where it was expected on lomography.com.")
    except FilmReferenceError:
        if saved:
            return saved, True
        raise
    try:
        os.makedirs(os.path.dirname(_cache_path()), exist_ok=True)
        with open(_cache_path(), "w", encoding="utf-8") as f:
            f.write(L.catalogue_to_json(films, now))
    except OSError:
        pass
    return films, False


class Fetcher(QObject):
    """Requests on a few worker threads; each answer comes back on the window's thread as done(tag, bytes or None, error text)."""

    done = pyqtSignal(object, object, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=CONNECTIONS, thread_name_prefix="film-reference")

    def get(self, tag, url: str, image: bool = False) -> None:
        def work() -> None:
            try:
                self.done.emit(tag, fetch(url, image=image), "")
            except FilmReferenceError as exc:
                self.done.emit(tag, None, str(exc))
            except Exception as exc:  # never let a worker die silently
                self.done.emit(tag, None, str(exc))

        self._pool.submit(work)

    def catalogue(self, tag, force: bool = False) -> None:
        def work() -> None:
            try:
                self.done.emit(tag, load_catalogue(force), "")
            except Exception as exc:
                self.done.emit(tag, None, str(exc))

        self._pool.submit(work)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
