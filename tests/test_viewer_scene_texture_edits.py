"""Rina scene recipes preserve native texture scope and canonical pixel edits."""
import base64
import copy
import io
import json
from pathlib import Path
import secrets
import struct
import time
from types import SimpleNamespace
import unittest
import zipfile
import zlib

import numpy as np
from PIL import Image
import UnityPy

from sifas_mesh_baker import read_attr, stream_layout, write_attr
import test_viewer_scene_roles as scene_fixture
from test_viewer_texture_tools import authored_texture, image_from_uri, uri
from viewer_scene_fixture import bundle_fixture
from webtools.core import decode, model_edits as edits, model_materials, model_viewer, viewer_archive
from webtools.core import viewer_mod_flow as flow, viewer_scene_format as fmt, viewer_scene_roles as roles
from webtools.core import viewer_texture_tools as textures


class SceneTextureEditTests(unittest.TestCase):
    def setUp(self):
        # Compose the established fixture without importing/inheriting its test
        # class into this module's unittest discovery inventory.
        self.fixture = scene_fixture.SceneRolesTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.raws, self.images = {}, {}
        for platform in fmt.PLATFORMS:
            for variant in fmt.VARIANTS:
                self.raws[platform, variant], self.images[platform, variant] = self.make_bundle(platform, variant)

    def make_bundle(self, platform, variant):
        raw, images = authored_texture(bundle_fixture(fmt.PLATFORMS[platform], variant))
        environment = UnityPy.load(raw)
        # The shared texture fixture targets Android; restore each real native
        # platform rather than accidentally converting the iOS source to APK.
        for asset in environment.assets:
            asset.target_platform = fmt.PLATFORMS[platform]
            asset._m_target_platform = fmt.PLATFORMS[platform]
        names = {obj.path_id: obj.read_typetree().get("m_Name")
                 for obj in environment.objects if obj.type.name == "GameObject"}
        transforms = {obj.path_id: names.get(obj.read_typetree()["m_GameObject"]["m_PathID"])
                      for obj in environment.objects if obj.type.name == "Transform"}
        offset = (17 if platform == "ios" else 0) + (29 if variant == "unmasked" else 0)
        images = [image.copy() for image in images]
        for image in images:
            image.putdata([(pixel[0] + offset, pixel[1], pixel[2] + offset, pixel[3])
                           for pixel in image.getdata()])
        for obj in environment.objects:
            tree = obj.read_typetree()
            if obj.type.name == "Texture2D":
                tree["m_Name"] = "ch9999_co0001_body" if variant == "primary" else "ch0209_co0001_body"
                tree["image data"] = b"".join(image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).tobytes()
                                               for image in images)
                obj.save_typetree(tree)
            elif obj.type.name == "MonoBehaviour" and "scaleValues" in tree:
                for row in tree["scaleValues"]:
                    if transforms.get(row["target"]["m_PathID"]) == "BreastSize":
                        row["scaledValue"] = {axis: row["originValue"][axis] * factor
                                              for axis, factor in zip("xyz", (1.2, 1.1, .9))}
                obj.save_typetree(tree)
            elif obj.type.name == "Mesh" and variant == "unmasked":
                count, channels, strides, starts, _ = stream_layout(tree)
                buffer = np.frombuffer(bytes(tree["m_VertexData"]["m_DataSize"]), np.uint8).copy()
                uv = read_attr(buffer, 4, channels, strides, starts, count)
                uv[:, 0] = 1 - uv[:, 0]
                uv[:, 1] *= .5
                write_attr(buffer, uv, 4, channels, strides, starts, count)
                tree["m_VertexData"]["m_DataSize"] = buffer.tobytes()
                obj.save_typetree(tree)
        result = environment.file.save(packer="original")
        self.assertEqual(fmt._native_platform(result), fmt.PLATFORMS[platform])
        return result, images

    def operation(self, token, platform, variant, image=None, padded=False):
        source_hash = fmt.sha(self.raws[platform, variant])
        catalog = textures.inspect(token)["textures"]
        row = next(row for row in catalog if row["sourceSha256"] == source_hash)
        if image is None:
            image = self.images[platform, variant][0].copy()
            alpha = image.getpixel((3, 1))[3]
            image.putpixel((3, 1), (201, 17, 211, alpha))
        encoded = uri(image)
        if padded:
            raw = base64.b64decode(encoded.split(",", 1)[1])
            length = 450 * 1024
            ancillary = b"vpAg" + bytes(length)
            raw = raw[:-12] + struct.pack(">I", length) + ancillary
            raw += struct.pack(">I", zlib.crc32(ancillary) & 0xffffffff) + base64.b64decode(encoded.split(",", 1)[1])[-12:]
            encoded = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        return {"texture": copy.deepcopy(row["texture"]), "sourceSha256": source_hash,
                "png": encoded, "kind": "costume"}, image

    @staticmethod
    def state(*operations):
        return {"version": 1, "savedSettingsEnabled": True, "edits": [], "textures": list(operations)}

    def assert_image(self, raw, expected, original_levels=None):
        environment = UnityPy.load(raw)
        obj = next(obj for obj in environment.objects if obj.type.name == "Texture2D")
        texture = obj.read()
        self.assertEqual((texture.m_Width, texture.m_Height, texture.m_MipCount), (8, 4, 4))
        self.assertEqual(texture.image.convert("RGBA").tobytes(), expected.tobytes())
        if original_levels:
            for level, proxy in enumerate(model_materials._original_mips(obj, texture), 1):
                image = decode._android_image(proxy.read(), time.monotonic() + 10).convert("RGBA")
                self.assertEqual(image.getchannel("A").tobytes(), original_levels[level].getchannel("A").tobytes())
                target = (min(image.width - 1, 3 >> level), min(image.height - 1, 1 >> level))
                for y in range(image.height):
                    for x in range(image.width):
                        if (x, y) != target:
                            self.assertEqual(image.getpixel((x, y)), original_levels[level].getpixel((x, y)))

    @staticmethod
    def recipe(decoded, platform, variant):
        reference = decoded["manifest"]["authoring"][platform][variant]["recipe"]["member"]
        return json.loads(decoded["files"][reference]), decoded["files"][reference]

    def test_dual_platform_scene_texture_only_edit_reopens_without_counter_projection(self):
        original = self.fixture.source(("android", "ios"), self.raws)
        original_bytes = original.read_bytes()
        token, _, _ = self.fixture.prepare(original)
        self.assertTrue(roles.pending_supported_nodes(edits.mod_source_context(token)))
        baseline, before = self.fixture.package(token, self.state())
        reopened, _, restored = self.fixture.prepare(baseline["mod_package"]["package_path"])
        self.assertEqual(restored["edits"], [])
        operation, expected = self.operation(reopened, "android", "primary")
        restored["textures"] = [operation]
        saved, changed = self.fixture.package(reopened, restored)
        for platform in fmt.PLATFORMS:
            for variant in fmt.VARIANTS:
                golden = self.fixture.golden(changed, platform, variant)
                self.assertEqual(fmt._native_platform(golden), fmt.PLATFORMS[platform])
                recipe, _ = self.recipe(changed, platform, variant)
                if (platform, variant) == ("android", "primary"):
                    self.assert_image(golden, expected, self.images[platform, variant])
                    self.assertEqual(len(recipe["state"]["textures"]), 1)
                    self.assertEqual(recipe["state"]["textures"][0]["texture"]["source"], 0)
                    self.assertEqual(recipe["state"]["textures"][0]["sourceSha256"], fmt.sha(self.raws[platform, variant]))
                else:
                    self.assertEqual(golden, self.fixture.golden(before, platform, variant))
                    self.assertFalse(recipe["state"].get("textures"))
        again, _, state = self.fixture.prepare(saved["mod_package"]["package_path"])
        self.assertEqual(state["textures"][0]["sourceSha256"], operation["sourceSha256"])
        repeated, repeated_decoded = self.fixture.package(again, state)
        for platform in fmt.PLATFORMS:
            for variant in fmt.VARIANTS:
                self.assertEqual(self.fixture.golden(repeated_decoded, platform, variant),
                                 self.fixture.golden(changed, platform, variant))
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertTrue(repeated["mod_package"]["installable"])

    def test_nonzero_source_recipe_and_ios_unmasked_reopen_rebind_texture_identity(self):
        paths = []
        for platform in fmt.PLATFORMS:
            for variant in fmt.VARIANTS:
                path = self.root / (platform + "_" + variant + ".unity")
                path.write_bytes(self.raws[platform, variant])
                paths.append(str(path))
        prepared = model_viewer.prepare(paths, rigged=True, face_context={"enabled": False, "allow_download": False})
        token = prepared["id"]
        edits.register_session(token, paths, prepared["rig"])
        foreign, _ = self.operation(token, "android", "unmasked")
        selected, expected = self.operation(token, "ios", "unmasked")
        self.assertEqual(selected["texture"]["source"], 3)
        normalized = edits.validate_state(token, self.state(foreign, selected))
        recipe = edits._recipe(edits._session(token), normalized)
        canonical = roles._normalize_recipe(recipe, self.raws["ios", "unmasked"], "ios_unmasked.unity")
        self.assertEqual(len(canonical["state"]["textures"]), 1)
        canonical_operation = canonical["state"]["textures"][0]
        self.assertEqual(canonical_operation["texture"]["source"], 0)
        self.assertEqual(canonical_operation["sourceSha256"], selected["sourceSha256"])
        self.assertEqual(canonical_operation["png"], selected["png"])

        source = self.fixture.source(("ios",), self.raws)
        source_token, _, _ = self.fixture.prepare(source, "unmasked")
        operation, _ = self.operation(source_token, "ios", "unmasked", expected)
        result, decoded = self.fixture.package(source_token, self.state(operation))
        self.assert_image(self.fixture.golden(decoded, "ios", "unmasked"), expected, self.images["ios", "unmasked"])
        unrelated = self.root / "unrelated-original.unity"
        unrelated.write_bytes(self.raws["android", "primary"])
        scene = result["mod_package"]["package_path"]
        with viewer_archive.expand_inputs([scene], self.root / "offset-cache", variant_choices={scene: "unmasked"}) as expanded:
            combined = [str(unrelated)] + expanded.paths
            prepared = model_viewer.prepare(combined, rigged=True, face_context={"enabled": False, "allow_download": False})
            token = prepared["id"]
            origins = dict(expanded.origins)
            origins[str(unrelated)] = str(unrelated)
            edits.register_session(token, combined, prepared["rig"],
                originals=[str(unrelated)] + (expanded.editing_originals or [scene]), origins=origins,
                archive_members=expanded.archive_members, variants=expanded.editing_variants)
            restored = roles.register_reopened(token, expanded.scene_context)
        self.assertEqual(restored["textures"][0]["texture"]["source"], 1)
        self.assertEqual(restored["textures"][0]["sourceSha256"], fmt.sha(self.raws["ios", "unmasked"]))
        session = edits._session(token)
        actual, _ = edits.edit_source_state(session, 1, restored)
        self.assert_image(actual, expected, self.images["ios", "unmasked"])
        untouched, _ = edits.edit_source_state(session, 0, restored)
        self.assertEqual(untouched, self.raws["android", "primary"])

    def test_raw_rina_pair_keeps_empty_partner_recipe_and_accepts_large_pixel_recipe(self):
        primary = self.root / "board.unity"
        other = self.root / "bare.unity"
        primary.write_bytes(self.raws["android", "primary"])
        other.write_bytes(self.raws["android", "unmasked"])
        token, _, _ = self.fixture.prepare(primary)
        operation, expected = self.operation(token, "android", "primary", padded=True)
        result = flow.create_package(token, self.state(operation), output_root=self.root / "raw-exports",
            repo_root=self.root, cache_root=self.root / "raw-game-cache", display_name="Texture-only Rina scene",
            character_id=209, counterpart_path=str(other), selected_variant="primary",
            job=SimpleNamespace(log=lambda _: None, should_stop=lambda: False))
        decoded = fmt.read_package(result["mod_package"]["package_path"])
        self.assert_image(self.fixture.golden(decoded, "android", "primary"), expected, self.images["android", "primary"])
        self.assertEqual(self.fixture.golden(decoded, "android", "unmasked"), self.raws["android", "unmasked"])
        partner, _ = self.recipe(decoded, "android", "unmasked")
        selected, selected_raw = self.recipe(decoded, "android", "primary")
        self.assertEqual(partner["state"]["edits"], [])
        self.assertFalse(partner["state"].get("textures"))
        self.assertGreater(len(selected_raw), 512 * 1024)
        self.assertEqual(selected["state"]["textures"][0]["png"], operation["png"])
        self.assertEqual(primary.read_bytes(), self.raws["android", "primary"])
        self.assertEqual(other.read_bytes(), self.raws["android", "unmasked"])
        _, _, restored = self.fixture.prepare(result["mod_package"]["package_path"])
        self.assertEqual(restored["textures"][0]["png"], operation["png"])
        self.assertEqual(restored["textures"][0]["sourceSha256"], operation["sourceSha256"])

        # The larger portable pixel recipe budget must not enlarge the outer
        # executable-dispatch manifest's original512KiB metadata limit.
        corrupt = io.BytesIO()
        with zipfile.ZipFile(result["mod_package"]["package_path"]) as source_zip, zipfile.ZipFile(corrupt, "w") as output:
            for entry in source_zip.infolist():
                raw = source_zip.read(entry)
                if entry.filename == fmt.MANIFEST:
                    raw = b" " * (512 * 1024 + 1) + raw
                output.writestr(entry, raw)
        with self.assertRaisesRegex(ValueError, "metadata exceeds its size limit"):
            fmt.read_package(corrupt.getvalue())

    def make_face(self):
        face_raw, levels = authored_texture(bundle_fixture(13, "primary", unit_breast=True))
        face_env = UnityPy.load(face_raw)
        for obj in face_env.objects:
            if obj.type.name == "Texture2D":
                tree = obj.read_typetree()
                # A face companion must not be inferred as another Rina body.
                tree["m_Name"] = "neutral_face_texture"
                obj.save_typetree(tree)
        face_raw = face_env.file.save(packer="original")
        return face_raw, levels

    def package_face(self, token, state, **options):
        return flow.create_package(token, state, output_root=self.root / "face-exports",
            repo_root=self.root, cache_root=self.root / "face-game-cache", display_name="Private face pixels",
            character_id=209, job=SimpleNamespace(log=lambda _: None, should_stop=lambda: False), **options)

    def test_face_texture_inclusion_reopens_with_original_pixel_source_identity(self):
        face_raw, levels = self.make_face()
        face_path = self.root / "original-face.unity"
        face_path.write_bytes(face_raw)
        source = self.fixture.source(("android",), self.raws)
        with zipfile.ZipFile(source) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries["modinstall.txt"] += b"costume_facedynamic_file = 'original-face.unity'\n"
        entries["original-face.unity"] = face_raw
        with zipfile.ZipFile(source, "w") as archive:
            for name, raw in entries.items():
                archive.writestr(name, raw)
        source_original = source.read_bytes()
        with viewer_archive.expand_inputs([str(source)], self.root / "face-cache") as expanded:
            prepared = model_viewer.prepare(expanded.paths, rigged=True,
                face_context={"enabled": False, "allow_download": False})
            token = prepared["id"]
            edits.register_session(token, expanded.paths, prepared["rig"],
                originals=expanded.editing_originals or [str(source)], origins=expanded.origins,
                archive_members=expanded.archive_members, variants=expanded.editing_variants)
        row = next(row for row in textures.inspect(token)["textures"]
                   if row["sourceSha256"] == fmt.sha(face_raw))
        expected = levels[0].copy()
        expected.putpixel((3, 1), (209, 13, 183, expected.getpixel((3, 1))[3]))
        operation = {"texture": row["texture"], "sourceSha256": fmt.sha(face_raw),
                     "png": uri(expected), "kind": "skin"}
        body_operation, body_expected = self.operation(token, "android", "primary")
        result = self.package_face(token, self.state(operation, body_operation), include_face_edits=True)
        decoded = fmt.read_package(result["mod_package"]["package_path"])
        self.assertIn("rina-face-authoring-v1", decoded["manifest"]["requires"])
        face_authoring = decoded["manifest"]["face_authoring"]["android"]
        self.assertEqual(decoded["files"][face_authoring["original"]["member"]], face_raw)
        face_recipe = json.loads(decoded["files"][face_authoring["recipe"]["member"]])
        self.assertEqual(face_recipe["state"]["textures"][0]["sourceSha256"], fmt.sha(face_raw))
        reference = decoded["manifest"]["dependencies"]["android"]["facedynamic"]
        self.assert_image(decoded["files"][reference["member"]], expected, levels)
        self.assert_image(self.fixture.golden(decoded, "android", "primary"), body_expected,
                          self.images["android", "primary"])
        reopened, _, restored = self.fixture.prepare(result["mod_package"]["package_path"])
        self.assertEqual(len(restored["textures"]), 2)
        reopened_operation = next(row for row in restored["textures"] if row["sourceSha256"] == fmt.sha(face_raw))
        self.assertEqual(reopened_operation["sourceSha256"], fmt.sha(face_raw))
        self.assertEqual(reopened_operation["png"], operation["png"])
        source_record = edits._session(reopened)["sources"][reopened_operation["texture"]["source"]]
        self.assertEqual(source_record["sha256"], fmt.sha(face_raw))
        repeated = self.package_face(reopened, restored, include_face_edits=True)
        repeated_decoded = fmt.read_package(repeated["mod_package"]["package_path"])
        repeated_face = repeated_decoded["manifest"]["dependencies"]["android"]["facedynamic"]
        self.assert_image(repeated_decoded["files"][repeated_face["member"]], expected, levels)
        self.assert_image(self.fixture.golden(repeated_decoded, "android", "primary"), body_expected,
                          self.images["android", "primary"])
        again, _, repeated_state = self.fixture.prepare(repeated["mod_package"]["package_path"])
        repeated_operation = next(row for row in repeated_state["textures"] if row["sourceSha256"] == fmt.sha(face_raw))
        self.assertEqual(repeated_operation["png"], operation["png"])
        self.assertEqual(edits._session(again)["sources"][repeated_operation["texture"]["source"]]["sha256"], fmt.sha(face_raw))
        self.assertEqual(source.read_bytes(), source_original)
        self.assertEqual(face_path.read_bytes(), face_raw)

        missing_capability = copy.deepcopy(decoded["manifest"])
        missing_capability["requires"].remove("rina-face-authoring-v1")
        with self.assertRaises(ValueError):
            fmt.read_package(fmt.encode_package(missing_capability, decoded["files"]))
        changed_original = copy.deepcopy(decoded["manifest"])
        changed_files = dict(decoded["files"])
        original_member = face_authoring["original"]["member"]
        changed_files[original_member] = self.raws["android", "unmasked"]
        changed_original["face_authoring"]["android"]["original"] = fmt.reference(
            original_member, changed_files[original_member], "android")
        with self.assertRaises(ValueError):
            corrupt = self.root / "substituted-face-original.zip"
            corrupt.write_bytes(fmt.encode_package(changed_original, changed_files))
            self.fixture.prepare(corrupt)

    def test_automatic_face_pixels_are_not_included_by_default_or_explicit_false(self):
        primary, counterpart = self.root / "board.unity", self.root / "bare.unity"
        primary.write_bytes(self.raws["android", "primary"])
        counterpart.write_bytes(self.raws["android", "unmasked"])
        face_raw, levels = self.make_face()
        face_path = self.root / "verified-original-face.unity"
        face_path.write_bytes(face_raw)
        prepared = model_viewer.prepare([str(primary)], rigged=True,
            face_context={"enabled": False, "allow_download": False})
        token = prepared["id"]
        edits.register_session(token, [str(primary)], prepared["rig"],
            companions=[{"path": str(face_path), "sha256": fmt.sha(face_raw), "sourceIndex": 1}])
        row = next(row for row in textures.inspect(token)["textures"] if row["sourceSha256"] == fmt.sha(face_raw))
        image = levels[0].copy()
        image.putpixel((3, 1), (213, 27, 199, image.getpixel((3, 1))[3]))
        operation = {"texture": row["texture"], "sourceSha256": fmt.sha(face_raw), "png": uri(image), "kind": "skin"}
        for options in ({}, {"include_face_edits": False}):
            with self.subTest(options=options):
                result = self.package_face(token, self.state(operation), counterpart_path=str(counterpart),
                    selected_variant="primary", **options)
                decoded = fmt.read_package(result["mod_package"]["package_path"])
                self.assertIsNone(decoded["manifest"]["dependencies"]["android"]["facedynamic"])
                for graph in decoded["manifest"].get("execution_model_graph", {}).values():
                    self.assertFalse(any("face" in node.get("model_dependencies", [])
                                         for node in graph["nodes"].values()))
                # Source-bound authoring metadata is inert and may retain an
                # excluded edit so reopening never discards the user's work.
                face_authoring = decoded["manifest"].get("face_authoring", {}).get("android")
                if face_authoring:
                    self.assertEqual(decoded["files"][face_authoring["original"]["member"]], face_raw)
                for variant in fmt.VARIANTS:
                    recipe, _ = self.recipe(decoded, "android", variant)
                    self.assertFalse(recipe["state"].get("textures"))
        self.assertEqual(face_path.read_bytes(), face_raw)


if __name__ == "__main__":
    unittest.main()
