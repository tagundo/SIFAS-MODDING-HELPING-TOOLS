"""Retain supported native stage shader inputs in the MV preview GLB."""
import math

import numpy as np

from .model_viewer import _key, _properties, _ref


_SHADERS = {
    ("cab-fc0511ca63f2d94bbfe211260d08ddd1", -6509019661097744245): "stage",
    ("cab-31fad648db7286e0012ae8cc07024bff", -1043432931367049882): "solid",
    ("cab-618a998abe328b9a2b05b370a5907b3e", 8330475765356442367): "general",
}
_AMBIENT_SCRIPT = ("LiveCoreStageAmbient", "LLAS.Scene.Live.Components", "Assembly-CSharp.dll")
_COLOR_FIELDS = ("_AmbientColor", "_TintColor", "_BlendColor")


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
        return {}
    script = _ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return {}
    script_tree = scene.tree(script)
    if tuple(script_tree.get(field) for field in ("m_ClassName", "m_Namespace", "m_AssemblyName")) != _AMBIENT_SCRIPT:
        return {}
    objects = [_ref(component, pointer) for pointer in materials if isinstance(pointer, dict)]
    if len(objects) != len(materials) or any(obj is None or obj.type.name != "Material" for obj in objects):
        return {}
    return dict.fromkeys((_key(obj) for obj in objects), _colors(scene.tree(objects[0])))


def _shader(material, tree):
    pointer = tree.get("m_Shader", {})
    number = pointer.get("m_FileID")
    externals = material.assets_file.externals
    if type(number) is not int or not 1 <= number <= len(externals):
        return None
    cab = externals[number - 1].path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return _SHADERS.get((cab, pointer.get("m_PathID")))


def read_material(scene, material, ambient):
    if material is None or material.type.name != "Material":
        return None
    tree = scene.tree(material)
    mode = _shader(material, tree)
    if mode is None:
        return None
    floats = _properties(tree, "m_Floats")
    keywords = set(tree.get("m_ShaderKeywords", "").split())
    if (floats.get("_SrcBlend", 1) != 1 or floats.get("_DstBlend", 0) != 0 or floats.get("_ZWrite", 1) != 1
            or floats.get("_StencilComp", 8) != 8 or floats.get("_StencilPassOp", 0) != 0
            or floats.get("_StencilZFailOp", 0) != 0 or "_ALPHATEST_ON" in keywords):
        return None
    colors = _colors(tree)
    if "_TintColor" not in colors or mode != "solid" and "_AmbientColor" not in colors:
        return None
    meta = {"shader": mode, "colors": colors, "ambientDefaults": ambient.get(_key(material)),
            "cull": floats.get("_CullMode", 2) if mode != "stage" else 2}
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
    if not {"_ALPHA_TRANSPARENCY_MAIN_TEX_ALPHA", "_THIRD_TEX_MODE_OFF"} <= keywords:
        return None
    modes = keywords & {"_CUBEMAP_MODE_OFF", "_CUBEMAP_MODE_FRAGMENT", "_CUBEMAP_MODE_VERTEX"}
    if len(modes) != 1:
        return None
    bias = floats.get("_MainTexMipmapBias", 0)
    if type(bias) not in (float, int) or not math.isfinite(bias) or "_BlendColor" not in colors:
        return None
    return dict(meta, vertexColor=True, mipBias=bias, reflectionToggle="_CUBEMAP_MODE_OFF" not in modes)


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
