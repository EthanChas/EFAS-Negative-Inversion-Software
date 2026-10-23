"""A Canon camera over USB through Canon's EDSDK: live picture, lens drive, shutter and download. No Qt.

EDSDK is not thread-safe and delivers its events (a file is ready, say) as Windows messages to the thread that started it, so one thread of ours owns the SDK for the whole
session: it starts it, keeps pumping messages, pulls live pictures, and does whatever the rest of the program asks of it, one thing at a time. Everything else submits a function
and waits for the answer. A thread that stops pumping messages stops the events, and then a capture never completes; that is why every wait here pumps.

Only Windows is wired up so far. Elsewhere EDSDK would want its events collected a different way (and, on a Mac, found from the main thread), which has not been done or tried.
"""

import ctypes
import logging
import os
import queue
import sys
import threading
import time
from concurrent.futures import Future
from ctypes import byref, c_char, c_uint32, c_uint64, c_void_p

from . import edsdk_api as api
from . import exposure as ex
from .backend import CameraInfo, Capabilities, NameFor, TetherError
from .naming import unique_path
from .edsdk_errors import EDS_ERR_DEVICE_BUSY, EDS_ERR_OBJECT_NOTREADY, EDS_ERR_OK, EDS_ERR_PTP_DEVICE_BUSY, EdsError, check, name_of

if sys.platform == "win32":
    from ctypes import wintypes

log = logging.getLogger(__name__)

BUSY_RETRY_S = 4.0       # a call refused as busy is retried this long: with live view running the camera is mid-transfer much of the time, and the refusal is passing
COMMAND_TIMEOUT_S = 30.0
SHOOT_TIMEOUT_S = 150.0
FILE_WAIT_S = 60.0       # how long after the shutter a file may take to be announced
EXTRA_FILE_GRACE_S = 1.5  # RAW and JPEG are announced one after the other: stop waiting only this long after the last
START_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 15.0
COINIT_APARTMENTTHREADED = 0x2


def pump(dll=None) -> None:
    """Deliver the SDK's waiting events to this thread. Without it nothing the camera reports ever arrives."""
    if sys.platform == "win32":
        msg = wintypes.MSG()
        user32 = ctypes.windll.user32
        while user32.PeekMessageW(byref(msg), None, 0, 0, 1):   # 1 = remove it from the queue
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))
    elif dll is not None and getattr(dll, "EdsGetEvent", None) is not None:
        dll.EdsGetEvent()


class EdsdkCamera:
    """The CameraBackend for a Canon body. `loader` gives the SDK library for a folder (a test gives a stand-in for it)."""

    def __init__(self, library_dir: str, loader=api.load, frames_per_second: int = 30):
        self._library_dir = library_dir
        self._loader = loader
        self._interval = 1.0 / max(1, frames_per_second)
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._ready = threading.Event()
        self._start_error: BaseException | None = None
        self._thread_error: BaseException | None = None
        self._frame_lock = threading.Lock()
        self._frame: bytes | None = None
        self._seq = 0
        # touched only by the camera thread
        self._dll = None
        self._camera: c_void_p | None = None
        self._streaming = False
        self._info = CameraInfo("(not connected)", backend="Canon EDSDK")
        self._caps = Capabilities()
        self._handler = None            # kept alive for as long as the SDK may call it
        self._announced: list[int] = []   # files the camera has announced and we have not fetched

    # ------------------------------------------------------------ public
    @property
    def info(self) -> CameraInfo:
        return self._info

    @property
    def capabilities(self) -> Capabilities:
        return self._caps

    def open(self) -> None:
        if sys.platform != "win32":
            raise TetherError(f"Tethering a Canon camera works on Windows only so far, not on {sys.platform}. The practice camera works everywhere.")
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping.clear()
        self._ready.clear()
        self._start_error = self._thread_error = None
        self._thread = threading.Thread(target=self._run, name="efas-canon-camera", daemon=True)
        self._thread.start()
        if not self._ready.wait(START_TIMEOUT_S):
            self._stopping.set()
            raise TetherError("The camera did not answer within 30 seconds.")
        if self._start_error is not None:
            raise self._start_error

    def close(self) -> None:
        self._stopping.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(STOP_TIMEOUT_S)
            if thread.is_alive():
                log.error("The camera thread did not stop.")
        self._thread = None

    def live_frame(self) -> tuple[int, bytes | None]:
        if self._thread_error is not None:
            raise TetherError(f"The camera connection ended: {self._thread_error}")
        with self._frame_lock:
            return self._seq, self._frame

    def focus(self, direction: str, size: int = 2, steps: int = 1) -> None:
        if direction not in ("near", "far"):
            raise ValueError(f"direction is 'near' or 'far', not {direction!r}")
        self._require_open()
        if not self._caps.focus_drive:
            raise TetherError("This lens cannot be focused from the computer. " + self._caps.note("focus_drive"))
        self._submit(lambda: self._drive_lens(direction, size, steps), "focus")

    def set_zoom(self, level: int) -> None:
        if int(level) not in api.EVF_ZOOMS:
            raise ValueError(f"level is one of {', '.join(str(z) for z in api.EVF_ZOOMS)}, not {level!r}")
        self._require_open()
        if not self._caps.zoom:
            raise TetherError("This camera does not offer a zoomed live picture to the computer. Zoom on the camera itself, or use the Zoom slider here, which only enlarges the pixels it has.")
        self._submit(lambda: self._write_number(api.PROP_EVF_ZOOM, int(level), "Evf_Zoom"), "zoom the live picture")

    def exposure(self) -> ex.ExposureState | None:
        if self._thread is None or not self._thread.is_alive():
            return None
        return self._submit(self._read_exposure, "read the exposure")

    def set_exposure(self, key: str, code: int) -> None:
        if key not in self._EXPOSURE_PROPS:
            raise ValueError(f"key is one of {', '.join(self._EXPOSURE_PROPS)}, not {key!r}")
        self._submit(lambda: self._write_exposure(key, int(code)), "set the " + ex.TITLES[key].lower())

    def shoot(self, folder: str, name_for: NameFor, settle_s: float = 1.0) -> list[str]:
        return self._submit(lambda: self._shoot(folder, name_for, max(0.0, float(settle_s))), "shoot", SHOOT_TIMEOUT_S)

    # ------------------------------------------------------------ running on the camera thread
    def _require_open(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            raise TetherError("The camera is not connected.")

    def _submit(self, fn, label: str, timeout: float = COMMAND_TIMEOUT_S):
        self._require_open()
        done: Future = Future()
        self._jobs.put((fn, done))
        try:
            return done.result(timeout)
        except TimeoutError as exc:
            raise TetherError(f"The camera did not finish '{label}' within {timeout:.0f} seconds.") from exc

    def _run(self) -> None:
        try:
            self._setup()
        except BaseException as exc:
            self._start_error = exc
            self._ready.set()
            self._teardown()
            return
        self._ready.set()
        try:
            self._loop()
        except BaseException as exc:   # the loop is gone: say why, so callers do not wait on nothing
            self._thread_error = exc
            log.exception("The camera thread failed")
        finally:
            self._teardown()
            self._fail_waiting(self._thread_error)

    def _loop(self) -> None:
        due = time.perf_counter()
        while not self._stopping.is_set():
            pump(self._dll)
            self._run_jobs()
            now = time.perf_counter()
            if self._streaming and now >= due:
                if self._pull_frame():
                    due = now + self._interval
            else:
                time.sleep(0.002)

    def _run_jobs(self) -> None:
        while True:
            try:
                fn, done = self._jobs.get_nowait()
            except queue.Empty:
                return
            if not done.set_running_or_notify_cancel():
                continue
            try:
                done.set_result(fn())
            except BaseException as exc:   # handed back to whoever asked
                done.set_exception(exc)

    def _fail_waiting(self, error: BaseException | None) -> None:
        failure = error or TetherError("The camera connection ended.")
        while True:
            try:
                _fn, done = self._jobs.get_nowait()
            except queue.Empty:
                return
            if not done.done():
                done.set_exception(failure)

    def _setup(self) -> None:
        if sys.platform == "win32":
            hr = ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
            if hr < 0:
                raise TetherError(f"Windows could not prepare the camera thread (0x{hr & 0xFFFFFFFF:08X}).")
        self._dll = self._loader(self._library_dir)
        check("EdsInitializeSDK", self._dll.EdsInitializeSDK())
        cameras = c_void_p()
        check("EdsGetCameraList", self._dll.EdsGetCameraList(byref(cameras)))
        try:
            count = c_uint32()
            check("EdsGetChildCount", self._dll.EdsGetChildCount(cameras, byref(count)))
            if count.value == 0:
                raise TetherError("No camera was found. Check that the USB cable carries data, the camera is on and awake, its Wi-Fi and Bluetooth are off, "
                                  "and no other program (EOS Utility, Lightroom, a phone app) has hold of it.")
            camera = c_void_p()
            check("EdsGetChildAtIndex", self._dll.EdsGetChildAtIndex(cameras, 0, byref(camera)))
            self._camera = camera
        finally:
            self._dll.EdsRelease(cameras)
        check("EdsOpenSession", self._dll.EdsOpenSession(self._camera))
        self._info = CameraInfo(self._read_text(api.PROP_PRODUCT_NAME) or "Canon camera", self._read_text(api.PROP_LENS_NAME) or "", "Canon EDSDK")
        log.info("Connected to %s (%s)", self._info.model, self._info.lens or "no lens")
        self._handler = api.ObjectEventHandler(self._on_object_event)
        check("EdsSetObjectEventHandler", self._dll.EdsSetObjectEventHandler(self._camera, api.OBJECT_EVENT_ALL, self._handler, None))
        self._detect()
        self._live_view(True)

    def _teardown(self) -> None:
        dll = self._dll
        if dll is None:
            return
        try:
            if self._camera is not None:
                if self._streaming:
                    try:
                        self._live_view(False)   # give the picture back to the camera's own screen, or the body looks broken afterwards
                    except TetherError as exc:
                        log.warning("Live view did not stop cleanly: %s", exc)
                dll.EdsCloseSession(self._camera)
                dll.EdsRelease(self._camera)
                self._camera = None
            dll.EdsTerminateSDK()
        finally:
            self._dll = None
            self._streaming = False
            if sys.platform == "win32":
                ctypes.windll.ole32.CoUninitialize()

    def _on_object_event(self, event: int, ref, _context) -> int:
        """The SDK says a file is ready. Note it and return: fetching it from inside the callback would re-enter the SDK while it is dispatching to us."""
        if event in (api.OBJECT_EVENT_DIR_ITEM_REQUEST_TRANSFER, api.OBJECT_EVENT_DIR_ITEM_CREATED):
            self._announced.append(ref)
        elif ref and self._dll is not None:
            self._dll.EdsRelease(c_void_p(ref))
        return EDS_ERR_OK

    # ------------------------------------------------------------ properties
    def _read_number(self, prop: int) -> int | None:
        value = c_uint32()
        code = self._dll.EdsGetPropertyData(self._camera, prop, 0, 4, byref(value))
        return value.value if code == EDS_ERR_OK else None

    def _read_text(self, prop: int) -> str | None:
        buf = (c_char * api.MAX_NAME)()
        code = self._dll.EdsGetPropertyData(self._camera, prop, 0, api.MAX_NAME, buf)
        return buf.value.decode("ascii", "replace") if code == EDS_ERR_OK else None

    def _retry_busy(self, call) -> int:
        """Run an SDK call, trying again while the camera says it is busy (and only then: any other refusal is real and comes straight back)."""
        deadline = time.perf_counter() + BUSY_RETRY_S
        while True:
            code = call()
            if code not in (EDS_ERR_DEVICE_BUSY, EDS_ERR_PTP_DEVICE_BUSY) or time.perf_counter() >= deadline:
                return code
            pump(self._dll)
            time.sleep(0.05)

    def _write_number(self, prop: int, value: int, label: str) -> None:
        data = c_uint32(value)
        check(f"EdsSetPropertyData({label})", self._retry_busy(lambda: self._dll.EdsSetPropertyData(self._camera, prop, 0, ctypes.sizeof(data), byref(data))))

    _EXPOSURE_PROPS = {"iso": api.PROP_ISO, "av": api.PROP_AV, "tv": api.PROP_TV, "comp": api.PROP_EXPOSURE_COMP}

    def _choices_of(self, prop: int) -> tuple[int, ...]:
        """The codes the camera will take for a property just now: empty when it will not take a change (the dial is on a mode that sets it itself)."""
        desc = api.PropertyDesc()
        if self._dll.EdsGetPropertyDesc(self._camera, prop, byref(desc)) != EDS_ERR_OK or desc.numElements <= 0:
            return ()
        return tuple(int(desc.propDesc[i]) & 0xFFFFFFFF for i in range(min(desc.numElements, 128)))

    def _read_exposure(self) -> ex.ExposureState:
        values = {key: self._read_number(prop) for key, prop in self._EXPOSURE_PROPS.items()}
        choices = {key: self._choices_of(prop) for key, prop in self._EXPOSURE_PROPS.items()}
        return ex.ExposureState(ex.mode_name(self._read_number(api.PROP_AE_MODE)), {k: v for k, v in values.items() if v is not None}, choices)

    def _write_exposure(self, key: str, code: int) -> None:
        state = self._read_exposure()
        if code not in state.choices.get(key, ()):
            why = (f"The camera is in {state.mode} mode, which sets the {ex.TITLES[key].lower()} itself. Turn its mode dial to M (manual) to set it from here."
                   if not state.choices.get(key) else f"The camera will not take {ex.label(key, code)} for the {ex.TITLES[key].lower()} just now.")
            raise TetherError(why)
        self._write_number(self._EXPOSURE_PROPS[key], code, ex.TITLES[key])

    def _detect(self) -> None:
        """Ask the body what it can do just now. A lens in manual focus, or no lens, cannot be driven from the computer."""
        notes: dict[str, str] = {}
        lens, af = self._read_number(api.PROP_LENS_STATUS), self._read_number(api.PROP_AF_MODE)
        focus = True
        if lens == 0:
            focus = False
            notes["focus_drive"] = "No lens is attached."
        elif af == api.AF_MODE_MANUAL:
            focus = False
            notes["focus_drive"] = "The lens is set to manual focus. Move its AF/MF switch to AF to focus from the computer, or focus by hand."
        self._caps = Capabilities(focus_drive=focus, exposure=self._read_number(api.PROP_TV) is not None, zoom=self._read_number(api.PROP_EVF_ZOOM) is not None, notes=notes)

    # ------------------------------------------------------------ live view and focus
    def _live_view(self, on: bool) -> None:
        current = self._read_number(api.PROP_EVF_OUTPUT_DEVICE) or 0
        if on:
            self._write_number(api.PROP_EVF_OUTPUT_DEVICE, current | api.EVF_OUTPUT_PC, "Evf_OutputDevice")
            self._streaming = True
        else:
            self._streaming = False
            self._write_number(api.PROP_EVF_OUTPUT_DEVICE, (current & ~api.EVF_OUTPUT_PC) | api.EVF_OUTPUT_TFT, "Evf_OutputDevice")

    def _pull_frame(self) -> bool:
        """Fetch one live picture into the shared slot. False when the camera had none ready (normal) or it failed."""
        dll = self._dll
        stream = c_void_p()
        if dll.EdsCreateMemoryStream(0, byref(stream)) != EDS_ERR_OK:
            return False
        try:
            evf = c_void_p()
            if dll.EdsCreateEvfImageRef(stream, byref(evf)) != EDS_ERR_OK:
                return False
            try:
                code = dll.EdsDownloadEvfImage(self._camera, evf)
                if code != EDS_ERR_OK:
                    if code != EDS_ERR_OBJECT_NOTREADY:
                        log.debug("EdsDownloadEvfImage: %s", name_of(code))
                    return False
                length, pointer = c_uint64(), c_void_p()
                if dll.EdsGetLength(stream, byref(length)) != EDS_ERR_OK or dll.EdsGetPointer(stream, byref(pointer)) != EDS_ERR_OK:
                    return False
                if not pointer.value or not length.value:
                    return False
                data = ctypes.string_at(pointer, length.value)
            finally:
                dll.EdsRelease(evf)
        finally:
            dll.EdsRelease(stream)
        with self._frame_lock:
            self._frame, self._seq = data, self._seq + 1
        return True

    def _drive_lens(self, direction: str, size: int, steps: int) -> None:
        param = (api.DRIVE_NEAR if direction == "near" else api.DRIVE_FAR)[max(1, min(3, int(size)))]
        for _ in range(max(1, int(steps))):
            check("EdsSendCommand(DriveLensEvf)", self._dll.EdsSendCommand(self._camera, api.CMD_DRIVE_LENS_EVF, param))
            pump(self._dll)
            self._pull_frame()

    # ------------------------------------------------------------ the shutter
    def _wait(self, seconds: float, until=None) -> bool:
        """Wait, pumping the SDK's events and pulling live pictures as it goes. True if `until()` became true, False when the time ran out."""
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            pump(self._dll)
            self._pull_frame()
            if until is not None and until():
                return True
            time.sleep(0.005)
        return until is not None and until()

    def _shoot(self, folder: str, name_for: NameFor, settle_s: float) -> list[str]:
        os.makedirs(folder, exist_ok=True)
        self._announced.clear()
        self._write_number(api.PROP_SAVE_TO, api.SAVE_TO_HOST, "SaveTo")   # to this computer, not the card...
        room = api.Capacity(numberOfFreeClusters=0x7FFFFFFF, bytesPerSector=512, reset=1)   # ...and claim room for it: the camera will not shoot if it thinks there is none
        check("EdsSetCapacity", self._retry_busy(lambda: self._dll.EdsSetCapacity(self._camera, room)))
        self._wait(settle_s)   # the rig stops shaking
        self._release_shutter()
        if not self._wait(FILE_WAIT_S, lambda: bool(self._announced)):
            raise TetherError("The camera did not report a file within 60 seconds. If it did take the picture, it may have gone to the memory card.")
        self._wait(EXTRA_FILE_GRACE_S)   # a RAW and its JPEG are announced one after the other
        saved: list[str] = []
        problems: list[str] = []
        seen: set[tuple] = set()
        while self._announced:
            item = c_void_p(self._announced.pop(0))
            try:
                path = self._fetch(item, folder, name_for, seen)
            except TetherError as exc:   # one bad file must not lose the others
                problems.append(str(exc))
                log.error("Download failed: %s", exc)
                continue
            if path:
                saved.append(path)
        if not saved:
            raise TetherError("None of the files from that shot could be saved: " + ("; ".join(problems) or "none was announced."))
        if problems:
            log.warning("%d file(s) could not be saved, %d were", len(problems), len(saved))
        return saved

    def _release_shutter(self) -> None:
        """Press the shutter fully without focusing: on a copy stand focus is set on purpose and must not move between frames. A body that refuses that is sent a plain TakePicture."""
        dll = self._dll
        code = self._retry_busy(lambda: dll.EdsSendCommand(self._camera, api.CMD_PRESS_SHUTTER_BUTTON, api.SHUTTER_COMPLETELY_NON_AF))
        if code == EDS_ERR_OK:
            dll.EdsSendCommand(self._camera, api.CMD_PRESS_SHUTTER_BUTTON, api.SHUTTER_OFF)
            return
        log.info("The shutter button was refused (%s); using TakePicture.", name_of(code))
        check("EdsSendCommand(TakePicture)", dll.EdsSendCommand(self._camera, api.CMD_TAKE_PICTURE, 0))

    def _fetch(self, item: c_void_p, folder: str, name_for: NameFor, seen: set) -> str | None:
        """Download one announced file. None when it is the same file announced twice."""
        dll = self._dll
        info = api.DirectoryItemInfo()
        check("EdsGetDirectoryItemInfo", dll.EdsGetDirectoryItemInfo(item, byref(info)))
        camera_name = info.szFileName.decode("ascii", "replace")
        key = (camera_name, info.size, info.dateTime)
        if key in seen:
            dll.EdsRelease(item)
            return None
        seen.add(key)
        dest = unique_path(folder, name_for(camera_name))
        stream = c_void_p()
        if sys.platform == "win32":
            check("EdsCreateFileStreamEx", dll.EdsCreateFileStreamEx(dest, api.FILE_CREATE_ALWAYS, api.ACCESS_READ_WRITE, byref(stream)))
        else:
            check("EdsCreateFileStream", dll.EdsCreateFileStream(os.fsencode(dest), api.FILE_CREATE_ALWAYS, api.ACCESS_READ_WRITE, byref(stream)))
        try:
            code = dll.EdsDownload(item, info.size, stream)
            if code != EDS_ERR_OK:
                dll.EdsDownloadCancel(item)
                raise EdsError("EdsDownload", code)
            check("EdsDownloadComplete", dll.EdsDownloadComplete(item))
        except TetherError:
            dll.EdsRelease(stream)
            stream = None
            try:
                os.remove(dest)   # never leave half a file where a capture should be
            except OSError:
                pass
            raise
        finally:
            if stream is not None:
                dll.EdsRelease(stream)
            dll.EdsRelease(item)
        return dest
