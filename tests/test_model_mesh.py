"""Bit-exact vertex-read comparisons with UnityPy's existing implementation."""
import copy
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from UnityPy.enums.VertexFormat import (
    VERTEX_CHANNEL_FORMAT_STRUCT_TYPE_MAP,
    VERTEX_FORMAT_2017_STRUCT_TYPE_MAP,
    VERTEX_FORMAT_STRUCT_TYPE_MAP,
)
from UnityPy.helpers import MeshHelper
from webtools.core import model_mesh


FIELDS = ("m_VertexCount", "m_Vertices", "m_Normals", "m_Tangents", "m_Colors",
          "m_BoneWeights", "m_BoneIndices") + tuple(f"m_UV{index}" for index in range(8))


def bits(value):
    if isinstance(value, float):
        return struct.pack(">d", value)  # includes signed zero and NaN payload bits
    if isinstance(value, (list, tuple)):
        return tuple(bits(item) for item in value)
    return value


def snapshot(handler):
    return {name: bits(getattr(handler, name)) for name in FIELDS}


class StridedVertexTests(unittest.TestCase):
    def setUp(self):
        self.boost = patch.object(MeshHelper, "UnityPyBoost", None)
        self.boost.start()
        self.addCleanup(self.boost.stop)

    def compare(self, data, channels, streams, count=3, version=(2019, 4, 0, 0), endian="<", fast=True):
        before = bytes(data)
        src = SimpleNamespace(m_VertexData=SimpleNamespace(m_VertexCount=count, m_DataSize=data))
        baseline = MeshHelper.MeshHandler(src, version=version, endianess=endian)
        expected_error = None
        try:
            baseline.read_vertex_data(channels, streams)
        except Exception as error:
            expected_error = type(error)
        actual = model_mesh.PreviewMeshHandler(src, version=version, endianess=endian)
        with patch.object(model_mesh, "_strided_values", wraps=model_mesh._strided_values) as gather:
            if expected_error:
                with self.assertRaises(expected_error):
                    actual.read_vertex_data(channels, streams)
            else:
                actual.read_vertex_data(channels, streams)
            self.assertEqual(snapshot(actual), snapshot(baseline))
            if fast:
                self.assertGreater(gather.call_count, 0)
            else:
                gather.assert_not_called()
        self.assertEqual(bytes(data), before)
        return actual

    def test_all_version_formats_dimensions_endians_and_buffers(self):
        tables = [((5, 6, 0, 0), VERTEX_CHANNEL_FORMAT_STRUCT_TYPE_MAP),
                  ((2017, 4, 0, 0), VERTEX_FORMAT_2017_STRUCT_TYPE_MAP),
                  ((2019, 4, 0, 0), VERTEX_FORMAT_STRUCT_TYPE_MAP)]
        for version, table in tables:
            for format, dtype in table.items():
                for dimension in range(1, 5):
                    for endian in ("<", ">"):
                        for container in (bytes, bytearray):
                            with self.subTest(version=version, format=format, dimension=dimension,
                                              endian=endian, container=container):
                                width = dimension * struct.calcsize(dtype)
                                stride = width + 5
                                raw = bytearray((index * 137 + 31) % 256 for index in range(7 + 3 * stride))
                                channels = [MeshHelper.ChannelInfo(dimension, int(format), 2, 0)]
                                streams = [MeshHelper.StreamInfo(channelMask=1, offset=7, stride=stride)]
                                self.compare(container(raw), channels, streams, version=version, endian=endian)

    def test_special_float_bit_patterns(self):
        patterns = {0: (4, [0, 0x80000000, 1, 0x007FFFFF, 0x7F800000, 0xFF800000,
                            0x7FC12345, 0x7FA12345, 0xFFC45678]),
                    1: (2, [0, 0x8000, 1, 0x03FF, 0x7C00, 0xFC00, 0x7E35, 0x7D35, 0xFE78])}
        for format, (size, values) in patterns.items():
            for endian in ("<", ">"):
                with self.subTest(format=format, endian=endian):
                    raw = b"".join(value.to_bytes(size, "little" if endian == "<" else "big") for value in values)
                    self.compare(raw, [MeshHelper.ChannelInfo(3, format, 0, 0)],
                                 [MeshHelper.StreamInfo(1, 0, 3 * size)], endian=endian)

    def test_integer_limits_are_not_normalized(self):
        for version, table in [((5, 6, 0, 0), VERTEX_CHANNEL_FORMAT_STRUCT_TYPE_MAP),
                               ((2017, 4, 0, 0), VERTEX_FORMAT_2017_STRUCT_TYPE_MAP),
                               ((2019, 4, 0, 0), VERTEX_FORMAT_STRUCT_TYPE_MAP)]:
            for format, dtype in table.items():
                if dtype in ("f", "e"):
                    continue
                size = struct.calcsize(dtype)
                signed = dtype.islower()
                low = -(1 << (size * 8 - 1)) if signed else 0
                high = (1 << (size * 8 - (1 if signed else 0))) - 1
                for endian in ("<", ">"):
                    with self.subTest(version=version, format=format, endian=endian):
                        raw = struct.pack(endian + "3" + dtype, low, high, 0)
                        result = self.compare(raw, [MeshHelper.ChannelInfo(1, int(format), 0, 0)],
                                              [MeshHelper.StreamInfo(1, 0, size)], version=version, endian=endian)
                        self.assertEqual(result.m_Vertices, [(low,), (high,), (0,)])

    def test_interleaved_multistream_channels_and_masked_dimension(self):
        channels = [MeshHelper.ChannelInfo(0, 0, 0, 0) for _ in range(14)]
        for index, dimension, format, offset, stream in [(0, 3, 0, 0, 0), (1, 3, 5, 12, 0),
                                                          (4, 0x12, 1, 18, 0), (12, 4, 0, 0, 1),
                                                          (13, 4, 10, 16, 1)]:
            channels[index] = MeshHelper.ChannelInfo(dimension, format, offset, stream)
        streams = [MeshHelper.StreamInfo((1 << 0) | (1 << 1) | (1 << 4), 3, 24),
                   MeshHelper.StreamInfo((1 << 12) | (1 << 13), 83, 32)]
        for endian in ("<", ">"):
            self.compare(bytes((index * 73 + 11) % 256 for index in range(179)), channels, streams, endian=endian)

    def test_legacy_color_dimension_override_does_not_mutate_channel(self):
        channels = [MeshHelper.ChannelInfo(0, 0, 0, 0), MeshHelper.ChannelInfo(0, 0, 0, 0),
                    MeshHelper.ChannelInfo(1, 2, 0, 0)]
        before = copy.deepcopy(channels)
        for version in ((5, 6, 0, 0), (2017, 4, 0, 0)):
            self.compare(bytes(range(12)), channels, [MeshHelper.StreamInfo(4, 0, 4)], version=version)
        self.assertEqual(channels, before)

    def test_invalid_later_channel_falls_back_before_any_fast_assignment(self):
        channels = [MeshHelper.ChannelInfo(3, 0, 0, 0), MeshHelper.ChannelInfo(3, 0, 0, 1)]
        streams = [MeshHelper.StreamInfo(1, 0, 12), MeshHelper.StreamInfo(2, 36, 12)]
        self.compare(bytes(39), channels, streams, fast=False)

    def test_malformed_layouts_keep_upstream_results_or_exceptions(self):
        cases = [(-1, 12, 0, 0, 3, 0), (0, -1, 0, 0, 3, 0), (0, 12, -1, 0, 3, 0),
                 (0, 4, 0, 0, 3, 0), (0, 12, 0, -1, 3, 0), (0, 12, 0, 2, 3, 0),
                 (0, 12, 0, 0, 0x10, 0), (0, 12, 0, 0, 3, 99)]
        for offset, stride, channel_offset, stream, dimension, format in cases:
            with self.subTest(case=(offset, stride, channel_offset, stream, dimension, format)):
                self.compare(bytes(36), [MeshHelper.ChannelInfo(dimension, format, channel_offset, stream)],
                             [MeshHelper.StreamInfo(1, offset, stride)], fast=False)

    def test_mask_disabled_channel_and_malformed_mask_keep_upstream_semantics(self):
        channels = [MeshHelper.ChannelInfo(3, 0, 0, 0), MeshHelper.ChannelInfo(3, 0, 0, 0)]
        self.compare(bytes(36), channels, [MeshHelper.StreamInfo(2, 0, 12)])
        self.compare(bytes(36), channels, [MeshHelper.StreamInfo(-1, 0, 12)], fast=False)
        channels = [MeshHelper.ChannelInfo(0, 0, 0, 0) for _ in range(4)] + [MeshHelper.ChannelInfo(3, 0, 0, 0)]
        self.compare(bytes(36), channels, [MeshHelper.StreamInfo(0, 0, 12)], fast=False)

    def test_unknown_channel_delegates_before_assignment(self):
        channels = [MeshHelper.ChannelInfo(0, 0, 0, 0) for _ in range(14)] + [MeshHelper.ChannelInfo(3, 0, 0, 0)]
        self.compare(bytes(36), channels, [MeshHelper.StreamInfo(1 << 14, 0, 12)], fast=False)

    def test_empty_compressed_and_nonbyte_buffers_keep_upstream_path(self):
        channels, streams = [MeshHelper.ChannelInfo(3, 0, 0, 0)], [MeshHelper.StreamInfo(1, 0, 12)]
        for data, count in [(b"", 3), (bytes(36), 0), (bytes(36), -1),
                            (list(bytes(36)), 3), (memoryview(bytes(36)), 3)]:
            with self.subTest(data=type(data).__name__, count=count):
                self.compare(data, channels, streams, count=count, fast=False)

    def test_boost_keeps_upstream_method(self):
        src = SimpleNamespace(m_VertexData=None)
        handler = model_mesh.PreviewMeshHandler(src, version=(2019, 4, 0, 0))
        with patch.object(MeshHelper, "UnityPyBoost", object()), \
                patch.object(MeshHelper.MeshHandler, "read_vertex_data", return_value="upstream") as original, \
                patch.object(handler, "_vertex_plans", side_effect=AssertionError("fast path must not run")):
            self.assertEqual(handler.read_vertex_data([], []), "upstream")
            original.assert_called_once_with([], [])

    def test_compressed_mesh_process_and_assignment_remain_upstream(self):
        import UnityPy
        fixture = Path(__file__).parent / "fixtures" / "viewer_triangle.unity"
        for fully_compressed in (False, True):
            results = []
            for handler_class in (MeshHelper.MeshHandler, model_mesh.PreviewMeshHandler):
                env = UnityPy.load(str(fixture))
                mesh = next(obj.read() for obj in env.objects if obj.type.name == "Mesh")
                mesh.m_CompressedMesh.m_Vertices = SimpleNamespace(
                    m_NumItems=9, m_BitSize=8, m_Data=bytes([0, 0, 0, 255, 0, 0, 0, 255, 0]),
                    m_Start=-0.5, m_Range=2.0)
                if fully_compressed:
                    mesh.m_VertexData.m_VertexCount = 0
                    mesh.m_VertexData.m_DataSize = b""
                handler = handler_class(mesh)
                with patch.object(model_mesh, "_strided_values", wraps=model_mesh._strided_values) as gather:
                    handler.process()
                    if handler_class is model_mesh.PreviewMeshHandler:
                        self.assertEqual(gather.call_count > 0, not fully_compressed)
                results.append(snapshot(handler))
                self.assertEqual(handler.m_Vertices, [[-0.5, -0.5, -0.5],
                                                      [1.5, -0.5, -0.5], [-0.5, 1.5, -0.5]])
            self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
