"""Accessory-only recipes preserve the existing source/variant contracts."""
from pathlib import Path
import secrets
import struct
import tempfile
import unittest
import zipfile
import numpy as np
import UnityPy
import copy
import hashlib

from webtools.core import model_edits as edits, model_viewer
from webtools.core import viewer_mod_pair_edits as paired
import test_viewer_mod_pair_edits as pair_fixtures
import test_viewer_scene_roles as scene_fixtures
import test_model_accessory_unclip as geometry_fixtures


class AccessoryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = Path(__file__).parent / "fixtures/viewer_persistence.unity"
        cls.raw = cls.fixture.read_bytes()
        cls.rig = model_viewer.prepare([str(cls.fixture.resolve())], rigged=True,
            face_context={"enabled": False, "allow_download": False})["rig"]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "original.unity"; self.path.write_bytes(self.raw)
        with edits._LOCK:
            edits._SESSIONS.clear()
        self.token = secrets.token_hex(16)
        self.metadata = edits.register_session(self.token, [str(self.path)], self.rig)

    def state(self, **extra):
        return {"version": 1, "savedSettingsEnabled": True, "edits": [], "accessoryUnclip": {}, **extra}

    def test_optional_settings_are_strict_and_old_state_normalization_is_unchanged(self):
        expected = {"strength": 1., "overlap": .15, "closeGaps": False}
        self.assertEqual(edits.validate_state(self.token, self.state())["accessoryUnclip"], expected)
        bad = [None, [], True, {"enabled": True}, {"strength": True}, {"strength": -1},
               {"strength": 3.001}, {"strength": float("inf")}, {"strength": 10**400},
               {"overlap": float("nan")}, {"overlap": 1.01}, {"closeGaps": 1}, {"closeGaps": "false"}]
        for value in bad:
            with self.subTest(value=str(value)[:80]), self.assertRaises(edits.ModelEditError):
                edits.validate_state(self.token, self.state(accessoryUnclip=value))
        node = next(row for row in self.metadata["nodes"] if row["name"] == "BreastSize")
        old = {"version": 1, "edits": [{"node": node["node"], "method": "node", "scale": [1, 1, 1]}]}
        normalized = edits.validate_state(self.token, old)
        self.assertEqual(set(normalized), {"version", "edits", "savedSettingsEnabled", "unsupported", "compensationReference"})
        self.assertNotIn("accessoryUnclip", normalized)
        with self.assertRaises(edits.ModelEditError):
            edits.validate_state(self.token, {"version": 1, "edits": []})
        self.assertEqual(edits.accessory_preview(self.token, {"version": 1, "edits": []}),
                         {"corrections": [], "summary": {"status": "disabled", "changed": 0}})

    def test_accessory_only_zero_result_preserves_bytes_recipe_and_repeat_export(self):
        state = self.state()
        first = edits.export(self.token, state, self.root / "exports")
        second = edits.export(self.token, state, self.root / "exports")
        self.assertEqual(Path(first["preview_paths"][0]).read_bytes(), self.raw)
        self.assertEqual(Path(second["preview_paths"][0]).read_bytes(), self.raw)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(Path(first["original_paths"][0]).read_bytes(), self.raw)
        self.assertEqual(edits.restore(self.token, first["recipe"]), edits.validate_state(self.token, state))

    def test_preview_and_export_share_process_slot_without_leaking_session_lock(self):
        self.assertTrue(edits._EXPORT_SLOT.acquire(blocking=False))
        try:
            with self.assertRaisesRegex(edits.ModelEditError, "Another model"):
                edits.accessory_preview(self.token, self.state())
        finally:
            edits._EXPORT_SLOT.release()
        session = edits._session(self.token)
        self.assertTrue(session["busy"].acquire(blocking=False))
        session["busy"].release()
        preview = edits.accessory_preview(self.token, self.state())
        self.assertEqual(preview["corrections"], [])
        self.assertEqual(preview["summary"]["changed"], 0)

    def test_accessory_only_export_keeps_original_changed_source_guard(self):
        self.path.write_bytes(self.raw + b"source changed")
        with self.assertRaisesRegex(edits.ModelEditError, "changed after opening"):
            edits.export(self.token, self.state(), self.root / "exports")
        self.assertFalse((self.root / "exports").exists())

    def test_unsupported_skin_and_ambiguous_or_external_bindings_fail_closed(self):
        missing = UnityPy.load(geometry_fixtures.make_fixture())
        missing.file.objects = {obj.path_id: obj for obj in missing.objects if obj.type.name != "SkinnedMeshRenderer"}
        cases = [(missing.file.save(), "skinning cannot"),
                 (geometry_fixtures.make_fixture(ambiguous_renderers=True), "ambiguous"),
                 (geometry_fixtures.make_fixture(external_weighted_bone=True), "external")]
        for raw, message in cases:
            with self.subTest(reason=message), self.assertRaisesRegex(edits.ModelEditError, message):
                edits._edit_source(raw, [], {}, [], accessory_unclip={})

    def pair_helper(self):
        helper = pair_fixtures.PairedBodyEditTests()
        helper.raw = self.raw
        helper.setUp(); self.addCleanup(helper.doCleanups)
        return helper

    def test_accessory_only_option_reaches_all_four_original_platform_variant_recipes(self):
        helper = self.pair_helper()
        path, original = helper.paired_zip(four=True)
        context, result, state, _ = helper.save(path, lambda nodes: helper.state(accessoryUnclip={}), archive=True)
        output = paired.apply_pair_edits(context, result, state, pair=None, job=helper.job)
        self.assertEqual(len(output["summary"]), 3)
        self.assertEqual(len(output["result"]["paired_recipe_paths"]), 4)
        import json
        for recipe in output["result"]["paired_recipe_paths"][:-1]:
            self.assertIn("accessoryUnclip", json.loads(Path(recipe).read_text())["state"])
        with zipfile.ZipFile(output["result"]["preview_paths"][0]) as saved:
            for member, raw in original.items():
                self.assertEqual(saved.read(member), raw)

    def test_scene_recipe_reopen_retains_accessory_only_setting_without_new_body_edits(self):
        helper = scene_fixtures.SceneRolesTests()
        helper.setUp(); self.addCleanup(helper.doCleanups)
        path = helper.source()
        token, nodes, _ = helper.prepare(path)
        first, _ = helper.package(token, helper.state(nodes))
        token, _, _ = helper.prepare(Path(first["mod_package"]["package_path"]))
        second, manifest = helper.package(token, self.state())
        token, _, restored = helper.prepare(Path(second["mod_package"]["package_path"]))
        self.assertEqual(restored["edits"], [])
        self.assertEqual(restored["accessoryUnclip"], {"strength": 1., "overlap": .15, "closeGaps": False})

    def accessory_variant(self, platform, variant):
        ios = platform == "ios"
        bare = variant == "unmasked"
        raw = geometry_fixtures.make_fixture(source_scale=(1.25, 1.1, 1.4) if bare else (1.5, 1.5, 1.5),
                                             authored_scale=(1.1, 1., 1.) if ios else (1., 1., 1.),
                                             rotated_parent=ios)
        env = UnityPy.load(raw)
        env.file.target_platform = 9 if ios else 13
        env.file._m_target_platform = 9 if ios else 13
        offset = (2000 if ios else 0) + (1000 if bare else 0)
        def remap(value):
            if isinstance(value, dict):
                if value.get("m_FileID") == 0 and value.get("m_PathID", 0) > 0:
                    value["m_PathID"] += offset
                for child in value.values(): remap(child)
            elif isinstance(value, list):
                for child in value: remap(child)
        objects = list(env.objects)
        for obj in objects:
            tree = obj.read_typetree()
            if obj.type.name == "Texture2D":
                tree["m_Name"] = "ch0209_co0123_body" if bare else "ch9999_co0123_body"
            remap(tree)
            obj.save_typetree(tree)
            obj.path_id += offset
        env.file.objects = {obj.path_id: obj for obj in objects}
        # Scene execution uses real UnityFS/CAB metadata, as production bundles
        # do; the geometry oracle fixture itself is a plain SerializedFile.
        template = UnityPy.load(scene_fixtures.bundle_fixture(9 if ios else 13, variant))
        original = next(obj for obj in template.objects if obj.type.name == "AssetBundle")
        serialized = copy.copy(original.serialized_type)
        serialized.node = scene_fixtures._copy_typetree(serialized.node)
        env.file.types.append(serialized)
        metadata = copy.copy(original)
        metadata.assets_file = env.file
        metadata.serialized_type = serialized
        metadata.type_id = len(env.file.types) - 1
        metadata.path_id = max(env.file.objects) + 1
        owner = next(obj.path_id for obj in objects if obj.type.name == "GameObject" and obj.read_typetree()["m_Name"] == "Move")
        pointer = {"m_FileID": 0, "m_PathID": owner}
        tree = original.read_typetree()
        tree["m_PreloadTable"] = [pointer]
        tree["m_Container"] = [("assets/fixtures/character.prefab", {"preloadIndex": 0, "preloadSize": 1, "asset": pointer})]
        metadata.save_typetree(tree)
        env.file.objects[metadata.path_id] = metadata
        cab = "CAB-" + hashlib.sha256((platform + variant).encode()).hexdigest()[:32]
        entries = [(cab, env.file.save()), (cab + ".resS", b"unchanged accessory fixture stream")]
        payload = b"".join(raw for _, raw in entries)
        info = bytes(16) + struct.pack(">iIIHi", 1, len(payload), len(payload), 0, len(entries))
        offset = 0
        for name, raw in entries:
            info += struct.pack(">qqI", offset, len(raw), 0) + name.encode() + b"\0"
            offset += len(raw)
        prefix = b"UnityFS\0" + struct.pack(">I", 6) + b"5.x.x\0" + env.file.unity_version.encode() + b"\0"
        return prefix + struct.pack(">QIII", len(prefix) + 20 + len(info) + len(payload), len(info), len(info), 64) + info + payload

    @staticmethod
    def anchor_position(raw):
        info = edits._inspect(raw)
        keys = [key for key, name in info["names"].items() if name == "PartsA_Offset"]
        assert len(keys) == 1
        return np.asarray(info["authored"][keys[0]]["position"])

    def standalone(self, helper, raw, name):
        path = helper.write(name, raw)
        token, _ = helper.register(path)
        saved = edits.export(token, self.state(), helper.root / "standalone")
        return Path(saved["preview_paths"][0]).read_bytes()

    def test_real_accessory_only_four_variants_equal_their_independent_native_exports(self):
        helper = self.pair_helper()
        values = {platform + "_" + variant: self.accessory_variant(platform, variant)
                  for platform in ("android", "ios") for variant in ("primary", "unmasked")}
        values["modinstall.txt"] = ("chara_id=209\ncostume_file='android_primary'\n"
            "rina_unmask_costume_file='android_unmasked'\ncostume_file_ios='ios_primary'\n"
            "rina_unmask_costume_file_ios='ios_unmasked'\n").encode()
        path = helper.root / "accessory-four.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, raw in values.items(): archive.writestr(name, raw)
        context, result, state, _ = helper.save(path, lambda nodes: self.state(), archive=True)
        exported = paired.apply_pair_edits(context, result, state, pair=None, job=helper.job)
        self.assertEqual(len(exported["summary"]), 3)
        with zipfile.ZipFile(exported["result"]["preview_paths"][0]) as archive:
            completed = {name: archive.read(name) for name in values if name != "modinstall.txt"}
        for name, saved in completed.items():
            expected = self.standalone(helper, values[name], name + ".unity")
            self.assertEqual(saved, expected, name)
            self.assertFalse(np.allclose(self.anchor_position(saved), self.anchor_position(values[name])), name)

    def test_rina_navi_derivation_and_reopen_do_not_apply_accessory_lift_twice(self):
        helper = scene_fixtures.SceneRolesTests()
        helper.setUp(); self.addCleanup(helper.doCleanups)
        values = {(platform, variant): self.accessory_variant(platform, variant)
                  for platform in ("android", "ios") for variant in ("primary", "unmasked")}
        path = helper.source(("android", "ios"), data=values)
        token, _, _ = helper.prepare(path)
        first, manifest = helper.package(token, self.state())
        def anchors(decoded):
            document, files = decoded["manifest"], decoded["files"]
            output = {}
            for platform in ("android", "ios"):
                golden = files[document["canonical_goldens"][platform]["mv_board"]["member"]]
                shared = files[document["platforms"][platform]["navi_board"]["member"]]
                self.assertTrue(np.allclose(self.anchor_position(golden), self.anchor_position(shared)))
                self.assertFalse(np.allclose(self.anchor_position(golden), self.anchor_position(values[platform, "primary"])))
                output[platform] = golden
            return output
        original = anchors(manifest)
        token, _, restored = helper.prepare(Path(first["mod_package"]["package_path"]))
        self.assertEqual(restored["edits"], [])
        self.assertIn("accessoryUnclip", restored)
        second, document = helper.package(token, restored)
        repeated = anchors(document)
        self.assertEqual(original, repeated)


if __name__ == "__main__":
    unittest.main()
