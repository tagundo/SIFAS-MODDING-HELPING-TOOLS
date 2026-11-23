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
* An Animator inside the prefab starts its controller's default state when the
  clone activates. Only a single-state controller with AlwaysAnimate culling is
  read, and only its constant curves are applied: a constant ``m_IsActive``
  keeps a node active or inactive and a constant Transform curve replaces the
  authored local pose. Systems under any time-varying activation or Transform
  curve, or whose ParticleSystem/renderer properties are animated, are listed
  as not previewed instead of being drawn statically.

* Billboard renderers draw 3D start rotation: the quad turns by the negated
  start angles in Unity's Euler order (Z, X, Y) inside its alignment frame
  (camera, world or emitter), the rule mv-studio-display-lights.js draws its
  Local strokes with. Other render modes with an X/Y start angle are reported.
* Local scaling mode applies the node's own localScale to local-space
  billboards: positions through the scaled transform, quad X/Y sizes times the
  scale's X/Y (_scaled_billboard). Other scaled cases are reported.

This module only normalizes serialized data. ``mv-studio-particle-systems.js``
simulates and draws it. Textures keep their authored pixels and mip levels.
"""

import base64
import math
import time
import zlib

from . import decode, model_animation as animation, model_viewer as viewer
from . import mv_studio_stage_motion as motion, mv_studio_stage_title as title, mv_studio_timeline as timeline
from .model_materials import _original_mips
from .mv_studio_stage_display import _shader_matches


SCHEMA = 1
_MAX_CUES = 512
_MAX_TEMPLATES = 192
_MAX_SYSTEMS = 1536
_MAX_SYSTEMS_PER_TEMPLATE = 96
_MAX_DEPTH = 24
_MAX_NODES = 4096
_MAX_KEYS = 64
_MAX_TEXTURES = 64
_MAX_TEXTURE_BYTES = 40 * 1024 * 1024
_MAX_TEXTURE_SIZE = 2048
_MAX_PARTICLES = 4096
_RESERVE_SECONDS = 4
# Native quality categories of the CustomControl tracks that start particle prefabs.
_CATEGORIES = {"stage_control", "stage_display", "stage_overlay_effect"}
# Unity ParticleSystemShapeType values this module reproduces. BoxShell and
# BoxEdge (15, 16) are not: the runtime has no boxThickness sampling.
_SHAPES = {0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 18}
# radiusThickness is reproduced only where the runtime has the native rule:
# full-volume spheres and hemispheres (sphereRadius, cbrt(1 - u)), and
# circles and cones at full area (sqrt((1 - u) + .001u)) or on the edge.
_SPHERES, _AREAS = {0, 2}, {4, 8, 10}
# Animator generic bindings: GameObject.m_IsActive (CRC32 of the property
# name), Transform channels, and the particle components themselves.
_GAME_OBJECT, _TRANSFORM, _ACTIVE = 1, 4, zlib.crc32(b"m_IsActive")
_POSITION, _ROTATION, _SCALE, _EULER = 1, 2, 3, 4
_PARTICLE_CLASSES = {198: "ParticleSystem", 199: "ParticleSystemRenderer"}
_SCALING = {0: "Hierarchy", 1: "Local", 2: "Shape"}
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


def _zero(source):
    """A MinMaxCurve that is 0 at every time and weight."""
    state, scalar = source.get("minMaxState"), source.get("scalar")
    if state == 3:
        return scalar == 0 and source.get("minScalar") == 0
    if state not in (0, 1, 2):
        return False
    if scalar == 0:
        return True
    curves = [source.get("maxCurve")] + ([source.get("minCurve")] if state == 2 else [])
    return state != 0 and all(key.get("value") == key.get("inSlope") == key.get("outSlope") == 0
                              for item in curves for key in (item or {}).get("m_Curve") or [])


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
        "randomSeed": seed & 0xFFFFFFFF, "maxParticles": capacity,
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
        # X/Y start rotation is drawn on Billboard quads only (see system()).
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
    thickness = _number(source.get("radiusThickness", 1), 0, 1)
    if (kind in _SPHERES and thickness != 1) or (kind in _AREAS and thickness not in (0, 1)):
        raise _Unsupported("ShapeModule.radiusThickness between surface and full volume")
    return {"type": kind, "radius": _number(radius.get("value", 1), 0, 1e5),
            "radiusThickness": thickness,
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


def _rotation(source):
    # Separate axes keep Z in "curve"; X/Y spin would need a 3D-rotated quad.
    if source.get("enabled") and source.get("separateAxes") and not (_zero(source["x"]) and _zero(source["y"])):
        raise _Unsupported("RotationModule X/Y rotation over lifetime")
    return _over_lifetime(source, (("x", "x"), ("y", "y"), ("z", "curve")))


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


def _planar_alignment(row):
    """alignToDirection that cannot change what a horizontal billboard draws.

    The only native evidence is mv_studio_umbrella_particles.py (the Aion
    umbrella rings): a Circle rotated 90 degrees about X aligns its particles
    to horizontal directions, which writes their initial X/Y Euler channels,
    and a horizontal billboard reads only the Z channel. Exactly that set-up
    is accepted (with SingleSidedEdge, whose one direction is also horizontal
    there) on an emitter that turns about Y only. Everything else is reported.
    """
    shape, renderer, main = row["shape"], row["renderer"], row["main"]
    x, _, z = (value % 360 for value in shape["rotation"])
    return (renderer["mode"] == 2 and renderer["alignment"] == 2 and not main["rotation3D"]
            and shape["type"] in (10, 12) and x == 90 and z == 0
            and shape["randomDirection"] == 0 and shape["sphericalDirection"] == 0)


def _turns_about_y(walked, own):
    """The node's world rotation keeps the horizontal plane (a pure Y turn)."""
    rotation, index = (0.0, 0.0, 0.0, 1.0), own
    while index is not None:
        rotation = animation._multiply(walked[index]["rotation"], rotation)
        index = walked[index]["parent"]
    return abs(rotation[0]) < 1e-6 and abs(rotation[2]) < 1e-6


def _unit_scale(walked, own, scaling):
    """The transform scale the scaling mode applies is the identity.

    Shape mode's emitter-only scale and Hierarchy mode's lossy scale are not
    reproduced; Local mode's own scale is, on the billboards _scaled_billboard
    accepts.
    """
    unit = lambda node: all(abs(value - 1) <= 1e-6 for value in node["scale"])
    if scaling == 1:
        return unit(walked[own])
    index = own
    while index is not None:
        if not unit(walked[index]):
            return False
        index = walked[index]["parent"]
    return True


def _scaled_billboard(source, render_tree, scale):
    """A Local-mode transform scale the runtime applies as Unity does.

    Local scaling uses the system's own localScale (no parent): local-space
    particle positions go through the scaled transform and each billboard
    quad's X/Y size is multiplied by the scale's X/Y, whatever the alignment
    (the fx_dis_par_so2035_02 display clouds are 1-unit particles on 5x3 and
    6x3 nodes). Only that evidenced set-up is accepted: a Billboard renderer,
    local simulation space, a positive scale, and no world-space force or
    velocity whose conversion into the scaled space is unknown.
    """
    initial = source.get("InitialModule") or {}
    velocity, clamp = source.get("VelocityModule") or {}, source.get("ClampVelocityModule") or {}
    return (render_tree.get("m_RenderMode") == 0 and source.get("moveWithTransform") == 0
            and all(value > 1e-6 for value in scale) and _zero(initial.get("gravityModifier") or {})
            and not (velocity.get("enabled") and velocity.get("inWorldSpace"))
            and not (clamp.get("enabled") and clamp.get("inWorldSpace")))


def _alive_bound(row):
    """More live particles than the system can ever hold, or None when a curve hides it.

    Every particle lives at most the peak start lifetime L, so the live ones
    were born within L: at most rate * L (+1 for the rate carry) plus every
    burst firing of each loop that can overlap L.
    """
    def peak(value):
        return value["scalar"] if value["mode"] == 0 else max(value["min"], value["scalar"]) if value["mode"] == 3 else None

    main, emission = row["main"], row["emission"]
    life, rate = peak(main["lifetime"]), peak(emission["rate"])
    if life is None or rate is None:
        return None
    life = max(life, 0)
    loops = math.ceil(life / main["duration"]) + 1 if main["looping"] else 1
    total = math.ceil(max(rate, 0) * life) + 1
    for burst in emission["bursts"]:
        count = peak(burst["count"])
        if count is None:
            return None
        firings = burst["cycles"] or math.floor(main["duration"] / max(burst["interval"], 1e-3)) + 1
        total += loops * firings * math.ceil(max(count, 0))
    return total


def system(objects, game, particle, renderer, textures, blocked=None, *, upright=True):
    """Normalize one ParticleSystem and its renderer, or raise _Unsupported.

    ``blocked`` is a reason from outside the system itself (its prefab
    Animator or transform scale); it is raised after the system's own checks
    and before any texture is read, so the warning names the system's own gap
    first. ``upright`` tells whether the emitter's world rotation is a pure Y turn.
    """
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
        if blocked:
            raise _Unsupported(blocked)
        return None
    # The render mode first: a mesh particle is reported as such before its modules.
    drawn = _renderer(render_tree)
    result = {"main": _main(source), "emission": _emission(source["EmissionModule"]), "shape": _shape(shape),
              "velocity": _velocity(source["VelocityModule"]), "clamp": _clamp(source["ClampVelocityModule"]),
              "size": _over_lifetime(source["SizeModule"], (("x", "curve"), ("y", "y"), ("z", "z"))),
              "rotation": _rotation(source["RotationModule"]),
              "color": color(source["ColorModule"]["gradient"]) if source["ColorModule"].get("enabled") else None,
              "uv": _uv(source["UVModule"]), "rotationBySpeed": _rotation_by_speed(source["RotationBySpeedModule"]),
              "renderer": drawn}
    if result["shape"] and result["shape"]["alignToDirection"] and not (upright and _planar_alignment(result)):
        raise _Unsupported("ShapeModule.alignToDirection")
    initial = source["InitialModule"]
    tilted = result["main"]["rotation3D"] and not (_zero(initial["startRotationX"]) and _zero(initial["startRotationY"]))
    if tilted and drawn["mode"] != 0:
        # The X/Y turn is reproduced on Billboard quads (View, World and Local
        # alignment) only; stretched and horizontal/vertical quads are reported.
        raise _Unsupported("3D start rotation (X/Y axes)")
    if result["main"]["maxParticles"] > _MAX_PARTICLES:
        bound = _alive_bound(result)
        if bound is None or bound >= _MAX_PARTICLES:
            # A capped pool would stop emission earlier than the game does.
            raise _Unsupported(f"maxParticles above the preview limit of {_MAX_PARTICLES}")
        # The authored pool can never fill, so the runtime's smaller one behaves the same.
        result["main"]["maxParticles"] = _MAX_PARTICLES
    if blocked:
        raise _Unsupported(blocked)
    surface, texture = _material(objects, renderer, render_tree)
    surface["texture"] = textures.add(texture)
    result["material"] = surface
    return result


def _walk(objects, prefab, deadline):
    """Every node of the prefab in GetComponentsInChildren order (pre-order, child order).

    Inactive GameObjects are kept so Animator binding paths resolve; ``authored``
    is the clone's activation before any Animator runs.
    """
    walked, stack = [], [(prefab, None, (), 0)]
    while stack:
        viewer._remaining(deadline)
        game, parent, path, depth = stack.pop()
        if depth > _MAX_DEPTH:
            raise _Unsupported("prefab hierarchy is too deep")
        if len(walked) >= _MAX_NODES:
            raise _Unsupported("prefab hierarchy is too large")
        tree, components = _components(objects, game)
        transform = components.get("Transform")
        if transform is None:
            continue
        # Binding hashes use the full names; the shown path keeps them short.
        own_path = (*path, str(tree.get("m_Name", "")))
        transform_tree = transform.read_typetree()
        try:
            pose = _trs(transform_tree)
        except _Unsupported:
            pose = {"position": None, "rotation": None, "scale": None}
        own = len(walked)
        walked.append({"parent": parent, "game": game, "tree": tree, "components": components, "parts": own_path,
                       "path": "/".join(part[:64] for part in own_path), "self": bool(tree.get("m_IsActive", True)),
                       **pose})
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
            stack.append((child_game, own, own_path, depth + 1))
    for node in walked:
        # OnBehaviourPlay activates the clone root itself (SetActive(true)), so only
        # m_IsActive below the root is the prefab's own.
        node["authored"] = node["parent"] is None or (node["self"] and walked[node["parent"]]["authored"])
    return walked


def _flat(curve):
    """The value of a packed clip curve that never changes, else None."""
    mode, keys = curve
    if mode == "constant":
        return keys
    if not keys:
        return None
    if mode == "cubic":
        values = {coefficients[3] for _, coefficients in keys}
        flat = all(coefficients[0] == coefficients[1] == coefficients[2] == 0 for _, coefficients in keys)
        return values.pop() if flat and len(values) == 1 else None
    values = {value for _, value in keys}
    return values.pop() if len(values) == 1 else None


def _default_clip(objects, animator, fields):
    """The clip of a single-state controller's default state, None without a controller.

    Anything else (several layers or states, transitions, blend trees, culling
    other than AlwaysAnimate, object-reference curves) raises _Unsupported.
    """
    controller = title._local(objects, animator, fields.get("m_Controller"))
    if controller is None:
        return None
    if controller.type.name != "AnimatorController":
        raise _Unsupported(f"Animator {controller.type.name}")
    if fields.get("m_CullingMode", 0) != 0:
        raise _Unsupported(f"Animator culling mode {fields.get('m_CullingMode')}")
    tree = controller.read_typetree()
    graph = tree["m_Controller"]
    layers, machines = graph["m_LayerArray"], graph["m_StateMachineArray"]
    if len(layers) != 1 or len(machines) != 1 or layers[0]["data"]["m_StateMachineIndex"] != 0:
        raise _Unsupported("Animator controller with several layers")
    machine = machines[0]["data"]
    states = machine["m_StateConstantArray"]
    if len(states) != 1 or machine["m_DefaultState"] != 0 or machine["m_AnyStateTransitionConstantArray"]:
        raise _Unsupported("Animator controller with several states")
    state = states[0]["data"]
    trees = state["m_BlendTreeConstantArray"]
    if state["m_TransitionConstantArray"] or len(trees) != 1:
        raise _Unsupported("Animator state with transitions or blend trees")
    leaves = trees[0]["data"]["m_NodeArray"]
    if len(leaves) != 1 or leaves[0]["data"].get("m_ChildIndices"):
        raise _Unsupported("Animator state with a blend tree")
    clips = tree.get("m_AnimationClips") or []
    index = leaves[0]["data"].get("m_ClipID")
    if type(index) is not int or not 0 <= index < len(clips):
        raise _Unsupported("Animator state without a clip")
    clip = title._local(objects, controller, clips[index], "AnimationClip")
    if clip is None:
        raise _Unsupported("Animator clip is unavailable")
    return clip.read_typetree()


def _bindings(clip, deadline):
    """(binding, per-channel constant or None) for every generic binding of a packed clip."""
    bindings = (clip.get("m_ClipBindingConstant") or {}).get("genericBindings") or []
    if any(binding.get("isPPtrCurve") for binding in bindings):
        raise _Unsupported("Animator clip with object reference curves")
    if not bindings:
        if any(clip.get(field) for field in ("m_PositionCurves", "m_RotationCurves", "m_ScaleCurves",
                                             "m_EulerCurves", "m_FloatCurves")):
            raise _Unsupported("Animator clip with editor curves")
        return []
    try:
        curves = animation._packed_curves(clip, deadline)
    except animation.AnimationError as error:
        raise _Unsupported(f"Animator clip ({error})") from None
    rows, offset = [], 0
    for binding in bindings:
        width = animation._width(binding)
        selected = curves[offset:offset + width]
        offset += width
        if len(selected) != width:
            raise _Unsupported("Animator clip curves do not match their bindings")
        rows.append((binding, [_flat(curve) for curve in selected]))
    if offset != len(curves):
        raise _Unsupported("Animator clip curves do not match their bindings")
    return rows


def _euler(values):
    # Unity's Quaternion.Euler applies Z, then X, then Y (Unity space, degrees).
    x, y, z = (math.radians(value) * .5 for value in values)
    return list(animation._multiply(animation._multiply((0, math.sin(y), 0, math.cos(y)), (math.sin(x), 0, 0, math.cos(x))),
                                    (0, 0, math.sin(z), math.cos(z))))


def _animators(objects, walked, deadline):
    """Apply what each in-prefab Animator's default state does to the particle nodes.

    Returns (active, moving, unresolved, notes): ``active`` maps a node to a
    constant m_IsActive; ``moving`` maps a node to the curve kinds that change
    over time on it (activation, Transform) or animate its particle components;
    ``unresolved`` maps an Animator node to the reason its controller is not read.
    Constant Transform curves are written into the walked node's local pose.
    """
    active, moving, unresolved, notes, posed = {}, {}, {}, set(), {}
    for own, node in enumerate(walked):
        legacy = node["components"].get("Animation")
        if legacy is not None and node["authored"] and legacy.read_typetree().get("m_Enabled", True):
            # Legacy Animation clips are not read at all.
            unresolved[own] = "legacy Animation component"
        animator = node["components"].get("Animator")
        if animator is None or not node["authored"]:
            continue
        fields = animator.read_typetree()
        if not fields.get("m_Enabled", True):
            continue
        try:
            clip = _default_clip(objects, animator, fields)
            if clip is None:
                continue
            rows = _bindings(clip, deadline)
        except (_Unsupported, *title._UNSUPPORTED) as error:
            unresolved[own] = str(error)[:120] or type(error).__name__
            notes.add("Animator")
            continue
        # Binding paths are CRC32 hashes of the path below the Animator's GameObject.
        prefix, targets = node["parts"], {}
        for index, other in enumerate(walked):
            if other["parts"][:len(prefix)] == prefix:
                targets.setdefault(zlib.crc32("/".join(other["parts"][len(prefix):]).encode("utf-8")), index)
        for binding, values in rows:
            target = targets.get(binding.get("path"))
            kind, attribute = binding.get("typeID", binding.get("classID")), binding.get("attribute")
            if target is None:
                continue
            components = walked[target]["components"]
            if kind == _GAME_OBJECT and attribute == _ACTIVE:
                value = values[0]
                if value in (0, 1) and active.get(target, value) == value:
                    active[target] = value == 1
                else:
                    moving.setdefault(target, set()).add("activation")
            elif kind == _TRANSFORM and attribute in (_POSITION, _ROTATION, _SCALE, _EULER):
                channel = {_POSITION: "position", _SCALE: "scale"}.get(attribute, "rotation")
                if any(value is None for value in values) or (target, channel) in posed:
                    moving.setdefault(target, set()).add("Transform")
                    continue
                posed[target, channel] = True
                if channel == "rotation":
                    rotation = _euler(values) if attribute == _EULER else [_number(value, -2, 2) for value in values]
                    length = math.sqrt(sum(value * value for value in rotation))
                    if not length > 1e-6:
                        raise _Unsupported("Animator rotation curve is not a rotation")
                    walked[target]["rotation"] = [value / length for value in rotation]
                else:
                    walked[target][channel] = [_number(value) for value in values]
            elif kind in _PARTICLE_CLASSES:
                if _PARTICLE_CLASSES[kind] in components:
                    moving.setdefault(target, set()).add(f"{_PARTICLE_CLASSES[kind]} properties")
            else:
                # Mesh renderer material curves and the like: content this preview does not draw.
                notes.add("Animator")
    return active, moving, unresolved, notes


def template(objects, prefab, textures, deadline):
    """Walk the prefab as Unity's GetComponentsInChildren does (pre-order, child order).

    Nodes keep their local TRS (with any constant Animator pose) and parent
    index so the runtime can rebuild the clone's transforms. PrefabControl
    activates the clone root but no inactive GameObject below it.
    """
    walked = _walk(objects, prefab, deadline)
    if not walked:
        raise _Unsupported("prefab has no Transform")
    name = str(walked[0]["tree"].get("m_Name", ""))[:128]
    switched, moving, unresolved, notes = _animators(objects, walked, deadline)
    nodes, systems, unsupported, remap = [], [], [], {}
    live, reasons = [], []
    for own, node in enumerate(walked):
        parent = node["parent"]
        on = switched.get(own, node["self"] or parent is None)
        live.append(on and (parent is None or live[parent]))
        # Why a system on this node is not drawn although the prefab says so.
        inherited = list(reasons[parent]) if parent is not None else []
        if own in unresolved:
            inherited.append(f"under prefab animation that is not previewed ({unresolved[own]})")
        kinds = sorted(kind for kind in moving.get(own, ()) if kind in ("activation", "Transform"))
        if kinds:
            inherited.append(f"animated by the prefab Animator ({', '.join(kinds)})")
        reasons.append(inherited)
    for own, node in enumerate(walked):
        components = node["components"]
        if live[own]:
            if any(node[field] is None for field in ("position", "rotation", "scale")):
                raise _Unsupported("non-finite or out-of-range value")
            remap[own] = len(nodes)
            nodes.append({"parent": remap.get(node["parent"]), "path": node["path"],
                          "layer": node["tree"].get("m_Layer", 0),
                          "position": node["position"], "rotation": node["rotation"], "scale": node["scale"]})
            for kind in ("Animation", "MeshRenderer", "SkinnedMeshRenderer"):
                if kind in components:
                    notes.add(kind)
        if "ParticleSystem" not in components:
            continue
        if not live[own]:
            if node["authored"]:
                # The prefab leaves it active, but its Animator keeps it (or an ancestor) off.
                unsupported.append({"path": node["path"],
                                    "reason": "kept inactive by the prefab Animator (the game never draws it)"})
            continue
        try:
            animated_parts = sorted(kind for kind in moving.get(own, ()) if kind.endswith("properties"))
            blocked = ("activated by the prefab Animator" if not node["authored"] else reasons[own][0] if reasons[own]
                       else f"animated by the prefab Animator ({', '.join(animated_parts)})" if animated_parts else None)
            renderer = components.get("ParticleSystemRenderer")
            if renderer is None:
                raise _Unsupported("ParticleSystem has no renderer")
            if len(systems) >= _MAX_SYSTEMS_PER_TEMPLATE:
                raise _Unsupported("too many systems in one prefab")
            source = components["ParticleSystem"].read_typetree()
            scaling = source.get("scalingMode")
            if (not blocked and scaling in _SCALING and not _unit_scale(walked, own, scaling)
                    and not (scaling == 1 and _scaled_billboard(source, renderer.read_typetree(), node["scale"]))):
                blocked = f"non-unit transform scale ({_SCALING[scaling]} scaling mode)"
            row = system(objects, node["game"], components["ParticleSystem"], renderer, textures, blocked,
                         upright=_turns_about_y(walked, own))
            if row is not None:
                index = remap[own]
                row.update(node=index, path=node["path"], layer=nodes[index]["layer"])
                systems.append(row)
        except (_Unsupported, *title._UNSUPPORTED) as error:
            unsupported.append({"path": node["path"], "reason": str(error)[:160] or type(error).__name__})
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
