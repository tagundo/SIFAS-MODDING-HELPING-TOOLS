"""Retain the native floor spotlight placed under each performer's Move node."""

import math

from . import model_viewer as viewer
from .model_materials import _original_mips
from .model_rig import _authored_trs
from .mv_studio_shaft import _STAGE_EFFECT
from .mv_studio_stage_display import _shader_matches
from .mv_studio_stage_title import _QUAD


def _local(owner, pointer, kind):
    if not isinstance(pointer, dict) or pointer.get("m_FileID") != 0:
        return None
    obj = viewer._ref(owner, pointer)
    return obj if obj is not None and obj.type.name == kind else None


def reference(scene, component, tree):
    """Resolve one detached, single-renderer Unity Quad instance source."""
    pointer = tree.get("spotLightAreaPrefab")
    if not pointer or not tree.get("m_Enabled"):
        return None
    script = _local(component, tree.get("m_Script"), "MonoScript")
    if script is None:
        return None
    definition = scene.tree(script)
    if tuple(definition.get(key) for key in ("m_AssemblyName", "m_Namespace", "m_ClassName")) != _STAGE_EFFECT:
        return None
    stage = _local(component, tree.get("m_GameObject"), "GameObject")
    prefab = _local(component, pointer, "GameObject")
    if stage is None or prefab is None or prefab == stage:
        return None
    fields = scene.tree(prefab)
    entries = fields.get("m_Component", [])
    if fields.get("m_Layer") != 1 or not fields.get("m_IsActive") or len(entries) != 3:
        return None
    pieces = {}
    for entry in entries:
        ref = entry.get("component")
        obj = viewer._ref(prefab, ref)
        if (obj is None or ref.get("m_FileID") != 0 or obj.type.name not in ("Transform", "MeshRenderer", "MeshFilter")
                or obj.type.name in pieces or _local(obj, scene.tree(obj).get("m_GameObject"), "GameObject") != prefab):
            return None
        pieces[obj.type.name] = obj
    transform = pieces["Transform"]
    transform_tree = scene.tree(transform)
    if transform_tree.get("m_Children") or (transform_tree.get("m_Father") or {}).get("m_PathID"):
        return None
    mesh_filter = pieces["MeshFilter"]
    mesh = scene.tree(mesh_filter).get("m_Mesh", {})
    file_id = mesh.get("m_FileID", 0)
    if (mesh.get("m_PathID") != 10210 or not 0 < file_id <= len(mesh_filter.assets_file.externals)
            or mesh_filter.assets_file.externals[file_id - 1].path.lower().replace("\\", "/") != "library/unity default resources"):
        return None
    renderer = pieces["MeshRenderer"]
    renderer_tree = scene.tree(renderer)
    materials = renderer_tree.get("m_Materials", [])
    if not renderer_tree.get("m_Enabled") or len(materials) != 1:
        return None
    material = _local(renderer, materials[0], "Material")
    return (prefab, transform, material) if material is not None else None


def export(scene, glb, materials, source, deadline):
    import numpy as np

    viewer._remaining(deadline)
    prefab, transform, material = source
    tree = scene.tree(material)
    if not _shader_matches(material, tree, "AS/General/Transparent"):
        return None
    floats = viewer._properties(tree, "m_Floats")
    keywords = set(str(tree.get("m_ShaderKeywords", "")).split())
    expected = {"_BlendSrc": 5, "_BlendDst": 1, "_CullMode": 0, "_ZTestMode": 4, "_ZWriteParam": 0,
                "_StencilComp": 8, "_StencilPassOp": 0, "_StencilZFailOp": 0, "_VERTEX_COLOR": 0, "_SATURATE": 0}
    if keywords - {"_VERTEX_COLOR_OFF"} or any(floats.get(key, value) != value for key, value in expected.items()):
        return None
    queue = tree.get("m_CustomRenderQueue", -1)
    if queue not in (-1, 3000):
        return None
    main = viewer._properties(tree, "m_TexEnvs").get("_MainTex", {})
    texture = _local(material, main.get("m_Texture"), "Texture2D")
    if texture is None:
        return None
    texture_tree = scene.tree(texture)
    sampler = texture_tree.get("m_TextureSettings", {})
    width, height = texture_tree["m_Width"], texture_tree["m_Height"]
    if (not 0 < width <= 512 or not 0 < height <= 512 or width & (width - 1) or height & (height - 1)
            or sampler.get("m_FilterMode") != 1 or sampler.get("m_WrapU") != 0 or sampler.get("m_WrapV") != 0):
        return None
    uv = [main.get("m_Scale", {}).get(axis, 1) for axis in "xy"] + [
        main.get("m_Offset", {}).get(axis, 0) for axis in "xy"]
    if not all(type(value) in (int, float) and math.isfinite(value) for value in uv):
        return None
    mips = _original_mips(texture, texture.read())
    texture_indices = [materials.texture(texture), *materials.mip_textures(mips)] if mips else [materials.texture(texture)]
    geometry = {
        "position": glb.attribute(np.asarray(_QUAD["positions"], dtype=np.float32), "VEC3", bounds=True),
        "uv": glb.attribute(np.asarray(_QUAD["uv"], dtype=np.float32), "VEC2"),
        "index": glb.attribute(np.asarray(_QUAD["indices"], dtype=np.uint16), "SCALAR", 5123),
    }
    return {"prefabPathId": str(prefab.path_id), "name": scene.name(prefab), "geometry": geometry, "textures": texture_indices,
            "queue": 3000, "uv": uv, **_authored_trs(scene.local_tree(transform))}
