"""Publish a graft through the game's original single-material Body renderer.

The game combines only submesh zero and reads the singular sharedMaterial.
Donor geometry may temporarily have separate triangle groups, but saved bundles
must carry one group using the target material settings and a baked atlas.
Shared assets are detached for the Body so other surfaces retain their look.
"""
from __future__ import annotations

from copy import deepcopy


def _index(environment):
    result = {}
    for obj in environment.objects:
        if obj.path_id in result:
            raise ValueError("The costume contains ambiguous object IDs; use one costume bundle for the graft.")
        result[obj.path_id] = obj
    return result


def _resolve(objects, pointer, kind, label):
    if isinstance(pointer, int):
        pointer = {"m_FileID": 0, "m_PathID": pointer}
    if not isinstance(pointer, dict) or pointer.get("m_FileID", 0) != 0:
        raise ValueError(f"{label} must be stored in its costume bundle before its materials can be baked.")
    obj = objects.get(pointer.get("m_PathID"))
    if obj is None or obj.type.name != kind:
        raise ValueError(f"{label} has no readable {kind}; choose an intact costume bundle.")
    return obj


def _texture_slots(material_tree):
    result = {}
    for entry in material_tree.get("m_SavedProperties", {}).get("m_TexEnvs", []):
        if isinstance(entry, (list, tuple)) and len(entry) == 2:
            name, value = entry
        elif isinstance(entry, dict):
            name, value = entry.get("first"), entry.get("second")
        else:
            raise ValueError("The target material has an unsupported texture-property layout.")
        if name in result or not isinstance(value, dict):
            raise ValueError("The target material has invalid or repeated texture properties.")
        result[name] = value
    return result


def _uv_bounds(mesh_tree):
    import numpy as np
    from costume_part_transplant import stream_layout, read_attr, submesh_triangles, ATTR_UV0
    count, channels, strides, starts, _ = stream_layout(mesh_tree)
    raw = np.frombuffer(bytes(mesh_tree["m_VertexData"]["m_DataSize"]), np.uint8)
    channel = channels[ATTR_UV0] if ATTR_UV0 < len(channels) else {}
    if channel.get("dimension", 0) < 2 or channel.get("format") not in (0, 1):
        raise ValueError("Atlas merging requires Float32 or Float16 UV0 coordinates.")
    if channel.get("format") == 1 and channel.get("dimension", 0) >= 2:
        stream, offset, dimension = channel["stream"], channel["offset"], channel["dimension"]
        block = raw[starts[stream]:starts[stream] + count * strides[stream]].reshape(count, strides[stream])
        uv = block[:, offset:offset + dimension * 2].copy().view("<f2").reshape(count, dimension).astype(np.float64)
    else:
        uv = read_attr(raw, ATTR_UV0, channels, strides, starts, count)
    if uv is None or uv.shape[1] < 2 or not np.isfinite(uv[:, :2]).all():
        raise ValueError("The Body mesh needs finite UV0 coordinates for a game-compatible graft.")
    result = []
    for group in submesh_triangles(mesh_tree):
        indices = np.unique(group)
        if len(indices) == 0:
            result.append(None)
            continue
        if indices.min() < 0 or indices.max() >= count:
            raise ValueError("A Body submesh references an invalid vertex.")
        selected = uv[indices, :2]
        low, high = selected.min(axis=0), selected.max(axis=0)
        result.append(tuple(float(value) for value in (*low, *high)))
    return result


_MATERIAL_CONTROLLERS = {"LiveCoreMemberAmbient", "LiveCoreMemberRimlight"}


def _pointers(value):
    if isinstance(value, dict):
        if "m_FileID" in value and "m_PathID" in value:
            yield value
        else:
            for child in value.values():
                yield from _pointers(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _pointers(child)


def _refers_to(owner, pointer, target):
    if not isinstance(pointer, dict) or pointer.get("m_PathID") != target.path_id:
        return False
    if pointer.get("m_FileID", 0) == 0:
        return owner.assets_file is target.assets_file
    # A loaded second SerializedFile can also reference the Body asset. FileID
    # is relative to the referring file, so matching just PathID is unsafe.
    from UnityPy.classes import PPtr
    try:
        return PPtr(m_FileID=pointer["m_FileID"], m_PathID=target.path_id,
                    assetsfile=owner.assets_file).deref() is target
    except (ValueError, KeyError, FileNotFoundError, IndexError):
        return False


def canonical_body_smr(objects):
    """Resolve an attached Body renderer independently of serialized ordering."""
    objects = list(objects)
    index = {(id(obj.assets_file), obj.path_id): obj for obj in objects}
    candidates = []
    for renderer in objects:
        if renderer.type.name != "SkinnedMeshRenderer":
            continue
        tree = renderer.read_typetree()
        pointer = tree.get("m_Mesh", {})
        mesh = index.get((id(renderer.assets_file), pointer.get("m_PathID"))) if pointer.get("m_FileID", 0) == 0 else None
        if mesh is None or mesh.type.name != "Mesh":
            continue
        pointer = tree.get("m_GameObject", {})
        go = index.get((id(renderer.assets_file), pointer.get("m_PathID"))) if pointer.get("m_FileID", 0) == 0 else None
        name = go.read_typetree().get("m_Name", "") if go is not None and go.type.name == "GameObject" else ""
        mesh_tree = mesh.read_typetree()
        candidates.append((renderer, tree, mesh_tree, str(name).casefold() == "body"))
    if not candidates:
        return None
    named = [row for row in candidates if row[3]]
    if named:
        candidates = named
    else:
        named = [row for row in candidates if str(row[2].get("m_Name", "")).casefold() == "body"]
        if named:
            candidates = named
        ranks = [(len(row[1].get("m_Bones", [])), int(row[2].get("m_VertexData", {}).get("m_VertexCount", 0)))
                 for row in candidates]
        best = max(ranks)
        candidates = [row for row, rank in zip(candidates, ranks) if rank == best]
    if len(candidates) != 1:
        raise ValueError("Several renderers could be the Body. Choose the target skinned mesh explicitly.")
    return candidates[0][0]


def _reference_trees(objects):
    # AssetBundle preload/container pointers describe dependencies, not another
    # rendered surface. Texture and shader payloads cannot reference a Material
    # or Mesh and can be expensive to decode.
    ignored = {"AssetBundle", "Texture2D", "Texture2DArray", "Texture3D", "Cubemap", "Shader"}
    return [(obj, obj.read_typetree()) for obj in objects.values() if obj.type.name not in ignored]


def _script_class(objects, owner, tree):
    pointer = tree.get("m_Script", {})
    script = objects.get(pointer.get("m_PathID"))
    if script is not None and script.type.name == "MonoScript" and _refers_to(owner, pointer, script):
        metadata = script.read_typetree()
        if (metadata.get("m_Namespace") == "LLAS.Scene.Live.Components"
                and str(metadata.get("m_AssemblyName", "")).removesuffix(".dll") == "Assembly-CSharp"):
            return metadata.get("m_ClassName")
    return None


def _shared_assets(objects, renderer, mesh, material=None):
    shared_mesh = shared_material = False
    reference_trees = _reference_trees(objects)
    for other, tree in reference_trees:
        if other is renderer:
            continue
        # These two verified game components apply common lighting uniforms to
        # every listed material. They do not assign a surface's material.
        if other.type.name == "MonoBehaviour" and _script_class(objects, other, tree) in _MATERIAL_CONTROLLERS:
            tree = {key: value for key, value in tree.items() if key != "materials"}
        for pointer in _pointers(tree):
            shared_mesh |= _refers_to(other, pointer, mesh)
            if material is not None:
                shared_material |= _refers_to(other, pointer, material)
    return shared_mesh, shared_material, reference_trees


def _lighting_bindings(objects, reference_trees, material, new_pid):
    updates = []
    for owner, tree in reference_trees:
        if owner.type.name != "MonoBehaviour" or _script_class(objects, owner, tree) not in _MATERIAL_CONTROLLERS:
            continue
        materials = tree.get("materials")
        if not isinstance(materials, list):
            continue
        source = next((p for p in materials if _refers_to(owner, p, material)), None)
        if source is not None:
            updated = deepcopy(tree)
            pointer = deepcopy(source)
            pointer["m_PathID"] = new_pid
            updated["materials"].append(pointer)
            updates.append((owner, updated))
    return updates


def save_isolated_mesh(environment, renderer, mesh, mesh_tree):
    """Save a pre-atlas cut without changing any other surface's shared mesh.

    Lower-body grafts reopen this intermediate bundle before the atlas pass.
    Detach before that first write, while the shared original is still intact.
    """
    from costume_part_transplant import _make_object, _rand_pids
    if (renderer.type.name != "SkinnedMeshRenderer" or mesh.type.name != "Mesh"
            or renderer.assets_file is not mesh.assets_file
            or not _refers_to(renderer, renderer.read_typetree().get("m_Mesh"), mesh)):
        raise ValueError("The selected Body renderer needs its own referenced local mesh before cutting.")
    shared, _, _ = _shared_assets(_index(environment), renderer, mesh)
    if not shared:
        original = mesh.data
        try:
            mesh.save_typetree(mesh_tree)
        except Exception:
            mesh.data = original
            raise
        return mesh
    sf = mesh.assets_file
    pid = _rand_pids(1, set(sf.objects))[0]
    tree = deepcopy(renderer.read_typetree())
    tree["m_Mesh"] = {"m_FileID": 0, "m_PathID": pid}
    original = renderer.data
    try:
        detached = _make_object(sf, mesh, pid, mesh_tree)
        renderer.save_typetree(tree)
    except Exception:
        sf.objects.pop(pid, None)
        renderer.data = original
        raise
    return detached


def bake_renderer_for_game(environment, smr_object, mesh_object=None, *, mesh_tree=None,
                           renderer_tree=None, additional_sources=(), log=lambda message: None,
                           max_vertices=65535, max_dimension=4096, reuse_empty_uv=True,
                           relocate_empty_uv=False, upscale_textures_for_uv_reuse=True,
                           uv_placement=None):
    """Bake every Body material group into its original single material slot.

    ``additional_sources`` contains ``(donor_environment, material_pointer_or_id)``
    pairs, in the order of temporary donor submeshes following the target's
    original material groups. Original donor shader identities are retained for
    compatibility checks. No donor materials/textures are injected beforehand.

    Atlas construction and geometry validation complete on detached trees before
    any Unity object changes. Supplied working trees are updated after success,
    so a caller's later serialization cannot restore temporary material groups.
    ``reuse_empty_uv`` first attempts donor placement at unchanged UVs when its
    texels do not overlap retained target faces. ``relocate_empty_uv`` also
    permits native-resolution placement elsewhere, then falls back to an atlas.
    ``upscale_textures_for_uv_reuse`` first enlarges smaller corresponding
    UV textures to the larger resolution before trying either UV path.
    An explicit ``uv_placement`` selects same-position reuse, relocation with
    original main dimensions, or an ordinary atlas; it overrides legacy flags.
    """
    from graft_texture_atlas import MaterialSource, bake_game_atlas
    from graft_atlas_geometry import flatten_material_groups
    from costume_part_transplant import _make_object, _rand_pids

    if any(type(value) is not bool for value in
           (reuse_empty_uv, relocate_empty_uv, upscale_textures_for_uv_reuse)):
        raise ValueError("UV reuse options must be true or false.")
    if uv_placement is not None and (not isinstance(uv_placement, str) or
                                     uv_placement not in ("same_position", "move_to_empty", "atlas")):
        raise ValueError("Choose same_position, move_to_empty or atlas for UV placement.")
    if uv_placement is None and relocate_empty_uv and not reuse_empty_uv:
        raise ValueError("Enable empty UV reuse before relocating donor UVs.")
    objects = _index(environment)
    if smr_object.type.name != "SkinnedMeshRenderer":
        raise ValueError("Game-compatible grafting needs a skinned Body renderer.")
    renderer = deepcopy(renderer_tree if renderer_tree is not None else smr_object.read_typetree())
    if mesh_object is None:
        mesh_object = _resolve(objects, renderer.get("m_Mesh"), "Mesh", "The Body renderer")
    if mesh_object.type.name != "Mesh" or mesh_object.assets_file is not smr_object.assets_file:
        raise ValueError("The Body mesh and renderer must belong to the same costume file.")
    if not _refers_to(smr_object, renderer.get("m_Mesh"), mesh_object):
        raise ValueError("The selected Body renderer does not reference its supplied mesh.")
    original_mesh = mesh_tree if mesh_tree is not None else mesh_object.read_typetree()
    working_mesh = deepcopy(original_mesh)
    bone_count = len(renderer.get("m_Bones", []))
    if bone_count > 256:
        raise ValueError(f"The Body would have {bone_count} bones; the game limit is 256. Select a smaller donor part.")
    if bone_count != len(working_mesh.get("m_BindPose", [])):
        raise ValueError("The Body bone list and bind poses do not match; reopen an intact costume before grafting.")
    materials = renderer.get("m_Materials", [])
    additions = tuple(additional_sources)
    group_count = len(working_mesh.get("m_SubMeshes", []))
    if not materials or group_count != len(materials) + len(additions):
        raise ValueError("The Body needs exactly one material source for each triangle group; reopen an intact costume and retry the graft.")
    first_material = _resolve(objects, materials[0], "Material", "The Body's original material")
    if first_material.assets_file is not smr_object.assets_file:
        raise ValueError("The Body material must be stored beside its mesh before grafting.")
    shared_mesh, shared_material, reference_trees = _shared_assets(objects, smr_object, mesh_object, first_material)
    bounds = _uv_bounds(working_mesh)
    sources = []
    for ordinal, pointer in enumerate(materials):
        material = _resolve(objects, pointer, "Material", f"Body material {ordinal + 1}")
        tree = material.read_typetree()
        sources.append(MaterialSource(tree.get("m_Name", f"Body material {ordinal + 1}"),
            deepcopy(tree), objects, material_object=material, uv_bounds=bounds[ordinal]))
    for ordinal, pair in enumerate(additions, len(materials)):
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise ValueError("Each donor triangle group needs its original costume material source.")
        donor_environment, pointer = pair
        donor_objects = _index(donor_environment)
        material = _resolve(donor_objects, pointer, "Material", f"Donor material {ordinal + 1}")
        tree = material.read_typetree()
        sources.append(MaterialSource(tree.get("m_Name", f"Donor material {ordinal + 1}"),
            deepcopy(tree), donor_objects, material_object=material, uv_bounds=bounds[ordinal]))

    fallback_diagnostics = []
    baked = None
    if uv_placement != "atlas" and (uv_placement is not None or reuse_empty_uv):
        from graft_uv_reuse import prepare_uv_reuse
        reuse_options = {"diagnostics": fallback_diagnostics,
                         "upscale_textures_for_uv_reuse": upscale_textures_for_uv_reuse,
                         "uv_placement": uv_placement}
        if relocate_empty_uv:
            reuse_options["relocate_empty_uv"] = True
        baked = prepare_uv_reuse(sources, working_mesh, original_group_count=len(materials),
                                **reuse_options)
    texture_mode = "reuse_empty_uv" if baked is not None else "atlas"
    if baked is not None and baked.identity:
        texture_mode = "identity"
    elif baked is not None and any(tuple(transform.scale) != (1.0, 1.0) or tuple(transform.offset) != (0.0, 0.0)
                                 for transform in baked.transforms):
        texture_mode = "relocate_empty_uv"
    if baked is None:
        baked = bake_game_atlas(sources[0], sources[1:], max_dimension=max_dimension, gutter=0)
        if baked.identity:
            texture_mode = "identity"
    geometry = flatten_material_groups(working_mesh, baked.transforms, max_vertices=max_vertices)
    material_tree = deepcopy(first_material.read_typetree())
    slots = _texture_slots(material_tree)
    sf = first_material.assets_file
    # Allocate all new IDs together, including detached Body assets. Original
    # meshes/materials and every unrelated consumer retain their identities.
    detach_material = shared_material and bool(baked.textures)
    pids = iter(_rand_pids(len(baked.textures) + int(shared_mesh) + int(detach_material), set(sf.objects)))
    mesh_pid = next(pids) if shared_mesh else mesh_object.path_id
    material_pid = next(pids) if detach_material else first_material.path_id
    prepared = []
    for slot, texture in baked.textures.items():
        pid = next(pids)
        if slot not in slots:
            known_slots = {"_MainTex", "_RimlightTex", "_MatcapMaskTex", "_EmissiveTex", "_EmissiveScrollTex"}
            if slot not in known_slots:
                raise ValueError(f"The target shader has no {slot} texture slot for the graft atlas.")
            # AS/Member may use a default texture without serializing this
            # property. Its default cell is baked alongside the donor's map.
            value = {"m_Texture": {"m_FileID": 0, "m_PathID": 0},
                     "m_Scale": {"x": 1.0, "y": 1.0}, "m_Offset": {"x": 0.0, "y": 0.0}}
            material_tree.setdefault("m_SavedProperties", {}).setdefault("m_TexEnvs", []).append((slot, value))
            slots[slot] = value
        if texture.template.assets_file is not sf:
            raise ValueError("The atlas texture template is outside the target costume file.")
        tree = deepcopy(texture.tree)
        if max(int(tree.get("m_Width", 0)), int(tree.get("m_Height", 0))) > max_dimension:
            raise ValueError(f"The graft atlas exceeds {max_dimension} pixels; select a smaller part.")
        prepared.append((pid, texture.template, tree))
        slots[slot]["m_Texture"] = {"m_FileID": 0, "m_PathID": pid}
    renderer["m_Materials"] = [{"m_FileID": 0, "m_PathID": material_pid}]
    renderer["m_Mesh"] = {"m_FileID": 0, "m_PathID": mesh_pid}
    if working_mesh.get("m_LocalAABB"):
        renderer["m_AABB"] = deepcopy(working_mesh["m_LocalAABB"])

    # Every potentially expensive/unsupported conversion above is complete.
    # Keep a rollback for an unexpected Unity serializer failure while committing.
    bindings = _lighting_bindings(objects, reference_trees, first_material, material_pid) if detach_material else []
    originals = [(obj, obj.data) for obj in (mesh_object, first_material, smr_object)]
    originals.extend((obj, obj.data) for obj, _ in bindings)
    created = [pid for pid, _, _ in prepared]
    if shared_mesh:
        created.append(mesh_pid)
    if detach_material:
        created.append(material_pid)
    try:
        for pid, template, tree in prepared:
            _make_object(sf, template, pid, tree)
        if shared_mesh:
            _make_object(sf, mesh_object, mesh_pid, working_mesh)
        else:
            mesh_object.save_typetree(working_mesh)
        if detach_material:
            _make_object(sf, first_material, material_pid, material_tree)
        elif prepared:
            first_material.save_typetree(material_tree)
        for obj, tree in bindings:
            obj.save_typetree(tree)
        smr_object.save_typetree(renderer)
    except Exception:
        for pid in created:
            sf.objects.pop(pid, None)
        for obj, data in originals:
            obj.data = data
        raise
    if mesh_tree is not None:
        mesh_tree.clear(); mesh_tree.update(working_mesh)
    if renderer_tree is not None:
        renderer_tree.clear(); renderer_tree.update(renderer)
    diagnostics = fallback_diagnostics + list(baked.diagnostics)
    if shared_mesh or detach_material:
        diagnostics.append("Detached shared Body " + " and ".join(
            name for name, detached in (("mesh", shared_mesh), ("material", detach_material)) if detached)
            + "; other surfaces keep their original assets.")
    for diagnostic in diagnostics:
        log(str(diagnostic))
    mode_label = {"reuse_empty_uv": "reuse empty UV areas", "relocate_empty_uv": "relocate into empty UV areas",
                  "atlas": "texture atlas", "identity": "original textures"}[texture_mode]
    log(f"Body textures: {mode_label}; {group_count} groups combined into one Body material.")
    return {**geometry, "source_materials": len(sources), "materials": 1,
            "atlas_textures": len(prepared), "atlas_identity": baked.identity,
            "atlas_sources": baked.unique_sources, "texture_mode": texture_mode,
            "requested_uv_placement": uv_placement, "diagnostics": diagnostics,
            "detached_mesh": shared_mesh, "detached_material": detach_material,
            "atlas_dimensions": {slot: [texture.width, texture.height] for slot, texture in baked.textures.items()}}
