"""Motion identities follow master-data relationships, not supplied paths."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from webtools.core import game_motions as motion
from webtools.jobs import Job

try:
    import llas_asset_extractor as extractor
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
        record = self.select("voice", "voice:100")
        paths = self.run_import(record).output_paths()
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(Path(path).read_bytes() == self.payload for path in paths))
        self.assertEqual(self.run_import(record).output_paths(), paths)
        for path, digest in self.originals.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_changed_cache_is_preserved_and_not_reused(self):
        original = Path(self.run_import().output_paths()[0])
        original.write_bytes(b"user edited")
        second = Path(self.run_import().output_paths()[0])
        self.assertNotEqual(original, second)
        self.assertEqual(original.read_bytes(), b"user edited")
        self.assertEqual(second.read_bytes(), self.payload)

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
            self.assertEqual(Path(self.run_import(self.select(download=True)).output_paths()[0]).read_bytes(), self.payload)
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

    def test_missing_or_too_many_dependencies_are_reported(self):
        with sqlite3.connect(self.assets) as db:
            for i in range(7):
                db.execute("INSERT INTO navi_motion VALUES(?,?,0,?,7,11)", (f"extra{i}", "pack0", len(self.payload)))
                db.execute("INSERT INTO navi_timeline_dependency VALUES('special-timeline',?)", (f"extra{i}",))
        with self.assertRaisesRegex(ValueError, "limit"):
            self.select("special", "auto:2")


if __name__ == "__main__":
    unittest.main()
