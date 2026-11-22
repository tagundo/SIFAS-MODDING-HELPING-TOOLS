"""Native layer-20 overlay materials and Unity's built-in plane."""

import math
from zlib import crc32

from . import model_viewer as viewer
from .mv_studio_stage_display import _shader_matches


# Authored MainCamera culling mask in the native live scene (level35).
_MAIN_CAMERA_MASK = 0x0C0BC013

_MATERIAL_PROPERTIES = {
    crc32(b"_TintColor") & 0x0FFFFFFF: "overlayTint",
    crc32(b"_MainTex_ST") & 0x0FFFFFFF: "overlayUV",
}


def material_channels(bindings, curves, width_of):
    """Decode built-in renderer material bindings with Unity's component nibble."""
    outputs, renderer_classes, count, offset = {}, {}, 0, 0
    for binding in bindings:
        width = width_of(binding)
        renderer_class = binding.get("typeID")
        if renderer_class in (23, 137) and (binding.get("customType"), binding.get("isPPtrCurve")) == (22, 0):
            attribute = binding["attribute"]
            kind = _MATERIAL_PROPERTIES.get(attribute & 0x0FFFFFFF)
            family, channel = divmod(attribute >> 28, 4)
            path = binding.get("path")
            if (kind is None or width != 1 or not path or family not in (0, 1)
                    or family == 1 and kind != "overlayTint"
                    or renderer_class == 137 and binding.get("script") != {"m_FileID": 0, "m_PathID": 0}):
                return [], 0
            if renderer_classes.setdefault(path, renderer_class) != renderer_class:
                return [], 0
            # Unity identifies both a four-channel vector and an animated
            # material color. Keep the families separate until all lanes exist.
            components = outputs.setdefault((path, kind, family), {})
            if channel in components:
                return [], 0
            components[channel] = curves[offset]
            count += 1
        offset += width
    if (any(len(components) != 4 for components in outputs.values())
            or len({(path, kind) for path, kind, _ in outputs}) != len(outputs)):
        return [], 0
    channels = []
    for (path, kind, _), components in outputs.items():
        channel = {"path": path, "kind": kind, "curves": [components[index] for index in range(4)]}
        if renderer_classes[path] == 137:
            channel["rendererClass"] = 137
        channels.append(channel)
    return channels, count


def layer(scene, game_object):
    return scene.tree(game_object).get("m_Layer") == 20


def world_layer(scene, game_object):
    index = scene.tree(game_object).get("m_Layer")
    return type(index) is int and 0 <= index < 32 and bool(_MAIN_CAMERA_MASK & (1 << index))


def builtin_plane(scene, game_object):
    """Recognize the exact external Unity default-resource Mesh Plane pointer."""
    tree = scene.tree(game_object)
    for entry in tree.get("m_Component", []):
        mesh_filter = viewer._ref(game_object, entry.get("component"))
        if mesh_filter is None or mesh_filter.type.name != "MeshFilter":
            continue
        pointer = scene.tree(mesh_filter).get("m_Mesh", {})
        file_id = pointer.get("m_FileID", 0)
        externals = mesh_filter.assets_file.externals
        if pointer.get("m_PathID") == 10209 and 0 < file_id <= len(externals):
            return externals[file_id - 1].path.replace("\\", "/").lower() == "library/unity default resources"
    return False


def plane_geometry():
    """Recreate the 10 m XZ plane with Unity's 11x11 UV lattice in glTF coordinates."""
    import numpy as np

    vertices = np.asarray([(u - 5, 0, 5 - v) for v in range(11) for u in range(11)], dtype=np.float32)
    normals = np.tile(np.asarray([0, 1, 0], dtype=np.float32), (121, 1))
    uv = np.asarray([(u / 10, 1 - v / 10) for v in range(11) for u in range(11)], dtype=np.float32)
    triangles = []
    for row in range(10):
        for column in range(10):
            base = row * 11 + column
            triangles.extend(((base, base + 12, base + 11), (base, base + 1, base + 12)))
    return "Plane", vertices, normals, uv, [np.asarray(triangles, dtype=np.int64)]


def read_material(scene, original):
    if original is None or original.type.name != "Material":
        return None
    tree = scene.tree(original)
    if not _shader_matches(original, tree, "AS/General/Transparent"):
        return None
    floats = viewer._properties(tree, "m_Floats")
    flags = set(str(tree.get("m_ShaderKeywords", "")).split())
    cull, depth = floats.get("_CullMode", 0), floats.get("_ZTestMode", 4)
    if (flags - {"_VERTEX_COLOR_ON"} or floats.get("_SATURATE") or cull not in (0, 1, 2) or depth not in (4, 8) or
            (floats.get("_BlendSrc", 5), floats.get("_BlendDst", 1), floats.get("_ZWriteParam", 0),
             floats.get("_StencilComp", 8), floats.get("_StencilPassOp", 0), floats.get("_StencilZFailOp", 0))
            != (5, 1, 0, 8, 0, 0)):
        return None
    values = viewer._properties(tree, "m_Colors")
    tint = [values.get("_TintColor", {}).get(axis, 1) for axis in "rgba"]
    main = viewer._properties(tree, "m_TexEnvs").get("_MainTex", {})
    uv = [main.get("m_Scale", {}).get(axis, 1) for axis in "xy"] + [
        main.get("m_Offset", {}).get(axis, 0) for axis in "xy"]
    queue = tree.get("m_CustomRenderQueue", -1)
    if type(queue) is not int or not all(type(value) in (int, float) and math.isfinite(value) for value in tint + uv):
        return None
    texture = None
    pointer = main.get("m_Texture", {})
    if pointer.get("m_PathID"):
        texture = viewer._ref(original, pointer)
        if texture is None or texture.type.name != "Texture2D":
            return None
    fields = {"texture": texture, "tint": tint, "uv": uv, "vertexColor": "_VERTEX_COLOR_ON" in flags,
              "cull": int(cull), "queue": 3000 if queue == -1 else queue}
    if depth == 4:
        fields["depthTest"] = True
    return fields


def export_material(materials, fields):
    if fields is None:
        return None
    texture = fields["texture"]
    return {**fields, "texture": materials.texture(texture) if texture is not None else None}


def material(scene, materials, original):
    return export_material(materials, read_material(scene, original))
