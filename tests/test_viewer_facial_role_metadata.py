"""Facial material roles are source metadata, never arbitrary mesh names."""
import hashlib
import copy
import json
import os
from pathlib import Path
import struct
import tempfile
import secrets
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

    def bound_face_pair(self, *, linked=True):
        """Serialize the real manager pointer contract, with a neutral prefab material."""
        from UnityPy.helpers.TypeTreeNode import TypeTreeNode
        from UnityPy.files.SerializedFile import FileIdentifier
        from test_viewer_transplants import costume_fixture
        from webtools.core import bundle_identity
        raw = costume_fixture()
        face_env = self.unity.load(raw)
        objects = {obj.path_id: obj for obj in face_env.objects}
        for obj in list(face_env.objects):
            tree = obj.read_typetree()
            if obj.type.name == "AssetBundle":
                tree.update(m_Name="ch0201_co0000_facedynamic.prefab.unity3d",
                            m_AssetBundleName="ch0201_co0000_facedynamic.prefab.unity3d")
                tree["m_Container"] = [("assets/llas/resources/characters/models/ch0201/ch0201_co0000_facedynamic.prefab", tree["m_Container"][0][1])]
            elif obj.type.name == "GameObject" and obj.path_id == 2:
                tree["m_Name"] = "ch0201_co0000_facedynamic"
            elif obj.type.name == "GameObject" and obj.path_id == 10 or obj.type.name == "Mesh":
                tree["m_Name"] = "Eye"
            elif obj.type.name == "Material":
                tree["m_Name"] = "neutral_prefab_head"
                for name, value in tree["m_SavedProperties"]["m_TexEnvs"]:
                    if name == "_MainTex":
                        value["m_Texture"] = {"m_FileID": 0, "m_PathID": 0}
            elif obj.type.name == "Texture2D":
                tree["m_Name"] = "ch0201_co0000_head"
            elif obj.path_id == 16:
                tree["m_GameObject"] = {"m_FileID": 0, "m_PathID": 2}
            obj.save_typetree(tree)
        # A second real renderer makes mouth and eye material loss independent.
        for source_id, target_id in ((1, 303), (10, 300), (11, 301), (12, 302)):
            obj = copy.copy(objects[source_id]); obj.path_id = target_id
            tree = copy.deepcopy(objects[source_id].read_typetree())
            if source_id == 1:
                tree["m_Name"] = "Mouth"
            elif source_id == 10:
                tree.update(m_Name="Mouth", m_Component=[{"component": {"m_FileID": 0, "m_PathID": n}} for n in (301, 302)])
            elif source_id == 11:
                tree.update(m_GameObject={"m_FileID": 0, "m_PathID": 300}, m_Father={"m_FileID": 0, "m_PathID": 3})
            else:
                tree.update(m_GameObject={"m_FileID": 0, "m_PathID": 300}, m_Mesh={"m_FileID": 0, "m_PathID": 303})
            obj.assets_file.objects[target_id] = obj; obj.save_typetree(tree)
        root = objects[3].read_typetree(); root["m_Children"].append({"m_FileID": 0, "m_PathID": 301}); objects[3].save_typetree(root)
        face_raw, _ = bundle_identity.isolate_verified_bundle(face_env.file.save(), "neutral-facial-material-fixture")
        face_assets = next(iter(self.unity.load(face_raw).assets))
        face_cab = face_assets.name
        face_name = next(obj.read_typetree()["m_AssetBundleName"] for obj in face_assets.objects.values() if obj.type.name == "AssetBundle")
        body_env = self.unity.load(raw); body_objects = {obj.path_id: obj for obj in body_env.objects}
        for obj in body_env.objects:
            tree = obj.read_typetree()
            if obj.type.name == "AssetBundle":
                tree.update(m_Name="ch0201_co0001.prefab.unity3d", m_AssetBundleName="ch0201_co0001.prefab.unity3d", m_Dependencies=[face_name])
            elif obj.type.name == "GameObject" and obj.path_id == 10:
                tree["m_Name"] = "Body"
            elif obj.type.name == "Mesh":
                tree["m_Name"] = "Face"
            elif obj.type.name == "Material":
                tree["m_Name"] = "ch0201_costume_head_atlas"
            elif obj.type.name == "Texture2D":
                tree["m_Name"] = "ch0201_co0001_head"
            obj.save_typetree(tree)
        asset = body_objects[16].assets_file
        external = object.__new__(FileIdentifier)
        external.path, external.temp_empty, external.guid, external.type = face_cab, "", bytes(16), 0
        asset.externals.append(external)
        fields = body_objects[16].serialized_type.node.m_Children[:4]
        pointers = []
        for name in ("face", "head", "headMaterial"):
            node = TypeTreeNode(**fields[0].to_dict()); node.m_Name = name; pointers.append(node)
        serialized = copy.copy(body_objects[16].serialized_type)
        serialized.node = TypeTreeNode(**{**serialized.node.to_dict(), "m_Children": fields + pointers})
        serialized.script_type_index = len(asset.types)
        component = copy.copy(body_objects[16]); component.path_id = 300
        component.type_id = len(asset.types); component.serialized_type = serialized
        asset.types.append(serialized); asset.objects[300] = component
        component.save_typetree({"m_GameObject": {"m_FileID": 0, "m_PathID": 2}, "m_Enabled": 1,
            "m_Script": {"m_FileID": 0, "m_PathID": 17}, "m_Name": "Neutral BodyPartManager",
            "face": {"m_FileID": 1, "m_PathID": 16 if linked else 0},
            "head": {"m_FileID": 0, "m_PathID": 110}, "headMaterial": {"m_FileID": 0, "m_PathID": 13}})
        body, face = self.root / "body.unity", self.root / "ch0201_facedynamic.unity"
        body.write_bytes(body_env.file.save()); face.write_bytes(face_raw)
        return body, face

    def material_textures(self, metadata):
        raw = viewer.get_model(metadata["id"]); size, = struct.unpack_from("<I", raw, 12)
        doc, binary = json.loads(raw[20:20 + size]), raw[28 + size:]
        result = {}
        for mesh in doc["meshes"]:
            if mesh["name"] not in ("Face", "Eye", "Mouth"):
                continue
            material = doc["materials"][mesh["primitives"][0]["material"]]
            texture = material.get("pbrMetallicRoughness", {}).get("baseColorTexture")
            png = None
            if texture is not None:
                image = doc["images"][doc["textures"][texture["index"]]["source"]]
                view = doc["bufferViews"][image["bufferView"]]; start = view.get("byteOffset", 0)
                png = binary[start:start + view["byteLength"]]
            result[mesh["name"]] = (material.get("name"), png)
        return result

    def assert_head_atlas(self, metadata):
        textures = self.material_textures(metadata)
        self.assertEqual(set(textures), {"Face", "Eye", "Mouth"})
        self.assertTrue(textures["Face"][1].startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(textures["Eye"], textures["Face"])
        self.assertEqual(textures["Mouth"], textures["Face"])
        return hashlib.sha256(textures["Face"][1]).hexdigest()

    def test_explicit_eye_and_mouth_use_serialized_costume_atlas_even_without_auto_discovery(self):
        body, face = self.bound_face_pair()
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (body, face)}
        hashes = set()
        for enabled in (False, True):
            for rigged in (False, True):
                metadata = viewer.prepare([str(body), str(face)], rigged=rigged,
                    face_context={"enabled": enabled, "allow_download": False})
                hashes.add(self.assert_head_atlas(metadata))
        self.assertEqual(len(hashes), 1)
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})

    def test_a_matching_face_name_without_the_actual_runtime_pointer_cannot_borrow_an_atlas(self):
        body, face = self.bound_face_pair(linked=False)
        metadata = viewer.prepare([str(body), str(face)], face_context={"enabled": False})
        textures = self.material_textures(metadata)
        self.assertIsNotNone(textures["Face"][1])
        self.assertIsNone(textures["Eye"][1])
        self.assertIsNone(textures["Mouth"][1])

    def test_saved_preview_copies_preserve_automatic_face_material_binding(self):
        from webtools.core import model_edits
        body, face = self.bound_face_pair()
        prepared = viewer.prepare([str(body)], rigged=True, face_context={"enabled": True,
            "allow_download": False, "library_roots": [str(self.root)], "cache_dir": str(self.root / "cache")})
        token = secrets.token_hex(16)
        editing = model_edits.register_session(token, [str(body)], prepared["rig"],
            companions=viewer.get_editing_companions(prepared["id"]))
        target = next(row for row in editing["nodes"] if row["name"] == "BreastSize" and row["sourceIndex"] == 0)
        result = model_edits.export(token, {"version": 1, "savedSettingsEnabled": True,
            "edits": [{"node": target["node"], "method": "node", "scale": [1.2, 1, 1]}]}, self.root / "saved")
        self.assertEqual(len(result["preview_paths"]), 2)
        reopened = viewer.prepare(result["preview_paths"], rigged=True,
            face_context={"enabled": True, "allow_download": False})
        self.assertEqual(self.assert_head_atlas(prepared), self.assert_head_atlas(reopened))
        self.assertTrue(result["originals_preserved"])
        self.assertEqual(Path(result["original_paths"][0]).read_bytes(), body.read_bytes())
        self.assertEqual(Path(result["original_paths"][1]).read_bytes(), face.read_bytes())

    def test_private_packaged_face_reopen_preserves_the_costume_atlas_and_original_pixels(self):
        body, face = self.bound_face_pair()
        expected = self.assert_head_atlas(viewer.prepare([str(body), str(face)], face_context={"enabled": False}))
        path = self.root / "face-on.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("body.unity", body.read_bytes()); archive.writestr("face.unity", face.read_bytes())
            archive.writestr("modinstall.txt", "costume_file='body.unity'\ncostume_facedynamic_file='face.unity'\nchara_id=201\n")
        temporary = self.root / "private"; temporary.mkdir()
        proofs = viewer_mod_package._isolate_face_graph(path, temporary, lambda: False)
        self.assertTrue(all(row["all_nonidentity_data_preserved"] for row in proofs))
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        for enabled in (False, True):
            with patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root)}):
                with viewer_archive.expand_inputs([str(path)], self.root / "cache") as expanded:
                    metadata = viewer.prepare(expanded.paths, rigged=True, face_context={"enabled": enabled,
                        "allow_download": False, "origins": expanded.origins, "manifest_paths": expanded.manifest_paths})
            self.assertEqual(self.assert_head_atlas(metadata), expected)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_package_face_option_keeps_saved_preview_colors_and_scopes_included_face(self):
        from webtools.core import model_edits, viewer_mod_flow
        from test_viewer_mod_flow import Job
        body, face = self.bound_face_pair()
        originals = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (body, face)}
        prepared = viewer.prepare([str(body)], rigged=True, face_context={"enabled": True,
            "allow_download": False, "library_roots": [str(self.root)], "cache_dir": str(self.root / "cache")})
        expected = self.assert_head_atlas(prepared)
        token = secrets.token_hex(16)
        model_edits.register_session(token, [str(body)], prepared["rig"],
            companions=viewer.get_editing_companions(prepared["id"]))
        for include in (False, True):
            with self.subTest(include_face=include):
                result = viewer_mod_flow.create_package(token,
                    {"version": 1, "savedSettingsEnabled": True, "edits": []},
                    output_root=self.root / "outputs", repo_root=Path(__file__).resolve().parents[2],
                    cache_root=self.root / "cache", display_name="Saved facial material", character_id=201,
                    include_face_edits=include, job=Job())
                reopened = viewer.prepare(result["preview_paths"], rigged=True,
                    face_context={"enabled": True, "allow_download": False})
                self.assertEqual(self.assert_head_atlas(reopened), expected)
                path = result["mod_package"]["package_path"]
                with zipfile.ZipFile(path) as archive:
                    manifest = next(name for name in archive.namelist() if name.endswith("modinstall.txt"))
                    from webtools.core.viewer_mod_package import _manifest
                    fields, _ = _manifest(archive.read(manifest), "Test")
                    self.assertEqual(bool(fields.get("costume_facedynamic_file")), include)
                with patch.dict(os.environ, {"SUKUSTA_DIR": str(self.root)}):
                    with viewer_archive.expand_inputs([path], self.root / "expanded") as expanded:
                        packaged = viewer.prepare(expanded.paths, rigged=True, face_context={"enabled": True,
                            "allow_download": False, "library_roots": [str(self.root)],
                            "origins": expanded.origins, "manifest_paths": expanded.manifest_paths})
                self.assertEqual(self.assert_head_atlas(packaged), expected)
        self.assertEqual(originals, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in originals})


if __name__ == "__main__":
    unittest.main()
