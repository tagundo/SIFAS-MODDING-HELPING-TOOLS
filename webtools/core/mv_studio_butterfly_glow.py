"""Read the native View-aligned glow billboards from Aion's Expert butterflies."""

from . import model_animation as animation, model_viewer as viewer
from . import mv_studio_stage_title as title
from .model_rig import _authored_trs
from .mv_studio_finale_floor import _SURFACE
from .mv_studio_speed_back_animation import _clip
from .mv_studio_stage_display import _shader_matches
from .mv_studio_stage_title_particles import _constant, _float32


_NULL = {"m_FileID": 0, "m_PathID": 0}
_ZERO = dict.fromkeys("xyz", 0)
_WHITE = dict.fromkeys("rgba", 1)
_MODULES = {"EmissionModule", "InitialModule", "SizeModule", "UVModule"}
_SETTINGS = {
    "lengthInSec": 5, "simulationSpeed": 1, "looping": False, "prewarm": False, "playOnAwake": True,
    "useUnscaledTime": False, "useRigidbodyForVelocity": True, "moveWithTransform": 0, "scalingMode": 1,
    "moveWithCustomTransform": _NULL, "stopAction": 0, "cullingMode": 0, "ringBufferMode": 0,
}
_LAYER = 1
_MATERIAL = -3459241494953612992
_ALPHA_MATERIAL = 648833837626327585
_TEXTURE = 6455981386118614978
_ACTIVATION = _float32(5 + 5 / 60)
_DUST_ACTIVATION = _float32(5 + 25 / 60)
_FINALE_ACTIVATIONS = {"out_glow": _ACTIVATION, "out_par_dust_add": _DUST_ACTIVATION, "out_par_dust": _DUST_ACTIVATION}
_RENDERER = {
    "m_Enabled": True, "m_RenderMode": 0, "m_RenderAlignment": 0, "m_AllowRoll": True,
    "m_UseCustomVertexStreams": False, "m_EnableGPUInstancing": True, "m_ApplyActiveColorSpace": True,
    "m_RenderingLayerMask": 1, "m_VertexStreams": [0, 1, 3, 4], "m_Pivot": _ZERO,
    "m_SortMode": 0, "m_SortingFudge": 0, "m_SortingOrder": 0, "m_SortingLayerID": 0, "m_SortingLayer": 0,
    "m_RendererPriority": 0, "m_MinParticleSize": 0, "m_CameraVelocityScale": 0, "m_VelocityScale": 0,
    "m_LengthScale": 2, "m_NormalDirection": 1, "m_CastShadows": 0, "m_ReceiveShadows": 0,
    "m_LightProbeUsage": 0, "m_ReflectionProbeUsage": 0, "m_MaskInteraction": 0,
    "m_StaticBatchRoot": _NULL, "m_StaticBatchInfo": {"firstSubMesh": 0, "subMeshCount": 0},
    "m_Mesh": _NULL, "m_Mesh1": _NULL, "m_Mesh2": _NULL, "m_Mesh3": _NULL,
}
_OPENING_SIZE = (
    (0, .9397342801094055, 0, 0),
    (.07216052711009979, .7206919193267822, 0, 0),
    (.13649053871631622, 1, 0, 0),
    (.21815171837806702, .7206919193267822, 0, 0),
    (.26516327261924744, 1, 0, 0),
    (.3616510331630707, .7206919193267822, 0, 0),
    (.42599084973335266, 1, 0, 0),
    (.5101279616355896, .7206919193267822, 0, 0),
    (.5818743109703064, 1, 0, 0),
)
_FINALE_SIZE = (
    (0, .5057507753372192, 1.4542194604873657, 1.4542194604873657),
    (.45689523220062256, .859779417514801, .44636112451553345, .44636112451553345),
    (1, 1, 0, 0),
)
_OPENING_RGB = (
    (16384, .04313725233078003, .23561561107635498, 1),
    (49151, .08627451211214066, .8352941870689392, .6509804129600525),
    (65535, .5662530660629272, .2588235139846802, 1),
)
_OPENING_ALPHA = ((0, .1411764770746231), (65535, .1411764770746231))
_FINALE_RGB = ((0, 1, 1, 1), (65535, 1, 1, 1))
_FINALE_ALPHA = ((0, 0), (23805, .7333333492279053), (38839, .7843137383460999),
                 (46356, .8627451062202454), (65535, 0))


def _matches(fields, expected):
    return all(fields.get(name) == value for name, value in expected.items())


def _child(objects, transform, fields, name):
    refs = fields["m_Children"]
    if not 1 <= len(refs) <= 8:
        return None
    matches = [child for ref in refs if (child := title._transform_child(objects, transform, ref)) is not None
               and child.peek_name() == name]
    return matches[0] if len(matches) == 1 else None


def _activations(objects, transform, fields, deadline):
    parent = title._local(objects, transform, fields["m_Father"], "Transform")
    if parent is None:
        return {}
    game = title._local(objects, parent, parent.read_typetree()["m_GameObject"], "GameObject")
    parts = title._components(objects, game, {"Transform", "Animator"}, layer=_LAYER) if game is not None else None
    if parts is None or parts[0]["m_Name"] != "root":
        return {}
    original = _clip(objects, *parts[1]["Animator"])
    if original is None or original.peek_name() != "clip_par_so2028_14" or not 0 < original.byte_size <= 8192:
        return {}
    tree = original.read_typetree()
    # The principal butterfly checks this same controller and its clip. Read
    # the typed sibling flags before enabling their separate emitters.
    bindings = tree["m_ClipBindingConstant"]["genericBindings"]
    if len(bindings) != 10:
        return {}
    curves = animation._packed_curves(tree, deadline)
    paths = {animation.path_hash(f"ctrl/{name}"): name for name in _FINALE_ACTIVATIONS}
    attribute = animation.path_hash("m_IsActive")
    offset, matching, seen = 0, {}, set()
    for binding in bindings:
        width = animation._width(binding)
        name = paths.get(binding["path"])
        if name is not None:
            if name in seen:
                return {}
            seen.add(name)
            if width == 1 and _matches(binding, {"attribute": attribute, "typeID": 1, "customType": 0,
                                                "isPPtrCurve": 0, "script": _NULL}):
                activation = _FINALE_ACTIVATIONS[name]
                mode, keys = curves[offset]
                expected = [(-_float32(3.4028234663852886e38), (0, 0, 0, 0)),
                            (0, (0, 0, 0, 0)), (activation, (0, 0, 0, 1))]
                if mode == "cubic" and keys == expected:
                    matching[name] = activation
        offset += width
    return matching if offset == len(curves) else {}


def _gradient(source, colors, alpha):
    gradient = source["maxGradient"]
    if (source["minMaxState"] != 1 or gradient["m_Mode"]
            or (gradient["m_NumColorKeys"], gradient["m_NumAlphaKeys"]) != (len(colors), len(alpha))):
        return False
    return (all((gradient[f"ctime{index}"], *(gradient[f"key{index}"][axis] for axis in "rgb")) == row
                for index, row in enumerate(colors))
            and all((gradient[f"atime{index}"], gradient[f"key{index}"]["a"]) == row
                    for index, row in enumerate(alpha)))


def _size(source, finale):
    curve = source["curve"]
    maximum = curve["maxCurve"]
    keys = maximum["m_Curve"]
    authored = _FINALE_SIZE if finale else _OPENING_SIZE
    return (not source["separateAxes"] and len(keys) == len(authored)
            and (curve["minMaxState"], curve["scalar"], curve["minScalar"]) == (1, 1 if finale else 2, 1)
            and not curve["minCurve"]["m_Curve"] and maximum["m_PreInfinity"] == 2
            and maximum["m_PostInfinity"] == (2 if finale else 1)
            and all(not key["weightedMode"] and tuple(key[name] for name in ("time", "value", "inSlope", "outSlope")) == row
                    for key, row in zip(keys, authored)))


def _profile(source, finale):
    enabled = {key for key, fields in source.items() if key.endswith("Module") and fields.get("enabled")}
    modules = _MODULES | {"ColorModule"} if finale else _MODULES
    if (enabled != modules or not _matches(source, _SETTINGS) or _constant(source["startDelay"]) != 0
            or (source["autoRandomSeed"], source["randomSeed"]) != ((True, 0) if finale else (False, 2))):
        return False
    initial = source["InitialModule"]
    life, size = (_float32(.9), .5) if finale else (30, _float32(.2))
    if ((initial["size3D"], initial["rotation3D"], initial["maxNumParticles"]) != (False, not finale, 1000)
            or initial["randomizeRotationDirection"] or _constant(initial["startLifetime"]) != life
            or _constant(initial["startSize"]) != size or any(_constant(initial[name]) != 0 for name in
                ("startSpeed", "startRotation", "startRotationX", "startRotationY", "gravityModifier"))
            or not _size(source["SizeModule"], finale)):
        return False
    start = initial["startColor"]
    if finale:
        color = dict(zip("rgba", (.9896755814552307, .5613207817077637, 1, _float32(.6))))
        if (not _matches(start, {"minMaxState": 0, "maxColor": color})
                or not _gradient(source["ColorModule"]["gradient"], _FINALE_RGB, _FINALE_ALPHA)):
            return False
    elif not _gradient(start, _OPENING_RGB, _OPENING_ALPHA):
        return False
    emission = source["EmissionModule"]
    if emission["m_BurstCount"] != 1 or any(_constant(emission[name]) != 0 for name in ("rateOverTime", "rateOverDistance")):
        return False
    burst, = emission["m_Bursts"]
    if not _matches(burst, {"time": 0, "cycleCount": 1, "probability": 1}) or _constant(burst["countCurve"]) != 1:
        return False
    sheet = source["UVModule"]
    return (_matches(sheet, {"mode": 0, "timeMode": 0, "animationType": 0, "cycles": 1, "tilesX": 2, "tilesY": 2,
                             "flipU": 0, "flipV": 0})
            and sheet["uvChannelMask"] & 1 and _constant(sheet["frameOverTime"]) == 0
            and _constant(sheet["startFrame"]) == .75)


def _texture(objects, renderer, fields, *, finale):
    maximum, flip = (1, _ZERO) if finale else (.5, {**_ZERO, "z": 1})
    if not _matches(fields, _RENDERER) or (fields["m_MaxParticleSize"], fields["m_Flip"]) != (maximum, flip):
        return None
    return _material_texture(objects, renderer, fields)


def _material_texture(objects, renderer, fields, *, alpha=False):
    material_id, name = (_ALPHA_MATERIAL, "mat_par_so2028_alb_01") if alpha else (_MATERIAL, "mat_par_so2028_add_01")
    surface = {**_SURFACE, "_BlendDst": 10} if alpha else _SURFACE
    refs = fields["m_Materials"]
    if refs != [{"m_FileID": 0, "m_PathID": material_id}] * 2:
        return None
    material = title._local(objects, renderer, refs[0], "Material")
    if material is None:
        return None
    tree = material.read_typetree()
    if (not _matches(tree, {"m_Name": name, "m_CustomRenderQueue": 3010,
                            "m_ShaderKeywords": "_VERTEX_COLOR_ON", "stringTagMap": [], "disabledShaderPasses": []})
            or not _shader_matches(material, tree, "AS/General/Transparent")
            or viewer._properties(tree, "m_Floats") != surface
            or viewer._properties(tree, "m_Colors") != {"_TintColor": _WHITE}):
        return None
    env = viewer._properties(tree, "m_TexEnvs")
    if set(env) != {"_MainTex"}:
        return None
    main = env["_MainTex"]
    if not _matches(main, {"m_Texture": {"m_FileID": 0, "m_PathID": _TEXTURE},
                           "m_Scale": dict.fromkeys("xy", 1), "m_Offset": dict.fromkeys("xy", 0)}):
        return None
    reader = title._local(objects, material, main["m_Texture"], "Texture2D")
    if reader is None:
        return None
    native = reader.read()
    sampler = native.m_TextureSettings
    if ((native.m_Name, native.m_Width, native.m_Height, native.m_TextureFormat, native.m_MipCount, native.m_ColorSpace,
         native.m_ImageCount, native.m_TextureDimension, native.m_StreamingMipmaps) != ("tex_par_so2028_01", 256, 256, 65, 9, 1, 1, 2, False)
            or (sampler.m_FilterMode, sampler.m_Aniso, sampler.m_MipBias, sampler.m_WrapU, sampler.m_WrapV,
                sampler.m_WrapW) != (1, 1, 0, 0, 0, 0)):
        return None
    return reader


def read(objects, ctrl, fields, deadline, *, finale=False, activations=None):
    """Return one validated glow descriptor and its undecoded shared atlas."""
    try:
        viewer._remaining(deadline)
        if finale:
            if activations is None:
                activations = _activations(objects, ctrl, fields, deadline)
            activation = activations.get("out_glow")
            game = _child(objects, ctrl, fields, "out_glow")
        else:
            activation = 0
            butterfly = _child(objects, ctrl, fields, "butterfly")
            parent = (title._components(objects, butterfly, {"Transform", "ParticleSystem", "ParticleSystemRenderer"},
                                        layer=_LAYER) if butterfly is not None else None)
            game = _child(objects, *parent[1]["Transform"], "glow") if parent is not None else None
        if activation is None or game is None:
            return None
        components = title._components(objects, game, {"Transform", "ParticleSystem", "ParticleSystemRenderer"}, layer=_LAYER)
        if components is None:
            return None
        parts = components[1]
        _, transform = parts["Transform"]
        pose = _authored_trs(transform)
        position = [0, 0 if finale else -_float32(.015), 0]
        if transform["m_Children"] or pose != {**title._IDENTITY, "translation": position}:
            return None
        if not _profile(parts["ParticleSystem"][1], finale):
            return None
        texture = _texture(objects, *parts["ParticleSystemRenderer"], finale=finale)
        if texture is None:
            return None
        return {"profile": "finale" if finale else "opening", "activation": activation, "position": position,
                "maxViewportWidth": 1 if finale else .5, "uv": [.5, .5, .5, .5],
                "material": {"tint": [1, 1, 1, 1], "queue": 3010, "cull": 0, "blend": "add", "premultiply": False}}, texture
    except title._UNSUPPORTED:
        return None
