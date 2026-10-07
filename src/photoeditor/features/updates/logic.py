"""Update checking rules: reading a GitHub release, comparing versions, deciding which download to trust - no Qt or network imports."""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

REPO = "EthanChas/EFAS-Negative-Inversion-Software"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
TRUSTED_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com", "github-releases.githubusercontent.com")


@dataclass(frozen=True)
class Release:
    tag: str
    version: tuple[int, ...]
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    asset_size: int
    sha256: str


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.4.1' -> (0, 4, 1); anything after the numbers ('-beta') is ignored; no numbers -> ()."""
    match = re.match(r"\s*[vV]?(\d+(?:\.\d+)*)", str(text or ""))
    return tuple(int(p) for p in match.group(1).split(".")) if match else ()


def _padded(v: tuple[int, ...], n: int) -> tuple[int, ...]:
    return v + (0,) * (n - len(v))


def is_newer(latest: tuple[int, ...], current: tuple[int, ...]) -> bool:
    if not latest or not current:
        return False
    n = max(len(latest), len(current))
    return _padded(latest, n) > _padded(current, n)


def version_text(v: tuple[int, ...]) -> str:
    return ".".join(str(p) for p in v)


def trusted_url(url: str) -> bool:
    """Downloads are only taken over https from GitHub's own hosts."""
    parts = urlparse(str(url or ""))
    return parts.scheme == "https" and (parts.hostname or "").lower() in TRUSTED_HOSTS


def pick_release(data) -> Release | None:
    """The newest published release from the API's JSON, with the Windows .exe to download; None when it has no usable build."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    version = parse_version(tag)
    if not version:
        return None
    asset = None
    for a in data.get("assets") or []:
        name = str(a.get("name") or "") if isinstance(a, dict) else ""
        if name.lower().endswith(".exe") and trusted_url(a.get("browser_download_url")):
            asset = a
            break
    digest = str(asset.get("digest") or "") if asset else ""
    sha = digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else ""
    size = asset.get("size") if asset else 0
    page = str(data.get("html_url") or RELEASES_PAGE)
    return Release(
        tag=tag, version=version, notes=str(data.get("body") or "").strip(),
        page_url=page if trusted_url(page) else RELEASES_PAGE,
        asset_name=str(asset["name"]) if asset else "", asset_url=str(asset["browser_download_url"]) if asset else "",
        asset_size=int(size) if isinstance(size, int) and not isinstance(size, bool) else 0, sha256=sha,
    )
