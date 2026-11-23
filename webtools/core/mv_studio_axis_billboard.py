"""Native AxisBillboard light-beam cones (LLAS.Components.AxisBillboard).

LiveCoreStageEffect.Initialize calls AxisBillboard.Initialize for every entry
of its ``axisBillboards`` array, which enables the component with the camera
targets. OnWillRenderObject then turns the transform about its own up axis
toward the drawing camera (RunAxisBillboardY). Components not listed there
never receive targets and stay as authored.
"""

from . import model_viewer as viewer
from .mv_studio_shaft import _STAGE_EFFECT

_AXIS_BILLBOARD = ("Assembly-CSharp.dll", "LLAS.Components.AxisBillboard", "AxisBillboard")


def _script(scene, component, tree):
    script = viewer._ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return None
    definition = scene.tree(script)
    return tuple(definition.get(field) for field in ("m_AssemblyName", "m_Namespace", "m_ClassName"))


def owners(scene, component, tree):
    """Return the GameObject keys of the AxisBillboards a LiveCoreStageEffect initializes."""
    pointers = tree.get("axisBillboards")
    if not isinstance(pointers, list) or not pointers or _script(scene, component, tree) != _STAGE_EFFECT:
        return set()
    keys = set()
    for pointer in pointers:
        billboard = viewer._ref(component, pointer) if isinstance(pointer, dict) else None
        if billboard is None or billboard.type.name != "MonoBehaviour":
            continue
        billboard_tree = scene.tree(billboard)
        if _script(scene, billboard, billboard_tree) != _AXIS_BILLBOARD:
            continue
        game = viewer._ref(billboard, billboard_tree.get("m_GameObject"))
        if game is not None and game.type.name == "GameObject":
            keys.add(viewer._key(game))
    return keys


def tag(glb, stage_nodes, keys):
    """Mark each billboard's retained node; return how many were marked.

    The node keeps its authored TRS. Billboards whose renderer was flattened
    into static geometry have no node to turn and stay as authored.
    """
    marked = 0
    for key in keys:
        index = stage_nodes.nodes.get(key) if stage_nodes is not None else None
        if index is None:
            continue
        glb.doc["nodes"][index].setdefault("extras", {})["mvAxisBillboard"] = 1
        marked += 1
    return marked
