"""Finding duplicate photos: identical files, look-alikes, and which copy to keep."""
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from photoeditor.features.library import duplicates as D  # noqa: E402


def picture(seed, h=240, w=320):
    rng = np.random.default_rng(seed)
    base = cv2.GaussianBlur(rng.random((h, w, 3)).astype(np.float32), (0, 0), 12)
    base = (base - base.min()) / np.ptp(base)
    return (base * 255).astype(np.uint8)


def save(path, img, quality=90):
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return str(path)


@pytest.fixture
def lib(tmp_path):
    a = save(tmp_path / "a.jpg", picture(1))
    shutil.copy(a, tmp_path / "a copy.jpg")
    resized = save(tmp_path / "a small.jpg", cv2.resize(picture(1), (160, 120)), 70)
    b = save(tmp_path / "b.jpg", picture(2))
    c = save(tmp_path / "c.jpg", picture(3))
    (tmp_path / "notes.txt").write_text("not a photo")
    return {"a": a, "a_copy": str(tmp_path / "a copy.jpg"), "a_small": resized, "b": b, "c": c, "dir": tmp_path}


def test_identical_files_are_found_by_content_and_names_do_not_matter(lib):
    groups = D.exact_groups([lib["a"], lib["a_copy"], lib["b"], lib["c"], lib["a_small"]])
    assert groups == [sorted([lib["a"], lib["a_copy"]])]


def test_only_files_of_the_same_size_are_read(lib, monkeypatch):
    read = []
    real = D.file_sha256
    monkeypatch.setattr(D, "file_sha256", lambda p, *a: (read.append(p), real(p))[1])
    D.exact_groups([lib["a"], lib["a_copy"], lib["b"], lib["c"]])
    assert sorted(read) == sorted([lib["a"], lib["a_copy"]]), "b and c have sizes nobody else shares"


def test_missing_files_are_ignored_and_cancelling_stops_early(lib):
    assert D.exact_groups([lib["a"], str(lib["dir"] / "gone.jpg")]) == []
    assert D.exact_groups([lib["a"], lib["a_copy"]], cancelled=lambda: True) == []


def test_a_resized_recompressed_copy_has_a_near_identical_fingerprint_and_other_pictures_do_not():
    a = D.difference_hash(cv2.cvtColor(picture(1), cv2.COLOR_BGR2GRAY))
    small = D.difference_hash(cv2.cvtColor(cv2.resize(picture(1), (160, 120)), cv2.COLOR_BGR2GRAY))
    other = D.difference_hash(cv2.cvtColor(picture(2), cv2.COLOR_BGR2GRAY))
    dist = lambda x, y: bin(x ^ y).count("1")  # noqa: E731
    assert dist(a, small) <= 4 and dist(a, other) > 10


def test_similar_groups_chain_neighbours_and_report_the_widest_gap():
    base = 0x0F0F0F0F0F0F0F0F
    hashes = {"x": base, "y": base ^ 0b111, "z": base ^ 0b111 ^ (0b11 << 20), "far": ~base & 0xFFFFFFFFFFFFFFFF}
    [(members, worst)] = D.similar_groups(hashes, 4)
    assert sorted(members) == ["x", "y", "z"] and worst == 3 and "far" not in members
    assert D.similar_groups({"only": 1}, 4) == [] and D.similar_groups(hashes, 0) == []


def test_a_photo_is_in_one_group_only(lib):
    infos = [D.Info(lib[k], size=Path(lib[k]).stat().st_size) for k in ("a", "a_copy", "a_small", "b", "c")]
    groups = D.find_duplicates(infos, "very", cache_dir=str(lib["dir"] / "cache"))
    kinds = [(g.kind, sorted(Path(p).name for p in g.paths)) for g in groups]
    assert kinds == [("similar", ["a copy.jpg", "a small.jpg", "a.jpg"])], kinds
    every = [p for g in groups for p in g.paths]
    assert len(every) == len(set(every))


def test_identical_files_that_look_like_nothing_else_stay_an_exact_group(lib):
    infos = [D.Info(lib[k], size=Path(lib[k]).stat().st_size) for k in ("a", "a_copy", "b", "c")]
    groups = D.find_duplicates(infos, "very", cache_dir=str(lib["dir"] / "cache"))
    assert [(g.kind, sorted(Path(p).name for p in g.paths)) for g in groups] == [("exact", ["a copy.jpg", "a.jpg"])]
    assert [g.kind for g in D.find_duplicates(infos, None)] == ["exact"]


def test_progress_is_reported_and_cancel_returns_what_was_found(lib):
    seen = []
    infos = [D.Info(lib[k]) for k in ("a", "a_copy", "b")]
    D.find_duplicates(infos, "very", cache_dir=str(lib["dir"] / "cache"), progress=lambda label, f: seen.append((label, f)))
    assert seen and seen[-1][1] <= 1.0 and all(0 <= f <= 1 for _l, f in seen)
    partial = D.find_duplicates(infos, "very", cache_dir=str(lib["dir"] / "cache2"), cancelled=lambda: False)
    assert partial


def test_the_suggested_keeper_is_the_best_rated_edited_biggest_one():
    plain = D.Info("/x/a.jpg", size=100, width=10, height=10)
    rated = D.Info("/x/b.jpg", size=50, width=5, height=5, rating=3)
    edited = D.Info("/x/c.jpg", size=60, width=5, height=5, edited=True)
    big = D.Info("/x/d.jpg", size=900, width=40, height=40)
    assert D.suggest_keep([plain, rated, edited, big]) == "/x/b.jpg"
    assert D.suggest_keep([plain, edited, big]) == "/x/c.jpg"
    assert D.suggest_keep([plain, big]) == "/x/d.jpg"
    assert D.suggest_keep([D.Info("/x/longer name copy.jpg", size=5), D.Info("/x/a.jpg", size=5)]) == "/x/a.jpg"
