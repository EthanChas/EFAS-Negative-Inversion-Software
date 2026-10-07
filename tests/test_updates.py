import hashlib
import http.server
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.updates import logic, processor  # noqa: E402


def _release_json(**over):
    data = {
        "tag_name": "v0.4.0", "draft": False, "prerelease": False, "body": "notes",
        "html_url": "https://github.com/EthanChas/EFAS-Negative-Inversion-Software/releases/tag/v0.4.0",
        "assets": [{
            "name": "EFAS-v0.4.0-windows.exe", "size": 10, "digest": "sha256:" + "AB" * 32,
            "browser_download_url": "https://github.com/EthanChas/EFAS-Negative-Inversion-Software/releases/download/v0.4.0/x.exe",
        }],
    }
    data.update(over)
    return data


def test_version_parsing_and_comparison():
    assert logic.parse_version("v0.4.1") == (0, 4, 1)
    assert logic.parse_version("0.10") == (0, 10)
    assert logic.parse_version("1.2.3-beta") == (1, 2, 3)
    assert logic.parse_version("nonsense") == ()
    assert logic.is_newer((0, 4, 0), (0, 3, 9))
    assert logic.is_newer((0, 10, 0), (0, 9, 0))
    assert not logic.is_newer((0, 3, 0), (0, 3, 0))
    assert not logic.is_newer((0, 3), (0, 3, 0))
    assert logic.is_newer((0, 3, 1), (0, 3))
    assert not logic.is_newer((), (0, 3, 0))


def test_pick_release():
    r = logic.pick_release(_release_json())
    assert r.version == (0, 4, 0) and r.asset_size == 10 and r.sha256 == "ab" * 32 and r.notes == "notes"
    assert logic.pick_release(_release_json(draft=True)) is None
    assert logic.pick_release(_release_json(prerelease=True)) is None
    assert logic.pick_release(_release_json(tag_name="latest")) is None
    assert logic.pick_release([]) is None
    none = logic.pick_release(_release_json(assets=[]))
    assert none.asset_url == "" and none.version == (0, 4, 0)


def test_only_github_https_downloads_are_trusted():
    assert logic.trusted_url("https://github.com/a/b/releases/download/v1/x.exe")
    assert logic.trusted_url("https://objects.githubusercontent.com/x")
    assert not logic.trusted_url("http://github.com/x")
    assert not logic.trusted_url("https://github.com.evil.example/x")
    assert not logic.trusted_url("https://evil.example/github.com")
    assert not logic.trusted_url("")
    bad = _release_json()
    bad["assets"][0]["browser_download_url"] = "https://evil.example/x.exe"
    assert logic.pick_release(bad).asset_url == ""


@pytest.fixture
def server(tmp_path):
    payload = b"0123456789"

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/x.exe", payload
    srv.shutdown()


def _local_release(url, payload, sha=None, size=None):
    return logic.Release("v0.4.0", (0, 4, 0), "", "", "x.exe", url, len(payload) if size is None else size,
                         hashlib.sha256(payload).hexdigest() if sha is None else sha)


def test_download_verifies_size_and_checksum(server, tmp_path, monkeypatch):
    url, payload = server
    monkeypatch.setattr(processor, "trusted_url", lambda u: True)
    seen = []
    dest = str(tmp_path / "new.exe")
    processor.download(_local_release(url, payload), dest, lambda d, t: seen.append((d, t)))
    assert Path(dest).read_bytes() == payload and seen[-1] == (10, 10) and not Path(dest + ".part").exists()

    bad = str(tmp_path / "bad.exe")
    with pytest.raises(processor.UpdateError, match="checksum"):
        processor.download(_local_release(url, payload, sha="0" * 64), bad)
    with pytest.raises(processor.UpdateError, match="incomplete"):
        processor.download(_local_release(url, payload, size=99), bad)
    assert not Path(bad).exists() and not Path(bad + ".part").exists()


def test_download_refuses_untrusted_url(tmp_path):
    release = logic.Release("v1", (1,), "", "", "x.exe", "http://127.0.0.1:1/x.exe", 1, "")
    with pytest.raises(processor.UpdateError, match="trust"):
        processor.download(release, str(tmp_path / "x"))


def test_download_can_be_cancelled(server, tmp_path, monkeypatch):
    url, payload = server
    monkeypatch.setattr(processor, "trusted_url", lambda u: True)
    dest = str(tmp_path / "c.exe")
    with pytest.raises(processor.UpdateError, match="Cancelled"):
        processor.download(_local_release(url, payload), dest, cancelled=lambda: True)
    assert not Path(dest).exists() and not Path(dest + ".part").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="the swap helper is a Windows batch file")
def test_swap_script_replaces_target_and_starts_it(tmp_path):
    target, new, marker = tmp_path / "app 100%.cmd", tmp_path / "new.cmd", tmp_path / "ran.txt"
    target.write_text("@echo old\r\n")
    new.write_text(f'@echo new> "{marker}"\r\n')
    script = tmp_path / "swap.cmd"
    script.write_text(processor._script(str(target), str(new)), encoding="mbcs")
    subprocess.run(["cmd.exe", "/c", str(script)], timeout=60, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 20
    while time.time() < deadline and not marker.exists():
        time.sleep(0.2)
    assert marker.exists(), "the replaced program was not started"
    assert "new" in target.read_text() and not new.exists()
    time.sleep(5)
    assert not Path(str(target) + ".old").exists() and not script.exists()
