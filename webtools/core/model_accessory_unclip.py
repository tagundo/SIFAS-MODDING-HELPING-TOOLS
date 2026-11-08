"""Source-bound accessory lifts, following sifas_accessory_unclip's cloth test.

Only anchor transforms are written by the caller. Detection always reads the
immutable source skin, and each scale region must have an original validated
LiveCoreMemberNodeScaling record; arbitrary mesh bones are not inferred regions.
"""
import math


class AccessoryUnclipError(ValueError):
    pass


def options(value):
    if not isinstance(value, dict) or set(value) - {"strength", "overlap", "closeGaps"}:
        raise AccessoryUnclipError("Accessory unclipping contains unsupported settings.")
    out = {}
    for name, default, maximum in (("strength", 1., 3.), ("overlap", .15, 1.)):
        number = value.get(name, default)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise AccessoryUnclipError("Accessory " + name + " is outside its supported range.")
        try:
            number = float(number)
        except (OverflowError, ValueError) as error:
            raise AccessoryUnclipError("Accessory " + name + " is outside its supported range.") from error
        if not math.isfinite(number) or not 0 <= number <= maximum:
            raise AccessoryUnclipError("Accessory " + name + " is outside its supported range.")
        out[name] = number
    flag = value.get("closeGaps", False)
    if type(flag) is not bool:
        raise AccessoryUnclipError("Accessory gap closing must be on or off.")
    out["closeGaps"] = flag
    return out


# Same body/ornament distinction as the legacy tool; HipsSize is additionally
# protected because it is a body-size control rather than an ornament anchor.
_BODY = {"Reference", "Move", "Position", "Center", "Hips_Position", "Hips", "HipsSize",
         "Spine", "Spine1", "Spine2", "Neck", "Neck1", "Head", "BreastSize"}
_LIMBS = {"Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase", "Toe",
          "HandThumb", "HandIndex", "HandMiddle", "HandRing", "HandPinky",
          "HandThumb1", "HandThumb2", "HandThumb3"}


def _body(name):
    return not name or name in _BODY or "Breast" in name or name.startswith("Head_") or any(
        name.startswith(side) and name[len(side):] in _LIMBS for side in ("Left", "Right"))


def plan(info, local_runtime, local_desired, desired_values, settings, *, writable_keys):
    """Return one world lift, and separate preview/export parent-frame deltas.

    The target's saved scale is absolute. Dividing by its authored scale avoids
    applying nonunit authored transforms twice. Ancestor edits/compensation stay
    in both comparison frames; a Mesh Baker parent therefore is not multiplied
    into the export translation a second time.
    """
    import numpy as np
    from . import model_edits as edits
    from .repo import ensure_repo_on_path
    ensure_repo_on_path()
    from sifas_mesh_baker import stream_layout, read_attr, get_skin, mat_from, ATTR_POS

    settings = options(settings)
    summary = {"status": "nothing", "changed": 0, "regions": 0, "candidates": 0}
    empty = {"corrections": {}, "summary": summary}
    nodes = sorted({key for key, kind in info["records"] if kind == "scale"})
    if not nodes:
        summary["status"] = "no_scaling"
        return empty
    for key, transform in info["transforms"].items():
        parent = transform.get("m_Father", {})
        owner = transform.get("m_GameObject", {})
        game = info["objects"].get((key[0], owner.get("m_PathID")))
        if (parent.get("m_FileID", 0) != 0 or parent.get("m_PathID") and parent.get("m_FileID") != 0 or owner.get("m_FileID") != 0 or
                game is None or game.type.name != "GameObject" or
                parent.get("m_PathID") and (key[0], parent["m_PathID"]) not in info["transforms"]):
            raise AccessoryUnclipError("The accessory hierarchy points outside its original model.")
    authored = edits._worlds({key: edits._matrix(value) for key, value in info["authored"].items()}, info["parents"])
    desired = edits._worlds(local_desired, info["parents"])
    runtime = edits._worlds(local_runtime, info["parents"])
    eligible = {}
    for key in nodes:
        old = np.asarray(info["authored"][key]["scale"], float)
        new = np.asarray(desired_values[key]["scale"], float)
        if (np.abs(old) < 1e-8).any():
            raise AccessoryUnclipError("An accessory scale region has a singular authored scale.")
        ratio = new / old
        if max(ratio) > 1.001 or settings["closeGaps"] and min(ratio) < .999:
            eligible[key] = ratio
    if not eligible or settings["strength"] == 0:
        return empty
    renderers = [(obj, obj.read_typetree()) for obj in info["env"].objects if obj.type.name == "SkinnedMeshRenderer"]
    renderers = [(obj, tree) for obj, tree in renderers if tree.get("m_Bones")]
    if not renderers:
        summary["status"] = "no_skin"
        return empty
    maximum = max(len(tree["m_Bones"]) for _, tree in renderers)
    selected = [(obj, tree) for obj, tree in renderers if len(tree["m_Bones"]) == maximum]
    if len(selected) != 1:
        raise AccessoryUnclipError("The costume skin is ambiguous; accessory unclipping cannot choose a renderer.")
    obj, tree = selected[0]
    ordinal = info["file_indices"][id(obj.assets_file)]
    def bound(pointer, kind):
        if pointer.get("m_FileID") != 0:
            raise AccessoryUnclipError("Accessory unclipping cannot follow external " + kind + ".")
        return ordinal, pointer.get("m_PathID")
    mesh = info["objects"].get(bound(tree.get("m_Mesh", {}), "meshes"))
    bones = [bound(pointer, "skin bones") for pointer in tree["m_Bones"]]
    if mesh is None or mesh.type.name != "Mesh" or any(key not in authored for key in bones):
        raise AccessoryUnclipError("The accessory skin is not bound to its original model.")
    mt = mesh.read_typetree()
    poses = mt.get("m_BindPose", [])
    if len(poses) != len(bones):
        raise AccessoryUnclipError("The accessory skin has inconsistent bind poses.")
    count, channels, stride, start, _ = stream_layout(mt)
    if not 0 < count <= edits.MAX_VERTICES:
        raise AccessoryUnclipError("The accessory skin exceeds the supported vertex limit.")
    raw = np.frombuffer(mt["m_VertexData"]["m_DataSize"], np.uint8)
    points = read_attr(raw, ATTR_POS, channels, stride, start, count)
    weights, indices = get_skin(raw, mt, channels, stride, start, count)
    if points is None or weights is None or indices is None:
        summary["status"] = "no_skin"
        return empty
    points, weights, indices = np.asarray(points, float), np.asarray(weights, float), np.asarray(indices, np.int64)
    if (points.shape != (count, 3) or weights.shape != indices.shape or weights.shape[0] != count or
            not np.isfinite(points).all() or not np.isfinite(weights).all() or (weights < 0).any()):
        raise AccessoryUnclipError("The accessory skin contains invalid vertex data.")
    if (np.abs(weights.sum(axis=1) - 1.) > 1e-3).any():
        raise AccessoryUnclipError("The accessory skin has unbound or non-normalized vertex weights.")
    invalid = (indices < 0) | (indices >= len(bones))
    if (invalid & (weights > 0)).any():
        raise AccessoryUnclipError("The accessory skin contains an unbound weighted bone.")
    indices = np.where(invalid, 0, indices)
    matrices = np.asarray([authored[key] @ mat_from(pose) for key, pose in zip(bones, poses)])
    if not np.isfinite(matrices).all():
        raise AccessoryUnclipError("The accessory bind poses contain invalid transforms.")
    homogeneous = np.column_stack((points, np.ones(count)))
    world = np.zeros((count, 3))
    for column in range(weights.shape[1]):
        world += weights[:, column:column+1] * np.einsum("vij,vj->vi", matrices[indices[:, column]], homogeneous)[:, :3]
    dominant = indices[np.arange(count), np.argmax(weights, axis=1)]
    children = {}
    for key, parent in info["parents"].items():
        children.setdefault(parent, []).append(key)
    def subtree(key):
        found, pending = set(), [key]
        while pending:
            item = pending.pop()
            if item in found:
                continue
            found.add(item); pending.extend(children.get(item, ()))
        return found
    def mask(keys):
        return np.isin(dominant, [index for index, bone in enumerate(bones) if bone in keys])
    regions = {}
    for key in eligible:
        sub = subtree(key); selected_points = world[mask(sub)]
        if len(selected_points) >= 8:
            regions[key] = (sub, selected_points.min(axis=0), selected_points.max(axis=0))
    summary["regions"] = len(regions)
    corrections = {}
    for anchor, name in info["names"].items():
        parent = info["parents"].get(anchor)
        if _body(name) or not _body(info["names"].get(parent)) or parent not in authored:
            continue
        vertices = world[mask(subtree(anchor))]
        if not len(vertices):
            continue
        summary["candidates"] += 1
        overlaps = []
        for key, (sub, lo, hi) in regions.items():
            if anchor in sub:
                continue
            z = hi[2] - lo[2]
            selected = ((vertices >= lo - [0, 0, z]) & (vertices <= hi + [0, 0, z])).all(axis=1)
            overlaps.append((float(selected.mean()), key))
        overlaps.sort(reverse=True)
        if not overlaps or overlaps[0][0] < settings["overlap"] or overlaps[0][0] <= 0:
            continue
        if len(overlaps) > 1 and abs(overlaps[0][0] - overlaps[1][0]) < 1e-12:
            raise AccessoryUnclipError("An accessory overlaps multiple equally likely body regions.")
        key = overlaps[0][1]
        if anchor not in writable_keys or (anchor, "position") in info["records"]:
            raise AccessoryUnclipError("The accessory anchor has no unambiguous writable rest position.")
        try:
            centroid = desired[anchor] @ np.linalg.solve(authored[anchor], np.r_[vertices.mean(axis=0), 1.])
            baseline = desired[key] @ np.diag([*(1 / eligible[key]), 1.])
            delta = (desired[key] @ np.linalg.solve(baseline, centroid) - centroid)[:3] * settings["strength"]
            export = np.linalg.solve(runtime[parent][:3, :3], delta)
            preview = np.linalg.solve(desired[parent][:3, :3], delta)
        except np.linalg.LinAlgError as error:
            raise AccessoryUnclipError("The accessory lift has a singular transform chain.") from error
        if not np.isfinite([delta, export, preview]).all() or np.max(np.abs([delta, export, preview])) > edits.MAX_VALUE:
            raise AccessoryUnclipError("The accessory lift exceeds its supported numeric range.")
        if np.max(np.abs(delta)) > 1e-9:
            corrections[anchor] = {"world": delta.tolist(), "export": export.tolist(), "preview": preview.tolist()}
    summary.update(status="applied" if corrections else "nothing", changed=len(corrections))
    return {"corrections": corrections, "summary": summary}
