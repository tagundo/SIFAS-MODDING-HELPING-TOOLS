"""LLAS.Scene.Live.Components.LiveCoreLossyScale on stage effect objects.

LateUpdate (GL 3.12.0, 0x2f63fa0) sets
``transform.localScale = transform.localScale / transform.lossyScale + offsetScale``
component-wise, after the animators ran. With lossyScale = localScale * P (P the
parent's lossy scale) the object's local scale becomes 1 / P + offsetScale every
frame, whatever it was authored or animated to. Six GL stage effects carry it
(9 objects each, e.g. the MultiIris / Hoop / Shimmer overlay sprites under an
animated ``joint_root``).
"""

import math

from . import model_viewer as viewer

_LOSSY_SCALE = ("Assembly-CSharp.dll", "LLAS.Scene.Live.Components", "LiveCoreLossyScale")


def offsets(scene, component, tree):
    """Return {GameObject key: (x, y, z)} for an enabled LiveCoreLossyScale, else {}."""
    script = viewer._ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript" or tree.get("m_Enabled") != 1:
        return {}
    definition = scene.tree(script)
    if tuple(definition.get(field) for field in ("m_AssemblyName", "m_Namespace", "m_ClassName")) != _LOSSY_SCALE:
        return {}
    offset = tree.get("offsetScale")
    values = [offset.get(axis) if isinstance(offset, dict) else None for axis in "xyz"]
    if any(type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1000 for value in values):
        return {}
    owner = viewer._ref(component, tree.get("m_GameObject"))
    if owner is None or owner.type.name != "GameObject":
        return {}
    return {viewer._key(owner): tuple(float(value) for value in values)}


def tag(glb, stage_nodes, entries):
    """Mark each retained node with its offsetScale; return how many were marked."""
    marked = 0
    for key, values in entries.items():
        index = stage_nodes.nodes.get(key) if stage_nodes is not None else None
        if index is None or values is None:
            continue
        glb.doc["nodes"][index].setdefault("extras", {})["mvLossyScaleOffset"] = list(values)
        marked += 1
    return marked
