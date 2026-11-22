"""Retain native spotlight shaft templates as detached preview geometry."""

from . import model_viewer as viewer
from .model_rig import _authored_trs
from .mv_studio_stage_overlay import material as transparent_material


_STAGE_EFFECT = ("Assembly-CSharp.dll", "LLAS.Scene.Live.Components", "LiveCoreStageEffect")


def references(scene, component, tree):
    """Locate the native template slots and the objects excluded from static previews."""
    pointers = tree.get("spotLightShaftPrefabs")
    if not isinstance(pointers, list) or not pointers:
        return set(), None
    script = viewer._ref(component, tree.get("m_Script"))
    if script is None or script.type.name != "MonoScript":
        return set(), None
    script_tree = scene.tree(script)
    if tuple(script_tree.get(field) for field in ("m_AssemblyName", "m_Namespace", "m_ClassName")) != _STAGE_EFFECT:
        return set(), None
    owner = viewer._ref(component, tree.get("m_GameObject"))
    if owner is None or owner.type.name != "GameObject":
        return set(), None

    excluded, slots = set(), []
    for pointer in pointers:
        slots.append(None)
        if not isinstance(pointer, dict) or pointer.get("m_FileID") != 0:
            continue
        game = viewer._ref(component, pointer)
        if game is None or game.type.name != "GameObject":
            continue
        transform = scene.transforms.get(viewer._key(game))
        if transform is None or (scene.tree(transform).get("m_Father") or {}).get("m_PathID"):
            continue
        pending, members = [(transform, None)], {}
        while pending:
            current, parent = pending.pop()
            values = scene.tree(current)
            child_game = viewer._ref(current, values.get("m_GameObject"))
            if child_game is None or child_game.type.name != "GameObject" or viewer._key(child_game) in members:
                continue
            key = viewer._key(child_game)
            members[key] = child_game, current, parent
            pending.extend((child, key) for ref in values.get("m_Children", []) if ref.get("m_FileID") == 0
                           if (child := viewer._ref(current, ref)) is not None and child.type.name == "Transform")
        if viewer._key(owner) not in members:
            excluded.update(members)
            slots[-1] = game, members
    return excluded, (component, slots) if tree.get("m_Enabled") and any(slots) else None


def _template(scene, glb, materials, component, slot, index, deadline):
    import numpy as np

    prefab, members = slot
    renderers = [row for row in scene.renderers if viewer._key(row[2]) in members]
    if len(renderers) != 1:
        return None
    renderer, renderer_tree, game = renderers[0]
    if renderer.type.name != "MeshRenderer":
        return None
    chain, key = [], viewer._key(game)
    while key is not None:
        node, transform, key = members[key]
        father = scene.tree(transform).get("m_Father", {})
        if key is not None and father != {"m_FileID": 0, "m_PathID": members[key][1].path_id}:
            return None
        chain.append((node, transform))
    chain.reverse()
    if not all(scene.tree(node).get("m_IsActive") for node, _ in chain):
        return None
    mesh = scene.filters.get(viewer._key(game))
    pointers = renderer_tree.get("m_Materials")
    if mesh is None or mesh.type.name != "Mesh" or not isinstance(pointers, list) or len(pointers) != 1:
        return None
    material = viewer._ref(renderer, pointers[0])
    if material is None or material.type.name != "Material":
        return None
    envs = viewer._properties(scene.tree(material), "m_TexEnvs")
    if envs.get("_MainTex", {}).get("m_Texture", {}).get("m_PathID"):
        return None  # This retained shader profile uses Unity's white texture.
    native = transparent_material(scene, materials, material)
    if native is None or native.get("depthTest") or not native["vertexColor"]:
        return None

    nodes = [{"pathId": str(node.path_id), "name": scene.name(node), **_authored_trs(scene.local_tree(transform))}
             for node, transform in chain]
    vertex = {}
    _, positions, normals, uv, submeshes = viewer._geometry(mesh, np.eye(4), deadline=deadline, stage_data=vertex)
    color = vertex.get("color")
    if color is None or np.min(color) < 0 or np.max(color) > 1 or not any(map(len, submeshes)):
        return None
    component_type = 5123 if len(positions) <= 65535 else 5125
    geometry = {
        "position": glb.attribute(positions, "VEC3", bounds=True),
        "normal": glb.attribute(normals, "VEC3"),
        "uv": glb.attribute(uv, "VEC2") if uv is not None else None,
        "color": glb.attribute(color, "VEC4"),
        "index": glb.attribute(np.concatenate(submeshes).reshape(-1), "SCALAR", component_type),
    }
    return {
        "index": index, "stageEffectPathId": str(component.path_id), "prefabPathId": str(prefab.path_id),
        "rendererPathId": str(renderer.path_id), "meshPathId": str(mesh.path_id),
        "materialPathId": str(material.path_id), "nodes": nodes, "geometry": geometry,
        "material": {"shader": "AS/General/Transparent", "tint": native["tint"], "queue": native["queue"]},
    }


def export(scene, glb, materials, source, deadline):
    component, slots = source
    templates = []
    for index, slot in enumerate(slots):
        viewer._remaining(deadline)
        try:
            template = _template(scene, glb, materials, component, slot, index, deadline) if slot is not None else None
        except (ValueError, TypeError, KeyError, IndexError, OverflowError):
            template = None
        templates.append(template)
    return templates if any(templates) else None
