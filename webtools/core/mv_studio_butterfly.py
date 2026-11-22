"""Read the original principal butterfly meshes from Aion's Expert cues."""

import math

from . import model_animation as animation, model_viewer as viewer
from . import mv_studio_butterfly_glow
from . import mv_studio_stage_particles as particles, mv_studio_stage_title as title
from . import mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_speed_back_animation import _clip
from .mv_studio_stage_title_particles import _constant, _float32


_TRACK = "StageEffect/Expert/Control/par_13_butterfly"
_FINALE = "StageEffect/Expert/Control/par_14_butterfly"
_NODES = (("prefab", {"Transform"}), ("root", {"Transform", "Animator"}),
          ("ctrl", {"Transform"}), ("butterfly", {"Transform", "ParticleSystem", "ParticleSystemRenderer"}))
_NULL = {"m_FileID": 0, "m_PathID": 0}
_ZERO = dict.fromkeys("xyz", 0)
_WHITE = dict.fromkeys("rgba", 1)
_DURATION = _float32(13 + 1 / 6)
_FINALE_DURATION = _float32(5.7)
_FINALE_LIFE = _float32(5.55)
_STEP = _float32(.001)
_MODULES = {"InitialModule", "EmissionModule", "VelocityModule"}
_SETTINGS = {
    "lengthInSec": 30, "simulationSpeed": 1, "stopAction": 0, "cullingMode": 0, "ringBufferMode": 0,
    "looping": True, "prewarm": False, "playOnAwake": True, "useUnscaledTime": False,
    "autoRandomSeed": True, "useRigidbodyForVelocity": True, "moveWithTransform": 0,
    "moveWithCustomTransform": _NULL, "scalingMode": 1, "randomSeed": 0,
}
_RENDERER = {
    "m_Enabled": True, "m_RenderingLayerMask": 1, "m_RenderMode": 4, "m_RenderAlignment": 1,
    "m_UseCustomVertexStreams": True, "m_EnableGPUInstancing": True, "m_ApplyActiveColorSpace": True,
    "m_AllowRoll": True, "m_VertexStreams": [0, 3, 4, 10, 19, 26], "m_Pivot": _ZERO, "m_Flip": _ZERO,
    "m_SortMode": 0, "m_SortingFudge": 0, "m_SortingOrder": 0, "m_SortingLayerID": 0, "m_RendererPriority": 0,
    "m_MinParticleSize": 0, "m_MaxParticleSize": .5, "m_CameraVelocityScale": 0, "m_VelocityScale": 0,
    "m_LengthScale": 2, "m_CastShadows": 0, "m_ReceiveShadows": 0, "m_MaskInteraction": 0,
    "m_StaticBatchRoot": _NULL, "m_StaticBatchInfo": {"firstSubMesh": 0, "subMeshCount": 0},
    "m_Mesh1": _NULL, "m_Mesh2": _NULL, "m_Mesh3": _NULL,
}
_FLOATS = {"_AUTO_PLAY": 1, "_FlapSpeed": 22, "_FlapIntensity": 1, "_RandomFlapIntensity": _float32(.3),
           "_RandomFlapDelay": 1, "_StencilComp": 8, "_StencilPassOp": 0, "_StencilRef": 2, "_StencilZFailOp": 0}
_COLORS = {"_RandomMove": [_float32(.005), _float32(.0075), _float32(.01), 10],
           "_RandomUp": [_float32(.1), 0, _float32(.1), 10], "_AmbientColor": [1, 1, 1, 0],
           "_TintColor": [2, 2, 2, 1]}
_SHADER = (48191361984536363, "cab-54f74bbf25d548ec3d7ea1ad759e85a6")
_FINALE_SIBLINGS = ("out_glitter", "out_glow", "out_par_dust", "out_par_dust_add")
_FINALE_SIZE_KEYS = (
    (0, _float32(.7479041), 0, 0, 0),
    (_float32(.95381784), _float32(.7479041), 0, 0, 0),
    (1, 1, _float32(5.4587293), _float32(5.4587293), 0),
)


def _matches(fields, expected):
    return all(fields.get(key) == value for key, value in expected.items())


def _valid_cubics(curves, duration, *, first=None, last=None, coefficient_limit=100):
    for mode, keys in curves:
        if (mode != "cubic" or not 3 <= len(keys) <= 64 or not math.isfinite(keys[0][0]) or keys[0][0] > -1e20
                or first is not None and keys[1][0] != first or last is not None and keys[-1][0] != last
                or any(not 0 <= row[0] <= duration for row in keys[1:])
                or any(not math.isfinite(value) or abs(value) > coefficient_limit for _, values in keys for value in values)):
            return False
        if coefficient_limit > 100:
            # The finale crosses adjacent 60 Hz keys with steep coefficients.
            # Bound the polynomial over its own segment.
            ends = [stamp for stamp, _ in keys[2:]] + [duration]
            if abs(keys[0][1][3]) > 100 or any(
                    sum(abs(value) * (end - stamp) ** (3 - i) for i, value in enumerate(values)) > 100
                    for (stamp, values), end in zip(keys[1:], ends)):
                return False
    return True


def _animation(objects, animator, fields, deadline, *, finale=False):
    number = 14 if finale else 13
    controller = title._local(objects, animator, fields["m_Controller"], "AnimatorController")
    if (controller is None or controller.peek_name() != f"ac_par_so2028_{number}"
            or not 0 < controller.byte_size <= 2048 or fields.get("m_LinearVelocityBlending")):
        return None
    source = controller.read_typetree()
    ref, = source["m_AnimationClips"]
    original = title._local(objects, controller, ref, "AnimationClip")
    layer, = source["m_Controller"]["m_LayerArray"]
    if (original is None or original.peek_name() != f"clip_par_so2028_{number}"
            or not 0 < original.byte_size <= 8192 or layer["data"]["m_StateMachineIndex"] != 0
            or layer["data"]["m_SkeletonMask"]["data"]["m_Data"]):
        return None
    if finale:
        return _finale_animation(original, deadline) if _clip(objects, animator, fields) is original else None
    data = title._animator(objects, animator, fields, deadline)
    if data is None:
        return None
    clip, _ = data
    duration = clip["duration"]
    if clip["start"] != 0 or clip["loop"] or duration != _DURATION or len(clip["channels"]) != 1:
        return None
    channel, = clip["channels"]
    if channel["path"] != animation.path_hash("ctrl") or channel["kind"] != "translation":
        return None
    curves = channel["curves"]
    return {"duration": duration, "curves": curves} if _valid_cubics(curves, duration, first=0, last=duration) else None


def _finale_animation(original, deadline):
    tree = original.read_typetree()
    if any(tree.get(key) for key in ("m_Legacy", "m_Compressed", "m_HasGenericRootTransform", "m_HasMotionFloatCurves",
                                     "m_Events", "m_PPtrCurves", "m_CompressedRotationCurves")):
        return None
    muscle = tree["m_MuscleClip"]
    duration = muscle["m_StopTime"]
    if duration != _FINALE_DURATION or any(muscle[key] for key in ("m_StartTime", "m_LoopTime", "m_CycleOffset", "m_Mirror")):
        return None
    muscle_curves = muscle["m_Clip"]["data"]
    stream = muscle_curves["m_StreamedClip"]
    if (stream["curveCount"] != 11 or len(stream["data"]) > 512 or muscle_curves["m_DenseClip"]["m_CurveCount"]
            or len(muscle_curves["m_ConstantClip"]["data"]) != 1):
        return None
    bindings = tree["m_ClipBindingConstant"]["genericBindings"]
    if len(bindings) != 10 or any(binding["isPPtrCurve"] or binding["script"] != _NULL for binding in bindings):
        return None
    path = animation.path_hash("ctrl/butterfly")
    active = animation.path_hash("m_IsActive")
    tint = animation.path_hash("_TintColor") & 0x0FFFFFFF
    # Unity's packed clip places the constant tint alpha after all streamed
    # lanes. Sibling active curves belong to separate effects.
    expected = [(animation.path_hash("ctrl"), 1, 4, 0), (path, active, 1, 0)]
    expected.extend((path, tint | channel << 28, 199, 22) for channel in (4, 5, 6))
    expected.extend((animation.path_hash(f"ctrl/{name}"), active, 1, 0) for name in _FINALE_SIBLINGS)
    expected.append((path, tint | 7 << 28, 199, 22))
    if [tuple(binding[key] for key in ("path", "attribute", "typeID", "customType")) for binding in bindings] != expected:
        return None
    tx, ty, tz, visible, red, green, blue, _, _, _, _, alpha = animation._packed_curves(tree, deadline)
    mode, keys = visible
    if (mode != "cubic" or len(keys) != 2 or keys[0][0] > -1e20 or keys[1][0] != 0
            or any(values != (0, 0, 0, 1) for _, values in keys)
            or not _valid_cubics((tx, ty, tz), duration, first=0, coefficient_limit=1_000_000)
            or not _valid_cubics((red, green, blue), duration, last=duration) or alpha != ("constant", 1)):
        return None
    return {"duration": duration, "curves": [tx, ty, tz], "tintCurves": [red, green, blue, alpha]}


def _finale_curves(fields):
    # The native helper evaluates this exact optimized size spline and packed
    # gradient. Fall back if the original curve settings have been modified.
    size = fields["SizeModule"]
    curve = size["curve"]
    maximum = curve["maxCurve"]
    if (size["separateAxes"] or (curve["minMaxState"], curve["scalar"], curve["minScalar"]) != (1, 1, 1)
            or curve["minCurve"]["m_Curve"] or (maximum["m_PreInfinity"], maximum["m_PostInfinity"]) != (2, 2)
            or tuple(tuple(row[key] for key in ("time", "value", "inSlope", "outSlope", "weightedMode"))
                     for row in maximum["m_Curve"]) != _FINALE_SIZE_KEYS):
        return False
    gradient = fields["ColorModule"]["gradient"]
    maximum = gradient["maxGradient"]
    return (gradient["minMaxState"] == 1 and maximum["m_Mode"] == 0
            and (maximum["m_NumColorKeys"], maximum["ctime0"], maximum["ctime1"]) == (2, 0, 65535)
            and (maximum["m_NumAlphaKeys"], maximum["atime0"], maximum["atime1"], maximum["atime2"]) == (3, 0, 62933, 65535)
            and maximum["key0"] == maximum["key1"] == _WHITE and maximum["key2"]["a"] == 0)


def _particle(fields, *, finale=False):
    enabled = {key for key, value in fields.items() if key.endswith("Module") and value.get("enabled")}
    modules = _MODULES | {"SizeModule", "ColorModule"} if finale else _MODULES
    settings = {**_SETTINGS, "lengthInSec": _FINALE_LIFE, "looping": False} if finale else _SETTINGS
    if (enabled != modules or not _matches(fields, settings) or _constant(fields["startDelay"]) != 0
            or finale and not _finale_curves(fields)):
        return None
    initial = fields["InitialModule"]
    color = initial["startColor"]
    life, size, speed = (_constant(initial[key]) for key in ("startLifetime", "startSize", "startSpeed"))
    expected = (_FINALE_LIFE, 9, _STEP) if finale else (30, 6, _STEP)
    if ((life, size, speed) != expected or initial["size3D"] or initial["rotation3D"]
            or initial["maxNumParticles"] != 1000 or initial["randomizeRotationDirection"] != 0
            or any(_constant(initial[name]) != 0 for name in
                   ("startRotation", "startRotationX", "startRotationY", "gravityModifier"))
            or not _matches(color, {"minMaxState": 0, "maxColor": _WHITE})):
        return None
    emission = fields["EmissionModule"]
    if (emission["m_BurstCount"] != 1 or _constant(emission["rateOverTime"]) != 0
            or _constant(emission["rateOverDistance"]) != 0):
        return None
    burst, = emission["m_Bursts"]
    if (not _matches(burst, {"time": 0, "cycleCount": 1, "probability": 1})
            or _constant(burst["countCurve"]) != 1):
        return None
    velocity = fields["VelocityModule"]
    translation = [_constant(velocity[axis]) for axis in "xyz"]
    expected = [-_STEP, -_STEP, 0] if finale else [_STEP, -_STEP, -_STEP]
    if (translation != expected or velocity["inWorldSpace"]
            or _constant(velocity["speedModifier"]) != 1 or _constant(velocity["radial"]) != 0
            or any(_constant(velocity[prefix + axis]) != 0 for prefix in ("orbital", "orbitalOffset") for axis in "XYZ")):
        return None
    # The shape is disabled. Native initial +Z speed adds to the local
    # VelocityModule, retaining the authored signed drift.
    return {"birth": burst["time"], "lifetime": life, "size": size,
            "velocity": [translation[0], translation[1], translation[2] + speed], "color": [1, 1, 1, 1]}


def _geometry(mesh, deadline):
    import numpy as np

    if mesh is None or mesh.peek_name() != "Butterfly_mdl_00" or not 0 < mesh.byte_size <= 8192:
        return None
    source = mesh.read_typetree()
    vertices, parts = source["m_VertexData"], source["m_SubMeshes"]
    if (vertices["m_VertexCount"] != 6 or len(parts) != 1 or parts[0]["indexCount"] != 12
            or parts[0]["topology"] != 0 or vertices["m_Channels"][3]["dimension"] != 0
            or vertices["m_Channels"][4]["dimension"] != 2 or source["m_MeshCompression"]
            or source["m_StreamData"]["size"] or source["m_BindPose"] or any(source["m_Shapes"].values())):
        return None
    _, positions, _, uv, faces = viewer._geometry(mesh, np.eye(4), deadline=deadline)
    if (positions.shape != (6, 3) or np.abs(positions).max() > .005001 or np.abs(positions[:, 1]).max() > 1e-8
            or uv is None or uv.shape != (6, 2) or uv.min() < 0 or uv.max() > 1
            or len(faces) != 1 or faces[0].shape != (4, 3)):
        return None
    return {"positions": positions.tolist(), "uv": uv.tolist(), "indices": faces[0].ravel().tolist()}


def _material(objects, owner, fields, *, finale=False):
    first, trail = fields["m_Materials"]
    material = title._local(objects, owner, first, "Material") if first == trail else None
    if material is None:
        return None
    tree = material.read_typetree()
    shader = tree["m_Shader"]
    file_id, external = shader["m_FileID"], material.assets_file.externals
    colors = viewer._properties(tree, "m_Colors")
    vectors = {key: [colors[key][axis] for axis in "rgba"] for key in _COLORS}
    suffix, image_suffix = ("02", "04") if finale else ("01", "03")
    floats = {**_FLOATS, "_FlapSpeed": 28, "_FlapIntensity": _float32(.9)} if finale else _FLOATS
    colors = {**_COLORS, "_RandomMove": [_float32(.01), *_COLORS["_RandomMove"][1:]]} if finale else _COLORS
    if (tree["m_Name"] != f"mat_par_so2028_add_oth_{suffix}" or tree["m_ShaderKeywords"] != "_AUTO_PLAY_ON"
            or tree["m_CustomRenderQueue"] != -1 or tree["disabledShaderPasses"] or tree["stringTagMap"]
            or shader["m_PathID"] != _SHADER[0] or not 0 < file_id <= len(external)
            or external[file_id - 1].name.lower() != _SHADER[1]
            or viewer._properties(tree, "m_Floats") != floats or vectors != colors):
        return None
    env = viewer._properties(tree, "m_TexEnvs")
    if set(env) != {"_MainTex"}:
        return None
    main = env["_MainTex"]
    texture = title._local(objects, material, main["m_Texture"], "Texture2D")
    if (texture is None or main["m_Scale"] != dict.fromkeys("xy", 1) or main["m_Offset"] != dict.fromkeys("xy", 0)):
        return None
    image = texture.read()
    sampler = image.m_TextureSettings
    if (image.m_Name != f"tex_par_so2028_{image_suffix}" or (image.m_Width, image.m_Height, image.m_TextureFormat,
            image.m_MipCount, image.m_ColorSpace, image.m_ImageCount, image.m_TextureDimension) != (512, 512, 65, 10, 1, 1, 2)
            or (sampler.m_FilterMode, sampler.m_Aniso, sampler.m_MipBias) != (1, 1, 0)
            or (sampler.m_WrapU, sampler.m_WrapV, sampler.m_WrapW) != (0, 0, 0)):
        return None
    return {"flapSpeed": floats["_FlapSpeed"], "flapIntensity": floats["_FlapIntensity"],
            "randomFlapIntensity": floats["_RandomFlapIntensity"], "randomFlapDelay": floats["_RandomFlapDelay"],
            "randomMove": vectors["_RandomMove"], "randomUp": vectors["_RandomUp"],
            "ambient": vectors["_AmbientColor"], "tint": vectors["_TintColor"]}, texture


def _prefab(objects, game, deadline, *, finale=False):
    hierarchy = {}
    prefab_name = "fx_par_so2028_14" if finale else "fx_par_so2028_13"
    for index, (name, types) in enumerate(_NODES):
        row = title._components(objects, game, types, layer=1) if game is not None else None
        if row is None or row[0]["m_Name"] != (prefab_name if index == 0 else name):
            return None
        parts = hierarchy[name] = row[1]
        transform, fields = parts["Transform"]
        if _authored_trs(fields) != title._IDENTITY or (index == 0 and fields["m_Father"]["m_PathID"]):
            return None
        if finale and name == "ctrl":
            children = fields["m_Children"]
            if not 1 <= len(children) <= 8:
                return None
            game, = [child for ref in children if (child := title._transform_child(objects, transform, ref))
                     is not None and child.peek_name() == "butterfly"]
        elif index < len(_NODES) - 1:
            child, = fields["m_Children"]
            game = title._transform_child(objects, transform, child)
    renderer, fields = hierarchy["butterfly"]["ParticleSystemRenderer"]
    if not _matches(fields, _RENDERER):
        return None
    particle = _particle(hierarchy["butterfly"]["ParticleSystem"][1], finale=finale)
    pose = _animation(objects, *hierarchy["root"]["Animator"], deadline, finale=finale)
    geometry = _geometry(title._local(objects, renderer, fields["m_Mesh"], "Mesh"), deadline)
    surface = _material(objects, renderer, fields, finale=finale)
    if any(value is None for value in (particle, pose, geometry, surface)):
        return None
    material, reader = surface
    try:
        glow = mv_studio_butterfly_glow.read(objects, *hierarchy["ctrl"]["Transform"], deadline, finale=finale)
    except title._UNSUPPORTED:
        glow = None
    return {"schema": 1, "geometry": geometry, "animation": pose, "particle": particle, "material": material}, reader, glow


def read(objects, mono, tracks, deadline):
    """Return the principal particles of the original Aion Expert butterfly cues."""
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    accepted = {}
    for track in tracks:
        declaration = controls.get(track["id"])
        label = track["label"]
        if declaration is None or label not in (_TRACK, _FINALE) or track.get("binding") or track.get("bindings"):
            continue
        finale = label == _FINALE
        owner, fields = declaration
        try:
            if (fields["m_Name"] != label.rsplit("/", 1)[1] or not fields["m_Enabled"] or len(fields["m_Clips"]) != 1
                    or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                    or not title._group(objects, owner, fields, "control")):
                continue
            event, = track["events"]
            viewer._remaining(deadline)
            control = particles._source(objects, owner, fields, event)
            effect = _prefab(objects, control[0], deadline, finale=finale) if control is not None else None
            if effect is not None:
                accepted[label] = None if label in accepted else (track["id"], event["id"], effect)
        except title._UNSUPPORTED:
            continue
    results, glows = {}, {}
    for label, effect in accepted.items():
        if effect is None:
            continue
        track_id, event_id, (data, reader, glow) = effect
        try:
            mipmaps = particles._texture(reader, deadline)
        except title._UNSUPPORTED:
            continue
        if mipmaps:
            results[label] = {**data, "trackId": track_id, "eventId": event_id, "texture": mipmaps}
            if glow is not None:
                glows[label] = glow
    if not results:
        return None
    result = results.get(_TRACK, {"schema": 1})
    if _FINALE in results:
        result["finale"] = results[_FINALE]
    if glows:
        _, atlas = next(iter(glows.values()))
        try:
            glow_mips = particles._texture(atlas, deadline)
        except title._UNSUPPORTED:
            glow_mips = None
        if glow_mips:
            result["glowTexture"] = glow_mips
            for label, (details, reader) in glows.items():
                if viewer._key(atlas) == viewer._key(reader):
                    results[label]["glow"] = details
    return result
