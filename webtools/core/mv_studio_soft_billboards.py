"""Read authenticated native soft billboard passes used by stage effects."""

from pathlib import PurePosixPath

from . import model_viewer as viewer
from .mv_studio_stage_materials import _numbers


_SOFT_SHADER = ("cab-b214ce933be761e55a829d7470161d63", -1880739195722111294)
_SMOKE_SHADER = ("cab-c559ebedb55c9abf2ff34a672d5d7a6d", -5163972902431082470)
_FOG_FLOATS = {
    "_Density": (1, 0, 4),
    "_SizeStartX": (0, 0, 4),
    "_SizeStartY": (0, 0, 4),
    "_SizeEndX": (2, 0, 4),
    "_SizeEndY": (2, 0, 4),
    "_SizeSpeed": (1, 0, 4),
    "_SizeRandom": (.10000000149011612, 0, 1),
    "_SizeAspect": (1, 0, 2),
    "_AlphaAnimPower": (1, .001, 10),
    "_AlphaAnimScale": (.699999988079071, .5, 1),
    "_MoveIntensity": (.10000000149011612, 0, .5),
    "_MoveSpeed": (1, 0, 4),
}
_SMOKE_FLOATS = {
    "_Density": (1, 0, 4),
    "_DensitySaturate": (1, 0, 1),
    "_TextureRate": (.20000000298023224, 0, 1),
    "_FadeOutPower": (1, .001, 50),
    "_FadeOutScale": (4, 0, 50),
    "_DistortionAmplitude": (.10000000149011612, 0, 1),
    "_DistortionSpeed": (.20000000298023224, -1, 1),
    "_DistortionFreq": (8, 0, 20),
    "_WaveAmplitude": (.10000000149011612, 0, 1),
    "_WaveSpeed": (.10000000149011612, -1, 1),
    "_WaveFreq": (100, 0, 300),
    "_FlowAmplitude": (.10000000149011612, 0, 5),
    "_FlowSpeed": (.05000000074505806, -1, 1),
    "_FlowFreq": (1, 0, 10),
    "_CurveIntensity": (1, 0, 5),
    "_CurvePower": (1, .001, 5),
    "_LightFlatness": (.5, 0, 1),
    "_LightSmoothness": (1, 1, 4),
}
_STENCIL_FIELDS = {"comparison": "_StencilComp", "ref": "_StencilRef",
                   "pass": "_StencilPassOp", "zFail": "_StencilZFailOp"}
_FOG_STENCIL = {"comparison": 8, "ref": 2, "pass": 0, "zFail": 0}
_SMOKE_STENCIL = {"comparison": 6, "ref": 4, "pass": 2, "zFail": 0}


def _shader_key(material, tree):
    pointer = tree.get("m_Shader", {})
    reference = pointer.get("m_FileID")
    externals = material.assets_file.externals
    if type(reference) is not int or not 0 <= reference <= len(externals):
        return None
    file_path = externals[reference - 1].path if reference else material.assets_file.name
    cab = PurePosixPath(file_path.replace("\\", "/")).name.casefold()
    return cab, pointer.get("m_PathID")


def _main_texture(material, tree):
    env = viewer._properties(tree, "m_TexEnvs").get("_MainTex", {})
    size = _numbers(env.get("m_Scale", {"x": 1, "y": 1}), "xy")
    offset = _numbers(env.get("m_Offset", {"x": 0, "y": 0}), "xy")
    if size is None or offset is None:
        return None
    texture = viewer._ref(material, env.get("m_Texture"))
    if texture is None or texture.type.name != "Texture2D":
        return None
    return texture, [*size, *offset]


def read_material(scene, material):
    """Resolve the original shader, source texture and compiled uniforms."""
    if material is None or material.type.name != "Material":
        return None
    tree = scene.tree(material)
    queue = tree.get("m_CustomRenderQueue", -1)
    if tree.get("stringTagMap") or tree.get("disabledShaderPasses") or type(queue) is not int or queue not in (-1, 3000):
        return None
    shader = _shader_key(material, tree)
    keywords = set((tree.get("m_ShaderKeywords") or "").split())
    floats = viewer._properties(tree, "m_Floats")
    if shader == _SOFT_SHADER and not keywords:
        kind, parameters, stencil = "fog", _FOG_FLOATS, _FOG_STENCIL
    elif shader == _SMOKE_SHADER and keywords == {"_FADE_ON"} and floats.get("_FADE") == 1:
        kind, parameters, stencil = "smoke", _SMOKE_FLOATS, _SMOKE_STENCIL
    else:
        return None
    if any(floats.get(property_name, stencil[key]) != stencil[key]
           for key, property_name in _STENCIL_FIELDS.items()):
        return None

    values = {}
    for name, (default, low, high) in parameters.items():
        value = floats.get(name, default)
        if type(value) not in (float, int) or not low <= value <= high:
            return None
        values[name] = value
    colors = viewer._properties(tree, "m_Colors")
    rgba = _numbers(colors.get("_Color", dict.fromkeys("rgba", 1)), "rgba")
    sampled = _main_texture(material, tree)
    if rgba is None or sampled is None:
        return None
    texture, main_st = sampled
    values.update(_Color=rgba, _MainTex_ST=main_st)
    if kind == "smoke":
        light = _numbers(colors.get("_LightDirection", dict.fromkeys("rgba", 0)), "rgba")
        if light is None:
            return None
        values["_LightDirection"] = light
    return {"kind": kind, "texture": texture, "uniforms": values,
            "queue": 3000, "cull": 2, "stencil": dict(stencil), "alphaBlend": True,
            "depthTest": True, "depthWrite": False}
