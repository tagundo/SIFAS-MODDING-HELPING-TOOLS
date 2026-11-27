"""Retain supported native stage shader inputs in the MV preview GLB."""
import math
import subprocess
import time

import numpy as np

from . import transient_failures
from .model_materials import _original_mips
from .model_viewer import MAX_TEXTURE_PIXELS, _key, _properties, _ref
from .mv_studio_stage_coloring import _path as _object_path


_SHADERS = {
    ("cab-fc0511ca63f2d94bbfe211260d08ddd1", -6509019661097744245): "stage",
    ("cab-31fad648db7286e0012ae8cc07024bff", -1043432931367049882): "solid",
    ("cab-618a998abe328b9a2b05b370a5907b3e", 8330475765356442367): "general",
    # AS/Blend/Opaque (shader06 of the stage shader set). Its only program,
    # with no keyword variants, reads both maps through their own _ST, COLOR
    # unconditionally, and fixes Blend One Zero, ZWrite On, ZTest LEqual.
    ("cab-f8a6d724e5bbefa191ed2e1f27102738", -3111404110691668338): "blend",
    # AS/General/TransparentCutout: its colour pass and its DEPTH pass discard
    # below _Cutoff without a keyword; Cull, ZWrite, ZTest and the stencil are
    # material floats.
    ("cab-ac0988328357841c205babac78d7cf4e", -6136900368392166873): "cutout",
    # Hidden/AS/Coloring/Opaque: fixed Blend One Zero, ZWrite On and ZTest
    # LEqual with Cull [_CullMode]; _PaletteTex (UV1 * _ColorIdTex_ST) scales
    # _TintColor, and UsePass "Hidden/AS/Depth/DEPTH" writes plain depth.
    ("cab-a82d81c63f90a9578a472659ba4c195f", -6110577314968069779): "coloring",
}
# Each shader's keyword space. Unity ignores a material keyword its shader
# does not declare, so only these select a compiled variant.
_KEYWORDS = {
    "stage": frozenset({
        "_ALPHATEST_ON", "_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA", "_ALPHA_TRANSPARENCY_MULTIPLY",
        "_ALPHA_TRANSPARENCY_VERTEX_ALPHA", "_CUBEMAP_BLEND_OP_ADD", "_CUBEMAP_BLEND_OP_ALPHA_BLEND",
        "_CUBEMAP_MODE_FRAGMENT", "_CUBEMAP_MODE_OFF", "_CUBEMAP_MODE_VERTEX", "_CUBEMAP_REFLECTIVITY_MAIN_TEX_ALPHA",
        "_CUBEMAP_REFLECTIVITY_MULTIPLY", "_CUBEMAP_REFLECTIVITY_VERTEX_ALPHA", "_FRESNEL_ON",
        "_PARALLAX_CORRECTED_CUBEMAP_ON", "_THIRD_TEX_MODE_DECAL", "_THIRD_TEX_MODE_EMISSIVE", "_THIRD_TEX_MODE_OFF"}),
    "cutout": frozenset({"PROCEDURAL_INSTANCING_ON", "SOFTPARTICLES_ON", "_SATURATE_ON", "_VERTEX_COLOR_ON"}),
    # _AUTO_PLAY_ON compiles to the same programs as its absence.
    "coloring": frozenset({"_AUTO_PLAY_ON", "_VERTEX_COLOR_ON"}),
}
# Tags { "Queue" } of each shader's subshader: TransparentCutout's AlphaTest,
# Geometry for every other shader above.
_SHADER_QUEUES = {"stage": 2000, "solid": 2000, "general": 2000, "blend": 2000, "cutout": 2450, "coloring": 2000}
# The shaders whose descriptor keeps its queue for the editor's pass state:
# a queue above 2500 draws in Unity's transparent order.
QUEUED_PASS_STATE = frozenset({"stage", "cutout", "coloring"})


def pass_queue(descriptor):
    """The descriptor's render queue (the opaque sort reads it for every kind);
    only the QUEUED_PASS_STATE kinds keep it in the exported descriptor."""
    return descriptor["queue"] if descriptor["shader"] in QUEUED_PASS_STATE else descriptor.pop("queue")


# AS/Blend/Opaque m_PropInfo defaults: _TintColor (1, 1, 1, 1), _AmbientColor
# (1, 1, 1, 0), _BlendRate Range(0, 1) = 0, and "white" for both 2D maps.
_BLEND_DEFAULTS = {"_TintColor": [1., 1., 1., 1.], "_AmbientColor": [1., 1., 1., 0.]}
_BLEND_MAPS = ("_MainTexA", "_MainTexB")
# _ALPHA_TRANSPARENCY: the alpha the variant tests against _Cutoff and multiplies by _TintColor.a.
_ALPHA_SOURCES = {"_ALPHA_TRANSPARENCY_VERTEX_ALPHA": "vertex", "_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA": "texture",
                  "_ALPHA_TRANSPARENCY_MULTIPLY": "multiply"}
_RIMLIGHT_DEPTH = ("cab-6cf8387efa4151b6220fceb9384d0e8e", 7983779172275908372)
_AMBIENT_SCRIPT = ("LiveCoreStageAmbient", "LLAS.Scene.Live.Components", "Assembly-CSharp.dll")
_MODEL_SCRIPT = ("LiveCoreStageModel", *_AMBIENT_SCRIPT[1:])
_EMISSIVE_SCRIPT = ("LiveCoreStageEmissive", *_AMBIENT_SCRIPT[1:])
_MAIN_STAGE = "/EntryPoint/Live/Stages/MainStage"
_COLOR_FIELDS = ("_AmbientColor", "_TintColor", "_BlendColor")
# AS/Stage reflection keywords. Every combination selects its own compiled
# variant: the cube direction per fragment or per vertex, optionally parallax
# corrected against _BoxMin/_BoxMax, a reflectivity from COLOR.a, _MainTex.a
# or both, an optional Schlick fresnel on it, and an add or alpha-blend op.
_CUBE_MODES = {"_CUBEMAP_MODE_FRAGMENT": "fragment", "_CUBEMAP_MODE_VERTEX": "vertex"}
_REFLECTION_OPS = {"_CUBEMAP_BLEND_OP_ADD": "add", "_CUBEMAP_BLEND_OP_ALPHA_BLEND": "alpha-blend"}
_REFLECTIVITY = {"_CUBEMAP_REFLECTIVITY_VERTEX_ALPHA": "vertex", "_CUBEMAP_REFLECTIVITY_MAIN_TEX_ALPHA": "texture",
                 "_CUBEMAP_REFLECTIVITY_MULTIPLY": "multiply"}
_CUBE_FORMATS = {34: "etc1", 32: "pvrtc4"}
_MAX_CUBE_SIZE = 256
MAIN_SAMPLERS, AUXILIARY_SAMPLERS, STATIC_OPAQUE_SAMPLERS = range(3)


def _numbers(value, axes):
    if not isinstance(value, dict):
        return None
    result = [value.get(axis) for axis in axes]
    return result if all(type(item) in (int, float) and math.isfinite(item) for item in result) else None


def _colors(tree):
    saved = _properties(tree, "m_Colors")
    return {field: result for field in _COLOR_FIELDS if (result := _numbers(saved.get(field), "rgba")) is not None}


def ambient_materials(scene, component, tree):
    materials = tree.get("materials")
    if not isinstance(materials, list) or not 0 < len(materials) <= 128 or not tree.get("m_Enabled", True):
        return {}, None
    script = _ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return {}, None
    script_tree = scene.tree(script)
    if tuple(script_tree.get(field) for field in ("m_ClassName", "m_Namespace", "m_AssemblyName")) != _AMBIENT_SCRIPT:
        return {}, None
    objects = [_ref(component, pointer) for pointer in materials if isinstance(pointer, dict)]
    if len(objects) != len(materials) or any(obj is None or obj.type.name != "Material" for obj in objects):
        return {}, None
    defaults = dict.fromkeys((_key(obj) for obj in objects), _colors(scene.tree(objects[0])))
    path = _object_path(scene, _ref(component, tree.get("m_GameObject")))
    binding = None
    if getattr(scene, "native_stage_effect", False):
        if len(path) == 1:
            binding = _MAIN_STAGE + "/Effect"
    elif len(path) == 3 and path[1] == "Ambient":
        binding = _MAIN_STAGE + "/Model/" + "/".join(path[1:])
    return defaults, binding


def _component_identity(scene, component, tree):
    script = _ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return None
    declaration = scene.tree(script)
    return tuple(declaration.get(field) for field in ("m_ClassName", "m_Namespace", "m_AssemblyName"))


def cubemap_model_ownership(scene, component, tree):
    """Resolve the Model root and the primary Ambient that receives quality."""
    if (getattr(scene, "native_stage_effect", False)
            or _component_identity(scene, component, tree) != _MODEL_SCRIPT):
        return False, None
    root = _ref(component, tree.get("m_GameObject"))
    if root is None or root.type.name != "GameObject" or len(_object_path(scene, root)) != 1:
        return False, None
    declarations = scene.tree(root).get("m_Component", ())
    if not any(_ref(root, entry.get("component")) is component for entry in declarations):
        return True, None
    receiver = _ref(component, tree.get("ambient"))
    if receiver is None or receiver.type.name != "MonoBehaviour":
        return True, None
    data = scene.tree(receiver)
    references = data.get("materials")
    if _component_identity(scene, receiver, data) != _AMBIENT_SCRIPT or not isinstance(references, list) or len(references) > 128:
        return True, None
    materials = [_ref(receiver, pointer) for pointer in references]
    if any(material is None or material.type.name != "Material" for material in materials):
        return True, None
    return True, {_key(material) for material in materials}


def emissive_materials(scene, component, tree):
    """Resolve the unique root receiver targeted by the stage model binding."""
    sources = tree.get("emissives")
    if (not isinstance(sources, list) or not 0 < len(sources) <= 128 or getattr(scene, "native_stage_effect", False)
            or _component_identity(scene, component, tree) != _MODEL_SCRIPT):
        return ()
    root = _ref(component, tree.get("m_GameObject"))
    if len(_object_path(scene, root)) != 1:
        return ()
    models, receivers = [], []
    for entry in scene.tree(root).get("m_Component", ()):
        node = _ref(root, entry.get("component"))
        if node is None or node.type.name != "MonoBehaviour":
            continue
        data = scene.tree(node)
        if _ref(node, data.get("m_GameObject")) is not root:
            continue
        identity = _component_identity(scene, node, data)
        if identity == _MODEL_SCRIPT:
            models.append(node)
        elif identity == _EMISSIVE_SCRIPT:
            receivers.append(node)
    if len(models) != 1 or models[0] is not component or len(receivers) != 1:
        return ()
    receiver = receivers[0]
    if not any(_ref(component, pointer) is receiver for pointer in sources):
        return ()
    materials = scene.tree(receiver).get("materials")
    if not isinstance(materials, list) or not 0 < len(materials) <= 128:
        return ()
    return {_key(material) for ref in materials
            if (material := _ref(receiver, ref)) is not None and material.type.name == "Material"}


def _shader_key(material, tree):
    pointer = tree.get("m_Shader", {})
    number = pointer.get("m_FileID")
    externals = material.assets_file.externals
    if type(number) is not int or not 1 <= number <= len(externals):
        return None
    cab = externals[number - 1].path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return cab, pointer.get("m_PathID")


def camera_depth(scene, material, renderer_tree, *, supports_cutout):
    """Resolve the known ShadowCaster pass independently of the color preview."""
    if renderer_tree.get("m_CastShadows") not in (0, 1, 2):
        return None
    tree = scene.tree(material)
    key = _shader_key(material, tree)
    queue = tree.get("m_CustomRenderQueue", -1)
    if ((key not in _SHADERS and key != _RIMLIGHT_DEPTH) or type(queue) is not int or not -1 <= queue <= 2500
            or tree.get("disabledShaderPasses")):
        return None
    # AS/Stage's DEPTH pass alpha-tests with _ALPHATEST_ON; TransparentCutout's always does.
    if (_SHADERS.get(key) == "stage" and "_ALPHATEST_ON" in tree.get("m_ShaderKeywords", "").split()
            or _SHADERS.get(key) == "cutout"):
        return {"kind": "cutout"} if supports_cutout else None
    return {"kind": "opaque"}


def _enum(floats, name, default, count):
    value = floats.get(name, default)
    if type(value) not in (int, float) or not math.isfinite(value) or value != int(value) or not 0 <= value < count:
        return None
    return int(value)


def _stencil(floats):
    """The float-bound stencil state: {} when it never tests nor writes, None when unreadable.

    Unity enums: CompareFunction (0 Disabled ... 8 Always) and StencilOp (0 Keep ... 7 DecrementWrap).
    """
    values = [_enum(floats, *field) for field in (("_StencilRef", 2, 256), ("_StencilComp", 8, 9),
                                                  ("_StencilPassOp", 0, 8), ("_StencilZFailOp", 0, 8))]
    if None in values:
        return None
    ref, comp, passing, failing = values
    if comp == 0 or (comp, passing, failing) == (8, 0, 0):
        return {}
    return {"stencil": {"ref": ref, "comp": comp, "pass": passing, "zfail": failing}}


def _stage_state(tree, floats):
    """AS/Stage binds Blend [_SrcBlend] [_DstBlend], ZWrite [_ZWrite] and the stencil to floats.

    The shader GUI's _BlendMode only writes those floats, the keywords and the
    queue; the pass reads the floats themselves.
    """
    source, target = _enum(floats, "_SrcBlend", 1, 11), _enum(floats, "_DstBlend", 0, 11)
    write, queue, stencil = _enum(floats, "_ZWrite", 1, 2), tree.get("m_CustomRenderQueue", -1), _stencil(floats)
    # UnityEngine.Rendering.BlendMode 9 (SrcAlphaSaturate) is a source factor only.
    if None in (source, target, write, stencil) or target == 9 or type(queue) is not int or not -1 <= queue <= 5000:
        return None
    state = {"queue": _SHADER_QUEUES["stage"] if queue == -1 else queue, **stencil}
    if (source, target) != (1, 0):
        state["blend"] = [source, target]
    if not write:
        state["depthWrite"] = False
    return state


def _cutout_state(tree, floats):
    """AS/General/TransparentCutout: Cull [_CullMode], ZWrite [_ZWriteParam], ZTest [_ZTestMode] and the stencil.

    Blend is fixed (One Zero). The float defaults are the shader's m_PropInfo
    values: Cull Off, ZWrite On, ZTest LEqual.
    """
    cull, write, test = _enum(floats, "_CullMode", 0, 3), _enum(floats, "_ZWriteParam", 1, 2), _enum(floats, "_ZTestMode", 4, 9)
    queue, stencil, cutoff = tree.get("m_CustomRenderQueue", -1), _stencil(floats), floats.get("_Cutoff", .5)
    if (None in (cull, write, test, stencil) or type(queue) is not int or not -1 <= queue <= 5000
            or type(cutoff) not in (int, float) or not math.isfinite(cutoff)):
        return None
    state = {"cull": cull, "queue": _SHADER_QUEUES["cutout"] if queue == -1 else queue, "alphaCutoff": cutoff, **stencil}
    if not write:
        state["depthWrite"] = False
    if test != 4:
        state["depthTest"] = test
    return state


def read_material(scene, material, ambient, single_ambient):
    if material is None or material.type.name != "Material":
        return None
    tree = scene.tree(material)
    mode = _SHADERS.get(_shader_key(material, tree))
    if mode is None:
        return None
    floats = _properties(tree, "m_Floats")
    keywords = set(tree.get("m_ShaderKeywords", "").split())
    if mode in _KEYWORDS:
        keywords &= _KEYWORDS[mode]
    state = {}
    if mode in ("stage", "cutout"):
        state = (_stage_state if mode == "stage" else _cutout_state)(tree, floats)
        if state is None:
            return None
    # AS/General/Opaque, AS/Blend/Opaque and Hidden/AS/Coloring/Opaque fix
    # blend and depth in their compiled passes. Serialized values for those
    # properties can survive a material shader swap.
    elif mode not in ("general", "blend", "coloring") and (
            floats.get("_SrcBlend", 1), floats.get("_DstBlend", 0), floats.get("_ZWrite", 1)) != (1, 0, 1):
        return None
    if mode in ("general", "solid", "blend") and (
            floats.get("_StencilComp", 8) != 8 or floats.get("_StencilPassOp", 0) != 0
            or floats.get("_StencilZFailOp", 0) != 0):
        return None
    colors = _colors(tree)
    if mode == "blend":
        # A property the material does not save reads the shader default.
        colors = {**_BLEND_DEFAULTS, **colors}
        colors.pop("_BlendColor", None)
    if "_TintColor" not in colors or mode != "solid" and "_AmbientColor" not in colors:
        return None
    identity = _key(material)
    cull = floats.get("_CullMode", 2) if mode != "stage" else 2
    if mode == "blend" and cull not in (0, 1, 2):
        return None
    meta = {"shader": mode, "colors": colors, "ambientDefaults": ambient.get(identity), "cull": cull}
    queue = tree.get("m_CustomRenderQueue", -1)
    if type(queue) is int and (queue == -1 or 0 <= queue <= 5000):
        # Unity draws the opaque queues (2500 and below) front to back.
        meta["queue"] = _SHADER_QUEUES[mode] if queue == -1 else queue
    if single := single_ambient.get(identity):
        meta["singleAmbientBinding"] = single
    if "_ALPHATEST_ON" in keywords:
        cutoff = floats.get("_Cutoff", 0.5)
        if mode != "stage" or type(cutoff) not in (int, float) or not 0 <= cutoff <= 1:
            return None
        meta["alphaCutoff"] = cutoff
    if mode == "solid":
        return meta
    if mode == "blend":
        rate = floats.get("_BlendRate", 0.)
        if type(rate) not in (int, float) or not math.isfinite(rate):
            return None
        envs = _properties(tree, "m_TexEnvs")
        transforms = []
        for name in _BLEND_MAPS:
            env = envs.get(name, {})
            scale, offset = _numbers(env.get("m_Scale", {"x": 1, "y": 1}), "xy"), _numbers(env.get("m_Offset", {"x": 0, "y": 0}), "xy")
            if scale is None or offset is None:
                return None
            transforms.append([*scale, offset[0], 1 - scale[1] - offset[1]])
        # The only program reads COLOR without a keyword; _VERTEX_COLOR_ON is
        # not one of this shader's keywords.
        return dict(meta, blendRate=float(rate), uvTransform=transforms[0], blendUVTransform=transforms[1],
                    vertexColor=True)
    env = _properties(tree, "m_TexEnvs").get("_MainTex", {})
    scale, offset = _numbers(env.get("m_Scale", {}), "xy"), _numbers(env.get("m_Offset", {}), "xy")
    if scale is None or offset is None:
        return None
    meta["uvTransform"] = [*scale, offset[0], 1 - scale[1] - offset[1]]
    if mode == "general":
        meta["vertexColor"] = "_VERTEX_COLOR_ON" in keywords
        return meta
    if mode == "cutout":
        # PROCEDURAL_INSTANCING_ON and SOFTPARTICLES_ON belong to its particle users.
        if keywords - {"_VERTEX_COLOR_ON", "_SATURATE_ON"} or not 0 <= state["alphaCutoff"] <= 1:
            return None
        meta.update(state, vertexColor="_VERTEX_COLOR_ON" in keywords)
        if "_SATURATE_ON" in keywords:
            meta["saturate"] = True
        return meta
    if mode == "coloring":
        # No component sets these materials' palette, so Unity binds the
        # property's "white" default: the palette lookup leaves _TintColor as is.
        palette = _properties(tree, "m_TexEnvs").get("_PaletteTex", {}).get("m_Texture") or {}
        cull, queue = _enum(floats, "_CullMode", 0, 3), tree.get("m_CustomRenderQueue", -1)
        if palette.get("m_PathID") or cull is None or type(queue) is not int or not -1 <= queue <= 5000:
            return None
        return dict(meta, cull=cull, queue=_SHADER_QUEUES["coloring"] if queue == -1 else queue,
                    vertexColor="_VERTEX_COLOR_ON" in keywords)
    third_modes = keywords & {"_THIRD_TEX_MODE_OFF", "_THIRD_TEX_MODE_EMISSIVE", "_THIRD_TEX_MODE_DECAL"}
    alpha = [source for name, source in _ALPHA_SOURCES.items() if name in keywords]
    if len(alpha) != 1 or len(third_modes) != 1 or "_THIRD_TEX_MODE_DECAL" in third_modes:
        return None
    meta.update(state)
    if alpha[0] != "texture":
        meta["alphaSource"] = alpha[0]
    modes = keywords & {"_CUBEMAP_MODE_OFF", "_CUBEMAP_MODE_FRAGMENT", "_CUBEMAP_MODE_VERTEX"}
    if len(modes) != 1:
        return None
    bias = floats.get("_MainTexMipmapBias", 0)
    if type(bias) not in (float, int) or not math.isfinite(bias) or "_BlendColor" not in colors:
        return None
    # The emissive third texture and the cube reflection are independent
    # keyword groups: their variants apply the reflection, then tint and
    # _BlendColor, then lerp to the emission by _EmissiveTex.r.
    reflection = "_CUBEMAP_MODE_OFF" not in modes
    emissive = "_THIRD_TEX_MODE_EMISSIVE" in third_modes
    return dict(meta, vertexColor=True, mipBias=bias, reflectionToggle=reflection, usesEmissive=emissive)


def export_emissive(scene, materials, material, controlled=False):
    tree = scene.tree(material)
    env = _properties(tree, "m_TexEnvs").get("_EmissiveTex", {})
    scale = _numbers(env.get("m_Scale"), "xy")
    offset = _numbers(env.get("m_Offset"), "xy")
    color = _numbers(_properties(tree, "m_Colors").get("_EmissiveColor"), "rgba")
    intensity = _properties(tree, "m_Floats").get("_EmissiveIntensity")
    texture = _ref(material, env.get("m_Texture"))
    if (scale is None or offset is None or color is None or type(intensity) not in (int, float)
            or not math.isfinite(intensity) or texture is None or texture.type.name != "Texture2D"):
        return None
    index = materials.texture(texture)
    if index is not None:
        result = {"texture": index, "color": color, "intensity": intensity,
                  "uvTransform": [*scale, offset[0], 1 - scale[1] - offset[1]]}
        if controlled:
            result["binding"] = _MAIN_STAGE + "/Model"
        collect_texture_sampler(materials, texture, result, "sampler")
        return result
    return None


def export_blend_maps(materials, material, descriptor):
    """Embed both AS/Blend/Opaque maps as authored. An unset map reads Unity's "white" default."""
    envs = _properties(materials.scene.tree(material), "m_TexEnvs")
    for name, field, sampler in (("_MainTexA", "mainTexture", "mainSampler"),
                                 ("_MainTexB", "blendTexture", "blendSampler")):
        pointer = envs.get(name, {}).get("m_Texture") or {}
        if not pointer.get("m_PathID"):
            descriptor[field] = None
            continue
        texture = _ref(material, pointer)
        if texture is None or texture.type.name != "Texture2D":
            return False
        descriptor[field] = materials.texture(texture)
        collect_texture_sampler(materials, texture, descriptor, sampler, priority=MAIN_SAMPLERS)
    return True


def opaque_sort_center(renderer_tree, mesh, position_matrix, *, builtin_mesh=False):
    """The renderer bounds centre Unity sorts opaque queues by, in the primitive's vertex frame.

    A MeshRenderer's world bounds are its mesh's local AABB under the
    renderer transform, so the box centre maps through the same matrix as the
    exported vertices (``position_matrix``, which also mirrors X).
    """
    if renderer_tree is None or any(renderer_tree.get(field, 0) for field in
                                    ("m_RendererPriority", "m_SortingLayerID", "m_SortingLayer", "m_SortingOrder")):
        return None
    if builtin_mesh:
        local = [0., 0., 0.]  # Unity's built-in Plane and Quad are centred on their origin.
    else:
        center = getattr(getattr(mesh, "m_LocalAABB", None), "m_Center", None)
        local = [getattr(center, axis, None) for axis in "xyz"]
    if any(type(value) not in (float, int) or not math.isfinite(value) for value in local):
        return None
    point = np.asarray(position_matrix, dtype=float) @ np.array([*local, 1.])
    return [float(value) for value in point[:3]] if np.isfinite(point).all() else None


def collect_main_sampler(scene, materials, material, descriptor, *, static_opaque=False):
    """Record the actual texture PPtr for each rendered stage primitive."""
    source = _properties(scene.tree(material), "m_TexEnvs").get("_MainTex", {})
    texture = _ref(material, source.get("m_Texture"))
    priority = STATIC_OPAQUE_SAMPLERS if static_opaque else MAIN_SAMPLERS
    collect_texture_sampler(materials, texture, descriptor, "mainSampler", priority=priority)


def collect_texture_sampler(materials, texture, descriptor, field, *, priority=None):
    if texture is None or texture.type.name != "Texture2D":
        return
    key = _key(texture)
    if materials.textures.get(key) is not None:
        if priority is None:
            priority = MAIN_SAMPLERS if field == "mainSampler" else AUXILIARY_SAMPLERS
        materials.stage_texture_samplers.setdefault(key, (texture, []))[1].append((descriptor, field, priority))


def _texture_sampler(materials, obj):
    texture = obj.read()
    settings = texture.m_TextureSettings
    filter_mode, anisotropy = settings.m_FilterMode, settings.m_Aniso
    if (type(filter_mode) is not int or filter_mode not in (0, 1, 2)
            or type(anisotropy) is not int or not 0 <= anisotropy <= 16
            or settings.m_MipBias != 0 or settings.m_WrapU not in (0, 1, 2)
            or settings.m_WrapV not in (0, 1, 2) or texture.m_ColorSpace != 1):
        return None
    width, height = texture.m_Width, texture.m_Height
    if texture.m_MipCount > 1 and (width & (width - 1) or height & (height - 1)):
        return None  # Explicit mip chains must also work on the WebGL1 path.
    mips = _original_mips(obj, texture, stage=True)
    if not mips and texture.m_MipCount != 1:
        return None
    missing = (mip.read() for mip in mips if _key(mip) not in materials.textures)
    additional_pixels = sum(level.m_Width * level.m_Height for level in missing)
    if additional_pixels + materials.pixels > MAX_TEXTURE_PIXELS:
        return None
    return {"mipmaps": materials.mip_textures(mips), "filterMode": filter_mode, "anisotropy": anisotropy}


def attach_texture_samplers(materials, deadline, *, priority):
    """Add complete chains for one priority group, including any shared roles."""
    glb, scene = materials.glb, materials.scene
    changed = False
    for source, bindings in materials.stage_texture_samplers.values():
        if min(level for _, _, level in bindings) != priority:
            continue
        if time.monotonic() >= deadline:
            transient_failures.note()  # a faster run would add the remaining chains
            break
        data_size, pixels, count = len(glb.data), materials.pixels, scene.stats["textures"]
        lengths = {name: len(glb.doc[name]) for name in ("bufferViews", "images", "samplers", "textures")}
        texture_indices = materials.textures.copy()
        try:
            sampler = _texture_sampler(materials, source)
        except (AttributeError, OSError, TypeError, ValueError, subprocess.SubprocessError) as error:
            transient_failures.note_if_environmental(error)
            # A missing or failed level must neither expose a partial chain nor
            # reserve texture budget needed by the next native source.
            del glb.data[data_size:]
            for name, length in lengths.items():
                del glb.doc[name][length:]
            materials.textures, materials.pixels = texture_indices, pixels
            scene.stats["textures"] = count
            continue
        if sampler is not None:
            for descriptor, field, _ in bindings:
                descriptor[field] = sampler
            changed = True
    return changed


def lightmap_for(scene, renderer, tree, lightmap_settings):
    index = tree.get("m_LightmapIndex")
    settings = lightmap_settings.get(id(renderer.assets_file))
    if settings is None or type(index) is not int or index < 0:
        return None
    maps = scene.tree(settings).get("m_Lightmaps")
    transform = _numbers(tree.get("m_LightmapTilingOffset"), "xyzw")
    if not isinstance(maps, list) or index >= len(maps) or transform is None:
        return None
    entry = maps[index]
    if not isinstance(entry, dict) or entry.get("m_DirLightmap", {}).get("m_PathID"):
        return None
    texture = _ref(settings, entry.get("m_Lightmap"))
    if texture is None or texture.type.name != "Texture2D":
        return None
    # These gamma-space mobile shaders use a 2x multiplier for dLDR maps.
    value = texture.read()
    if value.m_TextureFormat != 3 or value.m_LightmapFormat != 1:
        return None
    return texture, transform


def _cube_levels(size, format_name):
    for mip in range(size.bit_length()):
        side = size >> mip
        if format_name == "etc1":
            extent = side
            length = ((side + 3) // 4) ** 2 * 8
        else:
            # PVRTC stores at least two blocks in each dimension.
            extent = max(8, side)
            length = extent * extent // 2
        yield side, extent, length


def _cube_pixels(cube, remaining_pixels, deadline):
    from .decode import _stage_block_image

    side = cube.m_Width
    format_name = _CUBE_FORMATS.get(cube.m_TextureFormat)
    sampler = cube.m_TextureSettings
    if (format_name is None or type(side) is not int or not 8 <= side <= _MAX_CUBE_SIZE or side & (side - 1)
            or cube.m_Height != side or cube.m_ImageCount != 6 or cube.m_MipCount != side.bit_length()
            or cube.m_TextureDimension != 2 or cube.m_ColorSpace != 1 or cube.m_LightmapFormat != 0
            or sampler.m_FilterMode != 2 or sampler.m_MipBias != 0 or sampler.m_Aniso not in (0, 1)
            or any(getattr(sampler, "m_Wrap" + axis, None) != 1 for axis in "UVW")):
        return None
    levels = list(_cube_levels(side, format_name))
    face_length = sum(level[2] for level in levels)
    pixels = 6 * sum(extent * extent for extent, _, _ in levels)
    if (face_length != cube.m_CompleteImageSize or pixels > remaining_pixels
            or getattr(cube.m_StreamData, "size", 0) not in (0, face_length * 6)):
        return None
    source = cube.get_image_data()
    if len(source) != 6 * face_length:
        return None

    # Keep Unity's face-major +X,-X,+Y,-Y,+Z,-Z order and exact stored mip
    # rows. WebGL uploads these bytes directly, without a PNG Y flip.
    data = bytearray()
    cursor = 0
    for _ in range(6):
        for mip_side, extent, length in levels:
            raw = source[cursor:cursor + length]
            cursor += length
            with _stage_block_image(format_name, raw, extent, extent, deadline) as image:
                if extent == mip_side:
                    data.extend(image.tobytes())
                else:
                    with image.crop((0, 0, mip_side, mip_side)) as cropped:
                        data.extend(cropped.tobytes())
    return data, side, pixels


def reflection_variant(keywords):
    """The AS/Stage cube reflection variant a keyword set selects, or None."""
    keywords = set(keywords) & _KEYWORDS["stage"]
    picked = [[value for name, value in table.items() if name in keywords]
              for table in (_CUBE_MODES, _REFLECTION_OPS, _REFLECTIVITY)]
    if any(len(values) != 1 for values in picked) or "_CUBEMAP_MODE_OFF" in keywords:
        return None
    (mode,), (op,), (reflectivity,) = picked
    return {"mode": mode, "parallax": "_PARALLAX_CORRECTED_CUBEMAP_ON" in keywords, "op": op,
            "reflectivity": reflectivity, "fresnel": "_FRESNEL_ON" in keywords}


def export_reflection(scene, glb, materials, material, cube_cache):
    tree = scene.tree(material)
    variant = reflection_variant(tree.get("m_ShaderKeywords", "").split())
    if variant is None:
        return None
    vectors = {}
    if variant["parallax"]:
        # Only the parallax-corrected variants declare _BoxMin, _BoxMax and _CubemapPos.
        colors = _properties(tree, "m_Colors")
        vectors = {field: _numbers(colors.get(source), "rgb") for field, source in
                   (("boxMin", "_BoxMin"), ("boxMax", "_BoxMax"), ("origin", "_CubemapPos"))}
        if any(value is None for value in vectors.values()):
            return None
    cube_ref = _properties(tree, "m_TexEnvs").get("_Cube", {}).get("m_Texture")
    cube = _ref(material, cube_ref)
    if cube is None or cube.type.name != "Cubemap":
        return None
    key = _key(cube)
    if key not in cube_cache:
        try:
            result = _cube_pixels(cube.read(), MAX_TEXTURE_PIXELS - materials.pixels, scene.deadline)
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            # The decoders note their own failures; this catches a timeout or I/O error around them.
            transient_failures.note_if_environmental(error)
            result = None
        cube_cache[key] = None
        if result is not None:
            data, size, pixels = result
            cube_cache[key] = {"bufferView": glb.view(data), "size": size}
            materials.pixels += pixels
    data = cube_cache[key]
    return {**vectors, **data, **variant} if data is not None else None


def read_vertex_inputs(handler, output, count):
    color = np.asarray(handler.m_Colors, dtype=np.float32)
    channels = getattr(handler.src.m_VertexData, "m_Channels", ())
    if color.shape == (count, 4) and np.isfinite(color).all():
        normalization = ({0: 1, 1: 1, 2: 255}.get(channels[3].format)
                         if channels and len(channels) > 3 and channels[3].dimension else None)
        if normalization:
            output["color"] = color / normalization
    elif (len(channels) > 3 and not channels[3].dimension and not getattr(
            getattr(getattr(handler.src, "m_CompressedMesh", None), "m_Colors", None), "m_NumItems", 0)):
        # Neither the vertex streams nor the compressed data hold COLOR.
        output["colorAbsent"] = True
    uv = np.asarray(handler.m_UV1, dtype=np.float32)
    if uv.shape == (count, 2) and np.isfinite(uv).all():
        output["lightUV"] = uv
    if output.get("needsEmissiveUV"):
        uv = np.asarray(handler.m_UV2, dtype=np.float32)
        if uv.shape == (count, 2) and np.isfinite(uv).all():
            output["emissiveUV"] = uv
