"""Neutral ribbon whose upper quad is a second material joined by seam copies.

Built from viewer_persistence.unity (six vertices, two quads). The upper quad
moves to a second submesh/material and no longer uses vertices 2 and 3 but two
copies, the way game exports split a vertex at a UV seam or material border:

* vertex 6: exactly vertex 2's position, its own UV and different skin weights
  (bone 1 60 %, bone 2 40 %), so the copies would drift apart under their own
  skin maps;
* vertex 7: vertex 3's position one float32 step higher in X (seam noise that
  real exports leave), its own UV, vertex 3's weights.

The lower quad also gets a UV seam inside its own material: its second
triangle uses vertex 8, an exact copy of vertex 1 with its own UV. Two more
vertices are used by no triangle (as copies left on deleted faces are):

* vertex 9: a second exact copy of vertex 1, so {1, 8, 9} is a group of three;
* vertex 10: vertex 5 moved 1e-6 in X, a distinct nearby vertex (the closest
  distinct vertices in real costumes are 1.2e-6 apart), never a partner.

Vertices 0, 4 and 5 have no copy. All values are synthetic.
"""
import copy
import struct
from pathlib import Path

STRIDE = 56  # position, normal, uv, 4 weights, 4 byte indices, 4 byte colour


def _next_float(value):
    bits = struct.unpack('<I', struct.pack('<f', value))[0]
    return struct.unpack('<f', struct.pack('<I', bits + 1 if value >= 0 else bits - 1))[0]


def fixture_bytes():
    import UnityPy
    source = Path(__file__).parent / 'fixtures' / 'viewer_persistence.unity'
    env = UnityPy.load(source.read_bytes())
    objects = {o.path_id: o for o in env.objects}
    asset = objects[1].assets_file
    mesh = objects[1].read_typetree()
    vertex = mesh['m_VertexData']
    data = bytearray(vertex['m_DataSize'])
    assert vertex['m_VertexCount'] == 6 and len(data) == 6 * STRIDE
    copy6 = bytearray(data[2 * STRIDE:3 * STRIDE])
    struct.pack_into('<2f', copy6, 24, 0.05, 0.6)
    struct.pack_into('<4f', copy6, 32, 0.6, 0.4, 0.0, 0.0)
    struct.pack_into('<4B', copy6, 48, 1, 2, 0, 0)
    copy7 = bytearray(data[3 * STRIDE:4 * STRIDE])
    x = struct.unpack_from('<f', copy7, 0)[0]
    struct.pack_into('<f', copy7, 0, _next_float(x))
    struct.pack_into('<2f', copy7, 24, 0.95, 0.6)
    copy8 = bytearray(data[1 * STRIDE:2 * STRIDE])
    struct.pack_into('<2f', copy8, 24, 0.9, 0.08)
    copy9 = bytearray(data[1 * STRIDE:2 * STRIDE])
    struct.pack_into('<2f', copy9, 24, 0.7, 0.3)
    near10 = bytearray(data[5 * STRIDE:6 * STRIDE])
    struct.pack_into('<f', near10, 0, struct.unpack_from('<f', near10, 0)[0] + 1e-6)
    struct.pack_into('<2f', near10, 24, 0.6, 0.9)
    data += copy6 + copy7 + copy8 + copy9 + near10
    vertex['m_VertexCount'] = 11
    vertex['m_DataSize'] = bytes(data)
    lower, upper = (0, 1, 2, 8, 3, 2), (6, 7, 4, 7, 5, 4)
    mesh['m_IndexBuffer'] = struct.pack('<12H', *(lower + upper))
    first = mesh['m_SubMeshes'][0]
    first.update(indexCount=6, firstVertex=0, vertexCount=9)
    second = copy.deepcopy(first)
    second.update(firstByte=12, indexCount=6, firstVertex=4, vertexCount=4)
    mesh['m_SubMeshes'].append(second)
    objects[1].save_typetree(mesh)
    material = copy.copy(objects[13]); material.path_id = 313
    tree = copy.deepcopy(objects[13].read_typetree()); tree['m_Name'] = 'Neutral seam material'
    asset.objects[313] = material; material.save_typetree(tree)
    renderer = objects[12].read_typetree(); renderer['m_Materials'].append({'m_FileID': 0, 'm_PathID': 313})
    objects[12].save_typetree(renderer)
    return env.file.save(packer='original')


if __name__ == '__main__':
    import sys
    destination = Path(sys.argv[1]); destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(fixture_bytes())
