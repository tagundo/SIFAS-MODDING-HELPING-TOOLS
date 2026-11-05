"""Derive an original editable rig fixture without including any game assets.

The existing six-vertex ribbon supplies the typed Unity objects. This copy has
a weighted LeftUpLeg with an existing saved scale and an MV-like constant scale
track, plus a separate BreastSize node for ordinary NodeScaling edits. Keeping
the original saved scale non-unit exercises migration without double scaling.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

import UnityPy


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "fixtures" / "viewer_rig.unity"
OUTPUT = HERE / "fixtures" / "viewer_persistence.unity"


def vector(x=0., y=0., z=0.):
    return {"x": x, "y": y, "z": z}


def fixture_bytes(*, morphs=False, mixed_skin=False):
    env = UnityPy.load(str(SOURCE))
    replacements = {"BreastSize": "LeftUpLeg", "Tip": "BreastSize"}
    for obj in env.objects:
        tree = obj.read_typetree()
        changed = False
        if obj.type.name == "GameObject" and tree.get("m_Name") in replacements:
            tree["m_Name"] = replacements[tree["m_Name"]]
            changed = True
        elif obj.type.name == "MonoScript":
            tree.update(m_Name="LiveCoreMemberNodeScaling",
                        m_ClassName="LiveCoreMemberNodeScaling",
                        m_Namespace="LLAS.Scene.Live.Components",
                        m_AssemblyName="Assembly-CSharp")
            changed = True
        elif obj.type.name == "Mesh":
            hashes = {zlib.crc32(old.encode()) & 0xffffffff:
                      zlib.crc32(new.encode()) & 0xffffffff
                      for old, new in replacements.items()}
            tree["m_BoneNameHashes"] = [hashes.get(value, value)
                                         for value in tree["m_BoneNameHashes"]]
            if not morphs:
                tree["m_Shapes"] = {"vertices": [], "shapes": [],
                                     "channels": [], "fullWeights": []}
            if mixed_skin:
                vertex_data = tree["m_VertexData"]
                channels = vertex_data["m_Channels"]
                assert channels[12]["offset"] == 32 and channels[12]["format"] == 0
                assert channels[13]["offset"] == 48 and channels[13]["format"] == 6
                buffer = bytearray(vertex_data["m_DataSize"])
                stride = len(buffer) // vertex_data["m_VertexCount"]
                assert stride == 56
                for index in (2, 3):
                    struct.pack_into("<4f", buffer, index * stride + 32, .5, .5, 0., 0.)
                    struct.pack_into("<4B", buffer, index * stride + 48, 0, 1, 0, 0)
                for index in (4, 5):
                    struct.pack_into("<4f", buffer, index * stride + 32, .3, .7, 0., 0.)
                    struct.pack_into("<4B", buffer, index * stride + 48, 1, 2, 0, 0)
                vertex_data["m_DataSize"] = bytes(buffer)
            changed = True
        elif obj.type.name == "SkinnedMeshRenderer" and not morphs:
            tree["m_BlendShapeWeights"] = []
            changed = True
        elif obj.type.name == "AnimationClip":
            tree["m_Name"] = "Neutral MV scale override"
            for declaration in tree.get("m_RotationCurves", []):
                declaration["path"] = "Move/LeftUpLeg"
            keys = []
            for stamp in (0., 2.):
                keys.append({"time": stamp, "value": vector(1., 1., 1.),
                             "inSlope": vector(), "outSlope": vector(),
                             "weightedMode": 0, "inWeight": vector(),
                             "outWeight": vector()})
            tree["m_ScaleCurves"] = [{
                "path": "Move/LeftUpLeg",
                "curve": {"m_Curve": keys, "m_PreInfinity": 0,
                          "m_PostInfinity": 0, "m_RotationOrder": 0}}]
            changed = True
        if changed:
            obj.save_typetree(tree)
    return env.file.save()


def validate(data, *, morphs):
    env = UnityPy.load(data)
    names, component, clip, mesh = {}, None, None, None
    for obj in env.objects:
        tree = obj.read_typetree()
        if obj.type.name == "GameObject":
            names[obj.path_id] = tree["m_Name"]
        elif obj.type.name == "MonoBehaviour":
            component = tree
        elif obj.type.name == "AnimationClip":
            clip = tree
        elif obj.type.name == "Mesh":
            mesh = tree
    assert {"Move", "LeftUpLeg", "BreastSize"}.issubset(names.values())
    assert component["scaleValues"][0]["scaledValue"]["x"] > 1.29
    assert clip["m_ScaleCurves"][0]["path"] == "Move/LeftUpLeg"
    assert all(key["value"] == vector(1., 1., 1.)
               for key in clip["m_ScaleCurves"][0]["curve"]["m_Curve"])
    assert bool(mesh["m_Shapes"]["channels"]) is morphs
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "nodes": ["Move", "LeftUpLeg", "BreastSize"],
            "weighted_mesh": "NeutralRibbon", "vertices": 6,
            "saved_thigh_scale": [1.3, .9, 1.],
            "animation": "Neutral MV scale override",
            "animation_thigh_scale": [1., 1., 1.], "morphs": morphs,
            "scope": "Original generated neutral geometry, not a SIFAS game asset"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--morphs", action="store_true")
    parser.add_argument("--mixed-skin", action="store_true")
    args = parser.parse_args()
    data = fixture_bytes(morphs=args.morphs, mixed_skin=args.mixed_skin)
    assert data == fixture_bytes(morphs=args.morphs, mixed_skin=args.mixed_skin), "Fixture must be deterministic"
    report = validate(data, morphs=args.morphs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(dict(report, path=str(args.output)), sort_keys=True))


if __name__ == "__main__":
    main()
