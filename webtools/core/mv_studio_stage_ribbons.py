"""Read the authored mesh and animation of native stage display ribbons."""

import math
from zlib import crc32

from . import model_animation as animation, model_viewer as viewer
from . import mv_studio_stage_motion as motion, mv_studio_stage_particles as particles
from . import mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_stage_display import _SHADERS


_RIBBONS = ("obi_00", "obi_01", "obi_02", "obi_03")
_FLOATS = {"_BlendSrc": 5, "_BlendDst": 10, "_CullMode": 2, "_SATURATE": 0, "_StencilComp": 3,
           "_StencilPassOp": 0, "_StencilRef": 2, "_StencilZFailOp": 0, "_VERTEX_COLOR": 1,
           "_ZTestMode": 4, "_ZWriteParam": 0}
_PROPERTY_MASK = 0x0FFFFFFF
_TEXTURE_ST = crc32(b"_MainTex_ST") & _PROPERTY_MASK
_TINT = crc32(b"_TintColor") & _PROPERTY_MASK
_ACTIVE = crc32(b"m_IsActive")


def _component_binding(binding):
    if (binding["typeID"], binding["customType"]) != (23, 22):
        return None
    attribute = binding["attribute"]
    property_id, component = attribute & _PROPERTY_MASK, attribute >> 28
    if property_id == _TEXTURE_ST and component < 4:
        return "overlayUV", component
    # The high nibble carries the color-channel tag in addition to RGBA index.
    if property_id == _TINT and 4 <= component <= 7:
        return "overlayTint", component - 4
    return None


def _channels(tree, paths, deadline):
    bindings = tree["m_ClipBindingConstant"]["genericBindings"]
    packed = tree["m_MuscleClip"]["m_Clip"]["data"]
    streamed = packed["m_StreamedClip"]
    if (not 1 <= len(bindings) <= 28 or streamed["curveCount"] > 16 or len(streamed["data"]) > 256
            or packed["m_DenseClip"]["m_CurveCount"] or len(packed["m_ConstantClip"]["data"]) > 48):
        return None
    curves = animation._packed_curves(tree, deadline)
    components, result, offset = {}, {}, 0
    for binding in bindings:
        width = animation._width(binding)
        selected = curves[offset:offset + width]
        offset += width
        path = binding["path"]
        if (binding["isPPtrCurve"] or path not in paths or len(selected) != width or
                any(mode not in ("constant", "cubic") or
                    (mode == "cubic" and not 1 <= len(keys) <= 16) for mode, keys in selected)):
            return None
        binding_type = (binding["typeID"], binding["customType"], binding["attribute"], width)
        if binding_type in ((4, 0, 1, 3), (1, 0, _ACTIVE, 1)):
            kind = "translation" if binding["typeID"] == 4 else "visibility"
            key = (path, kind)
            if key in result:
                return None
            result[key] = selected
            continue
        property_component = _component_binding(binding)
        if width != 1 or property_component is None:
            return None
        kind, component = property_component
        axes = components.setdefault((path, kind), {})
        if component in axes:
            return None
        axes[component] = selected[0]
    if (offset != len(curves) or {path for path, kind in components if kind == "overlayUV"} != paths
            or any(set(axes) != {0, 1, 2, 3} for axes in components.values())):
        return None
    result.update((key, [axes[index] for index in range(4)]) for key, axes in components.items())
    return [{"path": path, "kind": kind, "curves": values} for (path, kind), values in sorted(result.items())]


def _animation(objects, animator, fields, paths, deadline):
    if (not fields["m_Enabled"] or not fields["m_HasTransformHierarchy"] or fields["m_Avatar"]["m_PathID"]
            or any(fields[key] for key in ("m_UpdateMode", "m_CullingMode", "m_ApplyRootMotion",
                                           "m_KeepAnimatorControllerStateOnDisable"))):
        return None
    controller = title._local(objects, animator, fields["m_Controller"], "AnimatorController")
    if controller is None:
        return None
    tree = controller.read_typetree()
    graph = tree["m_Controller"]
    layer, = graph["m_LayerArray"]
    machine, = graph["m_StateMachineArray"]
    machine = machine["data"]
    state, = machine["m_StateConstantArray"]
    state = state["data"]
    blend, = state["m_BlendTreeConstantArray"]
    node, = blend["data"]["m_NodeArray"]
    node = node["data"]
    if (tree["m_StateMachineBehaviours"] or graph["m_Values"]["data"]["m_ValueArray"]
            or layer["data"]["m_IKPass"] or machine["m_DefaultState"] != 0
            or machine["m_AnyStateTransitionConstantArray"] or state["m_Speed"] != 1 or not state["m_Loop"]
            or state["m_BlendTreeConstantIndexArray"] != [0]
            or any(state[key] for key in ("m_TransitionConstantArray", "m_SpeedParamID", "m_MirrorParamID",
                                         "m_CycleOffsetParamID", "m_TimeParamID", "m_Mirror",
                                         "m_CycleOffset", "m_IKOnFeet"))
            or node["m_ClipID"] != 0 or any(node[key] for key in
                ("m_BlendType", "m_ChildIndices", "m_CycleOffset", "m_Mirror"))):
        return None
    ref, = tree["m_AnimationClips"]
    clip = title._local(objects, controller, ref, "AnimationClip")
    if clip is None:
        return None
    raw = clip.read_typetree()
    if any(raw.get(field) for field in ("m_Legacy", "m_Compressed", "m_HasGenericRootTransform",
                                         "m_HasMotionFloatCurves", "m_Events", "m_PPtrCurves",
                                         "m_CompressedRotationCurves")):
        return None
    muscle = raw["m_MuscleClip"]
    duration = muscle["m_StopTime"]
    if (muscle["m_StartTime"] != 0 or not 0 < duration <= 90 or not muscle["m_LoopTime"]
            or muscle["m_CycleOffset"] or muscle["m_Mirror"]):
        return None
    channels = _channels(raw, paths, deadline)
    if channels is None:
        return None
    return {"start": 0, "duration": duration, "loop": True, "channels": channels}


def _material(objects, renderer, ref):
    reader = title._local(objects, renderer, ref, "Material")
    if reader is None:
        return None
    tree = reader.read_typetree()
    shader = tree["m_Shader"]
    file_id, externals = shader["m_FileID"], reader.assets_file.externals
    path_id, cab = _SHADERS["AS/General/Transparent"]
    if (tree["m_CustomRenderQueue"] != 2900 or tree["m_ShaderKeywords"] != "_VERTEX_COLOR_ON"
            or viewer._properties(tree, "m_Floats") != _FLOATS or shader["m_PathID"] != path_id
            or not 0 < file_id <= len(externals) or externals[file_id - 1].name.lower() != cab):
        return None
    color = viewer._properties(tree, "m_Colors")["_TintColor"]
    main = viewer._properties(tree, "m_TexEnvs")["_MainTex"]
    tint = [color[axis] for axis in "rgba"]
    uv = [main[key][axis] for key in ("m_Scale", "m_Offset") for axis in "xy"]
    texture = title._local(objects, reader, main["m_Texture"], "Texture2D")
    if texture is None or any(type(value) not in (int, float) or not math.isfinite(value) for value in tint + uv):
        return None
    return {"tint": tint, "uv": uv, "queue": 2900, "cull": 2}, texture


def _pose(fields):
    trs = _authored_trs(fields)
    return {"position": trs["translation"], "rotation": trs["rotation"], "scale": trs["scale"]}


def _mesh(objects, game):
    row = title._components(objects, game, {"Transform", "MeshFilter", "MeshRenderer"}, require_active=False)
    if row is None:
        return None
    tree, parts = row
    transform = parts["Transform"][1]
    renderer, render = parts["MeshRenderer"]
    mesh_filter, mesh_fields = parts["MeshFilter"]
    if (transform["m_Children"] or not render["m_Enabled"] or len(render["m_Materials"]) != 1
            or any(render[key] for key in ("m_CastShadows", "m_SortingLayerID", "m_SortingOrder", "m_RendererPriority"))
            or render["m_AdditionalVertexStreams"]["m_PathID"]):
        return None
    source = title._local(objects, mesh_filter, mesh_fields["m_Mesh"], "Mesh")
    surface = _material(objects, renderer, render["m_Materials"][0])
    if source is None or surface is None:
        return None
    name = tree["m_Name"]
    material, texture = surface
    return {**_pose(transform), "path": animation.path_hash(f"main/{name}"), "name": name,
            "active": bool(tree["m_IsActive"]), "material": material}, source, texture


def _geometry(reader, deadline):
    import numpy as np

    mesh = reader.read()
    if (mesh.m_VertexData.m_VertexCount != 9 or len(mesh.m_SubMeshes) != 1
            or (mesh.m_SubMeshes[0].indexCount, mesh.m_SubMeshes[0].topology) != (24, 0)):
        return None
    rig = {}
    _, positions, _, uv, faces = viewer._geometry(reader, np.eye(4), rig_data=rig, deadline=deadline)
    # The source mesh leaves COLOR absent. Both stock Gamma players use the
    # shader's default white vertex tint for this stream.
    if uv is None or rig["colors"] is not None or len(faces) != 1 or len(faces[0]) != 8:
        return None
    return {"positions": positions.tolist(), "uv": uv.tolist(), "indices": faces[0].reshape(-1).tolist()}


def _prefab(objects, game, deadline):
    root = title._components(objects, game, {"Transform"})
    if root is None:
        return None
    transform, fields = root[1]["Transform"]
    if (len(fields["m_Children"]) != 1 or _authored_trs(fields) != title._IDENTITY
            or fields["m_Father"]["m_PathID"]):
        return None
    pivot = title._transform_child(objects, transform, fields["m_Children"][0])
    row = title._components(objects, pivot, {"Transform", "Animator"}) if pivot is not None else None
    if row is None:
        return None
    _, parts = row
    transform, fields = parts["Transform"]
    if len(fields["m_Children"]) != 1 or _authored_trs(fields) != title._IDENTITY:
        return None
    child = title._transform_child(objects, transform, fields["m_Children"][0])
    row = title._components(objects, child, {"Transform"}) if child is not None else None
    if row is None or row[0]["m_Name"] != "main":
        return None
    transform, fields = row[1]["Transform"]
    if len(fields["m_Children"]) != 5:
        return None
    found, shine = {}, False
    for ref in fields["m_Children"]:
        game = title._transform_child(objects, transform, ref)
        if game is None:
            return None
        name = game.peek_name()
        if name == "shine":
            if shine or title._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"}) is None:
                return None
            shine = True
            continue
        if name not in _RIBBONS or name in found:
            return None
        mesh = _mesh(objects, game)
        if mesh is None:
            return None
        found[name] = mesh
    if not shine or found.keys() != set(_RIBBONS):
        return None
    meshes, geometry, textures = zip(*(found[name] for name in _RIBBONS))
    if len({viewer._key(source) for source in geometry}) != 1 or len({viewer._key(tex) for tex in textures}) != 2:
        return None
    paths = {mesh["path"] for mesh in meshes}
    if len(paths) != len(meshes):
        return None
    authored = _animation(objects, *parts["Animator"], paths, deadline)
    if authored is None:
        return None
    return {"parent": _pose(fields), "animation": authored}, geometry[0], list(zip(meshes, textures))


def read(objects, mono, tracks, deadline):
    """Return the bounded ribbon mesh stage preview from original local assets."""
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    textures, indexed, cues, geometry = [], {}, [], None
    for track in tracks:
        source = controls.get(track["id"])
        if source is None or track.get("binding") or track.get("bindings") or motion._quality(track["label"]) != "stage_display":
            continue
        owner, fields = source
        try:
            if (not fields["m_Enabled"] or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                    or not title._group(objects, owner, fields)):
                continue
        except title._UNSUPPORTED:
            continue
        for event in track["events"]:
            viewer._remaining(deadline)
            try:
                values = event["values"]
                if (values.get("clipIn") != 0 or values.get("offset") != dict(x=0, y=0, z=0)
                        or any(values.get(key) for key in ("easeIn", "easeOut", "blendIn", "blendOut"))):
                    continue
                source = particles._source(objects, owner, fields, event)
                if source is None:
                    continue
                original = _prefab(objects, source[0], deadline)
                if original is None or event["duration"] > original[0]["animation"]["duration"]:
                    continue
                cue, mesh, leaves = original
                if len(cues) >= 2 or (geometry is not None and geometry[0] != viewer._key(mesh)):
                    return None
                shape = geometry[1] if geometry is not None else _geometry(mesh, deadline)
                if shape is None:
                    continue
                pending, meshes, next_indices = [], [], dict(indexed)
                for leaf, reader in leaves:
                    key = viewer._key(reader)
                    if key not in next_indices:
                        if len(textures) + len(pending) >= 2:
                            break
                        chain = particles._texture(reader, deadline)
                        if not chain or chain[0]["width"] != 512:
                            break
                        next_indices[key] = len(textures) + len(pending)
                        pending.append(chain)
                    meshes.append({**leaf, "texture": next_indices[key]})
                else:
                    indexed = next_indices
                    textures.extend(pending)
                    cues.append({**cue, "trackId": track["id"], "eventId": event["id"], "meshes": meshes})
                    geometry = (viewer._key(mesh), shape)
            except title._UNSUPPORTED:
                continue
    return {"geometry": geometry[1], "textures": textures, "cues": cues} if cues else None
