"""Names that form a tree: "B&W/Number 1" is Number 1 in the folder B&W."""
from photoeditor.features.presettree import logic as t


def test_clean_path():
    assert t.clean_path("  B&W /  Number   1 ") == "B&W/Number 1"
    assert t.clean_path("a//b///c/") == "a/b/c" and t.clean_path("/") == "" and t.clean_path("   ") == "" and t.clean_path("a\\b") == "a/b"
    assert len(t.clean_path("x" * 500)) <= t.MAX_PATH and all(len(p) <= t.MAX_SEGMENT for p in t.split("y" * 200 + "/z"))
    assert t.split("A/B") == ["A", "B"] and t.leaf("A/B/C") == "C" and t.parent("A/B/C") == "A/B" and t.parent("A") == "" and t.leaf("") == ""
    assert t.join("A/B", "C") == "A/B/C" and t.join("", "C") == "C" and t.display("A/B/C") == "A › B › C"


def shape(nodes):
    return [(n.label, shape(n.children)) if n.is_folder else n.label for n in nodes]


def test_build_makes_folders_from_names_folders_first_then_presets_in_made_order():
    names = ["Zebra", "B&W/Number 2", "Lab/Frontier/Warm", "B&W/Number 1", "Alpha", "Lab/Noritsu", "Lab/Frontier/Cool"]
    tree = t.build(names)
    assert shape(tree) == [("B&W", ["Number 2", "Number 1"]), ("Lab", [("Frontier", ["Warm", "Cool"]), "Noritsu"]), "Zebra", "Alpha"]
    assert [n.full for n in tree[0].children] == ["B&W/Number 2", "B&W/Number 1"]
    assert tree[0].path == "B&W" and tree[1].children[0].path == "Lab/Frontier" and tree[0].is_folder and not tree[2].is_folder
    assert t.flatten(tree) == ["B&W/Number 2", "B&W/Number 1", "Lab/Frontier/Warm", "Lab/Frontier/Cool", "Lab/Noritsu", "Zebra", "Alpha"]


def test_folders_match_without_regard_to_case_and_spacing():
    tree = t.build(["b&w/One", "B&W /Two", "B&W/one"])
    assert shape(tree) == [("b&w", ["One", "Two"])], "the same folder, and a repeated name is shown once"


def test_a_preset_and_a_folder_may_share_a_name():
    tree = t.build(["Film", "Film/Fast", "Film/Slow"])
    assert [(n.label, n.is_folder) for n in tree] == [("Film", True), ("Film", False)]


def test_nothing_in_nothing_out():
    assert t.build([]) == [] and t.build(["", "  ", "/"]) == []


def test_in_folder_and_move_folder():
    names = ["A/x", "A/B/y", "AA/z", "a/q", "C"]
    assert t.in_folder(names, "A") == ["A/x", "A/B/y", "a/q"], "any depth, any case, but not a name that only starts the same"
    assert t.move_folder(names, "A", "New/Place") == {"A/x": "New/Place/x", "A/B/y": "New/Place/B/y", "a/q": "New/Place/q"}
    assert t.move_folder(names, "A/B", "A") == {"A/B/y": "A/y"}
    assert t.move_folder(names, "A", " ") == {}
