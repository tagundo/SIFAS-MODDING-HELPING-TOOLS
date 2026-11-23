"""Native AxisBillboard light-beam cones (LLAS.Components.AxisBillboard).

LiveCoreStageEffect.Initialize (0x2f6f4c4) refills its ``axisBillboards``
with GetComponentsInChildren<AxisBillboard>(true) and calls
AxisBillboard.Initialize for each, which enables the component with the
camera targets. OnWillRenderObject then turns the transform about its own up
axis toward the drawing camera (RunAxisBillboardY). Components outside a
stage effect never receive targets and stay as authored.
"""

from . import model_viewer as viewer
from .mv_studio_shaft import _STAGE_EFFECT
from .mv_studio_stage_coloring import _path

_AXIS_BILLBOARD = ("Assembly-CSharp.dll", "LLAS.Components.AxisBillboard", "AxisBillboard")


def _script(scene, component, tree):
    script = viewer._ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return None
    definition = scene.tree(script)
    return tuple(definition.get(field) for field in ("m_AssemblyName", "m_Namespace", "m_ClassName"))


def owners(scene, component, tree):
    """Return the GameObject keys of the AxisBillboards a LiveCoreStageEffect initializes:
    every AxisBillboard on its GameObject or below it, active or not."""
    if _script(scene, component, tree) != _STAGE_EFFECT:
        return set()
    game = viewer._ref(component, tree.get("m_GameObject"))
    root = _path(scene, game) if game is not None and game.type.name == "GameObject" else ()
    if not root:
        return set()
    keys = set()
    for billboard in scene.env.objects:
        if billboard.type.name != "MonoBehaviour" or billboard.assets_file is not component.assets_file:
            continue
        try:
            billboard_tree = scene.tree(billboard)
        except Exception:
            continue
        if _script(scene, billboard, billboard_tree) != _AXIS_BILLBOARD:
            continue
        owner = viewer._ref(billboard, billboard_tree.get("m_GameObject"))
        if owner is not None and owner.type.name == "GameObject" and _path(scene, owner)[:len(root)] == root:
            keys.add(viewer._key(owner))
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
