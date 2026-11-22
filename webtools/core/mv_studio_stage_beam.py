"""Keep the native material and mip chain for the Monster Girls stage beam."""

import subprocess

from . import model_viewer as viewer
from .model_materials import _original_mips
from .mv_studio_stage_coloring import _path


_PATH = ("bg0021_01_fx_so2056_ex", "fx_par_so2056_05", "root", "joint_all", "LaserBeam")
_BINDING = "/EntryPoint/Live/Stages/MainStage/Effect/" + "/".join(_PATH[1:])
_GAME_ID = -8013378665567441334
_RENDERER_ID = 5696258066361059067
_MESH_ID = 5194592982056741647
_MATERIAL_ID = -438483446559388561
_TEXTURE_ID = -7690959353496573415
_SHADER = "AS/General/Transparent"
_SHADER_ID = 7151384334892346267
_SHADER_CAB = "cab-adf9ba7b61bd035c754bf74ae44927cb"
_FLOATS = {
    "_BlendSrc": 5, "_BlendDst": 1, "_CullMode": 0, "_SATURATE": 0,
    "_StencilComp": 8, "_StencilPassOp": 0, "_StencilRef": 0, "_StencilZFailOp": 0,
    "_VERTEX_COLOR": 1, "_ZTestMode": 4, "_ZWriteParam": 0,
}


def _shader(material, pointer):
    if not isinstance(pointer, dict) or pointer.get("m_PathID") != _SHADER_ID:
        return False
    file_id = pointer.get("m_FileID", 0)
    externals = material.assets_file.externals
    if type(file_id) is not int or not 0 < file_id <= len(externals):
        return False
    name = externals[file_id - 1].path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name != _SHADER_CAB:
        return False
    shader = viewer._ref(material, pointer)
    return shader is None or (shader.type.name == "Shader" and
                              shader.read_typetree().get("m_ParsedForm", {}).get("m_Name") == _SHADER)


def _texture(material, main):
    if (main.get("m_Texture") != {"m_FileID": 0, "m_PathID": _TEXTURE_ID}
            or main.get("m_Scale") != {"x": 1, "y": 1}
            or main.get("m_Offset") != {"x": 0, "y": 0}):
        return None
    reader = viewer._ref(material, main["m_Texture"])
    if reader is None or reader.type.name != "Texture2D":
        return None
    texture = reader.read()
    sampler = texture.m_TextureSettings
    if (texture.m_Name != "tex_stg_so2056_01"
            or (texture.m_Width, texture.m_Height, texture.m_MipCount) != (512, 512, 10)
            or (texture.m_TextureFormat, texture.m_TextureDimension, texture.m_ImageCount,
                texture.m_ColorSpace) != (65, 2, 1, 1)
            or (sampler.m_FilterMode, sampler.m_Aniso, sampler.m_MipBias) != (1, 1, 0)
            or (sampler.m_WrapU, sampler.m_WrapV, sampler.m_WrapW) != (0, 0, 0)):
        return None
    return reader, texture


def export_material(scene, renderer, game_object, material, materials, deadline):
    if (not getattr(scene, "native_stage_effect", False) or renderer.path_id != _RENDERER_ID
            or renderer.type.name != "SkinnedMeshRenderer" or game_object.path_id != _GAME_ID
            or material is None or material.path_id != _MATERIAL_ID or material.type.name != "Material"
            or renderer.assets_file is not game_object.assets_file or renderer.assets_file is not material.assets_file
            or _path(scene, game_object) != _PATH):
        return None
    renderer_tree = scene.tree(renderer)
    if (not renderer_tree.get("m_Enabled") or not renderer_tree.get("m_UpdateWhenOffscreen")
            or renderer_tree.get("m_GameObject") != {"m_FileID": 0, "m_PathID": _GAME_ID}
            or renderer_tree.get("m_Mesh") != {"m_FileID": 0, "m_PathID": _MESH_ID}
            or renderer_tree.get("m_Materials") != [{"m_FileID": 0, "m_PathID": _MATERIAL_ID}]):
        return None
    mesh = viewer._ref(renderer, renderer_tree["m_Mesh"])
    if mesh is None or mesh.type.name != "Mesh" or scene.name(mesh) != "LaserBeam":
        return None
    vertices = scene.tree(mesh).get("m_VertexData", {})
    channels = vertices.get("m_Channels", ())
    if (vertices.get("m_VertexCount") != 1568 or len(channels) != 14
            or channels[3].get("dimension") != 0 or channels[4].get("dimension") != 2):
        return None

    tree = scene.tree(material)
    tint = viewer._properties(tree, "m_Colors").get("_TintColor")
    if (tree.get("m_Name") != "mat_par_so2056_add_03" or tree.get("m_CustomRenderQueue") != 3010
            or tree.get("m_ShaderKeywords") != "_VERTEX_COLOR_ON"
            or viewer._properties(tree, "m_Floats") != _FLOATS
            or tint != {"r": 2, "g": 2, "b": 2, "a": 1}
            or not _shader(material, tree.get("m_Shader"))):
        return None
    main = viewer._properties(tree, "m_TexEnvs").get("_MainTex", {})
    texture = _texture(material, main)
    if texture is None:
        return None
    viewer._remaining(deadline)
    reader, value = texture
    levels = _original_mips(reader, value)
    if len(levels) != 9:
        return None
    try:
        index = materials.texture(reader)
        mips = materials.mip_textures(levels)
    except (OSError, subprocess.SubprocessError):
        return None
    # The stock mesh has no COLOR stream. Its unrolled UV0 and saved HDR
    # tint remain in the native gamma lane, with source alpha/one blending.
    return {"shader": _SHADER, "binding": _BINDING, "renderOrder": 3010, "texture": index,
            "mips": mips, "tint": [tint[axis] for axis in "rgba"], "uv": [1, 1, 0, 0],
            "vertexColor": False}
