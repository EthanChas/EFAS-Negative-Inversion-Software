"""Color Balance RGB on the graphics card (Vulkan, through wgpu) - the same maths as features/colorbalancergb/logic.py for darktable's own saturation formula (darktable UCS), a pixel at a time.

On the processor this module costs about a second on a preview and many seconds on a big export, which makes its sliders heavy to drag. Here a band of rows goes up as packed 8-bit RGB, the shader
does every pixel by itself in single precision (decoding sRGB, grading in Filmlight Yrg, the saturation and brilliance with their gamut map, encoding sRGB) and the band comes back. The JzAzBz
formula (the old one, which needs double precision) and any trouble with the card give None, and the caller does the work on the processor."""
import logging
import threading
import time
from string import Template

import numpy as np

from . import MIN_PIXELS, enabled, limit
from . import device as gpu_device
from .throttle import MAX_BAND_PIXELS, Throttle

_log = logging.getLogger("photoeditor.gpu")
_lock = threading.Lock()
_programs: dict = {}
STATS = {"runs": 0, "pixels": 0}
WORKGROUP = 64
# the floats of the parameters, in order
PARAMS = ("vibrance", "contrast", "grey_fulcrum", "chroma_global", "saturation_global", "brilliance_global", "cos_hue", "sin_hue", "shadows_weight", "highlights_weight", "midtones_weight",
          "mask_grey_fulcrum", "white_fulcrum", "midtones_Y", "L_white")
VECTORS = ("global", "shadows", "highlights", "midtones", "chroma", "saturation", "brilliance")     # three floats each, after the scalars, in this order
SCALARS = len(PARAMS)
LUT_AT = SCALARS + 3 * len(VECTORS) + 1          # where the gamut table starts (the count of pixels is the slot before)
PARAM_COUNT = LUT_AT + 512


def _mat(name: str, m: np.ndarray) -> str:
    rows = ", ".join("vec3<f32>(" + ", ".join(f"{float(v):.9g}" for v in row) + ")" for row in m)
    return f"const {name} = array<vec3<f32>, 3>({rows});"


def _source() -> str:
    from ..colorbalancergb import logic as C

    consts = "\n".join([
        _mat("RGB_TO_LMS", C._RGB_TO_LMS), _mat("LMS_TO_GRADING", C._LMS_TO_GRADING), _mat("GRADING_TO_LMS", C._GRADING_TO_LMS), _mat("LMS_TO_XYZ", C._LMS_TO_XYZ),
        _mat("XYZ_TO_SRGB", C._XYZ_TO_SRGB),
    ])
    names = {f"P_{n.upper()}": str(i) for i, n in enumerate(PARAMS)}
    names.update({f"V_{n.upper()}": str(SCALARS + 3 * i) for i, n in enumerate(VECTORS)})
    names.update({"P_COUNT": str(SCALARS + 3 * len(VECTORS)), "LUT_AT": str(LUT_AT), "WG": str(WORKGROUP), "CONSTS": consts, "LUT_ELEM": str(C.LUT_ELEM),
                  "D65_R": f"{C._D65_R:.9g}", "D65_G": f"{C._D65_G:.9g}", "MASK_EXP": f"{C._GREY_MASK_EXPONENT:.9g}", "L_UPPER": f"{C._UCS_L_UPPER:.9g}", "L_RANGE": f"{C._UCS_L_RANGE:.9g}",
                  "D65_X": f"{C._D65_XY[0]:.9g}", "D65_Y": f"{C._D65_XY[1]:.9g}"})
    return _SOURCE.substitute(**names)


_SOURCE = Template(r"""
@group(0) @binding(0) var<storage, read> src: array<u32>;
@group(0) @binding(1) var<storage, read_write> dst: array<u32>;
@group(0) @binding(2) var<storage, read> prm: array<f32>;

$CONSTS

fn mulm(m: array<vec3<f32>, 3>, v: vec3<f32>) -> vec3<f32> { return vec3<f32>(dot(m[0], v), dot(m[1], v), dot(m[2], v)); }
fn vec_at(base: u32) -> vec3<f32> { return vec3<f32>(prm[base], prm[base + 1u], prm[base + 2u]); }

fn srgb_to_linear(c: f32) -> f32 {
    if (c <= 0.04045) { return c / 12.92; }
    return pow((c + 0.055) / 1.055, 2.4);
}

fn linear_to_srgb(x: f32) -> f32 {
    let c = clamp(x, 0.0, 1.0);
    if (c <= 0.0031308) { return c * 12.92; }
    return 1.055 * pow(c, 1.0 / 2.4) - 0.055;
}

fn pw(x: f32, p: f32) -> f32 { return pow(max(x, 0.0), p); }

fn yrg_of(lms: vec3<f32>) -> vec3<f32> {
    let y = 0.68990272 * lms.x + 0.34832189 * lms.y;
    let a = lms.x + lms.y + lms.z;
    var n = vec3<f32>(0.0);
    if (a != 0.0) { n = lms / a; }
    let g = mulm(LMS_TO_GRADING, n);
    return vec3<f32>(y, g.x, g.y);
}

fn lms_of(y: f32, r: f32, g: f32) -> vec3<f32> {
    let n = mulm(GRADING_TO_LMS, vec3<f32>(r, g, 1.0 - r - g));
    let denom = 0.68990272 * n.x + 0.34832189 * n.y;
    var s = 0.0;
    if (denom != 0.0) { s = y / denom; }
    return n * s;
}

fn soft_clip(x: f32, soft: f32, hard: f32) -> f32 {
    let norm = max(hard - soft, 1e-12);
    if (x > soft) { return soft + (1.0 - exp(-(x - soft) / norm)) * norm; }
    return x;
}

fn ucs_l_of_y(y: f32) -> f32 {
    let yh = pw(y, 0.631651345306265);
    return $L_RANGE * yh / (yh + 1.12426773749357);
}

fn y_of_ucs_l(l: f32) -> f32 { return pw(1.12426773749357 * l / ($L_RANGE - l), 1.5831518565279648); }

fn lookup_gamut(hue: f32) -> f32 {
    let x = f32($LUT_ELEM) * (hue + 3.14159265358979) / 6.28318530717959;
    let lo = floor(x);
    let i0 = u32(i32(lo)) & ($LUT_ELEM - 1u);
    let i1 = u32(i32(ceil(x))) & ($LUT_ELEM - 1u);
    let y0 = prm[$LUT_AT + i0];
    if (i0 != i1) { return y0 + (x - lo) * (prm[$LUT_AT + i1] - y0); }
    return y0;
}

fn finite_or(x: f32, fallback: f32) -> f32 {
    if (x == x && abs(x) < 1e30) { return x; }
    return fallback;
}

fn grade(srgb: vec3<f32>) -> vec3<f32> {
    let lin = vec3<f32>(srgb_to_linear(srgb.x), srgb_to_linear(srgb.y), srgb_to_linear(srgb.z));
    let lms0 = mulm(RGB_TO_LMS, max(lin, vec3<f32>(0.0)));
    let yrg0 = yrg_of(lms0);
    let Y = max(yrg0.x, 0.0);
    let rr = yrg0.y - $D65_R;
    let gg = yrg0.z - $D65_G;
    var c = length(vec2<f32>(rr, gg));
    var cos_h = 1.0;
    var sin_h = 0.0;
    if (c != 0.0) { cos_h = rr / c; sin_h = gg / c; }

    // the masks of the luminance
    let mask_grey = prm[$P_MASK_GREY_FULCRUM];
    let x_off = pw(Y, $MASK_EXP) - mask_grey;
    let x_norm = x_off / mask_grey;
    let alpha = 1.0 / (1.0 + exp(clamp(x_norm * prm[$P_SHADOWS_WEIGHT], -80.0, 80.0)));
    let beta = 1.0 / (1.0 + exp(clamp(-x_norm * prm[$P_HIGHLIGHTS_WEIGHT], -80.0, 80.0)));
    let gamma = exp(-x_off * x_off * prm[$P_MIDTONES_WEIGHT] / 4.0) * (1.0 - alpha) * (1.0 - alpha) * (1.0 - beta) * (1.0 - beta) * 8.0;
    let chroma_z = vec_at($V_CHROMA);
    let sat_z = vec_at($V_SATURATION);
    let bri_z = vec_at($V_BRILLIANCE);

    // hue rotation, then chroma, then the chroma clipped back into Yrg
    let ca = prm[$P_COS_HUE];
    let sa = prm[$P_SIN_HUE];
    let cos2 = ca * cos_h - sa * sin_h;
    let sin2 = sa * cos_h + ca * sin_h;
    let boost = prm[$P_CHROMA_GLOBAL] + alpha * chroma_z.x + gamma * chroma_z.y + beta * chroma_z.z;
    let vib = prm[$P_VIBRANCE];
    var vibrance = 0.0;
    if (vib != 0.0) { vibrance = vib * (1.0 - pw(c, abs(vib))); }
    c = c * max(1.0 + boost + vibrance, 0.0);
    var r2 = c * cos2 + $D65_R;
    var g2 = c * sin2 + $D65_G;
    var max_c = c;
    if (r2 < 0.0) { max_c = min(-$D65_R / cos2, max_c); }
    if (g2 < 0.0) { max_c = min(-$D65_G / sin2, max_c); }
    if (r2 + g2 > 1.0) { max_c = min((1.0 - $D65_R - $D65_G) / (cos2 + sin2), max_c); }
    c = finite_or(max_c, 0.0);
    r2 = c * cos2 + $D65_R;
    g2 = c * sin2 + $D65_G;

    // the four-way grading in Filmlight RGB
    var grading = mulm(LMS_TO_GRADING, lms_of(Y, r2, g2));
    grading = grading + vec_at($V_GLOBAL);
    let slope = (1.0 - beta) * (vec3<f32>(1.0 - alpha) + alpha * vec_at($V_SHADOWS)) + beta * vec_at($V_HIGHLIGHTS);
    grading = grading * slope;
    let white = prm[$P_WHITE_FULCRUM];
    let sgn = select(vec3<f32>(1.0), vec3<f32>(-1.0), grading < vec3<f32>(0.0));
    let mid = vec_at($V_MIDTONES);
    grading = vec3<f32>(pw(abs(grading.x) / white, mid.x), pw(abs(grading.y) / white, mid.y), pw(abs(grading.z) / white, mid.z)) * sgn * white;
    let yrg1 = yrg_of(mulm(GRADING_TO_LMS, grading));
    var y1 = pw(yrg1.x / white, prm[$P_MIDTONES_Y]) * white;
    let grey = prm[$P_GREY_FULCRUM];
    y1 = grey * pw(y1 / grey, prm[$P_CONTRAST]);
    var xyz = mulm(LMS_TO_XYZ, lms_of(y1, yrg1.y, yrg1.z));
    xyz = vec3<f32>(finite_or(xyz.x, 0.0), finite_or(xyz.y, 0.0), finite_or(xyz.z, 0.0));

    // perceptual saturation and brilliance in darktable UCS, with the gamut map
    let L_white = prm[$P_L_WHITE];
    let xyzc = max(xyz, vec3<f32>(0.0));
    let sum = xyzc.x + xyzc.y + xyzc.z;
    var x = $D65_X;
    var y = $D65_Y;
    if (sum > 0.0) { x = xyzc.x / sum; y = xyzc.y / sum; }
    let d0 = -0.783941002840055 * x + 0.277512987809202 * y + 0.153836578598858;
    let d1 = 0.745273540913283 * x - 0.205375866083878 * y - 0.165478376301988;
    let d2 = 0.318707282433486 * x + 2.16743692732158 * y + 0.291320554395942;
    var div = max(1.17549435e-38, d2);
    if (d2 < 0.0) { div = min(-1.17549435e-38, d2); }
    let uu = d0 / div;
    let vv = d1 / div;
    let us = 1.39656225667 * uu / (abs(uu) + 1.49217352929);
    let vs = 1.4513954287 * vv / (abs(vv) + 1.52488637914);
    let U = -1.124983854323892 * us - 0.980483721769325 * vs;
    let V = 1.86323315098672 * us + 1.971853092390862 * vs;
    let Ls = ucs_l_of_y(xyzc.y);
    let M2 = U * U + V * V;
    let J = Ls / L_white;
    let C0 = 15.932993652962535 * pw(Ls, 0.6523997524738018) * pw(M2, 0.6007557017508491) / L_white;
    let h = atan2(V, U);
    let B = J * (pw(C0, 1.33654221029386) + 1.0);
    let radius = length(vec2<f32>(C0, B));
    var sin_t = 0.0;
    var cos_t = 0.0;
    if (radius > 0.0) { sin_t = C0 / radius; cos_t = B / radius; }
    let P = max(1.17549435e-38, C0);
    let W = sin_t * C0 + cos_t * B;
    let a0 = max(1.0 + prm[$P_SATURATION_GLOBAL] + alpha * sat_z.x + gamma * sat_z.y + beta * sat_z.z, 0.0);
    let b0 = max(1.0 + prm[$P_BRILLIANCE_GLOBAL] + alpha * bri_z.x + gamma * bri_z.y + beta * bri_z.z, 0.0);
    let max_a = length(vec2<f32>(P, W)) / P;
    let a1 = soft_clip(a0, 0.5 * max_a, max_a);
    let P2 = (a1 - 1.0) * P;
    let W2 = sqrt(max(P * P * (1.0 - a1 * a1) + W * W, 0.0)) * b0;
    let C2 = max(cos_t * P2 + sin_t * W2, 0.0);
    let B2 = max(-sin_t * P2 + cos_t * W2, 0.0);
    let J2 = B2 / (pw(C2, 1.33654221029386) + 1.0);
    let max_colorfulness = lookup_gamut(h);
    let max_chroma = 15.932993652962535 * pw(J2 * L_white, 0.6523997524738018) * pw(max_colorfulness, 0.6007557017508491) / L_white;
    let B_b = J2 * (pw(max_chroma, 1.33654221029386) + 1.0);
    var S_b = 0.0;
    if (B_b > 0.0) { S_b = max_chroma / B_b; }
    var S = 0.0;
    if (B2 > 0.0) { S = C2 / B2; }
    S = soft_clip(S, 0.8 * S_b, S_b);
    let C3 = S * B2;
    let J3 = B2 / (pw(C3, 1.33654221029386) + 1.0);
    let L3 = clamp(J3 * L_white, 0.0, $L_UPPER);
    var Mm = 0.0;
    if (L3 != 0.0) { Mm = pw(C3 * L_white / (15.932993652962535 * pw(L3, 0.6523997524738018)), 0.8322850678616855); }
    let Us = Mm * cos(h);
    let Vs = Mm * sin(h);
    let q0 = -5.037522385190711 * Us - 2.504856328185843 * Vs;
    let q1 = 4.760029407436461 * Us + 2.874012963239247 * Vs;
    let Uu = -1.49217352929 * q0 / (abs(q0) - 1.39656225667);
    let Vv = -1.52488637914 * q1 / (abs(q1) - 1.4513954287);
    let xd0 = 0.167171472114775 * Uu + 0.141299802443708 * Vv - 0.00801531300850582;
    let xd1 = -0.150959086409163 * Uu - 0.155185060382272 * Vv - 0.00843312433578007;
    let xd2 = 0.940254742367256 * Uu + 1.0 * Vv - 0.0256325967652889;
    var div2 = max(1.17549435e-38, xd2);
    if (xd2 < 0.0) { div2 = min(-1.17549435e-38, xd2); }
    let xo = xd0 / div2;
    let yo = xd1 / div2;
    let Yo = y_of_ucs_l(L3);
    var out_xyz = vec3<f32>(0.0);
    if (yo != 0.0) { out_xyz = vec3<f32>(Yo * xo / yo, Yo, Yo * (1.0 - xo - yo) / yo); }
    out_xyz = vec3<f32>(finite_or(out_xyz.x, 0.0), finite_or(out_xyz.y, 0.0), finite_or(out_xyz.z, 0.0));
    let rgb = max(mulm(XYZ_TO_SRGB, out_xyz), vec3<f32>(0.0));
    return vec3<f32>(linear_to_srgb(rgb.x), linear_to_srgb(rgb.y), linear_to_srgb(rgb.z));
}

@compute @workgroup_size($WG)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= arrayLength(&src)) { return; }
    let p = src[i];
    let srgb = vec3<f32>(f32(p & 255u), f32((p >> 8u) & 255u), f32((p >> 16u) & 255u)) / 255.0;
    let o = grade(srgb);
    let q = vec3<u32>(u32(clamp(round(o.x * 255.0), 0.0, 255.0)), u32(clamp(round(o.y * 255.0), 0.0, 255.0)), u32(clamp(round(o.z * 255.0), 0.0, 255.0)));
    dst[i] = q.x | (q.y << 8u) | (q.z << 16u) | (255u << 24u);
}
""")


class _Program:
    def __init__(self, device):
        import wgpu

        self.wgpu = wgpu
        self.device = device
        stage = wgpu.ShaderStage.COMPUTE
        kinds = ["read-only-storage", "storage", "read-only-storage"]
        self.layout = device.create_bind_group_layout(entries=[{"binding": i, "visibility": stage, "buffer": {"type": kind}} for i, kind in enumerate(kinds)])
        module = device.create_shader_module(code=_source())
        pipeline_layout = device.create_pipeline_layout(bind_group_layouts=[self.layout])
        self.pipeline = device.create_compute_pipeline(layout=pipeline_layout, compute={"module": module, "entry_point": "main"})
        usage = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.COPY_SRC
        self.src = device.create_buffer(size=MAX_BAND_PIXELS * 4, usage=usage)
        self.dst = device.create_buffer(size=MAX_BAND_PIXELS * 4, usage=usage)
        self.params = device.create_buffer(size=PARAM_COUNT * 4, usage=usage)
        self.group = device.create_bind_group(layout=self.layout, entries=[{"binding": i, "resource": {"buffer": b, "offset": 0, "size": b.size}} for i, b in enumerate((self.src, self.dst, self.params))])


def _program(device) -> _Program:
    key = id(device)
    if key not in _programs:
        _programs.clear()
        _programs[key] = _Program(device)
    return _programs[key]


def usable(shape) -> bool:
    return enabled() and len(shape) == 3 and shape[2] == 3 and shape[0] * shape[1] >= MIN_PIXELS and gpu_device.available()


def warm_up() -> bool:
    """Open the card and compile the shader now, so the first Color Balance RGB does not wait for it."""
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


def parameters(values: dict) -> np.ndarray | None:
    """The floats the shader reads for these settings, or None when the formula is the one the shader does not have (JzAzBz)."""
    from ..colorbalancergb import logic as C

    d = C._commit({**C.DEFAULTS, **values})
    if d["formula"] != C.FORMULA_DTUCS:
        return None
    prm = np.zeros(PARAM_COUNT, dtype=np.float32)
    scalars = dict(d)
    scalars.update({"cos_hue": np.cos(d["hue_angle"]), "sin_hue": np.sin(d["hue_angle"]), "L_white": float(C._y_to_ucs_l(d["white_fulcrum"]))})
    for i, name in enumerate(PARAMS):
        prm[i] = scalars[name]
    for i, name in enumerate(VECTORS):
        prm[SCALARS + 3 * i: SCALARS + 3 * i + 3] = np.asarray(d[name], dtype=np.float64)
    prm[LUT_AT: LUT_AT + 512] = C._gamut_lut(C.FORMULA_DTUCS)
    return prm


def process(pixels: np.ndarray, values: dict) -> np.ndarray | None:
    """Color Balance RGB on the card for an 8-bit picture (the same result as the processor's apply_color_balance, to within a level), or None when the card is not to be used."""
    if pixels.dtype != np.uint8 or not usable(pixels.shape):
        return None
    prm = parameters(values)
    if prm is None:
        return None
    try:
        with _lock:
            device = gpu_device.get_device()
            prog = _program(device)
            queue = device.queue
            queue.write_buffer(prog.params, 0, prm)
            h, w = pixels.shape[:2]
            flat = pixels.reshape(-1, 3)
            out = np.empty_like(pixels).reshape(-1, 3)
            throttle = Throttle(limit())
            band = Throttle.next_band_pixels(0, 0.0)
            at = 0
            total = h * w
            while at < total:
                n = min(band, total - at)
                started = time.perf_counter()
                packed = np.empty((n, 4), dtype=np.uint8)
                packed[:, :3] = flat[at: at + n]
                packed[:, 3] = 255
                queue.write_buffer(prog.src, 0, packed.view(np.uint32).reshape(-1))
                encoder = device.create_command_encoder()
                compute = encoder.begin_compute_pass()
                compute.set_pipeline(prog.pipeline)
                compute.set_bind_group(0, prog.group)
                compute.dispatch_workgroups((n + WORKGROUP - 1) // WORKGROUP, 1, 1)
                compute.end()
                queue.submit([encoder.finish()])
                data = queue.read_buffer(prog.dst, 0, n * 4)
                out[at: at + n] = np.frombuffer(data, dtype=np.uint8, count=n * 4).reshape(n, 4)[:, :3]
                busy = time.perf_counter() - started
                throttle.after_band(busy)
                band = Throttle.next_band_pixels(n, busy)
                at += n
            STATS["runs"] += 1
            STATS["pixels"] += total
            return out.reshape(pixels.shape)
    except Exception as exc:
        gpu_device.disable(f"{exc.__class__.__name__}: {exc}")
        return None
