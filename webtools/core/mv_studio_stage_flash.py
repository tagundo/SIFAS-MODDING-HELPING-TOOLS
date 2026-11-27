"""Identify native flash-light renderers and preserve their atlas inputs."""

import math

from . import model_viewer as viewer
from .mv_studio_shader_identity import keywords as shader_keywords
from .mv_studio_stage_coloring import _coordinates, _path

_STAGE = "/EntryPoint/Live/Stages/MainStage/Effect/"
_SHADER = "AS/FlashLight"
_SHADER_ID = 9060382612279247893
_SHADER_CAB = "cab-a44cd34f6481b592fc0475c6e5d23bfa"
_KEYWORDS = {"_AUTO_PLAY_ON", "_FLASH_ALL_ON", "_SATURATE_ON"}


def _matches_shader(material, tree):
    pointer = tree.get("m_Shader", {})
    local = viewer._ref(material, pointer)
    if local is not None:
        return (local.type.name == "Shader" and
                local.read_typetree().get("m_ParsedForm", {}).get("m_Name") == _SHADER)
    file_id = pointer.get("m_FileID", 0)
    references = material.assets_file.externals
    if pointer.get("m_PathID") != _SHADER_ID or not 0 < file_id <= len(references):
        return False
    return references[file_id - 1].path.replace("\\", "/").rsplit("/", 1)[-1].lower() == _SHADER_CAB


def binding(scene, component, tree):
    if not tree.get("m_Enabled"):
        return None
    script = viewer._ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return None
    identity = scene.tree(script)
    if tuple(identity.get(key) for key in ("m_AssemblyName", "m_Namespace", "m_ClassName")) != (
            "Assembly-CSharp.dll", "LLAS.Scene.Live.Components", "LiveCoreStageFlashLight"):
        return None
    game = viewer._ref(component, tree.get("m_GameObject"))
    renderer = viewer._ref(component, tree.get("renderer"))
    material = viewer._ref(component, tree.get("material"))
    if (game is None or scene.tree(game).get("m_Layer") != 27
            or renderer is None or renderer.type.name != "MeshRenderer"
            or material is None or material.type.name != "Material"):
        return None
    renderer_tree = scene.tree(renderer)
    owner = viewer._ref(renderer, renderer_tree.get("m_GameObject"))
    references = renderer_tree.get("m_Materials", ())
    names = _path(scene, game)
    if (owner is None or viewer._key(owner) != viewer._key(game) or len(names) < 2
            or len(references) != 1 or viewer._ref(renderer, references[0]) != material):
        return None
    source = scene.tree(material)
    if _matches_shader(material, source):
        return viewer._key(renderer), (_STAGE + "/".join(names[1:]), material, source)
    # LiveCoreStageFlashLight drives whatever material it holds: its mixer's PostProcess sets
    # _TintColor (ApplyTintColor), _SelfTime and _Speed, enables the renderer for status 1 and 2
    # and disables it for 0, and switches _FLASH_ALL_ON (ApplyFlashStatus). An
    # AS/General/Transparent material (the position-1 flash lights) consumes only _TintColor;
    # the other inputs select or feed nothing in it. Order-dependent blends and COLOR are left
    # to the other stage readers.
    from . import mv_studio_stage_overlay as overlay

    transparent = overlay.read_material(scene, material, world=True, full=True)
    if transparent is None or transparent.get("matcap") or transparent.get("alphaBlend") or transparent["vertexColor"]:
        return None
    return viewer._key(renderer), (_STAGE + "/".join(names[1:]), material, source, transparent,
                                   renderer_tree.get("m_Enabled") is True or renderer_tree.get("m_Enabled") == 1)


def export(materials, binding):
    if len(binding) == 5:
        path, _, _, transparent, enabled = binding
        texture = transparent["texture"]
        fields = {key: value for key, value in transparent.items() if key not in ("texture", "depthTest")}
        fields["texture"] = materials.texture(texture) if texture is not None else None
        # Without a running mixer the renderer keeps its serialized enabled state and the
        # material its own _TintColor.
        return {"binding": path, "kind": "transparent", "enabled": enabled, "transparent": fields,
                "queue": transparent["queue"]}
    path, material, source = binding
    flags = shader_keywords(material, source)
    floats = viewer._properties(source, "m_Floats")
    length, queue = floats.get("_Length", 16), source.get("m_CustomRenderQueue", -1)
    if (flags - _KEYWORDS or (floats.get("_BlendSrc", 5), floats.get("_BlendDst", 1)) != (5, 1)
            or type(length) not in (int, float) or not 0 < length <= 4096 or type(queue) is not int
            or not (queue == -1 or 2501 <= queue <= 5000)):
        return None
    envs = viewer._properties(source, "m_TexEnvs")
    main, mask = (envs.get(key, {}) for key in ("_MainTex", "_TilingTex"))
    main_st, mask_st = _coordinates(main), _coordinates(mask)
    if (not all(type(value) in (int, float) and math.isfinite(value) for value in (*main_st, *mask_st))
            or not all(1 <= scale <= 64 and scale == int(scale) for scale in mask_st[:2])
            or length > mask_st[0] * mask_st[1]):
        return None
    textures = [viewer._ref(material, env.get("m_Texture")) for env in (main, mask)]
    if any(item is None or item.type.name != "Texture2D" for item in textures):
        return None
    color, atlas = (materials.texture(item) for item in textures)
    return {"binding": path, "texture": color, "atlas": atlas, "textureST": main_st, "atlasST": mask_st,
            "length": length, "autoPlay": "_AUTO_PLAY_ON" in flags, "saturate": "_SATURATE_ON" in flags,
            "queue": 3000 if queue == -1 else queue}
