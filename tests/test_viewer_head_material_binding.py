"""The viewer draws head meshes with BodyPartManager.headMaterial, like the game.

MergeAndCombineFaceMesh.MergeFace (GL 3.12.0 0x2c94ff4) sets headMaterial on
every Renderer below headAll (set_sharedMaterial loop at 0x2c95478) when the
face needs merging. A grafted Hair that serializes another material must
therefore preview with headMaterial, except on masked heads.
"""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from webtools.core import model_faces, model_viewer


_FILES = {"costume": SimpleNamespace(name="costume"), "face": SimpleNamespace(name="face")}


class _Object:
    def __init__(self, path_id, kind, tree, source):
        self.path_id, self.type, self.tree, self.source = path_id, SimpleNamespace(name=kind), tree, source
        self.assets_file = _FILES[source]

    def read_typetree(self):
        return self.tree


def _pointer(path_id):
    return {"m_FileID": 0, "m_PathID": path_id}


class _Scene:
    def __init__(self, objects, renderers):
        self.env = SimpleNamespace(objects=objects)
        self.objects = {obj.path_id: obj for obj in objects}
        self.deadline = time.monotonic() + 30
        self.transforms = {obj.tree["m_GameObject"]["m_PathID"]: obj for obj in objects if obj.type.name == "Transform"}
        self.renderers = renderers

    def tree(self, obj):
        return obj.tree

    def name(self, obj):
        return obj.tree.get("m_Name", "")


def head_scene(merge=1, masked=False):
    objects, ids, renderers = [], iter(range(1, 1000)), []

    def add(kind, tree, source="costume"):
        objects.append(_Object(next(ids), kind, tree, source))
        return objects[-1]

    def node(name, parent=None, source="costume"):
        game = add("GameObject", {"m_Name": name}, source)
        transform = add("Transform", {"m_GameObject": _pointer(game.path_id), "m_Children": [],
                                      "m_Father": _pointer(parent[1].path_id) if parent else {}}, source)
        if parent:
            parent[1].tree["m_Children"].append(_pointer(transform.path_id))
        return game, transform

    root = node("ch0212_co0001_member")
    head = node("Head", node("Hips", root))
    head_all = node("Head_All", head)
    face_holder = node("Head_Face", head_all)
    if masked:
        node("mesh_facedots", face_holder)
    head_material = add("Material", {"m_Name": "ch0212_co0001_head"})
    copied = add("Material", {"m_Name": "ch0212_co0001_head"})
    body_material = add("Material", {"m_Name": "ch0212_co0001_body"})
    for name, parent, material in (("Hair", node("mesh_hair", head_all), copied),
                                   ("Face", node("mesh_face", head_all), head_material),
                                   ("Body", node("mesh_body", root), body_material)):
        game, _ = node(name, parent)
        renderer = add("SkinnedMeshRenderer", {"m_GameObject": _pointer(game.path_id), "m_Materials": [_pointer(material.path_id)]})
        renderers.append((renderer, renderer.tree, game))
    prefab = node("ch0212_co0000_facedynamic", source="face")
    eye_game, _ = node("Eye", node("mesh_face", prefab, "face"), "face")
    eye = add("SkinnedMeshRenderer", {"m_GameObject": _pointer(eye_game.path_id), "m_Materials": []}, "face")
    renderers.append((eye, eye.tree, eye_game))
    face = add("MonoBehaviour", {"m_GameObject": _pointer(prefab[0].path_id),
                                 "memberFaceData": {"needsMergingFace": merge}}, "face")
    add("MonoBehaviour", {"head": _pointer(head[0].path_id), "headAll": _pointer(head_all[0].path_id),
                          "face": _pointer(face.path_id), "headMaterial": _pointer(head_material.path_id)})
    scene = _Scene(objects, renderers)
    return scene, {renderer.tree["m_GameObject"]["m_PathID"]: renderer for renderer, _, _ in renderers}, {
        "head": head_material, "copied": copied, "body": body_material}


def bound(scene):
    plan = SimpleNamespace(material_bindings={}, dynamic_sources=set(), head_material=None)

    def patched():
        return (patch.object(model_viewer, "_ref", side_effect=lambda owner, p: scene.objects.get((p or {}).get("m_PathID"))),
                patch.object(model_viewer, "_key", side_effect=lambda obj: obj.path_id),
                patch.object(model_viewer, "_source_path", side_effect=lambda obj: obj.source))

    def run(function, *arguments):
        first, second, third = patched()
        with first, second, third:
            return function(plan, *arguments)

    run(model_faces.FacePlan.bind_selected_materials, scene, {"face"})
    return lambda renderer, material: run(model_faces.FacePlan.material, renderer, material)


def renderer_named(scene, name):
    return next(renderer for renderer, _, game in scene.renderers if game.tree["m_Name"] == name)


class ViewerHeadMaterialBindingTests(unittest.TestCase):
    def test_grafted_hair_with_a_copied_material_previews_with_head_material(self):
        scene, _, materials = head_scene()
        material = bound(scene)
        self.assertIs(material(renderer_named(scene, "Hair"), materials["copied"]), materials["head"])
        self.assertIs(material(renderer_named(scene, "Face"), materials["head"]), materials["head"])
        self.assertIs(material(renderer_named(scene, "Body"), materials["body"]), materials["body"])
        self.assertIs(material(renderer_named(scene, "Eye"), None), materials["head"], "facial prefab binding is kept")

    def test_masked_or_unmerged_heads_keep_serialized_head_materials(self):
        for options in ({"masked": True}, {"merge": 0}):
            with self.subTest(**options):
                scene, _, materials = head_scene(**options)
                material = bound(scene)
                self.assertIs(material(renderer_named(scene, "Hair"), materials["copied"]), materials["copied"])
                self.assertIs(material(renderer_named(scene, "Eye"), None), materials["head"])


if __name__ == "__main__":
    unittest.main()


class GraftTargetFlagTests(unittest.TestCase):
    """Wearer-mesh choices exclude the pieces the client merges into its face."""

    def test_mesh_face_ancestry_is_detected_by_exact_name(self):
        scene, _, _ = head_scene()
        names = {game.tree["m_Name"]: game for _, _, game in scene.renderers}
        with patch.object(model_viewer, "_ref", side_effect=lambda owner, p: scene.objects.get((p or {}).get("m_PathID"))), \
                patch.object(model_viewer, "_key", side_effect=lambda obj: obj.path_id), \
                patch.object(model_viewer, "_source_path", side_effect=lambda obj: obj.source):
            self.assertTrue(model_viewer._beneath_named(scene, names["Face"], "mesh_face"))
            self.assertFalse(model_viewer._beneath_named(scene, names["Hair"], "mesh_face"))
            self.assertFalse(model_viewer._beneath_named(scene, names["Body"], "mesh_face"))
            self.assertFalse(model_viewer._beneath_named(scene, names["Face"], "Mesh_Face"))
