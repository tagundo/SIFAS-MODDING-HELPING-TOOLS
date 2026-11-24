"""Bake the client's cheek blush into a head texture, exactly as the shader does.

The GL 3.12.0 client ignores a costume's own blush settings in Live and Navi:
MemberCheekBase.Initialize binds the APK's shared Texture2DArray
``Live/Characters/facialAssets/cheek_array`` and ResetAll zeroes
_CHEEK_ON/_CheekIntensity/_CheekTexArrayIndex; only the song timeline's
MemberCheekClip drives the blush (median intensity 0.255, maximum 1.0). The
per-costume, client-safe way to get a stronger, permanent blush is to bake it
into that costume's head material _MainTex.

The Hidden/AS/Member/Main _CHEEK_ON fragment (GLES3 and Metal) multiplies
``vertex shade * _MainTex`` by ``f = 1 + I * (cheek.rgb - 1)`` before the
ambient lerp, tint lerp and rim, where

* ``cheek = tex2DArray(_CheekTex, (uv * 2.22 + (0, -1.221), layer))``,
* ``uv`` is the same TEXCOORD0 as _MainTex (no _ST transform; _MainTex_ST is
  identity on every head), in Unity's convention: v grows upwards,
* the array is RGBA32 256x256x2, one mip, bilinear, Clamp wrap (every edge
  texel is white, so a UV outside [0, 1] leaves the colour unchanged), and
* the project uses Gamma colour space: the math runs on the raw 8-bit/255
  values.

Baking ``f`` with strength ``k`` into _MainTex RGB (alpha untouched) is the
same as a permanent blush of intensity ``k``; k = 1 equals the strongest stock
timeline clip. Layer 0 ("Ppo", round patches on both cheeks) is used by 3105
of 3141 MV clips, layer 1 ("Akarame", a band across both cheeks and the nose)
by 36. The layers differ in shape only; strength is k.

Every rule here is shared bit-for-bit with web/static/texture-blush.js: both
use IEEE doubles and the same operation order, and round with floor(x + .5).
Only texels whose rounded RGB actually changes are written; a texel whose
bilinear footprint is all white has f == 1 exactly and is never touched.

The array's pixels are game data: they are never stored in this repository.
The caller supplies the payload from the costume bundle being edited, or from
a verified copy the user's own library cached earlier (see
``viewer_texture_tools``), and :func:`verify_payload` checks its hash.
"""
import hashlib
import math
import struct

# The 524288-byte RGBA32 payload of the stock cheek_array: the APK resource and
# all 1306 costume copies (Android and iOS) are byte-identical.
CHEEK_SHA256 = "26de3c60f632112a8a9617cbaac04d390936a8da3849ddfd9e28fdc5b7a34b09"
CHEEK_SIZE = 256
CHEEK_LAYERS = 2
CHEEK_LAYER_BYTES = CHEEK_SIZE * CHEEK_SIZE * 4
CHEEK_PAYLOAD_BYTES = CHEEK_LAYER_BYTES * CHEEK_LAYERS

# The compiled GLSL/Metal literals, as float32: 2.22000003 and -1.22100008
# (-1.2210000753: one float32 step from the value nearest to -1.221).
UV_SCALE = struct.unpack("<f", struct.pack("<f", 2.22))[0]
UV_OFFSET_V = struct.unpack("<f", struct.pack("<f", -1.22100008))[0]

# The layers differ in shape, not strength (strength is k): 0 = Ppo (stock
# default), two round patches on the cheeks; 1 = Akarame, one band across both
# cheeks and the bridge of the nose.
LAYERS = (0, 1)
DEFAULT_LAYER = 0

# Five named levels. k is a permanent cheek intensity (stock clips: median
# 0.255, maximum 1.0). The values split the CIEDE2000 path from "no blush" to
# the strongest level (k = 3) into five equal steps, measured at the darkest
# layer-0 texel (255, 215, 206) over REFERENCE_SKIN, then rounded to 0.05:
#
#   level        k     cheek-centre colour   CIEDE2000 to the level below
#   (none)       0     (250, 200, 194)       -
#   veryLight    0.5   (250, 184, 175)       4.69
#   light        1.05  (250, 167, 155)       4.59
#   medium       1.65  (250, 148, 132)       4.93
#   strong       2.3   (250, 128, 108)       4.90
#   veryStrong   3.0   (250, 106,  82)       5.01
#
# Over the cheek-centre skin of all ten real heads sampled (eight characters)
# and both layers, every neighbouring pair differs by 4.22 to 5.87. The
# strongest level keeps the darkest texel of either layer far from clipping:
# f >= 0.42 (B of layer 0 reaches 0 only at k = 5.20).
LEVELS = (
    ("veryLight", 0.5),
    ("light", 1.05),
    ("medium", 1.65),
    ("strong", 2.3),
    ("veryStrong", 3.0),
)
DEFAULT_LEVEL = "medium"
MAX_K = 4.0  # advanced numeric field; f stays >= 0.23 for every stock texel

# The median 5x5 cheek-centre colour of ten real heads (ch0001_co0004,
# ch0005_co0013, ch0107_co0028, ch0109_co0022, ch0206_co0001, ch0209_co0015,
# ch0210_co0017, ch0212_co0001/0002/0007) at the darkest layer-0 texel. The
# head art already carries a light painted blush there.
REFERENCE_SKIN = (250, 200, 194)
DARKEST_TEXEL = {0: (255, 215, 206), 1: (255, 210, 207)}


class BlushError(ValueError):
    pass


def level_k(name):
    for level, k in LEVELS:
        if level == name:
            return k
    raise BlushError("Choose a supported blush level.")


def checked_k(value):
    if type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= MAX_K:
        raise BlushError("Choose a blush strength between 0 and %g." % MAX_K)
    return float(value)


def checked_layer(value):
    if type(value) is not int or value not in LAYERS:
        raise BlushError("Choose the Ppo or Akarame blush type.")
    return value


def verify_payload(payload):
    """True for the exact stock cheek_array RGBA32 payload."""
    return (isinstance(payload, (bytes, bytearray)) and len(payload) == CHEEK_PAYLOAD_BYTES
            and hashlib.sha256(payload).hexdigest() == CHEEK_SHA256)


def layer_bytes(payload, layer):
    """One layer in Unity row order (row 0 is v = 0, the bottom)."""
    layer = checked_layer(layer)
    if not isinstance(payload, (bytes, bytearray)) or len(payload) != CHEEK_PAYLOAD_BYTES:
        raise BlushError("The cheek array payload has an unexpected size.")
    return bytes(payload[layer * CHEEK_LAYER_BYTES:(layer + 1) * CHEEK_LAYER_BYTES])


def layer_bounds(layer):
    """Inclusive (x0, y0, x1, y1) of non-white texels, Unity rows; None if all white."""
    x0 = y0 = CHEEK_SIZE
    x1 = y1 = -1
    for y in range(CHEEK_SIZE):
        row = layer[y * CHEEK_SIZE * 4:(y + 1) * CHEEK_SIZE * 4]
        if row.count(255) == len(row):
            continue
        for x in range(CHEEK_SIZE):
            offset = x * 4
            if row[offset] != 255 or row[offset + 1] != 255 or row[offset + 2] != 255:
                x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
    return None if x1 < 0 else (x0, y0, x1, y1)


def sample(layer, cu, cv):
    """Bilinear, Clamp-wrapped RGB of one cheek layer at Unity UV (cu, cv).

    Written as lerps so a footprint of four identical texels returns that value
    exactly (in particular 1.0 for white): untouched texels stay untouched.
    """
    x = cu * CHEEK_SIZE - 0.5
    y = cv * CHEEK_SIZE - 0.5
    xf = math.floor(x)
    yf = math.floor(y)
    fx = x - xf
    fy = y - yf
    last = CHEEK_SIZE - 1
    x0 = min(max(xf, 0), last)
    x1 = min(max(xf + 1, 0), last)
    y0 = min(max(yf, 0), last)
    y1 = min(max(yf + 1, 0), last)
    a, b = (y0 * CHEEK_SIZE + x0) * 4, (y0 * CHEEK_SIZE + x1) * 4
    c, d = (y1 * CHEEK_SIZE + x0) * 4, (y1 * CHEEK_SIZE + x1) * 4
    out = []
    for channel in range(3):
        p, q = layer[a + channel] / 255, layer[b + channel] / 255
        r, s = layer[c + channel] / 255, layer[d + channel] / 255
        bottom = p + (q - p) * fx
        top = r + (s - r) * fx
        out.append(bottom + (top - bottom) * fy)
    return out


def factor(cheek, k):
    """The shader's multiplier 1 + I * (cheek - 1), per RGB channel."""
    return [1 + k * (value - 1) for value in cheek]


def bake_value(value, f):
    """One 8-bit channel times f, rounded half up and clamped."""
    return min(255, max(0, math.floor(value * f + 0.5)))


def texel_uv(x, y, width, height):
    """Unity UV of a texel centre; (x, y) are top-left PNG coordinates."""
    return (x + 0.5) / width, 1 - (y + 0.5) / height


def cheek_uv(u, v):
    return u * UV_SCALE, v * UV_SCALE + UV_OFFSET_V


def _span(low, high, size):
    # Conservative texel range whose centres can map into [low, high] UV.
    first = max(0, math.floor(low * size - 0.5) - 2)
    last = min(size - 1, math.ceil(high * size - 0.5) + 2)
    return first, last


def region(width, height, bounds):
    """Top-left pixel rectangle (x0, y0, x1, y1) that can sample non-white texels.

    Outside it every bilinear footprint is white, f == 1 and nothing changes;
    computing only inside is an optimisation, never a different rule.
    """
    if bounds is None:
        return None
    bx0, by0, bx1, by1 = bounds
    # A sample touches texel i only when x = cu*256 - .5 lies in (i - 1, i + 1).
    cu_low, cu_high = (bx0 - 0.5) / CHEEK_SIZE, (bx1 + 1.5) / CHEEK_SIZE
    cv_low, cv_high = (by0 - 0.5) / CHEEK_SIZE, (by1 + 1.5) / CHEEK_SIZE
    u_low, u_high = cu_low / UV_SCALE, cu_high / UV_SCALE
    v_low, v_high = (cv_low - UV_OFFSET_V) / UV_SCALE, (cv_high - UV_OFFSET_V) / UV_SCALE
    # Clamp wrap repeats an edge texel for every UV beyond it. The stock array's
    # edges are white, but an edge that is not reaches the texture border.
    last = CHEEK_SIZE - 1
    u_low, u_high = (0.0 if bx0 == 0 else u_low), (1.0 if bx1 == last else u_high)
    v_low, v_high = (0.0 if by0 == 0 else v_low), (1.0 if by1 == last else v_high)
    x0, x1 = _span(u_low, u_high, width)
    # Top-left rows: y = (1 - v) * height - .5.
    y0, y1 = _span(1 - v_high, 1 - v_low, height)
    if x0 > x1 or y0 > y1:
        return None
    return x0, y0, x1, y1


def bake_rgba(rgba, width, height, layer, k, bounds=None):
    """Return (new RGBA bytes, changed texel count, changed bbox or None).

    ``rgba`` is straight RGBA in top-left row order (PNG/PIL). Alpha and every
    texel whose rounded RGB is unchanged keep their exact bytes.
    """
    k = checked_k(k)
    if len(rgba) != width * height * 4 or len(layer) != CHEEK_LAYER_BYTES:
        raise BlushError("The blush image or cheek layer has unexpected dimensions.")
    out = bytearray(rgba)
    area = region(width, height, layer_bounds(layer) if bounds is None else bounds)
    if area is None:
        return bytes(out), 0, None
    x0, y0, x1, y1 = area
    changed, box = 0, None
    for y in range(y0, y1 + 1):
        v = 1 - (y + 0.5) / height
        cv = v * UV_SCALE + UV_OFFSET_V
        for x in range(x0, x1 + 1):
            u = (x + 0.5) / width
            f = factor(sample(layer, u * UV_SCALE, cv), k)
            offset = (y * width + x) * 4
            touched = False
            for channel in range(3):
                before = out[offset + channel]
                after = bake_value(before, f[channel])
                if after != before:
                    out[offset + channel] = after
                    touched = True
            if touched:
                changed += 1
                box = (x, y, x, y) if box is None else (min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y))
    return bytes(out), changed, box


def bake_image(image, layer, k, bounds=None):
    """PIL RGBA image -> (baked PIL image, changed count)."""
    from PIL import Image
    data, changed, _ = bake_rgba(image.tobytes(), image.width, image.height, layer, k, bounds)
    return Image.frombytes("RGBA", image.size, data), changed


# --- perceptual spacing (documentation and tests) -------------------------

def _linear(value):
    value /= 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def srgb_to_lab(rgb):
    """8-bit sRGB (the Gamma-space display value) to CIE L*a*b* (D65)."""
    r, g, b = (_linear(channel) for channel in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b)
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def ciede2000(lab1, lab2):
    """CIEDE2000 colour difference (Sharma, Wu and Dalal 2005), kL = kC = kH = 1."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    mean_c = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(mean_c ** 7 / (mean_c ** 7 + 25 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0
    dl = l2 - l1
    dc = c2p - c1p
    if c1p * c2p == 0:
        dh = 0
    elif abs(h2p - h1p) <= 180:
        dh = h2p - h1p
    elif h2p - h1p > 180:
        dh = h2p - h1p - 360
    else:
        dh = h2p - h1p + 360
    dhh = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dh / 2))
    mean_l = (l1 + l2) / 2
    mean_cp = (c1p + c2p) / 2
    if c1p * c2p == 0:
        mean_h = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        mean_h = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        mean_h = (h1p + h2p + 360) / 2
    else:
        mean_h = (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(mean_h - 30)) + 0.24 * math.cos(math.radians(2 * mean_h))
         + 0.32 * math.cos(math.radians(3 * mean_h + 6)) - 0.20 * math.cos(math.radians(4 * mean_h - 63)))
    dtheta = 30 * math.exp(-((mean_h - 275) / 25) ** 2)
    rc = 2 * math.sqrt(mean_cp ** 7 / (mean_cp ** 7 + 25 ** 7))
    sl = 1 + 0.015 * (mean_l - 50) ** 2 / math.sqrt(20 + (mean_l - 50) ** 2)
    sc = 1 + 0.045 * mean_cp
    sh = 1 + 0.015 * mean_cp * t
    rt = -math.sin(math.radians(2 * dtheta)) * rc
    return math.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhh / sh) ** 2 + rt * (dc / sc) * (dhh / sh))


def centre_colour(skin, k, layer=DEFAULT_LAYER):
    """The baked colour of ``skin`` at the darkest texel of a stock layer."""
    texel = [value / 255 for value in DARKEST_TEXEL[layer]]
    return tuple(bake_value(channel, f) for channel, f in zip(skin, factor(texel, k)))


def level_differences(skin=REFERENCE_SKIN, layer=DEFAULT_LAYER):
    """CIEDE2000 between neighbouring levels, starting from no blush."""
    colours = [tuple(skin)] + [centre_colour(skin, k, layer) for _, k in LEVELS]
    labs = [srgb_to_lab(colour) for colour in colours]
    return [ciede2000(labs[index], labs[index + 1]) for index in range(len(labs) - 1)]
