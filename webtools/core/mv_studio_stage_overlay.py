"""Native layer-20 overlay materials and Unity's built-in plane."""

import math
from zlib import crc32

from . import model_viewer as viewer
from .mv_studio_shader_identity import keywords as shader_keywords
from .mv_studio_stage_display import _shader_matches


# Authored MainCamera culling mask in the native live scene (level35).
_MAIN_CAMERA_MASK = 0x0C0BC013
_MATCAP_SHADER = (4078992641913009367, "cab-2700399fc9d3cc42e6ceeda597765088")

_MATERIAL_PROPERTIES = {
    crc32(b"_TintColor") & 0x0FFFFFFF: "overlayTint",
    crc32(b"_MainTex_ST") & 0x0FFFFFFF: "overlayUV",
}
_SOFT_BILLBOARD_COLOR = crc32(b"_Color") & 0x0FFFFFFF
# World MeshRenderer scalars: every float uniform of the AS/SoftParticleBillboard and AS/Smoke
# passes (MVStudioSoftBillboards holds them all), and AS/Blend/Opaque _BlendRate (the only
# shipped shader that declares it).
_WORLD_SCALARS = {
    crc32(name.encode("ascii")) & 0x0FFFFFFF: name
    for name in ("_Density", "_MoveIntensity", "_MoveSpeed", "_AlphaAnimPower", "_AlphaAnimScale",
                 "_SizeStartX", "_SizeStartY", "_SizeEndX", "_SizeEndY", "_SizeSpeed", "_SizeRandom", "_SizeAspect",
                 "_DensitySaturate", "_TextureRate", "_FadeOutPower", "_FadeOutScale", "_DistortionAmplitude",
                 "_DistortionSpeed", "_DistortionFreq", "_WaveAmplitude", "_WaveSpeed", "_WaveFreq",
                 "_FlowAmplitude", "_FlowSpeed", "_FlowFreq", "_CurveIntensity", "_CurvePower",
                 "_LightFlatness", "_LightSmoothness", "_BlendRate")
}
# AS/Blend/Opaque _AmbientColor (its .x-.w or .r-.a lanes, like _TintColor).
_AMBIENT_COLOR = crc32(b"_AmbientColor") & 0x0FFFFFFF
_NULL_SCRIPT = {"m_FileID": 0, "m_PathID": 0}
# Renderer classes whose material curves no preview material holds (ParticleSystemRenderer).
DROPPED_RENDERERS = frozenset({199})


def material_channels(bindings, curves, width_of, *, world=False, dropped=None):
    """Decode built-in renderer material bindings with Unity's component nibble.

    With a ``dropped`` list, a material property no preview material holds (an unknown property,
    an unexpected lane family, a property whose lanes are incomplete, or a renderer class in
    DROPPED_RENDERERS) is left out and recorded there instead of refusing every channel."""
    outputs, renderer_classes, count, offset, unknown = {}, {}, 0, 0, {}
    for binding in bindings:
        width = width_of(binding)
        renderer_class = binding.get("typeID")
        if (binding.get("customType"), binding.get("isPPtrCurve")) == (22, 0) and (
                renderer_class in (23, 137) or dropped is not None and renderer_class in DROPPED_RENDERERS):
            attribute = binding["attribute"]
            property_hash = attribute & 0x0FFFFFFF
            kind = _MATERIAL_PROPERTIES.get(property_hash) if renderer_class in (23, 137) else None
            property_name = None
            family, channel = divmod(attribute >> 28, 4)
            path = binding.get("path")
            # A renderer's material binding names no script (class 23's typed properties never did).
            scripted = binding.get("script") != _NULL_SCRIPT and (renderer_class != 23 or kind is None)
            if scripted or width != 1 or not path:
                return [], 0
            if renderer_classes.setdefault(path, renderer_class) != renderer_class:
                return [], 0
            if kind is None and world and renderer_class == 23:
                if property_hash == _SOFT_BILLBOARD_COLOR and family == 0:
                    kind = "overlayColor"
                elif property_hash == _AMBIENT_COLOR and family in (0, 1):
                    kind = "overlayAmbient"
                elif family == 2 and channel == 0:
                    property_name = _WORLD_SCALARS.get(property_hash)
                    if property_name is not None:
                        kind = "overlayScalar"
            elif kind is not None and (family not in (0, 1) or family == 1 and kind != "overlayTint"):
                kind = None
            if kind is None:
                if dropped is None:
                    return [], 0
                lanes = unknown.setdefault((path, property_hash, renderer_class), set())
                if (family, channel) in lanes:
                    return [], 0
                lanes.add((family, channel))
                count += 1
                offset += width
                continue
            # Keep the scalar, vector and color families distinct until all
            # lanes of every property are present.
            components = outputs.setdefault((path, kind, property_name, family), {})
            if channel in components:
                return [], 0
            components[channel] = curves[offset]
            count += 1
        offset += width
    if len({(path, kind, name) for path, kind, name, _ in outputs}) != len(outputs):
        return [], 0
    incomplete = [key for key, components in outputs.items()
                  if len(components) != (1 if key[1] == "overlayScalar" else 4)]
    if incomplete and dropped is None:
        return [], 0
    channels = []
    for (path, kind, property_name, family), components in outputs.items():
        if (path, kind, property_name, family) in incomplete:
            unknown.setdefault((path, None, renderer_classes[path]), set()).add(kind if property_name is None else property_name)
            continue
        channel = {"path": path, "kind": kind, "curves": [components[index] for index in range(len(components))]}
        if property_name is not None:
            channel["property"] = property_name
        if renderer_classes[path] == 137:
            channel["rendererClass"] = 137
        channels.append(channel)
    if dropped is not None:
        for (path, property_hash, renderer_class), lanes in unknown.items():
            row = {"path": path, "rendererClass": renderer_class}
            if property_hash is None:
                row["incomplete"] = sorted(lanes)
            else:
                row["propertyHash"] = property_hash
            dropped.append(row)
    return channels, count


def layer(scene, game_object):
    return scene.tree(game_object).get("m_Layer") == 20


def world_layer(scene, game_object):
    index = scene.tree(game_object).get("m_Layer")
    return type(index) is int and 0 <= index < 32 and bool(_MAIN_CAMERA_MASK & (1 << index))


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


# AS/General/Transparent binds every render state to a material float: Blend [_BlendSrc]
# [_BlendDst], Cull [_CullMode], ZWrite [_ZWriteParam], ZTest [_ZTestMode] and Stencil
# {Ref [_StencilRef] Comp [_StencilComp] Pass [_StencilPassOp] ZFail [_StencilZFailOp]}
# (Fail Keep, masks 255). (name, ShaderLab default, largest UnityEngine.Rendering value.)
_STATE_FLOATS = (("_BlendSrc", 5, 10), ("_BlendDst", 1, 10), ("_CullMode", 0, 2), ("_ZTestMode", 4, 8),
                 ("_ZWriteParam", 0, 1), ("_StencilComp", 8, 8), ("_StencilRef", 2, 255),
                 ("_StencilPassOp", 0, 7), ("_StencilZFailOp", 0, 7))
# Blends whose result does not depend on draw order (additive, multiplicative); any other
# blend is drawn in Unity's back-to-front transparent order (alphaBlend, with sort bounds).
_UNORDERED_BLENDS = frozenset({(0, 1), (1, 1), (5, 1), (2, 0), (0, 3)})
# The particle programs of the keyword space (procedural instancing, soft particles).
_PARTICLE_KEYWORDS = frozenset({"PROCEDURAL_INSTANCING_ON", "SOFTPARTICLES_ON"})


def _state(floats):
    values = []
    for name, default, high in _STATE_FLOATS:
        value = floats.get(name, default)
        if type(value) not in (int, float) or not math.isfinite(value) or value != int(value) or not 0 <= value <= high:
            return None
        values.append(int(value))
    return values


def read_material(scene, original, *, world=False, full=False):
    """The native transparent pass of an AS/General/Transparent (or world AS/MatCap/Transparent) material.

    ``full`` reads the whole property-bound pass state (blend, ZTest, ZWrite, stencil, cull) and the
    _SATURATE_ON program; without it only the original additive and stencil-masked alpha profiles the
    per-effect readers rely on are returned."""
    if original is None or original.type.name != "Material":
        return None
    tree = scene.tree(original)
    if _is_matcap(original, tree):
        return _read_matcap(original, tree) if world else None
    if not _shader_matches(original, tree, "AS/General/Transparent"):
        return None
    floats = viewer._properties(tree, "m_Floats")
    # Saved keywords outside the shader's keyword space select no program (mv_studio_shader_identity).
    flags = shader_keywords(original, tree)
    state = _state(floats)
    if state is None or flags & _PARTICLE_KEYWORDS or not full and flags - {"_VERTEX_COLOR_ON"}:
        return None
    source, destination, cull, depth, depth_write, comparison, reference, pass_op, zfail_op = state
    if not full:
        if (depth not in (4, 8) or world and depth != 4 or (source, pass_op, zfail_op) != (5, 0, 0)
                or not ((destination, comparison) == (1, 8)
                        or world and (destination, comparison) == (10, 3) and reference >= 1)):
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
    alpha_blend = (source, destination) not in _UNORDERED_BLENDS
    fields = {"texture": texture, "tint": tint, "uv": uv, "vertexColor": "_VERTEX_COLOR_ON" in flags,
              "cull": cull, "queue": 3000 if queue == -1 else queue}
    if depth == 4:
        fields["depthTest"] = True
    if depth_write:
        # The original vertex-colored additive floors participate in the
        # main transparent pass and write its depth, even at zero tint alpha.
        if not full and (not world or alpha_blend or fields["queue"] != 3000 or texture is not None
                         or not fields["vertexColor"]):
            return None
        fields["depthWrite"] = True
    if alpha_blend:
        fields["alphaBlend"] = True
    if comparison == 3 and (pass_op, zfail_op) == (0, 0):
        fields["stencilRef"] = reference
    if full:
        fields.update(blend=[source, destination], zTest=depth, stencil=[comparison, reference, pass_op, zfail_op])
        if "_SATURATE_ON" in flags:
            fields["saturate"] = True
    return fields


def _sort_bounds(tree, mesh, skinned=False, *, builtin_mesh=False):
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
    elif builtin_mesh:
        # Unity's built-in Plane (10209) and Quad (10210) are centered on their local origin.
        values = [0., 0., 0.]
    else:
        center = getattr(getattr(mesh, "m_LocalAABB", None), "m_Center", None)
        values = [getattr(center, axis, None) for axis in "xyz"]
    if any(type(value) not in (float, int) or not math.isfinite(value) for value in values):
        return None
    fields["sortCenter"] = [-values[0], values[1], values[2]]
    return fields


def export_material(materials, fields, *, renderer_tree=None, mesh=None, skinned=False, builtin_mesh=False,
                    overlay=False):
    if fields is None:
        return None
    # The layer-20 OverlayCamera is orthographic: its meshes keep their draw order by view depth.
    if not overlay and (fields.get("alphaBlend") or fields.get("depthWrite") and not skinned):
        bounds = _sort_bounds(renderer_tree, mesh, skinned, builtin_mesh=builtin_mesh)
        if bounds is not None:
            fields = {**fields, **bounds}
        elif fields.get("alphaBlend"):
            return None
    texture = fields["texture"]
    return {**fields, "texture": materials.texture(texture) if texture is not None else None}


def material(scene, materials, original, *, full=False):
    return export_material(materials, read_material(scene, original, full=full), overlay=full)
