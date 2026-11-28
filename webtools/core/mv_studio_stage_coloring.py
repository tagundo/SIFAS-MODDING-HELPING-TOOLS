"""Native palette metadata for LiveCoreStageColoring during MV preview."""

import math

from . import model_viewer as viewer
from .mv_studio_shader_identity import keywords as shader_keywords


_ROOT = "/EntryPoint/Live/Stages/MainStage/Effect/"
_SHADER_CAB = "cab-da18667fd7e5e991d56b5d877869e6c6"
_SHADER_ID = 7366096703533297961


def _texture(owner, pointer):
    obj = viewer._ref(owner, pointer)
    return obj if obj is not None and obj.type.name == "Texture2D" else None


def _path(scene, game):
    names, visited = [], set()
    while game is not None:
        key = viewer._key(game)
        if key in visited or len(names) >= 64:
            return ()
        visited.add(key)
        name = scene.name(game)
        transform = scene.transforms.get(key)
        if not name or "/" in name or transform is None:
            return ()
        names.append(name)
        father = viewer._ref(transform, scene.tree(transform).get("m_Father"))
        game = viewer._ref(father, scene.tree(father).get("m_GameObject")) if father is not None else None
    return tuple(reversed(names))


def _shader(material, tree):
    pointer = tree.get("m_Shader", {})
    shader = viewer._ref(material, pointer)
    if shader is not None:
        return shader.type.name == "Shader" and shader.read_typetree().get("m_ParsedForm", {}).get("m_Name") == "AS/Coloring/Transparent"
    file_id = pointer.get("m_FileID", 0)
    references = material.assets_file.externals
    if pointer.get("m_PathID") != _SHADER_ID or not 0 < file_id <= len(references):
        return False
    return references[file_id - 1].path.replace("\\", "/").rsplit("/", 1)[-1].lower() == _SHADER_CAB


def _coordinates(value):
    value = value or {}
    return [value.get("m_Scale", {}).get(axis, 1) for axis in "xy"] + [
        value.get("m_Offset", {}).get(axis, 0) for axis in "xy"]


def binding(scene, component, tree):
    if not tree.get("m_Enabled"):
        return None
    script = viewer._ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return None
    identity = scene.tree(script)
    if tuple(identity.get(key) for key in ("m_AssemblyName", "m_Namespace", "m_ClassName")) != (
            "Assembly-CSharp.dll", "LLAS.Scene.Live.Components", "LiveCoreStageColoring"):
        return None
    game = viewer._ref(component, tree.get("m_GameObject"))
    material = viewer._ref(component, tree.get("material"))
    palette = _texture(component, tree.get("paletteTexture"))
    path = _path(scene, game)
    if len(path) < 2 or material is None or material.type.name != "Material" or palette is None:
        return None
    original = scene.tree(material)
    if not _shader(material, original):
        return None
    # Only the shader's own keywords select its program (mv_studio_shader_identity); the
    # _AUTO_PLAY, _VERTEX_COLOR and _SATURATE toggles only set them. Every combination of
    # _AUTO_PLAY_ON, _SATURATE_ON and _VERTEX_COLOR_ON has its own GLES3 program.
    keywords = shader_keywords(material, original)
    floats = viewer._properties(original, "m_Floats")
    if (floats.get("_BlendSrc", 5), floats.get("_BlendDst", 1)) != (5, 1):
        return None
    # LiveCoreStageColoring.ApplyTextureIndex swaps _MainTex for
    # lightShaftTextures[LiveColoringClip.textureIndex] (keeping _MainTex_ST).
    shafts = tree.get("lightShaftTextures") or []
    if not isinstance(shafts, list) or len(shafts) > 64:
        return None
    shafts = [_texture(component, pointer) for pointer in shafts]
    if any(shaft is None for shaft in shafts):
        return None
    cull = floats.get("_CullMode", 0)
    queue = original.get("m_CustomRenderQueue", -1)
    colors = viewer._properties(original, "m_Colors")
    rgba = [colors.get("_TintColor", {}).get(axis, 1) for axis in "rgba"]
    envs = viewer._properties(original, "m_TexEnvs")
    main = envs.get("_MainTex")
    texture = _texture(material, (main or {}).get("m_Texture"))
    main_uv = _coordinates(main)
    id_uv = _coordinates(envs.get("_ColorIdTex"))
    speed, shift = floats.get("_Speed", 1), floats.get("_Shift", 0)
    if (texture is None or cull not in (0, 1, 2) or type(queue) is not int
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in [*rgba, *main_uv, *id_uv, speed, shift])):
        return None
    return viewer._key(material), (path, palette, texture, {
        "target": _ROOT + "/".join(path[1:]), "tint": rgba, "speed": speed, "shift": shift,
        "cull": cull, "queue": 3000 if queue == -1 else queue, "mainUV": main_uv,
        "indexScale": id_uv[0], "indexOffset": id_uv[2],
        **{field: True for field, keyword in (("autoPlay", "_AUTO_PLAY_ON"), ("saturate", "_SATURATE_ON"),
                                             ("vertexColor", "_VERTEX_COLOR_ON")) if keyword in keywords},
    }, tuple(shafts))


def with_sort_center(descriptor, renderer_tree, mesh, *, builtin_mesh=False, world=None):
    """Adds the renderer's sort center. Unity draws the renderers of one transparent queue back
    to front by the distance from the camera to their bounds' center, the mesh's m_LocalAABB
    center under the renderer's transform; a renderer with its own sorting layer, order or
    priority keeps the descriptor without one (as the stage overlay does).

    ``world`` is the Unity local-to-world matrix the exporter baked into the vertices
    (model_viewer._geometry writes diag(-1, 1, 1, 1) @ world @ vertex). A coloring renderer
    outside the stage-motion bindings has no node transform, so its center is baked the same
    way; a renderer under a retained stage node or an AxisBillboard node is placed by its node
    and passes the identity. The center of a transformed box is the transformed center, so
    this is also the center of Unity's world bounds."""
    from . import mv_studio_stage_overlay as overlay

    bounds = overlay._sort_bounds(renderer_tree, None if builtin_mesh else mesh, builtin_mesh=builtin_mesh)
    if not bounds:
        return descriptor
    if world is not None:
        import numpy as np

        x, y, z = bounds["sortCenter"]
        center = np.asarray(world, dtype=float) @ np.array([-x, y, z, 1.])
        if not np.isfinite(center[:3]).all():
            return descriptor
        bounds = {**bounds, "sortCenter": [-float(center[0]), float(center[1]), float(center[2])]}
    return {**descriptor, **bounds}


def renderer_binding(scene, game, candidates):
    if not candidates:
        return None
    path = _path(scene, game)
    owning = [row for row in candidates if path[:len(row[0])] == row[0]]
    return owning[0] if len(owning) == 1 else None


def export(glb, materials, binding, palettes):
    _, palette, texture, fields, shafts = binding
    key = viewer._key(palette)
    if key not in palettes:
        original = palette.read()
        sampler = original.m_TextureSettings
        width, height = original.m_Width, original.m_Height
        if (original.m_TextureFormat != 4 or original.m_MipCount != 1 or width != 256 or
                not 0 < height <= 256 or (sampler.m_FilterMode, sampler.m_WrapU, sampler.m_WrapV) != (1, 0, 0)):
            palettes[key] = None
        else:
            data = original.get_image_data()
            palettes[key] = {"bytes": glb.view(data), "size": [width, height]} if len(data) == width * height * 4 else None
    saved = palettes[key]
    if saved is None:
        return None
    return {**fields, "palette": saved, "main": materials.texture(texture),
            "shaftTextures": [materials.texture(shaft) for shaft in shafts]}
