"""Read the two native Monster Girls cues that share falling display emitters."""

import math

from . import model_animation as animation, model_viewer as viewer
from . import mv_studio_stage_motion as motion, mv_studio_stage_particles as particles
from . import mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_rig import _authored_trs
from .mv_studio_center_stars import _material as _star_material, _palette
from .mv_studio_display_lights import _enabled, _sheet, _SURFACE
from .mv_studio_foot_particles import _rgba8
from .mv_studio_stage_display import _SHADERS
from .mv_studio_stage_title_particles import _atlas, _constant, _constant_range, _float32, _scalar


_PREFABS = ("fx_dis_so2056_05", "fx_dis_so2056_07")
_NAMES = {"light_big", "light_smole", "light_smole_R", "light_smole_L", "stars"}
_SIDE_LIGHTS = {"light_smole_R", "light_smole_L"}
_COMPONENTS = {"Transform", "ParticleSystem", "ParticleSystemRenderer"}
_MODULES = {"InitialModule", "ShapeModule", "EmissionModule", "ColorModule", "RotationModule", "VelocityModule", "UVModule"}
_ZERO = dict.fromkeys("xyz", 0)
_WHITE_START = {"minMaxState": 0, "maxColor": dict.fromkeys("rgba", 1)}
_ORBITAL = ("orbitalX", "orbitalY", "orbitalZ", "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ", "radial")
_ATLAS_NAMES = ("displayLights", "speedBackCenterStars")
# These exact curves are the ones used by the native renderer's star bounds.
# Tuples are normalized time, signed ordinate, incoming slope and outgoing slope.
_STAR_VELOCITY = {
    "x": (0, _float32(.2), ((0, 1, 0, 0), (.5, -1, 0, 0), (1, 1, 0, 0)),
          ((0, -1, 0, 0), (.5, 1, 0, 0), (1, -1, 0, 0))),
    "y": (-.5, 1.5,
          ((0, _float32(-.10473863780498505), _float32(-.39402538537979126), _float32(-.39402538537979126)),
           (1, _float32(-.4987640380859375), _float32(-.39402538537979126), _float32(-.39402538537979126))),
          ((0, _float32(-.35319215059280396), _float32(-.646807849407196), _float32(-.646807849407196)),
           (1, -1, _float32(-.646807849407196), _float32(-.646807849407196)))),
    "z": (0, 1, ((0, 0, 0, 0), (1, 0, 0, 0)), ((0, 0, 0, 0), (1, 0, 0, 0))),
}


def _light_material(objects, renderer, refs):
    if len(refs) != 2 or refs[0] != refs[1]:
        return None
    material = title._local(objects, renderer, refs[0], "Material")
    if material is None:
        return None
    tree = material.read_typetree()
    shader = tree["m_Shader"]
    path_id, cab = _SHADERS["AS/General/Transparent"]
    file_id, externals = shader["m_FileID"], material.assets_file.externals
    if (tree["m_CustomRenderQueue"] != 2900 or tree["m_ShaderKeywords"] != "_VERTEX_COLOR_ON"
            or tree["stringTagMap"] or tree["disabledShaderPasses"] or viewer._properties(tree, "m_Floats") != _SURFACE
            or shader["m_PathID"] != path_id or not 0 < file_id <= len(externals)
            or externals[file_id - 1].name.lower() != cab
            or viewer._properties(tree, "m_Colors") != {"_TintColor": dict.fromkeys("rgba", 1)}):
        return None
    textures = viewer._properties(tree, "m_TexEnvs")
    if set(textures) != {"_MainTex"}:
        return None
    main = textures["_MainTex"]
    if main["m_Scale"] != dict.fromkeys("xy", 1) or main["m_Offset"] != dict.fromkeys("xy", 0):
        return None
    texture = title._local(objects, material, main["m_Texture"], "Texture2D")
    if texture is None:
        return None
    native = texture.read()
    sampler = native.m_TextureSettings
    if ((native.m_Width, native.m_Height, native.m_TextureFormat, native.m_MipCount, native.m_ColorSpace) != (512, 512, 65, 10, 1)
            or (sampler.m_FilterMode, sampler.m_Aniso, sampler.m_MipBias,
                sampler.m_WrapU, sampler.m_WrapV, sampler.m_WrapW) != (1, 1, 0, 0, 0, 0)):
        return None
    return texture


def _surface(objects, renderer, fields, name):
    bias = 1 if name.startswith("light_smole") else 0
    if (not fields["m_Enabled"] or fields["m_RenderMode"] != 0 or fields["m_RenderAlignment"] != 2
            or not fields["m_AllowRoll"] or not fields["m_ApplyActiveColorSpace"]
            or fields["m_VertexStreams"] != [0, 1, 3, 4] or fields["m_Pivot"] != _ZERO or fields["m_Flip"] != _ZERO
            or fields["m_MaxParticleSize"] != 2 or fields["m_NormalDirection"] != 1
            or fields["m_LengthScale"] != (15 if name == "stars" else 2)
            or fields["m_SortMode"] != 1 or fields["m_SortingFudge"] != bias or fields["m_RenderingLayerMask"] != 1
            or fields["m_StaticBatchInfo"]["subMeshCount"]
            or any(fields[key] for key in ("m_UseCustomVertexStreams", "m_CameraVelocityScale", "m_VelocityScale",
                                           "m_MinParticleSize", "m_MaskInteraction", "m_CastShadows", "m_ReceiveShadows",
                                           "m_SortingLayerID", "m_SortingOrder", "m_RendererPriority"))
            or any(fields[key]["m_PathID"] for key in ("m_Mesh", "m_Mesh1", "m_Mesh2", "m_Mesh3", "m_StaticBatchRoot"))):
        return None
    material = _star_material if name == "stars" else _light_material
    return material(objects, renderer, fields["m_Materials"])


def _box(fields, name):
    axes = [fields["m_Scale"][axis] for axis in "xyz"]
    expected = [8, 1, 0] if name == "stars" else [2, 1, 1] if name in _SIDE_LIGHTS else [8, 1, 1]
    if (fields["type"] != 5 or fields["m_Position"] != _ZERO or fields["m_Rotation"] != _ZERO or axes != expected
            or any(fields[key] for key in ("alignToDirection", "randomDirectionAmount", "sphericalDirectionAmount",
                                           "randomPositionAmount", "placementMode"))
            or any(fields[key]["m_PathID"] for key in ("m_Texture", "m_Mesh", "m_MeshRenderer", "m_SkinnedMeshRenderer",
                                                        "m_Sprite", "m_SpriteRenderer"))):
        return None
    return axes


def _constant_pair(value, low=-10, high=10):
    # Preserve authored endpoint order. A descending range still consumes the
    # exact same random sample in the native MinMaxCurve evaluation.
    return _constant_range(value, low, high)


def _zero(value):
    return _constant(value) == 0 or _constant_pair(value) == (0, 0)


def _star_velocity(fields, deadline):
    curves, lower, upper = [], [], []
    for axis, (min_scalar, max_scalar, min_keys, max_keys) in _STAR_VELOCITY.items():
        row = fields[axis]
        if row["minMaxState"] != 2 or (row["minScalar"], row["scalar"]) != (min_scalar, max_scalar):
            return None
        packed = []
        for source, expected in ((row["minCurve"], min_keys), (row["maxCurve"], max_keys)):
            keys = source["m_Curve"]
            if ((source["m_PreInfinity"], source["m_PostInfinity"]) != (2, 2) or len(keys) != len(expected)
                    or any(k["weightedMode"] or (k["time"], k["value"], k["inSlope"], k["outSlope"]) != want
                           for k, want in zip(keys, expected))):
                return None
            packed.append(animation._editor_scalar(keys, deadline=deadline))
        curves.append(packed)
        lower.append(min_scalar)
        upper.append(max_scalar)
    return {"velocityCurves": curves, "velocityMultipliers": upper, "velocityMinMultipliers": lower}


def _velocity(fields, star, deadline):
    if fields["inWorldSpace"] or _constant(fields["speedModifier"]) != 1 or any(not _zero(fields[key]) for key in _ORBITAL):
        return None
    if star:
        return _star_velocity(fields, deadline)
    y = _constant_pair(fields["y"])
    return {"velocityY": y} if y == (-.5, -1.5) and all(_zero(fields[key]) for key in "xz") else None


def _births(fields, star):
    expected_count, rate = (0, 10) if star else (1, 0)
    bursts = fields["m_Bursts"]
    if (fields["m_BurstCount"] != expected_count or len(bursts) != expected_count
            or _constant(fields["rateOverTime"]) != rate or _constant(fields["rateOverDistance"]) != 0):
        return None
    if star:
        return {"rate": rate, "burstPeriod": 0}
    burst, = bursts
    if (burst["time"] != 0 or burst["cycleCount"] != 0 or burst["repeatInterval"] != 1 or burst["probability"] != 1
            or _constant(burst["countCurve"]) != 1):
        return None
    return {"rate": rate, "burstPeriod": burst["repeatInterval"]}


def _size(source, name, deadline):
    initial = source["InitialModule"]
    if name != "stars":
        size = [_constant(initial[key]) for key in ("startSize", "startSizeY", "startSizeZ")]
        expected = [4, 1, _float32(.1)] if name == "light_big" else [2, .5, .5]
        return {"size": size} if size == expected else None
    size = _constant_pair(initial["startSize"])
    module = source["SizeModule"]
    curve = module["curve"]
    raw = curve["maxCurve"]
    keys = raw["m_Curve"]
    if (size != (_float32(.3), .5) or module["separateAxes"] or curve["minMaxState"] != 1 or curve["scalar"] != 1
            or raw["m_PostInfinity"] != 1 or len(keys) != 3 or keys[0]["time"] != 0
            or keys[-1]["time"] != _float32(.05)):
        return None
    period = keys[-1]["time"]
    packed = _scalar(curve, deadline, through=period)
    return {"size": size, "sizeCurve": packed, "sizePeriod": period} if packed is not None else None


def _state(source, name, deadline):
    star = name == "stars"
    modes = _MODULES | {"SizeModule"} if star else _MODULES
    seed = source["randomSeed"]
    if (_enabled(source) != modes or not source["playOnAwake"] or not source["looping"] or not source["prewarm"]
            or source["lengthInSec"] != 50 or source["simulationSpeed"] != 1 or source["scalingMode"] != 1
            or _constant(source["startDelay"]) != 0 or source["moveWithCustomTransform"]["m_PathID"]
            or type(seed) is not int or not -(1 << 31) <= seed <= (1 << 32) - 1
            or any(source[key] for key in ("moveWithTransform", "autoRandomSeed", "useUnscaledTime", "cullingMode",
                                           "ringBufferMode", "stopAction"))):
        return None
    initial, rotation = source["InitialModule"], source["RotationModule"]
    lifetime = _constant(initial["startLifetime"])
    roll = _constant_pair(initial["startRotation"])
    spin = _constant_pair(rotation["curve"])
    if (lifetime != (5 if star else 8) or initial["maxNumParticles"] != 1000 or initial["size3D"] == star
            or initial["rotation3D"] or initial["randomizeRotationDirection"] or rotation["separateAxes"]
            or _constant(initial["startSpeed"]) != 0 or _constant(initial["gravityModifier"]) != 0
            or roll != (_float32(6.283185), _float32(-6.283185))
            or spin != (_float32(-.2617994), _float32(.2617994))):
        return None
    if not star and (initial["startColor"]["minMaxState"] != 0 or initial["startColor"]["maxColor"] != _WHITE_START["maxColor"]):
        return None
    box = _box(source["ShapeModule"], name)
    velocity = _velocity(source["VelocityModule"], star, deadline)
    emission = _births(source["EmissionModule"], star)
    size = _size(source, name, deadline)
    color = _rgba8({"startColor": _WHITE_START}, source["ColorModule"])
    if box is None or velocity is None or emission is None or size is None or color is None:
        return None
    return {"name": name, "box": box, "seed": seed & 0xFFFFFFFF, "lifetime": lifetime, "cycle": source["lengthInSec"],
            "rollRange": roll, "rollSpeedRange": spin, "colorKeys": color["rgba8"]["keys"], **emission, **size, **velocity}


def _light_atlas(module, deadline):
    value = module["frameOverTime"]
    source = value["maxCurve"]
    keys = []
    for key in source["m_Curve"]:
        if key["weightedMode"]:
            # These default weights are on two step tangents, where Unity
            # holds the keyed value without evaluating a weighted segment.
            if (key["weightedMode"] != 3 or key["inSlope"] != math.inf or key["outSlope"] != math.inf
                    or (key["inWeight"], key["outWeight"]) != (_float32(1 / 3), _float32(1 / 3))):
                return None
            key = {**key, "weightedMode": 0}
        keys.append(key)
    if not keys or not .17 <= keys[-1]["time"] <= .18:
        return None
    return _sheet({**module, "frameOverTime": {**value, "maxCurve": {**source, "m_Curve": keys}}}, deadline)


def _leaf(objects, game, name, deadline):
    row = title._components(objects, game, _COMPONENTS)
    if row is None:
        return None
    _, parts = row
    _, fields = parts["Transform"]
    pose = _authored_trs(fields)
    if (fields["m_Children"] or pose["scale"] != title._IDENTITY["scale"] or pose["rotation"][0] or pose["rotation"][2]
            or any(abs(value) > 100 for value in pose["translation"])):
        return None
    star = name == "stars"
    renderer, fields = parts["ParticleSystemRenderer"]
    source = parts["ParticleSystem"][1]
    state = _state(source, name, deadline)
    texture = _surface(objects, renderer, fields, name) if state is not None else None
    if texture is None:
        return None
    if star:
        atlas = _atlas(source["UVModule"], deadline, through=1)
        if atlas != {"tiles": [4, 4], "row": 1, "frame": ("constant", _float32(.9999))}:
            return None
        variant = _palette(source["InitialModule"]["startColor"])
        if (variant is None or [row[0] for row in variant["rgb"]] != [32768, 65535]
                or variant["alpha"] != [[0, 255], [65535, 255]]):
            return None
    else:
        variant = _light_atlas(source["UVModule"], deadline)
    if variant is None:
        return None
    return {**state, "position": pose["translation"], "rotation": pose["rotation"], "texture": int(star),
            "sortBias": fields["m_SortingFudge"], "maxViewportWidth": fields["m_MaxParticleSize"]}, texture, variant


def _prefab(objects, game, variant_name, deadline):
    outer = title._components(objects, game, {"Transform"})
    if outer is None:
        return None
    transform, fields = outer[1]["Transform"]
    child, = fields["m_Children"]
    if _authored_trs(fields) != title._IDENTITY or fields["m_Father"]["m_PathID"]:
        return None
    root = title._transform_child(objects, transform, child)
    row = title._components(objects, root, _COMPONENTS) if root is not None else None
    if row is None or row[0]["m_Name"] != "root":
        return None
    _, parts = row
    transform, fields = parts["Transform"]
    optional = variant_name == _PREFABS[1]
    if (len(fields["m_Children"]) != len(_NAMES) + optional or _authored_trs(fields) != title._IDENTITY
            or _enabled(parts["ParticleSystem"][1]) != {"InitialModule"} or parts["ParticleSystemRenderer"][1]["m_Enabled"]):
        return None
    rows, readers, names, light_atlas, star_palette = [], [None, None], set(), None, None
    for ref in fields["m_Children"]:
        viewer._remaining(deadline)
        child = title._transform_child(objects, transform, ref)
        name = child.peek_name() if child is not None else None
        if optional and name == "stars (1)":
            inert = title._components(objects, child, _COMPONENTS, require_active=False)
            if inert is None or inert[0]["m_IsActive"] or inert[1]["Transform"][1]["m_Children"]:
                return None
            continue
        if name not in _NAMES or name in names:
            return None
        data = _leaf(objects, child, name, deadline)
        if data is None:
            return None
        emitter, texture, variant = data
        index = emitter["texture"]
        if readers[index] is not None and viewer._key(readers[index]) != viewer._key(texture):
            return None
        if index == 1:
            star_palette = variant
        elif light_atlas is not None and light_atlas != variant:
            return None
        else:
            light_atlas = variant
        rows.append(emitter)
        readers[index] = texture
        names.add(name)
    if names != _NAMES or light_atlas is None or star_palette is None:
        return None
    return rows, readers, {"lightAtlasCurve": light_atlas[0], "lightAtlasPeriod": light_atlas[1], "starPalette": star_palette}


def read(objects, mono, tracks, deadline, atlas_refs=None):
    """Read each supported cue with common native emitters and one atlas per material."""
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    found = {name: [] for name in _PREFABS}
    for track in tracks:
        source = controls.get(track["id"])
        if (source is None or track.get("binding") or track.get("bindings") or motion._quality(track["label"]) != "stage_display"
                or track["label"] != "StageEffect/Expert/Display/light"):
            continue
        owner, fields = source
        try:
            if (not fields["m_Enabled"] or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))
                    or not title._group(objects, owner, fields)):
                continue
        except title._UNSUPPORTED:
            continue
        for event in track["events"]:
            name = event["label"]
            if name not in found:
                continue
            try:
                viewer._remaining(deadline)
                values = event["values"]
                if values.get("clipIn") != 0 or values.get("offset") != _ZERO:
                    continue
                ctrl = particles._source(objects, owner, fields, event)
                if ctrl is None or ctrl[0].peek_name() != name:
                    continue
                shape = _prefab(objects, ctrl[0], name, deadline)
                if shape is not None and event["duration"] <= shape[0][0]["cycle"]:
                    rows, readers, state = shape
                    found[name].append((rows, readers, {**state, "trackId": track["id"], "eventId": event["id"]}))
            except title._UNSUPPORTED:
                continue
    valid = [cues[0] for cues in found.values() if len(cues) == 1]
    if not valid:
        return None
    emitters, readers, _ = valid[0]
    ids = [viewer._key(reader) for reader in readers]
    cues = [cue for rows, surfaces, cue in valid if rows == emitters and [viewer._key(reader) for reader in surfaces] == ids]
    textures = []
    for key, original, expected in zip(ids, readers, _ATLAS_NAMES):
        alias = atlas_refs.get(key) if atlas_refs is not None else None
        if alias == expected:
            textures.append(alias)
            continue
        try:
            mips = particles._texture(original, deadline)
        except title._UNSUPPORTED:
            return None
        if not mips or len(mips) != 10:
            return None
        textures.append(mips)
    return {"emitters": emitters, "cues": cues, "textures": textures}
