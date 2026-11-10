"""Add a five-level CRN from the frozen arithmetic-authored16×16 input.

Preserves every original no-mip fixture/golden/provenance file unchanged.
The pinned Python decoder supports an optional mip index although its1.0.6
type stub/help omit that parameter: src/pylink.cpp parses y*|I.
"""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import subprocess
from PIL import Image
import texture2ddecoder

ROOT = Path(__file__).resolve().parent
PIN = '8708900eca8ec609d279270e72936258f81ddfb7'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    original_manifest = (ROOT / 'handoff-sha256.json').read_bytes()
    original = json.loads(original_manifest)
    for name, row in original['files'].items():
        assert sha((ROOT / name).read_bytes()) == row['sha256'], name
    assert subprocess.check_output(['git', '-C', str(ROOT / 'upstream'),
                                    'rev-parse', 'HEAD'], text=True).strip() == PIN
    assert importlib.metadata.version('UnityPy') == '1.25.0'
    assert importlib.metadata.version('texture2ddecoder') == '1.0.6'
    command = [str(ROOT / 'upstream/crnlib/crunch'), '-file', str(ROOT / 'input.tga'),
               '-out', str(ROOT / 'compressed-mips.crn'), '-fileformat', 'crn',
               '-ETC2A', '-quality', '255', '-mipMode', 'Generate',
               '-maxmips', '5', '-minmipsize', '1', '-mipFilter', 'box',
               '-gamma', '1.0', '-helperThreads', '0', '-noprogress', '-nostats']
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
    (ROOT / 'encode-mips.stdout.txt').write_text(completed.stdout)
    (ROOT / 'encode-mips.stderr.txt').write_text(completed.stderr)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    crn = (ROOT / 'compressed-mips.crn').read_bytes()
    assert crn[:2] == b'Hx' and crn[18] == 12
    assert int.from_bytes(crn[12:14], 'big') == int.from_bytes(crn[14:16], 'big') == 16
    assert crn[16] == 5 and crn[17] == 1
    directory = ROOT / 'mips'
    directory.mkdir(exist_ok=True)
    levels = []
    for level in range(5):
        width = height = max(1, 16 >> level)
        blocks = texture2ddecoder.unpack_unity_crunch(crn, level)
        assert len(blocks) == max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 16
        rgba = Image.frombytes('RGBA', (width, height),
                               texture2ddecoder.decode_etc2a8(blocks, width, height),
                               'raw', 'BGRA')
        raw = rgba.tobytes()
        display = rgba.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
        assert len(raw) == width * height * 4
        (directory / f'level-{level}.rgba').write_bytes(raw)
        rgba.save(directory / f'level-{level}-unflipped.png')
        rgba.transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(directory / f'level-{level}-display.png')
        pixels = list(rgba.getdata())
        levels.append({'level': level, 'width': width, 'height': height,
                       'rgba_bytes': len(raw), 'unpacked_etc2a_block_bytes': len(blocks),
                       'rgba_unflipped_sha256': sha(raw),
                       'rgba_display_sha256': sha(display),
                       'zero_alpha_nonzero_rgb_pixels': sum(p[3] == 0 and any(p[:3]) for p in pixels),
                       'partial_alpha_pixels': sum(0 < p[3] < 255 for p in pixels),
                       'raw_file': f'mips/level-{level}.rgba'})
    for name, row in original['files'].items():
        assert sha((ROOT / name).read_bytes()) == row['sha256'], name
    manifest = {'version': 1, 'width': 16, 'height': 16, 'texture_format': 65,
                'crunch_format': 12, 'mip_count': 5,
                'encoded_bytes': len(crn), 'encoded_sha256': sha(crn),
                'source_rgba_sha256': sha((ROOT / 'input.rgba').read_bytes()),
                'levels': levels,
                'provenance': {'encoder_repository': 'https://github.com/Unity-Technologies/crunch.git',
                               'encoder_commit': PIN, 'encoder_binary_sha256': sha((ROOT / 'upstream/crnlib/crunch').read_bytes()),
                               'encoder_command': command,
                               'reference_package': {'UnityPy': '1.25.0', 'texture2ddecoder': '1.0.6'},
                               'reference_mip_api': 'texture2ddecoder.unpack_unity_crunch(encoded, level_index); pinned pylink.cpp PyArg_ParseTuple y*|I',
                               'reference_rgba': 'decode_etc2a8(blocks,width,height), BGRA to RGBA; unflipped then exactly one vertical display flip',
                               'generator_sha256': sha(Path(__file__).read_bytes())},
                'base_no_mip_fixture_and_goldens_unchanged': True,
                'base_handoff_manifest_sha256': sha(original_manifest),
                'private_game_inputs': False,
                'license': 'CC0-1.0 mechanically authored fixture; encoder Zlib notice separately preserved'}
    (ROOT / 'mips-fixture.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'status': 'PASS_FIVE_AUTHORED_MIPS_FROZEN_BASE_UNCHANGED',
                      'encoded_bytes': len(crn), 'encoded_sha256': sha(crn), 'levels': levels}))


if __name__ == '__main__':
    main()
