"""Stock AS/Member outlines: edit the original UNorm8 red width mask only.

The game's shader has no material outline-width/color property. Red is its
width, green its depth bias, blue a main-surface lighting mask. Exports always
derive red from immutable source bytes and leave every other attribute intact.
"""
import json
import math
import ntpath
from types import SimpleNamespace

MAX_MESHES = 256
MAX_VERTICES = 250000


def _error(message):
    raise ValueError(message)


def _resolve(info, owner, pointer):
    if not isinstance(pointer, dict) or type(pointer.get("m_PathID")) is not int or not pointer["m_PathID"]:
        return None
    file_id = pointer.get("m_FileID", 0)
    if type(file_id) is not int:
        return None
    if file_id == 0:
        return owner.assets_file.objects.get(pointer["m_PathID"])
    if not 1 <= file_id <= len(owner.assets_file.externals):
        return None
    target = ntpath.basename(owner.assets_file.externals[file_id - 1].path).casefold()
    matches = [obj for obj in info["objects"].values() if obj.path_id == pointer["m_PathID"] and
               ntpath.basename(obj.assets_file.name).casefold() == target]
    return matches[0] if len(matches) == 1 else None


def _member(info, material):
    if material is None or material.type.name != "Material":
        return False
    from .model_viewer import _as_member_material
    tree = material.read_typetree()
    shader = _resolve(info, material, tree.get("m_Shader"))
    if shader is not None:
        if shader.type.name != "Shader":
            return False
        value = shader.read_typetree()
        # Hidden/Main has no outline pass itself; do not invent one for export.
        if (value.get("m_Name") or value.get("m_ParsedForm", {}).get("m_Name")) != "AS/Member":
            return False
    scene = SimpleNamespace(env=info["env"], tree=lambda obj: obj.read_typetree())
    return _as_member_material(scene, material, tree)


def _paths(info):
    paths, active = {}, set()
    anchored = sum(name == "Move" for name in info["names"].values()) == 1
    def path(key):
        if key in paths:
            return paths[key]
        if key in active or len(active) > 256:
            return None
        active.add(key)
        name = info["names"].get(key)
        parent = info["parents"].get(key)
        if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 1024:
            result = None
        elif anchored and name == "Move":
            result = ["sifas-skeleton", "Move"]
        elif parent in info["transforms"]:
            previous = path(parent)
            result = previous + [name] if previous is not None else None
        else:
            result = ["complete-hierarchy", name]
        if result is not None and sum(len(part.encode("utf-8")) + 1 for part in result) > 4096:
            result = None
        active.remove(key)
        paths[key] = result
        return result
    for key in info["transforms"]:
        path(key)
    return paths


def _layout(tree):
    from sifas_mesh_baker import stream_layout
    count, channels, strides, starts, _ = stream_layout(tree)
    if not 0 < count <= MAX_VERTICES or len(channels) <= 3:
        _error("The outline mesh exceeds its supported vertex limit.")
    color = channels[3]
    if color.get("dimension") != 4 or color.get("format") != 2:
        _error("Outline saving requires the original four-channel UNorm8 color mask.")
    data = tree["m_VertexData"].get("m_DataSize")
    # Unity aligns starts between streams, but omits final trailing padding in
    # e.g. original Face meshes (417*52 bytes, not align16(417*52)).
    required = max(starts[stream] + count * stride for stream, stride in strides.items())
    if not isinstance(data, (bytes, bytearray, list)) or len(data) < required:
        _error("The original outline color stream is truncated.")
    stream = color["stream"]
    return count, starts[stream] + color["offset"], strides[stream]


def catalogue(info, source_index):
    """Catalogue only local, writable meshes wholly using verified AS/Member."""
    records, references, transforms = [], {}, {}
    file_indices = info["file_indices"]
    for key, tree in info["transforms"].items():
        pointer = tree.get("m_GameObject", {})
        if pointer.get("m_FileID", 0) == 0:
            transforms[(key[0], pointer.get("m_PathID"))] = key
    filters = {}
    for key, obj in info["objects"].items():
        if obj.type.name == "MeshFilter":
            tree = obj.read_typetree()
            game = _resolve(info, obj, tree.get("m_GameObject"))
            if game is not None:
                filters.setdefault((file_indices[id(game.assets_file)], game.path_id), []).append((obj, tree))
    semantic_paths = _paths(info)
    for key, obj in info["objects"].items():
        if obj.type.name not in ("SkinnedMeshRenderer", "MeshRenderer"):
            continue
        tree = obj.read_typetree()
        game = _resolve(info, obj, tree.get("m_GameObject"))
        if game is None or game.type.name != "GameObject":
            continue
        game_key = (file_indices[id(game.assets_file)], game.path_id) if game is not None else None
        mesh_owner, mesh_pointer = obj, tree.get("m_Mesh")
        if obj.type.name == "MeshRenderer":
            matches = filters.get(game_key, [])
            if len(matches) != 1:
                continue
            mesh_owner, mesh_filter = matches[0]
            mesh_pointer = mesh_filter.get("m_Mesh")
        mesh = _resolve(info, mesh_owner, mesh_pointer)
        if mesh is None or mesh.type.name != "Mesh":
            continue
        mesh_key = (file_indices[id(mesh.assets_file)], mesh.path_id)
        pointers = tree.get("m_Materials", [])
        supported = bool(pointers) and all(_member(info, _resolve(info, obj, pointer)) for pointer in pointers)
        root = _resolve(info, obj, tree.get("m_RootBone"))
        root_key = (file_indices[id(root.assets_file)], root.path_id) if root is not None else None
        anchor = semantic_paths.get(root_key) if root_key in info["transforms"] else semantic_paths.get(transforms.get(game_key))
        binding = [obj.type.name, game.read_typetree().get("m_Name", "") if game is not None else "", anchor]
        references.setdefault(mesh_key, []).append((supported, binding))
    for key, uses in references.items():
        if not all(supported for supported, _ in uses):
            continue
        obj = info["objects"][key]
        tree = obj.read_typetree()
        try:
            count, _, _ = _layout(tree)
        except (KeyError, ValueError, TypeError, NotImplementedError):
            continue
        name = tree.get("m_Name", "")
        if not isinstance(name, str) or len(name.encode("utf-8")) > 1024:
            continue
        bindings = [binding for _, binding in uses]
        signatures = [json.dumps(binding, sort_keys=True) for binding in bindings]
        semantic = ([name, sorted(bindings, key=lambda row: json.dumps(row, sort_keys=True))]
                    if name and all(row[1] and row[2] for row in bindings) and len(set(signatures)) == len(signatures) else None)
        records.append({"id": f"{source_index}:{key[0]}:{key[1]}", "sourceIndex": source_index,
                        "file": key[0], "meshId": str(key[1]), "name": name or "Mesh",
                        "vertexCount": count, "format": "UNorm8", "channel": 3,
                        "min": 0, "max": 2, "default": 1, "saturatesAbove": 1,
                        "semantic": semantic})
    if len(records) > MAX_MESHES:
        _error("The model has too many outline meshes.")
    return {"version": 1, "available": bool(records), "meshes": records}


def validate(catalog, values):
    if not isinstance(values, list) or len(values) > MAX_MESHES:
        _error("The outline edit list is invalid.")
    known = {row["id"]: row for row in catalog.get("meshes", [])}
    normalized, seen = [], set()
    for value in values:
        if not isinstance(value, dict) or set(value) != {"id", "factor"}:
            _error("An outline edit contains unsupported properties.")
        identity, factor = value["id"], value["factor"]
        if not isinstance(identity, str) or identity not in known or identity in seen:
            _error("The outline mesh does not belong to this original model, or occurs twice.")
        seen.add(identity)
        if type(factor) not in (int, float) or not 0 <= factor <= 2 or not math.isfinite(factor):
            _error("Outline strength must be a finite value between zero and two.")
        if factor != 1:
            normalized.append({"id": identity, "factor": float(factor)})
    return sorted(normalized, key=lambda value: value["id"])


def apply_edits(raw, source_index, values, catalog, *, original_raw=None):
    from .model_edits import _inspect
    values = validate(catalog, values)
    known = {row["id"]: row for row in catalog.get("meshes", [])}
    selected = [value for value in values if known[value["id"]]["sourceIndex"] == source_index]
    if not selected:
        return raw
    info = _inspect(raw)
    original = _inspect(original_raw) if original_raw is not None else info
    current = {row["id"]: row for row in catalogue(info, source_index)["meshes"]}
    basis = {row["id"]: row for row in catalogue(original, source_index)["meshes"]}
    expected = {}
    for edit in selected:
        record = known[edit["id"]]
        for lookup in (current, basis):
            found = lookup.get(edit["id"])
            if found is None or any(found[name] != record[name] for name in ("meshId", "file", "vertexCount", "format", "semantic")):
                _error("The original outline mesh identity or layout changed before saving.")
        key = record["file"], int(record["meshId"])
        obj, original_obj = info["objects"][key], original["objects"][key]
        tree, source_tree = obj.read_typetree(), original_obj.read_typetree()
        count, start, stride = _layout(tree)
        _, source_start, source_stride = _layout(source_tree)
        data, source_data = bytearray(tree["m_VertexData"]["m_DataSize"]), source_tree["m_VertexData"]["m_DataSize"]
        for vertex in range(count):
            red = source_data[source_start + vertex * source_stride]
            data[start + vertex * stride] = min(255, max(0, int(red * edit["factor"] + .5)))
        tree["m_VertexData"]["m_DataSize"] = bytes(data)
        obj.save_typetree(tree)
        expected[key] = bytes(data)
    blob = info["env"].file.save(packer="original")
    check = _inspect(blob)
    for key, data in expected.items():
        if bytes(check["objects"][key].read_typetree()["m_VertexData"]["m_DataSize"]) != data:
            _error("The saved outline mask failed its exact reload check.")
    return blob
