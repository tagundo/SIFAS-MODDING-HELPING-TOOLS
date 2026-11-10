"""Motion identities follow master-data relationships, not supplied paths."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from webtools.core import game_motions as motion
from webtools.jobs import Job

try:
    import llas_asset_extractor as extractor
    import UnityPy
except ImportError:
    extractor = None


@unittest.skipUnless(extractor, "Elichika extractor is required")
class GameMotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.packs = self.root / "packs"
        self.packs.mkdir()
        self.output = self.root / "library/extracted/game-motions"
        directory = self.root / "assets/db/gl"
        directory.mkdir(parents=True)
        self.master = directory / "masterdata.db"
        self.assets = directory / "asset_a_en.db"
        self.payload = (Path(__file__).parent / "fixtures/viewer_rig.unity").read_bytes()
        encrypted = bytearray(self.payload)
        extractor.decrypt_section(encrypted, extractor.FIXED_KEY0, 7, 11)
        self.encrypted = encrypted
        with sqlite3.connect(self.master) as db:
            db.executescript("""
                CREATE TABLE m_navi_model(member_m_id,idle_animation_clip_path);
                CREATE TABLE m_navi_action(id,navi_action_timeline_id,navi_action_comment_id);
                CREATE TABLE m_navi_timeline(id,timeline_asset_path);
                CREATE TABLE m_navi_action_auto(id,navi_action_id,member_m_id,navi_action_scene,start_at,end_at,suit_m_id);
                CREATE TABLE m_navi_action_tap(id,navi_action_id,member_m_id,navi_action_scene,start_at,end_at,suit_m_id);
                CREATE TABLE m_navi_voice(id,member_m_id,name,display_order);
                CREATE TABLE m_navi_action_login(id,navi_action_id,member_m_id,login_bonus_type,login_bonus_day);
                CREATE TABLE m_navi_action_comment(navi_action_comment_id,order_no,comment);
                CREATE TABLE m_live(live_id,name,bgm_path,is_2d_live);
                CREATE TABLE m_live_difficulty(live_id,live_3d_asset_master_id);
                CREATE TABLE m_live_3d_asset(id,timeline);
                INSERT INTO m_navi_model VALUES(1,'idle');
                INSERT INTO m_navi_model VALUES(2,'idle2');
                INSERT INTO m_navi_action VALUES(10,100,1000);
                INSERT INTO m_navi_action VALUES(20,200,2000);
                INSERT INTO m_navi_timeline VALUES(100,'home-timeline');
                INSERT INTO m_navi_timeline VALUES(200,'special-timeline');
                INSERT INTO m_navi_action_auto VALUES(1,10,1,1,1,9999999999,NULL);
                INSERT INTO m_navi_action_auto VALUES(2,20,1,1,1687964400,1688050800,NULL);
                INSERT INTO m_navi_action_auto VALUES(3,10,1,2,1,9999999999,NULL);
                INSERT INTO m_navi_action_tap VALUES(4,10,1,1,1,9999999999,NULL);
                INSERT INTO m_navi_action_tap VALUES(5,20,2,1,1,9999999999,NULL);
                INSERT INTO m_navi_voice VALUES(100,1,'k.voice',1);
                INSERT INTO m_navi_action_login VALUES(6,20,1,4,NULL);
                INSERT INTO m_navi_action_comment VALUES(1000,1,'k.home');
                INSERT INTO m_navi_action_comment VALUES(2000,1,'Birthday greeting');
                INSERT INTO m_live VALUES(1,'Song','music_0001',0);
                INSERT INTO m_live_difficulty VALUES(1,1);
                INSERT INTO m_live_3d_asset VALUES(1,'mv-timeline');
            """)
        with sqlite3.connect(directory / "dictionary_en_k.db") as db:
            db.executescript("CREATE TABLE m_dictionary(id,message); INSERT INTO m_dictionary VALUES('home','Home greeting'); INSERT INTO m_dictionary VALUES('voice','Member voice');")
        with sqlite3.connect(self.assets) as db:
            for table in ("navi_motion", "navi_timeline", "live_timeline"):
                db.execute(f"CREATE TABLE {table}(asset_path,pack_name,head,size,key1,key2)")
            db.executescript("CREATE TABLE navi_timeline_dependency(asset_path,dependency); CREATE TABLE m_asset_package_mapping(pack_name,file_size,metapack_name,metapack_offset);")
            for index, asset in enumerate(("idle", "body", "eye", "special")):
                pack = f"pack{index}"
                db.execute("INSERT INTO navi_motion VALUES(?,?,0,?,7,11)", (asset, pack, len(encrypted)))
                db.execute("INSERT INTO m_asset_package_mapping VALUES(?,?,NULL,0)", (pack, len(encrypted)))
                (self.packs / pack).write_bytes(encrypted)
            db.executemany("INSERT INTO navi_timeline_dependency VALUES(?,?)", [("home-timeline", "body"), ("home-timeline", "eye"), ("special-timeline", "special")])
            db.execute("INSERT INTO live_timeline VALUES('mv-timeline','pack4',0,?,7,11)", (len(encrypted),))
            db.execute("INSERT INTO m_asset_package_mapping VALUES('pack4',?,NULL,0)", (len(encrypted),))
            (self.packs / "pack4").write_bytes(encrypted)
        self.originals = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in self.root.rglob("*") if path.is_file()}
        self.addCleanup(patch.stopall)
        patch.object(extractor, "detect_game_candidates", return_value=[]).start()
        patch.object(extractor, "build_pack_roots", return_value=[str(self.packs)]).start()
        patch.object(extractor, "indexed_pack_file", side_effect=lambda root, name: str(Path(root) / name) if (Path(root) / name).exists() else None).start()

    def select(self, category="home", value="idle:1", character="1", **extra):
        params = dict(region="gl", character=character, category=category, motion=value, download=False)
        params.update(extra)
        return motion.validate_selection(self.root, params)

    def run_import(self, record=None, job=None):
        job = job or Job("fake", "viewer_game_motion")
        motion.run_import(job, repo_root=self.root, output_root=self.output, record=record or self.select())
        return job

    def test_categories_use_actual_relations_and_date_windows(self):
        expected = {"home": {"idle:1", "auto:1"}, "tap": {"tap:4"}, "voice": {"voice:100"}, "mv": {"mv:1:1"}, "special": {"auto:2", "login:6"}}
        for category, keys in expected.items():
            result = motion.catalog(self.root, character="1", category=category)
            self.assertEqual({item["value"] for item in result["motions"]}, keys)
            self.assertTrue(all("asset" not in item and "table" not in item for item in result["motions"]))
        self.assertEqual(motion.catalog(self.root, character="1", search="greeting")["motions"][0]["label"], "Home greeting")
        self.assertEqual(motion.catalog(self.root, character="1", category="voice")["motions"][0]["label"], "Member voice")
        self.assertEqual(motion.catalog(self.root)["motions"], [])

    def test_companion_dependencies_and_mv_identity_are_exact(self):
        self.assertEqual([item["asset"] for item in self.select("voice", "voice:100")["resources"]], ["body", "eye"])
        self.assertEqual(self.select("mv", "mv:1:1", character="")["resources"][0]["table"], "live_timeline")
        self.assertEqual(self.select("special", "auto:2")["resources"][0]["asset"], "special")
        for args in [("home", "auto:2"), ("tap", "tap:5"), ("voice", "voice:100", "2"), ("mv", "mv:1:2")]:
            with self.assertRaises(ValueError):
                self.select(*args)

    def test_import_decrypts_all_clips_without_changing_sources_and_reuses_cache(self):
        record = self.select()
        paths = self.run_import(record).output_paths()
        self.assertEqual(len(paths), 1)
        self.assert_motion_only(paths[0])
        self.assertEqual(self.run_import(record).output_paths(), paths)
        for path, digest in self.originals.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_changed_cache_is_preserved_and_not_reused(self):
        original = Path(self.run_import().output_paths()[0])
        original.write_bytes(b"user edited")
        second = Path(self.run_import().output_paths()[0])
        self.assertNotEqual(original, second)
        self.assertEqual(original.read_bytes(), b"user edited")
        self.assert_motion_only(second)

    def test_original_style_action_retains_more_than_six_selected_bundles(self):
        from webtools.core import game_motion_selection as selection
        # Independent serialized files model an action's separate body/facial
        # sources. They contain real AnimationClips, not successful API stubs.
        selected = {"timeline": None, "selected": {}, "segments": []}
        for index in range(8):
            env = UnityPy.load(self.payload)
            clip = next(obj for obj in env.objects if obj.type.name == "AnimationClip")
            tree = clip.read_typetree()
            tree["m_Name"] = f"Selected action {index}"
            clip.save_typetree(tree)
            path = self.root / f"selected-source-{index}.unity"
            path.write_bytes(next(iter(env.files.values())).save())
            part = selection.animation_only(path, deadline=time.monotonic() + 10)
            selected["selected"].update(part["selected"])
            selected["segments"].extend(part["segments"])
        with patch.object(selection, "animation_only", return_value=selected):
            paths = self.run_import().output_paths()
        self.assertEqual(len(paths), 8)
        names = []
        for path in paths:
            objects = list(UnityPy.load(str(path)).objects)
            self.assertEqual([obj.type.name for obj in objects], ["AnimationClip"])
            names.extend(obj.peek_name() for obj in objects)
        self.assertEqual(names, [f"Selected action {index}" for index in range(8)])
        # The larger, verified action is also reusable without losing clips.
        self.assertEqual(self.run_import().output_paths(), paths)

    def test_same_size_source_pack_change_with_restored_mtime_is_not_reused(self):
        original = Path(self.run_import().output_paths()[0])
        source = self.packs / "pack0"
        before = source.stat()
        replacement = bytearray(self.payload.replace(b"Neutral swing", b"Changed swing"))
        self.assertEqual(len(replacement), len(self.encrypted))
        extractor.decrypt_section(replacement, extractor.FIXED_KEY0, 7, 11)
        source.write_bytes(replacement)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        changed = Path(self.run_import().output_paths()[0])
        self.assertNotEqual(original, changed)
        env = UnityPy.load(changed.read_bytes())
        self.assertEqual([obj.peek_name() for obj in env.objects], ["Changed swing"])
        self.assert_motion_only(original)

    def test_missing_pack_does_not_download_without_option_and_cleans_partial_output(self):
        (self.packs / "pack0").unlink()
        with patch.object(motion.game, "_remote_pack") as remote:
            with self.assertRaisesRegex(ValueError, "missing"):
                self.run_import()
            remote.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_downloaded_motion_uses_bounded_existing_decryptor(self):
        (self.packs / "pack0").unlink()
        with patch.object(motion.game, "_remote_pack", return_value=self.encrypted) as remote:
            self.assert_motion_only(self.run_import(self.select(download=True)).output_paths()[0])
            remote.assert_called_once()

    def test_cancelled_job_publishes_nothing(self):
        job = Job("cancel", "viewer_game_motion")
        job.cancel_event.set()
        self.run_import(job=job)
        self.assertEqual(job.output_paths(), [])
        self.assertFalse(self.output.exists())

    def test_invalid_requests_cannot_supply_file_paths_or_wrong_types(self):
        for params in [dict(path="/etc/passwd"), dict(category=[]), dict(motion="../../escape"), dict(download=1), dict(region="../../gl"), dict(character="1 OR 1=1")]:
            with self.assertRaises(ValueError):
                self.select(**params)
        with self.assertRaises(ValueError):
            motion.catalog(self.root, category=[])
        with self.assertRaises(ValueError):
            motion.catalog(self.root, search="a" * 121)

    def test_picker_reuses_choices_but_not_mutable_public_results_or_changed_dictionary(self):
        with patch.object(motion, "_choices", wraps=motion._choices) as queried:
            first = motion.catalog(self.root, character="1")
            first["motions"][0]["label"] = "caller changed its own result"
            again = motion.catalog(self.root, character="1", search="greeting")
            self.assertEqual(again["motions"][0]["label"], "Home greeting")
            self.assertEqual(queried.call_count, 1)
            dictionary = self.root / "assets/db/gl/dictionary_en_k.db"
            before = dictionary.stat()
            with sqlite3.connect(dictionary) as db:
                db.execute("UPDATE m_dictionary SET message='New greeting' WHERE id='home'")
            os.utime(dictionary, ns=(before.st_atime_ns, before.st_mtime_ns))
            changed = motion.catalog(self.root, character="1", search="greeting")
            self.assertEqual(changed["motions"][0]["label"], "New greeting")
            self.assertEqual(queried.call_count, 2, "Restoring mtime must not conceal committed dictionary changes")

    def test_picker_invalidates_when_master_changes_only_in_sqlite_wal(self):
        with sqlite3.connect(self.master) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            with patch.object(motion, "_choices", wraps=motion._choices) as queried:
                before = motion.catalog(self.root, character="1", search="greeting")
                self.assertEqual(before["motions"][0]["label"], "Home greeting")
                writer.execute("UPDATE m_navi_action_comment SET comment='WAL greeting' WHERE navi_action_comment_id=1000")
                writer.commit()
                after = motion.catalog(self.root, character="1", search="greeting")
                self.assertEqual(after["motions"][0]["label"], "WAL greeting")
                self.assertEqual(queried.call_count, 2)

    def test_failed_download_reports_exact_stage_pack_and_http_reason(self):
        from urllib.error import HTTPError
        (self.packs / "pack0").unlink()
        job = Job("failed-http", "motion")
        with patch.object(motion.game, "_remote_pack", side_effect=HTTPError("https://example.invalid/pack0", 404, "Not Found", {}, None)):
            with self.assertRaisesRegex(ValueError, "Downloading motion pack.*pack0.*404"):
                self.run_import(self.select(download=True), job)
        errors = [job.event_at(index, 0) for index in range(job.event_count) if job.event_at(index, 0).get("type") == "motion_error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["stage"], "Downloading motion pack")
        self.assertEqual(errors[0]["pack"], "pack0")
        self.assertEqual(errors[0]["httpStatus"], 404)
        self.assertIn("Not Found", errors[0]["reason"])
        self.assertEqual(job.output_paths(), [])

    def test_missing_or_too_many_dependencies_are_reported(self):
        with sqlite3.connect(self.assets) as db:
            for i in range(motion.MAX_RESOURCES + 1):
                db.execute("INSERT INTO navi_motion VALUES(?,?,0,?,7,11)", (f"extra{i}", "pack0", len(self.payload)))
                db.execute("INSERT INTO navi_timeline_dependency VALUES('special-timeline',?)", (f"extra{i}",))
        with self.assertRaisesRegex(ValueError, "limit"):
            self.select("special", "auto:2")

    def assert_motion_only(self, path):
        env = UnityPy.load(Path(path).read_bytes())
        objects = list(env.objects)
        self.assertEqual([obj.type.name for obj in objects], ["AnimationClip"])
        self.assertEqual(objects[0].peek_name(), "Neutral swing")

    def test_missing_action_timeline_is_not_replaced_by_unsynchronized_clips(self):
        with self.assertRaisesRegex(ValueError, "timeline is missing"):
            self.run_import(self.select("voice", "voice:100"))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_solo_and_mv_stage_only_assets_and_all_catalog_pages_are_accessible(self):
        with sqlite3.connect(self.master) as db:
            db.executescript("""
              ALTER TABLE m_live ADD COLUMN live_member_mapping_id;
              CREATE TABLE m_live_member_mapping(mapping_id,position,member_master_id,is_center);
              CREATE TABLE m_live_mv(live_id,live_3d_asset_master_id);
              UPDATE m_live SET live_member_mapping_id=1;
              INSERT INTO m_live_member_mapping VALUES(1,1,1,1);
              INSERT INTO m_live_member_mapping VALUES(1,3,2,0);
              INSERT INTO m_live_member_mapping VALUES(2,1,1,1);
              INSERT INTO m_live VALUES(2,'Solo song','music_0002',0,2);
              INSERT INTO m_live_3d_asset VALUES(2,'mv-solo-timeline');
              INSERT INTO m_live_mv VALUES(2,2);
            """)
            for live in range(3, 452):
                db.execute("INSERT INTO m_live VALUES(?,?,?,0,1)", (live, f"Group {live}", f"music_{live}"))
                db.execute("INSERT INTO m_live_difficulty VALUES(?,1)", (live,))
        solo = motion.catalog(self.root, category="mv", song_type="solo")
        self.assertEqual([entry["value"] for entry in solo["motions"]], ["mv:2:2"])
        self.assertEqual(solo["motions"][0]["performers"][0]["member_id"], 1)
        pages = [motion.catalog(self.root, category="mv", offset=str(offset)) for offset in (0, 200, 400)]
        keys = [entry["value"] for page in pages for entry in page["motions"]]
        self.assertEqual(len(keys), 451)
        self.assertEqual(len(set(keys)), 451)
        self.assertFalse(pages[-1]["more"])
        self.assertEqual(pages[-1]["total"], 451)
        self.assertEqual(self.select("mv", "mv:1:1", performer="3")["performer_position"], 3)
        with self.assertRaisesRegex(ValueError, "performer"):
            self.select("mv", "mv:1:1", performer="2")


if __name__ == "__main__":
    unittest.main()
