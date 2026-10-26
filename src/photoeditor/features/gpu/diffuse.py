"""Diffuse or Sharpen on the graphics card (Vulkan, through wgpu) - the same maths as features/diffuse/logic.py, a step at a time on whole-picture buffers.

The processor does this module a few rows at a time and it takes seconds on a preview and minutes on a big export. Here the whole picture lives in float buffers on the card: each iteration
decomposes it into wavelet scales (two passes of the a-trous B-spline for each) and rebuilds it from the coarsest scale (one pass of the heat equation on each), and the picture comes back
once at the end. Any trouble (no card, a picture too large for it, an error) gives None, and the caller does the work on the processor.

A picture of more than MAX_PIXELS is cut into strips with an overlap (the receptive field of the scales), as the processor path does; a strip needs `scales + 5` buffers of 16 bytes a pixel."""
import logging
import math
import threading
import time
from string import Template

import numpy as np

from . import MIN_PIXELS, enabled, limit
from . import device as gpu_device
from .throttle import Throttle

_log = logging.getLogger("photoeditor.gpu")
_lock = threading.Lock()
_programs: dict = {}
STATS = {"runs": 0, "pixels": 0}
MAX_PIXELS = 7_000_000          # per strip: a buffer of 16 bytes a pixel must stay under the card's default 128 MiB a binding
RECORD = 64                      # floats in the parameters of one dispatch (a record is padded to 256 bytes, the offset alignment of a binding)
WORKGROUP = 8

_SOURCE = Template(r"""
@group(0) @binding(0) var<storage, read> a_in: array<vec4<f32>>;
@group(0) @binding(1) var<storage, read> b_in: array<vec4<f32>>;
@group(0) @binding(2) var<storage, read_write> c_out: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read_write> d_out: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read> mask_in: array<u32>;
@group(0) @binding(5) var<storage, read> prm: array<f32>;

fn width() -> i32 { return i32(prm[0]); }
fn height() -> i32 { return i32(prm[1]); }
fn mult() -> i32 { return i32(prm[2]); }
fn at(x: i32, y: i32) -> u32 { return u32(clamp(y, 0, height() - 1)) * u32(width()) + u32(clamp(x, 0, width() - 1)); }

fn weight(k: i32) -> f32 {
    if (k == 0 || k == 4) { return 0.0625; }
    if (k == 1 || k == 3) { return 0.25; }
    return 0.375;
}

// vertical pass of the dilated B-spline: a_in -> c_out
@compute @workgroup_size($WG, $WG)
fn vblur(@builtin(global_invocation_id) gid: vec3<u32>) {
    let x = i32(gid.x);
    let y = i32(gid.y);
    if (x >= width() || y >= height()) { return; }
    var acc = vec3<f32>(0.0);
    for (var k = 0; k < 5; k = k + 1) {
        acc = acc + weight(k) * a_in[at(x, y + (k - 2) * mult())].xyz;
    }
    c_out[at(x, y)] = vec4<f32>(acc, 0.0);
}

// horizontal pass: a_in is the vertical pass, b_in the layer being decomposed; c_out gets the low frequencies (never below 0), d_out the high ones
@compute @workgroup_size($WG, $WG)
fn hblur(@builtin(global_invocation_id) gid: vec3<u32>) {
    let x = i32(gid.x);
    let y = i32(gid.y);
    if (x >= width() || y >= height()) { return; }
    var acc = vec3<f32>(0.0);
    for (var k = 0; k < 5; k = k + 1) {
        acc = acc + weight(k) * a_in[at(x + (k - 2) * mult(), y)].xyz;
    }
    let low = max(acc, vec3<f32>(0.0));
    c_out[at(x, y)] = vec4<f32>(low, 0.0);
    d_out[at(x, y)] = vec4<f32>(b_in[at(x, y)].xyz - low, 0.0);
}

struct Dir { mag: vec3<f32>, cos2: vec3<f32>, sin2: vec3<f32>, cs: vec3<f32> };

fn direction(g0: vec3<f32>, g1: vec3<f32>) -> Dir {
    let mag = sqrt(g0 * g0 + g1 * g1);
    let ok = mag != vec3<f32>(0.0);
    let safe = select(vec3<f32>(1.0), mag, ok);
    let c = select(vec3<f32>(1.0), g0 / safe, ok);
    let s = select(vec3<f32>(0.0), g1 / safe, ok);
    return Dir(mag, c * c, s * s, c * s);
}

// one of the four derivatives: the 3x3 laplacian that is isotropic (mode 0) or rotated to follow (mode 2) or avoid (mode 1) the gradient
fn derivative(mode: i32, aniso: f32, nine: array<vec3<f32>, 9>, d: Dir) -> vec3<f32> {
    let corner = nine[0] + nine[8] - nine[2] - nine[6];
    let v = nine[1] + nine[7];
    let h = nine[3] + nine[5];
    if (mode == 0) {
        return 0.25 * (nine[0] + nine[2] + nine[6] + nine[8]) + 0.5 * (v + h) - 3.0 * nine[4];
    }
    let c2 = exp(-d.mag * aniso);
    var a00: vec3<f32>;
    var a11: vec3<f32>;
    var a01: vec3<f32>;
    if (mode == 1) {
        a00 = d.cos2 + c2 * d.sin2;
        a11 = c2 * d.cos2 + d.sin2;
        a01 = (c2 - vec3<f32>(1.0)) * d.cs;
    } else {
        a00 = c2 * d.cos2 + d.sin2;
        a11 = d.cos2 + c2 * d.sin2;
        a01 = (vec3<f32>(1.0) - c2) * d.cs;
    }
    return (a01 * 0.5) * corner + a11 * v + a00 * h - 2.0 * (a00 + a11) * nine[4];
}

// one step of the heat equation on one scale: a_in the high frequencies, b_in the low ones under them, c_out the rebuilt low frequencies
@compute @workgroup_size($WG, $WG)
fn pde(@builtin(global_invocation_id) gid: vec3<u32>) {
    let x = i32(gid.x);
    let y = i32(gid.y);
    if (x >= width() || y >= height()) { return; }
    let m = mult();
    let here = at(x, y);
    if (prm[3] > 0.5 && mask_in[here] == 0u) {
        c_out[here] = vec4<f32>(a_in[here].xyz + b_in[here].xyz, 0.0);
        return;
    }
    var lf: array<vec3<f32>, 9>;
    var hf: array<vec3<f32>, 9>;
    for (var ii = 0; ii < 3; ii = ii + 1) {
        for (var jj = 0; jj < 3; jj = jj + 1) {
            let p = at(x + (jj - 1) * m, y + (ii - 1) * m);
            lf[3 * ii + jj] = b_in[p].xyz;
            hf[3 * ii + jj] = a_in[p].xyz;
        }
    }
    let dg = direction((lf[7] - lf[1]) * 0.5, (lf[5] - lf[3]) * 0.5);
    let dl = direction((hf[7] - hf[1]) * 0.5, (hf[5] - hf[3]) * 0.5);
    let d0 = derivative(i32(prm[8]), prm[4], lf, dg);
    let d1 = derivative(i32(prm[9]), prm[5], lf, dl);
    let d2 = derivative(i32(prm[10]), prm[6], hf, dg);
    let d3 = derivative(i32(prm[11]), prm[7], hf, dl);
    var variance = vec3<f32>(0.0);
    for (var k = 0; k < 9; k = k + 1) { variance = variance + hf[k] * hf[k]; }
    variance = variance * prm[12] + vec3<f32>(prm[13]);
    var acc = d0 * prm[14] + d1 * prm[15] + d2 * prm[16] + d3 * prm[17];
    acc = acc / variance + hf[4] * prm[18] + lf[4];
    c_out[here] = vec4<f32>(max(acc, vec3<f32>(0.0)), 0.0);
}
""")


class _Program:
    """The compiled kernels for one opened card (made once)."""

    def __init__(self, device):
        import wgpu

        self.wgpu = wgpu
        self.device = device
        stage = wgpu.ShaderStage.COMPUTE
        kinds = ["read-only-storage", "read-only-storage", "storage", "storage", "read-only-storage", "read-only-storage"]
        self.layout = device.create_bind_group_layout(entries=[{"binding": i, "visibility": stage, "buffer": {"type": kind}} for i, kind in enumerate(kinds)])
        module = device.create_shader_module(code=_SOURCE.substitute(WG=WORKGROUP))
        layout = device.create_pipeline_layout(bind_group_layouts=[self.layout])
        self.pipelines = {name: device.create_compute_pipeline(layout=layout, compute={"module": module, "entry_point": name}) for name in ("vblur", "hblur", "pde")}
        usage = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.COPY_SRC
        self.null_ro = device.create_buffer(size=256, usage=usage)
        self.null_rw = device.create_buffer(size=256, usage=usage)
        self.null_rw2 = device.create_buffer(size=256, usage=usage)
        self.null_mask = device.create_buffer(size=256, usage=usage)


def _program(device) -> _Program:
    key = id(device)
    if key not in _programs:
        _programs.clear()
        _programs[key] = _Program(device)
    return _programs[key]


def usable(shape) -> bool:
    return enabled() and len(shape) == 3 and shape[2] == 3 and shape[0] * shape[1] >= MIN_PIXELS and gpu_device.available()


def warm_up() -> bool:
    """Open the card and compile the kernels now, so the first Diffuse or Sharpen does not wait for it."""
    if not enabled():
        return False
    try:
        device = gpu_device.get_device()
        if device is None:
            return False
        with _lock:
            _program(device)
        return True
    except Exception as exc:
        gpu_device.disable(f"{exc.__class__.__name__}: {exc}")
        return False


def _record(width, height, mult, has_mask=0, anisotropy=(0, 0, 0, 0), isotropy=(0, 0, 0, 0), regularization_factor=0.0, variance_threshold=1.0, abcd=(0, 0, 0, 0), strength=1.0) -> np.ndarray:
    rec = np.zeros(RECORD, dtype=np.float32)
    rec[0:4] = (width, height, mult, has_mask)
    rec[4:8] = anisotropy
    rec[8:12] = isotropy
    rec[12], rec[13] = regularization_factor, variance_threshold
    rec[14:18] = abcd
    rec[18] = strength
    return rec


def run(linear: np.ndarray, values: dict, zoom: float, mask: np.ndarray | None = None) -> np.ndarray:
    """The linear-light picture (float32, h x w x 3) through every iteration on the card; returns the float32 result. Raises on any trouble."""
    from ..diffuse import logic as D

    device = gpu_device.get_device()
    prog = _program(device)
    wgpu = prog.wgpu
    queue = device.queue
    h, w = linear.shape[:2]
    n = h * w
    iterations = max(int(round(float(values["dif_iterations"]))), 1)
    scales = D.scales_for(values, zoom)
    anisotropy = [float(values[k]) ** 2 for k in ("dif_aniso_first", "dif_aniso_second", "dif_aniso_third", "dif_aniso_fourth")]
    isotropy = [0 if float(values[k]) == 0.0 else (1 if float(values[k]) > 0.0 else 2) for k in ("dif_aniso_first", "dif_aniso_second", "dif_aniso_third", "dif_aniso_fourth")]
    regularization = 10.0 ** float(values["dif_regularization"]) - 1.0
    variance_threshold = 10.0 ** float(values["dif_variance_threshold"])
    speeds = [float(values[k]) for k in ("dif_first", "dif_second", "dif_third", "dif_fourth")]
    radius = max(float(values["dif_radius"]), 1e-3)
    centre = float(values["dif_radius_center"])
    sharpness = float(values["dif_sharpness"])
    has_mask = mask is not None

    usage = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.COPY_SRC
    size = n * 16
    make = lambda: device.create_buffer(size=size, usage=usage)
    buf_in, buf_out, tmp, lf_a, lf_b = make(), make(), make(), make(), make()
    highs = [make() for _ in range(scales)]
    mask_buf = device.create_buffer(size=max(256, ((n * 4 + 3) // 4) * 4), usage=usage) if has_mask else prog.null_mask
    if has_mask:
        queue.write_buffer(mask_buf, 0, np.ascontiguousarray(mask.astype(np.uint32)))
    rgba = np.zeros((h, w, 4), dtype=np.float32)
    rgba[..., :3] = linear
    queue.write_buffer(buf_in, 0, np.ascontiguousarray(rgba))

    # one parameter record for every dispatch, written once (a write between dispatches would only be seen at the end)
    records: list[np.ndarray] = []
    plan: list[tuple] = []        # (pipeline, A, B, C, D, record index)

    def add(pipeline, a, b, c, d, rec):
        records.append(rec)
        plan.append((pipeline, a, b, c, d, len(records) - 1))

    source, target = buf_in, buf_out
    for _it in range(iterations):
        current = source
        lows = (lf_a, lf_b)
        for s in range(scales):
            low = lows[s % 2]
            m = 1 << s
            add("vblur", current, prog.null_ro, tmp, prog.null_rw, _record(w, h, m))
            add("hblur", tmp, current, low, highs[s], _record(w, h, m))
            current = low
        residual = current
        spare = lf_b if residual is lf_a else lf_a
        for s in range(scales - 1, -1, -1):
            sigma = D.equivalent_sigma_at_step(D.B_SPLINE_SIGMA, s)
            norm = math.exp(-(((sigma * zoom) - centre) ** 2) / (radius ** 2))
            rec = _record(w, h, 1 << s, 1 if has_mask else 0, anisotropy, isotropy, regularization * sigma ** 2 / 9.0, variance_threshold,
                          [speed * D.KAPPA * norm for speed in speeds], sharpness * norm + 1.0)
            out = target if s == 0 else spare
            add("pde", highs[s], residual, out, prog.null_rw, rec)
            residual, spare = out, residual
        source, target = target, source
    result = source

    table = np.zeros((len(records), RECORD), dtype=np.float32)
    for i, rec in enumerate(records):
        table[i] = rec
    prm = device.create_buffer(size=max(256, table.nbytes), usage=usage)
    queue.write_buffer(prm, 0, np.ascontiguousarray(table))

    throttle = Throttle(limit())
    per_iteration = max(1, len(plan) // iterations)
    done = 0
    while done < len(plan):
        started = time.perf_counter()
        encoder = device.create_command_encoder()
        compute = encoder.begin_compute_pass()
        stop = min(len(plan), done + per_iteration)
        for pipeline, a, b, c, d, index in plan[done:stop]:
            group = device.create_bind_group(layout=prog.layout, entries=[
                {"binding": 0, "resource": {"buffer": a, "offset": 0, "size": a.size}},
                {"binding": 1, "resource": {"buffer": b, "offset": 0, "size": b.size}},
                {"binding": 2, "resource": {"buffer": c, "offset": 0, "size": c.size}},
                {"binding": 3, "resource": {"buffer": d, "offset": 0, "size": d.size}},
                {"binding": 4, "resource": {"buffer": mask_buf, "offset": 0, "size": mask_buf.size}},
                {"binding": 5, "resource": {"buffer": prm, "offset": index * RECORD * 4, "size": RECORD * 4}},
            ])
            compute.set_pipeline(prog.pipelines[pipeline])
            compute.set_bind_group(0, group)
            compute.dispatch_workgroups((w + WORKGROUP - 1) // WORKGROUP, (h + WORKGROUP - 1) // WORKGROUP, 1)
        compute.end()
        queue.submit([encoder.finish()])
        done = stop
        if done < len(plan):
            queue.read_buffer(prog.null_rw, 0, 4)      # wait for this iteration, so the rest can be taken between
        throttle.after_band(time.perf_counter() - started)
    data = queue.read_buffer(result, 0, size)
    out = np.frombuffer(data, dtype=np.float32, count=n * 4).reshape(h, w, 4)[..., :3].copy()
    for b in (buf_in, buf_out, tmp, lf_a, lf_b, prm, *highs):
        b.destroy()
    if has_mask:
        mask_buf.destroy()
    STATS["runs"] += 1
    STATS["pixels"] += n
    return out


def process(pixels: np.ndarray, values: dict, zoom: float) -> np.ndarray | None:
    """Diffuse or Sharpen on the card for an 8-bit picture (the same steps as the processor's apply_diffuse), or None when the card is not to be used or the picture does not fit."""
    from ..diffuse import logic as D

    if pixels.dtype != np.uint8 or not usable(pixels.shape):
        return None
    h, w = pixels.shape[:2]
    scales = D.scales_for(values, zoom)
    overlap = (1 << scales) * max(1, int(round(float(values["dif_iterations"]) ** 0.5)))
    rows = max(8, MAX_PIXELS // w)
    if rows < h and rows < 4 * overlap:
        return None            # too large for one pass and strips this tall would be mostly overlap: the processor path cuts it up
    try:
        with _lock:
            out = np.empty_like(pixels)
            y = 0
            while y < h:
                y1 = min(h, y + rows) if rows < h else h
                r0, r1 = max(0, y - overlap), min(h, y1 + overlap)
                linear = D._to_linear(pixels[r0:r1])
                mask = None
                work = linear
                threshold = float(values["dif_threshold"])
                if threshold > 0:
                    mask = (linear > threshold).any(axis=2)
                    rng = np.random.default_rng(1337)
                    noise = np.abs(rng.normal(loc=linear, scale=np.maximum(linear, 1e-6))).astype(np.float32)
                    work = np.where(mask[:, :, None], noise, linear)
                done = D._from_linear(run(np.ascontiguousarray(work, dtype=np.float32), values, zoom, mask))
                out[y:y1] = done[y - r0: y - r0 + (y1 - y)]
                y = y1
            return out
    except Exception as exc:
        gpu_device.disable(f"{exc.__class__.__name__}: {exc}")
        return None
