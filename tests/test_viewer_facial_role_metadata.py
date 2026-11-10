"""Facial material roles are source metadata, never arbitrary mesh names."""
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from webtools.core import model_faces as faces
from webtools.core import model_viewer as viewer
from webtools.core import viewer_mod_package, viewer_archive


class FacialRoleMetadataTests(unittest.TestCase):
    def setUp(self):
        import UnityPy
        self.unity = UnityPy
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = (Path(__file__).parent / "fixtures/viewer_textured_triangle.unity").read_bytes()

    def source(self, filename, name):
        env = self.unity.load(self.fixture)
        for obj in env.objects:
            if obj.type.name in ("GameObject", "Mesh"):
                tree = obj.read_typetree()
                tree["m_Name"] = name
                obj.save_typetree(tree)
        path = self.root / filename
        path.write_bytes(next(iter(env.files.values())).save())
        return path

    def prepare(self, *paths):
        metadata = viewer.prepare(list(map(str, paths)), face_context={"enabled": False})
        raw = viewer.get_model(metadata["id"])
        length, = struct.unpack_from("<I", raw, 12)
        return metadata, json.loads(raw[20:20 + length]), raw[28 + length:]

    def test_an_unrelated_mesh_named_mouth_does_not_change_its_material_role(self):
        path = self.source("ordinary.unity", "Mouth")
        _, doc, _ = self.prepare(path)
        self.assertFalse(any(node.get("extras", {}).get("viewerFacialRole") for node in doc["nodes"]))

    def test_explicit_native_face_keeps_role_with_automatic_face_discovery_disabled(self):
        body = self.source("costume.unity", "Face")
        facial = self.source("facial.unity", "Mouth")
        baseline, before, binary = self.prepare(body, facial)
        hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (body, facial)}
        # Isolate the existing native-prefab provenance recognizer. Geometry,
        # serialization, disabled FacePlan and renderer-role classification run
        # through their real implementations on the independent Unity fixture.
        with patch.object(faces, "_names", return_value=(set(), {str(facial)})):
            metadata, after, current_binary = self.prepare(body, facial)
        roles = [(node["name"], node.get("extras", {}).get("viewerFacialRole"))
                 for node in after["nodes"] if "mesh" in node]
        self.assertEqual(roles, [("Face", None), ("Mouth", "mouth")])
        self.assertFalse(metadata["faces"]["enabled"])
        self.assertEqual(metadata["faces"], baseline["faces"])
        self.assertEqual(after["meshes"], before["meshes"])
        self.assertEqual(after["materials"], before["materials"])
        self.assertEqual(current_binary, binary)
        self.assertEqual(hashes, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in hashes})

    def test_native_facial_source_does_not_tag_other_parts_or_a_named_mouth_in_another_source(self):
        unrelated = self.source("accessory.unity", "Mouth")
        native = self.source("facial.unity", "Eye")
        with patch.object(faces, "_names", return_value=(set(), {str(native)})):
            _, doc, _ = self.prepare(unrelated, native)
        self.assertFalse(any(node.get("extras", {}).get("viewerFacialRole") for node in doc["nodes"]))

    def native_bundle(self, *, face, container=None):
        from test_viewer_transplants import costume_fixture
        env = self.unity.load(costume_fixture())
        renderer_ids = set()
        for obj in env.objects:
            if obj.type.name == "SkinnedMeshRenderer":
                renderer_ids.add(obj.read_typetree()["m_GameObject"]["m_PathID"])
        for obj in env.objects:
            tree = obj.read_typetree()
            if obj.type.name == "AssetBundle":
                tree["m_Name"] = tree["m_AssetBundleName"] = "ch0201_co0000_facedynamic.prefab.unity3d" if face else "ch0201_co0001.prefab.unity3d"
                if face:
                    value = tree["m_Container"][0][1]
                    tree["m_Container"] = [(container or "assets/llas/resources/characters/models/ch0201/ch0201_co0000_facedynamic.prefab", value)]
            elif obj.type.name == "Texture2D":
                tree["m_Name"] = "ch0201_co0000_head" if face else "ch0201_co0001_body"
            elif face and (obj.type.name == "Mesh" or obj.type.name == "GameObject" and obj.path_id in renderer_ids):
                tree["m_Name"] = "Mouth"
            obj.save_typetree(tree)
        return env.file.save()

    def test_private_face_on_zip_reopen_retains_native_container_role(self):
        body, facial = self.native_bundle(face=False), self.native_bundle(face=True)
        path = self.root / "face-on.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("body.unity", body)
            archive.writestr("face.unity", facial)
            archive.writestr("modinstall.txt", "costume_file='body.unity'\ncostume_facedynamic_file='face.unity'\nchara_id=201\n")
        temporary = self.root / "private"; temporary.mkdir()
        proofs = viewer_mod_package._isolate_face_graph(path, temporary, lambda: False)
        self.assertTrue(all(row["all_nonidentity_data_preserved"] for row in proofs))
        with zipfile.ZipFile(path) as archive:
            private_face = archive.read("face.unity")
        bundle = next(obj for obj in self.unity.load(private_face).objects if obj.type.name == "AssetBundle")
        declaration = bundle.read_typetree()
        self.assertNotIn("facedynamic", declaration["m_Name"])
        self.assertIn("_facedynamic.prefab", declaration["m_Container"][0][0])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        for enabled in (False, True):
            with self.subTest(auto_face=enabled), patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root)}):
                with viewer_archive.expand_inputs([str(path)], self.root / "cache") as expanded:
                    metadata = viewer.prepare(expanded.paths, face_context={"enabled": enabled, "allow_download": False,
                        "origins": expanded.origins, "manifest_paths": expanded.manifest_paths})
                raw = viewer.get_model(metadata["id"])
                size, = struct.unpack_from("<I", raw, 12)
                doc = json.loads(raw[20:20 + size])
                mouths = [node for node in doc["nodes"] if node.get("name") == "Mouth"]
                self.assertTrue(mouths)
                self.assertTrue(all(node.get("extras", {}).get("viewerFacialRole") == "mouth" for node in mouths))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_private_unrelated_or_mismatched_container_cannot_declare_a_mouth(self):
        from webtools.core import bundle_identity
        for container in ("assets/custom/Mouth.prefab", "assets/llas/resources/characters/models/ch0201/ch0202_co0000_facedynamic.prefab"):
            with self.subTest(container=container):
                raw, _ = bundle_identity.isolate_verified_bundle(self.native_bundle(face=True, container=container), "unrelated-face-declaration")
                path = self.root / "unrelated-private.unity"; path.write_bytes(raw)
                _, doc, _ = self.prepare(path)
                self.assertFalse(any(node.get("extras", {}).get("viewerFacialRole") for node in doc["nodes"]))


if __name__ == "__main__":
    unittest.main()
