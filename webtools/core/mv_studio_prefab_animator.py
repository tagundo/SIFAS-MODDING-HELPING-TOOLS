"""The default state of an Animator inside a CustomControl prefab clone (shared reader).

``PrefabControlPlayable`` activates the clone at the clip start. An enabled
Animator in it then plays its controller's default state on the player clock
from that activation: nothing in ``CustomControlClip.CreatePlayable`` (client
0x26e7cb0, which builds only a PrefabControlPlayable and a
CustomControlPlayable) drives its time, so the clip's ``clipIn`` and the
director's local time do not reach it. Its state time is the time since
activation, wrapped by the clip's ``m_LoopTime`` or held at the end.

Only what the serialized controller states is read: one layer, one state, no
transitions or blend tree, state speed 1 without a speed parameter, no cycle
offset or mirror, AlwaysAnimate culling and Normal update mode. Anything else
is reported by the callers instead of being guessed.

Bindings are resolved here against the walked prefab nodes (CRC32 of the path
below the Animator's GameObject, as Unity binds them) and returned as typed
channels with the packed curves the stage-motion reader also ships
(``["constant", v]``, ``["linear", [[t, v], ...]]``, ``["cubic", [[t, [a, b, c, d]], ...]]``).
Both the particle importer (mv_studio_particle_systems) and the prefab
instancer (mv_studio_control_prefabs) use this one reader.
"""

import math
import zlib

from . import model_animation as animation
from . import mv_studio_stage_title as title


GAME_OBJECT, TRANSFORM = 1, 4
ACTIVE = zlib.crc32(b"m_IsActive")
ENABLED = zlib.crc32(b"m_Enabled")
POSITION, ROTATION, SCALE, EULER = 1, 2, 3, 4
TRANSFORM_KINDS = {POSITION: "translation", ROTATION: "rotation", SCALE: "scale", EULER: "euler"}
RENDERERS = {23: "MeshRenderer", 137: "SkinnedMeshRenderer", 199: "ParticleSystemRenderer"}
# Material properties an animated renderer passes to AS/General/Transparent
# through its MaterialPropertyBlock: lanes x/r .. w/a in the top nibble.
MATERIAL_PROPERTIES = {zlib.crc32(b"_TintColor") & 0x0FFFFFFF: "tint",
                       zlib.crc32(b"_MainTex_ST") & 0x0FFFFFFF: "uv"}
_MATERIAL_CUSTOM_TYPE = 22


class Unsupported(Exception):
    """A controller or clip feature this reader does not reproduce."""


def flat(curve):
    """The value of a packed clip curve that never changes, else None."""
    mode, keys = curve
    if mode == "constant":
        return keys
    if not keys:
        return None
    if mode == "cubic":
        values = {coefficients[3] for _, coefficients in keys}
        constant = all(coefficients[0] == coefficients[1] == coefficients[2] == 0 for _, coefficients in keys)
        return values.pop() if constant and len(values) == 1 else None
    values = {value for _, value in keys}
    return values.pop() if len(values) == 1 else None


def _state(machine):
    states = machine["m_StateConstantArray"]
    if len(states) != 1 or machine["m_DefaultState"] != 0 or machine["m_AnyStateTransitionConstantArray"]:
        raise Unsupported("Animator controller with several states")
    state = states[0]["data"]
    if state.get("m_SpeedParamID") or state.get("m_TimeParamID") or state.get("m_CycleOffsetParamID") \
            or state.get("m_MirrorParamID"):
        raise Unsupported("Animator state driven by a parameter")
    if state.get("m_Speed", 1) != 1 or state.get("m_CycleOffset", 0) or state.get("m_Mirror"):
        raise Unsupported("Animator state with a speed, cycle offset or mirror")
    return state


def default_clip(objects, animator, fields):
    """The clip of a single-state controller's default state, None without a controller.

    Anything else (several layers or states, transitions, blend trees, culling
    other than AlwaysAnimate, object-reference curves) raises Unsupported.
    """
    controller = title._local(objects, animator, fields.get("m_Controller"))
    if controller is None:
        return None
    if controller.type.name != "AnimatorController":
        raise Unsupported(f"Animator {controller.type.name}")
    if fields.get("m_CullingMode", 0) != 0:
        raise Unsupported(f"Animator culling mode {fields.get('m_CullingMode')}")
    if fields.get("m_UpdateMode", 0) != 0:
        raise Unsupported(f"Animator update mode {fields.get('m_UpdateMode')}")
    tree = controller.read_typetree()
    graph = tree["m_Controller"]
    layers, machines = graph["m_LayerArray"], graph["m_StateMachineArray"]
    if len(layers) != 1 or len(machines) != 1 or layers[0]["data"]["m_StateMachineIndex"] != 0:
        raise Unsupported("Animator controller with several layers")
    state = _state(machines[0]["data"])
    trees = state["m_BlendTreeConstantArray"]
    if state["m_TransitionConstantArray"] or len(trees) != 1:
        raise Unsupported("Animator state with transitions or blend trees")
    leaves = trees[0]["data"]["m_NodeArray"]
    if len(leaves) != 1 or leaves[0]["data"].get("m_ChildIndices"):
        raise Unsupported("Animator state with a blend tree")
    clips = tree.get("m_AnimationClips") or []
    index = leaves[0]["data"].get("m_ClipID")
    if type(index) is not int or not 0 <= index < len(clips):
        raise Unsupported("Animator state without a clip")
    clip = title._local(objects, controller, clips[index], "AnimationClip")
    if clip is None:
        raise Unsupported("Animator clip is unavailable")
    tree = clip.read_typetree()
    if fields.get("m_ApplyRootMotion") and tree.get("m_HasGenericRootTransform"):
        # Without root motion the root's own curves are written like any other node's.
        raise Unsupported("Animator applies root motion")
    return tree


def bindings(clip, deadline):
    """(binding, per-lane constant or None, packed curves) for every generic binding of a packed clip."""
    rows = (clip.get("m_ClipBindingConstant") or {}).get("genericBindings") or []
    if any(binding.get("isPPtrCurve") for binding in rows):
        raise Unsupported("Animator clip with object reference curves")
    if not rows:
        if any(clip.get(field) for field in ("m_PositionCurves", "m_RotationCurves", "m_ScaleCurves",
                                             "m_EulerCurves", "m_FloatCurves")):
            raise Unsupported("Animator clip with editor curves")
        return []
    try:
        curves = animation._packed_curves(clip, deadline)
    except animation.AnimationError as error:
        raise Unsupported(f"Animator clip ({error})") from None
    result, offset = [], 0
    for binding in rows:
        width = animation._width(binding)
        selected = curves[offset:offset + width]
        offset += width
        if len(selected) != width:
            raise Unsupported("Animator clip curves do not match their bindings")
        result.append((binding, [flat(curve) for curve in selected], selected))
    if offset != len(curves):
        raise Unsupported("Animator clip curves do not match their bindings")
    return result


def timing(clip):
    """Start, duration and loop flag of the state's clip (Unity's muscle clip range)."""
    for field in ("m_Legacy", "m_Compressed", "m_HasMotionFloatCurves"):
        if clip.get(field):
            raise Unsupported(f"Animator clip {field.removeprefix('m_')}")
    muscle = clip.get("m_MuscleClip") or {}
    if muscle.get("m_CycleOffset") or muscle.get("m_Mirror"):
        raise Unsupported("Animator clip with a cycle offset or mirror")
    start, stop = muscle.get("m_StartTime", 0), muscle.get("m_StopTime", 0)
    if not all(type(value) in (int, float) and math.isfinite(value) for value in (start, stop)) \
            or not 0 <= stop - start <= animation.MAX_SECONDS:
        raise Unsupported("Animator clip range")
    return {"name": str(clip.get("m_Name", ""))[:128], "start": float(start), "duration": float(stop - start),
            "loop": bool(muscle.get("m_LoopTime"))}


def targets(walked, own):
    """Binding path hash -> walked index for the nodes below the Animator's GameObject."""
    prefix, found = walked[own]["parts"], {}
    for index, other in enumerate(walked):
        if other["parts"][:len(prefix)] == prefix:
            found.setdefault(zlib.crc32("/".join(other["parts"][len(prefix):]).encode("utf-8")), index)
    return found


def material_lane(binding):
    """(property kind, lane) of a renderer material property binding, or None."""
    attribute = binding.get("attribute")
    if (binding.get("customType") != _MATERIAL_CUSTOM_TYPE or type(attribute) is not int
            or binding.get("script") not in (None, {"m_FileID": 0, "m_PathID": 0})):
        return None
    kind = MATERIAL_PROPERTIES.get(attribute & 0x0FFFFFFF)
    family, lane = divmod(attribute >> 28, 4)
    # Lanes .x/.y/.z/.w are 0-3; a color's .r/.g/.b/.a are 4-7 (as mv_studio_stage_overlay reads them).
    return (kind, lane) if kind is not None and (family == 0 or family == 1 and kind == "tint") else None


def channels(walked, own, rows):
    """Typed channels of one Animator, resolved to walked node indices.

    Returns (channels, unsupported): ``channels`` holds Transform, GameObject
    activation, renderer enable and renderer _TintColor/_MainTex_ST rows;
    ``unsupported`` maps a walked index to the reason a binding on it is not
    reproduced (bindings whose path is not in the prefab bind nothing, as in Unity).
    """
    found, result, unsupported, material = targets(walked, own), [], {}, {}
    seen = set()
    for binding, _, curves in rows:
        target = found.get(binding.get("path"))
        if target is None:
            continue
        kind, attribute = binding.get("typeID", binding.get("classID")), binding.get("attribute")
        if kind == GAME_OBJECT and attribute == ACTIVE:
            row = {"node": target, "kind": "active", "curves": curves}
        elif kind == TRANSFORM and attribute in TRANSFORM_KINDS:
            row = {"node": target, "kind": TRANSFORM_KINDS[attribute], "curves": curves}
            if attribute == EULER:
                row["rotationOrder"] = animation.euler_order(binding.get("customType", animation.DEFAULT_EULER_ORDER))
        elif kind in RENDERERS and attribute == ENABLED and binding.get("customType", 0) == 0:
            row = {"node": target, "kind": "enabled", "renderer": RENDERERS[kind], "curves": curves}
        elif kind in RENDERERS and material_lane(binding) is not None:
            prop, lane = material_lane(binding)
            lanes = material.setdefault((target, RENDERERS[kind], prop), {})
            if lane in lanes:
                # Both the .xyzw and the .rgba lanes of one color: the order Unity
                # writes them in (and whether both bind) is not established.
                unsupported[target] = (f"Animator animates {'_TintColor' if prop == 'tint' else '_MainTex_ST'} "
                                       "through both its vector and color lanes")
            lanes[lane] = curves[0]
            continue
        else:
            unsupported.setdefault(target, f"Animator curve on {RENDERERS.get(kind, f'class {kind}')} "
                                           f"attribute {attribute:#x}" if type(attribute) is int else
                                   f"Animator curve on class {kind}")
            continue
        key = (row["node"], "rotation" if row["kind"] == "euler" else row["kind"], row.get("renderer"))
        if key in seen:
            unsupported[target] = "Animator binds one channel twice"
            continue
        seen.add(key)
        result.append(row)
    for (target, renderer, prop), lanes in material.items():
        if set(lanes) != {0, 1, 2, 3}:
            # A partial vector keeps the authored value in the other lanes; not reproduced.
            unsupported[target] = f"Animator animates part of {'_TintColor' if prop == 'tint' else '_MainTex_ST'}"
            continue
        result.append({"node": target, "kind": prop, "renderer": renderer, "curves": [lanes[i] for i in range(4)]})
    return result, unsupported


def constant(row):
    """Per-lane constants of a channel, or None when any lane changes over time."""
    values = [flat(curve) for curve in row["curves"]]
    return None if any(value is None for value in values) else values


def euler(values):
    # Unity's Quaternion.Euler applies Z, then X, then Y (Unity space, degrees).
    x, y, z = (math.radians(value) * .5 for value in values)
    return list(animation._multiply(animation._multiply((0, math.sin(y), 0, math.cos(y)), (math.sin(x), 0, 0, math.cos(x))),
                                    (0, 0, math.sin(z), math.cos(z))))


def json_curve(curve):
    """A packed curve as JSON: finite numbers only, keys in time order."""
    mode, keys = curve
    if mode == "constant":
        if not math.isfinite(keys):
            raise Unsupported("non-finite Animator curve")
        return ["constant", float(keys)]
    rows = []
    for stamp, value in keys:
        values = value if mode == "cubic" else (value,)
        if not all(math.isfinite(item) for item in values) or not (math.isfinite(stamp) or stamp < 0):
            raise Unsupported("non-finite Animator curve")
        # Unity's negative-infinity sentinel seeds the first streamed key.
        rows.append([max(stamp, -1e30), [float(item) for item in value] if mode == "cubic" else float(value)])
    return [mode, rows]
