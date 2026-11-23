"""Stage-effect props lit by LivePropBasic (LivePropAmbient / LivePropRimlight).

LiveCoreStageEffect.Initialize collects every LivePropBasic below it, and
LivePropBasic.Initialize (0x299ace0) gives the prop its own instance of every
material listed by its LivePropAmbient and LivePropRimlight components (keyed
by material name) and swaps those instances into the sharedMaterials of the
renderers below it. From then on only LivePropAmbientMixer / LivePropRimlightMixer,
bound to the prop's GameObject, change those materials; stage-level ambient
components keep the original assets.
"""

import math

from . import model_viewer as viewer
from .mv_studio_stage_coloring import _path

_NAMESPACE = ("Assembly-CSharp.dll", "LLAS.Scene.Live.Components")
_PREFIX = "/EntryPoint/Live/Stages/MainStage/Effect/"
_RIMLIGHT = "AS/Rimlight/Opaque"
_RIMLIGHT_KEY = ("cab-6cf8387efa4151b6220fceb9384d0e8e", 7983779172275908372)


def _script(scene, component, tree):
    script = viewer._ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return None
    definition = scene.tree(script)
    return tuple(definition.get(field) for field in ("m_AssemblyName", "m_Namespace", "m_ClassName"))


def _material_names(scene, owner, pointer, class_name):
    if not isinstance(pointer, dict) or pointer.get("m_FileID") != 0:
        return set()
    component = viewer._ref(owner, pointer)
    if component is None or component.type.name != "MonoBehaviour":
        return set()
    tree = scene.tree(component)
    if _script(scene, component, tree) != (*_NAMESPACE, class_name):
        return set()
    names = set()
    for item in tree.get("materials") or ():
        material = viewer._ref(component, item) if isinstance(item, dict) else None
        if material is not None and material.type.name == "Material":
            names.add(scene.name(material))
    return names


def props(scene, component, tree):
    """LiveCoreStageEffect.Initialize (0x2f6f4c4): Props = GetComponentsInChildren<LivePropBasic>(true),
    then each prop's Initialize. Return (GameObject path, entry) for each of them."""
    if _script(scene, component, tree) != (*_NAMESPACE, "LiveCoreStageEffect"):
        return []
    game = viewer._ref(component, tree.get("m_GameObject"))
    root = _path(scene, game) if game is not None and game.type.name == "GameObject" else ()
    if not root:
        return []
    found = []
    for obj in scene.env.objects:
        if obj.type.name != "MonoBehaviour" or obj.assets_file is not component.assets_file:
            continue
        try:
            candidate = scene.tree(obj)
        except Exception:
            continue
        entry = binding(scene, obj, candidate)
        if entry is not None and entry[0][:len(root)] == root:
            found.append(entry)
    return found


def binding(scene, component, tree):
    """Return (GameObject path, entry) for one LivePropBasic of a stage-effect prefab."""
    if _script(scene, component, tree) != (*_NAMESPACE, "LivePropBasic"):
        return None
    game = viewer._ref(component, tree.get("m_GameObject"))
    path = _path(scene, game) if game is not None and game.type.name == "GameObject" else ()
    if len(path) < 2:
        return None
    ambient = _material_names(scene, component, tree.get("ambient"), "LivePropAmbient")
    rim = _material_names(scene, component, tree.get("rimlight"), "LivePropRimlight")
    if not ambient and not rim:
        return None
    # The effect prefab is inserted under Stages/MainStage/Effect; its root name is not bound.
    return path, {"binding": _PREFIX + "/".join(path[1:]), "ambient": ambient, "rim": rim}


def renderer_entry(scene, game_object, props):
    """The innermost prop whose GetComponentsInChildren<Renderer> reaches this renderer."""
    if not props:
        return None
    path = _path(scene, game_object)
    owners = [(owner, entry) for owner, entry in props if path[:len(owner)] == owner]
    return max(owners, key=lambda row: len(row[0]))[1] if owners else None


def light(entry, material_name):
    """The mvPropLight extras for one primitive material, or None."""
    if entry is None or material_name not in entry["ambient"] | entry["rim"]:
        return None
    return {"binding": entry["binding"], "ambient": material_name in entry["ambient"],
            "rim": material_name in entry["rim"]}


def _is_rimlight(material, tree):
    pointer = tree.get("m_Shader", {})
    shader = viewer._ref(material, pointer)
    if shader is not None:
        return shader.type.name == "Shader" and shader.read_typetree().get("m_ParsedForm", {}).get("m_Name") == _RIMLIGHT
    number, externals = pointer.get("m_FileID"), material.assets_file.externals
    if type(number) is not int or not 1 <= number <= len(externals):
        return False
    cab = externals[number - 1].path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return (cab, pointer.get("m_PathID")) == _RIMLIGHT_KEY


def _finite(values):
    return all(type(value) in (int, float) and math.isfinite(value) for value in values)


def rimlight_material(scene, material):
    """Read the inputs of the single AS/Rimlight/Opaque pass, or None.

    The pass draws opaque (Blend One Zero, ZWrite On, ZTest LEqual, Cull
    [_CullMode]) and outputs max(0, lerp(main * COLOR0, ambient.rgb, ambient.a)
    * tint + rim * rimColor.rgb) with
    rim = pow(1 - saturate(dot(normalize(toCamera - direction), viewNormal)), power)
          * rimColor.a * intensity * rimTex.r; both textures use _MainTex_ST.
    """
    if material is None or material.type.name != "Material":
        return None
    tree = scene.tree(material)
    if not _is_rimlight(material, tree):
        return None
    floats = viewer._properties(tree, "m_Floats")
    if (floats.get("_StencilComp", 8), floats.get("_StencilPassOp", 0), floats.get("_StencilZFailOp", 0)) != (8, 0, 0):
        return None
    colors = viewer._properties(tree, "m_Colors")
    defaults = {"_TintColor": (1, 1, 1, 1), "_AmbientColor": (1, 1, 1, 0), "_RimlightColor": (1, 1, 1, 1),
                "_RimlightDirection": (0, 0, 0, 0)}
    values = {}
    for name, fallback in defaults.items():
        color = colors.get(name)
        values[name] = [color.get(axis, 0) for axis in "rgba"] if isinstance(color, dict) else list(fallback)
    textures = viewer._properties(tree, "m_TexEnvs")
    main = textures.get("_MainTex", {})
    uv = [main.get("m_Scale", {}).get(axis, 1) for axis in "xy"] + [main.get("m_Offset", {}).get(axis, 0) for axis in "xy"]
    cull, intensity, power = floats.get("_CullMode", 2), floats.get("_RimglightIntensity", 1), floats.get("_RimglightPower", 3)
    queue = tree.get("m_CustomRenderQueue", -1)
    if (not _finite([*uv, intensity, power, *(value for row in values.values() for value in row)])
            or cull not in (0, 1, 2) or type(queue) is not int):
        return None
    found = {}
    for name in ("_MainTex", "_RimlightTex"):
        pointer = textures.get(name, {}).get("m_Texture", {})
        found[name] = None
        if pointer.get("m_PathID"):
            texture = viewer._ref(material, pointer)
            if texture is None or texture.type.name != "Texture2D":
                return None
            found[name] = texture
    return {"texture": found["_MainTex"], "rimlightTexture": found["_RimlightTex"], "uv": uv,
            "tint": values["_TintColor"], "ambient": values["_AmbientColor"],
            "rimlightColor": values["_RimlightColor"], "rimlightDirection": values["_RimlightDirection"],
            "intensity": intensity, "power": power, "cull": int(cull), "queue": 2000 if queue == -1 else queue}


def export_rimlight(materials, fields):
    textures = {name: materials.texture(fields[name]) if fields[name] is not None else None
                for name in ("texture", "rimlightTexture")}
    return {**fields, **textures}
