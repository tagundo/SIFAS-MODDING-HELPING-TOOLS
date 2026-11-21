"""Read the supported native world-space display title prefab and animator."""

import base64
import struct
import subprocess

from . import decode, model_animation, model_viewer as viewer
from . import mv_studio_stage_motion as motion, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_stage_display import _SHADERS


_NAMESPACE = ("Assembly-CSharp.dll", "LLAS.Components.Timeline")
_IDENTITY = {"translation": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]}
_MAX_IMAGE_BYTES = 512 * 1024
_UNSUPPORTED = (ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, OSError, EOFError,
                struct.error, subprocess.SubprocessError)
# The vertices and UVs of built-in mesh 10210 match in Android and iOS.
# Use the same reflected basis, triangle winding and V coordinate as the GLB exporter.
_QUAD = {
    "positions": [[.5, -.5, -3.0616168005906746e-17], [-.5, .5, 3.0616168005906746e-17],
                  [-.5, -.5, -3.0616168005906746e-17], [.5, .5, 3.0616168005906746e-17]],
    "uv": [[0, 1], [1, 0], [1, 1], [0, 0]],
    "indices": [0, 2, 1, 1, 3, 0],
}


def _local(objects, owner, ref, kind=None):
    if not isinstance(ref, dict) or ref.get("m_FileID") != 0:
        return None
    target = objects.get(timeline._pointer(owner, ref))
    return target if target is not None and (kind is None or target.type.name == kind) else None


def _declared(objects, owner, tree, identity):
    script = _local(objects, owner, tree.get("m_Script"), "MonoScript")
    declaration = script.read_typetree() if script is not None else {}
    return tuple(declaration.get(field) for field in ("m_AssemblyName", "m_Namespace", "m_ClassName")) == identity


def _group(objects, owner, tree):
    groups = []
    for _ in range(3):
        child = owner
        owner = _local(objects, owner, tree.get("m_Parent"), "MonoBehaviour")
        if owner is None:
            return False
        tree = owner.read_typetree()
        if (tree.get("m_Muted") or
                not _declared(objects, owner, tree, ("UnityEngine.Timeline.dll", "UnityEngine.Timeline", "GroupTrack"))
                or all(_local(objects, owner, ref, "MonoBehaviour") is not child for ref in tree.get("m_Children", []))):
            return False
        groups.append(tree["m_Name"].replace(" ", "").lower())
    root = _local(objects, owner, tree.get("m_Parent"), "MonoBehaviour")
    if groups[0] != "display" or groups[2] != "stageeffect" or root is None:
        return False
    tree = root.read_typetree()
    return (_declared(objects, root, tree, ("UnityEngine.Timeline.dll", "UnityEngine.Timeline", "TimelineAsset"))
            and any(_local(objects, root, ref, "MonoBehaviour") is owner for ref in tree.get("m_Tracks", [])))


def _components(objects, game, types, *, require_active=True):
    tree = game.read_typetree()
    refs = tree.get("m_Component", [])
    if tree.get("m_Layer") != 26 or (require_active and not tree.get("m_IsActive")) or len(refs) != len(types):
        return None
    components = {}
    for entry in refs:
        component = _local(objects, game, entry.get("component"))
        if component is None or component.type.name not in types or component.type.name in components:
            return None
        fields = component.read_typetree()
        if _local(objects, component, fields.get("m_GameObject"), "GameObject") is not game:
            return None
        components[component.type.name] = component, fields
    return tree, components


def _transform_child(objects, transform, ref):
    child = _local(objects, transform, ref, "Transform")
    if child is None:
        return None
    fields = child.read_typetree()
    if _local(objects, child, fields.get("m_Father"), "Transform") is not transform:
        return None
    game = _local(objects, child, fields.get("m_GameObject"), "GameObject")
    if game is not None and any(_local(objects, game, entry.get("component"), "Transform") is child
                                for entry in game.read_typetree().get("m_Component", [])):
        return game
    return None


def _mesh(objects, game):
    row = _components(objects, game, {"Transform", "MeshFilter", "MeshRenderer"})
    if row is None:
        return None
    tree, components = row
    mesh, mesh_fields = components["MeshFilter"]
    renderer, fields = components["MeshRenderer"]
    _, transform = components["Transform"]
    ref = mesh_fields.get("m_Mesh", {})
    file_id = ref.get("m_FileID", 0)
    externals = mesh.assets_file.externals
    materials = fields.get("m_Materials", [])
    name = tree.get("m_Name", "")
    if (transform.get("m_Children") or not 0 < len(name) <= 96 or not name.isprintable() or "/" in name
            or ref.get("m_PathID") != 10210 or not 0 < file_id <= len(externals)
            or externals[file_id - 1].path.replace("\\", "/").lower() != "library/unity default resources"
            or not fields.get("m_Enabled") or len(materials) != 1
            or any(fields.get(key) for key in ("m_CastShadows", "m_SortingLayerID", "m_SortingOrder", "m_RendererPriority"))
            or (fields.get("m_AdditionalVertexStreams") or {}).get("m_PathID")):
        return None
    material = _local(objects, renderer, materials[0], "Material")
    if material is None:
        return None
    trs = _authored_trs(transform)
    return {"path": model_animation.path_hash(name), "name": name, "position": trs["translation"],
            "rotation": trs["rotation"], "scale": trs["scale"]}, material


def _animator(objects, obj, fields, deadline):
    if (not fields.get("m_Enabled") or not fields.get("m_HasTransformHierarchy") or
            (fields.get("m_Avatar") or {}).get("m_PathID") or any(fields.get(key) for key in
            ("m_UpdateMode", "m_CullingMode", "m_ApplyRootMotion", "m_KeepAnimatorControllerStateOnDisable"))):
        return None
    controller = _local(objects, obj, fields.get("m_Controller"), "AnimatorController")
    if controller is None:
        return None
    tree = controller.read_typetree()
    fields = tree["m_Controller"]
    layer, = fields["m_LayerArray"]
    machine, = fields["m_StateMachineArray"]
    machine = machine["data"]
    state, = machine["m_StateConstantArray"]
    state = state["data"]
    blend, = state["m_BlendTreeConstantArray"]
    node, = blend["data"]["m_NodeArray"]
    node = node["data"]
    if (tree.get("m_StateMachineBehaviours") or fields["m_Values"]["data"]["m_ValueArray"]
            or layer["data"].get("m_IKPass") or machine.get("m_DefaultState") != 0
            or machine.get("m_AnyStateTransitionConstantArray") or state.get("m_Speed") != 1
            or state.get("m_BlendTreeConstantIndexArray") != [0]
            or any(state.get(key) for key in ("m_TransitionConstantArray", "m_SpeedParamID", "m_MirrorParamID",
                                              "m_CycleOffsetParamID", "m_TimeParamID", "m_Loop", "m_Mirror",
                                              "m_CycleOffset", "m_IKOnFeet"))
            or node.get("m_ClipID") != 0 or any(node.get(key) for key in
                ("m_BlendType", "m_ChildIndices", "m_CycleOffset", "m_Mirror"))):
        return None
    ref, = tree["m_AnimationClips"]
    clip = _local(objects, controller, ref, "AnimationClip")
    return motion._read_clip(clip, deadline, overlay=True) if clip is not None else None


def _prefab(objects, game, deadline):
    root = _components(objects, game, {"Transform"})
    if root is None:
        return None
    tr, fields = root[1]["Transform"]
    if _authored_trs(fields) != _IDENTITY or (fields.get("m_Father") or {}).get("m_PathID"):
        return None
    child, = fields["m_Children"]
    pivot = _transform_child(objects, tr, child)
    row = _components(objects, pivot, {"Transform", "Animator"}) if pivot is not None else None
    if row is None:
        return None
    tr, fields = row[1]["Transform"]
    if _authored_trs(fields) != _IDENTITY or len(fields["m_Children"]) != 2:
        return None
    meshes, materials = [], []
    for ref in fields["m_Children"]:
        go = _transform_child(objects, tr, ref)
        mesh = _mesh(objects, go) if go is not None else None
        if mesh is None:
            return None
        meshes.append(mesh[0])
        materials.append(mesh[1])
    if materials[0] is not materials[1]:
        return None
    result = _animator(objects, *row[1]["Animator"], deadline)
    paths = {mesh["path"] for mesh in meshes}
    if result is None or len(paths) != 2:
        return None
    animation, cost = result
    channels = animation["channels"]
    if (animation["start"] != 0 or not 0 < animation["duration"] <= 15 or animation["loop"] or cost > 2048
            or len(channels) != 2 or {(row["path"], row["kind"]) for row in channels} !=
            {(path, "overlayUV") for path in paths}):
        return None
    return meshes, materials[0], animation


def _material(objects, item):
    tree = item.read_typetree()
    shader = tree.get("m_Shader", {})
    path_id, cab = _SHADERS["AS/General/Transparent"]
    file_id = shader.get("m_FileID", 0)
    externals = item.assets_file.externals
    expected = {"_BlendSrc": 5, "_BlendDst": 10, "_CullMode": 0, "_SATURATE": 0, "_StencilComp": 3,
                "_StencilPassOp": 0, "_StencilRef": 2, "_StencilZFailOp": 0, "_VERTEX_COLOR": 1,
                "_ZTestMode": 4, "_ZWriteParam": 0}
    if (tree.get("m_CustomRenderQueue") != 2900 or tree.get("m_ShaderKeywords") != "_VERTEX_COLOR_ON"
            or viewer._properties(tree, "m_Floats") != expected
            or shader.get("m_PathID") != path_id or not 0 < file_id <= len(externals)
            or externals[file_id - 1].path.replace("\\", "/").rsplit("/", 1)[-1].lower() != cab):
        return None
    color = viewer._properties(tree, "m_Colors").get("_TintColor", {})
    main = viewer._properties(tree, "m_TexEnvs").get("_MainTex", {})
    tint = [color.get(axis) for axis in "rgba"]
    uv = [main.get("m_Scale", {}).get(axis) for axis in "xy"] + [
        main.get("m_Offset", {}).get(axis) for axis in "xy"]
    texture = _local(objects, item, main.get("m_Texture"), "Texture2D")
    if texture is None or tint != [1, 1, 1, 1] or uv != [1, 1, 0, 0]:
        return None
    return {"tint": tint, "uv": uv, "queue": 2900}, texture


def _texture(reader, deadline):
    texture = reader.read()
    if (texture.m_TextureFormat, texture.m_Width, texture.m_Height, texture.m_MipCount) != (65, 512, 512, 10):
        return None
    settings = texture.m_TextureSettings
    if (settings.m_FilterMode, settings.m_WrapU, settings.m_WrapV) != (1, 0, 0):
        return None
    stream = texture.m_StreamData
    if stream is not None and stream.size:
        # Resolve only the resource embedded in this bundle, without external dependency lookup.
        cab = reader.assets_file.name
        path = f"archive:/{cab}/{cab}.resS"
        resource = reader.assets_file.environment.get_cab(f"{cab}.resS")
        if (stream.path != path or not 0 < stream.size <= _MAX_IMAGE_BYTES or stream.offset < 0
                or stream.offset + stream.size > getattr(resource, "Length", 0)):
            return None
    elif not 0 < len(texture.image_data) <= _MAX_IMAGE_BYTES:
        return None
    with decode._android_image(texture, deadline, stage=True) as image:
        png = viewer._png_texture(image, deadline)
    if len(png) <= _MAX_IMAGE_BYTES:
        return {"png": base64.b64encode(png).decode("ascii"), "width": 512, "height": 512}
    return None


def _playable(objects, owner, tree, event):
    values = event["values"]
    if (values.get("playableClass") != "CustomControlClip" or values.get("timeScale") != 1
            or any(values.get(key) for key in ("clipIn", "easeIn", "easeOut", "blendIn", "blendOut",
                "preExtrapolationMode", "postExtrapolationMode")) or not 0 < event["duration"] <= 15):
        return None
    clip = tree["m_Clips"][int(event["id"].rsplit(":", 1)[1])]
    asset = _local(objects, owner, clip.get("m_Asset"), "MonoBehaviour")
    if asset is None or (clip.get("m_AnimationCurves") or {}).get("m_PathID"):
        return None
    fields = asset.read_typetree()
    if (not _declared(objects, asset, fields, (*_NAMESPACE, "CustomControlClip")) or not fields.get("m_Enabled")
            or fields.get("weight") != 1 or fields.get("offset") != dict(x=0, y=0, z=0)):
        return None
    return _local(objects, asset, fields.get("prefabGameObject"), "GameObject")


def _attach_particles(result, candidates, mesh_texture, deadline):
    if not 0 < len(candidates) <= 4:
        return
    textures = result["textures"]
    indexed = {viewer._key(mesh_texture): 0}
    particle_cues = []
    for track_id, event_id, sources in candidates:
        pending, emitters, indices = [], [], dict(indexed)
        try:
            for emitter, reader in sources:
                key = viewer._key(reader)
                if key not in indices:
                    image = _texture(reader, deadline)
                    if image is None or len(textures) + len(pending) >= 8:
                        break
                    indices[key] = len(textures) + len(pending)
                    pending.append(image)
                emitters.append({**emitter, "texture": indices[key]})
            else:
                textures.extend(pending)
                indexed = indices
                particle_cues.append({"trackId": track_id, "eventId": event_id, "emitters": emitters})
        except _UNSUPPORTED:
            continue
    if particle_cues:
        result["particles"] = particle_cues


def read(objects, mono, tracks, deadline):
    """Resolve a native mesh title and any supported deterministic companion particle cues."""
    from . import mv_studio_stage_title_particles as particles

    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    cue, texture, particle_cues = None, None, []
    for track in tracks:
        source = controls.get(track["id"])
        if source is None or track.get("binding") or track.get("bindings") or motion._quality(track["label"]) != "stage_display":
            continue
        owner, tree = source
        viewer._remaining(deadline)
        try:
            if (not tree.get("m_Enabled") or not _declared(objects, owner, tree, (*_NAMESPACE, "CustomControlTrack"))
                    or not _group(objects, owner, tree)):
                continue
        except _UNSUPPORTED:
            continue
        for event in track["events"]:
            viewer._remaining(deadline)
            try:
                game = _playable(objects, owner, tree, event)
                if game is None:
                    continue
                mesh = _prefab(objects, game, deadline)
                if mesh is not None:
                    meshes, original, animation = mesh
                    material = _material(objects, original)
                    if material is not None:
                        if cue is not None:
                            return None
                        fields, texture = material
                        cue = {"trackId": track["id"], "eventId": event["id"], "texture": 0, "material": fields,
                               "meshes": meshes, "animation": animation}
            except _UNSUPPORTED:
                continue
            if len(particle_cues) > 4:
                continue
            try:
                sources = particles.read(objects, game, deadline)
            except _UNSUPPORTED:
                continue
            if sources is not None:
                particle_cues.append((track["id"], event["id"], sources))
    if cue is None:
        return None
    try:
        image = _texture(texture, deadline)
    except _UNSUPPORTED:
        return None
    if image is None:
        return None
    result = {"geometry": _QUAD, "textures": [image], "cues": [cue]}
    _attach_particles(result, particle_cues, texture, deadline)
    return result
