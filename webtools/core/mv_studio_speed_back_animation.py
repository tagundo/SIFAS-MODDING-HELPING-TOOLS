"""Read the local Animator's authored background texture transform."""

from . import model_animation as animation, mv_studio_stage_title as title


_PATH = animation.path_hash("speed_back")
_PROPERTY_MASK = 0x0FFFFFFF
_TEXTURE_ST = animation.path_hash("_MainTex_ST") & _PROPERTY_MASK


def _clip(objects, animator, fields):
    if (not fields["m_Enabled"] or not fields["m_HasTransformHierarchy"] or fields["m_Avatar"]["m_PathID"]
            or any(fields[key] for key in ("m_UpdateMode", "m_CullingMode", "m_ApplyRootMotion",
                                           "m_KeepAnimatorControllerStateOnDisable"))):
        return None
    controller = title._local(objects, animator, fields["m_Controller"], "AnimatorController")
    if controller is None:
        return None
    tree = controller.read_typetree()
    graph = tree["m_Controller"]
    layer, = graph["m_LayerArray"]
    machine, = graph["m_StateMachineArray"]
    machine = machine["data"]
    state, = machine["m_StateConstantArray"]
    state = state["data"]
    blend, = state["m_BlendTreeConstantArray"]
    node, = blend["data"]["m_NodeArray"]
    node = node["data"]
    if (tree["m_StateMachineBehaviours"] or graph["m_Values"]["data"]["m_ValueArray"]
            or any(layer["data"][key] for key in ("m_IKPass", "m_StateMachineIndex", "m_SyncedLayerAffectsTiming"))
            or machine["m_DefaultState"] != 0 or machine["m_AnyStateTransitionConstantArray"]
            or state["m_Speed"] != 1 or state["m_Loop"] or state["m_BlendTreeConstantIndexArray"] != [0]
            or any(state[key] for key in ("m_TransitionConstantArray", "m_SpeedParamID", "m_MirrorParamID",
                                         "m_CycleOffsetParamID", "m_TimeParamID", "m_Mirror",
                                         "m_CycleOffset", "m_IKOnFeet"))
            or any(node[key] for key in ("m_ClipID", "m_BlendType", "m_ChildIndices", "m_CycleOffset", "m_Mirror"))):
        return None
    ref, = tree["m_AnimationClips"]
    return title._local(objects, controller, ref, "AnimationClip")


def read(objects, animator, fields, deadline):
    """Return the four original texture ST curves from a supported local clip."""
    try:
        clip = _clip(objects, animator, fields)
        if clip is None:
            return None
        tree = clip.read_typetree()
        if any(tree.get(key) for key in ("m_Legacy", "m_Compressed", "m_HasGenericRootTransform",
                                         "m_HasMotionFloatCurves", "m_Events", "m_PPtrCurves",
                                         "m_CompressedRotationCurves")):
            return None
        muscle = tree["m_MuscleClip"]
        duration = muscle["m_StopTime"]
        if duration != 50 or any(muscle[key] for key in ("m_StartTime", "m_LoopTime", "m_CycleOffset", "m_Mirror")):
            return None
        bindings = tree["m_ClipBindingConstant"]["genericBindings"]
        packed = muscle["m_Clip"]["data"]
        streamed = packed["m_StreamedClip"]
        if (len(bindings) != 4 or streamed["curveCount"] != 3 or len(streamed["data"]) > 128
                or packed["m_DenseClip"]["m_CurveCount"] or len(packed["m_ConstantClip"]["data"]) != 1):
            return None
        # Native stores the streamed channels before constants, regardless of
        # their order in the texture transform. Read the high-nibble component.
        components = {}
        for binding, curve in zip(bindings, animation._packed_curves(tree, deadline), strict=True):
            attribute = binding["attribute"]
            component = attribute >> 28
            mode, keys = curve
            if (binding["path"] != _PATH or (binding["typeID"], binding["customType"]) != (199, 22)
                    or binding["isPPtrCurve"] or any(binding["script"].values())
                    or attribute & _PROPERTY_MASK != _TEXTURE_ST or not 0 <= component < 4
                    or component in components or (mode == "cubic" and not 1 <= len(keys) <= 16)):
                return None
            components[component] = curve
        return {"duration": duration, "uvCurves": [components[axis] for axis in range(4)]}
    except title._UNSUPPORTED:
        return None
