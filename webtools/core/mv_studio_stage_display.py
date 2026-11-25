"""Read the screen materials referenced by the native stage display component.

LiveCoreStageDisplay (GL 3.12.0 libil2cpp) switches the screen renderer between
its materialReferences one variant at a time: LiveDisplayMixer.PostProcess calls
ApplyMaterialIndex with the last processed clip's materialIndex (0 when no clip
is active), which sets renderer.sharedMaterials = [bgMaterial, logoMaterial] of
materialReferences[clamp(index, 0, count - 1)] and nothing else; then it writes
_AmbientColor and _MainTex_ST (the variant's scale, scroll speed x director time
as the offset) into that bg material.

Initialize(enabled) leaves the renderer's own materials in place while the stage
display is enabled; only a disabled display shows material2DReference (and a
display without one is forced enabled).
"""

import math

from . import model_viewer as viewer
from .mv_studio_shader_identity import KNOWN, matches, name as shader_name
from .mv_studio_stage_coloring import _path


_STAGE = "/EntryPoint/Live/Stages/MainStage/Effect/"
# (path ID, CAB) of the shared shader bundle copies, derived from the one verified
# table; the per-effect stage readers match a material's shader pointer against it.
_SHADERS = {name: (path_id, cab) for (cab, path_id), name in KNOWN.items()
            if name in ("AS/General/Opaque", "AS/General/Transparent")}

_OPAQUE, _TRANSPARENT = "AS/General/Opaque", "AS/General/Transparent"
# Keywords that select a program of each shader (its GLES3 keyword space); any other
# saved keyword has no effect in Unity. SOFTPARTICLES_ON and PROCEDURAL_INSTANCING_ON
# select particle programs the screens never use, so a material that sets them is refused.
_KEYWORDS = {_OPAQUE: {"_VERTEX_COLOR_ON"}, _TRANSPARENT: {"_VERTEX_COLOR_ON", "_SATURATE_ON"}}
_PARTICLE_KEYWORDS = {"SOFTPARTICLES_ON", "PROCEDURAL_INSTANCING_ON"}
# ShaderLab queue tags: Geometry for AS/General/Opaque, Transparent for AS/General/Transparent.
_QUEUES = {_OPAQUE: 2000, _TRANSPARENT: 3000}


class Unsupported(ValueError):
    """A display material the editor cannot draw; the message says why."""


def _shader_matches(material, tree, name):
    # Shader identity is the ShaderLab name (an embedded copy counts as the shader).
    return matches(material, tree, name)


def _class(scene, component, tree):
    script = viewer._ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return None
    identity = scene.tree(script)
    if tuple(identity.get(key) for key in ("m_AssemblyName", "m_Namespace")) != (
            "Assembly-CSharp.dll", "LLAS.Scene.Live.Components"):
        return None
    return identity.get("m_ClassName")


def binding(scene, component, tree):
    if not tree.get("m_Enabled"):
        return None
    if _class(scene, component, tree) != "LiveCoreStageDisplay":
        return None
    game = viewer._ref(component, tree.get("m_GameObject"))
    renderer = viewer._ref(component, tree.get("renderer"))
    fallback = viewer._ref(component, tree.get("material2DReference"))
    references = tree.get("materialReferences", [])
    names = _path(scene, game)
    # A display without material2DReference stays enabled (Initialize logs it and forces it on).
    # With no reference, ApplyMaterialIndex throws before it changes the renderer: nothing to switch.
    if (len(names) < 2 or renderer is None or renderer.type.name != "MeshRenderer" or
            not isinstance(references, list) or not 0 < len(references) <= 16):
        return None
    source_game = viewer._ref(renderer, scene.tree(renderer).get("m_GameObject"))
    if source_game is None or _path(scene, source_game)[:len(names)] != names:
        return None
    variants = [(viewer._ref(component, row.get("bgMaterial")), viewer._ref(component, row.get("logoMaterial")))
                for row in references]
    return viewer._key(renderer), (_STAGE + "/".join(names[1:]), fallback, variants, renderer)


def _finite(values):
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise Unsupported("a colour or texture transform is not finite")
    return values


def _integer(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value != int(value) or not low <= value <= high:
        raise Unsupported(f"{label} {value!r} is not a render state")
    return int(value)


def _color(colors, key, default):
    color = colors.get(key)
    return _finite([color.get(axis, default[index]) for index, axis in enumerate("rgba")] if isinstance(color, dict)
                   else list(default))


def _texture(materials, material, envs, key):
    env = envs.get(key) or {}
    uv = _finite([env.get("m_Scale", {}).get(axis, 1) for axis in "xy"] +
                 [env.get("m_Offset", {}).get(axis, 0) for axis in "xy"])
    pointer = env.get("m_Texture") or {}
    if not pointer.get("m_PathID"):
        return None, uv  # Unity binds the property default, "white".
    original = viewer._ref(material, pointer)
    if original is None or original.type.name != "Texture2D":
        raise Unsupported(f"{key} is not an available Texture2D")
    try:
        return materials.texture(original), uv
    except ValueError as error:
        raise Unsupported(f"{key} could not be decoded ({error})") from None


def _stencil(floats):
    return {"stencil": _integer(floats.get("_StencilRef", 2), 0, 255, "_StencilRef"),
            "stencilComp": _integer(floats.get("_StencilComp", 8), 0, 8, "_StencilComp"),
            "stencilPass": _integer(floats.get("_StencilPassOp", 0), 0, 7, "_StencilPassOp"),
            "stencilZFail": _integer(floats.get("_StencilZFailOp", 0), 0, 7, "_StencilZFailOp")}


def _identity(material):
    """The Material asset: LiveDisplayMixer writes into it, so every screen drawing it shows the last write."""
    source = getattr(getattr(material, "assets_file", None), "name", "")
    return f"{source}:{getattr(material, 'path_id', id(material))}"


def read(scene, materials, material):
    """Export one display material by its shader's own program; raise Unsupported otherwise."""
    if material is None or material.type.name != "Material":
        raise Unsupported("the material is missing")
    tree = scene.tree(material)
    shader = shader_name(material, tree)
    if shader not in _KEYWORDS:
        raise Unsupported(f"shader {shader or 'unknown'} has no display reader")
    keywords = set((tree.get("m_ShaderKeywords") or "").split())
    if keywords & _PARTICLE_KEYWORDS:
        raise Unsupported(f"particle keywords {sorted(keywords & _PARTICLE_KEYWORDS)}")
    keywords &= _KEYWORDS[shader]
    floats = viewer._properties(tree, "m_Floats")
    colors = viewer._properties(tree, "m_Colors")
    envs = viewer._properties(tree, "m_TexEnvs")
    queue = tree.get("m_CustomRenderQueue", -1)
    if type(queue) is not int or not -1 <= queue <= 5000:
        raise Unsupported(f"render queue {queue!r}")
    texture, uv = _texture(materials, material, envs, "_MainTex")
    fields = {"material": _identity(material), "texture": texture, "uv": uv,
              "tint": _color(colors, "_TintColor", (1, 1, 1, 1)),
              "queue": _QUEUES[shader] if queue == -1 else queue, **_stencil(floats)}
    if shader == _TRANSPARENT:
        fields.update(kind="transparent", cull=_integer(floats.get("_CullMode", 0), 0, 2, "_CullMode"),
                      blend=[_integer(floats.get("_BlendSrc", 5), 0, 10, "_BlendSrc"),
                             _integer(floats.get("_BlendDst", 1), 0, 10, "_BlendDst")],
                      zTest=_integer(floats.get("_ZTestMode", 4), 0, 8, "_ZTestMode"),
                      zWrite=_integer(floats.get("_ZWriteParam", 0), 0, 1, "_ZWriteParam") == 1)
        if "_SATURATE_ON" in keywords:
            fields["saturate"] = True
    else:
        fields["ambient"] = _color(colors, "_AmbientColor", (1, 1, 1, 0))
    if shader == _OPAQUE:
        fields.update(kind="general", cull=_integer(floats.get("_CullMode", 0), 0, 2, "_CullMode"))
    if "_VERTEX_COLOR_ON" in keywords:
        fields["vertexColor"] = True
    return fields


def _variant(scene, materials, background, logo):
    return {"background": read(scene, materials, background),
            "logo": read(scene, materials, logo) if logo is not None else None}


def export(scene, materials, binding):
    """The display's variants, its own materials (``initial``) and material2DReference (``fallback``).

    None when one of them cannot be drawn: the renderer then keeps its own glTF material.
    """
    target, original, references, renderer = binding
    own = [viewer._ref(renderer, pointer) for pointer in scene.tree(renderer).get("m_Materials") or ()]
    try:
        variants = [_variant(scene, materials, background, logo) for background, logo in references]
        # Unity draws every material of a one-submesh renderer over that submesh, in order.
        initial = (_variant(scene, materials, own[0], own[1] if len(own) == 2 else None)
                   if 0 < len(own) <= 2 else None)
        fallback = read(scene, materials, original) if original is not None else None
    except Unsupported:
        return None
    return {"target": target, "fallback": fallback, "initial": initial, "variants": variants}
