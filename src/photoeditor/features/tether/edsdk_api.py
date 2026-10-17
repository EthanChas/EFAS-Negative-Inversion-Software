"""Calling Canon's EDSDK from Python with ctypes: the constants, the structures, finding the library, and declaring every function's signature. No Qt.

EFAS does not contain Canon's SDK and cannot: Canon licenses it per developer and it may not be passed on. A person who wants to tether gets their own copy from Canon's developer
site and points EFAS at the folder that holds its 64-bit EDSDK.dll. This file holds only the names and numbers a program calling the SDK has to contain.

Every function gets its argument and result types declared; ctypes otherwise guesses from the Python values it is handed, which works until it quietly corrupts the stack.
"""

import ctypes
import os
import sys
from ctypes import POINTER, c_char, c_int32, c_uint32, c_uint64, c_void_p

from .backend import TetherError

Ref = c_void_p   # every Eds...Ref is one opaque handle

# property ids
PROP_PRODUCT_NAME = 0x00000002
PROP_SAVE_TO = 0x0000000B
PROP_AF_MODE = 0x00000404
PROP_LENS_NAME = 0x0000040D
PROP_LENS_STATUS = 0x00000416
PROP_EVF_OUTPUT_DEVICE = 0x00000500

# values
EVF_OUTPUT_TFT = 1       # the live picture goes to the camera's own screen
EVF_OUTPUT_PC = 2        # ... and to the computer
SAVE_TO_HOST = 2         # files go to the computer, not the memory card
AF_MODE_MANUAL = 3
FILE_CREATE_ALWAYS = 1
ACCESS_READ_WRITE = 2

# commands
CMD_TAKE_PICTURE = 0x00000000
CMD_PRESS_SHUTTER_BUTTON = 0x00000004
CMD_DRIVE_LENS_EVF = 0x00000103
SHUTTER_OFF = 0x00000000
SHUTTER_COMPLETELY_NON_AF = 0x00010003   # fully pressed, without focusing first

# lens drive: finest (1) to coarsest (3)
DRIVE_NEAR = {1: 0x00000001, 2: 0x00000002, 3: 0x00000003}
DRIVE_FAR = {1: 0x00008001, 2: 0x00008002, 3: 0x00008003}

# events
OBJECT_EVENT_ALL = 0x00000200
OBJECT_EVENT_DIR_ITEM_CREATED = 0x00000204
OBJECT_EVENT_DIR_ITEM_REQUEST_TRANSFER = 0x00000208

MAX_NAME = 256


class DirectoryItemInfo(ctypes.Structure):
    """One file on the camera."""

    _fields_ = [("size", c_uint64), ("isFolder", c_int32), ("groupID", c_uint32), ("option", c_uint32), ("szFileName", c_char * MAX_NAME), ("format", c_uint32), ("dateTime", c_uint32)]


class Capacity(ctypes.Structure):
    """The room the computer claims to have. The camera refuses to shoot unless it believes the destination has some."""

    _fields_ = [("numberOfFreeClusters", c_int32), ("bytesPerSector", c_int32), ("reset", c_int32)]


class PropertyDesc(ctypes.Structure):
    """The values a property will take just now (numElements is 0 when it cannot be set)."""

    _fields_ = [("form", c_int32), ("access", c_int32), ("numElements", c_int32), ("propDesc", c_int32 * 128)]


# The callbacks are __stdcall on Windows and plain C elsewhere. A registered callback object has to be kept alive for as long as the SDK may call it: if Python frees it the SDK
# calls freed memory and the program dies without a message.
_FUNCTYPE = ctypes.WINFUNCTYPE if sys.platform == "win32" else ctypes.CFUNCTYPE
ObjectEventHandler = _FUNCTYPE(c_uint32, c_uint32, c_void_p, c_void_p)


def library_name() -> str:
    return "EDSDK.dll" if sys.platform == "win32" else "EDSDK.framework/EDSDK" if sys.platform == "darwin" else "libEDSDK.so"


def find_library(folder: str) -> str:
    """The path of the 64-bit EDSDK library inside what the person chose: the folder that holds it, or Canon's own unpacked folder above it (a few levels are searched, and a
    path with 64 in it is preferred, because Canon ships a 32-bit and a 64-bit copy). An empty string when there is none."""
    if not folder or not os.path.isdir(folder):
        return ""
    name = library_name()
    direct = os.path.join(folder, name)
    if os.path.isfile(direct):
        return direct
    found: list[str] = []
    base_depth = folder.rstrip("\\/").count(os.sep)
    for here, dirs, files in os.walk(folder):
        if here.count(os.sep) - base_depth >= 4:
            dirs[:] = []
        if name.lower() in (f.lower() for f in files):
            found.append(os.path.join(here, name))
    found.sort(key=lambda p: (0 if "64" in p.replace(folder, "") else 1, len(p)))
    return found[0] if found else ""


def load(folder: str):
    """Load the EDSDK library from `folder` and declare its functions. TetherError, saying what to do, when it is missing or will not load."""
    path = find_library(folder)
    if not path:
        raise TetherError(f"Canon's EDSDK was not found{' in ' + folder if folder else ''}.\n"
                          "EFAS cannot include it: get your own copy from Canon's developer site, unpack it, and choose its folder (the one with EDSDK.dll, the 64-bit one) in the tether window.")
    if ctypes.sizeof(c_void_p) != 8:
        raise TetherError("This copy of EFAS is 32-bit, and Canon's 64-bit EDSDK needs a 64-bit program.")
    try:
        if sys.platform == "win32":
            os.add_dll_directory(os.path.dirname(path))   # the library loads its neighbours (EdsImage.dll) from its own folder
            dll = ctypes.WinDLL(path)
        else:
            dll = ctypes.CDLL(path)
    except OSError as exc:
        raise TetherError(f"Canon's EDSDK could not be loaded from {path}: {exc}\n"
                          "Usually the 32-bit library with a 64-bit program, or the library without the files that sit beside it.") from exc
    declare(dll)
    return dll


def declare(dll) -> None:
    """The argument and result types of every function EFAS calls."""
    err, ref = c_uint32, Ref
    sigs = {
        "EdsInitializeSDK": ([], err), "EdsTerminateSDK": ([], err),
        "EdsRetain": ([ref], c_uint32), "EdsRelease": ([ref], c_uint32),   # these two return the new count, not an error code
        "EdsGetCameraList": ([POINTER(ref)], err), "EdsGetChildCount": ([ref, POINTER(c_uint32)], err), "EdsGetChildAtIndex": ([ref, c_int32, POINTER(ref)], err),
        "EdsOpenSession": ([ref], err), "EdsCloseSession": ([ref], err),
        "EdsGetPropertyData": ([ref, c_uint32, c_int32, c_uint32, c_void_p], err), "EdsSetPropertyData": ([ref, c_uint32, c_int32, c_uint32, c_void_p], err),
        "EdsGetPropertyDesc": ([ref, c_uint32, POINTER(PropertyDesc)], err),
        "EdsSendCommand": ([ref, c_uint32, c_int32], err), "EdsSetCapacity": ([ref, Capacity], err),
        "EdsCreateMemoryStream": ([c_uint64, POINTER(ref)], err), "EdsGetPointer": ([ref, POINTER(c_void_p)], err), "EdsGetLength": ([ref, POINTER(c_uint64)], err),
        "EdsCreateEvfImageRef": ([ref, POINTER(ref)], err), "EdsDownloadEvfImage": ([ref, ref], err),
        "EdsGetDirectoryItemInfo": ([ref, POINTER(DirectoryItemInfo)], err), "EdsDownload": ([ref, c_uint64, ref], err), "EdsDownloadComplete": ([ref], err), "EdsDownloadCancel": ([ref], err),
        "EdsSetObjectEventHandler": ([ref, c_uint32, ObjectEventHandler, c_void_p], err),
    }
    if sys.platform == "win32":
        sigs["EdsCreateFileStreamEx"] = ([ctypes.c_wchar_p, c_uint32, c_uint32, POINTER(ref)], err)   # a wide string, so a folder with accents in its name works
    else:
        sigs["EdsCreateFileStream"] = ([POINTER(c_char), c_uint32, c_uint32, POINTER(ref)], err)
    for name, (argtypes, restype) in sigs.items():
        fn = getattr(dll, name)
        fn.argtypes, fn.restype = argtypes, restype
    get_event = getattr(dll, "EdsGetEvent", None)   # how events are collected where there is no Windows message queue
    if get_event is not None and sys.platform != "win32":
        get_event.argtypes, get_event.restype = [], err
