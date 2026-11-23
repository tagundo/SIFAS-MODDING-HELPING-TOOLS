"""BodyPartManager partMap export for LiveDepthOfFieldClip.bodyPart (GL 3.12.0 client).

BodyPartManager.Initialize adds Head 0, HeadAll 1, Face 2 (face.gameObject),
Hips 3 and Neck 4. face is a MemberFace on the separate facial prefab asset, a
reference Instantiate keeps, so its part is that asset's fixed world point.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from webtools.core import model_viewer
from webtools.core.model_rig import RigBuilder


class FakeScene:
    def __init__(self):
        self.objects, self.trees, self.transforms = {}, {}, {}
        self.env = SimpleNamespace(objects=[])

    def add(self, path_id, kind, tree, file):
        obj = SimpleNamespace(path_id=path_id, assets_file=file, type=SimpleNamespace(name=kind), source=file.source)
        self.objects[path_id], self.trees[path_id] = obj, tree
        self.env.objects.append(obj)
        return obj

    def tree(self, obj):
        return self.trees[obj.path_id]

    def world(self, transform):
        import numpy as np
        matrix, tree = np.eye(4), self.trees[transform.path_id]
        while tree is not None:
            local = np.eye(4)
            local[:3, 3] = [tree["m_LocalPosition"][axis] for axis in "xyz"]
            matrix = local @ matrix
            father = tree["m_Father"]["m_PathID"]
            tree = self.trees[father] if father else None
        return matrix


def pointer(path_id):
    return {"m_FileID": 0, "m_PathID": path_id}


class FocusPartTests(unittest.TestCase):
    def build(self, face_position=(0, 0, 0), face_inside=False):
        scene = FakeScene()
        body, facial = SimpleNamespace(source="body"), SimpleNamespace(source="face")
        nodes = {}
        # Body prefab: Model(10) > Hips(11) > Neck(12) > Head(13) > Head_All(14).
        chain = [(10, "Model", 0), (11, "Hips", 10), (12, "Neck", 11), (13, "Head", 12), (14, "Head_All", 13)]
        for index, (identity, name, father) in enumerate(chain):
            game = scene.add(identity + 100, "GameObject", {"m_Name": name}, body)
            transform = scene.add(identity, "Transform", {"m_GameObject": pointer(identity + 100), "m_Father": pointer(father),
                                                          "m_LocalPosition": {"x": 0, "y": 0.1 * index, "z": 0}}, body)
            scene.transforms[model_viewer._key(game)] = transform
            nodes[model_viewer._key(transform)] = index
        face_father = 13 if face_inside else 0
        face_file = body if face_inside else facial
        game = scene.add(300, "GameObject", {"m_Name": "ch0212_co0000_facedynamic"}, face_file)
        transform = scene.add(301, "Transform", {"m_GameObject": pointer(300), "m_Father": pointer(face_father),
                                                 "m_LocalPosition": dict(zip("xyz", face_position))}, face_file)
        scene.transforms[model_viewer._key(game)] = transform
        if face_inside:
            nodes[model_viewer._key(transform)] = 9
        scene.add(302, "MonoBehaviour", {"m_GameObject": pointer(300), "memberFaceData": {}}, face_file)
        scene.add(400, "MonoScript", {"m_ClassName": "BodyPartManager", "m_Namespace": "LLAS.Components.Members",
                                      "m_AssemblyName": "Assembly-CSharp.dll"}, body)
        scene.add(401, "MonoBehaviour", {"m_GameObject": pointer(110), "m_Script": pointer(400), "head": pointer(113),
                                         "headAll": pointer(114), "face": pointer(302), "hips": pointer(111),
                                         "neck": pointer(112), "headMaterial": pointer(0)}, body)
        rig = object.__new__(RigBuilder)
        rig.scene, rig.nodes, rig.selected, rig.facial_sources = scene, nodes, {"body"}, {"face"}
        return rig, scene

    def focus(self, rig, scene):
        with patch.object(model_viewer, "_ref", lambda owner, value: scene.objects.get((value or {}).get("m_PathID"))), \
                patch.object(model_viewer, "_source_path", lambda obj: obj.source):
            return rig._focus_parts()

    def test_every_partmap_entry_is_keyed_by_body_part_type(self):
        rig, scene = self.build(face_position=(0.5, 0, -2))
        self.assertEqual(self.focus(rig, scene), {"0": 3, "1": 4, "2": {"world": [0.5, 0.0, -2.0]}, "3": 1, "4": 2})

    def test_face_inside_the_member_prefab_uses_its_node(self):
        rig, scene = self.build(face_inside=True)
        self.assertEqual(self.focus(rig, scene)["2"], 9)

    def test_missing_fields_are_left_out_and_ambiguous_managers_export_nothing(self):
        rig, scene = self.build()
        del scene.trees[401]["neck"]
        self.assertNotIn("4", self.focus(rig, scene))
        scene.add(402, "MonoBehaviour", dict(scene.trees[401], head=pointer(114)), SimpleNamespace(source="body"))
        self.assertEqual(self.focus(rig, scene), {})


if __name__ == "__main__":
    unittest.main()
