"""The Canon backend against a stand-in for Canon's EDSDK: the order of calls, live view and its hand-back, retries, the lens drive, and the shutter with its downloads.

The stand-in is a Python object with the SDK's function names that behaves like a camera. That proves EFAS makes the right calls in the right order and copes with what the SDK is
known to do (a live picture that is not ready, a busy camera, one release announcing a RAW and a JPEG, a file announced twice). It does not prove Canon's real library agrees with
the signatures declared in edsdk_api.py: only a real camera does that."""
import ctypes
import os
import sys
import time
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from photoeditor.features.tether import edsdk_api as api
from photoeditor.features.tether import edsdk_camera as cam_mod
from photoeditor.features.tether.backend import TetherError
from photoeditor.features.tether.edsdk_errors import EdsError, HINTS, name_of

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the Canon backend runs on Windows only so far")


def put(arg, value):
    """Set what a byref(...) argument points at."""
    arg._obj.value = value


def val(x):
    return x.value if hasattr(x, "value") else x


def _jpeg(shade=100):
    ok, data = cv2.imencode(".jpg", np.full((48, 64, 3), shade, np.uint8))
    assert ok
    return data.tobytes()


class FakeEdsdk:
    """Behaves like an EDSDK with one camera on it."""

    def __init__(self, cameras=1, lens=1, af_mode=1, busy_sets=0, not_ready=2, shutter_refused=False, drive_error=0, items=None, announce_twice=False, fail_download=()):
        self.cameras, self.lens, self.af_mode, self.busy_sets, self.not_ready = cameras, lens, af_mode, busy_sets, not_ready
        self.shutter_refused, self.drive_error, self.announce_twice, self.fail_download = shutter_refused, drive_error, announce_twice, set(fail_download)
        self.shot_items = items if items is not None else [("IMG_0042.CR3", b"RAW" * 100, 1111), ("IMG_0042.JPG", b"JPG" * 50, 1111)]
        self.props = {api.PROP_EVF_OUTPUT_DEVICE: api.EVF_OUTPUT_TFT, api.PROP_LENS_STATUS: lens, api.PROP_AF_MODE: af_mode,
                      api.PROP_AE_MODE: 3, api.PROP_ISO: 0x48, api.PROP_AV: 0x38, api.PROP_TV: 0x68, api.PROP_EXPOSURE_COMP: 0}
        self.descs = {api.PROP_ISO: [0x48, 0x50, 0x58], api.PROP_AV: [0x38, 0x30], api.PROP_TV: [0x68, 0x60, 0x58], api.PROP_EXPOSURE_COMP: []}   # what each property will take just now
        self.calls, self.released, self.commands = [], [], []
        self.handler = None
        self._next = 5000
        self._streams, self._evf, self._items = {}, {}, {}
        self._evf_calls = 0
        self._frame_shade = 100

    def _handle(self):
        self._next += 1
        return self._next

    # lifecycle
    def EdsInitializeSDK(self):
        self.calls.append("init")
        return 0

    def EdsTerminateSDK(self):
        self.calls.append("terminate")
        return 0

    def EdsGetCameraList(self, p):
        put(p, 1000)
        return 0

    def EdsGetChildCount(self, ref, p):
        put(p, self.cameras)
        return 0

    def EdsGetChildAtIndex(self, ref, index, p):
        put(p, 2000)
        return 0

    def EdsRelease(self, ref):
        self.released.append(val(ref))
        return 0

    def EdsOpenSession(self, cam):
        self.calls.append("open session")
        return 0

    def EdsCloseSession(self, cam):
        self.calls.append("close session")
        return 0

    # properties
    def EdsGetPropertyData(self, ref, prop, param, size, data):
        if prop == api.PROP_PRODUCT_NAME:
            ctypes.memmove(data, b"Canon EOS R7\0", 13)
        elif prop == api.PROP_LENS_NAME:
            ctypes.memmove(data, b"RF100mm F2.8 L MACRO IS USM\0", 28)
        elif prop == api.PROP_EVF_COORDINATE_SYSTEM and prop in self.props:
            data._obj.width, data._obj.height = self.props[prop]
        elif prop in self.props:
            put(data, self.props[prop])
        else:
            return 0x0000200A
        return 0

    def EdsGetPropertyDesc(self, ref, prop, p):
        desc = p._obj
        codes = self.descs.get(prop, [])
        desc.numElements = len(codes)
        for i, code in enumerate(codes):
            desc.propDesc[i] = code
        return 0

    def EdsSetPropertyData(self, ref, prop, param, size, data):
        if self.busy_sets > 0:
            self.busy_sets -= 1
            return 0x00000081
        obj = data._obj
        value = obj.value if hasattr(obj, "value") else (obj.x, obj.y)
        self.props[prop] = value
        self.calls.append(("set", prop, value))
        return 0

    def EdsSetCapacity(self, cam, capacity):
        self.calls.append(("capacity", capacity.numberOfFreeClusters, capacity.reset))
        return 0

    def EdsSetObjectEventHandler(self, cam, events, handler, context):
        self.handler = handler
        return 0

    # live view
    def EdsCreateMemoryStream(self, size, p):
        h = self._handle()
        self._streams[h] = None
        put(p, h)
        return 0

    def EdsCreateEvfImageRef(self, stream, p):
        h = self._handle()
        self._evf[h] = val(stream)
        put(p, h)
        return 0

    def EdsDownloadEvfImage(self, cam, evf):
        if not self.props.get(api.PROP_EVF_OUTPUT_DEVICE, 0) & api.EVF_OUTPUT_PC:
            return 0x00002003
        self._evf_calls += 1
        if self._evf_calls <= self.not_ready:
            return 0x0000A102
        data = _jpeg(self._frame_shade + self._evf_calls % 50)
        self._streams[self._evf[val(evf)]] = (ctypes.create_string_buffer(data), len(data))
        return 0

    def EdsGetLength(self, stream, p):
        put(p, self._streams[val(stream)][1])
        return 0

    def EdsGetPointer(self, stream, p):
        put(p, ctypes.addressof(self._streams[val(stream)][0]))
        return 0

    # commands
    def EdsSendCommand(self, cam, command, param):
        self.commands.append((command, param))
        if command == api.CMD_DRIVE_LENS_EVF:
            return self.drive_error
        if command == api.CMD_PRESS_SHUTTER_BUTTON and param == api.SHUTTER_COMPLETELY_NON_AF:
            if self.shutter_refused:
                return 0x0000A005
            self._announce()
        elif command == api.CMD_TAKE_PICTURE:
            self._announce()
        return 0

    def _announce(self):
        for name, data, when in self.shot_items:
            h = self._handle()
            self._items[h] = (name, data, when)
            self.handler(api.OBJECT_EVENT_DIR_ITEM_REQUEST_TRANSFER, h, None)
            if self.announce_twice:
                h2 = self._handle()
                self._items[h2] = (name, data, when)
                self.handler(api.OBJECT_EVENT_DIR_ITEM_CREATED, h2, None)

    # downloads
    def EdsGetDirectoryItemInfo(self, item, p):
        name, data, when = self._items[val(item)]
        info = p._obj
        info.size, info.szFileName, info.dateTime = len(data), name.encode(), when
        return 0

    def EdsCreateFileStreamEx(self, path, disposition, access, p):
        h = self._handle()
        self._streams[h] = path
        open(path, "wb").close()
        put(p, h)
        return 0

    def EdsDownload(self, item, size, stream):
        name, data, _when = self._items[val(item)]
        if name in self.fail_download:
            return 0x0000002A
        with open(self._streams[val(stream)], "wb") as fh:
            fh.write(data)
        return 0

    def EdsDownloadComplete(self, item):
        self.commands.append(("download complete", self._items[val(item)][0]))
        return 0

    def EdsDownloadCancel(self, item):
        self.commands.append(("download cancel", self._items[val(item)][0]))
        return 0


@pytest.fixture
def quick(monkeypatch):
    """Short waits, so the failures that depend on time-outs take a moment and not a minute."""
    monkeypatch.setattr(cam_mod, "FILE_WAIT_S", 0.6)
    monkeypatch.setattr(cam_mod, "EXTRA_FILE_GRACE_S", 0.05)
    monkeypatch.setattr(cam_mod, "BUSY_RETRY_S", 1.0)
    monkeypatch.setattr(cam_mod, "START_TIMEOUT_S", 10.0)


def opened(fake, tmp_path=None):
    camera = cam_mod.EdsdkCamera("stand-in", loader=lambda folder: fake)
    camera.open()
    return camera


def wait_for_picture(camera, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        seq, jpeg = camera.live_frame()
        if jpeg is not None:
            return seq, jpeg
        time.sleep(0.01)
    raise AssertionError("no live picture arrived")


# ---------------------------------------------------------------- the session
def test_it_connects_starts_live_view_and_hands_the_camera_back(quick):
    fake = FakeEdsdk()
    camera = opened(fake)
    try:
        assert camera.info.model == "Canon EOS R7" and camera.info.lens.startswith("RF100mm") and camera.capabilities.focus_drive
        assert fake.props[api.PROP_EVF_OUTPUT_DEVICE] == api.EVF_OUTPUT_TFT | api.EVF_OUTPUT_PC, "the picture goes to the computer and stays on the camera's screen too"
        seq, jpeg = wait_for_picture(camera)
        assert seq > 0 and jpeg[:2] == b"\xff\xd8"
        assert fake.calls[:2] == ["init", "open session"] and fake.handler is not None
    finally:
        camera.close()
    assert not fake.props[api.PROP_EVF_OUTPUT_DEVICE] & api.EVF_OUTPUT_PC and fake.props[api.PROP_EVF_OUTPUT_DEVICE] & api.EVF_OUTPUT_TFT, "the camera's own screen gets its picture back"
    assert fake.calls[-2:] == ["close session", "terminate"] and 2000 in fake.released and 1000 in fake.released, "the session is closed and every handle let go"
    camera.close()   # twice is fine


def test_live_pictures_keep_arriving_and_not_ready_is_normal(quick):
    fake = FakeEdsdk(not_ready=6)
    camera = opened(fake)
    try:
        first = wait_for_picture(camera)
        time.sleep(0.15)
        second = camera.live_frame()
        assert second[0] > first[0], "newer pictures keep coming"
    finally:
        camera.close()


def test_no_camera_found_says_what_to_check_and_cleans_up(quick):
    fake = FakeEdsdk(cameras=0)
    camera = cam_mod.EdsdkCamera("stand-in", loader=lambda folder: fake)
    with pytest.raises(TetherError, match="No camera was found.*Wi-Fi.*EOS Utility"):
        camera.open()
    assert "terminate" in fake.calls and 1000 in fake.released
    camera.close()


def test_a_camera_that_says_busy_is_asked_again(quick):
    fake = FakeEdsdk(busy_sets=2)
    camera = opened(fake)
    try:
        assert fake.props[api.PROP_EVF_OUTPUT_DEVICE] & api.EVF_OUTPUT_PC
    finally:
        camera.close()


def test_the_sdk_not_loading_is_reported_and_the_camera_can_be_asked_again(quick):
    def broken(folder):
        raise TetherError("Canon's EDSDK was not found.")

    camera = cam_mod.EdsdkCamera("nowhere", loader=broken)
    with pytest.raises(TetherError, match="not found"):
        camera.open()
    with pytest.raises(TetherError, match="not connected"):
        camera.focus("near")
    with pytest.raises(TetherError, match="not connected"):
        camera.shoot("x", lambda n: n, 0)


# ---------------------------------------------------------------- the lens
def test_the_lens_is_driven_in_the_chosen_size_and_direction(quick):
    fake = FakeEdsdk()
    camera = opened(fake)
    try:
        camera.focus("near", 1, 2)
        camera.focus("far", 3, 1)
        camera.focus("far", 9, 1)   # a size past the coarsest is held to the coarsest
        drives = [p for c, p in fake.commands if c == api.CMD_DRIVE_LENS_EVF]
        assert drives == [api.DRIVE_NEAR[1], api.DRIVE_NEAR[1], api.DRIVE_FAR[3], api.DRIVE_FAR[3]]
        with pytest.raises(ValueError):
            camera.focus("up")
    finally:
        camera.close()


def test_a_lens_that_cannot_be_driven_says_why_and_a_refusal_is_explained(quick):
    manual = FakeEdsdk(af_mode=api.AF_MODE_MANUAL)
    camera = opened(manual)
    try:
        assert not camera.capabilities.focus_drive and "AF/MF" in camera.capabilities.note("focus_drive")
        with pytest.raises(TetherError, match="cannot be focused from the computer.*AF/MF"):
            camera.focus("near")
    finally:
        camera.close()
    nolens = FakeEdsdk(lens=0)
    camera = opened(nolens)
    try:
        assert not camera.capabilities.focus_drive and "No lens" in camera.capabilities.note("focus_drive")
    finally:
        camera.close()
    refusing = FakeEdsdk(drive_error=0x00000007)
    camera = opened(refusing)
    try:
        with pytest.raises(EdsError, match="NOT_SUPPORTED.*does not support"):
            camera.focus("far", 2, 1)
        camera.live_frame()   # the camera thread is still alive after a refused command
    finally:
        camera.close()


# ---------------------------------------------------------------- the shutter
def names(prefix):
    return lambda camera_name: prefix + os.path.splitext(camera_name)[1]


def test_a_shot_is_saved_to_the_computer_and_every_file_gets_its_name(quick, tmp_path):
    fake = FakeEdsdk()
    camera = opened(fake)
    try:
        folder = str(tmp_path / "roll")
        paths = camera.shoot(folder, names("scan_0001"), 0.0)
    finally:
        camera.close()
    assert sorted(os.path.basename(p) for p in paths) == ["scan_0001.CR3", "scan_0001.JPG"]
    assert open(os.path.join(folder, "scan_0001.CR3"), "rb").read() == b"RAW" * 100 and open(os.path.join(folder, "scan_0001.JPG"), "rb").read() == b"JPG" * 50
    assert ("set", api.PROP_SAVE_TO, api.SAVE_TO_HOST) in fake.calls, "saved to the computer, not the card"
    assert ("capacity", 0x7FFFFFFF, 1) in fake.calls, "the camera is told the computer has room, or it will not shoot"
    presses = [(c, p) for c, p in fake.commands if c == api.CMD_PRESS_SHUTTER_BUTTON]
    assert presses == [(api.CMD_PRESS_SHUTTER_BUTTON, api.SHUTTER_COMPLETELY_NON_AF), (api.CMD_PRESS_SHUTTER_BUTTON, api.SHUTTER_OFF)], "pressed without focusing, then released"
    assert [c for c in fake.commands if c[0] == "download complete"] == [("download complete", "IMG_0042.CR3"), ("download complete", "IMG_0042.JPG")]


def test_a_shot_never_overwrites_a_file_and_the_settle_time_is_waited(quick, tmp_path):
    (tmp_path / "scan_0001.CR3").write_bytes(b"precious")
    fake = FakeEdsdk()
    camera = opened(fake)
    try:
        started = time.perf_counter()
        paths = camera.shoot(str(tmp_path), names("scan_0001"), 0.3)
        assert time.perf_counter() - started >= 0.3
    finally:
        camera.close()
    assert (tmp_path / "scan_0001.CR3").read_bytes() == b"precious"
    assert sorted(os.path.basename(p) for p in paths) == ["scan_0001-1.CR3", "scan_0001.JPG"]


def test_a_file_the_camera_announces_twice_is_saved_once(quick, tmp_path):
    fake = FakeEdsdk(announce_twice=True)
    camera = opened(fake)
    try:
        paths = camera.shoot(str(tmp_path), names("scan_0002"), 0.0)
    finally:
        camera.close()
    assert sorted(os.path.basename(p) for p in paths) == ["scan_0002.CR3", "scan_0002.JPG"] and sorted(os.listdir(tmp_path)) == ["scan_0002.CR3", "scan_0002.JPG"]


def test_a_body_that_refuses_the_shutter_button_is_sent_take_picture(quick, tmp_path):
    fake = FakeEdsdk(shutter_refused=True)
    camera = opened(fake)
    try:
        paths = camera.shoot(str(tmp_path), names("scan_0003"), 0.0)
    finally:
        camera.close()
    assert len(paths) == 2 and (api.CMD_TAKE_PICTURE, 0) in fake.commands


def test_one_file_that_cannot_be_saved_does_not_lose_the_others_and_leaves_no_half_file(quick, tmp_path):
    fake = FakeEdsdk(fail_download={"IMG_0042.JPG"})
    camera = opened(fake)
    try:
        paths = camera.shoot(str(tmp_path), names("scan_0004"), 0.0)
        assert [os.path.basename(p) for p in paths] == ["scan_0004.CR3"] and sorted(os.listdir(tmp_path)) == ["scan_0004.CR3"], "the JPEG's half-made file is removed"
        assert ("download cancel", "IMG_0042.JPG") in fake.commands
    finally:
        camera.close()
    broken = FakeEdsdk(fail_download={"IMG_0042.JPG", "IMG_0042.CR3"})
    camera = opened(broken)
    try:
        with pytest.raises(TetherError, match="None of the files.*FILE_DISK_FULL_ERROR|None of the files.*disk is full"):
            camera.shoot(str(tmp_path / "again"), names("scan_0005"), 0.0)
        assert os.listdir(tmp_path / "again") == []
    finally:
        camera.close()


def test_a_shutter_that_announces_nothing_is_an_error_and_not_a_hang(quick, tmp_path):
    fake = FakeEdsdk(items=[])
    camera = opened(fake)
    try:
        started = time.perf_counter()
        with pytest.raises(TetherError, match="did not report a file"):
            camera.shoot(str(tmp_path), names("x"), 0.0)
        assert time.perf_counter() - started < 5
        camera.live_frame()   # still alive
    finally:
        camera.close()


def test_nothing_can_be_asked_of_a_camera_that_has_been_closed(quick, tmp_path):
    camera = opened(FakeEdsdk())
    camera.close()
    with pytest.raises(TetherError, match="not connected"):
        camera.focus("near")
    with pytest.raises(TetherError, match="not connected"):
        camera.shoot(str(tmp_path), names("x"), 0.0)


# ---------------------------------------------------------------- finding and declaring the SDK
def test_the_library_is_found_in_the_folder_or_in_canons_own_unpacked_folders(tmp_path):
    assert api.find_library("") == "" and api.find_library(str(tmp_path / "missing")) == ""
    assert api.find_library(str(tmp_path)) == ""
    for sub in ("EDSDK/Dll", "EDSDK_64/Dll", "Docs"):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / "EDSDK/Dll/EDSDK.dll").write_bytes(b"x")
    (tmp_path / "EDSDK_64/Dll/EDSDK.dll").write_bytes(b"x")
    assert api.find_library(str(tmp_path)).replace("\\", "/").endswith("EDSDK_64/Dll/EDSDK.dll"), "the 64-bit copy is preferred"
    direct = tmp_path / "EDSDK_64" / "Dll"
    assert api.find_library(str(direct)) == str(direct / "EDSDK.dll"), "or the folder that holds it, chosen directly"
    with pytest.raises(TetherError, match="cannot include it"):
        api.load(str(tmp_path / "nothing"))


def test_every_function_gets_its_types_declared():
    dll = MagicMock()
    api.declare(dll)
    assert dll.EdsOpenSession.restype is ctypes.c_uint32 and dll.EdsSendCommand.argtypes == [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32]
    assert dll.EdsCreateFileStreamEx.argtypes[0] is ctypes.c_wchar_p, "a wide string, so a folder with accents works"
    assert dll.EdsSetObjectEventHandler.argtypes[2] is api.ObjectEventHandler
    assert dll.EdsGetDirectoryItemInfo.argtypes[1]._type_ is api.DirectoryItemInfo
    assert ctypes.sizeof(api.DirectoryItemInfo) >= 8 + 4 + 4 + 4 + 256 + 4 + 4


def test_errors_say_what_happened_and_what_to_do():
    err = EdsError("EdsOpenSession", 0x000000C1)
    assert "COMM_DISCONNECTED" in str(err) and "USB cable" in str(err) and err.code == 0xC1
    assert name_of(0x1234) == "UNKNOWN_0x00001234" and name_of(0x81) == "DEVICE_BUSY"
    assert all(code in __import__("photoeditor.features.tether.edsdk_errors", fromlist=["NAMES"]).NAMES for code in HINTS if code != 0)


# ---------------------------------------------------------------- exposure
def test_exposure_is_read_from_the_camera_and_set_only_to_what_it_offers(quick):
    fake = FakeEdsdk()
    camera = opened(fake)
    try:
        assert camera.capabilities.exposure
        state = camera.exposure()
        assert state.mode == "M" and state.values == {"iso": 0x48, "av": 0x38, "tv": 0x68, "comp": 0}, state
        assert state.choices["tv"] == (0x68, 0x60, 0x58) and state.can_set("tv") and not state.can_set("comp"), "a property the camera will not change offers nothing"
        camera.set_exposure("tv", 0x60)
        assert ("set", api.PROP_TV, 0x60) in fake.calls and camera.exposure().values["tv"] == 0x60
        with pytest.raises(TetherError, match="will not take"):
            camera.set_exposure("tv", 0x20)
        fake.props[api.PROP_AE_MODE] = 2    # the dial is on Av: the camera sets the shutter itself and offers no choice
        fake.descs[api.PROP_TV] = []
        assert camera.exposure().mode == "Av"
        with pytest.raises(TetherError, match="Av mode.*dial to M"):
            camera.set_exposure("tv", 0x60)
        with pytest.raises(ValueError):
            camera.set_exposure("flash", 1)
    finally:
        camera.close()
    assert camera.exposure() is None, "closed: nothing to ask"


# ---------------------------------------------------------------- the camera's own live view zoom
def test_the_live_picture_can_be_zoomed_on_the_camera_to_5_and_10_times(quick):
    fake = FakeEdsdk()
    fake.props[api.PROP_EVF_ZOOM] = 1
    camera = opened(fake)
    try:
        assert camera.capabilities.zoom
        camera.set_zoom(5)
        assert ("set", api.PROP_EVF_ZOOM, 5) in fake.calls and fake.props[api.PROP_EVF_ZOOM] == 5
        camera.set_zoom(10); camera.set_zoom(1)
        assert fake.props[api.PROP_EVF_ZOOM] == 1
        with pytest.raises(ValueError):
            camera.set_zoom(7)
    finally:
        camera.close()


def test_the_zoom_is_offered_even_when_the_body_does_not_answer_for_it_until_live_view_runs(quick):
    fake = FakeEdsdk()      # (no Evf_Zoom property to read before live view: the buttons still work, the camera is simply asked)
    camera = opened(fake)
    try:
        assert camera.capabilities.zoom
        camera.set_zoom(5)
        assert fake.props[api.PROP_EVF_ZOOM] == 5
    finally:
        camera.close()


def test_a_camera_that_refuses_the_zoom_says_what_it_answered(quick):
    fake = FakeEdsdk()
    original = fake.EdsSetPropertyData
    fake.EdsSetPropertyData = lambda ref, prop, param, size, data: 0x0000A005 if prop == api.PROP_EVF_ZOOM else original(ref, prop, param, size, data)
    camera = opened(fake)
    try:
        with pytest.raises(TetherError, match="Evf_Zoom.*OPERATION_REFUSED"):
            camera.set_zoom(5)
    finally:
        camera.close()


def test_a_zoom_frame_that_cannot_be_moved_says_why_and_a_move_alone_does_not_rewrite_the_zoom(quick):
    fake = FakeEdsdk()
    fake.props[api.PROP_EVF_ZOOM] = 1
    camera = opened(fake)      # (no coordinate system on this body)
    try:
        camera.set_zoom(5)
        with pytest.raises(TetherError, match="size of its live picture.*Evf_CoordinateSystem"):
            camera.set_zoom(5, (0.2, 0.5))
        fake.props[api.PROP_EVF_COORDINATE_SYSTEM] = (5000, 3000)
        before = [c for c in fake.calls if c[:2] == ("set", api.PROP_EVF_ZOOM)]
        camera.set_zoom(5, (0.3, 0.5))
        assert [c for c in fake.calls if c[:2] == ("set", api.PROP_EVF_ZOOM)] == before, "already at 5x: only the position is written"
        assert fake.props[api.PROP_EVF_ZOOM_POSITION] == (1000, 1200)
        original = fake.EdsSetPropertyData
        fake.EdsSetPropertyData = lambda ref, prop, param, size, data: 0x0000A005 if prop == api.PROP_EVF_ZOOM_POSITION else original(ref, prop, param, size, data)
        with pytest.raises(TetherError, match="Evf_ZoomPosition.*OPERATION_REFUSED"):
            camera.set_zoom(5, (0.6, 0.5))
    finally:
        camera.close()


def test_the_zoom_frame_can_be_moved_to_another_part_of_the_picture(quick):
    fake = FakeEdsdk()
    fake.props[api.PROP_EVF_ZOOM] = 1
    fake.props[api.PROP_EVF_COORDINATE_SYSTEM] = (5000, 3000)
    camera = opened(fake)
    try:
        camera.set_zoom(5, (0.5, 0.5))
        assert fake.props[api.PROP_EVF_ZOOM_POSITION] == (2000, 1200), "a fifth of the picture, centred"
        camera.set_zoom(5, (0.0, 1.0))
        assert fake.props[api.PROP_EVF_ZOOM_POSITION] == (0, 2400), "held inside the picture"
        camera.set_zoom(10, (0.95, 0.5))
        assert fake.props[api.PROP_EVF_ZOOM_POSITION] == (4500, 1350)
    finally:
        camera.close()
