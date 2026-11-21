"""Read the paired native Aion spotlight's two authored mesh surfaces."""

from . import model_viewer as viewer
from . import mv_studio_stage_motion as motion, mv_studio_stage_particles as particles
from . import mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_stage_display import _SHADERS


_PREFAB = "fx_par_so2028_12"
_HIERARCHY = {
    "": ("Transform",),
    "root": ("Transform", "Animator"),
    "root/ctrl": ("Transform",),
    "root/ctrl/mdl": ("Transform",),
    "root/ctrl/mdl/Glow_03": ("Transform", "SkinnedMeshRenderer"),
    "root/ctrl/mdl/L": ("Transform",),
    "root/ctrl_area": ("Transform",),
    "root/ctrl_area/glow02": ("Transform", "MeshFilter", "MeshRenderer"),
}
_BEAM = "root/ctrl/mdl/Glow_03"
_BONE = "root/ctrl/mdl/L"
_FLOOR = "root/ctrl_area/glow02"
_IDENTITY_BIND = {f"e{row}{col}": float(row == col) for row in range(4) for col in range(4)}
_RENDER_FLOATS = {"_BlendSrc": 5, "_BlendDst": 1, "_CullMode": 0, "_VERTEX_COLOR": 1,
                  "_ZTestMode": 4, "_ZWriteParam": 0, "_StencilComp": 8,
                  "_StencilPassOp": 0, "_StencilRef": 2, "_StencilZFailOp": 0, "_SATURATE": 0}


def _hierarchy(objects, game, path, nodes):
    types = _HIERARCHY.get(path)
    if types is None or path in nodes:
        return False
    row = title._components(objects, game, set(types), layer=1)
    if row is None:
        return False
    tree, parts = row
    name = path.rsplit("/", 1)[-1] if path else _PREFAB
    transform, fields = parts["Transform"]
    if tree["m_Name"] != name or (not path and fields["m_Father"]["m_PathID"]):
        return False
    nodes[path] = parts
    for ref in fields["m_Children"]:
        child = title._transform_child(objects, transform, ref)
        if child is None or not _hierarchy(objects, child, f"{path}/{child.peek_name()}".lstrip("/"), nodes):
            return False
    return True


def _white_vertex_material(objects, renderer, ref):
    material = title._local(objects, renderer, ref, "Material")
    if material is None:
        return False
    tree = material.read_typetree()
    floats = viewer._properties(tree, "m_Floats")
    textures = viewer._properties(tree, "m_TexEnvs")
    tint = viewer._properties(tree, "m_Colors").get("_TintColor")
    shader = tree["m_Shader"]
    file_id, externals = shader["m_FileID"], material.assets_file.externals
    path_id, cab = _SHADERS["AS/General/Transparent"]
    if (tree["m_CustomRenderQueue"] != 3010 or tree["m_ShaderKeywords"] != "_VERTEX_COLOR_OFF _VERTEX_COLOR_ON"
            or tree["stringTagMap"] or tree["disabledShaderPasses"]
            or shader["m_PathID"] != path_id or not 0 < file_id <= len(externals)
            or externals[file_id - 1].name.lower() != cab
            or any(floats.get(key) != value for key, value in _RENDER_FLOATS.items())
            or tint != dict.fromkeys("rgba", 1) or set(textures) != {"_MainTex"}):
        return False
    # AS/General/Transparent's null MainTex resolves to opaque white.
    main = textures["_MainTex"]
    return (main["m_Texture"] == {"m_FileID": 0, "m_PathID": 0}
            and main["m_Scale"] == dict.fromkeys("xy", 1) and main["m_Offset"] == dict.fromkeys("xy", 0))


def _mesh_source(objects, nodes, path):
    parts = nodes[path]
    if path == _BEAM:
        renderer, fields = parts["SkinnedMeshRenderer"]
        bone = nodes[_BONE]["Transform"][0]
        if ([title._local(objects, renderer, ref, "Transform") for ref in fields["m_Bones"]] != [bone]
                or title._local(objects, renderer, fields["m_RootBone"], "Transform") is not bone
                or fields["m_BlendShapeWeights"] or _authored_trs(parts["Transform"][1]) != title._IDENTITY):
            return None
        owner, geometry = renderer, fields
    else:
        renderer, fields = parts["MeshRenderer"]
        owner, geometry = parts["MeshFilter"]
    materials = fields["m_Materials"]
    if (not fields["m_Enabled"] or len(materials) != 1 or fields["m_RenderingLayerMask"] != 1
            or fields["m_StaticBatchRoot"]["m_PathID"] or fields["m_StaticBatchInfo"]["subMeshCount"]
            or any(fields[key] for key in ("m_SortingLayerID", "m_SortingOrder", "m_RendererPriority"))
            or (fields.get("m_AdditionalVertexStreams") or {}).get("m_PathID")
            or not _white_vertex_material(objects, renderer, materials[0])):
        return None
    return title._local(objects, owner, geometry["m_Mesh"], "Mesh")


def _geometry(reader, is_beam, deadline):
    import numpy as np

    tree = reader.read_typetree()
    vertices, submeshes = tree["m_VertexData"], tree["m_SubMeshes"]
    count, index_count = (84, 390) if is_beam else (81, 420)
    if (tree["m_Name"] != ("Glow_03" if is_beam else "Glow_02")
            or vertices["m_VertexCount"] != count or len(submeshes) != 1
            or (submeshes[0]["indexCount"], submeshes[0]["topology"]) != (index_count, 0)
            or vertices["m_Channels"][3]["format"] != 2 or vertices["m_Channels"][3]["dimension"] != 4
            or tree["m_BindPose"] != ([_IDENTITY_BIND] if is_beam else [])
            or tree["m_MeshCompression"] or tree["m_StreamData"]["size"] or any(tree["m_Shapes"].values())):
        return None
    raw = {}
    name, positions, _, _, faces = viewer._geometry(reader, np.eye(4), rig_data=raw, deadline=deadline)
    if is_beam:
        if (not np.array_equal(raw["indices"], np.zeros((count, 4)))
                or not np.array_equal(raw["weights"], np.tile([1, 0, 0, 0], (count, 1)))):
            return None
    elif raw["indices"] is not None or raw["weights"] is not None:
        return None
    color = np.asarray(raw["colors"])
    if (color.shape != (count, 4) or color.dtype.kind not in "iu" or not (color[:, :3] == 255).all()
            or color[:, 3].min() < 0 or color[:, 3].max() > 255
            or (np.abs(positions) > 100).any() or len(faces) != 1 or faces[0].size != index_count):
        return None
    return {"name": name, "positions": positions.tolist(), "indices": faces[0].reshape(-1).tolist(),
            "alpha": color[:, 3].tolist()}


def _matrices(nodes, poses):
    import numpy as np

    matrices = {}
    for path in _HIERARCHY:
        local = _authored_trs(nodes[path]["Transform"][1])
        local.update(poses.get(path.removeprefix("root/"), {}))
        if not all(.001 <= value <= 100 for value in local["scale"]):
            return None
        matrix = viewer._trs({"m_LocalPosition": dict(zip("xyz", local["translation"])),
                              "m_LocalRotation": dict(zip("xyzw", local["rotation"])),
                              "m_LocalScale": dict(zip("xyz", local["scale"]))})
        if path:
            matrix = matrices[path.rpartition("/")[0]] @ matrix
        if not np.isfinite(matrix).all() or (np.abs(matrix) > 100).any():
            return None
        matrices[path] = matrix
    return matrices


def _prefab(objects, game, deadline):
    from . import mv_studio_stage_spot_animation

    nodes = {}
    if game.peek_name() != _PREFAB or not _hierarchy(objects, game, "", nodes) or nodes.keys() != _HIERARCHY.keys():
        return None
    if any(_authored_trs(nodes[path]["Transform"][1]) != title._IDENTITY for path in ("", "root")):
        return None
    animation = mv_studio_stage_spot_animation.read(objects, *nodes["root"]["Animator"], deadline)
    if animation is None:
        return None
    matrices = _matrices(nodes, animation["poses"])
    if matrices is None:
        return None
    meshes = []
    for path, pivot in ((_BEAM, _BONE), (_FLOOR, _FLOOR)):
        source = _mesh_source(objects, nodes, path)
        mesh = _geometry(source, path == _BEAM, deadline) if source is not None else None
        if mesh is None:
            return None
        # All beam vertices have unity weight on one bone and an identity bind
        # pose, so that bone's world matrix places the original mesh exactly.
        meshes.append({**mesh, "matrix": matrices[pivot].reshape(-1, order="F").tolist(),
                       "tintCurves": animation["tints"][path.removeprefix("root/")]})
    return {"duration": animation["duration"], "meshes": meshes}


def read(objects, mono, tracks, deadline):
    """Return the bounded authored spotlight for a typed Stage Control cue."""
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    results = []
    for track in tracks:
        source = controls.get(track["id"])
        if (source is None or track.get("binding") or track.get("bindings")
                or motion._quality(track["label"]) != "stage_control"):
            continue
        owner, fields = source
        try:
            if (fields["m_Name"] != "par_12_spot" or not fields["m_Enabled"] or len(fields["m_Clips"]) != 1
                    or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                    or not title._group(objects, owner, fields, "control")):
                continue
            event, = track["events"]
            viewer._remaining(deadline)
            values = event["values"]
            if values.get("clipIn") != 0 or values.get("offset") != dict.fromkeys("xyz", 0):
                continue
            control = particles._source(objects, owner, fields, event)
            spotlight = _prefab(objects, control[0], deadline) if control is not None else None
            if spotlight is not None:
                results.append({**spotlight, "trackId": track["id"], "eventId": event["id"]})
        except title._UNSUPPORTED:
            continue
    return results[0] if len(results) == 1 else None
