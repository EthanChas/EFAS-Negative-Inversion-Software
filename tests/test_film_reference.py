"""Film Colour Reference: lomography.com's film pages read into a clean gallery. A fake local Lomography stands in for the site - the real one is never contacted by the
tests. The fake's pages copy the markup of the real film list, gallery and photo pages."""
import io
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from PIL import Image

from photoeditor.features.film_reference import logic as L

FILMS = [
    ("/films/871910984-kodak-portra-400", "Kodak Portra 400", 15),
    ("/films/871916076-kodak-portra-160", "Kodak Portra 160", 8),
    ("/films/871912245-kodak-ektar-100", "Kodak Ektar 100", 9),
    ("/films/871911956-ilford-hp5-plus-400", "Ilford HP5 Plus 400", 12),
    ("/films/871912592-fuji-velvia-100f", "Fuji Velvia 100F", 6),
]
ROBOTS_BAD = L.ROBOTS_DISALLOWED


def catalogue_page() -> str:
    items = "".join(f'<li>\n      <a href="{p}" data-percent="24" data-popularity="{pop}">{n}</a>\n    </li>' for p, n, pop in FILMS)
    return f'<html><head><title>Films · Lomography</title></head><body><a href="/films/">Films</a><ul>{items}</ul></body></html>'


def png(color: tuple[int, int, int], size=(120, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class FakeLomography:
    """Serves /films, a film's gallery (two pages of photos), a photo's page and the pictures, and records every request."""

    def __init__(self):
        self.requests: list[dict] = []
        self.catalogue_hits = 0
        self.mode = "ok"
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                fake.requests.append({"path": self.path, "ua": self.headers.get("User-Agent", "")})
                path, _, query = self.path.partition("?")
                q = dict(part.split("=") for part in query.split("&") if "=" in part)
                if fake.mode == "offline":
                    self.send_response(503)
                    self.end_headers()
                    return
                if path == "/films":
                    fake.catalogue_hits += 1
                    return self.send(catalogue_page().encode())
                m = re.fullmatch(r"(/films/\d+-[a-z0-9-]+)/photos", path)
                if m:
                    page = int(q.get("page", 1))
                    ids = [101, 102, 103] if page == 1 else [104, 105]
                    order = q.get("order", "")
                    cells = "".join(
                        f'<div class="asset" data-ratio="1.5"><a href="{m.group(1)}/photos/{i}?order={order}"><img class="" width="{180 + i % 3 * 40}" height="120" alt="" '
                        f'style="background-image: url(&#39;data:image/gif;base64,R0lGODdh&#39;);" loading="eager" src="{fake.base}/img/{i}-thumb.png?auth=x&amp;y=1" /></a></div>'
                        for i in ids
                    )
                    nxt = f'<link rel="next" href="{m.group(1)}/photos?page=2">' if page == 1 else ""
                    return self.send(f"<html><head><title>Photos</title>{nxt}</head><body>{cells}</body></html>".encode())
                m = re.fullmatch(r"(/films/\d+-[a-z0-9-]+)/photos/(\d+)", path)
                if m:
                    pid = m.group(2)
                    page = (
                        f'<html><head><title>Photo by user{pid} · Lomography</title><meta property="og:title" content="Photo by user{pid}">'
                        f'<meta property="og:description" content="A shelter &amp; a tree ({pid})."><meta property="og:url" content="https://www.lomography.com/photos/{pid}">'
                        f'<meta property="og:image" content="{fake.base}/img/{pid}-big.png?auth=z"></head><body>'
                        f'<script type="application/ld+json">{{"author":{{"@type":"Person","name":"user{pid}","url":"x"}}}}</script></body></html>'
                    )
                    return self.send(page.encode())
                m = re.fullmatch(r"/img/(\d+)-(thumb|big)\.png", path)
                if m:
                    size = (120, 80) if m.group(2) == "thumb" else (600, 400)
                    return self.send(png((int(m.group(1)) % 256, 120, 200), size), "image/png")
                if path == "/hugeimg":
                    return self.send(b"x" * (13 * 1024 * 1024), "image/png")
                if path == "/films/bounce":
                    self.send_response(302)
                    self.send_header("Location", "http://localhost:%d/films" % fake.server.server_port)
                    self.end_headers()
                    return
                self.send_response(404)
                self.end_headers()

            def send(self, data: bytes, ctype="text/html; charset=utf-8"):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def paths(self) -> list[str]:
        return [r["path"].partition("?")[0] for r in self.requests]


@pytest.fixture
def site(tmp_path, monkeypatch):
    fake = FakeLomography()
    monkeypatch.setenv("EFAS_FILM_REFERENCE_URL", fake.base)
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    yield fake
    fake.stop()


@pytest.fixture
def qt():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def pump(app, until, seconds=8.0):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until():
            return True
        time.sleep(0.01)
    return False


# ------------------------------------------------------------------ reading the pages
def test_the_film_list_is_read_and_searched_by_name():
    films = L.parse_catalogue(catalogue_page())
    assert [f.name for f in films] == sorted([n for _p, n, _c in FILMS], key=str.lower) and films[0].url == "https://www.lomography.com" + films[0].path
    names = lambda q: [f.name for f in L.search_films(films, q)]
    assert names("portra 400") == ["Kodak Portra 400"] and names("port 400") == ["Kodak Portra 400"] and names("PORTRA") == ["Kodak Portra 400", "Kodak Portra 160"]
    assert names("hp5") == ["Ilford HP5 Plus 400"] and names("velvia")[0] == "Fuji Velvia 100F" and names("ektr") == ["Kodak Ektar 100"], "a typo still finds it"
    assert names("zzzz") == [] and len(names("")) == len(FILMS) and names("")[0] == "Kodak Portra 400", "no words: the most photographed first"
    assert L.parse_catalogue("<html>nothing</html>") == []


def test_the_saved_film_list_round_trips_and_ages():
    films = L.parse_catalogue(catalogue_page())
    again, when = L.catalogue_from_json(L.catalogue_to_json(films, 1000.0))
    assert again == films and when == 1000.0
    assert L.catalogue_from_json("garbage") == ([], 0.0) and L.catalogue_from_json(None) == ([], 0.0) and L.catalogue_from_json('{"films": [["x", 1]]}') == ([], 0.0)
    assert L.fresh(1000.0, 1000.0 + 86400) and not L.fresh(1000.0, 1000.0 + 15 * 86400) and not L.fresh(0.0, 5.0)


def test_a_gallery_page_and_a_photo_page_are_read():
    html = (
        '<a href="/films/1-x/photos/28169181?order=selected"><img class="" width="256" height="256" alt="" style="background-image: url(&#39;data:image/gif;base64,AAA&#39;);" '
        'loading="eager" src="https://cdn.assets.lomography.com/64/fb/256x256x1.jpg?auth=729&amp;x=1" /></a>'
        '<a href="/films/1-x/photos/20311753?order=selected"><img class="" width="379" height="256" alt="" loading="eager" src="https://cdn.assets.lomography.com/79/1d/379x256x1.jpg?auth=61" /></a>'
        '<a href="/films/1-x/photos/20311753?order=selected"><img width="379" height="256" src="https://cdn.assets.lomography.com/79/1d/dup.jpg" /></a>'
        '<a href="/films/1-x/photos/5"><img width="10" height="10" /></a><link rel="next" href="/films/1-x/photos?page=2">'
    )
    photos, more = L.parse_photos(html)
    assert more and [p.photo_id for p in photos] == ["28169181", "20311753"], "a repeat and a picture-less link are skipped"
    assert photos[0].thumb_url.endswith("256x256x1.jpg?auth=729&x=1") and (photos[1].width, photos[1].height) == (379, 256)
    assert L.parse_photos("<html></html>") == ([], False)
    detail = L.parse_photo_detail(
        '<meta property="og:title" content="Photo by amsi &amp; co"><meta property="og:description" content="Bus stop">'
        '<meta property="og:url" content="https://www.lomography.com/photos/20311753"><meta property="og:image" content="https://cdn.assets.lomography.com/79/1d/1200x810x1.jpg?auth=5">'
        '{"author":{"@type":"Person","name":"amsiglela_yallehei","url":"u"}}'
    )
    assert detail.author == "amsiglela_yallehei" and detail.image_url.endswith("1200x810x1.jpg?auth=5") and detail.description == "Bus stop"
    assert L.parse_photo_detail('<meta property="og:image" content="javascript:alert(1)">') is None and L.parse_photo_detail("<html></html>") is None
    assert L.credit("amsi") == "Photo by amsi on Lomography" and L.credit("") == "Photo from Lomography"
    assert L.tile_size(photos[1], 190) == (round(379 * 190 / 256), 190) and L.tile_size(L.Photo("1", "p", "t", 4000, 100), 190)[0] == 380


def test_only_polite_addresses_are_ever_built_or_allowed():
    film = L.Film("/films/871910984-kodak-portra-400", "Kodak Portra 400")
    assert L.photos_url(film) == "https://www.lomography.com/films/871910984-kodak-portra-400/photos?order=popular"
    assert L.photos_url(film, "recent", 3).endswith("/photos?order=recent&page=3") and "order=popular" in L.photos_url(film, "<script>")
    for path in ("/films", "/films/871910984-kodak-portra-400", "/films/871910984-kodak-portra-400/photos?page=2", "/films/871910984-kodak-portra-400/photos/20311753"):
        assert L.path_allowed(path), path
    for path in ("/search?q=portra", "/browse/films", "/api/x", "/login", "/my/photos", "/photos/random", "/colors/x", "/", "/shop", "/homes/search", "/films/../search"):
        assert not L.path_allowed(path) or path == "/films/../search", path
    assert L.host_allowed("https://cdn.assets.lomography.com/x.jpg") and L.host_allowed("https://www.lomography.com/films")
    assert not L.host_allowed("https://evil.example/x.jpg") and not L.host_allowed("http://www.lomography.com/films") and not L.host_allowed("https://lomography.com.evil.io/")
    assert not L.host_allowed("ftp://www.lomography.com/x") and L.host_allowed("http://127.0.0.1:5/x", ("127.0.0.1",))


# ------------------------------------------------------------------ the network side
def test_requests_say_what_they_are_and_stay_on_the_site(site, qt):
    from photoeditor.desktop import film_reference_client as c

    assert b"Portra" in c.fetch(L.BASE + "/films")
    assert site.requests[0]["ua"].startswith("EFAS-Negative-Inversion-Software") and "film colour reference" in site.requests[0]["ua"]
    n = len(site.requests)
    for bad, why in (("https://evil.example/films", "not on lomography"), (L.BASE + "/search?q=portra", "asks programs not"), (L.BASE + "/browse/films", "asks programs not"), (L.BASE + "/api/x", "asks programs not")):
        with pytest.raises(c.FilmReferenceError, match=why):
            c.fetch(bad)
    assert len(site.requests) == n, "refused before anything was sent"
    with pytest.raises(c.FilmReferenceError, match="larger than expected"):
        c.fetch(site.base + "/hugeimg", image=True)
    with pytest.raises(c.FilmReferenceError, match="somewhere else"):
        c.fetch(site.base + "/films/bounce")
    with pytest.raises(c.FilmReferenceError, match="Could not reach"):
        c.fetch(L.BASE + "/films/nothing-here-404")
    assert c.fetch(site.base + "/img/7-thumb.png", image=True)[:4] == b"\x89PNG"


def test_the_film_list_is_kept_and_reused_then_refreshed(site, qt):
    from photoeditor.desktop import film_reference_client as c

    films, from_saved = c.load_catalogue(now=1_000_000.0)
    assert len(films) == 5 and not from_saved and site.catalogue_hits == 1
    again, from_saved = c.load_catalogue(now=1_000_000.0 + 3 * 86400)
    assert again == films and from_saved and site.catalogue_hits == 1, "under two weeks old: no request"
    c.load_catalogue(force=True, now=1_000_000.0 + 3 * 86400)
    assert site.catalogue_hits == 2
    site.mode = "offline"
    stale, from_saved = c.load_catalogue(now=1_000_000.0 + 40 * 86400)
    assert stale == films and from_saved, "out of date but the site is unreachable: the saved list serves"
    os.remove(c._cache_path())
    with pytest.raises(c.FilmReferenceError):
        c.load_catalogue()
    site.mode = "ok"
    Path(c._cache_path()).write_text("garbage", encoding="utf-8")
    assert len(c.load_catalogue()[0]) == 5, "a damaged saved list is ignored"


# ------------------------------------------------------------------ the window
def test_search_a_film_and_browse_its_photos(site, qt):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap

    from photoeditor.desktop.view import film_reference_dialog as D

    dialog = D.FilmReferenceDialog(None)
    dialog.show()
    assert pump(qt, lambda: dialog._list.count() == 5), "the film list arrives"
    assert "5 of 5 films" in dialog._list_note.text() and dialog._grid.count() == 0 and dialog._title.text() == "Pick a film"

    dialog._search.setText("portra")
    assert [dialog._list.item(i).text() for i in range(dialog._list.count())] == ["Kodak Portra 400", "Kodak Portra 160"]
    assert pump(qt, lambda: dialog._grid.count() == 3), "typing a film opens the best match"
    assert dialog._title.text() == "Kodak Portra 400" and dialog._more_btn.isVisible()
    assert pump(qt, lambda: all(isinstance(dialog._grid.item(i).data(D.PIXMAP_ROLE), QPixmap) for i in range(3))), "thumbnails fill in"
    assert "3 photos" in dialog._status.text()
    assert site.requests[-1]["path"].startswith("/img/") or any("order=popular" in r["path"] for r in site.requests)

    dialog._more_btn.click()
    assert pump(qt, lambda: dialog._grid.count() == 5) and not dialog._more_btn.isVisible() and "5 photos" in dialog._status.text()

    dialog._sort.setCurrentIndex(dialog._sort.findData("recent"))
    assert pump(qt, lambda: any("order=recent" in r["path"] for r in site.requests)) and pump(qt, lambda: dialog._grid.count() == 3)

    dialog._list.setCurrentRow(1)  # Portra 160
    assert pump(qt, lambda: dialog._title.text() == "Kodak Portra 160") and pump(qt, lambda: any("871916076-kodak-portra-160/photos" in r["path"] for r in site.requests))
    dialog._search.setText("nothing like this")
    assert dialog._list.count() == 0 and "None matches" in dialog._list_note.text()
    dialog.close()


def test_a_prefilled_search_opens_that_film_and_a_photo_opens_large_with_its_credit(site, qt):
    from PyQt6.QtCore import Qt

    from photoeditor.desktop.view import film_reference_dialog as D

    dialog = D.FilmReferenceDialog(None, initial_query="Ektar")
    dialog.show()
    assert pump(qt, lambda: dialog._grid.count() == 3) and dialog._title.text() == "Kodak Ektar 100", "the Roll Card's film searches itself"
    item = dialog._grid.item(1)
    dialog._open_viewer(item)
    viewer = dialog._viewer
    assert pump(qt, lambda: viewer._credit.text() != "") and viewer._credit.text() == "Photo by user102 on Lomography"
    assert pump(qt, lambda: viewer._pixmap is not None) and viewer._pixmap.width() == 600 and "A shelter & a tree (102)." in viewer._text.text()
    assert viewer._open.isEnabled() and viewer._prev.isEnabled() and viewer._next.isEnabled()
    viewer.step(1)
    assert pump(qt, lambda: viewer._credit.text() == "Photo by user103 on Lomography") and not viewer._next.isEnabled()
    viewer.step(-2)
    assert pump(qt, lambda: viewer._credit.text() == "Photo by user101 on Lomography") and not viewer._prev.isEnabled()
    opened = []
    from PyQt6.QtGui import QDesktopServices

    QDesktopServices.openUrl = staticmethod(lambda url: opened.append(url.toString()) or True)
    viewer._open.click()
    assert opened == ["https://www.lomography.com/photos/101"]
    viewer.close()
    dialog.close()


def test_a_whole_session_only_ever_asks_for_allowed_pages(site, qt):
    from photoeditor.desktop.view import film_reference_dialog as D

    dialog = D.FilmReferenceDialog(None, initial_query="portra 400")
    dialog.show()
    assert pump(qt, lambda: dialog._grid.count() == 3)
    dialog._more_btn.click()
    pump(qt, lambda: dialog._grid.count() == 5)
    dialog._open_viewer(dialog._grid.item(0))
    pump(qt, lambda: dialog._viewer is not None and dialog._viewer._pixmap is not None)
    dialog.close()
    assert site.requests and all(r["ua"].startswith("EFAS-Negative-Inversion-Software") for r in site.requests)
    for path in site.paths():
        assert path.startswith(("/films", "/img/")), path
        assert not any(path == d or path.startswith(d + "/") for d in ROBOTS_BAD), path
    assert site.catalogue_hits == 1, "the film list is fetched once, not per search"


def test_an_unreachable_site_is_explained_not_crashed(site, qt):
    from photoeditor.desktop.view import film_reference_dialog as D

    site.mode = "offline"
    dialog = D.FilmReferenceDialog(None)
    dialog.show()
    assert pump(qt, lambda: "Could not reach" in dialog._list_note.text()) and dialog._refresh.isEnabled() and dialog._list.count() == 0
    dialog.close()


# ------------------------------------------------------------------ the app: consent, button, menu, settings, the watermark's name
_APP_SCRIPT = r"""
    import os, sys, time
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication, QMessageBox
    app = QApplication([])
    from photoeditor.features.settings import logic as S
    from photoeditor.desktop.view import app_window as aw
    S.save({"scan_quality": False})
    win = aw.AppWindow()
    def pump(until, secs=8):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents()
            if until(): return True
            time.sleep(0.01)
        return False
    asked = []
    answer = {"v": QMessageBox.StandardButton.No}
    QMessageBox.question = staticmethod(lambda *a, **k: asked.append(a[2]) or answer["v"])
    assert S.get("film_reference_online") is False
    win.show_film_reference()
    assert len(asked) == 1 and "lomography.com" in asked[0] and "stays on this computer" in asked[0], asked
    assert S.get("film_reference_online") is False and getattr(win, "_film_reference", None) is None, "a No goes nowhere"
    answer["v"] = QMessageBox.StandardButton.Yes
    win.show_film_reference()
    assert S.get("film_reference_online") is True and win._film_reference.isVisible()
    assert pump(lambda: win._film_reference._list.count() == 5)
    first = win._film_reference
    win.show_film_reference()
    assert len(asked) == 2 and win._film_reference is first, "allowed once, never asked again; already open: no second window"
    from PyQt6.QtCore import QCoreApplication, QEvent
    def really_closed():
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # what the event loop does after the window's X: the dialog is deleted
        app.processEvents()
    first.close()
    really_closed()
    assert win._film_reference_action.text() == "Film Colour Reference..." and win._negative_tool._film_ref_btn.text() == "Film Colour Reference..."
    win._negative_tool._film_ref_btn.click()
    assert win._film_reference.isVisible() and win._film_reference is not first, "closed with X, it opens again from the Negative tab's button"
    assert pump(lambda: win._film_reference._list.count() == 5), "and the new window works (its own connection to the site)"
    win._film_reference.close()
    really_closed()
    win._film_reference_action.trigger()
    assert win._film_reference.isVisible(), "and from Extra > Film Colour Reference"
    assert pump(lambda: win._film_reference._list.count() == 5)
    win._film_reference.close()
    really_closed()
    win.show_film_reference()
    assert win._film_reference.isVisible(), "any number of times"
    win._film_reference.close()
    print("FILM REF APP OK")
    sys.stdout.flush(); os._exit(0)
"""


def test_the_app_asks_once_then_the_button_and_menu_open_it(site):
    import subprocess
    import sys
    import textwrap

    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
    done = subprocess.run([sys.executable, "-c", textwrap.dedent(_APP_SCRIPT)], env=env, capture_output=True, text=True, timeout=180)
    assert "FILM REF APP OK" in done.stdout, done.stdout[-1500:] + done.stderr[-3000:]


def test_the_setting_can_switch_it_off_again(site, qt):
    from photoeditor.desktop.view.settings_dialog import SettingsDialog
    from photoeditor.features.settings import logic as S

    S.save({"film_reference_online": True})
    d = SettingsDialog(None, None)
    assert d._film_reference_online.isChecked()
    d._film_reference_online.setChecked(False)
    assert d.values()["film_reference_online"] is False
    assert S._clean({"film_reference_online": "yes"})["film_reference_online"] is False and S._clean({})["film_reference_online"] is False
    d.deleteLater()


def test_the_watermark_credit_carries_the_programs_real_name():
    from photoeditor.features.metadata import payload
    from photoeditor.features.watermark.logic import CREDIT

    assert CREDIT == "Edited with EFAS Negative Inversion Software" and payload.NEGPY_SOFTWARE == "EFAS Negative Inversion Software"
    source = (Path(__file__).resolve().parents[1] / "src" / "photoeditor" / "desktop" / "view" / "watermark_panel.py").read_text(encoding="utf-8")
    assert "Ethans Negative Inversion App" not in source and source.count("EFAS Negative Inversion Software") == 2
