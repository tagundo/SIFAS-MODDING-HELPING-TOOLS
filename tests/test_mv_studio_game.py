"""Game MV catalog joins and bounded local section reads."""

from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from webtools.core import model_viewer, mv_studio
from webtools.core import mv_studio_game as studio

try:
    import llas_asset_extractor as extractor
except ImportError:
    extractor = None


class MVTimelineCastTests(unittest.TestCase):
    def test_matches_native_character_codes_to_runtime_member_ids(self):
        performers = [
            {"position": 1, "memberId": 212, "outfit": "Lanzhu"},
            {"position": 2, "memberId": 210, "outfit": "Shioriko"},
            {"position": 3, "memberId": 211, "outfit": "Mia"},
        ]
        tracks = [
            {"kind": "dance", "binding": f"/EntryPoint/Live/Members/Member{slot}/Model",
             "events": [{"label": "Dance", "values": {"animationName": f"ch{owner:04}_so2056"}}]}
            for slot, owner in enumerate((210, 211, 212), start=1)
        ]
        self.assertEqual(
            [(actor["position"], actor["memberId"], actor["outfit"])
             for actor in mv_studio._cast_in_timeline_order(performers, tracks)],
            [(1, 210, "Shioriko"), (2, 212, "Lanzhu"), (3, 211, "Mia")],
        )
        self.assertIs(mv_studio._cast_in_timeline_order(performers, tracks[:2]), performers)


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
                CREATE TABLE m_member (id INTEGER PRIMARY KEY, theme_color INTEGER);
                CREATE TABLE m_suit (id INTEGER, member_m_id INTEGER, name TEXT, model_asset_path TEXT);
                INSERT INTO m_live VALUES (12, 'k.song', 4, 'song', NULL, 9, NULL), (13, 'k.second', 5, NULL, NULL, 9, NULL);
                INSERT INTO m_live_3d_asset VALUES (31, 'timeline', 7, NULL, NULL, 3, NULL);
                INSERT INTO m_live_stage VALUES (7, 'k.stage', 'scene_stage', 'model', NULL, 'bg');
                INSERT INTO m_live_mv VALUES (12, 7, 1, 31);
                INSERT INTO m_live_difficulty VALUES (13, 31);
                INSERT INTO m_live_member_mapping VALUES (9, 1, 101, 1, 51);
                INSERT INTO m_member VALUES (101, -690631937);
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

    def test_stage_model_follows_the_3d_asset_not_the_mv_picker_stage(self):
        # Like 11072 position 3: m_live_mv lists picker stage bg0001 (1000101), but the
        # client loads m_live_3d_asset.live_stage_master_id (bg0018, 1001801).
        with closing(sqlite3.connect(self.root / "assets/db/gl/masterdata.db")) as db, db:
            db.executescript("""
                INSERT INTO m_live VALUES (14, 'k.third', 6, NULL, NULL, 9, NULL);
                INSERT INTO m_live_3d_asset VALUES (33, 'timeline', 18, NULL, NULL, 3, NULL);
                INSERT INTO m_live_stage VALUES (1, 'k.picker', 'bg0001_01_s1', 'pickerModel', NULL, 'pickerBg'),
                    (18, 'k.special', 'bg0018_01_s1', 'specialModel', NULL, 'specialBg');
                INSERT INTO m_live_mv VALUES (14, 1, 3, 33), (14, 7, 1, 31);
            """)
        song = next(row for row in studio.catalog(self.root, region="gl", platform="android", language="en")["songs"]
                    if row["id"] == 14)
        self.assertEqual([(row["id"], row["stageId"], row["pickerStageId"], row["sceneName"], row["position"])
                          for row in song["variants"]],
                         [(31, 7, 7, "scene_stage", 1), (33, 18, 1, "bg0018_01_s1", 3)])
        selected = studio.resolve(self.root, region="gl", platform="android", live_id=14, asset_id=33, language="en")
        self.assertEqual((selected["stage"]["id"], selected["stage"]["sceneName"]), (18, "bg0018_01_s1"))
        self.assertEqual(selected["stageModel"]["asset"], "specialModel")
        self.assertEqual(selected["stage"]["background"]["asset"], "specialBg")
        self.assertNotIn("pickerModel", {row["asset"] for row in selected["missing"]})

    def test_resolves_same_platform_dependencies_costume_and_music(self):
        android, ios = self.selection(), self.selection("ios")
        self.assertEqual(android["timeline"]["pack_name"], "androidpack")
        self.assertEqual(ios["timeline"]["pack_name"], "iospack")
        self.assertEqual(ios["qualitySet"], 3)
        self.assertEqual([r["asset"] for r in ios["choreography"]], ["dance"])
        self.assertEqual([r["asset"] for r in ios["shaderDependencies"]], ["stageShader"])
        self.assertEqual(ios["performers"][0]["costumeName"], "Default costume")
        self.assertEqual(ios["performers"][0]["themeColor"], [214 / 255, 213 / 255, 202 / 255, 1.0])
        self.assertEqual(ios["audio"]["acb"]["pack_name"], "acbpack")
        self.assertEqual(ios["missing"][0]["asset"], "unavailable")

    def test_explicit_costumes_replace_the_member_mapping_suit(self):
        # A recorded game performance may wear another suit than m_live_member_mapping
        # (12035 runtime dump: 102111001 instead of 102112001). The import can pin it.
        with closing(sqlite3.connect(self.root / "assets/db/gl/masterdata.db")) as db, db:
            db.execute("INSERT INTO m_suit VALUES (52, 101, 'k.costume', 'costume2'), (61, 102, 'k.costume', 'other')")
        for platform in ("a", "i"):
            with closing(sqlite3.connect(self.root / f"assets/db/gl/asset_{platform}_en.db")) as db, db:
                db.execute("INSERT INTO member_model VALUES ('costume2', ?, 4, ?, 7, 11)",
                           ("androidpack" if platform == "a" else "iospack", len(self.plain)))
        pinned = studio.resolve(self.root, region="gl", platform="android", live_id=12, asset_id=31, language="en",
                                costumes={"1": 52})["performers"][0]
        self.assertEqual((pinned["costumeId"], pinned["model"]["asset"]), (52, "costume2"))
        self.assertEqual([choice["id"] for choice in pinned["costumes"]], [52, 51])
        self.assertEqual(self.selection()["performers"][0]["costumeId"], 51, "the mapping suit stays the default")
        for costumes, error in (({"1": 61}, "not a costume of the member at position 1"), ({"2": 51}, "no member at its position"),
                                ({"x": 52}, "valid costumes"), ({"1": "52"}, "valid costumes"), ([52], "valid costumes")):
            with self.subTest(costumes=costumes), self.assertRaisesRegex(ValueError, error):
                studio.resolve(self.root, region="gl", platform="android", live_id=12, asset_id=31, language="en", costumes=costumes)

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

    def test_exact_game_actor_reuses_only_verified_media_for_matching_inputs(self):
        model = self.root / "model.unity"
        companion = self.root / "face.unity"
        motion = self.root / "dance.unity"
        for file in (model, companion, motion):
            file.write_bytes(file.name.encode())
        meta = {"available": True, "clips": [{"bindingComplete": True, "sourceName": "Native"}]}
        glb = model_viewer._Glb().finish()

        def open_actor():
            return mv_studio._preview(model, performer=True, motions=(motion,), companions=(companion,), reuse=True)

        with (
            patch.object(mv_studio, "_root", return_value=self.root),
            patch.object(model_viewer, "prepare", return_value={"id": "actor", "rig": meta}) as prepare,
            patch.object(model_viewer, "get_model", return_value=glb),
        ):
            url, _ = open_actor()
            cached_url, cached_rig = open_actor()
            self.assertEqual((cached_url, cached_rig), (url, meta))
            self.assertEqual(prepare.call_count, 1)
            cached_rig["clips"].clear()
            self.assertEqual(open_actor()[1], meta)

            media, _ = mv_studio.media(url.rsplit("/", 1)[-1])
            media.write_bytes(glb[:-1] + bytes([glb[-1] ^ 1]))
            self.assertEqual(open_actor()[0], url)
            self.assertEqual(prepare.call_count, 2)
            self.assertEqual(media.read_bytes(), glb)

            motion.write_bytes(b"Different authored timeline clip data")
            open_actor()
            self.assertEqual(prepare.call_count, 3)

    def test_exact_game_stage_reuses_successful_media_across_staging_directories(self):
        first = self.root / "old-import" / "game-2.unity"
        repeated = self.root / "new-import" / "game-2.unity"
        for file in (first, repeated):
            file.parent.mkdir()
            file.write_bytes(b"Verified native stage source")
        glb = model_viewer._Glb().finish()
        with (
            patch.object(mv_studio, "_root", return_value=self.root),
            patch.object(model_viewer, "prepare", return_value={"id": "stage", "warnings": []}) as prepare,
            patch.object(model_viewer, "get_model", return_value=glb),
        ):
            output = mv_studio._preview(first, reuse=True)
            self.assertEqual(mv_studio._preview(repeated, reuse=True), output)
            self.assertEqual(prepare.call_count, 1)
            media_path = mv_studio.media(output[0].rsplit("/", 1)[-1])[0]
            media_path.write_bytes(glb[:-1] + bytes([glb[-1] ^ 1]))
            self.assertEqual(mv_studio._preview(repeated, reuse=True), output)
            self.assertEqual(prepare.call_count, 2)
            self.assertEqual(media_path.read_bytes(), glb)
            repeated.write_bytes(b"Changed stage source")
            prepare.return_value["warnings"] = ["A stage texture was temporarily unavailable."]
            mv_studio._preview(repeated, reuse=True)
            mv_studio._preview(repeated, reuse=True)
            self.assertEqual(prepare.call_count, 4)
