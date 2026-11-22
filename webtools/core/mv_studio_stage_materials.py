"""Retain supported native stage shader inputs in the MV preview GLB."""
import math
import subprocess
import time

import numpy as np

from .model_materials import _original_mips
from .model_viewer import MAX_TEXTURE_PIXELS, _key, _properties, _ref
from .mv_studio_stage_coloring import _path as _object_path


_SHADERS = {
    ("cab-fc0511ca63f2d94bbfe211260d08ddd1", -6509019661097744245): "stage",
    ("cab-31fad648db7286e0012ae8cc07024bff", -1043432931367049882): "solid",
    ("cab-618a998abe328b9a2b05b370a5907b3e", 8330475765356442367): "general",
}
_AMBIENT_SCRIPT = ("LiveCoreStageAmbient", "LLAS.Scene.Live.Components", "Assembly-CSharp.dll")
_MODEL_SCRIPT = ("LiveCoreStageModel", *_AMBIENT_SCRIPT[1:])
_EMISSIVE_SCRIPT = ("LiveCoreStageEmissive", *_AMBIENT_SCRIPT[1:])
_MAIN_STAGE = "/EntryPoint/Live/Stages/MainStage"
_COLOR_FIELDS = ("_AmbientColor", "_TintColor", "_BlendColor")
_PARALLAX_REFLECTION = {"_CUBEMAP_MODE_FRAGMENT", "_PARALLAX_CORRECTED_CUBEMAP_ON"}
_REFLECTION_BLENDS = {
    ("_CUBEMAP_BLEND_OP_ALPHA_BLEND", "_CUBEMAP_REFLECTIVITY_VERTEX_ALPHA"): "vertex-alpha",
    ("_CUBEMAP_BLEND_OP_ADD", "_CUBEMAP_REFLECTIVITY_MAIN_TEX_ALPHA"): "add-texture-alpha",
    ("_CUBEMAP_BLEND_OP_ADD", "_CUBEMAP_REFLECTIVITY_VERTEX_ALPHA"): "add-vertex-alpha",
}
_CUBE_FORMATS = {34: "etc1", 32: "pvrtc4"}
_MAX_CUBE_SIZE = 256


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


def _shader(material, tree):
    pointer = tree.get("m_Shader", {})
    number = pointer.get("m_FileID")
    externals = material.assets_file.externals
    if type(number) is not int or not 1 <= number <= len(externals):
        return None
    cab = externals[number - 1].path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return _SHADERS.get((cab, pointer.get("m_PathID")))


def read_material(scene, material, ambient, single_ambient):
    if material is None or material.type.name != "Material":
        return None
    tree = scene.tree(material)
    mode = _shader(material, tree)
    if mode is None:
        return None
    floats = _properties(tree, "m_Floats")
    keywords = set(tree.get("m_ShaderKeywords", "").split())
    # AS/General/Opaque fixes blend and depth in its compiled passes.
    # Serialized values for those properties can survive a material shader swap.
    if mode != "general" and (floats.get("_SrcBlend", 1), floats.get("_DstBlend", 0), floats.get("_ZWrite", 1)) != (1, 0, 1):
        return None
    if (floats.get("_StencilComp", 8) != 8 or floats.get("_StencilPassOp", 0) != 0
            or floats.get("_StencilZFailOp", 0) != 0):
        return None
    colors = _colors(tree)
    if "_TintColor" not in colors or mode != "solid" and "_AmbientColor" not in colors:
        return None
    identity = _key(material)
    meta = {"shader": mode, "colors": colors, "ambientDefaults": ambient.get(identity),
            "cull": floats.get("_CullMode", 2) if mode != "stage" else 2}
    if single := single_ambient.get(identity):
        meta["singleAmbientBinding"] = single
    if "_ALPHATEST_ON" in keywords:
        cutoff = floats.get("_Cutoff", 0.5)
        if mode != "stage" or type(cutoff) not in (int, float) or not 0 <= cutoff <= 1:
            return None
        meta["alphaCutoff"] = cutoff
    if mode == "solid":
        return meta
    env = _properties(tree, "m_TexEnvs").get("_MainTex", {})
    scale, offset = _numbers(env.get("m_Scale", {}), "xy"), _numbers(env.get("m_Offset", {}), "xy")
    if scale is None or offset is None:
        return None
    meta["uvTransform"] = [*scale, offset[0], 1 - scale[1] - offset[1]]
    if mode == "general":
        meta["vertexColor"] = "_VERTEX_COLOR_ON" in keywords
        return meta
    third_modes = keywords & {"_THIRD_TEX_MODE_OFF", "_THIRD_TEX_MODE_EMISSIVE", "_THIRD_TEX_MODE_DECAL"}
    if ("_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA" not in keywords or len(third_modes) != 1
            or "_THIRD_TEX_MODE_DECAL" in third_modes):
        return None
    modes = keywords & {"_CUBEMAP_MODE_OFF", "_CUBEMAP_MODE_FRAGMENT", "_CUBEMAP_MODE_VERTEX"}
    if len(modes) != 1:
        return None
    bias = floats.get("_MainTexMipmapBias", 0)
    if type(bias) not in (float, int) or not math.isfinite(bias) or "_BlendColor" not in colors:
        return None
    reflection = "_CUBEMAP_MODE_OFF" not in modes
    emissive = "_THIRD_TEX_MODE_EMISSIVE" in third_modes
    if emissive and reflection:
        return None
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


def collect_main_sampler(scene, materials, material, descriptor):
    """Record the actual texture PPtr for each rendered stage primitive."""
    source = _properties(scene.tree(material), "m_TexEnvs").get("_MainTex", {})
    texture = _ref(material, source.get("m_Texture"))
    collect_texture_sampler(materials, texture, descriptor, "mainSampler")


def collect_texture_sampler(materials, texture, descriptor, field):
    if texture is None or texture.type.name != "Texture2D":
        return
    key = _key(texture)
    if materials.textures.get(key) is not None:
        materials.stage_texture_samplers.setdefault(key, (texture, []))[1].append((descriptor, field))


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


def attach_texture_samplers(materials, deadline, *, main):
    """Add complete chains for one priority group, including any shared roles."""
    glb, scene = materials.glb, materials.scene
    changed = False
    for source, bindings in materials.stage_texture_samplers.values():
        if any(field == "mainSampler" for _, field in bindings) != main:
            continue
        if time.monotonic() >= deadline:
            break
        data_size, pixels, count = len(glb.data), materials.pixels, scene.stats["textures"]
        lengths = {name: len(glb.doc[name]) for name in ("bufferViews", "images", "samplers", "textures")}
        texture_indices = materials.textures.copy()
        try:
            sampler = _texture_sampler(materials, source)
        except (AttributeError, OSError, TypeError, ValueError, subprocess.SubprocessError):
            # A missing or failed level must neither expose a partial chain nor
            # reserve texture budget needed by the next native source.
            del glb.data[data_size:]
            for name, length in lengths.items():
                del glb.doc[name][length:]
            materials.textures, materials.pixels = texture_indices, pixels
            scene.stats["textures"] = count
            continue
        if sampler is not None:
            for descriptor, field in bindings:
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


def export_reflection(scene, glb, materials, material, cube_cache):
    tree = scene.tree(material)
    keywords = set(tree.get("m_ShaderKeywords", "").split())
    if not _PARALLAX_REFLECTION <= keywords or "_FRESNEL_ON" in keywords:
        return None
    blends = {name for name in keywords if name.startswith(("_CUBEMAP_BLEND_OP_", "_CUBEMAP_REFLECTIVITY_"))}
    blend = _REFLECTION_BLENDS.get(tuple(sorted(blends)))
    if blend is None:
        return None
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
        except (ValueError, OSError, subprocess.TimeoutExpired):
            result = None
        cube_cache[key] = None
        if result is not None:
            data, size, pixels = result
            cube_cache[key] = {"bufferView": glb.view(data), "size": size}
            materials.pixels += pixels
    data = cube_cache[key]
    return {**vectors, **data, "blend": blend} if data is not None else None


def read_vertex_inputs(handler, output, count):
    color = np.asarray(handler.m_Colors, dtype=np.float32)
    if color.shape == (count, 4) and np.isfinite(color).all():
        channels = getattr(handler.src.m_VertexData, "m_Channels", ())
        normalization = ({0: 1, 1: 1, 2: 255}.get(channels[3].format)
                         if channels and len(channels) > 3 and channels[3].dimension else None)
        if normalization:
            output["color"] = color / normalization
    uv = np.asarray(handler.m_UV1, dtype=np.float32)
    if uv.shape == (count, 2) and np.isfinite(uv).all():
        output["lightUV"] = uv
    if output.get("needsEmissiveUV"):
        uv = np.asarray(handler.m_UV2, dtype=np.float32)
        if uv.shape == (count, 2) and np.isfinite(uv).all():
            output["emissiveUV"] = uv
