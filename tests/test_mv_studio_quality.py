"""The studio reads each stage's original game-quality values and labels."""

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from webtools.core.mv_studio_quality import read_quality


FLAGS = (
    "frame_rate_60fps", "base_light", "stage_ambient", "stage_animation", "stage_coloring", "stage_control",
    "stage_overlay_effect", "stage_flash_light", "stage_display", "posteffect", "stage_emissive", "stage_audience",
    "stage_cubemap", "member_ambient", "member_rim_light", "member_spot_light_shaft", "member_spot_light_area",
    "member_swing_bone_live", "member_swing_bone_mv", "prop_ambient", "prop_rim_light", "split_screen",
)


class MVStudioQualityTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.master = self.root / "assets/db/gl/masterdata.db"
        self.master.parent.mkdir(parents=True)
        with sqlite3.connect(self.master) as db:
            db.execute("CREATE TABLE m_live_quality_mode(quality_mode INTEGER PRIMARY KEY,name TEXT,description TEXT,"
                       "dimension_name TEXT,system_index INTEGER)")
            db.executemany("INSERT INTO m_live_quality_mode VALUES(?,?,?,?,?)", [
                (50, "k.low2d", "k.low2d_desc", "k.m_live_quality_mode_2d", 4),
                (30, "k.normal3d", "k.normal3d_desc", "k.m_live_quality_mode_3d", 2),
                (40, "k.low3d", "k.low3d_desc", "k.m_live_quality_mode_3d", 3),
                (10, "k.max3d", "k.max3d_desc", "k.m_live_quality_mode_3d", 0),
            ])
            columns = ",".join(key + " INTEGER NOT NULL" for key in FLAGS)
            db.execute("CREATE TABLE m_live_quality_setting(set_id INTEGER,quality_mode INTEGER,rendering_resolution INTEGER,"
                       + columns + ",PRIMARY KEY(set_id,quality_mode))")
            query = "INSERT INTO m_live_quality_setting VALUES(" + ",".join(["?"] * (len(FLAGS) + 3)) + ")"
            db.executemany(query, [
                (1, 10, 1080, *([1] + [0] * 21)),
                (1, 30, 720, *([0] * 22)),
                (3, 10, 1080, *([1] * 22)),
                (3, 30, 720, *([0] * 21 + [1])),
                (3, 40, 640, *([0, 1, 0, 1] + [0] * 18)),
                (4, 50, 1080, *([1] + [0] * 21)),
            ])
        with sqlite3.connect(self.master.with_name("dictionary_ko_k.db")) as db:
            db.execute("CREATE TABLE m_dictionary(id TEXT PRIMARY KEY,message TEXT)")
            db.executemany("INSERT INTO m_dictionary VALUES(?,?)", [("max3d", "3D 매우 높음"),
                ("normal3d", "3D 보통"), ("low3d", "3D 경량"), ("low2d", "2D"), ("low2d_desc", "라이브가 2D로 표현됩니다.")])

    def test_stage_values_typed_controls_and_2d_fallback(self):
        result = read_quality(self.root, region="gl", language="ko", quality_set=3)
        modes = result["modes"]
        self.assertEqual([entry["id"] for entry in modes], [10, 30, 40, 50])
        self.assertEqual([entry["label"] for entry in modes], ["3D 매우 높음", "3D 보통", "3D 경량", "2D"])
        self.assertEqual(result["mode"], 30)
        self.assertEqual(result["values"], modes[1]["values"])
        self.assertEqual(result["values"]["set_id"], 3)
        self.assertEqual(result["values"]["quality_mode"], 30)
        self.assertEqual(result["values"]["rendering_resolution"], 720)
        self.assertIs(result["values"]["split_screen"], True)
        self.assertIs(result["values"]["posteffect"], False)
        self.assertIn("라이브가 2D로 표현됩니다.", modes[-1]["description"])
        self.assertIn("3D 경량", modes[-1]["description"])
        self.assertEqual({column["key"]: column["type"] for column in result["options"]},
                         {"rendering_resolution": "number", **dict.fromkeys(FLAGS, "boolean")})

    def test_mv_plays_the_2d_mode_with_the_presets_performance_3d_values(self):
        # LiveMvVO..ctor: an MV started in mode 50 runs with the recommended mode,
        # which is 40 when the device has none; never with the 2D set's values.
        modes = {entry["id"]: entry for entry in read_quality(self.root, region="gl", language="en", quality_set=3)["modes"]}
        self.assertEqual(modes[50]["values"], modes[40]["values"])
        self.assertEqual((modes[50]["values"]["set_id"], modes[50]["values"]["quality_mode"]), (3, 40))
        self.assertEqual(modes[50]["values"]["rendering_resolution"], 640)
        self.assertIs(modes[50]["values"]["frame_rate_60fps"], False)
        self.assertIs(modes[50]["values"]["base_light"], True)
        self.assertIs(modes[50]["values"]["stage_animation"], True)
        self.assertIn("MVs do not play in 2D", modes[50]["description"])
        self.assertIn(modes[40]["label"], modes[50]["description"])
        # A preset without a mode 40 row has no known MV values for mode 50.
        self.assertEqual([entry["id"] for entry in read_quality(self.root, region="gl", language="en")["modes"]], [10, 30])

    def test_default_initial_stage_and_missing_preset(self):
        result = read_quality(self.root, region="gl", language="en")
        self.assertEqual(result["values"]["set_id"], 1)
        self.assertIs(result["values"]["split_screen"], False)
        for invalid in (0, -1, "3", True, 999):
            with self.subTest(preset=invalid), self.assertRaises(ValueError):
                read_quality(self.root, region="gl", language="ko", quality_set=invalid)


if __name__ == "__main__":
    unittest.main()
