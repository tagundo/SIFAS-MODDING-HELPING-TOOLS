"""Neutral UnityFS pair with different triangulations at both .5/.92 cuts."""
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
import UnityPy
import costume_part_transplant as part
import lower_body_swap as lower
from webtools.core import model_edits
from test_viewer_transplants import costume_fixture


def fixture_bytes(donor=False):
    raw = costume_fixture()
    env = UnityPy.load(raw)
    body = lower.BodyMesh(env, 'neutral-seam.unity')
    bone = body.bones.index('LeftUpLeg')
    info = model_edits._inspect(raw)
    worlds = model_edits._worlds({key: model_edits._matrix(value) for key, value in info['effective'].items()}, info['parents'])
    pointer = body.smr['m_Bones'][bone]['m_PathID']
    matrix = worlds[(0, pointer)] @ part.mat_from(body.tt['m_BindPose'][bone])
    corners = np.array([[-.25, .1, .02], [.25, .1, .02], [.25, 1.1, .02], [-.25, 1.1, .02]])
    indices = [0, 1, 3, 1, 2, 3] if donor else [0, 1, 2, 0, 2, 3]
    local = (np.column_stack([corners[indices], np.ones(6)]) @ np.linalg.inv(matrix).T)[:, :3]
    channels = lower._chan_locs(body.tt)
    data = bytearray(body.tt['m_VertexData']['m_DataSize'])
    for vertex in range(6):
        for channel, values, fmt in ((0, local[vertex], '<3f'), (12, [1., 0., 0., 0.], '<4f'), (13, [bone, 0, 0, 0], '<4i')):
            stream, offset, *_ = channels[channel]
            struct.pack_into(fmt, data, body.off[stream] + vertex * body.st[stream] + offset, *values)
    body.tt['m_VertexData']['m_DataSize'] = bytes(data)
    part._recompute_local_aabb(body.tt)
    body.mesh_obj.save_typetree(body.tt)
    return env.file.save(packer='original')


def write_pair(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    result = {'cutLow': .5, 'cutHigh': .92, 'planeZ': .02, 'holeProbe': [-.2, .65], 'rectangle': [-.25, .1, .25, 1.1]}
    for name, donor in (('target', False), ('donor', True)):
        path = directory / ('lower-seam-' + name + '.unity')
        raw = fixture_bytes(donor)
        path.write_bytes(raw)
        result[name] = {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return result


if __name__ == '__main__':
    import sys
    print(json.dumps(write_pair(sys.argv[1]), indent=2))
