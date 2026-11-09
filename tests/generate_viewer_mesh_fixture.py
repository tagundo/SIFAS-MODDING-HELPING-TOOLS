"""Neutral ribbon with two different materials sharing overlapping UV geometry."""
import copy
from pathlib import Path


def fixture_bytes():
    import UnityPy
    source = Path(__file__).parent / 'fixtures' / 'viewer_persistence.unity'
    env = UnityPy.load(source.read_bytes())
    objects = {o.path_id: o for o in env.objects}; asset = objects[1].assets_file
    mesh = objects[1].read_typetree(); indices = bytes(mesh['m_IndexBuffer'])
    mesh['m_IndexBuffer'] = indices + indices
    second = copy.deepcopy(mesh['m_SubMeshes'][0]); second['firstByte'] = len(indices)
    mesh['m_SubMeshes'].append(second); objects[1].save_typetree(mesh)
    texture = copy.copy(objects[14]); texture.path_id = 314
    tt = copy.deepcopy(objects[14].read_typetree()); tt['m_Name'] = 'Neutral red texture'
    tt['image data'] = bytes((240, 50, 30, 255)) * 4
    asset.objects[314] = texture; texture.save_typetree(tt)
    material = copy.copy(objects[13]); material.path_id = 313
    mt = copy.deepcopy(objects[13].read_typetree()); mt['m_Name'] = 'Neutral red material'
    mt['m_SavedProperties']['m_TexEnvs'][0][1]['m_Texture']['m_PathID'] = 314
    asset.objects[313] = material; material.save_typetree(mt)
    renderer = objects[12].read_typetree(); renderer['m_Materials'].append({'m_FileID': 0, 'm_PathID': 313})
    objects[12].save_typetree(renderer)
    return env.file.save(packer='original')


if __name__ == '__main__':
    import sys
    destination = Path(sys.argv[1]); destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(fixture_bytes())
