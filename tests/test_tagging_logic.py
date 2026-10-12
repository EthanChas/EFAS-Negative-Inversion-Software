"""The Tagging panel (darktable's tagging module): what its lists show, the tag dictionary in the database, rename / change path / delete, keyword files."""
import pytest

from photoeditor.features.persistence import edit_store
from photoeditor.features.tags import tagging as G

PER_PATH = {"a": ["People/Family", "Holiday"], "b": ["People/Family", "People/Friends"], "c": ["Holiday"], "d": []}


def test_attached_tags_with_counts_for_several_photos():
    rows = G.attached_rows(PER_PATH, ["a", "b", "c"])
    assert [(r.tag, r.count, r.total) for r in rows] == [("Holiday", 2, 3), ("People/Family", 2, 3), ("People/Friends", 1, 3)]
    assert rows[1].label == "People › Family  (2/3)"
    one = G.attached_rows(PER_PATH, ["a"])
    assert [r.label for r in one] == ["Holiday", "People › Family"], "no counts for a single photo"
    assert G.attached_rows(PER_PATH, ["d"]) == [] and G.attached_rows(PER_PATH, []) == []


def test_attached_sort_and_parents_toggle():
    by_count = G.attached_rows(PER_PATH, ["a", "b", "c"], by_count=True)
    assert [r.tag for r in by_count][-1] == "People/Friends" and by_count[0].count == 2
    leaf = G.attached_rows(PER_PATH, ["b"], leaf_only=True)
    assert [r.label for r in leaf] == ["Family", "Friends"]


def test_attached_counts_ignore_capitalisation():
    counts = G.attached_counts({"a": ["Trip"], "b": ["trip"], "c": ["TRIP", "trip"]}, ["a", "b", "c"])
    assert list(counts.values()) == [3]


def test_marks_all_some_none():
    attached = G.attached_counts(PER_PATH, ["a", "b", "c"])
    assert G.mark_for("Holiday", attached, 3) == G.SOME
    assert G.mark_for("people/family", attached, 3) == G.SOME
    assert G.mark_for("Holiday", G.attached_counts(PER_PATH, ["a", "c"]), 2) == G.ALL
    assert G.mark_for("Nothing", attached, 3) == G.NONE and G.mark_for("Holiday", {}, 0) == G.NONE


DICTIONARY = {"People/Family": 9, "People/Friends": 4, "Holiday": 7, "Places/Paris": 2, "Unused/Thing": 0}


def test_dictionary_list_is_in_tree_order_or_filtered_best_first():
    attached = {"Holiday": 3}
    rows = G.dictionary_rows(DICTIONARY, attached, 3)
    assert [e.tag for e in rows] == ["Holiday", "People/Family", "People/Friends", "Places/Paris", "Unused/Thing"]
    assert [e.mark for e in rows][0] == G.ALL and all(e.mark == G.NONE for e in rows[1:])
    assert rows[1].count == 9
    typed = G.dictionary_rows(DICTIONARY, attached, 3, "fam")
    assert [e.tag for e in typed] == ["People/Family"]
    assert [e.tag for e in G.dictionary_rows(DICTIONARY, attached, 3, "zzz")] == []


def test_suggestions_are_what_goes_with_the_attached_tags():
    photos = [["Holiday", "Beach", "Family"], ["Holiday", "Beach"], ["Holiday", "Food"], ["Work", "Desk"], ["Beach"]]
    suggested = G.suggestions({"Holiday"}, photos)
    assert suggested[0] == "Beach" and set(suggested) == {"Beach", "Family", "Food"}
    assert G.suggestions(set(), photos) == []
    assert G.suggestions({"holiday"}, photos)[0] == "Beach", "capitalisation does not matter"


def test_tree_has_a_node_for_every_level_and_marks_free_nodes():
    tree = G.build_tree(DICTIONARY, {"People/Family": 2}, 2)
    assert [n.name for n in tree] == ["Holiday", "People", "Places", "Unused"]
    people = tree[1]
    assert not people.defined, "People is only a level other tags are inside - a free node"
    assert [c.name for c in people.children] == ["Family", "Friends"] and people.children[0].defined and people.children[0].count == 9
    assert people.children[0].mark == G.ALL and people.children[1].mark == G.NONE
    assert tree[0].defined and tree[0].count == 7
    deep = G.build_tree({"a/b/c": 1}, {}, 0)
    assert deep[0].name == "a" and deep[0].children[0].name == "b" and deep[0].children[0].children[0].path == "a/b/c" and not deep[0].defined
    filtered = G.build_tree(DICTIONARY, {}, 0, "paris")
    assert [n.name for n in filtered] == ["Places"] and filtered[0].children[0].name == "Paris"
    assert G.build_tree({}, {}, 0) == []


def test_a_tag_that_is_also_a_level_is_one_node():
    tree = G.build_tree({"People": 3, "People/Family": 2}, {}, 0)
    assert len(tree) == 1 and tree[0].defined and tree[0].count == 3 and [c.name for c in tree[0].children] == ["Family"]


KEYWORDS = "Places\n\tFrance\n\t\tParis\n\tSpain\nPeople\n\tFamily\n"


def test_lightroom_keyword_files_round_trip():
    tags = G.from_lightroom(KEYWORDS)
    assert tags == ["Places", "Places/France", "Places/France/Paris", "Places/Spain", "People", "People/Family"]
    text = G.to_lightroom(["Places/France/Paris", "People/Family"])
    assert text == "People\n\tFamily\nPlaces\n\tFrance\n\t\tParis\n"
    assert G.from_lightroom(text) == ["People", "People/Family", "Places", "Places/France", "Places/France/Paris"]
    assert G.to_lightroom([]) == ""


def test_lightroom_import_ignores_markers_and_junk():
    text = "Animals {cat, dog}\n\t[Private]\n\t{just a synonym line}\n\n\tBirds\n\t\t\t\tDeepTooFar\n"
    assert G.from_lightroom(text) == ["Animals", "Animals/Private", "Animals/Birds", "Animals/Birds/DeepTooFar"]
    assert G.from_lightroom("") == []
    assert G.from_lightroom("a/b\n") == ["a b"], "a slash inside one keyword is not a level"


@pytest.fixture
def db(tmp_path):
    conn = edit_store.connect(str(tmp_path / "t.db"))
    edit_store.add_tags(conn, ["a", "b"], ["People/Family", "Holiday"])
    edit_store.add_tags(conn, ["b", "c"], ["People/Friends", "People/Family/Gran"])
    edit_store.add_tags(conn, ["c"], ["Peoples"])
    yield conn
    conn.close()


def tags_of(conn, path):
    return edit_store.get_tags(conn, [path]).get(path, [])


def test_dictionary_counts_include_unused_tags(db):
    edit_store.define_tags(db, ["Places/Paris", "holiday", "Brand/New"])
    counts = edit_store.dictionary_counts(db)
    assert counts["Holiday"] == 2 and counts["People/Family"] == 2 and counts["Places/Paris"] == 0 and counts["Brand/New"] == 0
    assert "holiday" not in counts, "a defined tag that is also used is listed once, by the photos' spelling"
    assert edit_store.defined_tags(db) == ["Brand/New", "holiday", "Places/Paris"]


def test_rename_a_leaf(db):
    changed = edit_store.rename_tag(db, "People/Friends", "People/Mates", with_children=False)
    assert changed == ["b", "c"]
    assert "People/Mates" in tags_of(db, "b") and "People/Friends" not in tags_of(db, "b")
    assert "People/Mates" in tags_of(db, "c")


def test_change_path_moves_everything_inside(db):
    changed = edit_store.rename_tag(db, "People", "Humans", with_children=True)
    assert changed == ["a", "b", "c"]
    assert "Humans/Family" in tags_of(db, "a") and "Humans/Family/Gran" in tags_of(db, "b") and "Humans/Friends" in tags_of(db, "c")
    assert "Peoples" in tags_of(db, "c"), "Peoples is not inside People"
    assert not any(t.startswith("People/") or t == "People" for p in "abc" for t in tags_of(db, p))


def test_rename_onto_an_existing_tag_merges(db):
    edit_store.rename_tag(db, "People/Friends", "People/Family", with_children=False)
    assert tags_of(db, "b").count("People/Family") == 1
    assert "People/Family" in tags_of(db, "c")


def test_changing_only_the_capitals_keeps_the_tag(db):
    edit_store.rename_tag(db, "Holiday", "HOLIDAY", with_children=False)
    assert tags_of(db, "a").count("HOLIDAY") == 1 and "Holiday" not in tags_of(db, "a")


def test_rename_updates_the_dictionary_too(db):
    edit_store.define_tags(db, ["People/Kids", "Other"])
    edit_store.rename_tag(db, "People", "Humans", with_children=True)
    assert "Humans/Kids" in edit_store.defined_tags(db) and "People/Kids" not in edit_store.defined_tags(db) and "Other" in edit_store.defined_tags(db)


def test_delete_a_tag_and_a_node(db):
    edit_store.define_tags(db, ["People/Family", "People/Unused"])
    gone = edit_store.delete_tag(db, "People/Family", with_children=False)
    assert gone == ["a", "b"]
    assert "People/Family" not in tags_of(db, "a") and "People/Family/Gran" in tags_of(db, "b"), "the tag inside it stays when only the tag is deleted"
    assert "People/Family" not in edit_store.defined_tags(db) and "People/Unused" in edit_store.defined_tags(db)
    gone = edit_store.delete_tag(db, "People", with_children=True)
    assert set(gone) == {"b", "c"}
    assert tags_of(db, "a") == ["Holiday"] and "Peoples" in tags_of(db, "c") and edit_store.defined_tags(db) == []
    assert edit_store.delete_tag(db, "Nothing") == []


def test_tag_paths_and_wildcards_in_names(db):
    edit_store.add_tags(db, ["a"], ["100%_done/x"])
    assert edit_store.tag_paths(db, "People", with_children=True) == ["a", "b", "c"]
    assert edit_store.tag_paths(db, "100%_done", with_children=True) == ["a"]
    assert edit_store.tag_paths(db, "100", with_children=True) == [], "% and _ in a name are not wildcards"
    assert edit_store.tag_paths(db, "People", with_children=False) == []
