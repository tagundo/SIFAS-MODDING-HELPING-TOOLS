"""Head meshes are drawn with BodyPartManager.headMaterial; grafts must write there.

The GL 3.12.0 client's MergeAndCombineFaceMesh.MergeFace (0x2c94ff4) sets
headMaterial on every Renderer below headAll (set_sharedMaterial loop at
0x2c95478) unless the face is not merged (masked heads with
Head_All/Head_Face/mesh_facedots). A copied material or an atlas on such a
renderer is never drawn, and an atlas would move the UV0-driven cheek blush.
"""
from copy import deepcopy
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
from test_graft_texture_atlas import image, levels, source
from test_graft_uv_reuse import DONOR, RECEIVER, mesh

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
        renderers["Hair"].tree["m_Bones"] = []
        self.assertTrue(face_combined_renderer(objects, renderers["Hair"]),
                        "a bone-less piece is only placed rigidly, wherever it sits")

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
        logged = []
        for placement, sentence in (("same_position", compat.HEAD_POSITION_IN_USE), ("move_to_empty", HEAD_NO_SPACE)):
            with self.subTest(placement=placement), self.head(), self.assertRaises(ValueError) as caught:
                self.bake(tree, uv_placement=placement, face_surfaces=[everything], log=logged.append)
            self.assertTrue(str(caught.exception).startswith(sentence), str(caught.exception))
            # Only fixed, translatable sentences reach the message; the
            # technical diagnostics go to the job log instead.
            self.assertNotIn("unavailable", str(caught.exception))
            self.assertTrue(any("unavailable" in line for line in logged), logged)
        with self.head(), self.assertRaises(ValueError) as caught:
            self.bake(tree, uv_placement="same_position", face_surfaces=[])
        self.assertEqual(str(caught.exception), compat.HEAD_POSITION_IN_USE + " "
                         + compat.HEAD_DETAIL_POSITION.format(slot="_MainTex"), "the cheek window is reserved")
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


def chain(size, color):
    """A complete authored mip chain of one colour per level."""
    return [image((max(1, size >> level), max(1, size >> level)), (color[0], color[1], (color[2] + 40 * level) % 256, 255))
            for level in range(size.bit_length())]


def add_textures(material, slots):
    """Give a material its own RGBA32 texture objects: ``{slot: (size, colour)}``.

    All slots are written in one save; ObjectReader re-reads stale bytes
    until the bundle is reopened.
    """
    sf = material.assets_file
    template = next(obj for obj in sf.objects.values() if obj.type.name == "Texture2D")
    material_tree = material.read_typetree()
    envs = material_tree["m_SavedProperties"]["m_TexEnvs"]
    for slot, (size, color) in slots.items():
        images = chain(size, color)
        tree = template.read_typetree()
        payload = b"".join(level.transpose(1).tobytes() for level in images)  # Unity rows are bottom-up.
        tree.update(m_Name=f"{slot}-{size}", m_Width=size, m_Height=size, m_TextureFormat=4, m_MipCount=len(images),
                    m_CompleteImageSize=len(payload), **{"image data": payload})
        tree["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
        tree["m_TextureSettings"]["m_FilterMode"] = 0
        if "m_MipMap" in tree:
            tree["m_MipMap"] = len(images) > 1
        path_id = max(sf.objects) + 1
        cpt._make_object(sf, template, path_id, tree)
        value = {"m_Texture": pointer(path_id), "m_Scale": {"x": 1., "y": 1.}, "m_Offset": {"x": 0., "y": 0.}}
        for index, (name, _) in enumerate(envs):
            if name == slot:
                envs[index] = (name, value)
                break
        else:
            envs.append((slot, value))
    material.save_typetree(material_tree)


def texture_sizes(environment, material_id):
    objects = {obj.path_id: obj for obj in environment.objects}
    result = {}
    for slot, value in objects[material_id].read_typetree()["m_SavedProperties"]["m_TexEnvs"]:
        texture = objects[value["m_Texture"]["m_PathID"]].read()
        result[slot] = (texture.m_Width, texture.m_Height, texture.m_MipCount)
    return result


class HeadTextureSizeTests(unittest.TestCase):
    """The face, eyes and mouth sample every head texture: none may change size.

    Before this rule a 512-pixel donor rim map enlarged the head's 128-pixel
    rim map 4x, which changed the face's own bilinear rim lighting in game.
    """

    def sources(self, donor_rim):
        target = source("head", chain(32, (10, 20, 30)), rim=chain(8, (40, 50, 60)))
        donor = source("part", chain(32, (200, 0, 0)), rim=chain(donor_rim, (0, 200, 0)))
        return target, donor

    def test_finer_donor_maps_are_refused_instead_of_enlarging_the_head_maps(self):
        from graft_uv_upscale import ReceiverMapsLocked
        from graft_uv_reuse import prepare_uv_reuse
        for placement in ("same_position", "move_to_empty", None):
            with self.subTest(placement=placement):
                target, donor = self.sources(32)
                before = [deepcopy(value.tree) for value in (target, donor)]
                with self.assertRaises(ReceiverMapsLocked) as caught:
                    prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1, uv_placement=placement,
                                     keep_receiver_textures=True)
                self.assertEqual((caught.exception.slot, caught.exception.part, caught.exception.head),
                                 ("_RimlightTex", (32, 32), (8, 8)))
                self.assertEqual([value.tree for value in (target, donor)], before)
                # Body keeps the old behaviour: its own rim map may be enlarged.
                result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1, uv_placement=placement)
                self.assertEqual(result.textures["_RimlightTex"].width, 32)

    def test_coarser_donor_maps_grow_to_the_head_size_and_head_sizes_stay(self):
        from graft_uv_reuse import prepare_uv_reuse
        for placement in ("same_position", "move_to_empty"):
            with self.subTest(placement=placement):
                target, donor = self.sources(4)
                result = prepare_uv_reuse([target, donor], mesh([RECEIVER, DONOR]), 1, uv_placement=placement,
                                          keep_receiver_textures=True)
                self.assertIsNotNone(result)
                self.assertEqual({slot: (texture.width, texture.height, texture.mip_count)
                                  for slot, texture in result.textures.items()},
                                 {"_MainTex": (32, 32, 6), "_RimlightTex": (8, 8, 4)})
                rim = levels(result.textures["_RimlightTex"])[0]
                original = np.asarray(chain(8, (40, 50, 60))[0])
                changed = np.any(rim != original, axis=2)
                self.assertTrue(changed.any())
                # Donor texels are the 4x4 donor map replicated 2x (nearest), nothing else.
                self.assertTrue(np.all(rim[changed] == (0, 200, 0, 255)))

    def test_head_bake_keeps_head_texture_sizes_and_mip_counts(self):
        target, renderer, mesh_object, material = fixture((0, 0, 255, 255), size=16)
        donor, _, _, donor_material = fixture((255, 0, 0, 255), size=16)
        add_textures(material, {"_MainTex": (16, (0, 0, 255)), "_RimlightTex": (4, (0, 255, 255))})
        target = UnityPy.load(target.file.save(packer="original"))
        objects = {obj.path_id: obj for obj in target.objects}
        renderer, mesh_object, material = (objects[obj.path_id] for obj in (renderer, mesh_object, material))
        sizes = texture_sizes(target, material.path_id)
        self.assertEqual(sizes, {"_MainTex": (16, 16, 5), "_RimlightTex": (4, 4, 3)})
        binding = {"material": material, "head_all": 0, "renderers": [renderer]}
        bake = HeadBakeTests.bake.__get__(SimpleNamespace(target=target, renderer=renderer, mesh=mesh_object,
                                                          donor=None, donor_material=None))
        tree = HeadBakeTests.groups(SimpleNamespace(mesh=mesh_object),
                                    ((.05, .05), (.2, .05), (.05, .2)), ((.6, .1), (.8, .1), (.6, .3)))
        for rim, refused in ((16, True), (2, False)):
            with self.subTest(donor_rim=rim):
                donor_copy = UnityPy.load(donor.file.save(packer="original"))
                donor_objects = {obj.path_id: obj for obj in donor_copy.objects}
                add_textures(donor_objects[donor_material.path_id],
                             {"_MainTex": (16, (255, 0, 0)), "_RimlightTex": (rim, (255, 255, 0))})
                donor_copy = UnityPy.load(donor_copy.file.save(packer="original"))
                before = raw_objects(target)
                with patch.object(compat, "head_material_binding", return_value=binding):
                    if refused:
                        with self.assertRaises(ValueError) as caught:
                            bake_renderer_for_game(target, renderer, mesh_object, mesh_tree=deepcopy(tree),
                                additional_sources=[(donor_copy, donor_material.path_id)],
                                uv_placement="move_to_empty", face_surfaces=[])
                        self.assertTrue(str(caught.exception).startswith(compat.HEAD_MAP_DETAIL), caught.exception)
                        self.assertIn("_RimlightTex: the part uses 16×16 for a 16×16 main texture; the head uses 4×4 for 16×16.",
                                      str(caught.exception))
                        self.assertEqual(raw_objects(target), before)
                        continue
                    stats = bake_renderer_for_game(target, renderer, mesh_object, mesh_tree=deepcopy(tree),
                        additional_sources=[(donor_copy, donor_material.path_id)],
                        uv_placement="move_to_empty", face_surfaces=[])
                self.assertTrue(stats["head_material"])
                saved = UnityPy.load(target.file.save(packer="original"))
                self.assertEqual(texture_sizes(saved, material.path_id), sizes)


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
        for sentence in (HEAD_ATLAS_REFUSED, HEAD_FACE_REQUIRED, HEAD_NO_SPACE, FACE_TARGET_REFUSED, CULL_MODE_HINT,
                         compat.HEAD_MAP_DETAIL, compat.HEAD_POSITION_IN_USE, compat.HEAD_TEXTURES_INCOMPATIBLE):
            with self.subTest(sentence=sentence[:40]):
                self.assertIn('"' + sentence + '"', script)
                for language in ("ko", "ja"):
                    self.assertNotEqual(i18n.tr(sentence, language), sentence)
                    self.assertIn(sentence, cpt._TRANSLATIONS[language])
                    self.assertNotEqual(cpt._TRANSLATIONS[language][sentence], sentence)
        self.assertNotRegex(CULL_MODE_HINT, re.compile("head accessory", re.I))
        for sentence in (HEAD_ATLAS_REFUSED, HEAD_NO_SPACE, FACE_TARGET_REFUSED, CULL_MODE_HINT):
            self.assertNotIn("wearer", sentence, "the part panel calls it the receiving mesh")

    def test_detail_templates_translate_with_their_values_kept(self):
        from graft_texture_atlas import CULL_MODE_DETAIL
        script = (ROOT / "webtools/web/static/viewer-transplants.js").read_text(encoding="utf-8")
        templates = (compat.HEAD_MAP_DETAIL_DENSITY, compat.HEAD_MAP_DETAIL_SIZE, compat.HEAD_DETAIL_POSITION,
                     compat.HEAD_DETAIL_ISLAND, compat.HEAD_DETAIL_SEARCH, CULL_MODE_DETAIL)
        for template in templates:
            names = set(re.findall(r"\{(\w+)\}", template))
            with self.subTest(template=template[:40]):
                self.assertIn('"' + template + '"', script)
                for language in ("ko", "ja"):
                    translated = cpt._TRANSLATIONS[language][template]
                    self.assertEqual(set(re.findall(r"\{(\w+)\}", translated)), names)
        message = HEAD_NO_SPACE + " " + compat.HEAD_DETAIL_ISLAND.format(
            island=3, islands=22, width=93, height=129, slot="_RimlightTex")
        with patch.object(cpt, "_LANG", "ko"):
            translated = cpt._tr_reason(message)
        self.assertEqual(translated, cpt._TRANSLATIONS["ko"][HEAD_NO_SPACE] + " UV 섬 22개 중 3번째(93×129 px)가 "
                         "_RimlightTex에서 빈 텍셀을 찾지 못했습니다.")
        with patch.object(cpt, "_LANG", "en"):
            self.assertEqual(cpt._tr_reason(message), message)


if __name__ == "__main__":
    unittest.main()
