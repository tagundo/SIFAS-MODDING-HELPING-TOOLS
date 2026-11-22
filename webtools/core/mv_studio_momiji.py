"""Read Aion Expert's stencil-masked momiji display cue."""

from . import model_viewer as viewer, mv_studio_butterfly_glow as billboard, mv_studio_leaves as leaves
from . import mv_studio_momiji_particles as native, mv_studio_stage_particles as particles
from . import mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_stage_display import _shader_matches
from .mv_studio_stage_title_particles import _float32


TRACK = "StageEffect/Expert/Display/dis_par_03_momiji"
ROLES = {"fan": "fan", "flash": "flash", "leaf-green": "leaf", "leaf-red": "leaf"}
_OBJECTS = {"ougi": "fan", "mesh": "flash", "leaf_green": "leaf-green", "leaf_red": "leaf-red"}
_LAYER = 26
_ANCHOR = {"position": [_float32(.53), _float32(3.24), -12.5], "rotation": title._IDENTITY["rotation"],
           "scale": [_float32(1.2), _float32(1.3), _float32(1.3)]}
_LEAF_ROTATION = [0, 0, .13424559088326599, .9909480921463055]
_POSES = {
    "fan": ([_float32(1.39), -_float32(3.19), _float32(.3)], [0, 0, .24021702738038914, .9707192074727528]),
    "flash": ([0, 0, -.5], title._IDENTITY["rotation"]),
    "leaf-green": ([-_float32(.11), -_float32(2.05), _float32(.35)], _LEAF_ROTATION),
    "leaf-red": ([-_float32(.11), -_float32(2.05), _float32(.45)], _LEAF_ROTATION),
}
_RENDERERS = {
    "fan": {**billboard._RENDERER, "m_RenderAlignment": 1, "m_SortMode": 1, "m_MaxParticleSize": .5,
            "m_Pivot": {"x": 0, "y": .5, "z": 0}, "m_Flip": billboard._ZERO},
    "flash": {**billboard._RENDERER, "m_RenderAlignment": 2, "m_MaxParticleSize": 2, "m_Flip": billboard._ZERO},
    "leaf": {**leaves._RENDERER, "m_RenderAlignment": 4, "m_SortMode": 1},
}
_MATERIALS = {
    "fan": (-212231852118781808, "mat_dis_par_so2028_alb_04", 1155189878397289701, "tex_dis_par_so2028_03", 256, 1, 10),
    "flash": (-8369272728806906282, "mat_dis_par_gen_add_16", 3821574488674174747, "tex_grs_par_gen_10", 64, 0, 1),
    "leaf": (-5245640453824697119, "mat_dis_par_so2028_alb_03", 6455981386118614978, "tex_par_so2028_01", 256, 0, 10),
}
_TINT = 1.1898452043533325


def _material(objects, renderer, fields, kind):
    material_id, name, texture_id, texture_name, size, cull, destination = _MATERIALS[kind]
    refs = fields["m_Materials"]
    if refs != [{"m_FileID": 0, "m_PathID": material_id}] * 2:
        return None
    source = title._local(objects, renderer, refs[0], "Material")
    if source is None:
        return None
    tree = source.read_typetree()
    flash = kind == "flash"
    keywords = {"_VERTEX_COLOR_ON", "_VERTEX_COLOR_OFF"} if flash else {"_VERTEX_COLOR_ON"}
    tint = [1, 1, 1, 1] if flash else [_TINT, _TINT, _TINT, 1]
    colors = viewer._properties(tree, "m_Colors")
    values = viewer._properties(tree, "m_Floats")
    expected = {"_BlendSrc": 5, "_BlendDst": destination, "_CullMode": cull, "_SATURATE": 0, "_StencilComp": 3,
                "_StencilPassOp": 0, "_StencilRef": 2, "_StencilZFailOp": 0, "_VERTEX_COLOR": 1,
                "_ZTestMode": 4, "_ZWriteParam": 0}
    if (not billboard._matches(tree, {"m_Name": name, "m_CustomRenderQueue": 2900, "stringTagMap": [], "disabledShaderPasses": []})
            or not _shader_matches(source, tree, "AS/General/Transparent") or set(tree["m_ShaderKeywords"].split()) != keywords
            or colors.get("_TintColor") != dict(zip("rgba", tint))
            or not (billboard._matches(values, expected) if flash else values == expected)):
        return None
    tex = viewer._properties(tree, "m_TexEnvs")
    main = tex["_MainTex"]
    if (any(key != "_MainTex" and value["m_Texture"]["m_PathID"] for key, value in tex.items())
            or not billboard._matches(main, {"m_Texture": {"m_FileID": 0, "m_PathID": texture_id},
                                             "m_Scale": dict.fromkeys("xy", 1), "m_Offset": dict.fromkeys("xy", 0)})):
        return None
    reader = title._local(objects, source, main["m_Texture"], "Texture2D")
    if reader is None:
        return None
    image = reader.read()
    settings = image.m_TextureSettings
    if ((image.m_Name, image.m_Width, image.m_Height, image.m_TextureFormat, image.m_MipCount,
         image.m_ColorSpace, image.m_ImageCount, image.m_TextureDimension, image.m_StreamingMipmaps)
            != (texture_name, size, size, 65, size.bit_length(), 1, 1, 2, False)
            or (settings.m_FilterMode, settings.m_Aniso, settings.m_MipBias, settings.m_WrapU, settings.m_WrapV,
                settings.m_WrapW) != (1, 1, 0, 0, 0, 0)):
        return None
    return {"queue": 2900, "cull": cull, "blend": "add" if flash else "alpha", "saturate": False,
            "premultiply": False, "tint": tint, "stencil": "equal", "stencilRef": 2}, reader


def _emitter(objects, game, role):
    parts = title._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"}, layer=_LAYER)
    if parts is None:
        return None
    parts = parts[1]
    _, transform = parts["Transform"]
    position, rotation = _POSES[role]
    pose = _authored_trs(transform)
    if transform["m_Children"] or pose != {**title._IDENTITY, "translation": position, "rotation": rotation}:
        return None
    kind = ROLES[role]
    renderer, fields = parts["ParticleSystemRenderer"]
    if not billboard._matches(fields, _RENDERERS[kind]):
        return None
    system = parts["ParticleSystem"][1]
    mesh = None
    if kind == "leaf":
        data = native.leaf(system, green=role == "leaf-green")
        mesh = title._local(objects, renderer, fields["m_Mesh"], "Mesh")
        if mesh is None:
            return None
    else:
        data = native.flash(system) if kind == "flash" else native.fan(system)
    surface = _material(objects, renderer, fields, kind)
    if data is None or surface is None:
        return None
    material, atlas = surface
    return {"role": role, "texture": kind, "position": pose["translation"], "rotation": pose["rotation"],
            "scale": pose["scale"], "sortMode": fields["m_SortMode"], "maxViewportWidth": fields["m_MaxParticleSize"],
            "material": material, **data}, atlas, mesh


def _prefab(objects, game, deadline):
    viewer._remaining(deadline)
    for name in ("fx_dis_so2028_03", "root", "main"):
        body = title._components(objects, game, {"Transform"}, layer=_LAYER) if game is not None else None
        if body is None or body[0]["m_Name"] != name:
            return None
        root, fields = body[1]["Transform"]
        pose = _authored_trs(fields)
        if name == "main":
            anchor = {"position": pose["translation"], "rotation": pose["rotation"], "scale": pose["scale"]}
            if anchor != _ANCHOR:
                return None
        else:
            if pose != title._IDENTITY or name != "root" and fields["m_Father"] != billboard._NULL:
                return None
            child, = fields["m_Children"]
            game = title._transform_child(objects, root, child)
    refs = fields["m_Children"]
    if not 1 <= len(refs) <= len(_OBJECTS):
        return None
    found, emitters, atlases, mesh = set(), [], {}, None
    for ref in refs:
        game = title._transform_child(objects, root, ref)
        role = _OBJECTS.get(game.peek_name()) if game is not None else None
        if role is None or role in found:
            return None
        found.add(role)
        try:
            result = _emitter(objects, game, role)
        except title._UNSUPPORTED:
            continue
        if result is None:
            continue
        row, atlas, geometry = result
        kind = row["texture"]
        if kind in atlases and viewer._key(atlases[kind]) != viewer._key(atlas):
            continue
        if geometry is not None:
            if mesh is not None and viewer._key(mesh) != viewer._key(geometry):
                continue
            mesh = geometry
        atlases[kind] = atlas
        emitters.append(row)
    return anchor, emitters, atlases, mesh


def read(objects, mono, tracks, deadline):
    matches = [track for track in tracks if track["label"] == TRACK and not track.get("binding") and not track.get("bindings")]
    if len(matches) != 1:
        return None
    track, = matches
    source = next(((owner, fields) for key, (owner, fields, kind) in mono.items()
                   if kind == "CustomControlTrack" and timeline._id(key) == track["id"]), None)
    if source is None:
        return None
    owner, fields = source
    try:
        if (fields["m_Name"] != "dis_par_03_momiji" or not fields["m_Enabled"] or len(fields["m_Clips"]) != 1
                or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                or not title._group(objects, owner, fields)):
            return None
        cue, = track["events"]
        control = particles._source(objects, owner, fields, cue)
        native_prefab = _prefab(objects, control[0], deadline) if control is not None else None
    except title._UNSUPPORTED:
        return None
    if native_prefab is None:
        return None
    anchor, rows, atlases, mesh = native_prefab
    try:
        geometry = leaves._geometry(mesh, deadline) if mesh is not None else None
    except title._UNSUPPORTED:
        geometry = None
    textures = {}
    for kind, atlas in atlases.items():
        if kind == "leaf" and geometry is None:
            continue
        try:
            levels = particles._texture(atlas, deadline, sizes=(64 if kind == "flash" else 256,))
        except title._UNSUPPORTED:
            continue
        if levels:
            textures[kind] = levels
    rows = [row for row in rows if row["texture"] in textures]
    if not rows:
        return None
    result = {"schema": 1, "trackId": track["id"], "eventId": cue["id"], "anchor": anchor,
              "emitters": rows, "textures": textures}
    if "leaf" in textures:
        result["geometry"] = geometry
    return result
