"""Finding duplicate photos: identical files (same bytes), and photos that look alike (a re-saved, resized or re-exported copy, or the same frame scanned twice).

Identical files are found by size and then a SHA-256 of the contents. Photos that look alike are found with a small fingerprint of the picture (a 64-bit
difference hash of its thumbnail): two photos whose fingerprints differ in only a few bits look the same. A fingerprint cannot tell a copy from a different
exposure of the same frame, or from the next frame in a burst, so those are grouped too and the person decides. Nothing here changes any file.
"""

import hashlib
import io
import os
from dataclasses import dataclass, field

import numpy as np

_POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)
HASH_BITS = 64
BLOCK = 256

SIMILARITY = {"very": 4, "similar": 10}


@dataclass(frozen=True)
class Info:
    """What helps choose which copy to keep."""

    path: str
    size: int = 0
    width: int = 0
    height: int = 0
    rating: int = 0
    edited: bool = False
    versions: int = 1
    tags: int = 0


@dataclass
class Group:
    kind: str
    paths: list = field(default_factory=list)
    keep: str = ""
    distance: int = 0


def file_sha256(path: str, chunk: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def exact_groups(paths: list[str], progress=None, cancelled=None) -> list[list[str]]:
    """Groups of two or more files with identical contents. Only files of the same size are read, so most of a library is never opened."""
    by_size: dict[int, list[str]] = {}
    for p in dict.fromkeys(paths):
        try:
            by_size.setdefault(os.path.getsize(p), []).append(p)
        except OSError:
            continue
    candidates = [g for g in by_size.values() if len(g) > 1]
    todo = sum(len(g) for g in candidates)
    done = 0
    found: dict[str, list[str]] = {}
    for group in candidates:
        for p in group:
            if cancelled is not None and cancelled():
                return []
            try:
                found.setdefault(file_sha256(p), []).append(p)
            except OSError:
                pass
            done += 1
            if progress is not None:
                progress(done, todo)
    return [sorted(g) for g in found.values() if len(g) > 1]


def difference_hash(gray: np.ndarray) -> int:
    """A 64-bit fingerprint of a picture: is each of 8x8 neighbouring pairs of a 9x8 version brighter than the next?"""
    from PIL import Image

    small = np.asarray(Image.fromarray(np.ascontiguousarray(gray)).resize((9, 8), Image.Resampling.LANCZOS), dtype=np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return value


def image_hash(path: str, cache_dir: str | None = None) -> int | None:
    """The fingerprint of a photo, from its plain thumbnail (the cached one when there is one, never an edited look); None when it cannot be read."""
    from PIL import Image

    from ..browse.processor import load_cached_thumbnail, make_thumbnail_bytes, save_cached_thumbnail

    try:
        data = load_cached_thumbnail(cache_dir, path) if cache_dir else None
        if data is None:
            data = make_thumbnail_bytes(path)
            if data and cache_dir:
                save_cached_thumbnail(cache_dir, path, data)
        if not data:
            return None
        return difference_hash(np.asarray(Image.open(io.BytesIO(data)).convert("L")))
    except Exception:
        return None


def hamming_matrix_row(hashes: np.ndarray, i: int) -> np.ndarray:
    """Bits that differ between hash i and each later hash."""
    x = np.bitwise_xor(hashes[i + 1:], hashes[i])
    return _POPCOUNT[x.view(np.uint8).reshape(-1, 8)].sum(axis=1)


def similar_groups(hashes: dict[str, int], max_distance: int, progress=None, cancelled=None) -> list[tuple[list[str], int]]:
    """Groups of photos whose fingerprints are within max_distance bits of a neighbour in the group (so a chain of near-copies is one group), each with the
    largest distance joining it. Comparing every pair is quadratic, so it is done in blocks with numpy."""
    paths = list(hashes)
    n = len(paths)
    if n < 2:
        return []
    arr = np.array([hashes[p] for p in paths], dtype=np.uint64)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    link: dict[tuple[int, int], int] = {}
    for start in range(0, n, BLOCK):
        if cancelled is not None and cancelled():
            return []
        for i in range(start, min(n, start + BLOCK)):
            d = hamming_matrix_row(arr, i)
            for off in np.nonzero(d <= max_distance)[0]:
                j = i + 1 + int(off)
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[rb] = ra
                link[(i, j)] = int(d[off])
        if progress is not None:
            progress(min(n, start + BLOCK), n)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    worst: dict[int, int] = {}
    for (i, j), d in link.items():
        r = find(i)
        worst[r] = max(worst.get(r, 0), d)
    return [([paths[i] for i in members], worst.get(root, 0)) for root, members in groups.items() if len(members) > 1]


def suggest_keep(infos: list[Info]) -> str:
    """Which photo of a group to keep: the one you rated highest, then edited, then with virtual copies and tags, then the largest picture, then the
    largest file, then the shortest path (usually the original rather than 'copy of')."""
    def score(i: Info):
        return (i.rating, i.edited, i.versions > 1, i.tags > 0, i.width * i.height, i.size, -len(i.path))

    return max(infos, key=score).path


def find_duplicates(infos: list[Info], similarity: str | None = "very", cache_dir: str | None = None, progress=None, cancelled=None) -> list[Group]:
    """Exact duplicates, and (when `similarity` is 'very' or 'similar') photos that look alike. A photo is in one group only: identical files that also
    look like other photos are shown together as one look-alike group, and identical files that look like nothing else as an exact group."""
    by_path = {i.path: i for i in infos}
    paths = list(by_path)

    def stage(label: str, offset: float, weight: float):
        return lambda done, total: progress(label, offset + weight * done / max(1, total)) if progress else None

    exact = exact_groups(paths, stage("Comparing identical files", 0.0, 0.3 if similarity else 1.0), cancelled)
    if not similarity or (cancelled is not None and cancelled()):
        return [Group("exact", g, suggest_keep([by_path[p] for p in g])) for g in exact]
    stand_in: dict[str, list[str]] = {}
    hidden: set[str] = set()
    for g in exact:
        rep = suggest_keep([by_path[p] for p in g])
        stand_in[rep] = g
        hidden.update(p for p in g if p != rep)
    hashes: dict[str, int] = {}
    todo = [p for p in paths if p not in hidden]
    for k, p in enumerate(todo):
        if cancelled is not None and cancelled():
            return [Group("exact", g, suggest_keep([by_path[x] for x in g])) for g in exact]
        h = image_hash(p, cache_dir)
        if h is not None:
            hashes[p] = h
        if progress is not None:
            progress("Looking at the pictures", 0.3 + 0.5 * (k + 1) / max(1, len(todo)))
    groups: list[Group] = []
    used: set[str] = set()
    for members, dist in similar_groups(hashes, SIMILARITY[similarity], stage("Comparing pictures", 0.8, 0.2), cancelled):
        full = sorted({q for m in members for q in stand_in.get(m, [m])})
        used.update(m for m in members if m in stand_in)
        groups.append(Group("similar", full, suggest_keep([by_path[p] for p in full]), dist))
    leftover = [Group("exact", g, suggest_keep([by_path[p] for p in g])) for g in exact if suggest_keep([by_path[p] for p in g]) not in used]
    return leftover + groups
