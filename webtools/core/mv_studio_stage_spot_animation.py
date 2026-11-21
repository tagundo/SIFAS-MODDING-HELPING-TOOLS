"""Read the bounded default Animator state of Aion's stage spotlight."""

import math
import struct

from . import model_animation as animation
from .mv_studio_stage_title import _local


_TRANSFORMS = {
    "": (1,),
    "ctrl": (1, 4),
    "ctrl/mdl": (1, 4),
    "ctrl/mdl/L": (1, 3, 4),
    "ctrl_area": (1, 4),
}
_RENDERERS = {"ctrl/mdl/Glow_03": 137, "ctrl_area/glow02": 23}
_TINT_HASH = animation.path_hash("_TintColor") & 0x0fffffff


def _clip(objects, animator, fields):
    if (not fields["m_Enabled"] or not fields["m_HasTransformHierarchy"] or
            fields["m_Avatar"]["m_PathID"] or any(fields.get(key) for key in (
                "m_CullingMode", "m_UpdateMode", "m_ApplyRootMotion", "m_LinearVelocityBlending",
                "m_KeepAnimatorControllerStateOnDisable"))):
        return None
    controller = _local(objects, animator, fields["m_Controller"], "AnimatorController")
    if controller is None or not 0 < controller.byte_size <= 4 * 1024:
        return None
    tree = controller.read_typetree()
    data = tree["m_Controller"]
    layer, = data["m_LayerArray"]
    machine, = data["m_StateMachineArray"]
    machine = machine["data"]
    state, = machine["m_StateConstantArray"]
    state = state["data"]
    blend, = state["m_BlendTreeConstantArray"]
    node, = blend["data"]["m_NodeArray"]
    node = node["data"]
    if (tree["m_Name"] != "ac_par_so2028_12" or tree.get("m_StateMachineBehaviours") or
            data["m_Values"]["data"]["m_ValueArray"] or layer["data"]["m_IKPass"] or
            layer["data"]["m_StateMachineIndex"] != 0 or layer["data"]["m_SkeletonMask"]["data"]["m_Data"] or
            machine["m_DefaultState"] != 0 or machine["m_AnyStateTransitionConstantArray"] or
            state["m_BlendTreeConstantIndexArray"] != [0] or state["m_Speed"] != 1 or
            any(state[key] for key in ("m_TransitionConstantArray", "m_SpeedParamID", "m_MirrorParamID",
                "m_CycleOffsetParamID", "m_TimeParamID", "m_Loop", "m_Mirror", "m_CycleOffset", "m_IKOnFeet")) or
            any(node[key] for key in ("m_ClipID", "m_BlendType", "m_ChildIndices", "m_CycleOffset", "m_Mirror"))):
        return None
    ref, = tree["m_AnimationClips"]
    return _local(objects, controller, ref, "AnimationClip")


def _tint_curve(curve, component, duration):
    mode, keys = curve
    if component < 3:
        return mode == "constant" and 0 <= keys <= 1
    return (mode == "cubic" and len(keys) == 4 and keys[0][0] < -1e20 and
            keys[1][0] == 0 < keys[2][0] < keys[3][0] == duration and
            all(0 <= val[3] <= 1 and all(abs(coefficient) <= 32 for coefficient in val[:3])
                for _, val in keys) and keys[3][1][:3] == (0, 0, 0))


def _read_clip(tree, deadline):
    if (tree["m_Name"] != "clip_par_so2028_12" or not tree["m_HasGenericRootTransform"] or
            any(tree[key] for key in ("m_Legacy", "m_Compressed", "m_HasMotionFloatCurves", "m_Events",
                "m_PPtrCurves", "m_CompressedRotationCurves", "m_FloatCurves", "m_WrapMode"))):
        return None
    muscle = tree["m_MuscleClip"]
    duration = muscle["m_StopTime"]
    if (muscle["m_StartTime"] != 0 or not math.isfinite(duration) or not 0 < duration <= 3 or
            not muscle["m_StartAtOrigin"] or any(muscle[key] for key in ("m_Mirror", "m_LoopTime", "m_LoopBlend",
                "m_LoopBlendOrientation", "m_LoopBlendPositionY", "m_LoopBlendPositionXZ", "m_CycleOffset"))):
        return None
    packed = muscle["m_Clip"]["data"]
    streamed, dense, constants = packed["m_StreamedClip"], packed["m_DenseClip"], packed["m_ConstantClip"]
    if (streamed["curveCount"] != 2 or len(streamed["data"]) > 128 or dense["m_CurveCount"] != 0 or
            dense["m_SampleArray"] or len(constants["data"]) != 36):
        return None
    transforms = {(animation.path_hash(path), 4, attribute, 4 if attribute == 4 else 0): (path, attribute)
                  for path, attributes in _TRANSFORMS.items() for attribute in attributes}
    tints = {(animation.path_hash(path), renderer, _TINT_HASH | ((index + 4) << 28), 22): (path, index)
             for path, renderer in _RENDERERS.items() for index in range(4)}
    bindings = tree["m_ClipBindingConstant"]["genericBindings"]
    if len(bindings) != len(transforms) + len(tints):
        return None
    curves = animation._packed_curves(tree, deadline)
    poses, colors, cursor = {}, {path: [None] * 4 for path in _RENDERERS}, 0
    for row in bindings:
        if row["isPPtrCurve"] or row["script"] != {"m_FileID": 0, "m_PathID": 0}:
            return None
        binding = (row["path"], row["typeID"], row["attribute"], row["customType"])
        tint = tints.pop(binding, None)
        if tint is not None:
            path, component = tint
            curve = curves[cursor]
            if not _tint_curve(curve, component, duration):
                return None
            colors[path][component] = curve
            cursor += 1
            continue
        transform = transforms.pop(binding, None)
        if transform is None:
            return None
        path, attribute = transform
        section = curves[cursor:cursor + 3]
        if (len(section) != 3 or any(mode != "constant" or abs(value) > 360 for mode, value in section)):
            return None
        values = [value for _, value in section]
        cursor += 3
        if not path:
            # This generic-root flag describes a constant zero translation.
            # The Animator has ApplyRootMotion disabled. Preserve the cue root.
            if any(values):
                return None
            continue
        pose = poses.setdefault(path, {})
        if attribute == 1:
            pose["translation"] = [-values[0], values[1], values[2]]
        elif attribute == 4:
            pose["rotation"] = animation._quaternion(values, euler=True)
        elif all(0 < value <= 32 for value in values):
            pose["scale"] = values
        else:
            return None
    if transforms or tints or cursor != len(curves):
        return None
    return {"duration": duration, "poses": poses, "tints": colors}


def read(objects, animator, fields, deadline):
    """Return static reflected TRS and native RGBA curves bound to two renderers."""
    try:
        animation._check(deadline)
        clip = _clip(objects, animator, fields)
        return _read_clip(clip.read_typetree(), deadline) if clip is not None and 0 < clip.byte_size <= 8 * 1024 else None
    except (AttributeError, IndexError, KeyError, OverflowError, TypeError, ValueError, EOFError, OSError, struct.error):
        return None
