"""Read the original Shuriken ParticleSystems that CustomControl clips start.

One common rule for every song, taken from the client and the serialized assets:

* ``CustomControlClip.CreatePlayable`` instantiates ``prefabGameObject`` through
  Unity's ``PrefabControlPlayable`` with no parent, so the clone sits at the world
  root. ``CustomControlClip.ConnectPlayablesToMixer`` then adds the clip
  ``offset`` to the clone position. ``PrefabControlPlayable.Initialize`` leaves
  the clone inactive, so the same method's ``GetComponentsInChildren<ParticleSystem>()``
  (includeInactive=false) finds nothing: ``particleRandomSeed``,
  ``overwriteRandomSeed`` and ``weight`` never reach the particle systems.
* ``OnBehaviourPlay`` activates the clone at the clip start. Every active
  ParticleSystem with ``playOnAwake`` starts there and runs on the player clock
  with its own serialized ``randomSeed`` (``autoRandomSeed=0``) or a fresh auto
  seed. ``OnBehaviourPause`` deactivates the clone at the clip end.

This module only normalizes serialized data. ``mv-studio-particle-systems.js``
simulates and draws it. Textures keep their authored pixels and mip levels.
"""

import base64
import math
import time

from . import decode, model_viewer as viewer
from . import mv_studio_stage_motion as motion, mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_materials import _original_mips
from .mv_studio_stage_display import _shader_matches


SCHEMA = 1
_MAX_CUES = 512
_MAX_TEMPLATES = 192
_MAX_SYSTEMS = 1536
_MAX_SYSTEMS_PER_TEMPLATE = 96
_MAX_DEPTH = 24
_MAX_KEYS = 64
_MAX_TEXTURES = 64
_MAX_TEXTURE_BYTES = 40 * 1024 * 1024
_MAX_TEXTURE_SIZE = 2048
_MAX_PARTICLES = 4096
_RESERVE_SECONDS = 4
# Native quality categories of the CustomControl tracks that start particle prefabs.
_CATEGORIES = {"stage_control", "stage_display", "stage_overlay_effect"}
# Unity ParticleSystemShapeType values this module reproduces.
_SHAPES = {0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 15, 16, 18}
# Renderer modes: Billboard, Stretch, HorizontalBillboard, VerticalBillboard.
_RENDER_MODES = {0, 1, 2, 3}
# Modules read as data. Anything else that is enabled makes the system unsupported.
_READ_MODULES = {"InitialModule", "EmissionModule", "ShapeModule", "VelocityModule", "ClampVelocityModule",
                 "SizeModule", "RotationModule", "ColorModule", "UVModule", "RotationBySpeedModule"}
_UNSUPPORTED_MODULES = ("InheritVelocityModule", "ForceModule", "ExternalForcesModule", "NoiseModule",
                        "SizeBySpeedModule", "ColorBySpeedModule", "CollisionModule", "TriggerModule",
                        "SubModule", "LightsModule", "TrailModule", "CustomDataModule")
_SHADER = "AS/General/Transparent"


class _Unsupported(Exception):
    """A system feature the runtime does not reproduce; reported, never approximated."""


def _number(value, low=-1e6, high=1e6):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise _Unsupported("non-finite or out-of-range value")
    return float(value)


def _vector(value, axes="xyz", low=-1e6, high=1e6):
    if not isinstance(value, dict):
        raise _Unsupported("missing vector")
    return [_number(value.get(axis), low, high) for axis in axes]


def _slope(value):
    # Infinite tangents are Unity's stepped keys; JSON carries them as null.
    if type(value) in (int, float) and math.isinf(value):
        return None
    return _number(value, -1e7, 1e7)


def _keys(curve):
    rows = (curve or {}).get("m_Curve") or []
    if not isinstance(rows, list) or len(rows) > _MAX_KEYS:
        raise _Unsupported("animation curve has too many keys")
    keys = []
    for key in rows:
        stamp = _number(key.get("time"), -1e4, 1e4)
        if keys and stamp < keys[-1][0]:
            raise _Unsupported("unsorted curve keys")
        keys.append([stamp, _number(key.get("value")), _slope(key.get("inSlope")), _slope(key.get("outSlope"))])
    return keys


def curve(source):
    """Normalize a MinMaxCurve: state, scalar, minScalar and the two key lists."""
    state = source.get("minMaxState")
    if state not in (0, 1, 2, 3):
        raise _Unsupported(f"MinMaxCurve state {state}")
    result = {"mode": state, "scalar": _number(source.get("scalar")), "min": _number(source.get("minScalar"))}
    if state in (1, 2):
        result["maxKeys"] = _keys(source.get("maxCurve"))
        if not result["maxKeys"]:
            raise _Unsupported("empty MinMaxCurve")
    if state == 2:
        result["minKeys"] = _keys(source.get("minCurve"))
        if not result["minKeys"]:
            raise _Unsupported("empty MinMaxCurve")
    return result


def _color(value):
    return [_number(value.get(channel), -64, 64) for channel in "rgba"]


def gradient(source):
    """Normalize a Gradient with Unity's 16-bit key stamps (0..65535)."""
    colors, alphas = source.get("m_NumColorKeys"), source.get("m_NumAlphaKeys")
    if type(colors) is not int or type(alphas) is not int or not 1 <= colors <= 8 or not 1 <= alphas <= 8:
        raise _Unsupported("gradient key count")
    mode = source.get("m_Mode", 0)
    if mode not in (0, 1):
        raise _Unsupported(f"gradient mode {mode}")
    rgb, alpha = [], []
    for index in range(colors):
        stamp = source.get(f"ctime{index}")
        if type(stamp) is not int or not 0 <= stamp <= 65535:
            raise _Unsupported("gradient key time")
        rgb.append([stamp, *_color(source[f"key{index}"])[:3]])
    for index in range(alphas):
        stamp = source.get(f"atime{index}")
        if type(stamp) is not int or not 0 <= stamp <= 65535:
            raise _Unsupported("gradient key time")
        alpha.append([stamp, _color(source[f"key{index}"])[3]])
    return {"mode": mode, "rgb": rgb, "alpha": alpha}


def color(source):
    """Normalize a MinMaxGradient (states 0-4)."""
    state = source.get("minMaxState")
    if state not in (0, 1, 2, 3, 4):
        raise _Unsupported(f"MinMaxGradient state {state}")
    result = {"mode": state}
    if state in (0, 2):
        result["max"] = _color(source["maxColor"])
    if state == 2:
        result["min"] = _color(source["minColor"])
    if state in (1, 3, 4):
        result["maxGradient"] = gradient(source["maxGradient"])
    if state == 3:
        result["minGradient"] = gradient(source["minGradient"])
    return result


def _constant(source, value):
    return source.get("minMaxState") == 0 and source.get("scalar") == value or (
        source.get("minMaxState") == 3 and source.get("scalar") == value == source.get("minScalar"))


def _main(source):
    for field, expected in (("useUnscaledTime", False), ("ringBufferMode", 0)):
        if source.get(field) != expected:
            raise _Unsupported(f"{field}={source.get(field)}")
    space = source.get("moveWithTransform")
    if space not in (0, 1):
        raise _Unsupported(f"simulation space {space}")
    scaling = source.get("scalingMode")
    if scaling not in (0, 1, 2):
        raise _Unsupported(f"scaling mode {scaling}")
    seed = source.get("randomSeed")
    if type(seed) is not int or not -0x80000000 <= seed <= 0xFFFFFFFF:
        raise _Unsupported("random seed")
    initial = source["InitialModule"]
    if not initial.get("enabled", True):
        raise _Unsupported("InitialModule disabled")
    capacity = initial.get("maxNumParticles")
    if type(capacity) is not int or not 0 <= capacity <= 1_000_000:
        raise _Unsupported("maxNumParticles")
    result = {
        "duration": _number(source.get("lengthInSec"), 0.0001, 1e5), "looping": bool(source.get("looping")),
        "prewarm": bool(source.get("prewarm")), "startDelay": curve(source["startDelay"]),
        "worldSpace": space == 1, "scalingMode": scaling, "autoRandomSeed": bool(source.get("autoRandomSeed")),
        "randomSeed": seed & 0xFFFFFFFF, "maxParticles": min(capacity, _MAX_PARTICLES),
        "lifetime": curve(initial["startLifetime"]), "speed": curve(initial["startSpeed"]),
        "size": curve(initial["startSize"]), "rotation": curve(initial["startRotation"]),
        "color": color(initial["startColor"]), "gravity": curve(initial["gravityModifier"]),
        "size3D": bool(initial.get("size3D")), "rotation3D": bool(initial.get("rotation3D")),
        "randomizeRotationDirection": _number(initial.get("randomizeRotationDirection", 0), 0, 1),
        "stopAction": source.get("stopAction", 0), "cullingMode": source.get("cullingMode", 0),
        "simulationSpeed": _number(source.get("simulationSpeed", 1), 0.001, 100),
    }
    if result["size3D"]:
        result["sizeY"], result["sizeZ"] = curve(initial["startSizeY"]), curve(initial["startSizeZ"])
    if result["rotation3D"]:
        result["rotationX"], result["rotationY"] = curve(initial["startRotationX"]), curve(initial["startRotationY"])
    return result


def _emission(source):
    if not source.get("enabled"):
        return {"rate": {"mode": 0, "scalar": 0.0, "min": 0.0}, "bursts": []}
    if not _constant(source["rateOverDistance"], 0):
        raise _Unsupported("EmissionModule.rateOverDistance")
    bursts = []
    for burst in (source.get("m_Bursts") or [])[:source.get("m_BurstCount", 0)]:
        cycles = burst.get("cycleCount", 1)
        if type(cycles) is not int or not 0 <= cycles <= 100_000:
            raise _Unsupported("burst cycle count")
        bursts.append({"time": _number(burst.get("time"), 0, 1e5), "count": curve(burst["countCurve"]),
                       "cycles": cycles, "interval": _number(burst.get("repeatInterval", 0), 0, 1e5),
                       "probability": _number(burst.get("probability", 1), 0, 1)})
    return {"rate": curve(source["rateOverTime"]), "bursts": bursts}


def _shape(source):
    if not source.get("enabled"):
        return None
    kind = source.get("type")
    if kind not in _SHAPES:
        raise _Unsupported(f"ShapeModule.type {kind}")
    radius, arc = source.get("radius") or {}, source.get("arc") or {}
    # Random (0) everywhere; BurstSpread (3) for the arc, which spreads one
    # emission batch evenly (mv-studio-sparks-b-simulation.js). Loop and
    # PingPong are not reproduced.
    if radius.get("mode", 0) != 0:
        raise _Unsupported(f"ShapeModule.radius mode {radius.get('mode')}")
    if arc.get("mode", 0) not in (0, 3):
        raise _Unsupported(f"ShapeModule.arc mode {arc.get('mode')}")
    if source.get("placementMode", 0) != 0:
        raise _Unsupported("ShapeModule.placementMode")
    return {"type": kind, "radius": _number(radius.get("value", 1), 0, 1e5),
            "radiusThickness": _number(source.get("radiusThickness", 1), 0, 1),
            "arc": _number(arc.get("value", 360), 0, 360), "arcMode": arc.get("mode", 0),
            "angle": _number(source.get("angle", 25), 0, 90),
            "length": _number(source.get("length", 5), 0, 1e5),
            "boxThickness": _vector(source.get("boxThickness") or {"x": 0, "y": 0, "z": 0}, low=0, high=1),
            "position": _vector(source["m_Position"]), "rotation": _vector(source["m_Rotation"], low=-1e5, high=1e5),
            "scale": _vector(source["m_Scale"]),
            "alignToDirection": bool(source.get("alignToDirection")),
            "randomDirection": _number(source.get("randomDirectionAmount", 0), 0, 1),
            "sphericalDirection": _number(source.get("sphericalDirectionAmount", 0), 0, 1),
            "randomPosition": _number(source.get("randomPositionAmount", 0), 0, 1e5),
            "donutRadius": _number(source.get("donutRadius", 0), 0, 1e5)}


def _velocity(source):
    if not source.get("enabled"):
        return None
    result = {"x": curve(source["x"]), "y": curve(source["y"]), "z": curve(source["z"]),
              "worldSpace": bool(source.get("inWorldSpace"))}
    # Orbital and radial motion around the offset point, scaled with the linear
    # part by the speed modifier (mv-studio-autumn-red-burst-simulation.js).
    names = ("orbitalX", "orbitalY", "orbitalZ", "orbitalOffsetX", "orbitalOffsetY", "orbitalOffsetZ", "radial")
    if any(not _constant(source[name], 0) for name in names):
        result["orbital"] = {name: curve(source[name]) for name in names}
    if not _constant(source["speedModifier"], 1):
        result["speedModifier"] = curve(source["speedModifier"])
    return result


def _clamp(source):
    if not source.get("enabled"):
        return None
    result = {"separateAxes": bool(source.get("separateAxis")), "worldSpace": bool(source.get("inWorldSpace")),
              "dampen": _number(source.get("dampen", 0), 0, 1)}
    if not _constant(source["drag"], 0):
        # Only the evidenced form: drag scaled by particle area and speed squared
        # (mv-studio-moving-burst-simulation.js).
        if not (source.get("multiplyDragByParticleSize") and source.get("multiplyDragByParticleVelocity")):
            raise _Unsupported("ClampVelocityModule.drag without size and velocity scaling")
        result["drag"] = curve(source["drag"])
    if result["separateAxes"]:
        result.update(x=curve(source["x"]), y=curve(source["y"]), z=curve(source["z"]))
    else:
        result["magnitude"] = curve(source["magnitude"])
    return result


def _over_lifetime(source, axes):
    if not source.get("enabled"):
        return None
    if source.get("separateAxes"):
        return {"separateAxes": True, **{axis: curve(source[field]) for axis, field in axes}}
    return {"separateAxes": False, "curve": curve(source["curve"])}


def _uv(source):
    if not source.get("enabled"):
        return None
    if source.get("mode", 0) != 0:
        raise _Unsupported("UVModule sprite mode")
    if source.get("timeMode", 0) != 0:
        raise _Unsupported(f"UVModule.timeMode {source.get('timeMode')}")
    tiles = [source.get("tilesX"), source.get("tilesY")]
    if any(type(value) is not int or not 1 <= value <= 256 for value in tiles):
        raise _Unsupported("UVModule tiles")
    animation = source.get("animationType", 0)
    if animation not in (0, 1):
        raise _Unsupported(f"UVModule.animationType {animation}")
    row = source.get("rowIndex", 0)
    return {"tiles": tiles, "animation": animation, "rowIndex": row if type(row) is int else 0,
            "randomRow": bool(source.get("randomRow")), "frame": curve(source["frameOverTime"]),
            "startFrame": curve(source["startFrame"]), "cycles": _number(source.get("cycles", 1), 0, 1e4),
            "flipU": _number(source.get("flipU", 0), 0, 1), "flipV": _number(source.get("flipV", 0), 0, 1)}


def _rotation_by_speed(source):
    if not source.get("enabled"):
        return None
    if source.get("separateAxes"):
        raise _Unsupported("RotationBySpeedModule.separateAxes")
    return {"curve": curve(source["curve"]), "range": _vector(source["range"], "xy")}


def _renderer(tree):
    mode = tree.get("m_RenderMode")
    if mode == 4:
        raise _Unsupported("mesh render mode")
    if mode not in _RENDER_MODES:
        raise _Unsupported(f"render mode {mode}")
    alignment = tree.get("m_RenderAlignment", 0)
    if mode == 0 and alignment not in (0, 1, 2):
        raise _Unsupported(f"billboard alignment {alignment}")
    sort = tree.get("m_SortMode", 0)
    if sort not in (0, 1, 2, 3):
        raise _Unsupported(f"sort mode {sort}")
    return {"mode": mode, "alignment": alignment, "sortMode": sort,
            "sortingFudge": _number(tree.get("m_SortingFudge", 0)),
            "minParticleSize": _number(tree.get("m_MinParticleSize", 0), 0, 1e3),
            "maxParticleSize": _number(tree.get("m_MaxParticleSize", .5), 0, 1e3),
            "lengthScale": _number(tree.get("m_LengthScale", 2)), "velocityScale": _number(tree.get("m_VelocityScale", 0)),
            "cameraVelocityScale": _number(tree.get("m_CameraVelocityScale", 0)),
            "pivot": _vector(tree.get("m_Pivot") or {"x": 0, "y": 0, "z": 0}),
            "flip": _vector(tree.get("m_Flip") or {"x": 0, "y": 0, "z": 0}, low=0, high=1),
            "allowRoll": bool(tree.get("m_AllowRoll", True)), "sortingOrder": tree.get("m_SortingOrder", 0)}


def _material(objects, renderer, tree):
    materials = tree.get("m_Materials") or []
    if not materials or not (materials[0] or {}).get("m_PathID"):
        raise _Unsupported("renderer material is empty (nothing is drawn)")
    material = viewer._ref(renderer, materials[0])
    if material is None or material.type.name != "Material":
        raise _Unsupported("material is unavailable")
    fields = material.read_typetree()
    if not _shader_matches(material, fields, _SHADER):
        raise _Unsupported("shader is not " + _SHADER)
    floats = viewer._properties(fields, "m_Floats")
    colors = viewer._properties(fields, "m_Colors")
    main = viewer._properties(fields, "m_TexEnvs").get("_MainTex", {})
    keywords = set((fields.get("m_ShaderKeywords") or "").split())
    queue = fields.get("m_CustomRenderQueue", -1)
    tint = colors.get("_TintColor", {"r": 1, "g": 1, "b": 1, "a": 1})
    scale, offset = main.get("m_Scale", {"x": 1, "y": 1}), main.get("m_Offset", {"x": 0, "y": 0})

    def enum(name, default, low, high):
        value = floats.get(name, default)
        if type(value) not in (int, float) or not math.isfinite(value) or value != int(value) or not low <= value <= high:
            raise _Unsupported(f"material {name}")
        return int(value)

    surface = {"name": str(fields.get("m_Name", ""))[:128], "queue": queue if type(queue) is int and queue >= 0 else 3000,
               "tint": _color(tint), "st": [*_vector(scale, "xy"), *_vector(offset, "xy")],
               "vertexColor": "_VERTEX_COLOR_ON" in keywords, "saturate": "_SATURATE_ON" in keywords,
               "blend": [enum("_BlendSrc", 5, 0, 10), enum("_BlendDst", 1, 0, 10)],
               "cull": enum("_CullMode", 0, 0, 2), "zTest": enum("_ZTestMode", 4, 0, 8),
               "zWrite": enum("_ZWriteParam", 0, 0, 1),
               "stencil": [enum("_StencilComp", 8, 0, 8), enum("_StencilRef", 2, 0, 255),
                           enum("_StencilPassOp", 0, 0, 7), enum("_StencilZFailOp", 0, 0, 7)]}
    texture = viewer._ref(material, main.get("m_Texture"))
    if texture is not None and texture.type.name != "Texture2D":
        raise _Unsupported("main texture is not a Texture2D")
    return surface, texture


class _Textures:
    """Authored textures and mip levels, shared by every system that samples them."""

    def __init__(self, deadline):
        self.deadline, self.levels, self.index, self.bytes = deadline, [], {}, 0

    def add(self, reader):
        if reader is None:
            return None
        key = viewer._key(reader)
        if key not in self.index:
            self.index[key] = self._read(reader)
        result = self.index[key]
        if isinstance(result, str):
            raise _Unsupported(result)
        return result

    def _png(self, image):
        png = viewer._png_texture(image, self.deadline)
        self.bytes += len(png)
        if self.bytes > _MAX_TEXTURE_BYTES:
            raise _Unsupported("texture budget exceeded")
        return base64.b64encode(png).decode("ascii")

    def _read(self, reader):
        if len(self.levels) >= _MAX_TEXTURES:
            return "too many textures"
        try:
            texture = reader.read()
            width, height = texture.m_Width, texture.m_Height
            if (type(width) is not int or type(height) is not int or not 0 < width <= _MAX_TEXTURE_SIZE
                    or not 0 < height <= _MAX_TEXTURE_SIZE or width & (width - 1) or height & (height - 1)):
                return "texture size is not a supported power of two"
            settings = texture.m_TextureSettings
            # The authored pixels go out unchanged: no resampling, padding or dilation.
            with decode._android_image(texture, self.deadline, stage=True) as image:
                if image.size != (width, height):
                    return "decoded texture size differs from the asset"
                levels = [{"png": self._png(image), "width": width, "height": height}]
            for proxy in _original_mips(reader, texture, stage=True):
                native = proxy.read()
                with decode._android_image(native, self.deadline, stage=True) as image:
                    levels.append({"png": self._png(image), "width": native.m_Width, "height": native.m_Height})
        except _Unsupported as error:
            return str(error)
        except title._UNSUPPORTED as error:
            return f"texture is unavailable ({type(error).__name__}: {str(error)[:80]})"
        self.levels.append({"name": str(texture.m_Name)[:128], "levels": levels,
                            "filter": int(settings.m_FilterMode), "wrap": [int(settings.m_WrapU), int(settings.m_WrapV)]})
        return len(self.levels) - 1


def _components(objects, game):
    tree = game.read_typetree()
    found = {}
    for entry in tree.get("m_Component") or []:
        component = title._local(objects, game, entry.get("component") or entry.get("second"))
        if component is not None:
            found.setdefault(component.type.name, component)
    return tree, found


def _trs(tree):
    position = _vector(tree["m_LocalPosition"])
    rotation = _vector(tree["m_LocalRotation"], "xyzw", -2, 2)
    scale = _vector(tree["m_LocalScale"])
    return {"position": position, "rotation": rotation, "scale": scale}


def system(objects, game, particle, renderer, textures):
    """Normalize one ParticleSystem and its renderer, or raise _Unsupported."""
    source = particle.read_typetree()
    for name in _UNSUPPORTED_MODULES:
        if (source.get(name) or {}).get("enabled"):
            raise _Unsupported(name)
    if not source.get("playOnAwake"):
        raise _Unsupported("playOnAwake is off (the clone never starts it)")
    shape = source["ShapeModule"]
    if shape.get("enabled") and shape.get("type") in (6, 13, 14):
        raise _Unsupported("mesh emitter shape")
    render_tree = renderer.read_typetree()
    if not render_tree.get("m_Enabled"):
        return None
    result = {"main": _main(source), "emission": _emission(source["EmissionModule"]), "shape": _shape(shape),
              "velocity": _velocity(source["VelocityModule"]), "clamp": _clamp(source["ClampVelocityModule"]),
              "size": _over_lifetime(source["SizeModule"], (("x", "curve"), ("y", "y"), ("z", "z"))),
              "rotation": _over_lifetime(source["RotationModule"], (("x", "x"), ("y", "y"), ("z", "curve"))),
              "color": color(source["ColorModule"]["gradient"]) if source["ColorModule"].get("enabled") else None,
              "uv": _uv(source["UVModule"]), "rotationBySpeed": _rotation_by_speed(source["RotationBySpeedModule"]),
              "renderer": _renderer(render_tree)}
    surface, texture = _material(objects, renderer, render_tree)
    surface["texture"] = textures.add(texture)
    result["material"] = surface
    return result


def template(objects, prefab, textures, deadline):
    """Walk the prefab as Unity's GetComponentsInChildren does (pre-order, child order).

    Nodes keep their local TRS and parent index so the runtime can rebuild the
    clone's transforms; inactive GameObjects are never activated by PrefabControl.
    """
    nodes, systems, unsupported, notes = [], [], [], set()
    root_tree, _ = _components(objects, prefab)
    name = str(root_tree.get("m_Name", ""))[:128]
    stack = [(prefab, None, (), 0)]
    while stack:
        viewer._remaining(deadline)
        game, parent, path, depth = stack.pop()
        if depth > _MAX_DEPTH:
            raise _Unsupported("prefab hierarchy is too deep")
        tree, components = _components(objects, game)
        transform = components.get("Transform")
        if not tree.get("m_IsActive", True) or transform is None:
            continue
        node_path = (*path, str(tree.get("m_Name", ""))[:64])
        transform_tree = transform.read_typetree()
        own = len(nodes)
        nodes.append({"parent": parent, "path": "/".join(node_path), "layer": tree.get("m_Layer", 0),
                      **_trs(transform_tree)})
        for kind in ("Animator", "Animation", "MeshRenderer", "SkinnedMeshRenderer"):
            if kind in components:
                notes.add(kind)
        if "ParticleSystem" in components:
            try:
                renderer = components.get("ParticleSystemRenderer")
                if renderer is None:
                    raise _Unsupported("ParticleSystem has no renderer")
                if len(systems) >= _MAX_SYSTEMS_PER_TEMPLATE:
                    raise _Unsupported("too many systems in one prefab")
                row = system(objects, game, components["ParticleSystem"], renderer, textures)
                if row is not None:
                    row.update(node=own, path=nodes[own]["path"], layer=nodes[own]["layer"])
                    systems.append(row)
            except (_Unsupported, *title._UNSUPPORTED) as error:
                unsupported.append({"path": nodes[own]["path"], "reason": str(error)[:160] or type(error).__name__})
        children = []
        for child in transform_tree.get("m_Children") or []:
            child_transform = title._local(objects, transform, child, "Transform")
            if child_transform is None:
                continue
            child_game = title._local(objects, child_transform, child_transform.read_typetree().get("m_GameObject"),
                                      "GameObject")
            if child_game is not None:
                children.append(child_game)
        for child_game in reversed(children):
            stack.append((child_game, own, node_path, depth + 1))
    return {"name": name, "nodes": nodes, "systems": systems}, unsupported, sorted(notes)


def _muted(objects, owner, tree):
    # A muted GroupTrack silences every CustomControlTrack beneath it.
    for _ in range(_MAX_DEPTH):
        if tree.get("m_Muted"):
            return True
        owner = title._local(objects, owner, tree.get("m_Parent"), "MonoBehaviour")
        if owner is None:
            return False
        tree = owner.read_typetree()
    return False


def _clip(objects, owner, tree, event):
    values = event["values"]
    if values.get("playableClass") != "CustomControlClip":
        return None
    clip = tree["m_Clips"][int(event["id"].rsplit(":", 1)[1])]
    asset = title._local(objects, owner, clip.get("m_Asset"), "MonoBehaviour")
    if asset is None:
        return None
    fields = asset.read_typetree()
    if not title._declared(objects, asset, fields, (*title._NAMESPACE, "CustomControlClip")):
        return None
    prefab = title._local(objects, asset, fields.get("prefabGameObject"), "GameObject")
    if prefab is None:
        return None
    seed = fields.get("particleRandomSeed")
    return prefab, _vector(fields.get("offset"), low=-1e4, high=1e4), seed if type(seed) is int else 0


def claimed_cues(result):
    """(trackId, eventId) pairs that a per-prefab legacy reader already draws."""
    found, stack = set(), [value for key, value in result.items() if key.startswith("stage")]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if isinstance(value.get("trackId"), str) and isinstance(value.get("eventId"), str):
                found.add((value["trackId"], value["eventId"]))
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return found


def read(objects, mono, tracks, deadline, *, claimed=frozenset()):
    """Return the particle templates and cues of every CustomControlTrack, or None."""
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    textures = _Textures(deadline)
    templates, cues, unsupported, notes = [], [], [], {}
    prefab_ids = {}
    for track in tracks:
        source = controls.get(track["id"])
        quality = motion._quality(track["label"])
        if source is None or quality not in _CATEGORIES or track.get("binding") or track.get("bindings"):
            continue
        owner, fields = source
        if (not fields.get("m_Enabled", True) or _muted(objects, owner, fields)
                or not title._declared(objects, owner, fields, (*title._NAMESPACE, "CustomControlTrack"))):
            continue
        for event in track["events"]:
            if (track["id"], event["id"]) in claimed:
                continue
            try:
                found = _clip(objects, owner, fields, event)
            except (_Unsupported, *title._UNSUPPORTED):
                found = None
            if found is None:
                continue
            prefab, offset, seed = found
            key = viewer._key(prefab)
            if key not in prefab_ids:
                prefab_ids[key] = None
                if time.monotonic() > deadline - _RESERVE_SECONDS or len(templates) >= _MAX_TEMPLATES:
                    unsupported.append({"template": event["label"][:128], "path": "", "reason": "import time budget"})
                    continue
                try:
                    row, rejected, kinds = template(objects, prefab, textures, deadline)
                except (_Unsupported, *title._UNSUPPORTED) as error:
                    unsupported.append({"template": event["label"][:128], "path": "", "reason": str(error)[:160]})
                    continue
                for item in rejected:
                    unsupported.append({"template": row["name"], **item})
                if kinds:
                    notes[row["name"]] = kinds
                if row["systems"] and sum(len(item["systems"]) for item in templates) + len(row["systems"]) <= _MAX_SYSTEMS:
                    prefab_ids[key] = len(templates)
                    templates.append(row)
            index = prefab_ids[key]
            if index is None or len(cues) >= _MAX_CUES:
                continue
            cues.append({"trackId": track["id"], "eventId": event["id"], "template": index,
                         "offset": offset, "quality": quality, "clipSeed": seed & 0xFFFFFFFF})
    if not cues and not unsupported:
        return None
    return {"schema": SCHEMA, "textures": textures.levels, "templates": templates, "cues": cues,
            "unsupported": unsupported, "otherComponents": notes}


def warning(descriptor):
    """One project warning that lists what the original prefabs use and the preview leaves out."""
    rows = (descriptor or {}).get("unsupported") or []
    others = (descriptor or {}).get("otherComponents") or {}
    parts = []
    if rows:
        reasons = {}
        for row in rows:
            reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
        listed = ", ".join(f"{reason} x{count}" for reason, count in sorted(reasons.items(), key=lambda item: -item[1]))
        parts.append(f"{len(rows)} original particle systems are not previewed: {listed}.")
    if others:
        kinds = sorted({kind for row in others.values() for kind in row})
        parts.append(f"{len(others)} particle prefabs also hold {', '.join(kinds)} content that is not previewed.")
    return " ".join(parts) or None
