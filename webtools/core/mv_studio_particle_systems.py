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

* Local-aligned Billboard renderers draw 3D start rotation: the quad turns by
  the negated start angles in Unity's Euler order (Z, X, Y) inside the emitter
  frame, the rule mv-studio-display-lights.js draws its Local strokes with.
  libunity.so draws View, World and Local billboards with one geometry routine
  (0xd242c; its variants 0xd78f4, 0xdd314 and 0xdf694 are picked by flags other
  than the alignment in 0xcb86c) that turns the quad in its own unscaled
  coefficients and then maps them through the alignment's three axes. The
  camera axes of View alignment (0xc37d8) and the X/Y turn on World quads are
  not yet checked against a game frame, so X/Y start rotation on View or
  World billboards stays reported, as on the other render modes.
* Local scaling mode applies the node's own localScale to local-space
  billboards (_scaled_billboard): positions through the scaled transform, and
  the quad axes times the scale component-wise in world space, after the roll
  and 3D turn; the min/max size cap is checked on the unscaled quad against
  the limit over the scale's X (libunity.so 0xc35c4, 0xd2844, 0xd2c30). Other
  scaled cases are reported.
* Unity culling freezes a looping procedural Automatic (cullingMode 0) system
  and any Pause (cullingMode 2) system while its renderer is invisible, and
  resumes it without catching up (libunity.so GL 3.12.0, Unity 2018.4: the
  ParticleSystemRenderer visibility callbacks 0xc2618 / 0xc2648 in vtable
  slots 0xe11d58 / 0xe11d60 call uncull 0x1cbd10 / cull 0x1cc5d8), so its
  clock lags the clip by however long the main camera looked away.
  culling() gives the runtime the procedural flag (procedural(), 0x1d1910)
  and the system's local culling box (procedural_bounds(), 0x1d0480); the
  runtime replays the main camera's visibility of that box frame by frame.
  Where the box is not reproduced the system keeps its always-simulating
  preview, and the two billboard cases above, whose look depends on the
  clock, stay reported (_paused_off_screen). PauseAndCatchup systems catch up
  when they come back and keep their always-simulating preview.

This module only normalizes serialized data. ``mv-studio-particle-systems.js``
simulates and draws it. Textures keep their authored pixels and mip levels.
"""

import base64
import math
import time
import zlib

from . import decode, model_animation as animation, model_viewer as viewer
from . import mv_studio_prefab_animator as animator
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


# A system feature the runtime does not reproduce; reported, never approximated.
_Unsupported = animator.Unsupported


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
        # X/Y start rotation is drawn on Local billboards only (see system()).
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
    return surface(objects, renderer, materials[0] if materials else None)


def surface(objects, owner, pointer):
    """(surface, texture reader) of one AS/General/Transparent material, or raise _Unsupported.

    Shared with mv_studio_control_prefabs, whose meshes use the same shader.
    """
    if not (pointer or {}).get("m_PathID"):
        raise _Unsupported("renderer material is empty (nothing is drawn)")
    material = viewer._ref(owner, pointer)
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

    libunity.so (GL 3.12.0, Unity 2018.4):

    * 0x1cca20 keeps the scaling-mode scale s in the ParticleSystem state at
      +0x154: Hierarchy the lossy scale, Local the node's own localScale
      (0x1cd2f0), Shape (1, 1, 1). The local-to-world matrix is the node's
      world rotation and position times diag(s) (Matrix4x4::Scale 0x210684).
    * The renderer job copies s (0xc3528) and divides the renderer's min/max
      particle size by max(s.x, 1e-5) before the camera factor (0xc35c4).
    * The View/World/Local billboard geometry (0xd242c and its variants
      0xd78f4, 0xdd314, 0xdf694) multiplies its three quad axes
      component-wise by s in world space (0xd2844), turns each particle by
      its roll and 3D rotation in the unscaled quad coefficients (0xd301c),
      and caps the particle's own, unscaled larger side (0xd2c30).

    So positions go through the scaled transform, the quad keeps its unscaled
    size and turns, its axes carry s, and the cap sees the size times s.x.
    Only this set-up is accepted: a Billboard renderer, local simulation space,
    a positive scale, and no world-space force or velocity whose conversion
    into the scaled space is unknown. system() still reports it on a system
    whose culling the runtime cannot replay (_paused_off_screen).
    """
    initial = source.get("InitialModule") or {}
    velocity, clamp = source.get("VelocityModule") or {}, source.get("ClampVelocityModule") or {}
    return (render_tree.get("m_RenderMode") == 0 and source.get("moveWithTransform") == 0
            and all(value > 1e-6 for value in scale) and _zero(initial.get("gravityModifier") or {})
            and not (velocity.get("enabled") and velocity.get("inWorldSpace"))
            and not (clamp.get("enabled") and clamp.get("inWorldSpace")))


# ---------------------------------------------------------------- culling
# libunity.so (GL 3.12.0, Unity 2018.4.23f1). The serialized module fields
# below were mapped through the ParticleSystem Transfer (0x1df058: modules at
# ParticleSystem +0x50, InitialModule +0x0, Shape +0x200, Emission +0x490,
# Size +0x6f0, Rotation +0x768, Velocity +0x8f8, Force +0xaa0, ExternalForces
# +0xb60, ClampVelocity +0xb98, Noise +0xc50, SizeBySpeed +0xdc8,
# RotationBySpeed +0xe48, Collision +0xf20, Trail +0x1030, Trigger +0x1128,
# Sub +0x1160, Lights +0x1190; each module's enabled byte at +0x8) and the
# main-module Transfer 0x660780 (read-only block at ParticleSystem +0x40:
# lengthInSec +0x28, looping +0x35, prewarm +0x36, stopAction +0x3c,
# cullingMode +0x40, moveWithTransform +0x44, scalingMode +0x48).
_GRAVITY = 9.81
_PROCEDURAL_OFF = ("ExternalForcesModule", "ClampVelocityModule", "RotationBySpeedModule", "CollisionModule",
                   "TriggerModule", "SubModule", "NoiseModule")
# 0x167920: the shape's own box before its transform, by ParticleSystemShapeType.
_SHAPE_BOX = {
    0: lambda r: ([-r, -r, -r], [r, r, r]), 2: lambda r: ([-r, -r, 0.0], [r, r, r]),
    4: lambda r: ([-r, -r, 0.0], [r, r, 0.0]), 5: lambda r: ([-.5, -.5, -.5], [.5, .5, .5]),
    10: lambda r: ([-r, -r, -.1], [r, r, .1]), 12: lambda r: ([-r, -.1, -.1], [r, .1, .1]),
    18: lambda r: ([-.5, -.5, 0.0], [.5, .5, 0.0]),
}
# 0x167f20.. (jump table 0xb38d00): the box of emission directions per type.
_SHAPE_DIRECTIONS = {0: ([-1, -1, -1], [1, 1, 1]), 10: ([-1, -1, -1], [1, 1, 1]), 2: ([-1, -1, 0], [1, 1, 1]),
                     5: ([0, 0, 0], [0, 0, 1]), 18: ([0, 0, 0], [0, 0, 1]), 12: ([0, 0, 0], [0, 1, 0])}


def _curve_procedural(source):
    """0x1da114 returns 0: the curve fits Unity's 8-segment polynomial curve.

    Keys before 0 or after 1 add a segment unless the curve starts at 0 or
    ends at 1, and a Loop or PingPong wrap there (serialized m_PreInfinity /
    m_PostInfinity 1 or 0; table 0xb46a20 maps them to WrapMode 2 and 4)
    rules it out.
    """
    keys = (source or {}).get("m_Curve") or []
    if not keys:
        return True
    segments = len(keys) - 1
    if keys[0].get("time") != 0:
        if source.get("m_PreInfinity") in (0, 1):
            return False
        segments = len(keys)
    if keys[-1].get("time") != 1:
        if source.get("m_PostInfinity") in (0, 1):
            return False
        segments += 1
    return segments < 9


def _minmax_procedural(source):
    state = (source or {}).get("minMaxState")
    if state not in (1, 2):
        return True
    return _curve_procedural(source.get("maxCurve")) and (state != 2 or _curve_procedural(source.get("minCurve")))


def procedural(source):
    """The procedural flag Play stores at state +0x21 (0x1d1910), from the serialized ParticleSystem.

    Automatic culling (0x1cc5d8) pauses only a looping system with this flag;
    the client reads it back as automaticCullingEnabled (0x1d4ee8).
    """
    if source.get("moveWithTransform") != 0 or source.get("stopAction", 0) != 0:
        return False
    if ((source.get("EmissionModule") or {}).get("rateOverDistance") or {}).get("scalar", 0) != 0:
        return False
    if any((source.get(name) or {}).get("enabled") for name in _PROCEDURAL_OFF):
        return False
    trail = source.get("TrailModule") or {}
    if trail.get("enabled") and not trail.get("mode"):
        return False
    initial = source.get("InitialModule") or {}
    if initial.get("enabled", True):
        if (initial.get("gravityModifier") or {}).get("minMaxState", 0) != 0:
            return False
        if math.isinf((initial.get("startLifetime") or {}).get("scalar", 0)):
            return False
    shape = source.get("ShapeModule") or {}
    if shape.get("enabled"):
        kind = shape.get("type")
        if kind in (4, 8, 10, 17) and (shape.get("arc") or {}).get("mode", 0) != 0:
            return False
        if kind == 12 and (shape.get("radius") or {}).get("mode", 0) != 0:
            return False
    rotation = source.get("RotationModule") or {}
    if rotation.get("enabled"):
        axes = ("curve", "x", "y") if rotation.get("separateAxes") else ("curve",)
        if not all(_minmax_procedural(rotation.get(axis)) for axis in axes):
            return False
    velocity = source.get("VelocityModule") or {}
    if velocity.get("enabled"):
        if not all(_minmax_procedural(velocity.get(axis)) for axis in "xyz"):
            return False
        if any((velocity.get(name) or {}).get("scalar", 0) != 0 for name in ("orbitalX", "orbitalY", "orbitalZ",
                                                                             "radial")):
            return False
    force = source.get("ForceModule") or {}
    if force.get("enabled"):
        if not all(_minmax_procedural(force.get(axis)) for axis in "xyz") or force.get("randomizePerFrame"):
            return False
    return True


def _segments(source):
    """Cubic coefficients (a, b, c, d) of each keyed segment over u = t - t0, with its length.

    Unity's Hermite segment; an infinite tangent holds the left key's value.
    """
    keys = (source or {}).get("m_Curve") or []
    rows = []
    for left, right in zip(keys, keys[1:]):
        t0, t1 = float(left["time"]), float(right["time"])
        v0, v1 = float(left["value"]), float(right["value"])
        span = t1 - t0
        out, inn = left.get("outSlope"), right.get("inSlope")
        if span <= 0:
            continue
        if not (isinstance(out, (int, float)) and math.isfinite(out) and isinstance(inn, (int, float))
                and math.isfinite(inn)):
            rows.append((t0, span, 0.0, 0.0, 0.0, v0))
            continue
        a = (2 * (v0 - v1) + (out + inn) * span) / span ** 3
        b = (3 * (v1 - v0) - (2 * out + inn) * span) / span ** 2
        rows.append((t0, span, a, b, float(out), v0))
    return keys, rows


def _cubic(a, b, c, d, u):
    return ((a * u + b) * u + c) * u + d


def _curve_range(source, low=math.inf, high=-math.inf):
    """0x1db800: the value range of an AnimationCurve over its keys (keys and segment extrema)."""
    keys, rows = _segments(source)
    if not keys:
        return low, high
    low, high = min(low, float(keys[0]["value"])), max(high, float(keys[0]["value"]))
    for _t0, span, a, b, c, d in rows:
        # Extrema where 3a u^2 + 2b u + c = 0 inside the segment.
        roots = []
        if abs(3 * a) > 1e-12:
            disc = 4 * b * b - 12 * a * c
            if disc >= 0:
                root = math.sqrt(disc)
                roots = [(-2 * b + root) / (6 * a), (-2 * b - root) / (6 * a)]
        elif abs(b) > 1e-12:
            roots = [-c / (2 * b)]
        for u in roots + [span]:
            if 0 <= u <= span:
                value = _cubic(a, b, c, d, u)
                low, high = min(low, value), max(high, value)
    return low, high


def value_range(source):
    """MinMaxCurve value range as the procedural bounds read it (0x1d0918, 0x1db800).

    Constant: (0, s) or (s, 0). Two constants: sorted. Curves: their value
    range times the scalar, in that order (a negative scalar swaps the ends).
    """
    state, scalar = source.get("minMaxState"), float(source.get("scalar", 0))
    if state == 0:
        return (0.0, scalar) if scalar > 0 else (scalar, 0.0)
    if state == 3:
        low = float(source.get("minScalar", 0))
        return (low, scalar) if scalar > low else (scalar, low)
    low, high = _curve_range(source.get("maxCurve"))
    if state == 2:
        low, high = _curve_range(source.get("minCurve"), low, high)
    return low * scalar, high * scalar


def _integral_range(source, scalar):
    """Range of the curve's integral from 0 to t over t in [0, 1] (0x1dbaec: polynomial curve
    0x1da5b4, integral 0x1da7ac, extrema 0x1dacf0), times the scalar. Constant before the first
    and after the last key."""
    keys, rows = _segments(source)
    if not keys:
        return 0.0, 0.0
    first, last = float(keys[0]["time"]), float(keys[-1]["time"])
    # Pieces (start, end, a, b, c, d) in absolute time, clipped to [0, 1].
    pieces = []
    if first > 0:
        pieces.append((0.0, min(first, 1.0), 0, 0, 0, float(keys[0]["value"]), 0.0))
    for t0, span, a, b, c, d in rows:
        pieces.append((t0, t0 + span, a, b, c, d, t0))
    if last < 1:
        pieces.append((max(last, 0.0), 1.0, 0, 0, 0, float(keys[-1]["value"]), max(last, 0.0)))
    total, low, high = 0.0, 0.0, 0.0
    for start, end, a, b, c, d, origin in pieces:
        start, end = max(start, 0.0), min(end, 1.0)
        if end <= start:
            continue

        def integral(u, a=a, b=b, c=c, d=d):
            return ((a / 4 * u + b / 3) * u + c / 2) * u * u + d * u

        base = integral(start - origin)
        # The integral's extrema inside the piece are where the curve crosses 0.
        candidates = [end]
        if a or b or c:
            steps = 64
            previous = None
            for index in range(steps + 1):
                u = start + (end - start) * index / steps
                value = _cubic(a, b, c, d, u - origin)
                if previous is not None and (previous[1] < 0) != (value < 0):
                    lo, hi = previous[0], u
                    for _ in range(60):
                        mid = (lo + hi) / 2
                        if (_cubic(a, b, c, d, lo - origin) < 0) != (_cubic(a, b, c, d, mid - origin) < 0):
                            hi = mid
                        else:
                            lo = mid
                    candidates.append((lo + hi) / 2)
                previous = (u, value)
        for u in candidates:
            value = total + integral(u - origin) - base
            low, high = min(low, value), max(high, value)
        total += integral(end - origin) - base
    return low * scalar, high * scalar


def integral_range(source):
    """MinMaxCurve integral range (0x1dbaec): constants as value_range, curves integrated over [0, 1]."""
    state, scalar = source.get("minMaxState"), float(source.get("scalar", 0))
    if state in (0, 3):
        return value_range(source)
    low, high = _integral_range(source.get("maxCurve"), scalar)
    if state == 2:
        other = _integral_range(source.get("minCurve"), scalar)
        low, high = min(low, other[0]), max(high, other[1])
    return low, high


def _euler_matrix(degrees):
    """Rotation matrix (rows) of Unity's Euler angles: Z, then X, then Y."""
    x, y, z = (math.radians(value) for value in degrees)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
    rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    mul = lambda p, q: [[sum(p[i][k] * q[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return mul(ry, mul(rx, rz))


def _transform_box(matrix, low, high, offset=(0, 0, 0)):
    """0x47d910: the box of a transformed min/max box (center and absolute extents)."""
    center = [(low[i] + high[i]) / 2 for i in range(3)]
    extent = [(high[i] - low[i]) / 2 for i in range(3)]
    moved = [sum(matrix[i][k] * center[k] for k in range(3)) + offset[i] for i in range(3)]
    reach = [sum(abs(matrix[i][k]) * extent[k] for k in range(3)) for i in range(3)]
    return [moved[i] - reach[i] for i in range(3)], [moved[i] + reach[i] for i in range(3)]


def _shape_bounds(shape, low_move, high_move):
    """0x167920: the emitter shape's box, widened by the start displacement along its directions."""
    kind = shape.get("type")
    if kind not in _SHAPE_BOX:
        raise _Unsupported(f"its culling bounds for shape type {kind} are not reproduced")
    radius = float((shape.get("radius") or {}).get("value", 1))
    low, high = _SHAPE_BOX[kind](radius)
    rotation = _euler_matrix(_vector(shape["m_Rotation"], low=-1e5, high=1e5))
    scale = _vector(shape["m_Scale"])
    scaled = [[rotation[i][j] * scale[j] for j in range(3)] for i in range(3)]
    low, high = _transform_box(scaled, low, high, _vector(shape["m_Position"]))
    if (shape.get("randomDirectionAmount") or 0) > 0:
        if kind == 4:
            spread = math.sin(math.radians(float(shape.get("angle", 25))))
            directions = ([-spread, -spread, 0], [spread, spread, 1])
        else:
            directions = ([-1, -1, -1], [1, 1, 1])
            low_move, high_move = abs(low_move), abs(high_move)
    elif kind == 4:
        spread = math.sin(math.radians(float(shape.get("angle", 25))))
        directions = ([-spread, -spread, 0], [spread, spread, 1])
    else:
        directions = _SHAPE_DIRECTIONS[kind]
    d_low, d_high = _transform_box(rotation, *directions)
    low = [min(low[i], low[i] + high_move * d_low[i]) for i in range(3)]
    high = [max(high[i], high[i] + high_move * d_high[i]) for i in range(3)]
    low = [min(low[i], low_move * d_low[i], low_move * d_high[i]) for i in range(3)]
    high = [max(high[i], low_move * d_low[i], low_move * d_high[i]) for i in range(3)]
    return low, high


def procedural_bounds(source, render_tree):
    """The local-space box Play gives a procedural system (0x1d0480, procedural branch 0x1d08fc).

    Displacement: start speed range times the longest start lifetime along +Z,
    or the emitter shape's box widened along its directions (0x167920); the
    gravity term 0.5 g L^2 times the constant modifier; the velocity module's
    integral range times L (0x5dc6d8); the Stretch length (0x1d0f34); then
    every side widens by the largest start size (times the size module's
    peak) times the largest pivot component, and again times 0.71. Pieces
    whose rule is not mapped here (a non-zero gravity modifier, world-space
    velocity, the Shape scaling mode with a shape, other shape types) raise
    _Unsupported.
    """
    initial = source["InitialModule"]
    life = value_range(initial["startLifetime"])[1]
    speed = value_range(initial["startSpeed"])
    move = (speed[0] * life, speed[1] * life)
    low = [0.0, 0.0, min(0.0, *move)]
    high = [0.0, 0.0, max(0.0, *move)]
    shape = source.get("ShapeModule") or {}
    if shape.get("enabled"):
        if source.get("scalingMode") == 2:
            raise _Unsupported("its culling bounds with the Shape scaling mode are not reproduced")
        low, high = _shape_bounds(shape, *move)
    gravity = initial.get("gravityModifier") or {}
    if float(gravity.get("scalar", 0)) != 0:
        raise _Unsupported("its culling bounds with gravity are not reproduced")
    velocity = source.get("VelocityModule") or {}
    if velocity.get("enabled"):
        ranges = [integral_range(velocity[axis]) for axis in "xyz"]
        if velocity.get("inWorldSpace") and any(value for pair in ranges for value in pair):
            raise _Unsupported("its culling bounds with world-space velocity are not reproduced")
        low = [min(low[i], low[i] + ranges[i][0] * life) for i in range(3)]
        high = [max(high[i], high[i] + ranges[i][1] * life) for i in range(3)]
    mode = render_tree.get("m_RenderMode")
    if mode not in (0, 1, 2, 3):
        raise _Unsupported(f"its culling bounds for render mode {mode} are not reproduced")
    if mode == 1:
        # Stretch (0x1d0f34): the peak start speed times m_VelocityScale
        # (renderer +0x1d0) plus m_LengthScale (+0x1d4) times the peak start
        # size (Y with size3D); only the first term below a 1e-6 speed.
        fastest = speed[1]
        reach = abs(float(render_tree.get("m_VelocityScale", 0)))
        if fastest > 1e-6:
            longest = value_range(initial["startSizeY" if initial.get("size3D") else "startSize"])[1]
            reach += abs(float(render_tree.get("m_LengthScale", 2))) * longest / fastest
        reach *= fastest
        low, high = [value - reach for value in low], [value + reach for value in high]
    size_module = source.get("SizeModule") or {}
    speed_module = source.get("SizeBySpeedModule") or {}
    # Particle data keeps 3D sizes (+0x794, set by 0x1c6a28) for size3D or a
    # separate-axes size module (0x1d2d40..0x1d2e9c); the box then takes the
    # largest of the three axes.
    three = initial.get("size3D") or (size_module.get("enabled") and size_module.get("separateAxes")) or (
        speed_module.get("enabled") and speed_module.get("separateAxes"))
    largest = 0.0
    for start, over in zip(("startSize", "startSizeY", "startSizeZ")[:3 if three else 1], ("curve", "y", "z")):
        peak = value_range(initial[start])[1]
        if size_module.get("enabled"):
            peak *= value_range(size_module[over])[1]
        if speed_module.get("enabled"):
            peak *= value_range(speed_module[over])[1]
        largest = max(largest, peak)
    pivot = render_tree.get("m_Pivot") or {}
    widen = largest * max(abs(float(pivot.get(axis, 0))) for axis in "xyz")
    low, high = [value - widen for value in low], [value + widen for value in high]
    widen = largest * 0.71
    return [value - widen for value in low] + [value + widen for value in high]


def culling(source, render_tree):
    """How Unity culling treats this system off screen, as the runtime draws it.

    libunity.so: the ParticleSystemRenderer visibility callbacks 0xc2618
    (became visible) and 0xc2648 (became invisible), vtable slots 0xe11d58 /
    0xe11d60, call uncull 0x1cbd10 and cull 0x1cc5d8, and the per-system
    update end 0x1cde54 culls a system whose renderer was not visible
    (renderer +0x129 bit 4). Cull: mode 3 (AlwaysSimulate) never; mode 0
    (Automatic) only a looping system with the procedural flag (procedural());
    modes 1 and 2 always. It freezes the clock (the system leaves the update
    list) and keeps the particles. Uncull catches up only for mode 1
    (PauseAndCatchup); modes 0 and 2 resume where they stopped.

    The renderer's culling box (0xc09ec, registered for renderer type 7 at
    0xc01f4) is the procedural box (procedural_bounds) through the
    local-to-world matrix (state +0x3c: world pose times the scaling-mode
    scale); with View alignment (renderer +0x1e4 == 0) each scaled column
    takes the largest scale instead. A non-procedural system's box follows its
    particles, which is not reproduced for Pause culling.

    ``pauses``: culling freezes this system's clock off screen. ``bounds``:
    the local box, or None with ``reason`` when it is not reproduced.
    ``uniform``: the View-alignment largest-scale rule applies.
    """
    mode = source.get("cullingMode", 0)
    flag = procedural(source)
    pauses = mode == 2 or (mode == 0 and bool(source.get("looping")) and flag)
    result = {"pauses": pauses, "bounds": None, "uniform": render_tree.get("m_RenderAlignment", 0) == 0}
    if not pauses:
        return result
    if not flag:
        result["reason"] = "Pause culling of a non-procedural system (its particle bounds are not reproduced)"
        return result
    try:
        result["bounds"] = [_number(value) for value in procedural_bounds(source, render_tree)]
    except _Unsupported as exc:
        result["reason"] = str(exc)
    except (KeyError, TypeError, ValueError):
        result["reason"] = "its culling bounds could not be read"
    return result


def _paused_off_screen(main, cull=None):
    """Why culling freezes this system's clock in a way the runtime cannot draw, or None.

    The runtime reproduces culling from ``culling()``: a system whose clock
    culling freezes is drawn when its culling box is reproduced. Without that
    box, the cases whose look depends on the clock (3D start rotation and a
    Local-mode node scale) stay reported.
    """
    if cull is not None:
        if not cull["pauses"] or cull["bounds"] is not None:
            return None
        mode = main.get("cullingMode", 0)
        kind = "Pause" if mode == 2 else "Automatic"
        return f"{kind} culling pauses it off screen, and {cull.get('reason', 'its culling bounds are not reproduced')}"
    mode = main.get("cullingMode", 0)
    if mode == 2:
        return "Pause culling pauses it off screen (not reproduced)"
    if mode == 0 and main.get("looping"):
        return "Automatic culling may pause it off screen (not reproduced)"
    return None


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


def system(objects, game, particle, renderer, textures, blocked=None, *, upright=True, scaled=False):
    """Normalize one ParticleSystem and its renderer, or raise _Unsupported.

    ``blocked`` is a reason from outside the system itself (its prefab
    Animator or transform scale); it is raised after the system's own checks
    and before any texture is read, so the warning names the system's own gap
    first. ``upright`` tells whether the emitter's world rotation is a pure Y turn.
    ``scaled`` tells that a non-unit Local-mode node scale was accepted for it
    (_scaled_billboard).
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
        raise _Unsupported("3D start rotation (X/Y axes)")
    if tilted and drawn["alignment"] != 2:
        # Only the emitter frame of Local alignment is evidenced (display-light
        # strokes, the 12035 shot 34/35 light X-cross). The handedness of the
        # View camera frame and the World frame for the X/Y turn is not.
        raise _Unsupported("3D start rotation (X/Y axes) on a View or World billboard")
    result["culling"] = culling(source, render_tree)
    paused = _paused_off_screen(result["main"], result["culling"]) if tilted or scaled else None
    if paused:
        # Its look depends on how long it was culled, which is not reproduced.
        raise _Unsupported(paused)
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


# The Animator reader is shared with the prefab instancer (mv_studio_control_prefabs).
_flat, _default_clip, _bindings, _euler = animator.flat, animator.default_clip, animator.bindings, animator.euler


def _animators(objects, walked, deadline):
    """Apply what each in-prefab Animator's default state does to the particle nodes.

    Returns (active, moving, unresolved, notes, driven): ``active`` maps a node
    to a constant m_IsActive; ``moving`` maps a node to the curve kinds that
    change over time on it (activation, Transform, translation) or animate its
    particle components; ``unresolved`` maps an Animator node to the reason its
    controller is not read. Constant Transform curves are written into the
    walked node's local pose. ``driven`` holds the time-varying curves the
    runtime plays (mv_studio_prefab_animator): node translations and the
    renderer's _TintColor/_MainTex_ST, with the clip timing of their Animator;
    ``driven["unsupported"]`` maps a node to the reason a renderer material
    binding on it is not reproduced, worded as mv_studio_prefab_animator.channels
    reports a mesh renderer's.
    """
    active, moving, unresolved, notes, posed = {}, {}, {}, set(), {}
    driven = {"clips": [], "nodes": {}, "renderers": {}, "unsupported": {}}
    for own, node in enumerate(walked):
        legacy = node["components"].get("Animation")
        if legacy is not None and node["authored"] and legacy.read_typetree().get("m_Enabled", True):
            # Legacy Animation clips are not read at all.
            unresolved[own] = "legacy Animation component"
        component = node["components"].get("Animator")
        if component is None or not node["authored"]:
            continue
        fields = component.read_typetree()
        if not fields.get("m_Enabled", True):
            continue
        try:
            clip = _default_clip(objects, component, fields)
            if clip is None:
                continue
            rows = _bindings(clip, deadline)
            # A stand-in clip without a muscle range only plays its constants.
            timing = animator.timing(clip) if "m_MuscleClip" in clip else None
        except (_Unsupported, *title._UNSUPPORTED) as error:
            unresolved[own] = str(error)[:120] or type(error).__name__
            notes.add("Animator")
            continue
        clip_index = None
        # Binding paths are CRC32 hashes of the path below the Animator's GameObject.
        targets, lanes, both_families = animator.targets(walked, own), {}, set()
        for binding, values, *rest in rows:
            curves = rest[0] if rest else None
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
                    # A moving position is played at runtime under local-space systems.
                    playable = (attribute == _POSITION and curves is not None and timing is not None
                                and (target, channel) not in posed)
                    if playable:
                        if clip_index is None:
                            clip_index = len(driven["clips"])
                            driven["clips"].append(timing)
                        driven["nodes"].setdefault(target, []).append(
                            {"clip": clip_index, "kind": "translation",
                             "curves": [animator.json_curve(curve) for curve in curves]})
                    posed[target, channel] = True
                    moving.setdefault(target, set()).add("translation" if playable else "Transform")
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
                if _PARTICLE_CLASSES[kind] not in components:
                    continue
                lane = animator.material_lane(binding) if kind == 199 else None
                if lane is not None and curves is not None and timing is not None:
                    found = lanes.setdefault((target, lane[0]), {})
                    if lane[1] in found:
                        both_families.add((target, lane[0]))
                    found[lane[1]] = curves[0]
                else:
                    moving.setdefault(target, set()).add(f"{_PARTICLE_CLASSES[kind]} properties")
            else:
                # Mesh renderer material curves and the like: drawn by mv_studio_control_prefabs.
                notes.add("Animator")
        for (target, prop), found in lanes.items():
            if (target, prop) in both_families or set(found) != {0, 1, 2, 3}:
                moving.setdefault(target, set()).add("ParticleSystemRenderer properties")
                driven["unsupported"].setdefault(target, animator.lane_reason(prop, (target, prop) in both_families))
                continue
            if prop in {row["kind"] for row in driven["renderers"].get(target, ())}:
                moving.setdefault(target, set()).add("ParticleSystemRenderer properties")
                continue
            if clip_index is None:
                clip_index = len(driven["clips"])
                driven["clips"].append(timing)
            driven["renderers"].setdefault(target, []).append(
                {"clip": clip_index, "kind": prop, "curves": [animator.json_curve(found[i]) for i in range(4)]})
    return active, moving, unresolved, notes, driven


def template(objects, prefab, textures, deadline, walked=None):
    """Walk the prefab as Unity's GetComponentsInChildren does (pre-order, child order).

    Nodes keep their local TRS (with any constant Animator pose) and parent
    index so the runtime can rebuild the clone's transforms. PrefabControl
    activates the clone root but no inactive GameObject below it. A system
    under an Animator that moves a node's position over time (and nothing
    else) is drawn when it simulates in local space: ``animation`` lists those
    translation curves and the renderer _TintColor/_MainTex_ST curves, which
    the runtime samples at the Animator's time since activation.
    """
    walked = _walk(objects, prefab, deadline) if walked is None else walked
    if not walked:
        raise _Unsupported("prefab has no Transform")
    name = str(walked[0]["tree"].get("m_Name", ""))[:128]
    switched, moving, unresolved, notes, driven = _animators(objects, walked, deadline)
    nodes, systems, unsupported, remap = [], [], [], {}
    live, reasons, translated = [], [], []
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
        # Nodes on the chain whose position the Animator moves over time.
        translated.append((translated[parent] if parent is not None else []) +
                          ([own] if "translation" in moving.get(own, ()) else []))
    played_nodes, played_systems = set(), []
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
                       else driven["unsupported"].get(own)
                       or (f"animated by the prefab Animator ({', '.join(animated_parts)})" if animated_parts else None))
            renderer = components.get("ParticleSystemRenderer")
            if renderer is None:
                raise _Unsupported("ParticleSystem has no renderer")
            if len(systems) >= _MAX_SYSTEMS_PER_TEMPLATE:
                raise _Unsupported("too many systems in one prefab")
            source = components["ParticleSystem"].read_typetree()
            scaling = source.get("scalingMode")
            scaled = False
            if not blocked and scaling in _SCALING and not _unit_scale(walked, own, scaling):
                scaled = scaling == 1 and _scaled_billboard(source, renderer.read_typetree(), node["scale"])
                if not scaled:
                    blocked = f"non-unit transform scale ({_SCALING[scaling]} scaling mode)"
            if not blocked and translated[own] and source.get("moveWithTransform") != 0:
                # World-space particles keep the emitter position of their birth step.
                blocked = "world-space particles under an Animator that moves the emitter"
            row = system(objects, node["game"], components["ParticleSystem"], renderer, textures, blocked,
                         upright=_turns_about_y(walked, own), scaled=scaled)
            if row is not None:
                index = remap[own]
                row.update(node=index, path=node["path"], layer=nodes[index]["layer"])
                played_nodes.update(translated[own])
                if own in driven["renderers"]:
                    played_systems.append((len(systems), own))
                systems.append(row)
        except (_Unsupported, *title._UNSUPPORTED) as error:
            unsupported.append({"path": node["path"], "reason": str(error)[:160] or type(error).__name__})
    result = {"name": name, "nodes": nodes, "systems": systems}
    channels = [{"node": remap[own], **row} for own in sorted(played_nodes) for row in driven["nodes"][own]]
    channels += [{"system": index, **row} for index, own in played_systems for row in driven["renderers"][own]]
    if channels:
        used = sorted({row["clip"] for row in channels})
        result["animation"] = {"clips": [driven["clips"][index] for index in used],
                               "channels": [{**row, "clip": used.index(row["clip"])} for row in channels]}
    return result, unsupported, sorted(notes)


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


def _missing(objects, owner, tree, event):
    """Why a CustomControl clip resolves to no prefab in this bundle."""
    if event["values"].get("playableClass") != "CustomControlClip":
        return "the clip is not a CustomControlClip"
    clip = tree["m_Clips"][int(event["id"].rsplit(":", 1)[1])]
    asset = title._local(objects, owner, clip.get("m_Asset"), "MonoBehaviour")
    if asset is None:
        return "the clip asset is missing"
    pointer = asset.read_typetree().get("prefabGameObject") or {}
    file_id, path_id = pointer.get("m_FileID"), pointer.get("m_PathID")
    if not path_id:
        return NO_PREFAB
    externals = asset.assets_file.externals
    if type(file_id) is int and 0 < file_id <= len(externals):
        name = externals[file_id - 1].path.replace("\\", "/").rsplit("/", 1)[-1]
        return f"the prefab is in another asset bundle ({name[:64]}) that the timeline import does not load"
    return "the prefab GameObject is missing from the bundle"


# Why the client plays no clip of a CustomControlTrack (mv_studio_control_prefabs reports these).
MUTED, NO_CATEGORY, BOUND, DISABLED = (
    "muted in the timeline", "outside the StageEffect Control, Display and OverlayEffect groups (no quality category)",
    "bound to a scene object", "the track is disabled")
NO_PREFAB = "the clip names no prefab (the game instantiates nothing)"


def control_clips(objects, mono, tracks):
    """Every CustomControlClip of the timeline, as the client starts it.

    Yields dicts with ``track``, ``event``, ``quality`` and either ``prefab``,
    ``offset`` and ``seed`` or a ``reason`` the clip instantiates nothing here.
    The particle reader and the prefab instancer share this one extraction.
    """
    controls = {timeline._id(key): (owner, fields) for key, (owner, fields, kind) in mono.items()
                if kind == "CustomControlTrack"}
    for track in tracks:
        if track.get("nativeClass") != "CustomControlTrack":
            continue
        source = controls.get(track["id"])
        quality = motion._quality(track["label"])
        reason = None
        if source is None or not title._declared(objects, source[0], source[1],
                                                 (*title._NAMESPACE, "CustomControlTrack")):
            reason = "the track is not the original CustomControlTrack"
        elif quality not in _CATEGORIES:
            reason = NO_CATEGORY
        elif track.get("binding") or track.get("bindings"):
            reason = BOUND
        elif not source[1].get("m_Enabled", True):
            reason = DISABLED
        elif _muted(objects, *source):
            reason = MUTED
        for event in track["events"]:
            row = {"track": track, "event": event, "quality": quality}
            if reason is not None:
                yield {**row, "reason": reason}
                continue
            try:
                found = _clip(objects, *source, event)
                missing = None if found is not None else _missing(objects, *source, event)
            except (_Unsupported, *title._UNSUPPORTED) as error:
                found, missing = None, f"the clip asset is unreadable ({str(error)[:80]})"
            if found is None:
                yield {**row, "reason": missing}
            else:
                prefab, offset, seed = found
                yield {**row, "prefab": prefab, "offset": offset, "seed": seed}


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


def read(objects, mono, tracks, deadline, *, claimed=frozenset(), outcomes=None, textures=None):
    """Return the particle templates and cues of every CustomControlTrack, or None.

    ``outcomes``, when given, receives per prefab (viewer._key) what this reader
    did with it: the walked hierarchy, the drawn systems' layers, the rejected
    systems or the reason no template exists. mv_studio_control_prefabs reuses it.
    ``textures``, when given, is the _Textures table shared with that reader, so
    a texture both use is exported once; the descriptor lists the levels this
    reader added (indices 0..n-1 of the shared table).
    """
    textures = _Textures(deadline) if textures is None else textures
    templates, cues, unsupported, notes = [], [], [], {}
    prefab_ids = {}
    outcomes = {} if outcomes is None else outcomes
    for row in control_clips(objects, mono, tracks):
        track, event = row["track"], row["event"]
        if "reason" in row or (track["id"], event["id"]) in claimed:
            continue
        prefab, offset, seed, quality = row["prefab"], row["offset"], row["seed"], row["quality"]
        key = viewer._key(prefab)
        if key not in prefab_ids:
            prefab_ids[key] = None
            outcome = outcomes.setdefault(key, {"systems": [], "rejected": [], "error": None})
            if time.monotonic() > deadline - _RESERVE_SECONDS or len(templates) >= _MAX_TEMPLATES:
                outcome["error"] = "import time budget"
                unsupported.append({"template": event["label"][:128], "path": "", "reason": "import time budget"})
                continue
            try:
                outcome["walked"] = _walk(objects, prefab, deadline)
                found, rejected, kinds = template(objects, prefab, textures, deadline, walked=outcome["walked"])
            except (_Unsupported, *title._UNSUPPORTED) as error:
                outcome["error"] = str(error)[:160]
                unsupported.append({"template": event["label"][:128], "path": "", "reason": str(error)[:160]})
                continue
            outcome.update(name=found["name"], rejected=rejected)
            for item in rejected:
                unsupported.append({"template": found["name"], **item})
            if kinds:
                notes[found["name"]] = kinds
            if found["systems"] and sum(len(item["systems"]) for item in templates) + len(found["systems"]) <= _MAX_SYSTEMS:
                prefab_ids[key] = len(templates)
                templates.append(found)
                outcome["systems"] = [system["layer"] for system in found["systems"]]
            elif found["systems"]:
                outcome["error"] = "particle system budget of the preview"
        index = prefab_ids[key]
        if index is None:
            continue
        if len(cues) >= _MAX_CUES:
            outcomes[key].setdefault("dropped", set()).add((track["id"], event["id"]))
            continue
        cues.append({"trackId": track["id"], "eventId": event["id"], "template": index,
                     "offset": offset, "quality": quality, "clipSeed": seed & 0xFFFFFFFF})
    if not cues and not unsupported:
        return None
    return {"schema": SCHEMA, "textures": list(textures.levels), "templates": templates, "cues": cues,
            "unsupported": unsupported, "otherComponents": notes}


def warning(descriptor, *, meshes_elsewhere=False):
    """One project warning that lists what the original prefabs use and the preview leaves out.

    ``meshes_elsewhere``: mv_studio_control_prefabs draws (or reports) the prefabs'
    mesh renderers and Animators, so they are not listed here.
    """
    rows = (descriptor or {}).get("unsupported") or []
    others = {} if meshes_elsewhere else (descriptor or {}).get("otherComponents") or {}
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
