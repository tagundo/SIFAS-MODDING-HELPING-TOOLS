"""Flatten material-indexed graft geometry into the game's single Body slot.

Only UV0 and triangle indices change. Vertex rows shared by different atlas
regions are split byte-for-byte, including skin channels and morph deltas.
The caller retains the original renderer material and assigns the atlas to it.
"""
from __future__ import annotations

from copy import deepcopy
import numpy as np


def _expanded_shapes(shapes, duplicates, vertex_count):
    """Duplicate sparse morph entries within their original animation frames."""
    if not shapes or not duplicates:
        return deepcopy(shapes)
    output = deepcopy(shapes)
    vertices = shapes.get("vertices", [])
    frames = shapes.get("shapes", [])
    if vertices and not frames:
        raise ValueError("The mesh has morph vertices without animation frames.")
    copies = {}
    for new_index, source_index in duplicates:
        copies.setdefault(source_index, []).append(new_index)
    result, covered = [], set()
    for frame, destination in zip(frames, output.get("shapes", [])):
        first, count = int(frame.get("firstVertex", 0)), int(frame.get("vertexCount", 0))
        if first < 0 or count < 0 or first + count > len(vertices):
            raise ValueError("The mesh has an invalid morph-frame vertex range.")
        if any(index in covered for index in range(first, first + count)):
            raise ValueError("The mesh has overlapping morph-frame vertex ranges.")
        destination["firstVertex"] = len(result)
        additions = []
        for offset in range(first, first + count):
            covered.add(offset)
            entry = vertices[offset]
            index = int(entry.get("index", -1))
            if index < 0 or index >= vertex_count:
                raise ValueError("The mesh has an out-of-range morph vertex.")
            result.append(deepcopy(entry))
            for new_index in copies.get(index, ()):
                copied = deepcopy(entry)
                copied["index"] = new_index
                additions.append(copied)
        # Keep the original deltas in their original order, then add split rows.
        result.extend(sorted(additions, key=lambda entry: entry["index"]))
        destination["vertexCount"] = count + len(additions)
    result.extend(deepcopy(entry) for i, entry in enumerate(vertices) if i not in covered)
    output["vertices"] = result
    return output


def _transform_key(transform, fallback):
    """Share rows only when both affine parameters have identical encodings."""
    if not hasattr(transform, "scale") or not hasattr(transform, "offset"):
        return ("opaque", fallback)
    scale, offset = np.asarray(transform.scale), np.asarray(transform.offset)
    if scale.dtype.hasobject or offset.dtype.hasobject:
        return ("opaque", fallback)
    return (scale.dtype.str, scale.shape, scale.tobytes(),
            offset.dtype.str, offset.shape, offset.tobytes())


def flatten_material_groups(mesh_tree, transforms, *, max_vertices=65535):
    """Bake one atlas UV transform per submesh and merge all triangle groups.

    ``transforms`` contains objects exposing ``remap_uv(ndarray)``. The function
    validates and prepares the complete result before mutating ``mesh_tree``.
    Unreferenced original vertex rows are retained. All bind poses, bone hashes,
    channels other than UV0 and unrelated mesh metadata retain their values.
    """
    # A lazy import avoids a cycle when the transplant tool calls this module.
    from costume_part_transplant import stream_layout, submesh_triangles, ATTR_UV0

    source_index_format = int(mesh_tree.get("m_IndexFormat", 0))
    if source_index_format not in (0, 1):
        raise ValueError("The mesh uses an unsupported index format.")
    index_width = 2 if source_index_format == 0 else 4
    if len(mesh_tree.get("m_IndexBuffer", b"")) % index_width:
        raise ValueError("The mesh index buffer has an incomplete index.")
    if any(int(group.get("firstByte", 0)) % index_width for group in mesh_tree.get("m_SubMeshes", [])):
        raise ValueError("A source submesh index range is not aligned.")
    groups = submesh_triangles(mesh_tree)
    transforms = tuple(transforms)
    if not groups or len(transforms) != len(groups):
        raise ValueError("The atlas needs one UV transform for each source submesh.")
    vc, channels, strides, starts, total = stream_layout(mesh_tree)
    if vc < 1:
        raise ValueError("The atlas source mesh has no vertices.")
    if max_vertices is not None and vc > max_vertices:
        raise ValueError(f"The Body mesh already exceeds the game's {max_vertices} vertex limit.")
    if mesh_tree.get("m_VariableBoneCountWeights", {}).get("m_Data"):
        raise ValueError("Atlas merging does not support variable-count skin weights yet.")
    if mesh_tree.get("m_StreamData", {}).get("size", 0):
        raise ValueError("Atlas merging requires inline vertex data; reimport the original bundle.")
    compressed = mesh_tree.get("m_CompressedMesh", {})
    if any(isinstance(value, dict) and value.get("m_NumItems", 0) for value in compressed.values()):
        raise ValueError("Atlas merging requires an uncompressed vertex/index mesh.")
    if ATTR_UV0 >= len(channels):
        raise ValueError("The Body mesh has no UV0 channel for its texture atlas.")
    uv_channel = channels[ATTR_UV0]
    if uv_channel.get("dimension", 0) < 2 or uv_channel.get("format") not in (0, 1):
        raise ValueError("Atlas merging requires Float32 or Float16 UV0 coordinates.")
    original = np.frombuffer(bytes(mesh_tree["m_VertexData"]["m_DataSize"]), np.uint8)
    required = max(starts[s] + vc * strides[s] for s in strides)
    if len(original) < required:
        raise ValueError("The mesh vertex buffer is incomplete; reimport its original bundle.")
    width = 4 if uv_channel["format"] == 0 else 2
    uv_dtype = "<f4" if width == 4 else "<f2"
    uv_stream, uv_offset = uv_channel["stream"], uv_channel["offset"]
    from costume_part_transplant import FMT_BYTES
    for attribute, channel in enumerate(channels):
        if attribute == ATTR_UV0 or not channel.get("dimension", 0) or channel["stream"] != uv_stream:
            continue
        end = channel["offset"] + channel["dimension"] * FMT_BYTES[channel["format"]]
        if channel["offset"] < uv_offset + width * 2 and end > uv_offset:
            raise ValueError("The mesh UV0 bytes overlap another vertex attribute.")
    old_block = original[starts[uv_stream]:starts[uv_stream] + vc * strides[uv_stream]].reshape(vc, strides[uv_stream])
    uv = old_block[:, uv_offset:uv_offset + width * 2].copy().view(uv_dtype).reshape(vc, 2).astype(np.float64)
    if not np.isfinite(uv).all():
        raise ValueError("The mesh contains non-finite UV0 coordinates.")

    canonical, identifiers = [], {}
    for index, transform in enumerate(transforms):
        key = _transform_key(transform, index)
        canonical.append(identifiers.setdefault(key, index))
    owners = np.full(vc, -1, np.int64)
    source_rows = list(range(vc))
    shared_rows = {}
    duplicates, remapped_groups, uv_rows = [], [], []
    for group_index, (faces, transform) in enumerate(zip(groups, transforms)):
        if np.any(faces < 0) or np.any(faces >= vc):
            raise ValueError("A source submesh references a vertex outside its buffer.")
        used = np.unique(faces)
        destination = used.copy()
        transform_id = canonical[group_index]
        shared = (owners[used] >= 0) & (owners[used] != transform_id)
        for position in np.flatnonzero(shared):
            source_index = int(used[position])
            key = (transform_id, source_index)
            new_index = shared_rows.get(key)
            if new_index is None:
                new_index = len(source_rows)
                shared_rows[key] = new_index
                source_rows.append(source_index)
                duplicates.append((new_index, source_index))
            destination[position] = new_index
        owners[used[owners[used] < 0]] = transform_id
        transformed = np.asarray(transform.remap_uv(uv[used].copy()), np.float64)
        if transformed.shape != (len(used), 2) or not np.isfinite(transformed).all():
            raise ValueError("The atlas returned invalid UV coordinates.")
        if width == 2 and np.any(np.abs(transformed) > np.finfo(np.float16).max):
            raise ValueError("The atlas UV coordinates exceed the mesh's Float16 range.")
        uv_rows.append((destination, transformed))
        remapped_groups.append(destination[np.searchsorted(used, faces)])
    new_vc = len(source_rows)
    if max_vertices is not None and new_vc > max_vertices:
        raise ValueError(f"Atlas UV seams require {new_vc} vertices, exceeding the game's {max_vertices} vertex limit. Select a smaller graft.")

    layout_tree = {"m_VertexData": {"m_VertexCount": new_vc, "m_Channels": channels}}
    _, _, new_strides, new_starts, new_total = stream_layout(layout_tree)
    new_data = np.zeros(new_total, np.uint8)
    rows = np.asarray(source_rows, np.int64)
    for stream, stride in strides.items():
        source = original[starts[stream]:starts[stream] + vc * stride].reshape(vc, stride)
        destination = new_data[new_starts[stream]:new_starts[stream] + new_vc * stride].reshape(new_vc, stride)
        destination[:] = source[rows]
    uv_block = new_data[new_starts[uv_stream]:new_starts[uv_stream] + new_vc * new_strides[uv_stream]].reshape(new_vc, new_strides[uv_stream])
    for destination, transformed in uv_rows:
        uv_block[destination, uv_offset:uv_offset + width * 2] = np.ascontiguousarray(transformed, dtype=uv_dtype).view(np.uint8).reshape(-1, width * 2)

    legacy_skin = mesh_tree.get("m_Skin")
    if legacy_skin and len(legacy_skin) != vc:
        raise ValueError("The legacy skin-weight array does not match the vertex count.")
    new_shapes = _expanded_shapes(mesh_tree.get("m_Shapes"), duplicates, vc)
    faces = np.concatenate(remapped_groups)
    index_format = int(mesh_tree.get("m_IndexFormat", 0))
    if index_format not in (0, 1):
        raise ValueError("The mesh uses an unsupported index format.")
    if faces.size and int(faces.max()) > 65535:
        index_format = 1
    new_submesh = deepcopy(mesh_tree["m_SubMeshes"][0])
    first = int(faces.min()) if faces.size else 0
    last = int(faces.max()) if faces.size else -1
    new_submesh.update(firstByte=0, indexCount=int(faces.size), baseVertex=0,
                       topology=0, firstVertex=first, vertexCount=last - first + 1)
    if "localAABB" in new_submesh and mesh_tree.get("m_LocalAABB"):
        new_submesh["localAABB"] = deepcopy(mesh_tree["m_LocalAABB"])
    # No operation above mutates the caller's mesh, so every rejection is atomic.
    mesh_tree["m_VertexData"]["m_VertexCount"] = new_vc
    mesh_tree["m_VertexData"]["m_DataSize"] = new_data.tobytes()
    mesh_tree["m_IndexFormat"] = index_format
    mesh_tree["m_IndexBuffer"] = faces.astype("<u2" if index_format == 0 else "<u4").tobytes()
    mesh_tree["m_SubMeshes"] = [new_submesh]
    if legacy_skin:
        mesh_tree["m_Skin"] = [deepcopy(legacy_skin[i]) for i in source_rows]
    if "m_Shapes" in mesh_tree:
        mesh_tree["m_Shapes"] = new_shapes
    return {"source_submeshes": len(groups), "submeshes": 1,
            "vertices": new_vc, "split_vertices": len(duplicates),
            "triangles": len(faces), "index_format": index_format}
