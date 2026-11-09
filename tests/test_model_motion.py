"""Original neutral Unity fixtures and fake DBs exercise preview provenance."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from webtools.core import model_motion as motion
from webtools.core import model_viewer as viewer

FIXTURE = Path(__file__).parent / "fixtures" / "viewer_rig.unity"
_IMPORT = __import__


def without_extractor(name, *args, **kwargs):
    if name == "llas_asset_extractor":
        raise AssertionError("Packaged preview must not need the extractor")
    return _IMPORT(name, *args, **kwargs)


class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import UnityPy
            import llas_asset_extractor
        except ImportError as error:
            raise unittest.SkipTest("UnityPy and the SIFAS extractor are required") from error
        cls.UnityPy, cls.extractor = UnityPy, llas_asset_extractor

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        env = self.UnityPy.load(FIXTURE.read_bytes())
        for obj in list(env.objects):
            if obj.type.name != "AnimationClip":
                del obj.assets_file.objects[obj.path_id]
        self.plain = next(iter(env.files.values())).save()
        self.digest = hashlib.sha256(self.plain).hexdigest()
        self.recipe = {"size": len(self.plain), "assetName": None,
                       "clipName": "Neutral swing", "channels": 1}
        self.addCleanup(patch.stopall)
        patch.object(motion, "KNOWN_PREVIEWS", {self.digest: self.recipe}).start()
        self.context = {"enabled": False, "allow_download": False,
                        "repo_root": str(self.root), "cache_dir": str(self.cache)}
        self.deadline = time.monotonic() + 120
        self.raw = self.pack("neutralpack", 191, -271)
        self.database("jp", "asset_a_ja.db", "neutralpack", 191, -271)

    def tearDown(self):
        viewer._SESSIONS.clear()

    def pack(self, name, key1, key2, data=None, parent=None):
        encrypted = bytearray(self.plain if data is None else data)
        self.extractor.decrypt_section(encrypted, self.extractor.FIXED_KEY0, key1, key2)
        path = (parent or self.root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encrypted)
        return path

    def database(self, region, filename, name, key1, key2, *, head=0, size=None, pack_size=None):
        root = self.root / "assets" / "db" / region
        root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(root / "masterdata.db") as db:
            db.execute("CREATE TABLE IF NOT EXISTS m_ui_navi_motion(motion_key,animation_clip_path)")
            db.execute("INSERT INTO m_ui_navi_motion VALUES(1,'preview')")
        with sqlite3.connect(root / filename) as db:
            db.execute("CREATE TABLE navi_motion(asset_path,pack_name,head,size,key1,key2)")
            db.execute("CREATE TABLE m_asset_package_mapping(pack_name,file_size)")
            db.execute("INSERT INTO navi_motion VALUES(?,?,?,?,?,?)", ("preview", name, head, len(self.plain) if size is None else size, key1, key2))
            db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?)", (name, len(self.plain) if pack_size is None else pack_size))

    def prepare(self, paths):
        return viewer.prepare([str(path) for path in paths], face_context=self.context, rigged=True)

    def test_incompatible_early_bundle_does_not_suppress_later_automatic_lookup(self):
        stage = motion.MotionInputs([], self.context, self.deadline)
        self.addCleanup(stage.close)
        rejected = {"path": "unbound-preview.unity"}

        def unbound(rig, deadline):
            stage.verified.append(rejected)
            return []

        with patch.object(stage, "_bundled", side_effect=unbound):
            self.assertEqual(stage.bundled(object(), [], self.deadline), [])
        self.assertEqual(stage.verified, [])
        with patch.object(stage, "_bundled", return_value=["later-preview.unity"]) as lookup:
            self.assertEqual(stage.automatic(object(), [], self.deadline), ["later-preview.unity"])
        lookup.assert_called_once()

    def test_early_bundle_registration_rolls_back_on_exception_and_keeps_selected(self):
        stage = motion.MotionInputs([], self.context, self.deadline)
        self.addCleanup(stage.close)

        def broken(rig, deadline):
            stage.verified.append({"path": "half-loaded.unity"})
            raise RuntimeError("optional import")

        with patch.object(stage, "_bundled", side_effect=broken):
            with self.assertRaisesRegex(RuntimeError, "optional import"):
                stage.bundled(object(), [], self.deadline)
        self.assertEqual(stage.verified, [])
        selected = {"path": "explicit-preview.unity"}
        stage.verified.append(selected)
        with patch.object(stage, "_bundled") as lookup:
            self.assertEqual(stage.bundled(object(), [], self.deadline), [])
            self.assertEqual(stage.automatic(object(), [], self.deadline), [])
        lookup.assert_not_called()
        self.assertEqual(stage.verified, [selected])

    def test_raw_selected_stages_read_only_and_cleans_on_success(self):
        before = self.raw.read_bytes()
        with motion.prepare_motion_inputs([str(self.raw)], self.context, self.deadline) as staged:
            output = Path(staged.paths[0])
            self.assertEqual(output.read_bytes(), self.plain)
            self.assertEqual(staged.origins[str(output)], str(self.raw))
            self.assertEqual(staged.verified[0]["sourceName"], "neutralpack")
        self.assertFalse(output.exists())
        self.assertEqual(self.raw.read_bytes(), before)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_failure_after_staging_cleans_all_temporary_files(self):
        with self.assertRaisesRegex(RuntimeError, "conversion"):
            with motion.prepare_motion_inputs([str(self.raw)], self.context, self.deadline) as staged:
                output = Path(staged.paths[0])
                raise RuntimeError("conversion")
        self.assertFalse(output.exists())
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_all_installed_regions_platforms_are_searched(self):
        self.database("gl", "asset_a_en.db", "wrongplatform", 20, 30)
        with motion.prepare_motion_inputs([str(self.raw)], self.context, self.deadline) as staged:
            self.assertEqual(staged.verified[0]["sourceHash"], self.digest)
            self.assertEqual(len(staged.descriptors()), 2)

    def test_plain_exact_identity_is_verified_but_same_clip_name_is_not(self):
        plain = self.root / "plain.unity"
        plain.write_bytes(self.plain)
        with motion.prepare_motion_inputs([str(plain), str(FIXTURE)], self.context, self.deadline) as staged:
            self.assertEqual([item["sourceId"] for item in staged.verified], [motion.source_id(plain)])

    def test_explicit_duplicate_clip_name_promotes_verified_source_only(self):
        metadata = self.prepare([FIXTURE, self.raw])
        self.assertEqual([clip["name"] for clip in metadata["rig"]["clips"]], ["Neutral swing", "Neutral swing__2"])
        self.assertEqual(metadata["rig"]["previewMotion"]["name"], "Neutral swing__2")
        self.assertEqual(metadata["source_names"], [FIXTURE.name, "neutralpack"])
        self.assertEqual(metadata["faces"]["status"], "not_needed")
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_changed_loaded_bytes_cannot_promote_previously_verified_source(self):
        stage = motion.MotionInputs([str(self.raw)], self.context, self.deadline)
        self.addCleanup(stage.close)
        stage.selected()
        record = stage.verified[0]
        clip = {"sourceId": record["sourceId"], "sourceHash": "0" * 64,
                "sourceName": "Neutral swing", "name": "Neutral swing",
                "bindingComplete": True, "channels": 1, "sourceTracks": 1}
        metadata = {"clips": [clip]}
        stage.promote(metadata)
        self.assertNotIn("previewMotion", metadata)

    def test_unknown_raw_input_is_actionable_and_never_creates_temp_files(self):
        unknown = self.root / "unknown"
        unknown.write_bytes(self.raw.read_bytes())
        with self.assertRaisesRegex(ValueError, "recognized original"):
            with motion.prepare_motion_inputs([str(unknown)], self.context, self.deadline):
                pass
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_wrong_keys_and_truncated_pack_do_not_publish(self):
        self.raw.write_bytes(self.raw.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, "could not be decrypted"):
            with motion.prepare_motion_inputs([str(self.raw)], self.context, self.deadline):
                pass
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_symlinked_private_cache_is_rejected_without_writes(self):
        outside = self.root / "originals"
        outside.mkdir()
        linked = self.root / "linked-cache"
        linked.symlink_to(outside, target_is_directory=True)
        context = dict(self.context, cache_dir=str(linked))
        with self.assertRaises(ValueError):
            with motion.prepare_motion_inputs([str(self.raw)], context, self.deadline):
                pass
        self.assertEqual(list(outside.iterdir()), [])

    def test_bad_descriptor_paths_offsets_and_size_are_rejected(self):
        stage = motion.MotionInputs([], self.context, self.deadline)
        for update in ({"pack_name": "../escape"}, {"head": -1}, {"size": motion.MAX_BYTES + 1}, {"pack_size": 1}):
            row = {"pack_name": "neutralpack", "head": 0, "size": len(self.plain),
                   "pack_size": len(self.plain), "key1": 191, "key2": -271}
            row.update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                stage._decrypt(str(self.raw), row, self.deadline)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_automatic_cache_uses_complete_bound_preview_even_with_existing_clip(self):
        # Original game layout files/pkg<first>/<pack> beneath trusted root.
        layout = self.root / "game" / "files" / "pkgn"
        self.pack("neutralpack", 191, -271, parent=layout)
        self.raw.unlink()
        self.context["library_roots"] = [str(self.root / "game")]
        metadata = self.prepare([FIXTURE])
        self.assertEqual(len(metadata["rig"]["clips"]), 2)
        self.assertEqual(metadata["rig"]["previewMotion"]["name"], "Neutral swing__2")

    def test_automatic_cache_requires_every_track_to_bind_uniquely(self):
        # Same known bytes, but a rig missing the target must not receive even a
        # partially bound default preview. Generic embedded source clip survives.
        from webtools.core.model_rig import RigBuilder
        original = RigBuilder.__init__
        def missing_binding(rig, *args, **kwargs):
            original(rig, *args, **kwargs)
            rig.node_bindings = {}
        with patch.object(RigBuilder, "__init__", missing_binding):
            metadata = self.prepare([FIXTURE])
        self.assertNotIn("previewMotion", metadata["rig"])

    def test_bundled_preview_needs_no_selected_motion_database_cache_or_extractor(self):
        bundled = self.root / "bundled.unity"
        bundled.write_bytes(self.plain)
        with patch.object(motion, "BUNDLED_PREVIEW", bundled), \
                patch.object(motion.MotionInputs, "descriptors", side_effect=AssertionError("DB must not be used")), \
                patch("builtins.__import__", side_effect=without_extractor):
            metadata = viewer.prepare([str(FIXTURE)], rigged=True)
        self.assertEqual(metadata["source_names"], [FIXTURE.name])
        self.assertEqual(metadata["rig"]["previewMotion"]["origin"], "bundled")
        self.assertEqual(metadata["rig"]["previewMotion"]["name"], "Neutral swing__2")
        self.assertEqual(metadata["rig"]["previewMotion"]["sourceName"], bundled.name)

    def test_eight_selected_inputs_leave_a_separate_offline_preview_slot(self):
        bundled = self.root / "bundled.unity"; bundled.write_bytes(self.plain)
        selected = [FIXTURE]
        for index in range(7):
            env = self.UnityPy.load(self.plain)
            obj = next(obj for obj in env.objects if obj.type.name == "AnimationClip")
            tree = obj.read_typetree(); tree["m_Name"] = "Selected custom motion " + str(index); obj.save_typetree(tree)
            path = self.root / ("motion-" + str(index) + ".unity"); path.write_bytes(env.file.save()); selected.append(path)
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in selected}
        with patch.object(motion, "BUNDLED_PREVIEW", bundled), patch.object(motion.MotionInputs, "descriptors", side_effect=AssertionError("The packaged preview is available offline")):
            metadata = self.prepare(selected)
        self.assertEqual(len(metadata["source_names"]), 8)
        self.assertTrue(metadata["rig"]["previewMotion"]["verified"])
        self.assertEqual(metadata["rig"]["previewMotion"]["origin"], "bundled")
        self.assertEqual(before, {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in selected})
        self.assertEqual(metadata["faces"]["status"], "not_needed")
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_zip_backed_package_resource_lifetime_and_loaded_provenance(self):
        archive_path = self.root / "package.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("sifas_suit_preview.unity", self.plain)
        materialized = []
        original = motion.MotionInputs._fully_bound
        def inspect(stage, path, rig, deadline):
            materialized.append(Path(path))
            self.assertEqual(Path(path).read_bytes(), self.plain)
            return original(stage, path, rig, deadline)
        with zipfile.ZipFile(archive_path) as archive, \
                patch.object(motion, "BUNDLED_PREVIEW", zipfile.Path(archive, "sifas_suit_preview.unity")), \
                patch.object(motion.MotionInputs, "_fully_bound", inspect):
            metadata = viewer.prepare([str(FIXTURE)], rigged=True)
        self.assertEqual(metadata["rig"]["previewMotion"]["origin"], "bundled")
        self.assertTrue(materialized)
        self.assertTrue(all(not path.exists() for path in materialized))
        selected = next(clip for clip in metadata["rig"]["clips"] if clip["name"] == metadata["rig"]["previewMotion"]["name"])
        self.assertEqual(selected["sourceHash"], self.digest)
        self.assertTrue(selected["bindingComplete"])

    def test_corrupt_bundled_preview_is_ignored_without_replacing_valid_body(self):
        bundled = self.root / "corrupt.unity"
        bundled.write_bytes(self.plain[:-1] + bytes([self.plain[-1] ^ 1]))
        with patch.object(motion, "BUNDLED_PREVIEW", bundled):
            metadata = viewer.prepare([str(FIXTURE)], rigged=True)
        self.assertNotIn("previewMotion", metadata["rig"])
        self.assertEqual(len(metadata["rig"]["clips"]), 1)
        self.assertEqual(metadata["stats"]["vertices"], 6)

    def test_bundled_preview_requires_complete_unique_bindings(self):
        from webtools.core.model_rig import RigBuilder
        bundled = self.root / "bundled.unity"
        bundled.write_bytes(self.plain)
        original = RigBuilder.__init__
        def ambiguous(rig, *args, **kwargs):
            original(rig, *args, **kwargs)
            rig.node_bindings["Move/BreastSize"] = [0, 1]
        with patch.object(motion, "BUNDLED_PREVIEW", bundled), patch.object(RigBuilder, "__init__", ambiguous):
            metadata = viewer.prepare([str(FIXTURE)], rigged=True)
        self.assertNotIn("previewMotion", metadata["rig"])

    def test_explicit_verified_motion_takes_priority_over_bundled_copy(self):
        bundled = self.root / "bundled.unity"
        bundled.write_bytes(self.plain)
        with patch.object(motion, "BUNDLED_PREVIEW", bundled):
            metadata = self.prepare([FIXTURE, self.raw])
        self.assertEqual(len(metadata["rig"]["clips"]), 2)
        self.assertEqual(metadata["rig"]["previewMotion"]["origin"], "selected")

    def test_hair_only_or_renamed_body_owner_excludes_motion_only_identity(self):
        environment = self.UnityPy.load(FIXTURE.read_bytes())
        renderer = next(obj for obj in environment.objects if obj.type.name == "SkinnedMeshRenderer")
        game_id = renderer.read_typetree()["m_GameObject"]["m_PathID"]
        for obj in environment.objects:
            if obj.type.name == "Material" or (obj.type.name == "GameObject" and obj.path_id == game_id):
                tree = obj.read_typetree()
                tree["m_Name"] = "ch0207_head" if obj.type.name == "Material" else "Hair"
                obj.save_typetree(tree)
        hair = self.root / "hair.unity"
        hair.write_bytes(next(iter(environment.files.values())).save())
        environment = self.UnityPy.load(FIXTURE.read_bytes())
        named = False
        for obj in list(environment.objects):
            if obj.type.name == "AnimationClip":
                continue
            if obj.type.name == "GameObject" and not named:
                tree = obj.read_typetree()
                tree["m_Name"] = "ch0301_shared_motion"
                obj.save_typetree(tree)
                named = True
            else:
                del obj.assets_file.objects[obj.path_id]
        companion = self.root / "shared-motion.unity"
        companion.write_bytes(next(iter(environment.files.values())).save())
        from webtools.core.model_faces import FacePlan
        from webtools.core.model_rig import RigBuilder
        scene = viewer._Scene(viewer._environment([str(hair), str(companion)], self.deadline), self.deadline)
        rig = RigBuilder(scene, viewer._Glb(), FacePlan(scene, [str(hair)], None, self.deadline), [str(hair)], self.deadline)
        self.assertEqual(rig.owner, 207)

    def test_static_legacy_does_not_implicitly_decrypt_raw_inputs(self):
        with self.assertRaises(viewer.ModelViewerError):
            viewer.prepare([str(self.raw)], face_context=self.context)


class ActualPreviewTests(unittest.TestCase):
    def test_clean_clothed_model_gets_packaged_preview_without_db_or_extra_inputs(self):
        costume = os.environ.get("SIFAS_FACE_TEST_COSTUME")
        if not costume:
            self.skipTest("Set actual clothed costume for automatic packaged preview")
        before = hashlib.sha256(Path(costume).read_bytes()).hexdigest()
        with patch.object(motion.MotionInputs, "descriptors", side_effect=AssertionError("No database allowed")), \
                patch("builtins.__import__", side_effect=without_extractor):
            metadata = viewer.prepare([costume], rigged=True)
        preview = metadata["rig"]["previewMotion"]
        self.assertEqual(preview["origin"], "bundled")
        self.assertEqual(preview["name"], "ch0301_GEN_preview1_L")
        self.assertEqual(metadata["source_names"], [Path(costume).name])
        clip = next(clip for clip in metadata["rig"]["clips"] if clip["name"] == preview["name"])
        self.assertTrue(clip["bindingComplete"])
        self.assertEqual(clip["channels"], 58)
        self.assertEqual(clip["sourceHash"], "96ada81d0b8f35573fa81e0a3830b018a1d46ff26fff778f3be0a0deed618ebe")
        self.assertEqual(hashlib.sha256(Path(costume).read_bytes()).hexdigest(), before)

    def test_clothed_costume_raw_preview_and_explicit_eye_clips(self):
        names = ("SIFAS_FACE_TEST_COSTUME", "SIFAS_FACE_TEST_BUNDLE", "SIFAS_FACE_TEST_EYE_TABLE", "SIFAS_PREVIEW_TEST_PACK")
        if not all(os.environ.get(name) for name in names):
            self.skipTest("Set actual clothed costume, face, eye table and preview pack variables")
        costume, face, eye, pack = [os.environ[name] for name in names]
        before = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in (costume, face, eye, pack)}
        with tempfile.TemporaryDirectory() as cache:
            metadata = viewer.prepare([costume, pack, eye], rigged=True, face_context={
                "enabled": True, "allow_download": False, "repo_root": str(Path(__file__).resolve().parents[2]),
                "library_roots": [str(Path(face).parent)], "cache_dir": cache})
        self.assertEqual(metadata["faces"], {"enabled": True, "status": "added", "added": 5, "characters": [207]})
        self.assertEqual(metadata["stats"]["vertices"], 10525)
        self.assertEqual(len(metadata["rig"]["clips"]), 21)
        self.assertEqual(metadata["rig"]["previewMotion"]["name"], "ch0301_GEN_preview1_L")
        selected = next(clip for clip in metadata["rig"]["clips"] if clip["name"] == metadata["rig"]["previewMotion"]["name"])
        self.assertTrue(selected["bindingComplete"])
        self.assertEqual(selected["channels"], 58)
        self.assertEqual(before, {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in before})


if __name__ == "__main__":
    unittest.main()
