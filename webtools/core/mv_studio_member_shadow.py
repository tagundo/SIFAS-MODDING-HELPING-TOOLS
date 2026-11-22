"""Extract the stock member's two default foot shadows for MV playback."""

import subprocess

import numpy as np

from . import model_viewer as viewer
from .mv_studio_stage_coloring import _path


_DECLARATION = ("ShadowComponent", "LLAS.Components.Members", "Assembly-CSharp.dll")
_STAGE_DECLARATION = ("LiveCoreStageEffect", "LLAS.Scene.Live.Components", "Assembly-CSharp.dll")
_TOES = ("LeftToeBase", "RightToeBase")
_ANCHORS = ("ShadowToeL", "ShadowToeR")
_SHADER_ID = 7151384334892346267
_SHADER_CAB = "cab-adf9ba7b61bd035c754bf74ae44927cb"
_STATE = {
    "_BlendSrc": 2, "_BlendDst": 0, "_CullMode": 0, "_SATURATE": 0,
    "_StencilComp": 8, "_StencilPassOp": 0, "_StencilZFailOp": 0,
    "_VERTEX_COLOR": 0, "_ZTestMode": 4, "_ZWriteParam": 0,
}


def _local(owner, pointer, kind):
    if not isinstance(pointer, dict) or pointer.get("m_FileID") != 0:
        return None
    target = viewer._ref(owner, pointer)
    return target if target is not None and target.assets_file is owner.assets_file and target.type.name == kind else None


def _declares(scene, component, fields, identity):
    script = viewer._ref(component, fields.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return False
    record = scene.tree(script)
    return tuple(record.get(key) for key in ("m_ClassName", "m_Namespace", "m_AssemblyName")) == identity


def stage_default(scene, component, tree):
    """Determine whether a typed stage leaves the costume's shadows in place."""
    prefabs = tree.get("memberShadowPrefabs")
    if (component.type.name != "MonoBehaviour" or tree.get("m_Enabled") != 1
            or not isinstance(prefabs, list) or len(prefabs) > 64):
        return None
    if any(not isinstance(ref, dict) or type(ref.get("m_PathID")) is not int or not ref["m_PathID"]
           or type(ref.get("m_FileID")) is not int or ref["m_FileID"] < 0 for ref in prefabs):
        return None
    try:
        if (_local(component, tree.get("m_GameObject"), "GameObject") is not None
                and _declares(scene, component, tree, _STAGE_DECLARATION)):
            return not prefabs
    except (AttributeError, KeyError, TypeError, ValueError, OSError):
        pass
    return None


def _nodes(scene, rig, component, fields, root):
    found = []
    for field, name in zip(("toeL", "toeR", "shadowL", "shadowR"), (*_TOES, *_ANCHORS), strict=True):
        transform = _local(component, fields.get(field), "Transform")
        if transform is None:
            return None
        game = _local(transform, scene.tree(transform).get("m_GameObject"), "GameObject")
        if game is None or scene.transforms.get(viewer._key(game)) is not transform:
            return None
        path = _path(scene, game)
        node = rig.nodes.get(viewer._key(transform))
        if (path[:len(root)] != root or not path or path[-1] != name
                or (field.startswith("shadow") and path != (*root, "Shadows", name))
                or type(node) is not int or not scene.active(game)):
            return None
        found.append((node, game))
    return found if len({node for node, _ in found}) == 4 else None


def _renderer(scene, game):
    key = viewer._key(game)
    rows = [(obj, tree) for obj, tree, owner in scene.renderers if viewer._key(owner) == key]
    if len(rows) != 1:
        return None
    renderer, tree = rows[0]
    states = ("m_CastShadows", "m_ReceiveShadows", "m_RenderingLayerMask",
              "m_RendererPriority", "m_SortingLayerID", "m_SortingOrder")
    refs = tree.get("m_Materials", ())
    if (renderer.type.name != "MeshRenderer" or not tree.get("m_Enabled") or len(refs) != 1
            or scene.tree(game).get("m_Layer") != 16
            or tuple(tree.get(name) for name in states) != (0, 0, 1, 0, 0, 0)):
        return None
    material = _local(renderer, refs[0], "Material")
    mesh = scene.filters.get(key)
    if (material is None or mesh is None or mesh.type.name != "Mesh"
            or mesh.assets_file is not renderer.assets_file or scene.name(mesh) != "foot_shadow_Plane"):
        return None
    return mesh, material


def _shader(scene, material, pointer):
    if not isinstance(pointer, dict) or pointer.get("m_PathID") != _SHADER_ID:
        return False
    file_id = pointer.get("m_FileID", 0)
    externals = material.assets_file.externals
    if type(file_id) is not int or not 0 < file_id <= len(externals):
        return False
    cab = externals[file_id - 1].path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if cab != _SHADER_CAB:
        return False
    shader = viewer._ref(material, pointer)
    return shader is None or (shader.type.name == "Shader" and
                              scene.tree(shader).get("m_ParsedForm", {}).get("m_Name") == "AS/General/Transparent")


def _image(scene, material):
    tree = scene.tree(material)
    floats = viewer._properties(tree, "m_Floats")
    tint = viewer._properties(tree, "m_Colors").get("_TintColor")
    keywords = set(str(tree.get("m_ShaderKeywords", "")).split())
    if (tree.get("m_Name") != "shadow" or tree.get("m_CustomRenderQueue") != 2800
            or "_VERTEX_COLOR_OFF" not in keywords or keywords - {"_VERTEX_COLOR_OFF", "_ALPHABLEND_ON", "_EMISSION"}
            or any(floats.get(name) != value for name, value in _STATE.items())
            or tint != dict.fromkeys("rgba", 1) or not _shader(scene, material, tree.get("m_Shader"))):
        return None
    main = viewer._properties(tree, "m_TexEnvs").get("_MainTex", {})
    if main.get("m_Scale") != {"x": 1, "y": 1} or main.get("m_Offset") != {"x": 0, "y": 0}:
        return None
    image = _local(material, main.get("m_Texture"), "Texture2D")
    if image is None:
        return None
    texture = image.read()
    sampler = texture.m_TextureSettings
    if (texture.m_Name != "dropshadow" or (texture.m_Width, texture.m_Height, texture.m_MipCount) != (128, 128, 1)
            or (texture.m_TextureFormat, texture.m_ImageCount, texture.m_TextureDimension, texture.m_ColorSpace)
            not in ((32, 1, 2, 1), (34, 1, 2, 1))
            or (sampler.m_FilterMode, sampler.m_Aniso, sampler.m_MipBias) != (1, 1, 0)
            or (sampler.m_WrapU, sampler.m_WrapV) != (0, 0)):
        return None
    return image, texture


def _read(scene, glb, materials, rig, deadline):
    matches = []
    sources = rig.selected - rig.facial_sources - rig.motion_sources
    for obj in scene.env.objects:
        if obj.type.name != "MonoBehaviour" or viewer._source_path(obj) not in sources:
            continue
        viewer._remaining(deadline)
        try:
            fields = scene.tree(obj)
        except (TypeError, ValueError, OSError):
            continue
        if not fields.get("m_Enabled") or not {"toeL", "toeR", "shadowL", "shadowR"} <= fields.keys():
            continue
        if _declares(scene, obj, fields, _DECLARATION):
            matches.append((obj, fields))
    if len(matches) != 1:
        return None
    component, fields = matches[0]
    owner = _local(component, fields.get("m_GameObject"), "GameObject")
    root = _path(scene, owner)
    nodes = _nodes(scene, rig, component, fields, root) if root and scene.active(owner) else None
    if nodes is None:
        return None
    left, right = (_renderer(scene, game) for _, game in nodes[2:])
    if left is None or right is None or tuple(map(viewer._key, left)) != tuple(map(viewer._key, right)):
        return None
    mesh, material = left
    tree = scene.tree(mesh)
    parts = tree.get("m_SubMeshes", ())
    if (tree.get("m_VertexData", {}).get("m_VertexCount") != 12 or len(parts) != 1
            or parts[0].get("indexCount") != 30 or parts[0].get("topology") != 0):
        return None
    _, positions, _, uv, triangles = viewer._geometry(mesh, np.eye(4), deadline=deadline)
    if (positions.shape != (12, 3) or not np.all(positions[:, 1] == 0) or np.abs(positions).max() > 5.001
            or uv is None or uv.shape != (12, 2) or not np.all((0 <= uv) & (uv <= 1))
            or len(triangles) != 1 or triangles[0].shape != (10, 3)):
        return None
    image = _image(scene, material)
    if image is None:
        return None
    reader, texture = image
    key = viewer._key(reader)
    if key not in materials.textures:
        if materials.pixels + 128 * 128 > viewer.MAX_TEXTURE_PIXELS:
            return None
        # ETC1/PVRTC4 stock shadow textures use the isolated stage decoder.
        # Reuse the existing GLB image registrar without broadening model decoding.
        png = viewer._texture_png(texture, deadline, stage=True)
        if len(glb.data) + len(png) + 1024 > viewer.MAX_GLB_BYTES:
            return None
        materials.predecoded[key] = png
    elif len(glb.data) + 1024 > viewer.MAX_GLB_BYTES:
        return None
    index = materials.texture(reader)
    return {"schema": 1, "toes": [node for node, _ in nodes[:2]], "anchors": [node for node, _ in nodes[2:]],
            "geometry": {"POSITION": glb.attribute(positions, "VEC3", bounds=True),
                         "TEXCOORD_0": glb.attribute(uv, "VEC2"),
                         "indices": glb.attribute(triangles[0].ravel(), "SCALAR", 5123)},
            "texture": index}


def read(scene, glb, materials, rig, deadline):
    """Return detached GLB geometry and its four original rig node indices."""
    try:
        return _read(scene, glb, materials, rig, deadline)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        # An optional shadow should never substitute for the playable costume.
        return None
