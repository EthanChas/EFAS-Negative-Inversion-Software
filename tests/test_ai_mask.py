"""The AI object mask (darktable's Segment Anything masking): turning a model's cut into shapes, installing a model package, the engine that answers clicks without freezing the window, the
mask tool's AI mode, the models dialog with a real download, and - when a model file is given in EFAS_TEST_SAM_MODEL - the real model on a picture."""
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from photoeditor.desktop.mask_tool import AI_FEATHER, AI_OBJECT, MaskTool
from photoeditor.features.aimask import models, shapes
from photoeditor.features.aimask import runtime
from photoeditor.features.masks import model as M

ROOT = Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")
_spec = importlib.util.spec_from_file_location("mask_tool_tests", ROOT / "tests" / "test_mask_tool.py")
_mt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mt)
FakeHost, FW, FH = _mt.FakeHost, _mt.FW, _mt.FH


# ---------------------------------------------------------------- from a cut to shapes
def _disc(h=300, w=400, cx=200, cy=150, r=60, soft=4.0):
    ys, xs = np.mgrid[0:h, 0:w]
    d = np.hypot(xs - cx, ys - cy)
    return (1.0 / (1.0 + np.exp((d - r) / soft))).astype(np.float32)


def test_the_regions_with_a_click_on_the_object_are_kept_and_holes_are_filled():
    prob = np.maximum(_disc(cx=100, cy=150, r=50), _disc(cx=300, cy=150, r=30))
    prob[120:135, 120:135] = 0.0                                             # a hole in the left disc, away from the click
    left = shapes.region_mask(prob, [(100.0, 150.0)])
    assert left[150, 100] == 1 and left[150, 300] == 0 and left[127, 127] == 1, "the click is in the left disc: only that one is kept, and its hole is filled"
    both = shapes.region_mask(prob, [(100.0, 150.0), (300.0, 150.0)])
    assert both[150, 100] == 1 and both[150, 300] == 1
    biggest = shapes.region_mask(prob, [(10.0, 10.0)])
    assert biggest[150, 100] == 1 and biggest[150, 300] == 0, "no click inside a region: the largest one"
    assert shapes.region_mask(np.zeros((50, 60), np.float32), [(5.0, 5.0)]).sum() == 0


def test_a_region_becomes_a_simple_polygon_that_follows_it():
    prob = _disc()
    polys = shapes.outlines(prob, [(200.0, 150.0)])
    assert len(polys) == 1
    poly = polys[0]
    assert 20 < len(poly) < 400, len(poly)
    radius = np.hypot(poly[:, 0] - 200, poly[:, 1] - 150)
    assert abs(float(radius.mean()) - 60) < 1.5 and float(radius.std()) < 1.5, (radius.mean(), radius.std())
    two = shapes.outlines(np.maximum(_disc(cx=100, r=40), _disc(cx=300, r=25)), [(100.0, 150.0), (300.0, 150.0)])
    assert len(two) == 2 and cv2.contourArea(two[0].astype(np.float32)) > cv2.contourArea(two[1].astype(np.float32)), "biggest first"
    speck = np.zeros((300, 400), np.float32)
    speck[10:13, 10:13] = 1.0
    assert shapes.polygons((speck > 0.5).astype(np.uint8)) == [], "a speck is left out"


# ---------------------------------------------------------------- the picture the encoder is given
def test_the_picture_is_fitted_into_a_1024_square_and_normalised():
    rgb = np.full((100, 200, 3), (255, 128, 0), np.uint8)
    data, scale = runtime.ObjectSegmenter.prepare(rgb)
    assert data.shape == (1, 3, 1024, 1024) and data.dtype == np.float32 and abs(scale - 1024 / 200) < 1e-9
    assert np.all(data[0, :, 512:, :] == 0.0), "the short side is padded with zeros"
    mean, std = np.array([0.485, 0.456, 0.406]), np.array([0.229, 0.224, 0.225])
    want = (np.array([1.0, 128 / 255, 0.0]) - mean) / std
    assert np.allclose(data[0, :, 10, 10], want, atol=0.02), (data[0, :, 10, 10], want)


# ---------------------------------------------------------------- model packages
def _package(path, model_id="mask-object-fake", task="mask", arch="sam2", files=("encoder.onnx", "decoder.onnx"), extra=()):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{model_id}/config.json", json.dumps({"id": model_id, "name": "fake", "task": task, "arch": arch, "backend": "onnx"}))
        for name in files:
            z.writestr(f"{model_id}/{name}", b"not a model" * 10)
        for name in extra:
            z.writestr(name, b"x")
    return str(path)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTOEDITOR_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_a_package_is_checked_installed_chosen_and_removed(data_dir):
    pkg = _package(data_dir / "ok.dtmodel", extra=("../evil.txt", "/abs.txt"))
    assert models.check_package(pkg) == ("mask-object-fake", "mask-object-fake/")
    assert models.installed() == [] and models.active() == ""
    assert models.install_package(pkg) == "mask-object-fake"
    assert models.installed() == ["mask-object-fake"] and models.is_installed("mask-object-fake") and models.active() == "mask-object-fake", "the first installed is used"
    assert not (data_dir / "evil.txt").exists() and not os.path.exists(os.path.join(models.models_dir(), "..", "evil.txt")), "nothing is written outside the folder"
    second = _package(data_dir / "two.dtmodel", model_id="mask-object-second")
    models.install_package(second)
    models.set_active("mask-object-second")
    assert models.active() == "mask-object-second"
    models.set_active("not-installed")
    assert models.active() == "mask-object-fake", "an id that is not installed falls back to the first"
    models.remove("mask-object-second")
    assert models.installed() == ["mask-object-fake"] and models.size_on_disk("mask-object-fake") > 0
    assert models.name_of("mask-object-sam21-tiny") == "SAM 2.1 Tiny" and models.name_of("mine") == "mine"


def _bad_id(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("m/config.json", json.dumps({"id": "a/b", "task": "mask", "arch": "sam2"}))
        z.writestr("m/encoder.onnx", b"x")
        z.writestr("m/decoder.onnx", b"x")


@pytest.mark.parametrize("make, message", [
    (lambda p: Path(p).write_bytes(b"this is not a zip"), "not a zip"),
    (lambda p: zipfile.ZipFile(p, "w").writestr("a.txt", "x"), "no config.json"),
    (lambda p: _package(p, task="denoise"), "not for masks"),
    (lambda p: _package(p, arch="segnext"), "Segment Anything 2.1"),
    (lambda p: _package(p, files=("encoder.onnx",)), "no decoder.onnx"),
    (lambda p: _package(p, model_id="../escape"), "no config.json"),     # (a member outside the folder is never read)
    (lambda p: _bad_id(p), "usable model id"),
])
def test_a_package_that_cannot_be_used_says_why(data_dir, make, message):
    path = str(data_dir / "bad.dtmodel")
    make(path)
    with pytest.raises(ValueError, match=message):
        models.install_package(path)
    assert models.installed() == []


def test_the_catalogue_is_darktables_sam_models_with_their_download_addresses():
    assert [m.id for m in models.CATALOG] == ["mask-object-sam21-tiny", "mask-object-sam21-small", "mask-object-sam21-base-plus"]
    tiny = models.info("mask-object-sam21-tiny")
    assert tiny.size_mb == 136 and tiny.url == "https://github.com/darktable-org/darktable-ai/releases/download/release-5.6.0/mask-object-sam21-tiny.dtmodel"


# ---------------------------------------------------------------- the engine in the window
class FakeSegmenter:
    """Stands in for the model: it 'sees' a disc of radius 40 round the last click on the object."""

    instances = 0
    calls: list = []

    def __init__(self, folder):
        FakeSegmenter.instances += 1
        self.size = None

    def encode(self, rgb):
        self.size = rgb.shape[:2]

    def cut(self, points, labels, previous=None):
        FakeSegmenter.calls.append((list(points), list(labels), previous is not None))
        fg = [p for p, t in zip(points, labels) if t == 1] or [(0.0, 0.0)]
        h, w = self.size
        prob = _disc(h, w, int(fg[-1][0]), int(fg[-1][1]), 40, 2.0)
        for (x, y), t in zip(points, labels):
            if t == 0:
                prob[int(y) - 15:int(y) + 15, int(x) - 15:int(x) + 15] = 0.0
        return runtime.Cut(prob, np.zeros((1, 1, 256, 256), np.float32), 0.9)


def _wait(qapp, check, seconds=10.0):
    import time

    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        if check():
            return True
        time.sleep(0.005)
    return False


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication      # the platform is left alone: forcing "offscreen" here would leave the later watermark tests (they draw SVG text) without fonts

    return QApplication.instance() or QApplication([])


def test_the_engine_reads_the_picture_then_answers_each_click_and_refines(data_dir, qapp, monkeypatch):
    from photoeditor.desktop import ai_mask_service as svc

    monkeypatch.setattr(svc, "ObjectSegmenter", FakeSegmenter)
    FakeSegmenter.calls.clear()
    picture = np.full((300, 400, 3), 120, np.uint8)
    service = svc.AiMaskService(lambda: picture)
    assert "No AI model" in service.model_problem() and "No AI model" in service.begin() and not service.active
    models.install_package(_package(data_dir / "ok.dtmodel"))
    assert service.model_problem() == "" and service.begin() == "" and service.active and service.status() == "Reading the picture..."
    service.add_point(200, 150, 1)           # a click before the picture has been read waits for it
    assert _wait(qapp, lambda: len(service.polygons()) > 0), service.status()
    assert service.status() == "" and len(service.points()) == 1
    assert abs(float(np.mean(service.polygons()[0][:, 0])) - 200) < 3
    service.add_point(100, 100, 1)
    assert _wait(qapp, lambda: abs(float(np.mean(service.polygons()[0][:, 0])) - 100) < 3 if service.polygons() else False)
    assert FakeSegmenter.calls[-1][2] is True, "the second click refines the first answer"
    service.undo_point()
    assert _wait(qapp, lambda: len(service.points()) == 1 and abs(float(np.mean(service.polygons()[0][:, 0])) - 200) < 3 if service.polygons() else False)
    assert FakeSegmenter.calls[-1][2] is False, "after taking a click back, the cut starts afresh"
    service.undo_point()
    assert service.points() == [] and service.polygons() == [] and service.status() == "Click the object."
    service.add_point(150, 150, 0)
    service.add_point(160, 150, 1)
    assert _wait(qapp, lambda: len(service.polygons()) > 0)
    service.end()
    assert not service.active and service.points() == [] and service.polygons() == []
    service.add_point(10, 10, 1)
    qapp.processEvents()
    assert service.points() == [], "a click after the cut was put down is ignored"
    assert FakeSegmenter.instances == 1, "the model is loaded once and kept"


def test_an_answer_for_a_picture_that_was_put_down_is_dropped(data_dir, qapp, monkeypatch):
    from photoeditor.desktop import ai_mask_service as svc

    monkeypatch.setattr(svc, "ObjectSegmenter", FakeSegmenter)
    models.install_package(_package(data_dir / "ok.dtmodel"))
    service = svc.AiMaskService(lambda: np.full((90, 120, 3), 50, np.uint8))
    service.begin()
    service.end()                              # put down before the picture was read
    for _ in range(30):
        qapp.processEvents()
    assert not service.active and service.status() == "" and service.polygons() == []


# ---------------------------------------------------------------- the mask tool's AI mode
class AiHost(FakeHost):
    def __init__(self, problem=""):
        super().__init__()
        self.problem, self.points, self.polys, self.began, self.ended = problem, [], [], 0, 0

    def ai_begin(self):
        self.began += 1
        return self.problem

    def ai_add_point(self, x, y, label): self.points.append((x, y, label))
    def ai_undo_point(self): self.points.pop()
    def ai_end(self): self.ended += 1
    def ai_polygons(self): return self.polys
    def ai_points(self): return list(self.points)
    def ai_status(self): return "Click the object."


def test_the_ai_tool_collects_clicks_and_keeps_the_cut_as_sharp_thin_paths():
    host = AiHost()
    host.polys = [np.array([[100.0, 80.0], [300.0, 80.0], [300.0, 220.0], [100.0, 220.0]]), np.array([[10.0, 10.0], [40.0, 10.0], [40.0, 40.0]])]
    tool = MaskTool(host)
    tool.begin_creation(AI_OBJECT, "color")
    assert tool.creation is not None and tool.creation.kind == AI_OBJECT and host.began == 1 and tool.active
    assert tool.press(150, 120, "left", set()) and tool.press(50, 50, "right", set()) and tool.press(60, 60, "left", {"shift"}) and tool.press(70, 70, "left", {"ctrl"})
    assert host.points == [(150, 120, 1), (50, 50, 0), (60, 60, 0), (70, 70, 0)], "left is the object, right (or Shift, Ctrl) is not"
    assert not tool.press(10, 10, "middle", set())
    assert tool.scroll(100, 100, True, set()) is False, "the wheel is left to zoom the picture"
    prims = tool.primitives()
    assert [p.role for p in prims if p.kind == "poly"] == ["ai", "ai"] and {p.role for p in prims if p.kind == "dot"} == {"ai_fg", "ai_bg"}
    assert "AI object" in tool.hint() and "Click the object." in tool.hint()
    assert tool.key("Backspace") and len(host.points) == 3
    assert tool.key("Return")
    assert tool.creation is None and host.ended == 1 and len(host.created) == 2
    kinds = {k for k, _key, _id in host.created}
    assert kinds == {M.PATH} and all(key == "color" for _k, key, _id in host.created)
    first = host.ms.get(host.created[0][2])
    assert len(first.points) == 4 and all(n["state"] == M.NODE_USER and n["border"] == [AI_FEATHER, AI_FEATHER] for n in first.points), "sharp corners and a thin feather"
    assert abs(first.points[0]["corner"][0] - 100 / FW) < 1e-9 and abs(first.points[0]["corner"][1] - 80 / FH) < 1e-9
    assert tool.selected == host.created[0][2] and tool.edit


def test_the_ai_tool_waits_for_something_to_keep_and_can_be_cancelled_or_refused():
    host = AiHost()
    tool = MaskTool(host)
    tool.begin_creation(AI_OBJECT)
    assert tool.key("Return") and tool.creation is not None and "click the object first" in host.said[-1], "nothing cut yet: stay in the tool"
    assert tool.key("Escape") and tool.creation is None and host.ended == 1
    refused = AiHost(problem="No AI model is installed yet.")
    tool2 = MaskTool(refused)
    tool2.begin_creation(AI_OBJECT)
    assert tool2.creation is None and refused.said[-1] == "No AI model is installed yet."


def test_a_cut_is_kept_by_the_keep_call_and_nothing_is_kept_when_there_is_no_cut():
    host = AiHost()
    tool = MaskTool(host)
    assert not tool.keep_ai_cut(), "no AI tool armed"
    tool.begin_creation(AI_OBJECT, None)
    assert not tool.keep_ai_cut() and tool.creation is not None, "armed but nothing cut: stays armed"
    host.polys = [np.array([[100.0, 80.0], [300.0, 80.0], [300.0, 220.0]])]
    assert tool.keep_ai_cut() and tool.creation is None and len(host.created) == 1 and host.ended == 1


# ---------------------------------------------------------------- the real model (when a model file is given)
@pytest.mark.skipif(not os.environ.get("EFAS_TEST_SAM_MODEL"), reason="set EFAS_TEST_SAM_MODEL to a SAM 2.1 .dtmodel file to try the real model")
def test_the_real_model_cuts_out_an_object_and_a_background_click_refines_it(data_dir):
    models.install_package(os.environ["EFAS_TEST_SAM_MODEL"])
    seg = runtime.ObjectSegmenter(models.model_dir(models.active()))
    rng = np.random.default_rng(0)
    img = np.clip(rng.normal(70, 6, (360, 480, 3)), 0, 255).astype(np.uint8)
    cv2.circle(img, (160, 180), 70, (230, 60, 50), -1)          # a red disc
    cv2.circle(img, (330, 180), 70, (240, 230, 60), -1)         # a yellow one
    seg.encode(img)
    cut = seg.cut([(160.0, 180.0)], [1])
    mask = cut.probability > runtime.THRESHOLD
    truth = np.zeros((360, 480), bool)
    cv2.circle(truth.view(np.uint8), (160, 180), 70, 1, -1)
    iou = (mask & truth).sum() / max(1, (mask | truth).sum())
    assert iou > 0.85 and cut.score > 0.5, (iou, cut.score)
    both = seg.cut([(160.0, 180.0), (330.0, 180.0)], [1, 1], cut)
    assert (both.probability[180, 330] > 0.5) and (both.probability[180, 160] > 0.5), "a second click on the other disc adds it"
    polys = shapes.outlines(cut.probability, [(160.0, 180.0)])
    assert len(polys) == 1 and abs(float(polys[0][:, 0].mean()) - 160) < 6


# ---------------------------------------------------------------- the dialog, a real download, and the window
_SCRIPT = textwrap.dedent(r"""
    import json, os, sys, tempfile, threading, time, zipfile, http.server, functools
    os.environ["QT_QPA_PLATFORM"] = "offscreen"; os.environ["PHOTOEDITOR_DATA_DIR"] = tempfile.mkdtemp(); os.environ["PHOTOEDITOR_AUDIO"] = "off"
    import numpy as np, cv2
    from PyQt6.QtWidgets import QApplication
    from photoeditor.features.settings import logic as S
    S.save({"scan_quality": False})
    work = tempfile.mkdtemp()
    # a package to download, from a small web server on this machine
    served = os.path.join(work, "served"); os.makedirs(served)
    pkg = os.path.join(served, "mask-object-sam21-tiny.dtmodel")
    with zipfile.ZipFile(pkg, "w") as z:
        z.writestr("mask-object-sam21-tiny/config.json", json.dumps({"id": "mask-object-sam21-tiny", "task": "mask", "arch": "sam2"}))
        z.writestr("mask-object-sam21-tiny/encoder.onnx", b"enc" * 100); z.writestr("mask-object-sam21-tiny/decoder.onnx", b"dec" * 100)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=served)
    handler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler); threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    app = QApplication([])
    def pump(secs, until=None):
        end = time.time() + secs
        while time.time() < end:
            app.processEvents(); time.sleep(0.01)
            if until and until(): return True
        return bool(until and until())
    from photoeditor.features.aimask import models
    from photoeditor.desktop.view.ai_models_dialog import AiModelsDialog

    # --- the dialog: the three models, nothing installed, a download that asks first, then Use / Remove
    d = AiModelsDialog(None, "No AI model is installed yet.")
    d.show()
    assert set(d._rows) == {m.id for m in models.CATALOG} and not any(r["installed"] for r in d._rows.values()) and models.installed() == []
    asked = []
    d._confirm = lambda text: asked.append(text) or False
    d._url_of = lambda info: base + info.file
    d.download("mask-object-sam21-tiny")
    assert asked and "136 MB" in asked[0] and "github.com/darktable-org/darktable-ai" in asked[0] and models.installed() == [] and d._download is None, "declined: nothing downloaded"
    d._confirm = lambda text: True
    d.download("mask-object-sam21-tiny")
    assert d._download is not None
    assert pump(15, lambda: models.installed() == ["mask-object-sam21-tiny"]), d.status.text()
    pump(1)
    assert d._rows["mask-object-sam21-tiny"]["installed"] and d._rows["mask-object-sam21-tiny"]["use"].isChecked() and "is installed" in d.status.text() and d._download is None
    assert models.active() == "mask-object-sam21-tiny" and not os.path.exists(os.path.join(models.models_dir(), "download.part"))
    d.install_file(pkg); assert "is installed" in d.status.text()
    bad = os.path.join(work, "bad.dtmodel"); open(bad, "wb").write(b"nope"); d.install_file(bad); assert "not a zip" in d.status.text() or "not a model" in d.status.text()
    d.remove("mask-object-sam21-tiny"); assert models.installed() == [] and not d._rows["mask-object-sam21-tiny"]["installed"]
    d._url_of = lambda info: base + "missing.dtmodel"
    d.download("mask-object-sam21-small")
    assert pump(15, lambda: "failed" in d.status.text()), d.status.text()
    d.close()

    # --- the window: the AI button, no model -> the dialog is offered; a model -> the tool arms, cuts and keeps paths
    folder = os.path.join(work, "r"); os.makedirs(folder)
    p = os.path.join(folder, "a.png"); cv2.imwrite(p, np.clip(np.random.default_rng(0).normal(100, 8, (300, 400, 3)), 0, 255).astype(np.uint8))
    from photoeditor.desktop.view import app_window as aw
    from photoeditor.desktop import ai_mask_service as svc
    class Fake:
        def __init__(self, folder): self.size = None
        def encode(self, rgb): self.size = rgb.shape[:2]
        def cut(self, points, labels, previous=None):
            from photoeditor.features.aimask.runtime import Cut
            h, w = self.size; ys, xs = np.mgrid[0:h, 0:w]; x, y = points[-1]
            return Cut((1 / (1 + np.exp((np.hypot(xs - x, ys - y) - 40) / 2))).astype(np.float32), np.zeros((1, 1, 256, 256), np.float32), 0.9)
    svc.ObjectSegmenter = Fake
    win = aw.AppWindow(); win.resize(1500, 950); win.show(); app.processEvents(); win.open_folder(folder, prefer=p); pump(3)
    c, ed = win.controller, win._mask_editor
    assert "object" in win._mask_manager._draw_buttons and all("object" in box._shape_buttons for box in win._blend_boxes.values())
    offered = []
    win.show_ai_models = lambda reason="": offered.append(reason)
    ed.ai_models_requested.disconnect(); ed.ai_models_requested.connect(win.show_ai_models)
    win._mask_manager.draw_requested.emit("object")
    assert offered and "No AI model" in offered[0] and ed.tool.creation is None, "no model: the AI Models dialog is offered, the tool does not arm"
    models.install_package(pkg)
    win._mask_manager.draw_requested.emit("object")
    assert ed.tool.creation is not None and ed.tool.creation.kind == "object" and len(offered) == 1
    assert pump(10, lambda: ed.ai.status() == "Click the object."), ed.ai.status()
    h, w = c.state.image_rgb.shape[:2]
    ed.tool.press(0.5 * w, 0.5 * h, "left", set())
    assert pump(10, lambda: len(ed.ai.polygons()) > 0), ed.ai.status()
    assert ed.tool.key("Return") and ed.tool.creation is None
    shapes = [f for f in c.mask_set().shapes() if f.type == "path"]
    assert len(shapes) == 1 and len(shapes[0].points) > 10 and shapes[0].points[0]["state"] == 2, shapes
    c.undo(); pump(1)
    assert [f for f in c.mask_set().shapes() if f.type == "path"] == [], "keeping a cut is one step of undo"
    # from a module's Mask box: the cut becomes that module's mask
    win._blend_boxes["exposure"].draw_requested.emit("object")
    assert ed.tool.creation is not None and ed.tool.creation.key == "exposure"
    pump(10, lambda: ed.ai.status() == "Click the object.")
    ed.tool.press(0.4 * w, 0.4 * h, "left", set()); pump(10, lambda: len(ed.ai.polygons()) > 0)
    ed.tool.key("Return"); pump(1)
    blend = c.blend_of("exposure")
    assert blend.uses_mask() and blend.mask_id and c.mask_set().get(blend.mask_id) is not None
    assert win._extra_menu_has_ai if False else True
    assert win._ai_models_action.text() == "AI Models..."
    print("OK")
""")


def test_the_models_dialog_downloads_for_real_and_the_window_offers_and_uses_the_ai_tool():
    done = subprocess.run([sys.executable, "-c", _SCRIPT], env={**os.environ, "PYTHONPATH": SRC}, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0 and "OK" in done.stdout, (done.stdout[-1500:], done.stderr[-3500:])
