"""Author a neutral texture; encode once; pin full, unflipped decoder pixels.

No game bundle, game image, original game coordinates, or private asset is read.
Run with the existing pinned host Python environment after building upstream.
"""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import struct
import subprocess
from PIL import Image

ROOT = Path(__file__).resolve().parent
PIN = '8708900eca8ec609d279270e72936258f81ddfb7'
ENCODER = ROOT / 'upstream/crnlib/crunch'
WIDTH = HEIGHT = 16


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def author():
    # Different X/Y coefficients and a distinct diagonal mark make channel,
    # transpose and vertical-flip mistakes observable in a compact image.
    pixels = []
    for y in range(HEIGHT):
        for x in range(WIDTH):
            red = (17 + 37 * x + 11 * y) % 256
            green = (91 + 7 * x + 43 * y) % 256
            blue = (231 + 13 * x + 19 * y) % 256
            alpha = (0, 17, 64, 127, 191, 238, 255)[(x + 2 * y) % 7]
            # Pure4×4alpha blocks guarantee exact decoded extrema despite lossy
            # EAC endpoint quantization in the remaining mixed-alpha blocks.
            if x < 4 and y < 4:
                alpha = 0
            elif x >= 12 and y >= 8:
                alpha = 255
            if x == 2 and y < 5:
                red, green, blue = 245, 41, 119
            pixels.append((red, green, blue, alpha))
    raw = bytes(channel for pixel in pixels for channel in pixel)
    (ROOT / 'input.rgba').write_bytes(raw)
    image = Image.frombytes('RGBA', (WIDTH, HEIGHT), raw)
    image.save(ROOT / 'input.png')
    # Explicit top-left-origin32bpp uncompressed TGA, with8alpha bits. Encoding
    # from TGA avoids depending on whether a PNG reader normalizes alpha0RGB.
    header = struct.pack('<BBBHHBHHHHBB', 0, 0, 2, 0, 0, 0, 0, 0,
                         WIDTH, HEIGHT, 32, 0x28)
    bgra = bytes(channel for r, g, b, a in pixels for channel in (b, g, r, a))
    (ROOT / 'input.tga').write_bytes(header + bgra)
    return raw


def main():
    original = author()
    actual_pin = subprocess.check_output(['git', '-C', str(ROOT / 'upstream'),
                                         'rev-parse', 'HEAD'], text=True).strip()
    assert actual_pin == PIN
    assert importlib.metadata.version('UnityPy') == '1.25.0'
    assert importlib.metadata.version('texture2ddecoder') == '1.0.6'
    command = [str(ENCODER), '-file', str(ROOT / 'input.tga'),
               '-out', str(ROOT / 'compressed.crn'), '-fileformat', 'crn',
               '-ETC2A', '-quality', '255', '-mipMode', 'None',
               '-helperThreads', '0', '-noprogress', '-nostats']
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
    (ROOT / 'encode.stdout.txt').write_text(completed.stdout)
    (ROOT / 'encode.stderr.txt').write_text(completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    crn = (ROOT / 'compressed.crn').read_bytes()
    # Unity crunch12=ETC2A. Big-endian width/height are serialized at12/14.
    assert crn[:2] == b'Hx' and crn[18] == 12, crn[:24].hex()
    assert int.from_bytes(crn[12:14], 'big') == WIDTH
    assert int.from_bytes(crn[14:16], 'big') == HEIGHT
    import texture2ddecoder
    from UnityPy.export.Texture2DConverter import parse_image_data
    image = parse_image_data(crn, WIDTH, HEIGHT, 65, (2018, 4, 0, 0), 13, flip=False).convert('RGBA')
    expected = image.tobytes()
    blocks = texture2ddecoder.unpack_unity_crunch(crn)
    direct = Image.frombytes('RGBA', (WIDTH, HEIGHT),
                             texture2ddecoder.decode_etc2a8(blocks, WIDTH, HEIGHT),
                             'raw', 'BGRA').tobytes()
    assert expected == direct
    assert len(expected) == WIDTH * HEIGHT * 4
    rgba = list(image.getdata())
    zero = [p for p in rgba if p[3] == 0]
    assert zero and any(p[3] == 255 for p in rgba)
    assert any(0 < p[3] < 255 for p in rgba)
    assert any(any(p[:3]) for p in zero), 'Encoder did not retain nonzero alpha0 RGB'
    assert len(set(rgba)) > 32
    (ROOT / 'expected.rgba').write_bytes(expected)
    image.save(ROOT / 'expected-unflipped.png')
    flipped = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    flipped.save(ROOT / 'expected-flipped.png')
    assert expected != flipped.tobytes()
    license_raw = (ROOT / 'upstream/license.txt').read_bytes()
    (ROOT / 'UPSTREAM-LICENSE.txt').write_bytes(license_raw)
    manifest = {
        'version': 1, 'width': WIDTH, 'height': HEIGHT,
        'unityTextureFormat': 65, 'crnFormat': 12, 'crnFormatName': 'ETC2A',
        'mipLevels': crn[16], 'faces': crn[17], 'layout': 'row-major RGBA8',
        'expectedRawOrientation': 'unflipped; UnityPy.parse_image_data flip=False',
        'inputSHA': sha(original), 'compressedSHA': sha(crn), 'decodedSHA': sha(expected),
        'files': {name: {'bytes': (ROOT / name).stat().st_size,
                         'sha256': sha((ROOT / name).read_bytes())}
                  for name in ('input.rgba', 'input.tga', 'input.png', 'compressed.crn',
                               'expected.rgba', 'expected-unflipped.png', 'expected-flipped.png')},
        'pixels': {'count': WIDTH * HEIGHT, 'uniqueRGBA': len(set(rgba)),
                   'alpha0': len(zero), 'alpha255': sum(p[3] == 255 for p in rgba),
                   'partialAlpha': sum(0 < p[3] < 255 for p in rgba),
                   'alpha0NonzeroRGB': sum(any(p[:3]) for p in zero),
                   'allDecodedRGBA': [list(p) for p in rgba]},
        'provenance': {
            'authoredSource': 'generate_fixture.py author() arithmetic only; no input asset files',
            'encoderRepository': 'https://github.com/Unity-Technologies/crunch.git',
            'encoderBranch': 'unity', 'encoderCommit': PIN,
            'encoderSHA256': sha(ENCODER.read_bytes()), 'encoderCommand': command,
            'decoder': {'UnityPy': '1.25.0', 'texture2ddecoder': '1.0.6'},
            'decoderAgreement': 'UnityPy converter == direct unpack_unity_crunch + decode_etc2a8 BGRA→RGBA',
            'generatorSHA256': sha(Path(__file__).read_bytes()),
        },
        'license': {'encoder': 'Zlib', 'encoderNoticeSHA256': sha(license_raw),
                    'fixture': 'Original mechanically generated neutral test data; CC0-1.0',
                    'privateGameInputs': False},
    }
    (ROOT / 'fixture.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({k: manifest[k] for k in ('width', 'height', 'compressedSHA', 'decodedSHA')}))
    print(json.dumps({k: v for k, v in manifest['pixels'].items() if k != 'allDecodedRGBA'}))


if __name__ == '__main__':
    main()
