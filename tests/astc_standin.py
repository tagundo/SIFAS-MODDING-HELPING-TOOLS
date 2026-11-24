"""A test-only astcenc command line built on ARM's library (astc-encoder-py).

The apps ship the real astcenc 4.8 as ASTCENC_BIN. Test machines may only have
a decode-only stand-in, so tests that re-encode ASTC blocks write this one to a
temporary folder. It accepts the two command shapes the tools use:

  astcenc -dl IN.astc OUT.(tga|png) [-j N]
  astcenc -cl IN.png OUT.astc BxB -exhaustive [-decode_unorm8] [-j N]

and refuses anything else, so the product's arguments are checked as well.
"""
import os
import stat
import sys

SCRIPT = r'''
import sys
import astc_encoder as A
from PIL import Image
a = sys.argv[1:]
threads = 1
if "-j" in a:
    i = a.index("-j"); threads = max(1, int(a[i + 1])); del a[i:i + 2]
if len(a) == 3 and a[0] == "-dl":
    raw = open(a[1], "rb").read()
    if raw[:4] != b"\x13\xab\xa1\x5c" or raw[6] != 1:
        sys.exit("not a 2D .astc file")
    w, h = (int.from_bytes(raw[i:i + 3], "little") for i in (7, 10))
    flags = A.ASTCConfigFlags.DECOMPRESS_ONLY | A.ASTCConfigFlags.USE_DECODE_UNORM8
    ctx = A.ASTCContext(A.ASTCConfig(A.ASTCProfile.LDR, raw[4], raw[5], 1, 0, flags), threads)
    img = A.ASTCImage(A.ASTCType.U8, w, h, 1)
    ctx.decompress(raw[16:], img, A.ASTCSwizzle.from_str("RGBA"))
    Image.frombytes("RGBA", (w, h), bytes(img.data)).save(a[2])
    sys.exit(0)
if len(a) in (5, 6) and a[0] == "-cl" and a[4] == "-exhaustive" and a[5:] in ([], ["-decode_unorm8"]):
    bx, by = (int(v) for v in a[3].split("x"))
    with Image.open(a[1]) as source:
        image = source.convert("RGBA")
    flags = A.ASTCConfigFlags.USE_DECODE_UNORM8 if a[5:] else 0
    ctx = A.ASTCContext(A.ASTCConfig(A.ASTCProfile.LDR, bx, by, 1, int(A.ASTCQualityPreset.EXHAUSTIVE), flags), threads)
    blocks = ctx.compress(A.ASTCImage(A.ASTCType.U8, image.width, image.height, 1, image.tobytes()), A.ASTCSwizzle.from_str("RGBA"))
    header = (b"\x13\xab\xa1\x5c" + bytes((bx, by, 1)) + image.width.to_bytes(3, "little")
              + image.height.to_bytes(3, "little") + (1).to_bytes(3, "little"))
    with open(a[2], "wb") as stream:
        stream.write(header + bytes(blocks))
    sys.exit(0)
sys.exit("unsupported astcenc arguments: " + " ".join(sys.argv[1:]))
'''


def available():
    try:
        import astc_encoder  # noqa: F401
        return True
    except Exception:
        return False


def write(directory, *, decode_only=False):
    """Write the stand-in into ``directory``; returns its path."""
    path = os.path.join(str(directory), "astcenc-decode-only" if decode_only else "astcenc")
    body = SCRIPT
    if decode_only:
        body = body.replace('if len(a) in (5, 6) and a[0] == "-cl"', 'if False')
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("#!" + sys.executable + " -I\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


FAULTY = r'''
import os
import sys
import time
target, mode, state = TARGET, MODE, STATE
args = sys.argv[1:]
if args[:1] == ["-cl"]:
    open(os.path.join(state, "encoded"), "w").close()
elif args[:1] == ["-dl"] and os.path.exists(os.path.join(state, "encoded")) and not os.path.exists(os.path.join(state, "faulted")):
    open(os.path.join(state, "faulted"), "w").close()
    if mode == "fail":
        sys.exit("astcenc: simulated decoder error")
    if mode == "garbage":
        with open(args[2], "wb") as stream:
            stream.write(b"garbage")
        sys.exit(0)
    if mode == "slow":
        time.sleep(600)
os.execv(target, [target] + args)
'''


def write_faulty(directory, target, mode):
    """An astcenc that runs ``target`` but spoils the first decode after an encode.

    That decode is the astc-keep splice's check of its first re-encoded level.
    ``mode`` is "fail" (exits 1), "garbage" (exits 0 with an unreadable image)
    or "slow" (never finishes in time). Every other call runs ``target``.
    """
    state = os.path.join(str(directory), "faulty-" + mode)
    os.makedirs(state, exist_ok=True)
    path = os.path.join(state, "astcenc")
    body = FAULTY.replace("TARGET, MODE, STATE", ", ".join(map(repr, (os.path.abspath(target), mode, state))))
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("#!" + sys.executable + " -I\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def compress(image, block):
    """Raw ASTC blocks of a PIL image whose first row is block row 0 (tests only)."""
    import astc_encoder as A
    rgba = image.convert("RGBA")
    ctx = A.ASTCContext(A.ASTCConfig(A.ASTCProfile.LDR, block, block, 1, int(A.ASTCQualityPreset.MEDIUM),
                                     A.ASTCConfigFlags.USE_DECODE_UNORM8), 1)
    return bytes(ctx.compress(A.ASTCImage(A.ASTCType.U8, rgba.width, rgba.height, 1, rgba.tobytes()),
                              A.ASTCSwizzle.from_str("RGBA")))
