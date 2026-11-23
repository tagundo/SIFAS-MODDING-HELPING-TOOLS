"""Read the screen materials referenced by the native stage display component."""

import math

from . import model_viewer as viewer
from .mv_studio_shader_identity import KNOWN, matches
from .mv_studio_stage_coloring import _path


_STAGE = "/EntryPoint/Live/Stages/MainStage/Effect/"
# (path ID, CAB) of the shared shader bundle copies, derived from the one verified
# table; the per-effect stage readers match a material's shader pointer against it.
_SHADERS = {name: (path_id, cab) for (cab, path_id), name in KNOWN.items()
            if name in ("AS/General/Opaque", "AS/General/Transparent")}


def _shader_matches(material, tree, name):
    # Shader identity is the ShaderLab name (an embedded copy counts as the shader).
    return matches(material, tree, name)


def binding(scene, component, tree):
    if not tree.get("m_Enabled"):
        return None
    script = viewer._ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return None
    identity = scene.tree(script)
    if tuple(identity.get(key) for key in ("m_AssemblyName", "m_Namespace", "m_ClassName")) != (
            "Assembly-CSharp.dll", "LLAS.Scene.Live.Components", "LiveCoreStageDisplay"):
        return None
    game = viewer._ref(component, tree.get("m_GameObject"))
    renderer = viewer._ref(component, tree.get("renderer"))
    fallback = viewer._ref(component, tree.get("material2DReference"))
    references = tree.get("materialReferences", [])
    names = _path(scene, game)
    if (len(names) < 2 or renderer is None or renderer.type.name != "MeshRenderer" or
            fallback is None or not isinstance(references, list) or not 0 < len(references) <= 16):
        return None
    source_game = viewer._ref(renderer, scene.tree(renderer).get("m_GameObject"))
    if source_game is None or _path(scene, source_game)[:len(names)] != names:
        return None
    variants = [(viewer._ref(component, row.get("bgMaterial")), viewer._ref(component, row.get("logoMaterial")))
                for row in references]
    return viewer._key(renderer), (_STAGE + "/".join(names[1:]), fallback, variants)


def _material(scene, materials, material, transparent):
    if material is None or material.type.name != "Material":
        return None
    tree = scene.tree(material)
    keywords = set((tree.get("m_ShaderKeywords") or "").split())
    if (keywords and (transparent or keywords != {"_VERTEX_COLOR_ON"})) or not _shader_matches(
            material, tree, "AS/General/Transparent" if transparent else "AS/General/Opaque"):
        return None
    vertex_color = bool(keywords)
    floats = viewer._properties(tree, "m_Floats")
    vertex_color_property = floats.get("_VERTEX_COLOR", 0)
    if (vertex_color_property and (not vertex_color or vertex_color_property != 1)) or floats.get("_SATURATE"):
        return None
    cull, queue = floats.get("_CullMode", 0), tree.get("m_CustomRenderQueue", -1)
    stencil = (floats.get("_StencilComp", 8), floats.get("_StencilRef", 2),
               floats.get("_StencilPassOp", 0), floats.get("_StencilZFailOp", 0))
    # The opaque backgrounds write the reference on pass; some (12035, 12036)
    # also replace it when the depth test fails (_StencilZFailOp 2).
    if (cull not in (0, 1, 2) or type(queue) is not int or
            stencil[:3] != (8, 2, 0 if transparent else 2) or stencil[3] not in ((0,) if transparent else (0, 2))):
        return None
    if transparent and (floats.get("_BlendSrc", 5), floats.get("_BlendDst", 1),
                        floats.get("_ZTestMode", 4), floats.get("_ZWriteParam", 0)) != (5, 10, 4, 0):
        return None
    if not transparent and floats.get("_ZWrite", 1) != 1:
        return None
    colors = viewer._properties(tree, "m_Colors")
    tint = [colors.get("_TintColor", {}).get(axis, 1) for axis in "rgba"]
    ambient = [colors.get("_AmbientColor", {}).get(axis, 1 if axis != "a" else 0) for axis in "rgba"]
    env = viewer._properties(tree, "m_TexEnvs").get("_MainTex", {})
    tex_st = [env.get("m_Scale", {}).get(axis, 1) for axis in "xy"] + [
        env.get("m_Offset", {}).get(axis, 0) for axis in "xy"]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in [*tint, *ambient, *tex_st]):
        return None
    texture = None
    pointer = env.get("m_Texture", {})
    if pointer.get("m_PathID"):
        original = viewer._ref(material, pointer)
        if original is None or original.type.name != "Texture2D":
            return None
        texture = materials.texture(original)
    fields = {"texture": texture, "uv": tex_st, "tint": tint, "ambient": ambient, "cull": cull,
              "stencil": int(stencil[1]), "stencilZFail": int(stencil[3]),
              "queue": (3000 if transparent else 2000) if queue == -1 else queue}
    if vertex_color:
        fields["vertexColor"] = True
    return fields


def export(scene, materials, binding):
    target, original, references = binding
    fallback = _material(scene, materials, original, False)
    if fallback is None:
        return None
    variants = []
    for background, logo in references:
        bg = _material(scene, materials, background, False)
        fg = _material(scene, materials, logo, True) if logo is not None else None
        if bg is None or (logo is not None and fg is None):
            return None
        variants.append({"background": bg, "logo": fg})
    return {"target": target, "fallback": fallback, "variants": variants}
