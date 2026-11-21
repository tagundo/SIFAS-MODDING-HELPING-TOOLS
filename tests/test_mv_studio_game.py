"""Game MV catalog joins and bounded local section reads."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from webtools.core import mv_studio_game as studio

try:
    import llas_asset_extractor as extractor
except ImportError:
    extractor = None


@unittest.skipUnless(extractor, "The shared Elichika pack reader is required")
class MVGameCatalogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        database = self.root / "assets/db/gl"
        self.static = self.root / "static"
        self.static.mkdir()
        database.mkdir(parents=True)
        self.plain = (Path(__file__).parent / "fixtures/viewer_rig.unity").read_bytes()
        self.encrypted = bytearray(self.plain)
        extractor.decrypt_section(self.encrypted, extractor.FIXED_KEY0, 7, 11)
        with closing(sqlite3.connect(database / "masterdata.db")) as db, db:
            db.executescript("""
                CREATE TABLE m_live (live_id INTEGER PRIMARY KEY, name TEXT, music_id INTEGER, bgm_path TEXT,
                    chorus_bgm_path TEXT, live_member_mapping_id INTEGER, background_asset_path TEXT);
                CREATE TABLE m_live_3d_asset (id INTEGER PRIMARY KEY, timeline TEXT, live_stage_master_id INTEGER,
                    stage_effect_asset_path TEXT, live_prop_skeleton_asset_path TEXT, quality_setitng_set_id INTEGER,
                    shader_variant_asset_path TEXT);
                CREATE TABLE m_live_stage (id INTEGER PRIMARY KEY, stage_name TEXT, scene_name TEXT,
                    stage_model_asset_path TEXT, stage_thumbnail_asset_path TEXT, stage_background_asset_path TEXT);
                CREATE TABLE m_live_mv (live_id INTEGER, live_stage_master_id INTEGER, position INTEGER, live_3d_asset_master_id INTEGER);
                CREATE TABLE m_live_difficulty (live_id INTEGER, live_3d_asset_master_id INTEGER);
                CREATE TABLE m_live_member_mapping (mapping_id INTEGER, position INTEGER, member_master_id INTEGER,
                    is_center INTEGER, suit_master_id INTEGER);
                CREATE TABLE m_suit (id INTEGER, member_m_id INTEGER, name TEXT, model_asset_path TEXT);
                INSERT INTO m_live VALUES (12, 'k.song', 4, 'song', NULL, 9, NULL), (13, 'k.second', 5, NULL, NULL, 9, NULL);
                INSERT INTO m_live_3d_asset VALUES (31, 'timeline', 7, NULL, NULL, 3, NULL);
                INSERT INTO m_live_stage VALUES (7, 'k.stage', 'scene_stage', 'model', NULL, 'bg');
                INSERT INTO m_live_mv VALUES (12, 7, 1, 31);
                INSERT INTO m_live_difficulty VALUES (13, 31);
                INSERT INTO m_live_member_mapping VALUES (9, 1, 101, 1, 51);
                INSERT INTO m_suit VALUES (51, 101, 'k.costume', 'costume');
            """)
        with closing(sqlite3.connect(database / "dictionary_en_k.db")) as db, db:
            db.executescript("""
                CREATE TABLE m_dictionary (id TEXT, message TEXT);
                INSERT INTO m_dictionary VALUES ('song', 'Example song'), ('second', 'Gameplay song'),
                    ('stage', 'Stage &amp; lights'), ('costume', 'Default costume');
            """)
        for platform, name in (("a", "androidpack"), ("i", "iospack")):
            with closing(sqlite3.connect(database / f"asset_{platform}_en.db")) as db, db:
                for table in ("live_timeline", "stage", "texture", "member_model", "shader"):
                    db.execute(f"CREATE TABLE {table} (asset_path TEXT PRIMARY KEY, pack_name TEXT, head INTEGER, size INTEGER, key1 INTEGER, key2 INTEGER)")
                db.executescript("""
                    CREATE TABLE live_timeline_dependency (asset_path TEXT, dependency TEXT);
                    CREATE TABLE stage_dependency (asset_path TEXT, dependency TEXT);
                    CREATE TABLE m_asset_package_mapping (package_key TEXT, pack_name TEXT, file_size INTEGER, metapack_name TEXT, metapack_offset INTEGER);
                    CREATE TABLE m_asset_sound (sheet_name TEXT, acb_pack_name TEXT, awb_pack_name TEXT);
                    INSERT INTO live_timeline_dependency VALUES ('timeline', 'dance'), ('timeline', 'unavailable');
                    INSERT INTO stage_dependency VALUES ('model', 'stageShader');
                    INSERT INTO m_asset_sound VALUES ('song', 'acbpack', 'awbpack');
                    INSERT INTO m_asset_package_mapping VALUES ('music:12','acbpack',8,NULL,0), ('music:12','awbpack',8,NULL,0);
                """)
                for table, key in (("live_timeline", "timeline"), ("live_timeline", "dance"), ("stage", "model"),
                                   ("texture", "bg"), ("member_model", "costume"), ("shader", "stageShader")):
                    db.execute(f"INSERT INTO {table} VALUES (?,?,4,?,7,11)", (key, name, len(self.plain)))
                db.execute("INSERT INTO m_asset_package_mapping VALUES ('live:31',?,?,'metabucket',12)", (name, len(self.plain)+4))
        self.addCleanup(patch.stopall)
        patch.object(extractor, "detect_game_candidates", return_value=[]).start()
        patch.object(extractor, "build_pack_roots", return_value=[str(self.static)]).start()
        patch.object(extractor, "build_pack_index", side_effect=AssertionError("A selected MV does not cold-scan packs")).start()
        patch.object(extractor, "_load_disk_index", return_value=None).start()

    def selection(self, platform="android", live=12):
        return studio.resolve(self.root, region="gl", platform=platform, live_id=live, asset_id=31, language="en")

    def test_catalog_keeps_stage_difficulty_and_mv_only_links(self):
        rows = studio.catalog(self.root, region="gl", platform="android", language="en")["songs"]
        self.assertEqual([(row["id"], row["mvOnly"]) for row in rows], [(12, True), (13, False)])
        self.assertEqual(rows[0]["variants"][0]["label"], "Stage & lights")
        self.assertEqual(rows[1]["variants"][0]["source"], "difficulty")
        self.assertEqual(self.selection(live=13)["stage"]["sceneName"], "scene_stage")
        with self.assertRaisesRegex(ValueError, "no longer available"):
            self.selection(live=14)

    def test_resolves_same_platform_dependencies_costume_and_music(self):
        android, ios = self.selection(), self.selection("ios")
        self.assertEqual(android["timeline"]["pack_name"], "androidpack")
        self.assertEqual(ios["timeline"]["pack_name"], "iospack")
        self.assertEqual(ios["qualitySet"], 3)
        self.assertEqual([r["asset"] for r in ios["choreography"]], ["dance"])
        self.assertEqual([r["asset"] for r in ios["shaderDependencies"]], ["stageShader"])
        self.assertEqual(ios["performers"][0]["costumeName"], "Default costume")
        self.assertEqual(ios["audio"]["acb"]["pack_name"], "acbpack")
        self.assertEqual(ios["missing"][0]["asset"], "unavailable")

    def test_reads_exact_local_pack_or_metapack_without_implicit_download(self):
        descriptor = self.selection()["timeline"]
        with patch.object(studio.game, "_remote_pack", side_effect=AssertionError("No implicit network")):
            self.assertIsNone(studio.load_asset(self.root, descriptor))
            disk = self.static / "files/pkgm"
            disk.mkdir(parents=True)
            metapack = disk / "metabucket"
            original = b"m" * 12 + b"head" + self.encrypted + b"end"
            metapack.write_bytes(original)
            self.assertEqual(studio.load_asset(self.root, descriptor), self.plain)
            self.assertEqual(metapack.read_bytes(), original)
        with self.assertRaisesRegex(ValueError, "asset descriptor"):
            studio.load_asset(self.root, dict(descriptor, pack_name="../../arbitrary"))
