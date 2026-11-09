"""Serialized main/LOD graph and unweighted-tip regression for costume grafts."""
import copy
import json
import struct
from pathlib import Path
import tempfile
import unittest

import UnityPy
import costume_transplant as full
import costume_part_transplant as part
from generate_viewer_physics_fixture import fixture_bytes
from webtools.core import model_edits, viewer_physics


def as_bundle(raw):
    """Wrap the neutral standalone SerializedFile in a genuine UnityFS."""
    version = UnityPy.load(raw).file.unity_version
    entry = b"CAB-neutral-physics\0"
    info = bytes(16) + struct.pack(">iIIHi", 1, len(raw), len(raw), 0, 1)
    info += struct.pack(">qqI", 0, len(raw), 0) + entry
    prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0" + version.encode() + b"\0"
    return prefix + struct.pack(">QIII", len(prefix) + 20 + len(info) + len(raw), len(info), len(info), 64) + info + raw


def donor_chain():
    env = UnityPy.load(fixture_bytes(native=True))
    objects = {obj.path_id: obj for obj in env.objects}
    asset = objects[221].assets_file
    def ptr(n): return {"m_FileID": 0, "m_PathID": n}
    for ident, name in ((200, "TailA1_Dyna"), (210, "TailA_End")):
        tree = objects[ident].read_typetree(); tree["m_Name"] = name
        objects[ident].save_typetree(tree)
    for source, ident in ((200, 250), (201, 251), (221, 252)):
        obj = copy.copy(objects[source]); obj.path_id = ident
        asset.objects[ident] = obj
        tree = objects[source].read_typetree()
        if ident == 250:
            tree.update(m_Name="TailA2_Dyna", m_Component=[{"component": ptr(251)}, {"component": ptr(252)}])
        elif ident == 251:
            tree.update(m_GameObject=ptr(250), m_Father=ptr(201), m_Children=[ptr(211)],
                        m_LocalPosition={"x": -.04, "y": 0., "z": 0.})
        else:
            tree.update(m_GameObject=ptr(250), child=ptr(211), sibling=ptr(0), parentIndex=0, childIndex=-1,
                        siblingIndex=-1, enableLod=True)
        obj.save_typetree(tree)
    tree = objects[201].read_typetree(); tree["m_Children"] = [ptr(209), ptr(251)]
    objects[201].save_typetree(tree)
    tree = objects[211].read_typetree(); tree["m_Father"] = ptr(251)
    tree["m_LocalPosition"] = {"x": -.04, "y": 0., "z": 0.}
    objects[211].save_typetree(tree)
    tree = objects[221].read_typetree()
    tree.update(child=ptr(251), sibling=ptr(252), childIndex=1, siblingIndex=1, parentIndex=-1, enableLod=True)
    objects[221].save_typetree(tree)
    tree = objects[228].read_typetree(); tree.update(bones=[], lodBones=[ptr(221), ptr(252)])
    objects[228].save_typetree(tree)
    return env.file.save(packer="original")


class TransplantPhysicsGraphTests(unittest.TestCase):
    def test_full_and_part_keep_unweighted_tips_typed_siblings_and_lod_indices(self):
        target_raw, donor_raw = as_bundle(fixture_bytes(native=True)), as_bundle(donor_chain())
        for operation in ("full", "part"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                donor_path, target_path, out_path = (root / name for name in ("donor.unity", "target.unity", "out.unity"))
                donor_path.write_bytes(donor_raw); target_path.write_bytes(target_raw)
                donor, target = UnityPy.load(donor_raw), UnityPy.load(target_raw)
                _, index = part._index(target)
                names = part._name2transform(index)
                if operation == "full":
                    new, children = full.inject_appendage_bones(donor, target, ["TailA1_Dyna"], names,
                                                                 restore_collision=False)
                else:
                    new, children = part.inject_bone_chain(donor, target, ["TailA1_Dyna"], names,
                                                           restore_collision=False)
                self.assertTrue({"TailA1_Dyna", "TailA2_Dyna", "TailA_End"} <= set(new))
                part.wire_child_adds(index, children)
                out_path.write_bytes(target.file.save(packer="original"))
                full.repair_transplant_physics(str(out_path), str(donor_path), str(target_path), new,
                                               restore_collision=False, verbose=False)
                saved = UnityPy.load(str(out_path))
                objects, index = part._index(saved)
                scripts = part._scriptname_map(objects)
                manager = full._find_swingbone_manager(objects, scripts).read_typetree()
                self.assertEqual(len(manager["bones"]), 1)
                self.assertEqual(len(manager["lodBones"]), 2)
                by_name = {part._go_name(index, obj.read_typetree()["m_GameObject"]["m_PathID"]): obj
                           for obj in objects if obj.type.name == "MonoBehaviour"
                           and scripts.get(obj.read_typetree()["m_Script"]["m_PathID"]) == "SwingBone"}
                first, second = (by_name[name] for name in ("TailA1_Dyna", "TailA2_Dyna"))
                a, b = first.read_typetree(), second.read_typetree()
                self.assertEqual(index[a["child"]["m_PathID"]].type.name, "Transform")
                self.assertEqual(index[a["sibling"]["m_PathID"]].type.name, "MonoBehaviour")
                self.assertEqual(a["sibling"]["m_PathID"], second.path_id)
                self.assertEqual(a["childIndex"], 2)
                self.assertEqual(a["siblingIndex"], 2)
                self.assertEqual(b["parentIndex"], 1)
                endpoint = index[b["child"]["m_PathID"]]
                self.assertEqual(part._go_name(index, endpoint.read_typetree()["m_GameObject"]["m_PathID"]), "TailA_End")
                info = model_edits._inspect(out_path.read_bytes())
                bones = [{"sourceIndex": 0, "serializedFile": key[0], "transformId": str(key[1]), "node": node}
                         for node, key in enumerate(info["transforms"])]
                catalog = viewer_physics.make_catalog(viewer_physics.inspect_info(info, 0, bones),
                                                      viewer_physics.native_managers(info, 0, bones))
                self.assertTrue(catalog["native"]["available"], catalog["native"])
                self.assertEqual(target_path.read_bytes(), target_raw)
                self.assertEqual(donor_path.read_bytes(), donor_raw)
                # Re-saving/re-opening must retain typed references; an in-memory
                # catalogue-only fix would fail this assertion.
                out_path.write_bytes(saved.file.save(packer="original"))
                self.assertTrue(full.validate(str(out_path), verbose=False))
                # A zero tip or a Transform used as a SwingBone sibling used
                # to pass the publication validator despite disabling physics.
                broken = UnityPy.load(str(out_path))
                _, broken_index = part._index(broken)
                data = broken_index[first.path_id].read_typetree()
                data["sibling"] = data["child"].copy()
                broken_index[first.path_id].save_typetree(data)
                out_path.write_bytes(broken.file.save(packer="original"))
                self.assertFalse(full.validate(str(out_path), verbose=False))
                self.assertFalse(part.validate(str(out_path), verbose=False))
