"""Sharing presets as a file: what goes out, what is let in from a file somebody else made (every value checked, nothing that points at a file on a computer), and what happens to a name
that is already taken."""
import json

import pytest

from photoeditor.features.lookpresets import share as S

LOOK = {"exposure_ev": 0.5, "saturation": -0.2, "film_type": "c41", "tone_curve_points": [[0, 0], [128, 140], [255, 255]], "sharpen_method": "usm", "negative_inverted": True}


def _file(**kw) -> str:
    data = {"format": S.FORMAT, "version": S.VERSION, "look_presets": [{"name": "Film/Mine", "look": LOOK}], **kw}
    return json.dumps(data)


def test_a_pack_goes_out_and_comes_back_the_same():
    pack = S.build_pack([{"name": "Film/Mine", "look": LOOK}], ["Film/Empty"], {"exposure": [{"name": "Push", "values": {"exposure_ev": 1.0}}]}, "EFAS 0.9.0")
    back = S.loads(S.dumps(pack))
    assert [p["name"] for p in back.looks] == ["Film/Mine"] and back.folders == ["Film/Empty"] and back.modules == {"exposure": [{"name": "Push", "values": {"exposure_ev": 1.0}}]}
    assert back.looks[0]["look"] == pack.looks[0]["look"] and back.made_by == "EFAS 0.9.0"
    assert back.looks[0]["look"]["tone_curve_points"] == [[0, 0], [128, 140], [255, 255]] and back.looks[0]["look"]["exposure_ev"] == 0.5
    assert back.describe() == "1 look preset and 1 module preset"


def test_values_from_a_file_are_checked_against_the_field_they_belong_to():
    look = {
        "exposure_ev": 9999, "saturation": "lots", "contrast": True, "temperature": float("nan"), "tint": 0.3,   # too big is pulled in; text, true/false and NaN are not numbers
        "film_type": "nonsense", "sharpen_method": "usm", "negative_inverted": "yes", "wm_camera": "x" * 500,
        "tone_curve_points": [[0, 0]] * 1000, "tone_curve_red": [[0, 0], [255, 255]], "tone_curve_green": [[0, 0], ["a", 1]],
        "totally_unknown": 1, "__class__": "x",
    }
    cleaned = S.clean_look(look)
    assert cleaned["tint"] == 0.3 and cleaned["sharpen_method"] == "usm" and cleaned["tone_curve_red"] == [[0, 0], [255, 255]]
    assert cleaned["exposure_ev"] == 2.0, "pulled into the field's range"
    for gone in ("saturation", "contrast", "temperature", "film_type", "negative_inverted", "tone_curve_points", "tone_curve_green", "totally_unknown", "__class__"):
        assert gone not in cleaned, gone
    assert len(cleaned["wm_camera"]) == 80, "text is cut short"
    assert S.clean_look("not a look") == {} and S.clean_look({"nothing": 1}) == {}


def test_nothing_that_points_at_a_file_on_a_computer_is_shared():
    notes: set[str] = set()
    look = {"saturation": 0.1, "marks": {"text": "(c) Me", "logo": r"\\server\share\logo.svg", "text_size": 0.05}, "metering": {"film": "user:my film.json", "rect": [0, 0, 10, 10], "grade": 0.2}}
    cleaned = S.clean_look(look, notes)
    assert "logo" not in cleaned["marks"] and cleaned["marks"]["text"] == "(c) Me" and cleaned["marks"]["text_size"] == 0.05
    assert cleaned["metering"]["film"] == "generic" and "rect" not in cleaned["metering"] and cleaned["metering"]["grade"] == 0.2
    assert len(notes) == 3 and any("logo" in n for n in notes) and any("film profile" in n for n in notes) and any("text" in n for n in notes), "the watermark text is shared, and said so"
    pack = S.build_pack([{"name": "A", "look": look}], [], {})
    assert pack.notes == sorted(notes) and "server" not in S.dumps(pack) and "user:" not in S.dumps(pack)


def test_a_module_preset_keeps_only_its_own_module_s_fields():
    assert S.clean_module_values("exposure", {"exposure_ev": 1.0, "saturation": 0.5}) == {"exposure_ev": 1.0}
    assert S.clean_module_values("no_such_module", {"exposure_ev": 1.0}) == {}
    assert S.clean_module_values("watermark", {"marks": {"text": "hi", "logo": "C:/x.png"}})["marks"] == {"text": "hi"}
    assert "marks" not in S.clean_module_values("exposure", {"exposure_ev": 1.0, "marks": {"text": "hi"}})


@pytest.mark.parametrize("bad, words", [
    (b"\xff\xfe\x00 not text", "not text"),
    ("{ not json", "could not be read"),
    ("[1, 2]", "not an EFAS presets file"),
    (json.dumps({"format": "something-else", "version": 1}), "not an EFAS presets file"),
    (json.dumps({"format": S.FORMAT}), "version"),
    (json.dumps({"format": S.FORMAT, "version": True}), "version"),
    (json.dumps({"format": S.FORMAT, "version": S.VERSION + 1, "look_presets": []}), "newer EFAS"),
    (json.dumps({"format": S.FORMAT, "version": 1, "look_presets": [{"name": "A", "look": {"nope": 1}}]}), "no presets"),
    ('{"format": "efas-presets", "version": 1, "look_presets": [{"name": "A", "look": {"exposure_ev": NaN}}]}', "could not be read"),
])
def test_a_file_that_cannot_be_used_says_why(bad, words):
    with pytest.raises(S.ShareError) as err:
        S.loads(bad)
    assert words in str(err.value)


def test_a_file_that_is_far_too_big_is_refused_without_being_read():
    with pytest.raises(S.ShareError, match="too big"):
        S.loads(b"x" * (S.MAX_BYTES + 1))


def test_bad_presets_in_a_good_file_are_left_out_and_counted():
    text = _file(look_presets=[
        {"name": "Good", "look": LOOK}, {"name": "good", "look": LOOK}, {"name": "", "look": LOOK}, {"name": "Empty look", "look": {}}, "nonsense", {"name": 5, "look": LOOK},
        {"name": "  Film /  B&W  / Soft ", "look": LOOK},
    ], folders=["A/B", "a/b", 7, ""], module_presets={"exposure": [{"name": "P", "values": {"exposure_ev": 1}}, {"name": "Q", "values": {}}], "bogus": [{"name": "Z", "values": {"x": 1}}]})
    pack = S.loads(text)
    assert [p["name"] for p in pack.looks] == ["Good", "Film/B&W/Soft"], "names cleaned, a repeat (any case) is not taken twice"
    assert pack.folders == ["A/B"] and list(pack.modules) == ["exposure"] and pack.dropped == 7, pack.dropped   # the repeat, the empty name, the empty look, the non-preset, the number name, the empty module preset, the unknown module


def test_a_file_cannot_hold_more_than_the_limit():
    items = [{"name": f"P{i}", "look": {"exposure_ev": 0.1}} for i in range(S.MAX_PRESETS + 50)]
    pack = S.loads(json.dumps({"format": S.FORMAT, "version": 1, "look_presets": items}))
    assert len(pack.looks) == S.MAX_PRESETS and pack.dropped == 50


def test_a_byte_order_mark_from_a_text_editor_is_fine():
    assert S.loads(b"\xef\xbb\xbf" + _file().encode("utf-8")).looks[0]["name"] == "Film/Mine"


def test_names_that_are_taken_are_kept_both_replaced_or_skipped():
    incoming = [("Film/Mine", {"a": 1}), ("Other", {"b": 2}), ("New", {"c": 3})]
    existing = ["film/mine", "Other", "Other (imported)"]
    plan, skipped = S.plan_names(existing, incoming, S.KEEP_BOTH)
    assert [(p.original, p.final, p.action) for p in plan] == [("Film/Mine", "Film/Mine (imported)", "renamed"), ("Other", "Other (imported 2)", "renamed"), ("New", "New", "new")] and skipped == 0
    plan, skipped = S.plan_names(existing, incoming, S.REPLACE)
    assert [(p.final, p.action) for p in plan] == [("Film/Mine", "replaced"), ("Other", "replaced"), ("New", "new")]
    plan, skipped = S.plan_names(existing, incoming, S.SKIP)
    assert [p.final for p in plan] == ["New"] and skipped == 2
    assert S.count_conflicts(existing, [n for n, _ in incoming]) == 2
    assert S.plan_names([], incoming, "nonsense")[0][0].action == "new", "an unknown policy keeps both"


def test_a_long_name_still_gets_its_suffix_and_never_collides():
    name = "A" * 60 + "/" + "B" * 60 + "/" + "C" * 58   # about as long as a name can be
    plan, _ = S.plan_names([name], [(name, {})], S.KEEP_BOTH)
    final = plan[0].final
    assert final != name and final.endswith(" (imported)") and len(final) <= 180
    plan, _ = S.plan_names([name, final], [(name, {})], S.KEEP_BOTH)
    assert plan[0].final.endswith("(imported 2)") and plan[0].final not in (name, final)


def test_the_stores_take_a_pack_in_and_give_it_back(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path))
    from photoeditor.features.lookpresets import module_store, store
    pack = S.loads(_file(folders=["Spare"], module_presets={"exposure": [{"name": "Push", "values": {"exposure_ev": 1.0}}]}))
    plan, _ = S.plan_names(store.names(), [(p["name"], p["look"]) for p in pack.looks], S.KEEP_BOTH)
    for item in plan:
        store.save_preset(item.final, item.payload)
    module_store.save_preset("exposure", "Push", {"exposure_ev": 1.0})
    store.set_folders(pack.folders)
    assert store.names() == ["Film/Mine"] and store.get("Film/Mine")["exposure_ev"] == 0.5 and store.folders() == ["Spare"]
    again = S.build_pack([{"name": n, "look": store.get(n)} for n in store.names()], store.folders(), module_store.all_presets())
    assert S.loads(S.dumps(again)).looks == pack.looks and module_store.all_presets()["exposure"][0]["name"] == "Push"


def test_a_file_of_only_folders_makes_the_folders_and_says_so():
    pack = S.loads(json.dumps({"format": S.FORMAT, "version": 1, "look_presets": [], "folders": ["Film/Empty", "Other"]}))
    assert pack.folders == ["Film/Empty", "Other"] and pack.count() == 0 and pack.describe() == "2 folders"
    assert S.ImportResult(folders=2).summary() == "Made 2 folders; there were no presets to import"
    assert S.ImportResult(added=1, renamed=1).summary() == "Imported 2 presets (1 kept next to yours with ' (imported)' added)"
    assert S.ImportResult(skipped=3).summary() == "Nothing was imported (3 skipped, the names were already there)"
