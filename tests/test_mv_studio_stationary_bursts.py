import unittest

from webtools.core import mv_studio_stationary_bursts as bursts


class StationaryBurstSourceTests(unittest.TestCase):
    def test_gradient_holds_last_declared_alpha(self):
        white = dict.fromkeys("rgba", 1)
        gradient = {
            "m_Mode": 0, "m_NumColorKeys": 2, "m_NumAlphaKeys": 3,
            "ctime0": 0, "ctime1": 65535,
            "atime0": 0, "atime1": 12743, "atime2": 14260, "atime3": 65535,
            "key0": white, "key1": white, "key2": {**white, "a": 0}, "key3": white,
        }
        fields = {"minMaxState": 1, "maxGradient": gradient}
        self.assertEqual(bursts._color_over_life(fields), {
            "rgb": [[0, 1, 1, 1], [65535, 1, 1, 1]],
            "alpha": [[0, 1], [12743, 1], [14260, 0], [65535, 0]],
        })
        self.assertIsNone(bursts._color_over_life({**fields, "minMaxState": 3}))

    def test_atlas_preserves_grid_uvs_and_rejects_sprite_sheet(self):
        def fixed(value):
            return {"minMaxState": 0, "scalar": value}

        fields = {
            "mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1, "randomRow": True,
            "rowIndex": 0, "flipU": 0, "flipV": 0, "uvChannelMask": -1,
            "tilesX": 4, "tilesY": 8, "startFrame": fixed(.46875), "frameOverTime": fixed(0),
            "sprites": [{"sprite": {"m_FileID": 0, "m_PathID": 0}}],
        }
        self.assertEqual(bursts._atlas(fields), [.25, .125, .75, .375])
        self.assertIsNone(bursts._atlas({**fields, "frameOverTime": fixed(.5)}))
        self.assertIsNone(bursts._atlas({
            **fields, "sprites": [{"sprite": {"m_FileID": 1, "m_PathID": 2}}],
        }))
