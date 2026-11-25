"""Face pieces the client merges into CombineFace cannot receive a part.

MergeAndCombineFaceMesh (GL 3.12.0 0x2c94ff4/0x2c95984) folds mesh_face and
bone-less face pieces into the combined face, drawn with
BodyPartManager.headMaterial and fixed cheek UVs.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import costume_part_transplant as cpt
from graft_game_compat import FACE_TARGET_REFUSED, face_combined_renderer


class Fake:
    def __init__(self, path_id, kind, tree, assets_file):
        self.path_id, self.type, self.tree, self.assets_file = path_id, SimpleNamespace(name=kind), tree, assets_file

    def read_typetree(self):
        return self.tree


def pointer(path_id):
    return {"m_FileID": 0, "m_PathID": path_id}


def head_costume(masked=False):
    """Hips/Head/Head_All with mesh_hair/Hair and mesh_face/Face, plus Body."""
    sf = SimpleNamespace(externals=[])
    objects, ids = {}, iter(range(1, 1000))

    def add(kind, tree):
        obj = Fake(next(ids), kind, tree, sf)
        objects[obj.path_id] = obj
        return obj

    def node(name, parent=None):
        game = add("GameObject", {"m_Name": name})
        transform = add("Transform", {"m_GameObject": pointer(game.path_id), "m_Children": [],
                                      "m_Father": pointer(parent[1].path_id) if parent else {"m_FileID": 0, "m_PathID": 0}})
        if parent:
            parent[1].tree["m_Children"].append(pointer(transform.path_id))
        return game, transform

    root = node("ch0212_co0001_member")
    hips = node("Hips", root)
    head = node("Head", hips)
    head_all = node("Head_All", head)
    hair_node = node("Hair", node("mesh_hair", head_all))
    face_node = node("Face", node("mesh_face", head_all))
    body_node = node("Body", node("mesh_body", root))
    if masked:
        node("mesh_facedots", node("Head_Face", head_all))
    head_material = add("Material", {"m_Name": "ch0212_co0001_head"})
    body_material = add("Material", {"m_Name": "ch0212_co0001_body"})
    renderers = {}
    for name, game, bones, material in (("Hair", hair_node, [pointer(hips[1].path_id)], head_material),
                                        ("Face", face_node, [], head_material),
                                        ("Body", body_node, [pointer(hips[1].path_id)], body_material)):
        renderers[name] = add("SkinnedMeshRenderer", {"m_GameObject": pointer(game[0].path_id), "m_Bones": bones,
                                                      "m_Materials": [pointer(material.path_id)]})
    script = add("MonoScript", {"m_ClassName": "BodyPartManager", "m_Namespace": "LLAS.Components.Members",
                                "m_AssemblyName": "Assembly-CSharp.dll"})
    add("MonoBehaviour", {"m_Script": pointer(script.path_id), "head": pointer(head[0].path_id),
                          "headAll": pointer(head_all[0].path_id), "face": {"m_FileID": 2, "m_PathID": 77},
                          "headMaterial": pointer(head_material.path_id)})
    return objects, renderers, head_material


class FaceRendererRuleTests(unittest.TestCase):
    def test_face_pieces_are_never_part_targets(self):
        objects, renderers, _ = head_costume()
        self.assertTrue(face_combined_renderer(objects, renderers["Face"]))
        self.assertFalse(face_combined_renderer(objects, renderers["Hair"]))
        self.assertFalse(face_combined_renderer(objects, renderers["Body"]))
        boned_face = renderers["Face"]
        boned_face.tree["m_Bones"] = list(renderers["Hair"].tree["m_Bones"])
        self.assertTrue(face_combined_renderer(objects, boned_face), "mesh_face is merged even with bones")


class FaceTargetTransplantTests(unittest.TestCase):
    def test_transplant_part_refuses_face_targets_before_any_change(self):
        objects, renderers, _ = head_costume()
        environment = SimpleNamespace(objects=list(objects.values()))
        with patch.object(cpt, "_require_unitypy", return_value=SimpleNamespace(load=lambda path: environment)), \
                patch.object(cpt, "_body_smr", return_value=renderers["Body"]):
            with self.assertRaises(ValueError) as caught:
                cpt.transplant_part("donor.unity", "target.unity", "out.unity", auto=True,
                                    target_renderer=renderers["Face"].path_id)
        self.assertEqual(str(caught.exception), FACE_TARGET_REFUSED)


if __name__ == "__main__":
    unittest.main()
