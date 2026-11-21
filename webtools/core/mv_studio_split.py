"""Resolve the original Unity mesh masks used by a live split-screen clip."""

import math
import struct

from . import mv_studio_timeline as timeline

_SPLIT_BINDING = "/EntryPoint/Live/Cameras/SplitScreenEffect"
_MAX_MASKS = 128
_MAX_VERTICES = 256
_MAX_INDICES = 768


def _mesh(object_reader):
    from .model_mesh import PreviewMeshHandler
    from .model_viewer import _validate_mesh_allocations

    mesh = object_reader.read()
    _validate_mesh_allocations(mesh)
    count = getattr(mesh.m_VertexData, "m_VertexCount", 0)
    packed = getattr(getattr(mesh.m_CompressedMesh, "m_Vertices", None), "m_NumItems", 0)
    if max(count, (packed + 2) // 3) > _MAX_VERTICES or sum(p.indexCount for p in mesh.m_SubMeshes) > _MAX_INDICES:
        raise ValueError("A split-screen mask exceeds the supported mesh size.")
    handler = PreviewMeshHandler(mesh)
    handler.process()
    vertices, uv = handler.m_Vertices or (), handler.m_UV0 or ()
    if not 3 <= len(vertices) <= _MAX_VERTICES or len(uv) != len(vertices):
        raise ValueError("A split-screen mask is missing its positions or UVs.")
    positions = [float(value) for vertex in vertices for value in vertex[:3]]
    uv = [float(value) for point in uv for value in point[:2]]
    indices = [int(index) + int(part.baseVertex or 0)
               for part, triangles in zip(mesh.m_SubMeshes, handler.get_triangles())
               for triangle in triangles for index in triangle]
    extents = mesh.m_LocalAABB.m_Extent
    bounds = [float(extents.x) * 2, float(extents.y) * 2]
    if (len(positions) != len(vertices) * 3 or len(uv) != len(vertices) * 2
            or not all(math.isfinite(value) and abs(value) <= 64 for value in positions + uv)
            or not 3 <= len(indices) <= _MAX_INDICES or min(indices) < 0 or max(indices) >= len(vertices)
            or not all(math.isfinite(value) and 0 < value <= 64 for value in bounds)):
        raise ValueError("A split-screen mask has invalid mesh data.")
    return {"positions": positions, "uv": uv, "indices": indices, "bounds": bounds}


def read(objects, mono, tracks, deadline):
    """Match masks to exact clip PPtrs without adding data to editable events."""
    from .model_viewer import ModelViewerError, _remaining

    masks, events = {}, {}
    by_id = {timeline._id(key): row for key, row in mono.items() if row[2] == "LiveSplitScreenTrack"}
    for track in tracks:
        native = by_id.get(track["id"])
        if native is None or track.get("binding") != _SPLIT_BINDING:
            continue
        obj, tree, _ = native
        for event in track["events"]:
            _remaining(deadline)
            clip_index = int(event["id"].rsplit(":", 1)[1])
            asset_key = timeline._pointer(obj, tree["m_Clips"][clip_index].get("m_Asset"))
            playable = mono.get(asset_key)
            if playable is None or playable[2] != "LiveSplitScreenClip":
                continue
            asset, values, _ = playable
            refs = [None] * 4
            for slot in range(1, 5):
                pointer = values.get(f"mask{slot}")
                key = timeline._pointer(asset, pointer)
                if key is None:
                    continue
                reader = objects.get(key)
                if reader is None or reader.type.name != "Mesh":
                    continue
                identity = timeline._id(key)
                if identity not in masks and len(masks) < _MAX_MASKS:
                    try:
                        masks[identity] = _mesh(reader)
                    except (ModelViewerError, AttributeError, IndexError, KeyError, OverflowError, TypeError, ValueError, struct.error):
                        masks[identity] = None
                if masks.get(identity) is not None:
                    refs[slot - 1] = {"key": identity, "pointer": event["values"][f"mask{slot}"]}
            events[event["id"]] = refs
    return {"masks": {key: value for key, value in masks.items() if value is not None}, "events": events} if events else None
