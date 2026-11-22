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

    def test_moving_drag_uses_one_multiplier_and_preserves_short_curves(self):
        def curve(end, value):
            return {
                "m_PreInfinity": 2, "m_PostInfinity": 2, "m_Curve": [
                    {"time": 0, "value": 0, "inSlope": 0, "outSlope": 12, "weightedMode": 0},
                    {"time": end, "value": value, "inSlope": 0, "outSlope": 0, "weightedMode": 0},
                ],
            }

        fields = {
            "separateAxis": False, "inWorldSpace": False, "multiplyDragByParticleSize": True,
            "multiplyDragByParticleVelocity": True, "dampen": .15,
            "magnitude": {"minMaxState": 0, "scalar": 1},
            "drag": {"minMaxState": 2, "scalar": 10, "minScalar": 1.72,
                     "minCurve": curve(.03, .5), "maxCurve": curve(.02, 1)},
        }
        self.assertEqual(bursts._moving_clamp(fields), {
            "limit": 1, "dampen": .15, "drag": {
                "minKeys": [[0, 0, 0, 12], [.03, .5, 0, 0]],
                "maxKeys": [[0, 0, 0, 12], [.02, 1, 0, 0]],
                "multiplier": 10,
            },
        })
        self.assertIsNone(bursts._moving_clamp({**fields, "multiplyDragByParticleSize": False}))

    def test_moving_emission_admits_one_time_zero_burst(self):
        zero = {"minMaxState": 0, "scalar": 0}
        schedule = {"time": 0, "cycleCount": 1, "probability": 1,
                    "countCurve": {"minMaxState": 0, "scalar": 10}}
        fields = {"rateOverTime": zero, "rateOverDistance": zero, "m_BurstCount": 1, "m_Bursts": [schedule]}
        self.assertEqual(bursts._moving_count(fields), 10)
        self.assertIsNone(bursts._moving_count({**fields, "m_Bursts": [{**schedule, "cycleCount": 2}]}))
