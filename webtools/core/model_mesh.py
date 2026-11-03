"""Read validated interleaved vertex scalars without intermediate byte copies.

UnityPy retains ownership of format selection, channel assignment, index reading
and compressed meshes. Only its pure-Python vertex byte gather is replaced.
"""
import struct

from UnityPy.helpers import MeshHelper


def _strided_values(data, offset, stride, count, unpack):
    return [unpack(data, offset + stride * index) for index in range(count)]


class PreviewMeshHandler(MeshHelper.MeshHandler):
    def _vertex_plans(self, channels, streams):
        if not isinstance(channels, (list, tuple)) or not isinstance(streams, (list, tuple)):
            return None  # do not consume one-shot iterables before an upstream fallback
        vertex = self.src.m_VertexData
        if vertex is None:
            return None
        count = vertex.m_VertexCount
        if count == 0:
            return None  # upstream does not access m_DataSize for compressed-only meshes
        data = vertex.m_DataSize
        # Other containers keep the upstream interpretation and error behavior.
        if type(count) is not int or count <= 0 or type(data) not in (bytes, bytearray) or not data:
            return None
        plans = []
        try:
            for index, channel in enumerate(channels):
                if channel.dimension == 0:
                    continue
                if (type(channel.dimension) is not int or channel.dimension < 0
                        or index > (13 if self.version[0] >= 2018 else 7)):
                    return None
                if type(channel.stream) is not int or channel.stream < 0:
                    return None
                stream = streams[channel.stream]
                # Match upstream mask handling, including malformed-mask errors.
                if type(stream.channelMask) is not int or stream.channelMask < 0:
                    return None
                if bin(stream.channelMask)[::-1][index] != "1":
                    continue
                if self.version[0] < 2018 and index == 2 and channel.format == 2:
                    channel = MeshHelper.ChannelInfo(dimension=4, format=2,
                                                     offset=channel.offset, stream=channel.stream)
                dimension = channel.dimension & 0xF
                if not dimension:
                    return None
                dtype = self.get_channel_dtype(channel)
                component_size = self.get_channel_component_size(channel)
                # Upstream reverses little-endian component bytes then reads >.
                prefix = "<" if self.endianess == "<" and component_size > 1 else ">"
                unpack = struct.Struct(prefix + str(dimension) + dtype)
                if unpack.size != dimension * component_size:
                    return None
                if any(type(value) is not int for value in (stream.offset, stream.stride, channel.offset)):
                    return None
                if stream.offset < 0 or stream.stride <= 0 or channel.offset < 0:
                    return None
                offset = stream.offset + channel.offset
                if (channel.offset + unpack.size > stream.stride
                        or offset + (count - 1) * stream.stride + unpack.size > len(data)):
                    return None
                plans.append((index, unpack.unpack_from, offset, stream.stride))
        except (AttributeError, IndexError, TypeError, ValueError, OverflowError, struct.error):
            return None
        return count, data, plans

    def read_vertex_data(self, channels, streams):
        if MeshHelper.UnityPyBoost:
            return super().read_vertex_data(channels, streams)
        prepared = self._vertex_plans(channels, streams)
        if prepared is None:
            # Validate the whole call before assigning any optimized channel.
            return super().read_vertex_data(channels, streams)
        count, data, plans = prepared
        self.m_VertexCount = count
        for index, unpack, offset, stride in plans:
            values = _strided_values(data, offset, stride, count, unpack)
            self.assign_channel_vertex_data(index, values)
