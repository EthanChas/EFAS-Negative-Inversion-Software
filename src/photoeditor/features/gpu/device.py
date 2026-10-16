"""Finding the graphics card and opening it - the one place that imports wgpu. Vulkan first; any trouble leaves the card unused and the CPU does the work."""
import logging
import threading

from . import env_off

_log = logging.getLogger("photoeditor.gpu")
_lock = threading.RLock()
_state: dict = {"tried": False, "device": None, "info": {}, "error": ""}


def _rank(info) -> tuple:
    """Vulkan before the other real back ends, a discrete card before an integrated one."""
    backends = ("Vulkan", "D3D12", "Metal")
    backend = info.get("backend_type")
    kind = info.get("adapter_type")
    return (backends.index(backend) if backend in backends else 9, 0 if kind == "DiscreteGPU" else 1 if kind == "IntegratedGPU" else 2)


def _open():
    import wgpu

    adapters = [a for a in wgpu.gpu.enumerate_adapters_sync() if a.info.get("adapter_type") != "CPU" and a.info.get("backend_type") in ("Vulkan", "D3D12", "Metal")]
    if not adapters:
        raise RuntimeError("no Vulkan graphics card was found")
    best = min(adapters, key=lambda a: _rank(a.info))
    info = {"name": str(best.info.get("device", "")), "backend": str(best.info.get("backend_type", "")), "driver": str(best.info.get("description", "")),
            "kind": str(best.info.get("adapter_type", ""))}
    return best.request_device_sync(label="EFAS"), info


def get_device():
    """The opened graphics card, or None (switched off by PHOTOEDITOR_GPU=off, not there, or it failed once). Opened on first use, once."""
    if env_off():
        return None
    with _lock:
        if not _state["tried"]:
            _state["tried"] = True
            try:
                _state["device"], _state["info"] = _open()
                _log.info("GPU: %s (%s)", _state["info"]["name"], _state["info"]["backend"])
            except Exception as exc:   # no wgpu, no Vulkan, a driver that will not open: the CPU does everything
                _state["error"] = str(exc) or exc.__class__.__name__
                _log.info("GPU not used: %s", _state["error"])
        return _state["device"]


def available() -> bool:
    return get_device() is not None


def info() -> dict:
    """{"name", "backend", "driver", "kind"} of the card in use (empty when there is none)."""
    get_device()
    return dict(_state["info"]) if _state["device"] is not None else {}


def describe() -> str:
    """One line for the Settings page."""
    if env_off():
        return "Switched off by PHOTOEDITOR_GPU=off"
    get_device()
    if _state["device"] is not None:
        i = _state["info"]
        return f"{i['name']} ({i['backend']})"
    return f"No usable graphics card ({_state['error']})" if _state["error"] else "No usable graphics card"


def disable(reason: str) -> None:
    """The card gave trouble: it is not used again in this run."""
    with _lock:
        _state["device"] = None
        _state["error"] = reason
        _state["tried"] = True
    _log.warning("GPU switched off for this run: %s", reason)


def reset() -> None:
    """Forget what was found, so the next use looks again (the tests use this)."""
    with _lock:
        _state.update({"tried": False, "device": None, "info": {}, "error": ""})
