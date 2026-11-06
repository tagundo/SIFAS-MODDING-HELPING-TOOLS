"""Generate original neutral triangles for the dedicated body controls.

The typed object templates come from the repository's own neutral ribbon.
Every named bone has its own weighted triangle. Rotated, translated, nonunit
rest frames make child compensation observable instead of merely changing a
file's compressed bytes. No game model or motion is included.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import struct
import zlib

import numpy as np
import UnityPy


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "fixtures" / "viewer_rig.unity"
# name, parent, local position, XYZ Euler degrees, authored local scale.
BONES = (
    ("Move", None, (0, 0, 0), (0, 0, 0), (1, 1, 1)),
    ("HipsSize", "Move", (0, .5, 0), (0, 0, 12), (.9, 1.07, .96)),
    ("ButtockTip", "HipsSize", (.1, .16, .08), (18, 0, 0), (1.04, .97, 1.02)),
    ("Spine", "Move", (0, .55, 0), (0, 7, 80), (1.08, .94, 1.06)),
    ("Spine1", "Spine", (.4, .03, 0), (12, 0, -10), (.98, 1.03, .97)),
    ("Spine2", "Spine1", (.35, 0, .02), (0, -13, 5), (1.02, .96, 1.04)),
    ("Head", "Spine2", (.3, 0, 0), (0, 0, -85), (1.01, 1.04, .98)),
    ("Head_Hair", "Head", (0, .1, .04), (5, 0, 0), (1, 1, 1)),
    ("LeftUpLeg", "Move", (-.2, .45, 0), (0, 0, -80), (1.13, .92, 1.04)),
    ("LeftLeg", "LeftUpLeg", (.4, 0, 0), (0, 20, 7), (.98, 1.07, .96)),
    ("LeftFoot", "LeftLeg", (.4, 0, 0), (0, 0, 65), (1.03, .95, 1.07)),
    ("RightUpLeg", "Move", (.2, .45, 0), (0, 0, -95), (.97, 1.09, .93)),
    ("RightLeg", "RightUpLeg", (.43, .01, 0), (0, -20, -5), (1.02, .96, 1.04)),
    ("RightFoot", "RightLeg", (.4, 0, 0), (0, 0, 75), (.96, 1.05, 1.02)),
    ("LeftArm", "Spine2", (.1, .18, 0), (0, 15, 30), (1, 1, 1)),
    ("LeftForeArm", "LeftArm", (.35, 0, 0), (0, 0, 8), (1, 1, 1)),
    ("LeftHand", "LeftForeArm", (.3, 0, 0), (0, 0, 0), (1, 1, 1)),
    ("LeftHandIndex1", "LeftHand", (.1, 0, 0), (0, 0, 0), (1, 1, 1)),
    ("LeftShoulder", "Spine2", (.05, .1, 0), (0, 0, 0), (1, 1, 1)),
)
LOCAL_TRIANGLE = np.array(((.14, .08, .06), (.35, -.12, .06), (.22, .02, -.12)), float)


def vector(value):
    return dict(zip("xyz", map(float, value)))


def quaternion(euler):
    x, y, z = (math.radians(v) / 2 for v in euler)
    # qZ*qY*qX, solely to create nontrivial authored transforms.
    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
    return (sx*cy*cz-cx*sy*sz, cx*sy*cz+sx*cy*sz,
            cx*cy*sz-sx*sy*cz, cx*cy*cz+sx*sy*sz)


def local_matrix(position, rotation, scale):
    x, y, z, w = rotation
    r = np.array(((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
                  (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
                  (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y))))
    result = np.eye(4); result[:3, :3] = r @ np.diag(scale); result[:3, 3] = position
    return result


def fixture_bytes(*, missing_spine2=False, duplicate_hips=False):
    env = UnityPy.load(SOURCE.read_bytes())
    objects = {obj.path_id: obj for obj in env.objects}
    game_template, transform_template = objects[4], objects[5]
    asset = game_template.assets_file
    specs = [row for row in BONES if not (missing_spine2 and row[0] == "Spine2")]
    transforms, worlds, go_ids, tr_ids = {}, {}, {}, {}
    next_id = 100
    for name, parent, position, euler, scale in specs:
        if name == "Move":
            go_ids[name], tr_ids[name] = 4, 5
        else:
            go_ids[name], tr_ids[name] = next_id, next_id + 1; next_id += 2
        # When testing the missing target, keep its former children on Spine1.
        if missing_spine2 and parent == "Spine2":
            parent = "Spine1"
        q = quaternion(euler)
        world = (worlds[parent] if parent else np.eye(4)) @ local_matrix(position, q, scale)
        worlds[name] = world
        transforms[name] = (parent, position, q, scale)
    if duplicate_hips:
        specs.append(("DuplicateHips", "Move", (.1, .5, 0), (0, 0, 0), (1, 1, 1)))
        go_ids["DuplicateHips"], tr_ids["DuplicateHips"] = next_id, next_id + 1
        transforms["DuplicateHips"] = ("Move", (.1, .5, 0), (0, 0, 0, 1), (1, 1, 1))
        worlds["DuplicateHips"] = local_matrix((.1, .5, 0), (0, 0, 0, 1), (1, 1, 1))
    for old in (6, 7, 8, 9, 15):
        del asset.objects[old]
    for name, _, _, _, _ in specs:
        gid, tid = go_ids[name], tr_ids[name]
        go = copy.copy(game_template); go.path_id = gid
        transform = copy.copy(transform_template); transform.path_id = tid
        go_tree = copy.deepcopy(game_template.read_typetree())
        go_tree.update(m_Name="HipsSize" if name == "DuplicateHips" else name,
                       m_Component=[{"component": {"m_FileID": 0, "m_PathID": tid}}])
        parent, position, rotation, scale = transforms[name]
        tr_tree = copy.deepcopy(transform_template.read_typetree())
        tr_tree.update(m_GameObject={"m_FileID": 0, "m_PathID": gid},
                       m_LocalPosition=vector(position), m_LocalRotation=dict(zip("xyzw", rotation)),
                       m_LocalScale=vector(scale),
                       m_Father={"m_FileID": 0, "m_PathID": tr_ids[parent] if parent else 3},
                       m_Children=[{"m_FileID": 0, "m_PathID": tr_ids[child]}
                                   for child, values in transforms.items() if values[0] == name])
        asset.objects[gid], asset.objects[tid] = go, transform
        go.save_typetree(go_tree); transform.save_typetree(tr_tree)
    root_tree = objects[3].read_typetree()
    root_tree["m_Children"] = [{"m_FileID": 0, "m_PathID": 5}, {"m_FileID": 0, "m_PathID": 11}]
    objects[3].save_typetree(root_tree)
    script = objects[17].read_typetree()
    script.update(m_Name="LiveCoreMemberNodeScaling", m_ClassName="LiveCoreMemberNodeScaling",
                  m_Namespace="LLAS.Scene.Live.Components", m_AssemblyName="Assembly-CSharp")
    objects[17].save_typetree(script)
    component = objects[16].read_typetree()
    component.update(scaleValues=[], positionValues=[], rotationValues=[])
    objects[16].save_typetree(component)
    names = [row[0] for row in specs]
    positions = []; buffer = bytearray()
    for index, name in enumerate(names):
        world = worlds[name]
        points = LOCAL_TRIANGLE @ world[:3, :3].T + world[:3, 3]
        normal = np.cross(points[1] - points[0], points[2] - points[0]); normal /= np.linalg.norm(normal)
        for point in points:
            positions.append(point)
            buffer += struct.pack("<3f3f2f4f4B4B", *point, *normal, 0., 0., 1., 0., 0., 0.,
                                  index, 0, 0, 0, 180, 205, 240, 255)
    positions = np.asarray(positions); minimum, maximum = positions.min(axis=0), positions.max(axis=0)
    aabb = {"m_Center": vector((minimum+maximum)/2), "m_Extent": vector((maximum-minimum)/2)}
    mesh = objects[1].read_typetree()
    mesh.update(m_Name="BodyControlNeutral", m_Shapes={"vertices": [], "shapes": [], "channels": [], "fullWeights": []},
                m_BoneNameHashes=[zlib.crc32(("HipsSize" if name == "DuplicateHips" else name).encode()) & 0xffffffff for name in names],
                m_RootBoneNameHash=zlib.crc32(b"Move") & 0xffffffff,
                m_BindPose=[{f"e{r}{c}": float(np.linalg.inv(worlds[name])[r, c]) for r in range(4) for c in range(4)} for name in names],
                m_IndexBuffer=struct.pack("<"+"H"*len(positions), *range(len(positions))),
                m_LocalAABB=aabb)
    mesh["m_SubMeshes"][0].update(indexCount=len(positions), vertexCount=len(positions), localAABB=aabb)
    mesh["m_VertexData"].update(m_VertexCount=len(positions), m_DataSize=bytes(buffer))
    objects[1].save_typetree(mesh)
    renderer = objects[12].read_typetree()
    renderer.update(m_Bones=[{"m_FileID": 0, "m_PathID": tr_ids[name]} for name in names],
                    m_BlendShapeWeights=[], m_AABB=aabb)
    objects[12].save_typetree(renderer)
    return env.file.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--missing-spine2", action="store_true")
    parser.add_argument("--duplicate-hips", action="store_true")
    args = parser.parse_args()
    data = fixture_bytes(missing_spine2=args.missing_spine2, duplicate_hips=args.duplicate_hips)
    assert data == fixture_bytes(missing_spine2=args.missing_spine2, duplicate_hips=args.duplicate_hips)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_bytes(data)
    print(json.dumps({"path": str(args.output), "sha256": hashlib.sha256(data).hexdigest(),
                      "bytes": len(data), "scope": "Original generated weighted neutral geometry"}))


if __name__ == "__main__":
    main()
