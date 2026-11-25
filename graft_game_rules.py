"""Two game rules a written part graft must keep, both confirmed in the game client.

1. A renderer outside ``BodyPartManager.headAll`` must not skin to bones at or
   below ``headAll``. The client combines the body renderers at runtime; a Body
   that gained ``Head_Hair`` (from a hat taken off a head mesh) made the whole
   member disappear, and binding the same vertices to ``Head`` showed it again.
   Weights on such bones that this graft added move to ``BodyPartManager.head``
   with a bind pose that keeps the rest-pose skin matrix, and the bones leave
   the renderer's bone list. Bones the costume already used are left alone.

2. A donor part that culls back faces (``_CullMode`` 1 or 2) grafted onto a
   receiving material that draws both sides (``_CullMode`` 0) keeps its culling:
   its triangles become their own submesh, drawn by a copy of the receiving
   material with the donor's ``_CullMode``. The copy is added wherever the
   receiving material is listed (``LiveCoreMemberRimlight``/``Ambient``
   ``materials``) so the client lights it the same way. Drawn from both sides,
   back-to-back donor faces z-fight and flicker in game.

Textures are not touched: the copy uses the receiving material's textures.
"""
import copy
import hashlib
import zlib

import numpy as np

_TOLERANCE = 1e-4


def _load(path):
    import UnityPy
    env = UnityPy.load(str(path))
    return env, {obj.path_id: obj for obj in env.objects}


def _save(env, path):
    env.file.mark_changed()
    with open(path, "wb") as stream:
        stream.write(env.file.save(packer="original"))


def _scripts(objs):
    return {pid: obj.read_typetree().get("m_ClassName") for pid, obj in objs.items() if obj.type.name == "MonoScript"}


def _behaviours(objs, scripts, class_name):
    for obj in objs.values():
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        if scripts.get(tree.get("m_Script", {}).get("m_PathID")) == class_name:
            yield obj, tree


def _transform_of(objs, game_object):
    tree = objs[game_object].read_typetree() if game_object in objs else {}
    for row in tree.get("m_Component", []):
        pid = row["component"]["m_PathID"]
        if pid in objs and objs[pid].type.name == "Transform":
            return pid
    return None


def _quaternion(q):
    x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def _rest_world(transforms, pid):
    matrix = np.eye(4)
    while pid:
        tree = transforms[pid]
        local = np.eye(4)
        scale = tree["m_LocalScale"]
        local[:3, :3] = _quaternion(tree["m_LocalRotation"]) @ np.diag([scale["x"], scale["y"], scale["z"]])
        local[:3, 3] = [tree["m_LocalPosition"][axis] for axis in "xyz"]
        matrix = local @ matrix
        pid = tree["m_Father"]["m_PathID"]
    return matrix


def _ancestors(transforms, pid):
    seen = []
    while pid and pid in transforms and len(seen) < 1000:
        seen.append(pid)
        pid = transforms[pid]["m_Father"]["m_PathID"]
    return seen


def _bindpose(row):
    return np.array([[row[f"e{r}{c}"] for c in range(4)] for r in range(4)], float)


def _bindpose_row(matrix):
    return {f"e{r}{c}": float(matrix[r, c]) for r in range(4) for c in range(4)}


def _path(objs, transforms, pid):
    names = [objs[transforms[p]["m_GameObject"]["m_PathID"]].read_typetree()["m_Name"]
             for p in reversed(_ancestors(transforms, pid))]
    return "/".join(names)


def rebind_head_bones(path, renderer_id, original_bone_count, log=print):
    """Apply rule 1 to one written renderer. Returns the number of vertices moved."""
    import costume_part_transplant as cpt
    env, objs = _load(path)
    scripts = _scripts(objs)
    manager = next((tree for _, tree in _behaviours(objs, scripts, "BodyPartManager")), None)
    renderer = objs.get(int(renderer_id))
    if manager is None or renderer is None:
        return 0
    transforms = {pid: obj.read_typetree() for pid, obj in objs.items() if obj.type.name == "Transform"}
    head_all = _transform_of(objs, manager.get("headAll", {}).get("m_PathID"))
    head = _transform_of(objs, manager.get("head", {}).get("m_PathID"))
    renderer_tree = renderer.read_typetree()
    own = _transform_of(objs, renderer_tree["m_GameObject"]["m_PathID"])
    if head_all is None or head is None or head_all in _ancestors(transforms, own):
        return 0
    bones = [row["m_PathID"] for row in renderer_tree["m_Bones"]]
    face_side = [i for i in range(int(original_bone_count), len(bones)) if head_all in _ancestors(transforms, bones[i])]
    if not face_side:
        return 0
    mesh_id = renderer_tree["m_Mesh"]["m_PathID"]
    sharing = [obj for obj in objs.values() if obj.type.name == "SkinnedMeshRenderer" and obj.path_id != renderer.path_id
               and obj.read_typetree()["m_Mesh"]["m_PathID"] == mesh_id]
    if sharing:
        raise ValueError("The receiving mesh is shared by another renderer; its face-side bones cannot be rebound.")
    mesh = objs[mesh_id]
    tree = mesh.read_typetree()
    poses = [_bindpose(row) for row in tree["m_BindPose"]]
    hashes = list(tree.get("m_BoneNameHashes") or [])
    worlds = {pid: _rest_world(transforms, pid) for pid in set(bones) | {head}}
    target = {}
    for i in face_side:
        skin = worlds[bones[i]] @ poses[i]
        match = next((j for j, bone in enumerate(bones) if bone == head and j not in face_side
                      and np.allclose(worlds[head] @ poses[j], skin, atol=_TOLERANCE)), None)
        if match is None:
            bones.append(head)
            poses.append(np.linalg.inv(worlds[head]) @ skin)
            if hashes:
                hashes.append(zlib.crc32(_path(objs, transforms, head).encode("utf-8")) & 0xFFFFFFFF)
            match = len(bones) - 1
        target[i] = match
    keep = [j for j in range(len(bones)) if j not in target]
    order = {old: new for new, old in enumerate(keep)}
    remap = np.array([order[target.get(j, j)] for j in range(len(bones))], np.int64)

    count, channels, strides, starts, _ = cpt.stream_layout(tree)
    data = bytearray(tree["m_VertexData"]["m_DataSize"])
    u8 = np.frombuffer(data, np.uint8)
    weights = cpt.read_attr(u8, cpt.ATTR_BLENDWEIGHT, channels, strides, starts, count)
    indices = cpt.read_attr(u8, cpt.ATTR_BLENDINDICES, channels, strides, starts, count)
    if weights is None or indices is None:
        raise ValueError("The receiving mesh has no skin weights to rebind.")
    moved = int(((weights > 0) & np.isin(indices, list(target))).any(1).sum())
    indices = remap[np.clip(indices, 0, len(remap) - 1)]
    slots = indices.shape[1]
    for v in np.where([len(set(row[w > 0])) < (w > 0).sum() for row, w in zip(indices, weights)])[0]:
        totals = {}
        for bone, weight in zip(indices[v], weights[v]):
            if weight > 0:
                totals[int(bone)] = totals.get(int(bone), 0.) + float(weight)
        rows = sorted(totals.items(), key=lambda item: -item[1]) + [(0, 0.)] * slots
        indices[v], weights[v] = [b for b, _ in rows[:slots]], [w for _, w in rows[:slots]]
    indices[weights <= 0] = 0
    cpt.write_attr(u8, weights, cpt.ATTR_BLENDWEIGHT, channels, strides, starts, count)
    cpt.write_attr(u8, indices, cpt.ATTR_BLENDINDICES, channels, strides, starts, count)
    tree["m_VertexData"]["m_DataSize"] = bytes(data)
    tree["m_BindPose"] = [_bindpose_row(poses[j]) for j in keep]
    if hashes:
        tree["m_BoneNameHashes"] = [hashes[j] for j in keep]
    mesh.save_typetree(tree)
    renderer_tree["m_Bones"] = [{"m_FileID": 0, "m_PathID": bones[j]} for j in keep]
    if renderer_tree.get("m_RootBone", {}).get("m_PathID") in {bones[i] for i in target}:
        renderer_tree["m_RootBone"] = {"m_FileID": 0, "m_PathID": head}
    renderer.save_typetree(renderer_tree)
    _save(env, path)
    def name(pid):
        return objs[transforms[pid]["m_GameObject"]["m_PathID"]].read_typetree()["m_Name"]

    log(f"[game] the body renderer cannot use face-side bones; bound {moved} vertices from "
        f"{', '.join(name(bones[i]) for i in target)} to Head")
    chains = [_ancestors(transforms, bones[i]) for i in target]
    if any(name(p).endswith("_Dyna") for chain in chains for p in chain[:chain.index(head_all)]):
        log("[warn] those vertices followed swinging hair bones; on the body they follow the head without swinging")
    return moved


def _cull(material_tree):
    for name, value in material_tree["m_SavedProperties"]["m_Floats"]:
        if name == "_CullMode":
            return float(value)
    return None


def split_culled_part(path, renderer_id, added_index_count, donor_cull, log=print):
    """Apply rule 2 to one written renderer. Returns the new material's path ID or None."""
    import costume_part_transplant as cpt
    if donor_cull not in (1., 2.) or added_index_count <= 0:
        return None
    env, objs = _load(path)
    renderer = objs[int(renderer_id)]
    renderer_tree = renderer.read_typetree()
    mesh = objs[renderer_tree["m_Mesh"]["m_PathID"]]
    tree = mesh.read_typetree()
    submeshes = tree["m_SubMeshes"]
    materials = renderer_tree["m_Materials"]
    receiving_index = min(len(submeshes), len(materials)) - 1
    if receiving_index < 0:
        return None
    receiving = materials[receiving_index]["m_PathID"]
    receiving_tree = objs[receiving].read_typetree()
    if _cull(receiving_tree) != 0.:
        return None
    last = submeshes[-1]
    if int(last["indexCount"]) <= int(added_index_count) or len(materials) != len(submeshes):
        log("[warn] the grafted part could not get its own culled material; its back faces can show")
        return None
    width = 2 if tree.get("m_IndexFormat", 0) == 0 else 4
    indices = np.frombuffer(bytes(tree["m_IndexBuffer"]), "<u2" if width == 2 else "<u4")
    end = int(last["firstByte"]) // width + int(last["indexCount"])
    start = end - int(added_index_count)
    used = np.unique(indices[start:end].astype(np.int64) + int(last.get("baseVertex", 0)))
    count, channels, strides, starts, _ = cpt.stream_layout(tree)
    positions = cpt.read_attr(np.frombuffer(bytes(tree["m_VertexData"]["m_DataSize"]), np.uint8),
                              cpt.ATTR_POS, channels, strides, starts, count)[used, :3]
    part = copy.deepcopy(last)
    low, high = positions.min(0), positions.max(0)
    part.update(firstByte=start * width, indexCount=int(added_index_count),
                firstVertex=int(used.min()), vertexCount=int(used.max() - used.min() + 1))
    part["localAABB"] = {"m_Center": dict(zip("xyz", map(float, (low + high) / 2))),
                         "m_Extent": dict(zip("xyz", map(float, (high - low) / 2)))}
    last["indexCount"] = int(last["indexCount"]) - int(added_index_count)
    submeshes.append(part)
    mesh.save_typetree(tree)

    culled = copy.deepcopy(receiving_tree)
    culled["m_Name"] = receiving_tree["m_Name"] + "_culled"
    rows = []
    for row in culled["m_SavedProperties"]["m_Floats"]:
        name, value = row
        value = float(donor_cull) if name == "_CullMode" else value
        rows.append((name, value) if isinstance(row, tuple) else [name, value])
    culled["m_SavedProperties"]["m_Floats"] = rows
    seed = hashlib.sha256(f"culled:{receiving}:{renderer.path_id}".encode()).digest()
    new_id = int.from_bytes(seed[:8], "little") & ((1 << 62) - 1)
    while new_id in objs or new_id == 0:
        new_id += 1
    cpt._make_object(renderer.assets_file, objs[receiving], new_id, culled)
    pointer = {"m_FileID": 0, "m_PathID": new_id}
    renderer_tree["m_Materials"] = materials + [pointer]
    renderer.save_typetree(renderer_tree)
    for obj in objs.values():
        if obj.type.name != "MonoBehaviour":
            continue
        component = obj.read_typetree()
        listed = component.get("materials")
        if isinstance(listed, list) and any(row.get("m_FileID") == 0 and row.get("m_PathID") == receiving for row in listed):
            component["materials"] = listed + [dict(pointer)]
            obj.save_typetree(component)
    bundle = next((obj for obj in objs.values() if obj.type.name == "AssetBundle"), None)
    if bundle is not None:
        bundle_tree = bundle.read_typetree()
        if len(bundle_tree.get("m_Container", [])) == 1:
            bundle_tree["m_PreloadTable"].append(dict(pointer))
            bundle_tree["m_Container"][0][1]["preloadSize"] += 1
            bundle.save_typetree(bundle_tree)
    _save(env, path)
    log(f"[game] the grafted part keeps _CullMode {donor_cull:g} in its own submesh "
        f"({culled['m_Name']}); drawn from both sides its back faces flicker")
    return new_id
