"""Independent serialized-fixture setup and output inspection for browser QA."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import zipfile

import UnityPy
from UnityPy.helpers.MeshHelper import MeshHandler


def sha(data):
    return hashlib.sha256(data).hexdigest()


def setup(directory):
    from generate_viewer_persistence_fixture import fixture_bytes
    directory = Path(directory)
    models = directory / "extracted" / "3d_model"
    models.mkdir(parents=True, exist_ok=True)
    raw = fixture_bytes()
    for name in ("body.unity", "stale.unity"):
        (models / name).write_bytes(raw)
    (models / "body-morph.unity").write_bytes(fixture_bytes(morphs=True))
    (models / "body-mixed.unity").write_bytes(fixture_bytes(mixed_skin=True))
    # Real costumes commonly carry fractional authored TRS values which do not
    # match the browser number spinner's increments. Keep those bytes intact.
    fractional = UnityPy.load(raw)
    names = {obj.path_id: obj.read_typetree()["m_Name"] for obj in fractional.objects
             if obj.type.name == "GameObject"}
    for obj in fractional.objects:
        if obj.type.name != "Transform":
            continue
        tree = obj.read_typetree()
        if names.get(tree["m_GameObject"]["m_PathID"]) != "LeftUpLeg":
            continue
        tree["m_LocalPosition"]["y"] = .1234567
        tree["m_LocalRotation"] = {"x": math.sin(math.radians(13.125) / 2),
                                  "y": 0., "z": 0., "w": math.cos(math.radians(13.125) / 2)}
        obj.save_typetree(tree)
    fractional_raw = fractional.file.save()
    (models / "fractional.unity").write_bytes(fractional_raw)
    fractional_zip = models / "fractional-costume.zip"
    with zipfile.ZipFile(fractional_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("primary.unity", fractional_raw)
        archive.writestr("notes.txt", b"Preserve this companion exactly.\n")
    alternate = (Path(__file__).parent / "fixtures" / "viewer_triangle.unity").read_bytes()
    manifest = (b"chara_id=209\ncostume_file='primary.unity'\n"
                b"rina_unmask_costume_file='alternate.unity'\n")
    archive = models / "two-variants.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in (("primary.unity", raw), ("alternate.unity", alternate),
                           ("modinstall.txt", manifest), ("notes.txt", b"Preserve this companion exactly.\n")):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, data)
    editable = models / "two-editable-variants.zip"
    second = UnityPy.load(raw)
    for obj in second.objects:
        tree = obj.read_typetree()
        if obj.type.name == "GameObject" and tree.get("m_Name") == "SyntheticRig":
            tree["m_Name"] = "AlternateRig"; obj.save_typetree(tree)
        elif obj.type.name == "MonoBehaviour" and tree.get("targetName") == "SyntheticRig":
            tree["targetName"] = "AlternateRig"; obj.save_typetree(tree)
    with zipfile.ZipFile(editable, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in (("primary.unity", raw), ("alternate.unity", second.file.save()),
                           ("modinstall.txt", manifest), ("notes.txt", b"Keep both editable alternatives.\n")):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, data)
    return {"raw": str(models / "body.unity"), "morph": str(models / "body-morph.unity"),
            "mixed": str(models / "body-mixed.unity"),
            "stale": str(models / "stale.unity"), "archive": str(archive),
            "fractional": str(models / "fractional.unity"), "fractional_archive": str(fractional_zip),
            "editable_archive": str(editable),
            "original_raw_sha256": sha(raw)}


def inspect(path, member=None):
    path = Path(path)
    source = path.read_bytes()
    entries = None
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            entries = {info.filename: {"sha256": sha(archive.read(info)), "bytes": info.file_size}
                       for info in archive.infolist() if not info.is_dir()}
            if member is None:
                member = "primary.unity"
            source = archive.read(member)
    env = UnityPy.load(source)
    names, transforms, components, meshes, objects, renderers = {}, [], [], [], [], []
    for obj in env.objects:
        tree = obj.read_typetree()
        if obj.type.name == "GameObject":
            names[obj.path_id] = tree["m_Name"]
    transform_names = {}
    for obj in env.objects:
        tree = obj.read_typetree()
        if obj.type.name == "Transform":
            name = names.get(tree["m_GameObject"]["m_PathID"], "")
            transform_names[obj.path_id] = name
            transforms.append({"name": name, "path_id": str(obj.path_id),
                               "scale": [tree["m_LocalScale"][axis] for axis in "xyz"],
                               "position": [tree["m_LocalPosition"][axis] for axis in "xyz"],
                               "rotation": [tree["m_LocalRotation"][axis] for axis in "xyzw"]})
    for obj in env.objects:
        tree = obj.read_typetree()
        objects.append({"id": str(obj.path_id), "type": obj.type.name,
                        "sha256": sha(obj.get_raw_data())})
        if obj.type.name == "MonoBehaviour" and "scaleValues" in tree:
            entries_for_component = []
            for kind in ("scale", "position", "rotation"):
                for entry in tree.get(kind + "Values", []):
                    entries_for_component.append({"kind": kind,
                        "target": transform_names.get(entry["target"]["m_PathID"], ""),
                        "origin": [entry["originValue"][axis] for axis in "xyz"],
                        "scaled": [entry["scaledValue"][axis] for axis in "xyz"]})
            components.append({"targetName": tree["targetName"], "entries": entries_for_component})
        elif obj.type.name == "Mesh":
            decoded = MeshHandler(obj.read())
            decoded.process()
            meshes.append({"name": tree["m_Name"], "positions": decoded.m_Vertices,
                           "bind_pose_sha256": sha(json.dumps(tree["m_BindPose"], sort_keys=True).encode()),
                           "morphs": tree["m_Shapes"]})
        elif obj.type.name == "SkinnedMeshRenderer":
            renderers.append({"enabled": tree["m_Enabled"],
                              "morph_weights": tree["m_BlendShapeWeights"]})
    return {"file": str(path), "file_sha256": sha(path.read_bytes()),
            "model_sha256": sha(source), "archive_entries": entries,
            "transforms": transforms, "components": components,
            "meshes": meshes, "objects": objects, "renderers": renderers}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--member")
    args = parser.parse_args()
    print(json.dumps(setup(args.path) if args.setup else inspect(args.path, args.member)))


if __name__ == "__main__":
    main()
