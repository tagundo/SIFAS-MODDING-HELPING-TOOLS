"""Native head-pointer proofs must never treat costume labels as anatomy."""
import copy
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import UnityPy

from webtools.core import model_viewer, viewer_thumbnail_roles, viewer_thumbnails


FIXTURE = Path(__file__).parent / "fixtures/viewer_persistence.unity"


def pointer(path_id, file_id=0):
    return {"m_FileID": file_id, "m_PathID": path_id}


class Objects:
    def __init__(self):
        self.files = []
        self.renderers = []

    def file(self, name="CAB-body", source="/original/body.unity"):
        file = SimpleNamespace(name=name, objects={}, externals=[], preview_source_path=source)
        self.files.append(file)
        return file

    @staticmethod
    def add(file, path_id, kind, **tree):
        obj = SimpleNamespace(path_id=path_id, type=SimpleNamespace(name=kind), assets_file=file,
                              value=tree)
        obj.read_typetree = lambda: copy.deepcopy(obj.value)
        file.objects[path_id] = obj
        return obj

    def game(self, file, path_id, name, parent=0):
        game = self.add(file, path_id, "GameObject", m_Name=name)
        self.add(file, path_id + 100, "Transform", m_GameObject=pointer(path_id), m_Father=pointer(parent))
        return game

    def renderer(self, file, game, renderer_id, mesh_id, name):
        mesh = self.add(file, mesh_id, "Mesh", m_Name=name)
        renderer = self.add(file, renderer_id, "SkinnedMeshRenderer", m_GameObject=pointer(game.path_id),
                            m_Mesh=pointer(mesh.path_id), m_Bones=[pointer(110)])
        self.renderers.append((renderer, renderer.value, game))
        return renderer, mesh

    def component(self, file, name="BodyPartManager", root=1, **fields):
        script = self.add(file, 401, "MonoScript", m_ClassName=name,
                          m_Namespace="LLAS.Components.Members", m_AssemblyName="Assembly-CSharp.dll")
        component = self.add(file, 501, "MonoBehaviour", m_GameObject=pointer(root),
                             m_Script=pointer(script.path_id), **fields)
        return component, script

    def scene(self):
        objects = [obj for file in self.files for obj in file.objects.values()]
        return SimpleNamespace(env=SimpleNamespace(objects=objects), deadline=time.monotonic() + 5,
                               renderers=self.renderers, tree=lambda obj: obj.value,
                               name=lambda obj: obj.value.get("m_Name", ""))


def hierarchy():
    env = Objects()
    file = env.file()
    env.game(file, 1, "Costume")
    env.game(file, 10, "arbitrary-native-head-root", 101)
    face = env.game(file, 20, "Face_Print", 110)
    hair = env.game(file, 30, "Hair_Ribbon", 110)
    costume = env.game(file, 40, "Face_Print", 101)
    env.renderer(file, face, 201, 301, "unknown facial surface")
    env.renderer(file, hair, 202, 302, "unknown hair surface")
    env.renderer(file, costume, 203, 303, "Eye_Embroidery")
    component, script = env.component(file, headAll=pointer(10))
    return env, file, component, script


class ThumbnailRoleTests(unittest.TestCase):
    def test_thumbnail_keeps_typed_head_dependency_but_hides_unrelated_dependency_body(self):
        env, body, component, _ = hierarchy()
        body.externals = [SimpleNamespace(path="archive:/CAB-head/CAB-head")]
        dependency = env.file("CAB-head", "/original/head.unity")
        head = env.game(dependency, 10, "native head")
        env.renderer(dependency, head, 250, 350, "arbitrary face surface")
        unrelated = env.game(dependency, 40, "separate donor body")
        env.renderer(dependency, unrelated, 251, 351, "unrelated costume")
        component.value["headAll"] = pointer(10, 1)
        scene = env.scene()
        with patch.object(model_viewer, "_environment", return_value=scene.env), patch.object(model_viewer, "_Scene", return_value=scene):
            result = viewer_thumbnails._excluded_meshes([body.preview_source_path, dependency.preview_source_path], [body.preview_source_path])
        self.assertEqual([row["mesh"]["id"] for row in result], ["351"])
        self.assertEqual(result[0]["role"], "dependency")
        self.assertEqual(viewer_thumbnails._excluded_meshes([body.preview_source_path]), [])

    def test_real_neutral_costume_mesh_names_never_authorize_head_removal(self):
        raw = FIXTURE.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            for name in ("Face_Print", "Hair_Ribbon", "Eye_Embroidery", "Mouth_Bow"):
                with self.subTest(name=name):
                    env = UnityPy.load(raw)
                    for obj in env.objects:
                        if obj.type.name == "Mesh":
                            tree = obj.read_typetree()
                            tree["m_Name"] = name
                            obj.save_typetree(tree)
                    path = Path(directory) / (name + ".unity")
                    data = env.file.save(packer="original")
                    path.write_bytes(data)
                    deadline = time.monotonic() + 10
                    scene = model_viewer._Scene(model_viewer._environment([str(path)], deadline), deadline)
                    self.assertEqual(viewer_thumbnail_roles.excluded_renderers(scene, [str(path)]), [])
                    self.assertEqual(path.read_bytes(), data)

    def test_exact_manager_head_subtree_excludes_head_but_keeps_body_using_head_joint(self):
        env, file, _, _ = hierarchy()
        original = {key: copy.deepcopy(obj.value) for key, obj in file.objects.items()}
        result = viewer_thumbnail_roles.excluded_renderers(env.scene(), [file.preview_source_path])
        self.assertEqual({row["mesh"]["id"] for row in result}, {"301", "302"})
        self.assertNotIn("303", {row["mesh"]["id"] for row in result})
        self.assertTrue(all(row["role"] == "head" for row in result))
        self.assertTrue(all(row["proofs"][0]["field"] == "headAll" for row in result))
        self.assertEqual(original, {key: obj.value for key, obj in file.objects.items()})

    def test_wrong_script_namespace_assembly_or_class_preserves_all_geometry(self):
        for field, value in (("m_Namespace", "Custom.Components"),
                             ("m_AssemblyName", "Other.dll"),
                             ("m_ClassName", "BodyPartManagerFake")):
            with self.subTest(field=field):
                env, file, _, script = hierarchy()
                script.value[field] = value
                self.assertEqual(viewer_thumbnail_roles.excluded_renderers(env.scene(), [file.preview_source_path]), [])

    def test_standalone_native_face_and_hair_components_use_exact_root_not_labels(self):
        for kind, role in (("MemberFace", "face"), ("MemberHair", "hair")):
            with self.subTest(kind=kind):
                env, file, component, script = hierarchy()
                script.value["m_ClassName"] = kind
                component.value["m_GameObject"] = pointer(10)
                component.value.pop("headAll")
                result = viewer_thumbnail_roles.excluded_renderers(env.scene(), [file.preview_source_path])
                self.assertEqual({row["mesh"]["id"] for row in result}, {"301", "302"})
                self.assertTrue(all(row["role"] == role for row in result))

    def test_pointer_type_and_cross_file_cab_are_checked_without_path_id_guessing(self):
        for bad in (pointer(10, 1), pointer(True), pointer(10, -1), {"m_FileID": True, "m_PathID": 10}):
            with self.subTest(pointer=bad):
                env, file, component, _ = hierarchy()
                component.value["headAll"] = bad
                self.assertEqual(viewer_thumbnail_roles.excluded_renderers(env.scene(), [file.preview_source_path]), [])

    def test_external_cab_head_reference_requires_one_exact_loaded_asset(self):
        env, file, component, _ = hierarchy()
        file.externals = [SimpleNamespace(path="archive:/CAB-other/CAB-other")]
        other = env.file("CAB-other", "/original/other.unity")
        other_root = env.game(other, 10, "a-native-root-with-no-role-name")
        env.renderer(other, other_root, 250, 350, "Face_Print")
        component.value["headAll"] = pointer(10, 1)
        paths = [file.preview_source_path, other.preview_source_path]
        result = viewer_thumbnail_roles.excluded_renderers(env.scene(), paths)
        self.assertEqual([(row["mesh"]["source"], row["mesh"]["id"]) for row in result], [(1, "350")])
        duplicate = env.file("CAB-other", "/original/duplicate.unity")
        env.game(duplicate, 10, "same numeric ID in an ambiguous CAB")
        self.assertEqual(viewer_thumbnail_roles.excluded_renderers(env.scene(), paths + [duplicate.preview_source_path]), [])

    def test_ambiguous_or_circular_transform_hierarchy_preserves_geometry(self):
        env, file, _, _ = hierarchy()
        env.add(file, 999, "Transform", m_GameObject=pointer(10), m_Father=pointer(101))
        self.assertEqual(viewer_thumbnail_roles.excluded_renderers(env.scene(), [file.preview_source_path]), [])
        env, file, _, _ = hierarchy()
        file.objects[110].value["m_Father"] = pointer(110)
        self.assertEqual(viewer_thumbnail_roles.excluded_renderers(env.scene(), [file.preview_source_path]), [])


if __name__ == "__main__":
    unittest.main()
