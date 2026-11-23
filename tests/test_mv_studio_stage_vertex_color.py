"""Meshes without a COLOR stream read opaque white in vertex-colored stage shaders."""
from types import SimpleNamespace
import unittest

from webtools.core import mv_studio_stage_materials as stage


def _handler(colors, channels, compressed_colors=0):
    channel = lambda dimension, fmt=0: SimpleNamespace(dimension=dimension, format=fmt)
    return SimpleNamespace(
        m_Colors=colors, m_UV1=None, m_UV2=None,
        src=SimpleNamespace(m_VertexData=SimpleNamespace(m_Channels=[channel(*row) for row in channels]),
                            m_CompressedMesh=SimpleNamespace(m_Colors=SimpleNamespace(m_NumItems=compressed_colors))))


class VertexColorInputTests(unittest.TestCase):
    def test_missing_color_stream_is_marked_absent(self):
        # 12038 LaserBox: position, normal, tangent, no COLOR, UV0.
        output = {}
        stage.read_vertex_inputs(_handler(None, [(3,), (3,), (4,), (0,), (2,)]), output, 42)
        self.assertEqual(output, {"colorAbsent": True})

    def test_authored_or_unreadable_colors_are_not_absent(self):
        output = {}
        stage.read_vertex_inputs(_handler([[255, 255, 255, 255]] * 2, [(3,), (3,), (4,), (4, 2), (2,)]), output, 2)
        self.assertEqual(output["color"].tolist(), [[1, 1, 1, 1]] * 2)
        self.assertNotIn("colorAbsent", output)
        for handler in (_handler(None, [(3,), (3,), (4,), (4, 2), (2,)]),   # declared but unreadable
                        _handler(None, [(3,), (3,)]),                       # no channel table entry
                        _handler(None, [(3,), (3,), (4,), (0,)], compressed_colors=8)):
            output = {}
            stage.read_vertex_inputs(handler, output, 2)
            self.assertEqual(output, {})


if __name__ == "__main__":
    unittest.main()
