"""Stage-node clip material curves of the soft billboard and smoke passes."""
import unittest
from zlib import crc32

from webtools.core import model_animation as animation
from webtools.core import mv_studio_stage_overlay as overlay

_NULL = {"m_FileID": 0, "m_PathID": 0}
_SMOKE = animation.path_hash("smoke_01")


def _binding(name, lane, *, path=_SMOKE, renderer=23, script=_NULL):
    return {"path": path, "attribute": (lane << 28) | crc32(name.encode()) & 0x0FFFFFFF, "typeID": renderer,
            "customType": 22, "isPPtrCurve": 0, "script": script}


def _decode(rows, **options):
    curves = [("constant", float(index)) for index in range(len(rows))]
    return overlay.material_channels(rows, curves, lambda _: 1, **options), curves


class MaterialCurvePolicyTests(unittest.TestCase):
    def test_every_smoke_and_fog_float_is_a_world_channel(self):
        # 11030 clip_stg_so1030_05 animates these AS/Smoke floats.
        names = ("_CurvePower", "_FadeOutPower", "_FadeOutScale", "_TextureRate", "_MoveSpeed", "_SizeAspect")
        (channels, count), curves = _decode([_binding(name, 8) for name in names], world=True)
        self.assertEqual(count, len(names))
        self.assertEqual({row["property"]: row["curves"] for row in channels},
                         {name: [curves[index]] for index, name in enumerate(names)})


if __name__ == "__main__":
    unittest.main()
