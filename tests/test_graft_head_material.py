"""Head meshes are drawn with BodyPartManager.headMaterial; grafts must write there.

The GL 3.12.0 client's MergeAndCombineFaceMesh.MergeFace (0x2c94ff4) sets
headMaterial on every Renderer below headAll (set_sharedMaterial loop at
0x2c95478) unless the face is not merged (masked heads with
Head_All/Head_Face/mesh_facedots). A copied material or an atlas on such a
renderer is never drawn, and an atlas would move the UV0-driven cheek blush.
"""
from pathlib import Path
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import UnityPy

import costume_part_transplant as cpt
import graft_game_compat as compat
from graft_game_compat import (CHEEK_WINDOW, FACE_TARGET_REFUSED, HEAD_ATLAS_REFUSED, HEAD_FACE_REQUIRED,
                               HEAD_NO_SPACE, bake_renderer_for_game, face_combined_renderer, head_material_binding)
from test_graft_game_compat import fixture, raw_objects

ROOT = Path(__file__).resolve().parents[1]


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


class HeadRendererRuleTests(unittest.TestCase):
    def test_renderers_below_head_all_are_drawn_with_head_material(self):
        objects, renderers, head_material = head_costume()
        binding = head_material_binding(objects, renderers["Hair"])
        self.assertIs(binding["material"], head_material)
        self.assertEqual({obj.tree["m_GameObject"]["m_PathID"] for obj in binding["renderers"]},
                         {renderers[name].tree["m_GameObject"]["m_PathID"] for name in ("Hair", "Face")})
        self.assertIsNone(head_material_binding(objects, renderers["Body"]), "Body keeps its own material")

    def test_masked_heads_are_not_merged_and_keep_their_materials(self):
        objects, renderers, _ = head_costume(masked=True)
        self.assertIsNone(head_material_binding(objects, renderers["Hair"]))

    def test_face_pieces_are_never_part_targets(self):
        objects, renderers, _ = head_costume()
        self.assertTrue(face_combined_renderer(objects, renderers["Face"]))
        self.assertFalse(face_combined_renderer(objects, renderers["Hair"]))
        self.assertFalse(face_combined_renderer(objects, renderers["Body"]))
        boned_face = renderers["Face"]
        boned_face.tree["m_Bones"] = list(renderers["Hair"].tree["m_Bones"])
        self.assertTrue(face_combined_renderer(objects, boned_face), "mesh_face is merged even with bones")

    def test_cheek_window_is_the_uv0_area_the_cheek_formula_maps_into_the_array(self):
        u0, v0, u1, v1 = CHEEK_WINDOW
        for u, v in ((u0, v0), (u1, v1)):
            cheek = np.array([u, v]) * 2.22 + np.array([0, -1.221])
            self.assertTrue(np.all(cheek >= -1e-9) and np.all(cheek <= 1 + 1e-3))


class HeadBakeTests(unittest.TestCase):
    """bake_renderer_for_game on a real (synthetic) costume, as a head renderer."""

    def setUp(self):
        # 16x16 nearest-sampled maps; receiver group 0 covers the whole tile,
        # so donor groups get their own UVs below.
        self.target, self.renderer, self.mesh, self.material = fixture((0, 0, 255, 255), size=16)
        self.donor, _, _, self.donor_material = fixture((255, 0, 0, 255), size=16)

    def head(self):
        binding = {"material": self.material, "head_all": 0, "renderers": [self.renderer]}
        return patch.object(compat, "head_material_binding", return_value=binding)

    def groups(self, receiver, donor):
        """Receiver = the first ten triangles, donor = the other ten (own vertices)."""
        tree = self.mesh.read_typetree()
        width = 2 if tree.get("m_IndexFormat", 0) == 0 else 4
        half = len(bytes(tree["m_IndexBuffer"])) // width // 2
        first = dict(tree["m_SubMeshes"][0], firstByte=0, indexCount=half)
        tree["m_SubMeshes"] = [first, dict(first, firstByte=half * width)]
        count, channels, strides, starts, _ = cpt.stream_layout(tree)
        data = bytearray(tree["m_VertexData"]["m_DataSize"])
        uv = cpt.read_attr(np.frombuffer(data, np.uint8), cpt.ATTR_UV0, channels, strides, starts, count)
        groups = cpt.submesh_triangles(tree)
        for vertices, triangle in ((np.unique(groups[0]), receiver), (np.unique(groups[1]), donor)):
            uv[vertices] = np.resize(np.asarray(triangle, np.float32), (len(vertices), 2))
        cpt.write_attr(np.frombuffer(data, np.uint8), uv, cpt.ATTR_UV0, channels, strides, starts, count)
        tree["m_VertexData"]["m_DataSize"] = bytes(data)
        return tree

    def bake(self, tree, **options):
        return bake_renderer_for_game(self.target, self.renderer, self.mesh, mesh_tree=tree,
                                      additional_sources=[(self.donor, self.donor_material.path_id)], **options)

    def test_atlas_is_refused_for_head_meshes_without_touching_objects(self):
        tree = self.groups(((.05, .05), (.2, .05), (.05, .2)), ((.6, .1), (.8, .1), (.6, .3)))
        before = raw_objects(self.target)
        for options in ({"uv_placement": "atlas", "face_surfaces": []}, {"reuse_empty_uv": False, "face_surfaces": []}):
            with self.subTest(options=options), self.head(), self.assertRaises(ValueError) as caught:
                self.bake(tree, **options)
            self.assertEqual(str(caught.exception), HEAD_ATLAS_REFUSED)
        self.assertEqual(raw_objects(self.target), before)

    def test_head_meshes_need_the_face_bundle(self):
        tree = self.groups(((.05, .05), (.2, .05), (.05, .2)), ((.6, .1), (.8, .1), (.6, .3)))
        with self.head(), self.assertRaises(ValueError) as caught:
            self.bake(tree, uv_placement="same_position")
        self.assertEqual(str(caught.exception), HEAD_FACE_REQUIRED)

    def test_no_free_head_texels_refuses_instead_of_making_an_atlas(self):
        # The donor sits in the cheek window, and the face bundle covers the rest.
        tree = self.groups(((.9, .05), (.95, .05), (.9, .1)), ((.1, .7), (.3, .7), (.1, .9)))
        everything = (np.array([[0., 0.], [1., 0.], [0., 1.], [1., 1.]]), np.array([[0, 1, 2], [1, 3, 2]]))
        before = raw_objects(self.target)
        for placement in ("same_position", "move_to_empty"):
            with self.subTest(placement=placement), self.head(), self.assertRaises(ValueError) as caught:
                self.bake(tree, uv_placement=placement, face_surfaces=[everything])
            self.assertTrue(str(caught.exception).startswith(HEAD_NO_SPACE), str(caught.exception))
            self.assertNotIn("using the texture atlas", str(caught.exception))
        with self.head(), self.assertRaises(ValueError) as caught:
            self.bake(tree, uv_placement="same_position", face_surfaces=[])
        self.assertTrue(str(caught.exception).startswith(HEAD_NO_SPACE), "the cheek window is reserved")
        self.assertEqual(raw_objects(self.target), before)
        self.assertEqual(sum(obj.type.name == "Material" for obj in self.target.objects), 1)

    def test_free_head_texels_are_written_into_the_head_material_itself(self):
        donor_uv = ((.6, .1), (.8, .1), (.6, .3))
        tree = self.groups(((.05, .05), (.2, .05), (.05, .2)), donor_uv)
        materials_before = sorted(obj.path_id for obj in self.target.objects if obj.type.name == "Material")
        renderer_tree = self.renderer.read_typetree()
        with self.head():
            stats = self.bake(tree, renderer_tree=renderer_tree, uv_placement="same_position", face_surfaces=[])
        self.assertTrue(stats["head_material"])
        self.assertFalse(stats["detached_material"])
        self.assertEqual(renderer_tree["m_Materials"], [{"m_FileID": 0, "m_PathID": self.material.path_id}])
        saved = UnityPy.load(self.target.file.save(packer="original"))
        objects = {obj.path_id: obj for obj in saved.objects}
        self.assertEqual(sorted(pid for pid, obj in objects.items() if obj.type.name == "Material"), materials_before)
        slot = dict(objects[self.material.path_id].read_typetree()["m_SavedProperties"]["m_TexEnvs"])["_MainTex"]
        image = np.asarray(objects[slot["m_Texture"]["m_PathID"]].read().image.convert("RGBA"))
        self.assertEqual(image.shape[:2], (16, 16), "the head texture keeps its size")
        red = np.all(image == (255, 0, 0, 255), axis=2)
        self.assertTrue(red.any())
        self.assertTrue(np.all(image[~red] == (0, 0, 255, 255)), "only donor texels change")
        rows, columns = np.nonzero(red)
        self.assertGreaterEqual(columns.min(), int(.6 * 16) - 1)
        self.assertLessEqual(15 - rows.max(), int(.3 * 16), "copied at the same UV position")


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


class RefusalTranslationTests(unittest.TestCase):
    """Fixed refusal sentences are translated by exact key in every UI."""

    def test_every_refusal_has_korean_and_japanese_text(self):
        from graft_texture_atlas import CULL_MODE_HINT
        from webtools import i18n
        script = (ROOT / "webtools/web/static/viewer-transplants.js").read_text(encoding="utf-8")
        for sentence in (HEAD_ATLAS_REFUSED, HEAD_FACE_REQUIRED, HEAD_NO_SPACE, FACE_TARGET_REFUSED, CULL_MODE_HINT):
            with self.subTest(sentence=sentence[:40]):
                self.assertIn('"' + sentence + '"', script)
                for language in ("ko", "ja"):
                    self.assertNotEqual(i18n.tr(sentence, language), sentence)
                    self.assertIn(sentence, cpt._TRANSLATIONS[language])
                    self.assertNotEqual(cpt._TRANSLATIONS[language][sentence], sentence)
        self.assertNotRegex(CULL_MODE_HINT, re.compile("head accessory", re.I))


if __name__ == "__main__":
    unittest.main()
