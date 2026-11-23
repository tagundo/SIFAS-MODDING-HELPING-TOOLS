"""Resolve a native animated fan to its performer and authored bone."""

import math
import re
from zlib import crc32

from . import model_animation, model_materials, model_viewer as viewer, mv_studio_timeline


_MEMBER_PROP = re.compile(
    r"/EntryPoint/Live/Members/(ske_[A-Za-z0-9_]+)/(Member[1-9][0-9]*)/Model/"
    r"([A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*)/(chp[0-9]+)\Z"
)
_FAN_ANGLE = crc32(b"clipUV2Angle")
_FAN_SHADER = ("cab-2e396210aff4c20f7175085dc1e3e4e6", -8442881240486637179)
_FAN_TEXTURES = {"_MainTex": 1024, "_RimlightTex": 256}


def bindings(tracks):
    """Use the same exact target for animation and activation."""
    activation = {}
    for track in tracks:
        target = track.get("binding")
        if target and track.get("nativeClass") == "ActivationTrack":
            activation.setdefault(target, []).append(track["id"])
    result = []
    for track in tracks:
        target = track.get("binding") or ""
        match = _MEMBER_PROP.fullmatch(target)
        if not match or track.get("nativeClass") != "AnimationTrack" or target not in activation:
            continue
        skeleton, member, bone, prop = match.groups()
        clips = {
            event["id"]: event["values"]["animation"]
            for event in track["events"] if "animation" in event["values"]
        }
        if clips:
            result.append({
                "track": track["id"], "activation": activation[target], "clips": clips,
                "member": int(member.removeprefix("Member")), "bone": bone,
                "path": [skeleton, member, "Model", *bone.split("/"), prop],
            })
    return result


def _find_transform(scene, names):
    matches = []
    for final in scene.transforms.values():
        game_object = viewer._ref(final, scene.tree(final).get("m_GameObject"))
        if game_object is None or scene.name(game_object) != names[-1]:
            continue
        current = final
        for name in reversed(names):
            if current is None:
                break
            record = scene.tree(current)
            current_object = viewer._ref(current, record.get("m_GameObject"))
            if current_object is None or scene.name(current_object) != name:
                break
            current = viewer._ref(current, record.get("m_Father"))
        else:
            if current is None:
                matches.append(final)
    return matches[0] if len(matches) == 1 else None


def _fan(scene, target):
    for obj in scene.env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = scene.tree(obj)
        if viewer._ref(obj, tree.get("m_GameObject")) != target:
            continue
        script = viewer._ref(obj, tree.get("m_Script"))
        if script is None or scene.tree(script).get("m_ClassName") != "LiveMemberPropFan":
            continue
        renderer = viewer._ref(obj, tree.get("meshRenderer"))
        if renderer is not None and renderer.type.name == "MeshRenderer":
            return renderer, model_animation._finite(tree.get("clipUV2Angle"))
    raise ValueError("The selected hand prop has no native fan renderer.")


def _angle_curves(native, source_name, clips, deadline):
    _, objects, _ = mv_studio_timeline._read(native, source_name, deadline)
    indexed = {mv_studio_timeline._id(key): value for key, value in objects.items()}
    curves = {}
    for event, identity in clips.items():
        clip = indexed.get(identity)
        if clip is None or clip.type.name != "AnimationClip":
            continue
        tree = clip.read_typetree()
        bindings = tree.get("m_ClipBindingConstant", {}).get("genericBindings", ())
        matches, offset = [], 0
        for binding in bindings:
            width = model_animation._width(binding)
            if (width == 1 and binding.get("typeID") == 114 and binding.get("path") == 0
                    and binding.get("attribute") == _FAN_ANGLE and not binding.get("isPPtrCurve")):
                script = viewer._ref(clip, binding.get("script"))
                if script is not None and script.read_typetree().get("m_ClassName") in (
                        "LiveMemberPropBase", "LiveMemberPropFan"):
                    matches.append(offset)
            offset += width
        if len(matches) != 1:
            continue
        values = model_animation._packed_curves(tree, deadline)
        if len(values) != offset:
            continue
        mode, keys = values[matches[0]]
        if mode != "constant" and (not keys or len(keys) > 4096):
            continue
        muscle = tree.get("m_MuscleClip", {})
        first = model_animation._finite(muscle.get("m_StartTime"))
        last = model_animation._finite(muscle.get("m_StopTime"))
        if not 0 <= first <= last <= 3600:
            continue
        curves[event] = {"mode": mode, "keys": keys, "first": first, "last": last}
    return curves


def _attach_fan_material(scene, materials, obj, tree, exported):
    """Export the verified native MainProp and unexpanded OutlineProp inputs."""
    if (set(tree.get("m_ShaderKeywords", "").split()) != {"_RIMLIGHT_ON", "_UV2ANGLE_ON"}
            or tree.get("m_CustomRenderQueue") != -1 or tree.get("disabledShaderPasses")):
        return False
    if mv_studio_timeline._pointer(obj, tree.get("m_Shader")) != _FAN_SHADER:
        return False
    if not any(candidate.type.name == "AssetBundle" and candidate.assets_file is obj.assets_file
               and "asmemberprop.shader.unity3d" in scene.tree(candidate).get("m_Dependencies", [])
               for candidate in scene.env.objects):
        return False
    floats = viewer._properties(tree, "m_Floats")
    if any(floats.get(name) != value for name, value in (
            ("_CullMode", 2), ("_OutlineStencilComp", 8), ("_ZWrite", 1),
            ("_Mode", 0), ("_SrcBlend", 1), ("_DstBlend", 0))):
        return False
    envs = viewer._properties(tree, "m_TexEnvs")
    for name, size in _FAN_TEXTURES.items():
        source = envs.get(name, {})
        target = viewer._ref(obj, source.get("m_Texture"))
        if target is None or target.assets_file is not obj.assets_file or target.type.name != "Texture2D":
            return False
        texture = target.read()
        if (texture.m_Width, texture.m_Height, texture.m_MipCount) != (size, size, size.bit_length()):
            return False
        if [source.get("m_Scale", {}).get(axis) for axis in "xy"] != [1, 1] or any(
                source.get("m_Offset", {}).get(axis) != 0 for axis in "xy"):
            return False
    # Keep the original unlit export if an optional source mip cannot be decoded.
    glb = materials.glb
    data_size = len(glb.data)
    tables = {name: len(glb.doc[name]) for name in ("bufferViews", "images", "textures", "samplers")}
    saved_textures, pixels, texture_count = dict(materials.textures), materials.pixels, scene.stats["textures"]
    complete = False
    try:
        metadata = model_materials.attach_member_metadata(
            scene, obj, tree, {}, materials.texture, mip_resolver=materials.mip_textures)
        # The hand-prop export keeps the rule it was verified with (the fan's
        # authored rim switch plus a resolved rim texture); it does not follow
        # the AS/Member rule that exports the rim texture for every material.
        complete = (model_materials.authored_rimlight(metadata) and metadata["features"]["rimlight"]
                    and not metadata["limitations"]
                    and all(len(metadata["textures"].get(name, {}).get("mipmaps", ())) == size.bit_length()
                            for name, size in _FAN_TEXTURES.items()))
    finally:
        if not complete:
            del glb.data[data_size:]
            for name, count in tables.items():
                del glb.doc[name][count:]
            materials.textures, materials.pixels = saved_textures, pixels
            scene.stats["textures"] = texture_count
    if not complete:
        return False
    # The prop Main pass shares the supported AS/Member equations. The
    # distinct shader identity selects its original back-face pass in Studio.
    metadata["shader"] = "AS/MemberProp"
    exported.setdefault("extras", {})["sifas"] = metadata
    return True


def _mesh(scene, glb, renderer, hand):
    import numpy as np
    from .model_mesh import PreviewMeshHandler

    tree = scene.tree(renderer)
    game_object = viewer._ref(renderer, tree.get("m_GameObject"))
    mesh = scene.filters.get(viewer._key(game_object)) if game_object is not None else None
    if mesh is None or mesh.type.name != "Mesh":
        raise ValueError("The selected fan has no native geometry.")
    transform = scene.transforms.get(viewer._key(game_object))
    if transform is None:
        raise ValueError("The selected fan has no native transform.")
    # Keep vertex positions in mesh space so the authored UV2 rotation occurs
    # before applying the fan's original local transform below the hand.
    name, positions, normals, uv, parts = viewer._geometry(mesh, np.eye(4))
    handler = PreviewMeshHandler(mesh.read())
    handler.process()
    uv2 = np.asarray(handler.m_UV1, dtype=np.float32)
    if uv is None or uv2.shape != (len(positions), 2) or not np.isfinite(uv2).all():
        raise ValueError("The selected fan has no authored UV2 vertex data.")
    attributes = {"POSITION": glb.attribute(positions, "VEC3", bounds=True),
                  "NORMAL": glb.attribute(normals, "VEC3"),
                  "TEXCOORD_0": glb.attribute(uv, "VEC2"),
                  "_MV_FAN_UV": glb.attribute(uv2, "VEC2")}
    colors = np.asarray(handler.m_Colors, dtype=np.float32)
    native_colors = (colors.shape == (len(positions), 4) and np.isfinite(colors).all()
                     and (colors >= 0).all() and (colors <= 1).all())
    materials = viewer._Materials(scene, glb)
    refs = tree.get("m_Materials", [])
    if not refs:
        raise ValueError("The selected fan has no native material.")
    primitives, limits, evaluated_materials = [], [], set()
    for index, indices in enumerate(parts):
        if not len(indices):
            continue
        obj = viewer._ref(renderer, refs[min(index, len(refs) - 1)])
        if obj is None or obj.type.name != "Material":
            raise ValueError("The selected fan material is unavailable.")
        original = scene.tree(obj)
        floats = viewer._properties(original, "m_Floats")
        axis = viewer._properties(original, "m_Colors").get("_UV2Axis", {})
        limit = floats.get("_UV2Limit")
        if (floats.get("_UV2ANGLE") != 1 or [axis.get(name) for name in "rgb"] != [0, 1, 0]
                or type(limit) not in (int, float) or not math.isfinite(limit) or not 0 <= limit <= 360):
            raise ValueError("The selected fan shader has unsupported angle settings.")
        material = materials.material(obj)
        if native_colors and material not in evaluated_materials:
            evaluated_materials.add(material)
            try:
                native_material = _attach_fan_material(scene, materials, obj, original, glb.doc["materials"][material])
            except (ValueError, TypeError, KeyError, AttributeError, OSError):
                native_material = False
            if native_material and "_SIFAS_COLOR" not in attributes:
                attributes["_SIFAS_COLOR"] = glb.attribute(colors, "VEC4")
        primitives.append({
            "attributes": attributes, "material": material, "mode": 4,
            "indices": glb.attribute(indices.reshape(-1), "SCALAR", 5123 if len(positions) <= 65535 else 5125),
        })
        limits.append(limit)
    if not primitives or len(set(limits)) != 1:
        raise ValueError("The selected fan uses incompatible angle settings.")
    glb.doc["meshes"].append({"name": name, "primitives": primitives})
    mirror = np.diag([-1., 1., 1., 1.])
    local = mirror @ np.linalg.inv(scene.world(hand)) @ scene.world(transform) @ mirror
    if not np.isfinite(local).all():
        raise ValueError("The selected fan has an invalid hand attachment transform.")
    glb.doc["nodes"].append({"name": name, "mesh": 0, "matrix": local.T.reshape(-1).tolist()})
    glb.doc["scenes"][0]["nodes"].append(0)
    return limits[0]


def preview(path, native, source_name, binding, deadline):
    """Read matching serialized objects and emit one hand-local prop GLB."""
    scene = viewer._Scene(viewer._environment([str(path)], deadline), deadline)
    prop = _find_transform(scene, binding["path"])
    hand = _find_transform(scene, binding["path"][:-1])
    if prop is None or hand is None:
        raise ValueError("The timeline's original fan attachment is missing from the prop bundle.")
    target = viewer._ref(prop, scene.tree(prop).get("m_GameObject"))
    renderer, default = _fan(scene, target)
    curves = _angle_curves(native, source_name, binding["clips"], deadline)
    if not curves:
        raise ValueError("The selected fan has no playable native opening curve.")
    glb = viewer._Glb()
    limit = _mesh(scene, glb, renderer, hand)
    return glb.finish(), {
        "kind": "fan", "member": binding["member"], "bone": binding["bone"],
        "binding": "/EntryPoint/Live/Members/" + "/".join(binding["path"]),
        "track": binding["track"], "activation": binding["activation"], "curves": curves,
        "defaultAngle": default, "defaultVisible": scene.active(target), "limit": limit,
    }
