"""Native layer-20 overlay materials and Unity's built-in plane."""

import math
from zlib import crc32

from . import model_viewer as viewer
from .mv_studio_stage_display import _shader_matches


# Authored MainCamera culling mask in the native live scene (level35).
_MAIN_CAMERA_MASK = 0x0C0BC013
_MATCAP_SHADER = (4078992641913009367, "cab-2700399fc9d3cc42e6ceeda597765088")

_MATERIAL_PROPERTIES = {
    crc32(b"_TintColor") & 0x0FFFFFFF: "overlayTint",
    crc32(b"_MainTex_ST") & 0x0FFFFFFF: "overlayUV",
}
_SOFT_BILLBOARD_COLOR = crc32(b"_Color") & 0x0FFFFFFF
_SOFT_BILLBOARD_SCALARS = {
    crc32(name.encode("ascii")) & 0x0FFFFFFF: name
    for name in ("_Density", "_MoveIntensity", "_AlphaAnimPower", "_AlphaAnimScale",
                 "_SizeStartX", "_SizeStartY", "_SizeEndX", "_SizeEndY", "_SizeRandom")
}


def material_channels(bindings, curves, width_of, *, world=False):
    """Decode built-in renderer material bindings with Unity's component nibble."""
    outputs, renderer_classes, count, offset = {}, {}, 0, 0
    for binding in bindings:
        width = width_of(binding)
        renderer_class = binding.get("typeID")
        if renderer_class in (23, 137) and (binding.get("customType"), binding.get("isPPtrCurve")) == (22, 0):
            attribute = binding["attribute"]
            property_hash = attribute & 0x0FFFFFFF
            kind = _MATERIAL_PROPERTIES.get(property_hash)
            property_name = None
            family, channel = divmod(attribute >> 28, 4)
            path = binding.get("path")
            if kind is None and world and renderer_class == 23:
                if binding.get("script") != {"m_FileID": 0, "m_PathID": 0}:
                    return [], 0
                if property_hash == _SOFT_BILLBOARD_COLOR and family == 0:
                    kind = "overlayColor"
                elif family == 2 and channel == 0:
                    property_name = _SOFT_BILLBOARD_SCALARS.get(property_hash)
                    if property_name is not None:
                        kind = "overlayScalar"
            elif (family not in (0, 1) or family == 1 and kind != "overlayTint"
                  or renderer_class == 137 and binding.get("script") != {"m_FileID": 0, "m_PathID": 0}):
                return [], 0
            if kind is None or width != 1 or not path:
                return [], 0
            if renderer_classes.setdefault(path, renderer_class) != renderer_class:
                return [], 0
            # Keep the scalar, vector and color families distinct until all
            # lanes of every property are present.
            components = outputs.setdefault((path, kind, property_name, family), {})
            if channel in components:
                return [], 0
            components[channel] = curves[offset]
            count += 1
        offset += width
    if (any(len(components) != (1 if kind == "overlayScalar" else 4)
            for (_, kind, _, _), components in outputs.items())
            or len({(path, kind, name) for path, kind, name, _ in outputs}) != len(outputs)):
        return [], 0
    channels = []
    for (path, kind, property_name, _), components in outputs.items():
        channel = {"path": path, "kind": kind, "curves": [components[index] for index in range(len(components))]}
        if property_name is not None:
            channel["property"] = property_name
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


def _is_matcap(material, tree):
    pointer = tree.get("m_Shader", {})
    if pointer.get("m_PathID") != _MATCAP_SHADER[0]:
        return False
    file_id = pointer.get("m_FileID")
    serialized = material.assets_file
    if type(file_id) is not int or not 0 <= file_id <= len(serialized.externals):
        return False
    path = serialized.externals[file_id - 1].path if file_id else serialized.name
    return path.replace("\\", "/").rsplit("/", 1)[-1].casefold() == _MATCAP_SHADER[1]


def _read_matcap(material, tree):
    """Read the inputs consumed by the fixed original MatCap pass."""
    queue = tree.get("m_CustomRenderQueue", -1)
    if (type(queue) is not int or queue != -1 and not 2501 <= queue <= 5000
            or tree.get("disabledShaderPasses") or tree.get("stringTagMap")):
        return None
    colors = viewer._properties(tree, "m_Colors")
    tint = [colors.get("_TintColor", {}).get(axis, 1) for axis in "rgba"]
    add_color = [colors.get("_AddColor", {}).get(axis, 0) for axis in "rgb"]
    if not all(type(value) in (int, float) and math.isfinite(value) for value in tint + add_color):
        return None
    pointer = viewer._properties(tree, "m_TexEnvs").get("_MainTex", {}).get("m_Texture", {})
    texture = None
    if pointer.get("m_PathID"):
        texture = viewer._ref(material, pointer)
        if texture is None or texture.type.name != "Texture2D":
            return None
    # The normal supplies UV, and old serialized blend/stencil keywords may
    # survive a shader change. The compiled MatCap pass fixes those states.
    return {"matcap": True, "texture": texture, "tint": tint, "addColor": add_color,
            "vertexColor": True, "cull": 2, "queue": 3000 if queue == -1 else queue,
            "depthTest": True, "alphaBlend": True}


def read_material(scene, original, *, world=False):
    if original is None or original.type.name != "Material":
        return None
    tree = scene.tree(original)
    if _is_matcap(original, tree):
        return _read_matcap(original, tree) if world else None
    if not _shader_matches(original, tree, "AS/General/Transparent"):
        return None
    floats = viewer._properties(tree, "m_Floats")
    flags = set(str(tree.get("m_ShaderKeywords", "")).split())
    cull, depth = floats.get("_CullMode", 0), floats.get("_ZTestMode", 4)
    destination = floats.get("_BlendDst", 1)
    depth_write = floats.get("_ZWriteParam", 0)
    comparison, reference = floats.get("_StencilComp", 8), floats.get("_StencilRef", 2)
    if (flags - {"_VERTEX_COLOR_ON"} or floats.get("_SATURATE") or cull not in (0, 1, 2)
            or depth not in (4, 8) or world and depth != 4 or depth_write not in (0, 1)
            or (floats.get("_BlendSrc", 5), floats.get("_StencilPassOp", 0),
                floats.get("_StencilZFailOp", 0)) != (5, 0, 0)):
        return None
    alpha_blend = (world and (destination, comparison) == (10, 3)
                   and type(reference) in (float, int) and 1 <= reference <= 255 and reference == int(reference))
    if not alpha_blend and (destination, comparison) != (1, 8):
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
    if depth_write:
        # The original vertex-colored additive floors participate in the
        # main transparent pass and write its depth, even at zero tint alpha.
        if (not world or alpha_blend or fields["queue"] != 3000 or texture is not None
                or not fields["vertexColor"]):
            return None
        fields["depthWrite"] = True
    if alpha_blend:
        fields.update(alphaBlend=True, stencilRef=int(reference))
    return fields


def _sort_bounds(tree, mesh, skinned):
    if tree is None or any(tree.get(field, 0) for field in
                           ("m_RendererPriority", "m_SortingLayerID", "m_SortingLayer", "m_SortingOrder")):
        return None
    fields = {}
    if skinned:
        # The skin's authored bounds are in its root bone's frame.
        root = tree.get("m_RootBone")
        joints = tree.get("m_Bones", ())
        if not root or root not in joints or tree.get("m_DirtyAABB"):
            return None
        fields["sortJoint"] = joints.index(root)
        center = tree.get("m_AABB", {}).get("m_Center", {})
        values = [center.get(axis) for axis in "xyz"]
    else:
        center = getattr(getattr(mesh, "m_LocalAABB", None), "m_Center", None)
        values = [getattr(center, axis, None) for axis in "xyz"]
    if any(type(value) not in (float, int) or not math.isfinite(value) for value in values):
        return None
    fields["sortCenter"] = [-values[0], values[1], values[2]]
    return fields


def export_material(materials, fields, *, renderer_tree=None, mesh=None, skinned=False):
    if fields is None:
        return None
    if fields.get("alphaBlend"):
        bounds = _sort_bounds(renderer_tree, mesh, skinned)
        if bounds is None:
            return None
        fields = {**fields, **bounds}
    texture = fields["texture"]
    return {**fields, "texture": materials.texture(texture) if texture is not None else None}


def material(scene, materials, original):
    return export_material(materials, read_material(scene, original))
