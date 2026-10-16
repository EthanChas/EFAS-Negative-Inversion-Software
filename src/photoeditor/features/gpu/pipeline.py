"""Running the per-pixel stages on the graphics card, a band of rows at a time, and handing back the picture - or None, when the card is not to be used and the CPU does it.

The picture goes up as the packed 8-bit RGB bytes it already is, comes back the same way, and between them the one kernel (kernels.py) does the stages that were asked for. Each band is
sent, run and fetched before the next, and the throttle (throttle.py) rests the card after each one as the limit in the settings asks."""
import logging
import threading
import time

import numpy as np

from . import MIN_PIXELS, enabled, limit
from . import device as gpu_device
from . import kernels as K
from .throttle import MAX_BAND_PIXELS, Throttle

_log = logging.getLogger("photoeditor.gpu")
_run_lock = threading.Lock()
_programs: dict = {}
STATS = {"runs": 0, "pixels": 0, "busy": 0.0, "rested": 0.0}   # what the card has done this run (the tests and the Settings page read it)
_MASK_SIDE = 192   # the same size the CPU vignette builds its mask at


def usable(shape) -> bool:
    """Whether a picture of this shape would go to the card: it is switched on, the picture is big enough to be worth the trip, and there is a card."""
    return enabled() and len(shape) == 3 and shape[2] == 3 and shape[0] * shape[1] >= MIN_PIXELS and gpu_device.available()


class _Program:
    """The compiled kernel and its buffers for one opened card (made once)."""

    def __init__(self, device):
        import wgpu

        self.wgpu = wgpu
        self.device = device
        stage = wgpu.ShaderStage.COMPUTE
        kinds = ["read-only-storage", "storage", "read-only-storage", "read-only-storage", "read-only-storage", "read-only-storage"]
        layout = device.create_bind_group_layout(entries=[{"binding": i, "visibility": stage, "buffer": {"type": kind}} for i, kind in enumerate(kinds)])
        module = device.create_shader_module(code=K.source())
        self.pipeline = device.create_compute_pipeline(layout=device.create_pipeline_layout(bind_group_layouts=[layout]), compute={"module": module, "entry_point": "main"})
        words = ((MAX_BAND_PIXELS + 3) // 4) * 3
        usage = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.COPY_SRC
        self.src = device.create_buffer(size=words * 4, usage=usage)
        self.dst = device.create_buffer(size=words * 4, usage=usage)
        self.params = device.create_buffer(size=K.PARAM_COUNT * 4, usage=usage)
        self.lut = device.create_buffer(size=768 * 4, usage=usage)
        self.vig = device.create_buffer(size=_MASK_SIDE * _MASK_SIDE * 4, usage=usage)
        self.meta = device.create_buffer(size=K.META_COUNT * 4, usage=usage)
        buffers = [self.src, self.dst, self.params, self.lut, self.vig, self.meta]
        self.group = device.create_bind_group(layout=layout, entries=[{"binding": i, "resource": {"buffer": b, "offset": 0, "size": b.size}} for i, b in enumerate(buffers)])


def _program(device) -> _Program:
    key = id(device)
    if key not in _programs:
        _programs.clear()
        _programs[key] = _Program(device)
    return _programs[key]


def _run(pixels: np.ndarray, flags: int, params: np.ndarray, lut: np.ndarray | None = None, vig: np.ndarray | None = None) -> np.ndarray:
    """The picture through the kernel with these flags and numbers. Raises on any trouble (the callers turn that into "use the CPU")."""
    device = gpu_device.get_device()
    prog = _program(device)
    queue = device.queue
    h, w = pixels.shape[:2]
    flat = np.ascontiguousarray(pixels).reshape(-1)
    out = np.empty(flat.shape, dtype=np.uint8)
    queue.write_buffer(prog.params, 0, np.ascontiguousarray(params, dtype=np.float32))
    queue.write_buffer(prog.lut, 0, np.ascontiguousarray(lut if lut is not None else np.zeros(768), dtype=np.uint32))
    mask = np.zeros(_MASK_SIDE * _MASK_SIDE, dtype=np.float32)
    if vig is not None:
        mask[: vig.size] = vig.reshape(-1)
    queue.write_buffer(prog.vig, 0, mask)
    throttle = Throttle(limit())
    band = Throttle.next_band_pixels(0, 0.0)
    row = 0
    while row < h:
        rows = max(4, (band // w) // 4 * 4)   # a multiple of 4 rows keeps every band but the last a whole number of 4-pixel groups
        rows = min(rows, h - row)
        n = rows * w
        words = ((n + 3) // 4) * 3
        chunk = flat[row * w * 3:(row + rows) * w * 3]
        if chunk.size % 4:   # the last band: the buffer write wants a multiple of 4 bytes
            chunk = np.concatenate([chunk, np.zeros(4 - chunk.size % 4, dtype=np.uint8)])
        started = time.perf_counter()
        queue.write_buffer(prog.src, 0, chunk)
        queue.write_buffer(prog.meta, 0, np.array([w, row, n, flags, h], dtype=np.uint32))
        encoder = device.create_command_encoder()
        compute = encoder.begin_compute_pass()
        compute.set_pipeline(prog.pipeline)
        compute.set_bind_group(0, prog.group)
        groups = (n + 3) // 4
        compute.dispatch_workgroups((groups + K.WORKGROUP - 1) // K.WORKGROUP, 1, 1)
        compute.end()
        queue.submit([encoder.finish()])
        data = queue.read_buffer(prog.dst, 0, words * 4)
        out[row * w * 3:(row + rows) * w * 3] = np.frombuffer(data, dtype=np.uint8, count=n * 3)
        busy = time.perf_counter() - started
        throttle.after_band(busy)
        band = Throttle.next_band_pixels(n, busy)
        row += rows
    STATS["runs"] += 1
    STATS["pixels"] += h * w
    STATS["busy"] += throttle.busy
    STATS["rested"] += throttle.rested
    return out.reshape(pixels.shape)


def warm_up() -> bool:
    """Open the card and compile the kernel now (it takes about a second), so the first picture that needs it does not wait. True when the card is ready. Safe to call from any thread."""
    if not enabled():
        return False
    try:
        device = gpu_device.get_device()
        if device is None:
            return False
        with _run_lock:
            _program(device)
        return True
    except Exception as exc:
        gpu_device.disable(f"{exc.__class__.__name__}: {exc}")
        return False


def tone_params(shadows: float = 0.0, highlights: float = 0.0, saturation: float = 0.0, tone_lut: np.ndarray | None = None, color: tuple | None = None):
    """The flags, the numbers and the table for the stages that are asked for (the same tests the CPU stages make before they do anything): (flags, params, lut) - flags 0 when none is."""
    from ..colormix import logic as cm
    from ..shadows_highlights.logic import gain_table

    flags = 0
    prm = np.zeros(K.PARAM_COUNT, dtype=np.float32)
    table = None
    if shadows != 0.0 or highlights != 0.0:
        flags |= K.F_SH
        prm[K.P_GAIN:K.P_GAIN + 256] = gain_table(float(shadows), float(highlights))
    if saturation != 0.0:
        flags |= K.F_SAT
        prm[K.P_SAT_K] = np.float32(1.0 + saturation)
    if tone_lut is not None:
        flags |= K.F_LUT
        table = np.ascontiguousarray(tone_lut, dtype=np.uint8).reshape(-1).astype(np.uint32)
    if color is not None:
        values, response, amount = color
        values = values or {}
        amount = float(min(max(amount, 0.0), 1.0))
        use_response = response in cm.RESPONSE and amount > 0.0
        vibrance = float(values.get("vibrance", 0.0))
        mix = {k: float(values.get(k, 0.0)) for k in cm.MIXER_KEYS if abs(float(values.get(k, 0.0))) > 1e-9}
        toning = [(r, float(values.get(f"tone_hue_{r}", 0.0)), float(min(max(values.get(f"tone_amt_{r}", 0.0), 0.0), 1.0))) for r in cm.REGIONS]
        toning = [t for t in toning if t[2] > 1e-9]
        if use_response or vibrance != 0.0 or mix or toning:
            flags |= K.F_COLOR
            prm[K.P_M1INV:K.P_M1INV + 9] = cm._M1_INV.reshape(-1)
            prm[K.P_M2INV:K.P_M2INV + 9] = cm._M2_INV.reshape(-1)
            if vibrance != 0.0:
                flags |= K.F_VIB
                prm[K.P_VIBRANCE] = vibrance
            if mix:
                flags |= K.F_MIX
                for i, band in enumerate(cm.BANDS):
                    prm[K.P_MIX + i] = mix.get(f"mix_hue_{band}", 0.0)
                    prm[K.P_MIX + 8 + i] = mix.get(f"mix_sat_{band}", 0.0)
                    prm[K.P_MIX + 16 + i] = mix.get(f"mix_lum_{band}", 0.0)
            if use_response:
                flags |= K.F_RESP
                spec = cm.RESPONSE[response]
                prm[K.P_RESP_AMOUNT] = amount
                prm[K.P_RESP_SCALE] = 1.0 + amount * (spec["chroma"] - 1.0)
                for i, key in enumerate(("shadows", "mids", "highs")):
                    prm[K.P_RESP_CAST + 2 * i], prm[K.P_RESP_CAST + 2 * i + 1] = spec[key]
            if toning:
                flags |= K.F_TONING
                for region, degrees, strength in toning:
                    i = cm.REGIONS.index(region)
                    prm[K.P_TONE_COS + i], prm[K.P_TONE_SIN + i] = np.cos(np.radians(degrees)), np.sin(np.radians(degrees))
                    prm[K.P_TONE_STRENGTH + i] = strength
    return flags, prm, table


def tone(pixels: np.ndarray, shadows: float = 0.0, highlights: float = 0.0, saturation: float = 0.0, tone_lut: np.ndarray | None = None, color: tuple | None = None) -> np.ndarray | None:
    """An 8-bit RGB picture through shadows / highlights, saturation, the tone table and the OKLCH colour stages - or None when the card is not to be used (the caller then runs the
    CPU stages). `color` is (values, response, amount) as apply_color takes them."""
    if pixels.dtype != np.uint8 or not usable(pixels.shape):
        return None
    flags, params, table = tone_params(shadows, highlights, saturation, tone_lut, color)
    if not flags:
        return None
    try:
        with _run_lock:
            return _run(pixels, flags, params, table)
    except Exception as exc:
        gpu_device.disable(f"{exc.__class__.__name__}: {exc}")
        return None


def vignette(image: np.ndarray, amount: float, size: float) -> np.ndarray | None:
    """The vignette on the card (the same mask as the CPU one, stretched over the picture there), or None."""
    if not amount or image.dtype != np.uint8 or not usable(image.shape):
        return None
    from ..finishing.logic import VIGNETTE_RANGE, _smoothstep

    h, w = image.shape[:2]
    mh, mw = max(8, round(_MASK_SIDE * h / max(h, w))), max(8, round(_MASK_SIDE * w / max(h, w)))
    ys = (np.arange(mh, dtype=np.float32) + 0.5) / mh * 2.0 - 1.0
    xs = (np.arange(mw, dtype=np.float32) + 0.5) / mw * 2.0 - 1.0
    radius = np.sqrt(ys[:, None] ** 2 + xs[None, :] ** 2) / np.sqrt(2.0)
    start = float(np.clip(size, 0.0, 0.98))
    weight = _smoothstep((radius - start) / max(1.0 - start, 1e-3)).astype(np.float32)
    params = np.zeros(K.PARAM_COUNT, dtype=np.float32)
    params[K.P_VIG_STRENGTH] = float(np.clip(amount, VIGNETTE_RANGE[0], VIGNETTE_RANGE[1]))
    params[K.P_VIG_MW], params[K.P_VIG_MH] = mw, mh
    try:
        with _run_lock:
            return _run(image, K.F_VIG, params, None, weight)
    except Exception as exc:
        gpu_device.disable(f"{exc.__class__.__name__}: {exc}")
        return None
