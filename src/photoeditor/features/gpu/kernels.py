"""The compute shader (WGSL) for the per-pixel stages, and the layout of the numbers it is given - no wgpu import, so this can be read and tested anywhere.

One kernel does every stage that works on each pixel by itself, in the order the CPU pipeline runs them, and rounds to 8 bits after each stage exactly as the CPU stage does (for a
16-bit picture, F_WIDE, there is no rounding between stages and the picture is read and written as 16-bit values, two to a word):
  shadows / highlights  ->  saturation  ->  the tone table (a 3 x 256 lookup)  ->  colour in OKLCH (vibrance, mixer, scanner response, toning)  ->  vignette
Which stages run is a set of flags. A thread takes four pixels (12 bytes = three 32-bit words of the packed RGB picture) so that it alone writes those words."""
from string import Template

# the flags (geo[3])
F_SH, F_SAT, F_LUT, F_COLOR, F_VIG, F_MIX, F_VIB, F_RESP, F_TONING, F_WIDE = (1 << n for n in range(10))

# geo: unsigned integers
M_WIDTH, M_FIRST_ROW, M_PIXELS, M_FLAGS, M_HEIGHT = range(5)
META_COUNT = 5

# params: floats
P_SAT_K = 0
P_VIG_STRENGTH, P_VIG_MW, P_VIG_MH = 1, 2, 3
P_VIBRANCE = 4
P_RESP_AMOUNT, P_RESP_SCALE = 5, 6
P_RESP_CAST = 8        # 6: the (a, b) cast of the shadows, midtones and highlights
P_TONE_COS = 14        # 3
P_TONE_SIN = 17        # 3
P_TONE_STRENGTH = 20   # 3
P_M1INV = 24           # 9
P_M2INV = 33           # 9
P_MIX = 42             # 24: hue x 8, saturation x 8, lightness x 8
P_GAIN = 66            # 256: the shadows / highlights gain of each brightness
PARAM_COUNT = 322

WORKGROUP = 64

_SOURCE = Template(r"""
@group(0) @binding(0) var<storage, read> src: array<u32>;
@group(0) @binding(1) var<storage, read_write> dst: array<u32>;
@group(0) @binding(2) var<storage, read> prm: array<f32>;
@group(0) @binding(3) var<storage, read> lut: array<u32>;
@group(0) @binding(4) var<storage, read> vig: array<f32>;
@group(0) @binding(5) var<storage, read> geo: array<u32>;

const LUMA = vec3<f32>(0.299, 0.587, 0.114);
var<private> BAND_HUE = array<f32, 8>(29.0, 55.0, 100.0, 145.0, 195.0, 262.0, 305.0, 345.0);

fn wrap(x: f32, m: f32) -> f32 { return x - m * floor(x / m); }

fn sstep(e0: f32, e1: f32, x: f32) -> f32 {
    let t = clamp((x - e0) / (e1 - e0), 0.0, 1.0);
    return t * t * (3.0 - 2.0 * t);
}

fn is_wide() -> bool { return (geo[$M_FLAGS] & $F_WIDE) != 0u; }

// what a stage rounds to: the 8-bit picture's whole levels, or - for a 16-bit picture - nothing (the fraction is carried on to the next stage and the end)
fn round8(x: vec3<f32>) -> vec3<f32> {
    if (is_wide()) { return clamp(x, vec3<f32>(0.0), vec3<f32>(255.0)); }
    return floor(clamp(x + vec3<f32>(0.5), vec3<f32>(0.0), vec3<f32>(255.0)));
}

fn trunc8(x: vec3<f32>) -> vec3<f32> {
    if (is_wide()) { return clamp(x, vec3<f32>(0.0), vec3<f32>(255.0)); }
    return floor(clamp(x, vec3<f32>(0.0), vec3<f32>(255.0)));
}

fn stage_sh(v: vec3<f32>) -> vec3<f32> {
    let luma = dot(v, LUMA);
    var gain: f32;
    if (is_wide()) {
        // the brightness is looked up between the two neighbouring entries of the gain table, not rounded to one of them
        let y = clamp(luma, 0.0, 255.0);
        let i0 = min(u32(y), 254u);
        let fr = y - f32(i0);
        gain = prm[$P_GAIN + i0] * (1.0 - fr) + prm[$P_GAIN + i0 + 1u] * fr;
    } else {
        let li = u32(clamp(round(luma), 0.0, 255.0));
        gain = prm[$P_GAIN + li];
    }
    let brightest = max(v.x, max(v.y, v.z));
    gain = min(gain, 255.0 / max(brightest, 1.0));
    return round8(v * gain);
}

fn stage_sat(v: vec3<f32>) -> vec3<f32> {
    let gray = dot(v, LUMA);
    let out = (v - vec3<f32>(gray)) * prm[$P_SAT_K] + vec3<f32>(gray);
    return trunc8(out);
}

fn stage_lut(v: vec3<f32>) -> vec3<f32> {
    if (is_wide()) {
        // a table of 65536 entries a channel, holding 16-bit values; the picture is on the 0-255 scale, so 257 per level
        let i = vec3<u32>(u32(clamp(round(v.x * 257.0), 0.0, 65535.0)), u32(clamp(round(v.y * 257.0), 0.0, 65535.0)), u32(clamp(round(v.z * 257.0), 0.0, 65535.0)));
        return vec3<f32>(f32(lut[i.x]), f32(lut[65536u + i.y]), f32(lut[131072u + i.z])) / 257.0;
    }
    return vec3<f32>(f32(lut[u32(v.x)]), f32(lut[256u + u32(v.y)]), f32(lut[512u + u32(v.z)]));
}

fn srgb_to_linear(x: f32) -> f32 {
    let c = x / 255.0;
    if (c <= 0.04045) { return c / 12.92; }
    return pow((c + 0.055) / 1.055, 2.4);
}

fn linear_to_srgb(x: f32) -> f32 {
    let c = clamp(x, 0.0, 1.0);
    if (c <= 0.0031308) { return c * 12.92; }
    return 1.055 * pow(c, 1.0 / 2.4) - 0.055;
}

fn cbrt0(x: f32) -> f32 {
    if (x <= 0.0) { return 0.0; }
    return pow(x, 1.0 / 3.0);
}

fn oklab_from_srgb8(v: vec3<f32>) -> vec3<f32> {
    let c = vec3<f32>(srgb_to_linear(v.x), srgb_to_linear(v.y), srgb_to_linear(v.z));
    let l = max(dot(vec3<f32>(0.4122214708, 0.5363325363, 0.0514459929), c), 0.0);
    let m = max(dot(vec3<f32>(0.2119034982, 0.6806995451, 0.1073969566), c), 0.0);
    let s = max(dot(vec3<f32>(0.0883024619, 0.2817188376, 0.6299787005), c), 0.0);
    let q = vec3<f32>(cbrt0(l), cbrt0(m), cbrt0(s));
    return vec3<f32>(
        dot(vec3<f32>(0.2104542553, 0.7936177850, -0.0040720468), q),
        dot(vec3<f32>(1.9779984951, -2.4285922050, 0.4505937099), q),
        dot(vec3<f32>(0.0259040371, 0.7827717662, -0.8086757660), q));
}

fn row3(base: u32) -> vec3<f32> { return vec3<f32>(prm[base], prm[base + 1u], prm[base + 2u]); }

fn oklab_to_linear(lab: vec3<f32>) -> vec3<f32> {
    let q = vec3<f32>(dot(row3($P_M2INV), lab), dot(row3($P_M2INV + 3u), lab), dot(row3($P_M2INV + 6u), lab));
    let c = q * q * q;
    return vec3<f32>(dot(row3($P_M1INV), c), dot(row3($P_M1INV + 3u), c), dot(row3($P_M1INV + 6u), c));
}

fn oklab_to_srgb8(lab_in: vec3<f32>) -> vec3<f32> {
    var lab = lab_in;
    for (var i = 0; i < 6; i = i + 1) {
        let rgb = oklab_to_linear(lab);
        let lo = min(rgb.x, min(rgb.y, rgb.z));
        let hi = max(rgb.x, max(rgb.y, rgb.z));
        if (lo < -0.0005 || hi > 1.0005) {
            lab.y = lab.y * 0.85;
            lab.z = lab.z * 0.85;
        } else {
            break;
        }
    }
    let rgb = oklab_to_linear(lab);
    let out = vec3<f32>(linear_to_srgb(rgb.x), linear_to_srgb(rgb.y), linear_to_srgb(rgb.z)) * 255.0;
    if (is_wide()) { return clamp(out, vec3<f32>(0.0), vec3<f32>(255.0)); }
    return clamp(round(out), vec3<f32>(0.0), vec3<f32>(255.0));
}

fn stage_color(v: vec3<f32>, flags: u32) -> vec3<f32> {
    let lab = oklab_from_srgb8(v);
    var light = lab.x;
    var chroma = length(vec2<f32>(lab.y, lab.z));
    var hue = wrap(degrees(atan2(lab.z, lab.y)), 360.0);
    let colourful = sstep(0.012, 0.06, chroma);
    if ((flags & $F_MIX) != 0u) {
        var raw: array<f32, 8>;
        var total = 0.0;
        for (var i = 0u; i < 8u; i = i + 1u) {
            let d = abs(wrap(hue - BAND_HUE[i] + 180.0, 360.0) - 180.0);
            var w = 0.0;
            if (d < 60.0) { w = 0.5 * (1.0 + cos(3.14159265358979 * d / 60.0)); }
            raw[i] = w;
            total = total + w;
        }
        total = max(total, 1e-6);
        var d_hue = 0.0;
        var d_sat = 0.0;
        var d_lum = 0.0;
        for (var i = 0u; i < 8u; i = i + 1u) {
            let wb = raw[i] / total * colourful;
            d_hue = d_hue + prm[$P_MIX + i] * wb;
            d_sat = d_sat + prm[$P_MIX + 8u + i] * wb;
            d_lum = d_lum + prm[$P_MIX + 16u + i] * wb;
        }
        hue = wrap(hue + d_hue * 30.0, 360.0);
        chroma = chroma * clamp(1.0 + d_sat, 0.0, 3.0);
        light = clamp(light + d_lum * 0.12, 0.0, 1.0);
    }
    if ((flags & $F_VIB) != 0u) {
        let muted = 1.0 - sstep(0.03, 0.22, chroma);
        let skin = abs(wrap(hue - 52.5 + 180.0, 360.0) - 180.0);
        let guard = 1.0 - 0.6 * (1.0 - sstep(22.5, 47.5, skin));
        chroma = chroma * clamp(1.0 + prm[$P_VIBRANCE] * muted * guard * sstep(0.004, 0.025, chroma), 0.0, 3.0);
    }
    var a = chroma * cos(radians(hue));
    var b = chroma * sin(radians(hue));
    let shadows = 1.0 - sstep(0.18, 0.60, light);
    let highs = sstep(0.50, 0.90, light);
    let mids = clamp(1.0 - shadows - highs, 0.0, 1.0);
    if ((flags & $F_RESP) != 0u) {
        let amount = prm[$P_RESP_AMOUNT];
        a = a + amount * prm[$P_RESP_CAST] * shadows + amount * prm[$P_RESP_CAST + 2u] * mids + amount * prm[$P_RESP_CAST + 4u] * highs;
        b = b + amount * prm[$P_RESP_CAST + 1u] * shadows + amount * prm[$P_RESP_CAST + 3u] * mids + amount * prm[$P_RESP_CAST + 5u] * highs;
        let scale = prm[$P_RESP_SCALE];
        a = a * scale;
        b = b * scale;
    }
    if ((flags & $F_TONING) != 0u) {
        for (var r = 0u; r < 3u; r = r + 1u) {
            var wr = shadows;
            if (r == 1u) { wr = mids; }
            if (r == 2u) { wr = highs; }
            let strength = prm[$P_TONE_STRENGTH + r];
            a = a + prm[$P_TONE_COS + r] * 0.08 * strength * wr;
            b = b + prm[$P_TONE_SIN + r] * 0.08 * strength * wr;
        }
    }
    return oklab_to_srgb8(vec3<f32>(light, a, b));
}

fn stage_vig(v: vec3<f32>, x: u32, y: u32) -> vec3<f32> {
    let mw = prm[$P_VIG_MW];
    let mh = prm[$P_VIG_MH];
    let fx = (f32(x) + 0.5) * mw / f32(geo[$M_WIDTH]) - 0.5;
    let fy = (f32(y) + 0.5) * mh / f32(geo[$M_HEIGHT]) - 0.5;
    let x0 = floor(fx);
    let y0 = floor(fy);
    let ax = fx - x0;
    let ay = fy - y0;
    let imw = i32(mw);
    let imh = i32(mh);
    let xa = u32(clamp(i32(x0), 0, imw - 1));
    let xb = u32(clamp(i32(x0) + 1, 0, imw - 1));
    let ya = u32(clamp(i32(y0), 0, imh - 1));
    let yb = u32(clamp(i32(y0) + 1, 0, imh - 1));
    let w = u32(imw);
    let top = vig[ya * w + xa] * (1.0 - ax) + vig[ya * w + xb] * ax;
    let bottom = vig[yb * w + xa] * (1.0 - ax) + vig[yb * w + xb] * ax;
    let weight = top * (1.0 - ay) + bottom * ay;
    let strength = prm[$P_VIG_STRENGTH];
    var out: vec3<f32>;
    if (strength > 0.0) {
        out = v * (1.0 - strength * weight);
    } else {
        out = v + (vec3<f32>(255.0) - v) * (-strength * weight);
    }
    return round8(out);
}

fn shade(v_in: vec3<f32>, idx: u32) -> vec3<f32> {
    let flags = geo[$M_FLAGS];
    var v = v_in;
    if ((flags & $F_SH) != 0u) { v = stage_sh(v); }
    if ((flags & $F_SAT) != 0u) { v = stage_sat(v); }
    if ((flags & $F_LUT) != 0u) { v = stage_lut(v); }
    if ((flags & $F_COLOR) != 0u) { v = stage_color(v, flags); }
    if ((flags & $F_VIG) != 0u) {
        let w = geo[$M_WIDTH];
        v = stage_vig(v, idx % w, idx / w);
    }
    return v;
}

fn byte_of(w: u32, k: u32) -> f32 { return f32((w >> (8u * k)) & 255u); }

fn pack3(v: vec3<f32>) -> u32 { return u32(v.x) | (u32(v.y) << 8u) | (u32(v.z) << 16u); }

@compute @workgroup_size($WORKGROUP)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let g = gid.x;
    let base = g * 4u;
    let n = geo[$M_PIXELS];
    if (base >= n) { return; }
    let w0 = src[3u * g];
    let w1 = src[3u * g + 1u];
    let w2 = src[3u * g + 2u];
    var px = array<vec3<f32>, 4>(
        vec3<f32>(byte_of(w0, 0u), byte_of(w0, 1u), byte_of(w0, 2u)),
        vec3<f32>(byte_of(w0, 3u), byte_of(w1, 0u), byte_of(w1, 1u)),
        vec3<f32>(byte_of(w1, 2u), byte_of(w1, 3u), byte_of(w2, 0u)),
        vec3<f32>(byte_of(w2, 1u), byte_of(w2, 2u), byte_of(w2, 3u)));
    let first = geo[$M_FIRST_ROW] * geo[$M_WIDTH];
    for (var k = 0u; k < 4u; k = k + 1u) {
        if (base + k < n) { px[k] = shade(px[k], first + base + k); }
    }
    let a = pack3(px[0]) | (u32(px[1].x) << 24u);
    let b = u32(px[1].y) | (u32(px[1].z) << 8u) | (u32(px[2].x) << 16u) | (u32(px[2].y) << 24u);
    let c = u32(px[2].z) | (u32(px[3].x) << 8u) | (u32(px[3].y) << 16u) | (u32(px[3].z) << 24u);
    dst[3u * g] = a;
    dst[3u * g + 1u] = b;
    dst[3u * g + 2u] = c;
}

// the 16-bit picture: a thread takes four pixels = twelve 16-bit values = six words. The values go in and out on the 0-255 scale (a 16-bit level over 257).
fn half_of(w: u32, k: u32) -> f32 { return f32((w >> (16u * k)) & 65535u) / 257.0; }

fn put16(v: f32) -> u32 { return u32(clamp(round(v * 257.0), 0.0, 65535.0)); }

@compute @workgroup_size($WORKGROUP)
fn main_wide(@builtin(global_invocation_id) gid: vec3<u32>) {
    let g = gid.x;
    let base = g * 4u;
    let n = geo[$M_PIXELS];
    if (base >= n) { return; }
    let w0 = src[6u * g];
    let w1 = src[6u * g + 1u];
    let w2 = src[6u * g + 2u];
    let w3 = src[6u * g + 3u];
    let w4 = src[6u * g + 4u];
    let w5 = src[6u * g + 5u];
    var px = array<vec3<f32>, 4>(
        vec3<f32>(half_of(w0, 0u), half_of(w0, 1u), half_of(w1, 0u)),
        vec3<f32>(half_of(w1, 1u), half_of(w2, 0u), half_of(w2, 1u)),
        vec3<f32>(half_of(w3, 0u), half_of(w3, 1u), half_of(w4, 0u)),
        vec3<f32>(half_of(w4, 1u), half_of(w5, 0u), half_of(w5, 1u)));
    let first = geo[$M_FIRST_ROW] * geo[$M_WIDTH];
    for (var k = 0u; k < 4u; k = k + 1u) {
        if (base + k < n) { px[k] = shade(px[k], first + base + k); }
    }
    dst[6u * g] = put16(px[0].x) | (put16(px[0].y) << 16u);
    dst[6u * g + 1u] = put16(px[0].z) | (put16(px[1].x) << 16u);
    dst[6u * g + 2u] = put16(px[1].y) | (put16(px[1].z) << 16u);
    dst[6u * g + 3u] = put16(px[2].x) | (put16(px[2].y) << 16u);
    dst[6u * g + 4u] = put16(px[2].z) | (put16(px[3].x) << 16u);
    dst[6u * g + 5u] = put16(px[3].y) | (put16(px[3].z) << 16u);
}
""")


def source() -> str:
    """The shader's WGSL, with the layout constants filled in."""
    names = {k: v for k, v in globals().items() if (k.startswith(("P_", "M_", "F_")) or k == "WORKGROUP") and isinstance(v, int)}
    return _SOURCE.substitute(**{k: f"{v}u" if k.startswith(("F_", "M_")) else str(v) for k, v in names.items()})
