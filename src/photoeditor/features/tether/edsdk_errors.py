"""Canon's EDSDK error codes: what they are called, and what to tell a person. No Qt.

Only the codes that can plausibly reach a person while tethering have a plain-words explanation; every code has a name, and an unknown one is shown in hex."""

from .backend import TetherError

EDS_ERR_OK = 0x00000000
EDS_ERR_DEVICE_BUSY = 0x00000081
EDS_ERR_PTP_DEVICE_BUSY = 0x00002019
EDS_ERR_OBJECT_NOTREADY = 0x0000A102   # a live picture is not ready yet: normal, ask again

NAMES = {
    0x00000001: "UNIMPLEMENTED", 0x00000002: "INTERNAL_ERROR", 0x00000003: "MEM_ALLOC_FAILED", 0x00000005: "OPERATION_CANCELLED", 0x00000006: "INCOMPATIBLE_VERSION",
    0x00000007: "NOT_SUPPORTED", 0x00000008: "UNEXPECTED_EXCEPTION", 0x0000000B: "SELECTION_UNAVAILABLE", 0x00000020: "FILE_IO_ERROR", 0x00000022: "FILE_NOT_FOUND",
    0x00000023: "FILE_OPEN_ERROR", 0x00000028: "FILE_WRITE_ERROR", 0x00000029: "FILE_PERMISSION_ERROR", 0x0000002A: "FILE_DISK_FULL_ERROR", 0x0000002B: "FILE_ALREADY_EXISTS",
    0x00000040: "DIR_NOT_FOUND", 0x00000050: "PROPERTIES_UNAVAILABLE", 0x00000060: "INVALID_PARAMETER", 0x00000061: "INVALID_HANDLE", 0x00000062: "INVALID_POINTER",
    0x00000080: "DEVICE_NOT_FOUND", 0x00000081: "DEVICE_BUSY", 0x00000082: "DEVICE_INVALID", 0x00000083: "DEVICE_EMERGENCY", 0x00000084: "DEVICE_MEMORY_FULL",
    0x00000085: "DEVICE_INTERNAL_ERROR", 0x00000086: "DEVICE_INVALID_PARAMETER", 0x00000087: "DEVICE_NO_DISK", 0x00000088: "DEVICE_DISK_ERROR", 0x0000008D: "DEVICE_NOT_RELEASED",
    0x000000C0: "COMM_PORT_IS_IN_USE", 0x000000C1: "COMM_DISCONNECTED", 0x000000C2: "COMM_DEVICE_INCOMPATIBLE", 0x000000C3: "COMM_BUFFER_FULL", 0x000000C4: "COMM_USB_BUS_ERR",
    0x000000D0: "USB_DEVICE_LOCK_ERROR", 0x000000F4: "WAIT_TIMEOUT_ERROR", 0x00002003: "SESSION_NOT_OPEN", 0x0000200A: "DEVICEPROP_NOT_SUPPORTED", 0x00002019: "PTP_DEVICE_BUSY",
    0x0000201E: "SESSION_ALREADY_OPEN", 0x00002021: "NOT_CAMERA_SUPPORT_SDK_VERSION", 0x00008D01: "TAKE_PICTURE_AF_NG", 0x00008D06: "TAKE_PICTURE_NO_CARD_NG",
    0x00008D07: "TAKE_PICTURE_CARD_NG", 0x00008D08: "TAKE_PICTURE_CARD_PROTECT_NG", 0x00008D0B: "TAKE_PICTURE_NO_LENS_NG", 0x00008D0E: "TAKE_PICTURE_MOVIE_MODE_NG",
    0x0000A005: "OPERATION_REFUSED", 0x0000A006: "LENS_COVER_CLOSE", 0x0000A101: "LOW_BATTERY", 0x0000A102: "OBJECT_NOTREADY",
}

HINTS = {
    0x00000007: "The camera does not support that.",
    0x0000000B: "The camera will not take that setting in its current mode.",
    0x0000002A: "The disk is full.",
    0x00000061: "The camera's handle went stale: the session was probably closed behind our back.",
    0x00000080: "No camera was found. Check the USB cable, and that the camera is on and awake.",
    0x00000081: "The camera is busy. Wait a moment and try again.",
    0x00000083: "The camera reported an emergency. Switch it off and on again.",
    0x00000084: "The camera's memory card is full.",
    0x00000087: "There is no memory card in the camera.",
    0x000000C0: "Another program is using the camera (EOS Utility, Lightroom, a phone app). Close it.",
    0x000000C1: "The camera disconnected. Suspect the USB cable, or a camera that went to sleep.",
    0x000000C2: "This camera does not work with this version of Canon's SDK.",
    0x000000C4: "A USB error. Try another port, directly on the computer and not through a hub.",
    0x00002003: "No session is open with the camera.",
    0x0000200A: "This camera does not offer that setting.",
    0x00002019: "The camera is busy with something else. Try again.",
    0x0000201E: "A session is already open, usually left behind by a program that crashed. Switch the camera off and on again.",
    0x00002021: "This version of Canon's SDK does not support this camera.",
    0x00008D01: "Autofocus could not lock. Focus by hand, or aim at something with more contrast.",
    0x00008D06: "There is no memory card in the camera, so it refused to shoot.",
    0x00008D07: "The camera found a problem with its memory card and refused to shoot.",
    0x00008D08: "The memory card is write-protected.",
    0x00008D0B: "There is no lens on the camera, so it refused to shoot.",
    0x00008D0E: "The camera is in movie mode and refused to take a still.",
    0x0000A005: "The camera refused that in its current state.",
    0x0000A006: "The lens cap is on.",
    0x0000A101: "The camera's battery is too low.",
    0x0000A102: "Not ready yet.",
}


def name_of(code: int) -> str:
    return NAMES.get(code, f"UNKNOWN_0x{code:08X}")


class EdsError(TetherError):
    """An EDSDK call returned something other than OK."""

    def __init__(self, call: str, code: int):
        self.call, self.code = call, code
        hint = HINTS.get(code, "")
        super().__init__(f"{call} failed: {name_of(code)} (0x{code:08X})." + (f" {hint}" if hint else ""))


def check(call: str, code: int) -> None:
    if code != EDS_ERR_OK:
        raise EdsError(call, code)
