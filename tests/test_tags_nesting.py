"""Nested tags (People/Family), finding the closest tag as you type, and the pre-made list."""
import pytest

from photoeditor.features.tags import logic as T


def test_cleaning_keeps_levels_and_drops_empties():
    assert T.clean_tag("People/Family") == "People/Family"
    assert T.clean_tag("  People /  Family ") == "People/Family"
    assert T.clean_tag("a / / b") == "a/b"
    assert T.clean_tag("a > b › c") == "a/b/c"
    assert T.clean_tag("/lead/and/trail/") == "lead/and/trail"
    assert T.clean_tag("#holiday") == "holiday" and T.clean_tag("a,b;c|d") == "a b c d"
    assert T.clean_tag("") == "" and T.clean_tag("///") == ""
    assert len(T.clean_tag("x" * 500)) <= T.MAX_TAG_LENGTH


def test_levels():
    assert T.parts("a/b/c") == ["a", "b", "c"] and T.leaf("a/b/c") == "c" and T.parent("a/b/c") == "a/b" and T.parent("a") == ""
    assert T.depth("a") == 0 and T.depth("a/b/c") == 2
    assert T.ancestors("a/b/c") == ["a", "a/b"] and T.ancestors("a") == []
    assert T.display("People/Family") == "People › Family"


def test_a_parent_finds_everything_inside_it():
    assert T.is_inside("People/Family", "People") and T.is_inside("people/family/gran", "PEOPLE/Family") and T.is_inside("People", "people")
    assert not T.is_inside("Peoples", "People") and not T.is_inside("People", "People/Family") and not T.is_inside("x", "")
    assert T.matches(["Places/Paris", "People/Family"], "people")
    assert not T.matches(["Peoples"], "People")


def test_counts_include_the_levels_above():
    counts = T.count_with_parents([["People/Family", "People/Friends"], ["People/Family/Gran"], ["Places"], []])
    assert counts["People"] == 2, "a photo counts once for People however many tags inside it"
    assert counts["People/Family"] == 2 and counts["People/Friends"] == 1 and counts["People/Family/Gran"] == 1 and counts["Places"] == 1


def test_tree_order_puts_children_under_their_parent():
    assert T.tree_order(["b", "a/z", "a", "a/b", "A/c"]) == ["a", "a/b", "A/c", "a/z", "b"]


def test_unique_and_parse():
    assert T.parse_tags("People/Family, people/family; Travel") == ["People/Family", "Travel"]
    assert T.unique(["A/B", "a/b", "C"]) == ["A/B", "C"]
    assert T.merged(["A"], ["a", "B/C"]) == ["A", "B/C"] and T.without(["A/B", "C"], ["a/b"]) == ["C"]


TAGS = ["People/Family", "People/Friends", "People/Portrait", "Places/Paris", "Places/Nature", "Subject/Street", "Subject/Night", "Holiday", "Film/Black & white", "Status/Keeper"]


def test_best_match_comes_first():
    assert T.rank("family", TAGS)[0] == "People/Family"
    assert T.rank("fam", TAGS)[0] == "People/Family"
    assert T.rank("PEOPLE/FRIENDS", TAGS)[0] == "People/Friends"
    assert T.rank("holiday", TAGS)[0] == "Holiday"
    assert T.rank("hol", TAGS)[0] == "Holiday"
    assert T.rank("paris", TAGS) == ["Places/Paris"]
    assert T.rank("night", TAGS)[0] == "Subject/Night"
    assert T.rank("black", TAGS)[0] == "Film/Black & white"


def test_typos_still_find_it():
    assert T.rank("famly", TAGS)[0] == "People/Family"
    assert T.rank("prtrt", TAGS)[0] == "People/Portrait"
    assert T.rank("strt", TAGS)[0] == "Subject/Street"
    assert T.rank("zzzq", TAGS) == []
    assert T.rank("", TAGS) == [] and T.rank("   ", TAGS) == []


def test_an_exact_leaf_beats_a_longer_partial():
    tags = ["Film/Black & white", "Black", "Subject/Black cat"]
    assert T.rank("black", tags)[0] == "Black"
    nested = ["Places/Home", "Home", "Status/Homework"]
    assert T.rank("home", nested)[0] == "Home"
    assert T.rank("home", ["Places/Home", "Status/Homework"])[0] == "Places/Home", "its last level is exactly what was typed"


def test_ties_go_to_the_more_used_then_the_shorter():
    tags = ["Trip/Spain", "Trip/Spain 2019", "Other/Spain"]
    assert T.rank("spain", tags, usage={"Other/Spain": 9})[0] == "Other/Spain"
    assert T.rank("spain", ["Trip/Spain 2019", "Trip/Spain"])[0] == "Trip/Spain"
    assert len(T.rank("a", [f"a{i}" for i in range(30)], limit=5)) == 5


def test_premade_tags_are_clean_nested_and_unique():
    assert len(T.PREMADE) >= 20 and len(set(t.casefold() for t in T.PREMADE)) == len(T.PREMADE)
    for tag in T.PREMADE:
        assert T.clean_tag(tag) == tag, tag
    assert any(T.depth(t) for t in T.PREMADE)


def _row(name, tags):
    return {"name": name, "tags": tags, "tags_text": " ".join(tags), "rating": 0, "flag": "", "edited": False, "camera": "", "roll_camera": "", "lens": "", "roll_lens": "",
            "film": "", "folder": "f", "iso": 0, "day": "2026-01-01", "path": name, "note": "", "place": "", "taken": "", "mtime_ns": 0}


def test_workbench_filter_by_a_parent_tag_finds_what_is_inside():
    from photoeditor.features.library import query as Q

    rows = [_row("a", ["People/Family"]), _row("b", ["People/Friends/School"]), _row("c", ["Places/Paris"]), _row("d", []), _row("e", ["Peoples"])]
    names = lambda tag: sorted(r["name"] for r in Q.filter_rows(rows, Q.Query(tag=tag)))
    assert names("People") == ["a", "b"], "everything inside People, not the unrelated 'Peoples'"
    assert names("people/family") == ["a"] and names("People/Friends") == ["b"] and names("Places") == ["c"] and names("nothing") == []
    assert names("") == ["a", "b", "c", "d", "e"]


def test_the_tag_filter_list_is_a_tree_with_counts_for_parents():
    from photoeditor.features.library import query as Q

    rows = [_row("a", ["People/Family"]), _row("b", ["People/Friends/School", "People/Family"]), _row("c", ["Places/Paris"])]
    tags = Q.facets(rows)["tag"]
    assert [t[0] for t in tags] == ["People", "People/Family", "People/Friends", "People/Friends/School", "Places", "Places/Paris"]
    counts = {t[0]: t[2] for t in tags}
    assert counts["People"] == 2 and counts["People/Family"] == 2 and counts["People/Friends"] == 1
    labels = {t[0]: t[1] for t in tags}
    assert labels["People"] == "People" and labels["People/Family"] == "    Family" and labels["People/Friends/School"] == "        School"


def test_typing_a_parent_in_search_also_finds_nested():
    from photoeditor.features.library import query as Q

    rows = [_row("a", ["People/Family"]), _row("b", ["Places/Paris"])]
    assert [r["name"] for r in Q.filter_rows(rows, Q.Query(text="tag:people"))] == ["a"]
    assert [r["name"] for r in Q.filter_rows(rows, Q.Query(text="tag:family"))] == ["a"]


def test_sidecar_keeps_nested_tags_and_writes_the_hierarchy(tmp_path):
    from photoeditor.features.xmp import logic as xmp

    photo = tmp_path / "x.jpg"
    photo.write_bytes(b"x")
    assert xmp.write_tags(str(photo), ["Holiday", "People/Family", "Places/Paris/Louvre"])
    assert xmp.read_tags(str(photo)) == ["Holiday", "People/Family", "Places/Paris/Louvre"]
    text = open(xmp.sidecar_path(str(photo)), encoding="utf-8").read()
    assert "hierarchicalSubject" in text and "People|Family" in text and "Places|Paris|Louvre" in text and "Holiday|" not in text
    assert xmp.write_tags(str(photo), ["Holiday"])
    assert "hierarchicalSubject" not in open(xmp.sidecar_path(str(photo)), encoding="utf-8").read()
