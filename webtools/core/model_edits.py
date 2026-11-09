"""Source-bound body edits shared by the viewer and persistent Unity exporters.

A session retains immutable selected inputs. Every export starts from them;
preview animation, camera, expressions and imported facial companions are never
an implicit source of persistent edits. Saved NodeScaling endpoints are absolute
local values. Mesh edits migrate their selected properties out of NodeScaling
and bake a rest-frame affine difference into each weighted vertex, including
blend-shape deltas. The game's existing motion assets are left untouched.
"""
from collections import OrderedDict
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import threading
import time
import zipfile

VERSION = 1
MAX_SOURCE_BYTES = 96 * 1024 * 1024
MAX_CACHE_BYTES = 192 * 1024 * 1024
MAX_SESSIONS = 3
SESSION_SECONDS = 30 * 60
MAX_EDITS = 1024
MAX_STATE_BYTES = 512 * 1024
MAX_VERTICES = 250_000
MAX_MORPH_VERTICES = 500_000
MAX_VALUE = 1_000_000
_TOKEN = re.compile(r"^[a-f0-9]{32}$")
_LOCK = threading.RLock()
_SESSIONS = OrderedDict()
_EXPORT_SLOT = threading.BoundedSemaphore(1)
# Observed in four original clips from two MVs, not an all-song guarantee.
_MV_SCALE_NAMES = {"Hips", "Spine", "Spine1", "Spine2", "Neck"} | {
    side + name for side in ("Left", "Right") for name in
    ("Shoulder", "Arm", "ForeArm", "HandThumb1", "HandThumb2", "HandIndex1",
     "HandMiddle1", "HandRing1", "HandPinky1", "UpLeg", "Leg", "Foot", "ToeBase")}
_NODE_NAMES = {"Move", "Head", "Head_Hair", "Neck_Hair", "BreastSize", "Breast_Offset", "HipsSize"}
_KINDS = {"scale": "scaleValues", "position": "positionValues", "rotation": "rotationValues"}


class ModelEditError(ValueError):
    pass


def _fail(message):
    raise ModelEditError(message)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("Body edit values must be finite numbers.")
    value = float(value)
    if not math.isfinite(value) or abs(value) > MAX_VALUE:
        _fail("A body edit is outside the supported numeric range.")
    return value


def _vector(value, *, scale=False):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        _fail("Body edit vectors must have exactly three axes.")
    result = [_number(x) for x in value]
    if scale and any(abs(x) < 1e-8 for x in result):
        _fail("A body scale must not collapse a bone to zero.")
    return result


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_SOURCE_BYTES:
        _fail("The original model is missing or exceeds the body editor limit.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if not 0 < len(raw) <= MAX_SOURCE_BYTES:
        _fail("The original model exceeds the body editor limit.")
    return raw


def _d3(value):
    return dict(zip("xyz", (float(x) for x in value)))


def _v3(value):
    return _vector([value[axis] for axis in "xyz"])


def _quaternion(value):
    import numpy as np
    q = np.asarray([_number(value[axis]) for axis in "xyzw"], float)
    n = float(np.linalg.norm(q))
    if n < 1e-12:
        _fail("The original model contains an invalid rotation.")
    return q / n


def _euler_matrix(value):
    import numpy as np
    x, y, z = (math.radians(a) for a in value)
    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
    return np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ np.array(
        [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]) @ np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])


def _quat_matrix(q):
    import numpy as np
    x, y, z, w = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def _matrix_euler(r):
    # Inverse of Unity's Ry @ Rx @ Rz, matching the viewer's ZXY fields.
    x = math.asin(max(-1., min(1., -float(r[1, 2]))))
    if abs(math.cos(x)) > 1e-7:
        y, z = math.atan2(r[0, 2], r[2, 2]), math.atan2(r[1, 0], r[1, 1])
    else:
        y, z = math.atan2(-r[2, 0], r[0, 0]), 0.
    return [math.degrees(a) for a in (x, y, z)]


def _matrix(value):
    import numpy as np
    result = np.eye(4)
    result[:3, :3] = _euler_matrix(value["rotation"]) @ np.diag(value["scale"])
    result[:3, 3] = value["position"]
    return result


def _public_trs(value):
    return {"scale": list(value["scale"]),
            "position": [-value["position"][0], *value["position"][1:]],
            "rotation": list(value["rotation"])}


def _unity_values(kind, value):
    out = list(value)
    if kind == "position":
        out[0] = -out[0]
    return out


def _close(left, right):
    return max(abs(a-b) for a, b in zip(left, right)) <= 1e-6


def _class_name(obj, tree):
    ptr = tree.get("m_Script", {})
    script = obj.assets_file.objects.get(ptr.get("m_PathID")) if ptr.get("m_FileID") == 0 else None
    if script is None or script.type.name != "MonoScript":
        return None
    return script.read_typetree().get("m_ClassName")


def _inspect(raw):
    import UnityPy
    env = UnityPy.load(raw)
    # Selected Unity files can themselves contain multiple serialized files.
    # Identity includes the stable serialized-file ordinal and the PathID.
    transforms, objects, names, parents, authored = {}, {}, {}, {}, {}
    component_trees, records = [], {}
    all_objects = list(env.objects)
    file_indices = {}
    game_transforms = {}
    for obj in all_objects:
        file_indices.setdefault(id(obj.assets_file), len(file_indices))
    for obj in all_objects:
        file_index = file_indices[id(obj.assets_file)]
        key = (file_index, obj.path_id)
        objects[key] = obj
        if obj.type.name != "Transform":
            continue
        tree = obj.read_typetree()
        transforms[key] = tree
        game = obj.assets_file.objects.get(tree.get("m_GameObject", {}).get("m_PathID"))
        names[key] = game.read_typetree().get("m_Name", "") if game else ""
        parent = tree.get("m_Father", {})
        parents[key] = (file_index, parent.get("m_PathID")) if parent.get("m_FileID") == 0 and parent.get("m_PathID") else None
        authored[key] = {"scale": _v3(tree["m_LocalScale"]),
                         "position": _v3(tree["m_LocalPosition"]),
                         "rotation": _matrix_euler(_quat_matrix(_quaternion(tree["m_LocalRotation"])))}
        game_transforms[(file_index, tree.get("m_GameObject", {}).get("m_PathID"))] = key
    if len(transforms) > MAX_EDITS:
        _fail("This model has too many transforms for persistent editing.")
    effective = copy.deepcopy(authored)
    conflicts = set()
    for obj in all_objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        if _class_name(obj, tree) != "LiveCoreMemberNodeScaling":
            continue
        if not tree.get("m_Enabled", True):
            _fail("Disabled saved body-setting components cannot be exported safely.")
        # The legacy viewer displays authored component values independently
        # of runtime activation. Refuse ambiguous persistence rather than save
        # geometry using a different baseline from the model on screen.
        current = game_transforms.get((file_indices[id(obj.assets_file)], tree.get("m_GameObject", {}).get("m_PathID")))
        seen = set()
        while current is not None:
            if current in seen:
                _fail("The saved body-setting hierarchy is circular.")
            seen.add(current)
            tr = transforms[current]
            go = objects.get((current[0], tr.get("m_GameObject", {}).get("m_PathID")))
            if go is not None and not go.read_typetree().get("m_IsActive", True):
                _fail("Inactive saved body-setting hierarchies cannot be exported safely.")
            current = parents.get(current)
        component_trees.append((obj, tree))
        for kind, field in _KINDS.items():
            for ordinal, wrapper in enumerate(tree.get(field, [])):
                entry = wrapper.get("data", wrapper)
                ptr = entry.get("target", {})
                key = (file_indices[id(obj.assets_file)], ptr.get("m_PathID")) if ptr.get("m_FileID") == 0 else None
                if key not in authored:
                    _fail("A saved body setting points outside its source model.")
                value = _v3(entry["scaledValue"])
                if kind == "scale" and any(abs(x) < 1e-8 for x in value):
                    _fail("A saved body setting contains zero scale.")
                rk = (key, kind)
                old = records.get(rk, [])
                if old and not _close(old[0][3], value):
                    conflicts.add(rk)
                records.setdefault(rk, []).append((obj, tree, entry, value, ordinal))
                effective[key][kind] = value
    return {"env": env, "objects": objects, "transforms": transforms, "names": names,
            "parents": parents, "authored": authored, "effective": effective,
            "components": component_trees, "records": records, "conflicts": conflicts, "file_indices": file_indices}


def _prune(now):
    for token in list(_SESSIONS):
        if _SESSIONS[token]["expires"] <= now and not _SESSIONS[token]["busy"].locked():
            del _SESSIONS[token]
    while len(_SESSIONS) > MAX_SESSIONS or sum(s["bytes"] for s in _SESSIONS.values()) > MAX_CACHE_BYTES:
        candidates = [key for key, session in _SESSIONS.items() if not session["busy"].locked()]
        if not candidates:
            break
        del _SESSIONS[candidates[0]]


def _session(token):
    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
        _fail("The body editing session is invalid. Open the model again.")
    with _LOCK:
        _prune(time.monotonic())
        value = _SESSIONS.get(token)
        if value is None:
            _fail("The body editing session expired. Open the original model again.")
        _SESSIONS.move_to_end(token)
        return value


def register_session(model_id, paths, rig, *, originals=None, origins=None,
                     archive_members=None, cache_dir=None, variants=None):
    """Bind exported node numbers to immutable, already-jailed input bytes.

    Must run while ZIP inputs still exist. Only caller-selected model inputs are
    writable; automatically discovered face/motion companions have no identity.
    ``cache_dir`` is accepted for the HTTP integration; originals are bounded in
    memory and copied to the export's originals folder when saving.
    """
    if not isinstance(model_id, str) or not _TOKEN.fullmatch(model_id):
        _fail("The model preview has no valid editing identity.")
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= 8:
        _fail("Choose between one and eight original model files.")
    if not isinstance(rig, dict) or rig.get("available") is not True:
        return {"available": False, "reason": "This model has no editable rig."}
    paths = [str(Path(p).resolve()) for p in paths]
    origins = origins or {p: p for p in paths}
    members = archive_members or {}
    originals = list(dict.fromkeys(str(Path(p).resolve()) for p in (originals or paths)))
    containers, total = [], 0
    for path in originals:
        raw = _read(path); total += len(raw)
        if total > MAX_SOURCE_BYTES:
            _fail("The selected originals exceed the body editing memory limit.")
        containers.append({"path": path, "name": Path(path).name, "raw": raw, "sha256": _sha(raw)})
    container_ids = {x["path"]: i for i, x in enumerate(containers)}
    variants = variants or {}
    if (not isinstance(variants, dict) or any(path not in container_ids or choice not in ("primary", "unmasked")
                                            for path, choice in variants.items())):
        _fail("The selected costume variant is invalid.")
    from . import viewer_physics, model_outlines
    sources, targets, public, physics_records, outline_records = [], {}, [], [], []
    for index, path in enumerate(paths):
        origin = str(Path(origins.get(path, path)).resolve())
        if origin not in container_ids:
            _fail("An editable model is not bound to a selected original.")
        member = members.get(path)
        container = containers[container_ids[origin]]
        if member is None and path != origin:
            _fail("An extracted model is missing its original archive member identity.")
        raw = container["raw"] if member is None else _read(path)
        source_hash = container["sha256"] if member is None else _sha(raw)
        if member is not None:
            with zipfile.ZipFile(io.BytesIO(container["raw"])) as archive:
                if archive.read(member) != raw:
                    _fail("The original costume archive changed while opening.")
        candidates = [b for b in rig.get("bones", []) if b.get("sourceIndex") == index and "transformId" in b]
        if candidates and any(b.get("sourceHash") != source_hash for b in candidates):
            _fail("The original model changed while its preview was opening. Open it again before editing.")
        info = _inspect(raw)
        sources.append({"raw": raw, "sha256": source_hash, "name": Path(path).name,
                        "container": container_ids[origin], "member": member})
        by_pid = {}
        for key in info["transforms"]:
            by_pid.setdefault(str(key[1]), []).append(key)
        for bone in candidates:
            node = bone.get("node")
            matches = by_pid.get(str(bone["transformId"]), [])
            if isinstance(node, bool) or not isinstance(node, int) or len(matches) != 1:
                continue
            key = matches[0]
            name = info["names"][key]
            baseline = _public_trs(info["effective"][key])
            authored_public = _public_trs(info["authored"][key])
            position_writable = str(node) not in (rig.get("sourcePositions") or {}) and node not in (rig.get("sourcePositions") or {})
            node_available = bool(info["components"]) and not info["conflicts"]
            method = "mesh" if name in _MV_SCALE_NAMES else "node" if name in _NODE_NAMES or "skirt" in name.lower() else "choose"
            if not node_available:
                method = "mesh" if method != "choose" else "choose"
            target = {"node": node, "name": name, "sourceIndex": index, "transformId": str(key[1]),
                      "serializedFile": key[0], "baseline": baseline,
                      "authored": authored_public, "recommendedMethod": method,
                      "methods": ["mesh"] + (["node"] if node_available else []),
                      "positionWritable": position_writable,
                      "reason": "observed_mv_scale_track" if name in _MV_SCALE_NAMES else "saved_node_setting" if method == "node" else "unverified_motion_coverage"}
            targets[node] = {**target, "key": key}
            public.append({k: copy.deepcopy(v) for k, v in target.items() if k not in ("serializedFile",)})
        physics_records.extend(viewer_physics.inspect_info(info, index, list(targets.values())))
        outline_records.extend(model_outlines.catalogue(info, index)["meshes"])
        if len(outline_records) > model_outlines.MAX_MESHES:
            _fail("The selected models have too many outline meshes.")
        if len(physics_records) > viewer_physics.MAX_COMPONENTS:
            _fail("The selected models have too many physics components.")
    if not targets:
        return {"available": False, "reason": "No original writable body nodes were found."}
    physics = {"available": bool(physics_records), "components": physics_records,
               "presets": viewer_physics.recommendations(),
               "recommendationSource": "sifas_breast_tuner.py / Upleg_SwingCollider_changer.py",
               "preview": "approximate_spring_sphere_capsule"}
    outlines = {"version": 1, "available": bool(outline_records), "meshes": outline_records}
    session = {"expires": time.monotonic() + SESSION_SECONDS, "bytes": total,
               "containers": containers, "sources": sources, "targets": targets,
               "physics": physics, "outlines": outlines,
               "variants": {str(container_ids[path]): choice for path, choice in variants.items()},
               "readOnlySkinJoints": {node for node in rig.get("readOnlySkinJoints", []) if node in targets},
               "busy": threading.Lock()}
    # Count expanded model copies too when archives retain compressed originals.
    session["bytes"] += sum(len(s["raw"]) for s in sources if s["member"] is not None)
    if session["bytes"] > MAX_SOURCE_BYTES:
        _fail("The selected originals expand beyond the body editing memory limit.")
    with _LOCK:
        _SESSIONS[model_id] = session
        _prune(time.monotonic())
        if model_id not in _SESSIONS:
            _fail("The body editor cache is busy. Finish saving another model first.")
    return {"available": True, "token": model_id, "version": VERSION, "nodes": public,
            "sourceFingerprint": _sha(json.dumps({
                "containers": [item["sha256"] for item in containers],
                "sources": [[item["container"], item["member"], item["sha256"]] for item in sources],
                "variants": session["variants"],
            }, sort_keys=True, separators=(",", ":")).encode()),
            "scope": "Observed MV tracks guide recommendations; other songs may differ.",
            "physics": copy.deepcopy(physics),
            "outlines": copy.deepcopy(outlines),
            "originalsPreserved": True, "supported": ["scale", "position", "rotation", "child_compensation", "blend_shape_geometry", "swing_physics", "outline_mask"]}


def mod_source_context(token):
    """Return immutable source identities for server-side mod packaging only.

    Raw bytes stay in this process; this structure must never be sent to HTTP
    clients. Automatically discovered preview companions are not included.
    """
    with _LOCK:
        session = _session(token)
        return {
            "model_id": token,
            "containers": [{key: container[key] for key in ("path", "name", "raw", "sha256")}
                           for container in session["containers"]],
            "sources": [{key: source[key] for key in ("name", "container", "member", "sha256")}
                        for source in session["sources"]],
            "variants": dict(session["variants"]),
            "physics": copy.deepcopy(session.get("physics", {})),
            "outlines": copy.deepcopy(session.get("outlines", {})),
            "nodes": [{key: copy.deepcopy(target[key]) for key in
                       ("node", "name", "sourceIndex", "transformId", "serializedFile", "baseline", "authored", "methods")}
                      for target in session["targets"].values()],
        }


def _node(session, value):
    if isinstance(value, bool) or not isinstance(value, int) or value not in session["targets"]:
        _fail("An edit refers to a node outside the original writable models.")
    return session["targets"][value]


def validate_state(token, state, *, allow_empty=False):
    session = _session(token)
    if not isinstance(state, dict) or set(state) - {"version", "edits", "savedSettingsEnabled", "unsupported", "compensationReference", "physics", "accessoryUnclip", "outlines"}:
        _fail("The body edit state contains unsupported settings.")
    try:
        encoded = json.dumps(state, allow_nan=False).encode()
    except (ValueError, TypeError):
        _fail("The body edit state contains invalid values.")
    if len(encoded) > MAX_STATE_BYTES:
        _fail("The body edit request is too large.")
    if type(state.get("version")) is not int or state["version"] != VERSION:
        _fail("The body edit recipe version is unsupported.")
    if state.get("savedSettingsEnabled", True) is not True:
        _fail("Enable the file's saved body settings before exporting edits.")
    unsupported = state.get("unsupported", [])
    if not isinstance(unsupported, list) or unsupported:
        _fail("Reset unsupported preview-only changes before exporting body edits.")
    accessory = None
    if "accessoryUnclip" in state:
        from .model_accessory_unclip import options, AccessoryUnclipError
        try:
            accessory = options(state["accessoryUnclip"])
        except AccessoryUnclipError as error:
            _fail(str(error))
    edits = state.get("edits")
    from . import viewer_physics
    try:
        physics = viewer_physics.validate_edits(session.get("physics", {}), state.get("physics", []))
        from . import model_outlines
        outlines = model_outlines.validate(session.get("outlines", {}), state.get("outlines", []))
    except ValueError as error:
        _fail(str(error))
    if not isinstance(edits, list) or not (0 if allow_empty or physics or outlines or accessory is not None or session.get("allowEmptySceneReset") else 1) <= len(edits) <= MAX_EDITS:
        _fail("Change at least one body property before saving.")
    out, seen = [], set()
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) - {"node", "method", "scale", "position", "rotation", "compensate", "compensationTargets"}:
            _fail("A body edit contains unsupported properties.")
        target = _node(session, edit.get("node")); node = target["node"]
        if node in seen:
            _fail("The same body node occurs more than once in this edit.")
        seen.add(node)
        method = edit.get("method", "auto")
        if method not in ("auto", "node", "mesh"):
            _fail("Choose automatic, saved node settings, or mesh baking.")
        comp = edit.get("compensate", False)
        if not isinstance(comp, bool):
            _fail("Child compensation must be on or off.")
        if method == "auto":
            if "position" in edit or "rotation" in edit:
                _fail("Choose a save method explicitly for position or rotation edits; MV compatibility differs by motion.")
            method = "mesh" if comp else target["recommendedMethod"]
        if method == "choose":
            _fail("Choose a save method for unverified body nodes in advanced settings.")
        if method not in target["methods"]:
            _fail("This model has no writable saved NodeScaling component; choose mesh baking.")
        row = {"node": node, "method": method, "compensate": comp}
        for kind in _KINDS:
            if kind in edit:
                row[kind] = _vector(edit[kind], scale=kind == "scale")
                if kind == "position" and not target["positionWritable"]:
                    _fail("Edit an attached model's original position in its own source model file.")
        if not any(kind in row for kind in _KINDS):
            _fail("A body edit must change scale, position, or rotation.")
        if comp:
            if method != "mesh" or "scale" not in row:
                _fail("Child compensation requires a mesh scale edit.")
            ids = edit.get("compensationTargets")
            if (not isinstance(ids, list) or not ids or len(ids) > MAX_EDITS or
                    any(type(ident) is not int for ident in ids) or len(set(ids)) != len(ids)):
                _fail("Choose valid child compensation targets.")
            for ident in ids:
                child = _node(session, ident)
                if child["sourceIndex"] != target["sourceIndex"] or ident == node:
                    _fail("Child compensation targets must belong to the edited model hierarchy.")
            row["compensationTargets"] = list(ids)
        elif edit.get("compensationTargets"):
            _fail("Enable child compensation before choosing its targets.")
        out.append(row)
    reference = []
    supplied = state.get("compensationReference", [])
    if not isinstance(supplied, list) or len(supplied) > MAX_EDITS:
        _fail("The compensation reference is invalid.")
    seen = set()
    for row in supplied:
        if not isinstance(row, dict) or set(row) != {"node", "scale", "position", "rotation"}:
            _fail("The compensation reference must contain complete local transforms.")
        target = _node(session, row["node"])
        if target["node"] in seen:
            _fail("Duplicate compensation reference nodes are unsupported.")
        seen.add(target["node"])
        reference.append({"node": target["node"], "scale": _vector(row["scale"], scale=True),
                          "position": _vector(row["position"]), "rotation": _vector(row["rotation"])})
    result = {"version": VERSION, "edits": sorted(out, key=lambda e: e["node"]),
              "savedSettingsEnabled": True, "unsupported": [], "compensationReference": reference}
    if physics:
        result["physics"] = physics
    if accessory is not None:
        result["accessoryUnclip"] = accessory
    if outlines:
        result["outlines"] = outlines
    return result


def has_changes(state):
    """Node, physics, outline and accessory-only recipes carry saved changes."""
    return bool(state.get("edits") or state.get("physics") or state.get("outlines")) or "accessoryUnclip" in state


def _worlds(local, parents):
    worlds, active = {}, set()
    def visit(key):
        if key in worlds:
            return worlds[key]
        if key in active or len(active) > 256:
            _fail("The original model has a circular transform hierarchy.")
        active.add(key)
        parent = parents.get(key)
        worlds[key] = visit(parent) @ local[key] if parent in local else local[key]
        active.remove(key)
        return worlds[key]
    for key in local:
        visit(key)
    return worlds


def _descendant(parents, child, parent):
    seen = set()
    while child in parents and child not in seen:
        seen.add(child); child = parents[child]
        if child == parent:
            return True
    return False


def _apply_node_record(info, key, kind, value):
    matches = info["records"].get((key, kind), [])
    if matches:
        for _, _, entry, _, _ in matches:
            # Re-anchor exactly the edited property; unrelated saved settings
            # retain their original origin/scaled endpoints byte-for-byte.
            entry["originValue"] = _d3(info["authored"][key][kind])
            entry["scaledValue"] = _d3(value)
        return
    components = info["components"]
    if len(components) != 1:
        _fail("This node has no unambiguous saved body-setting component.")
    obj, tree = components[0]
    if info["file_indices"][id(obj.assets_file)] != key[0]:
        _fail("Saved body settings cannot point into another serialized file.")
    tree.setdefault(_KINDS[kind], []).append({"target": {"m_FileID": 0, "m_PathID": key[1]},
          "originValue": _d3(info["authored"][key][kind]), "scaledValue": _d3(value)})


def _mesh_delta(info, current, desired):
    import numpy as np
    from .repo import ensure_repo_on_path
    ensure_repo_on_path()
    from sifas_mesh_baker import (stream_layout, read_attr, write_attr, get_skin,
                                 ATTR_POS, ATTR_NORMAL, ATTR_TANGENT, mat_from)
    changed, vertices_total, morph_total = [], 0, 0
    objects = info["objects"]
    renderer_meshes, renderer_objects = {}, {}
    for obj in info["env"].objects:
        if obj.type.name != "SkinnedMeshRenderer":
            continue
        tree = obj.read_typetree(); ptr = tree.get("m_Mesh", {})
        if ptr.get("m_FileID") != 0:
            continue
        key = (info["file_indices"][id(obj.assets_file)], ptr.get("m_PathID"))
        bones = []
        for p in tree.get("m_Bones", []):
            bk = (info["file_indices"][id(obj.assets_file)], p.get("m_PathID")) if p.get("m_FileID") == 0 else None
            if bk not in current:
                _fail("A skinned mesh uses external or missing bones; export is unavailable.")
            bones.append(bk)
        if key in renderer_meshes and renderer_meshes[key] != bones:
            _fail("A shared mesh has inconsistent skin bindings.")
        renderer_meshes[key] = bones
        renderer_objects.setdefault(key, []).append((obj, tree))
        if not bones:
            # The rigged viewer anchors zero-bind face surfaces to Head. Their
            # original game attachment is not a writable bone-weight array;
            # never bake only the other parts and silently leave the face out.
            for name in ("Head_Face", "Head"):
                anchors = [k for k, value in info["names"].items() if k[0] == key[0] and value == name]
                if len(anchors) == 1:
                    if not np.allclose(current[anchors[0]], desired[anchors[0]], atol=1e-9, rtol=1e-9):
                        _fail("This mesh edit would omit a rigid face attachment. Use saved node settings for this body part.")
                    break
    for key, bones in renderer_meshes.items():
        obj = objects.get(key)
        if obj is None or obj.type.name != "Mesh":
            _fail("A skinned mesh is missing from its source model.")
        tree = obj.read_typetree(); bps = tree.get("m_BindPose", [])
        if len(bps) != len(bones):
            _fail("A mesh's skin bindings do not match its skeleton.")
        base = np.asarray([current[b] @ mat_from(bp) for b, bp in zip(bones, bps)])
        goal = np.asarray([desired[b] @ mat_from(bp) for b, bp in zip(bones, bps)])
        if np.allclose(base, goal, atol=1e-9, rtol=1e-9):
            continue
        count, channels, stride, start, _ = stream_layout(tree)
        # The legacy vertex writer also accepts UNorm8 and clips into [0, 1].
        # That is unsuitable for arbitrary baked positions or signed rotated
        # normals/tangents. Keep packed inputs viewable and Node-editable, but
        # refuse a mesh write until a lossless format conversion is supported.
        for attribute, width, label, required in (
                (ATTR_POS, 3, "vertex positions", True),
                (ATTR_NORMAL, 3, "vertex normals", False),
                (ATTR_TANGENT, 4, "vertex tangents", False)):
            channel = channels[attribute] if attribute < len(channels) else {}
            dimension = channel.get("dimension", 0)
            if not required and dimension == 0:
                continue
            if channel.get("format") != 0 or dimension != width:
                _fail("Mesh baking requires Float32 " + label + "; use saved node settings for this model.")
        vertices_total += count
        if count <= 0 or vertices_total > MAX_VERTICES:
            _fail("The edited meshes exceed the persistent body editor vertex limit.")
        raw = bytearray(tree["m_VertexData"]["m_DataSize"])
        buf = np.frombuffer(raw, dtype=np.uint8)
        positions = read_attr(buf, ATTR_POS, channels, stride, start, count)
        weights, indices = get_skin(buf, tree, channels, stride, start, count)
        if positions is None or weights is None or indices is None:
            _fail("This mesh has unsupported vertex or skin data.")
        if not np.isfinite(positions).all() or not np.isfinite(weights).all() or (indices < 0).any() or (indices >= len(bones)).any():
            _fail("This mesh has invalid skin weights or bone indices.")
        # Bound all dense matrix work to a small vertex chunk. Original vertex,
        # weight and morph arrays remain bounded by the explicit export limits.
        normals = read_attr(buf, ATTR_NORMAL, channels, stride, start, count)
        tangents = read_attr(buf, ATTR_TANGENT, channels, stride, start, count)
        if ((normals is not None and not np.isfinite(normals).all()) or
                (tangents is not None and not np.isfinite(tangents).all())):
            _fail("The mesh contains invalid normal or tangent values.")
        moved = np.empty_like(positions, dtype=float)
        new_normals = np.empty_like(normals, dtype=float) if normals is not None else None
        new_tangents = np.array(tangents, dtype=float, copy=True) if tangents is not None else None
        morphs = tree.get("m_Shapes", {}).get("vertices", [])
        morph_total += len(morphs)
        if morph_total > MAX_MORPH_VERTICES:
            _fail("The edited blend shapes exceed the body editor limit.")
        for entry in morphs:
            index = entry.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count:
                _fail("A blend shape refers to an invalid mesh vertex.")
        ordered_morphs = sorted(morphs, key=lambda value: value["index"])
        full_weights = tree.get("m_Shapes", {}).get("fullWeights", [])
        if any(_number(value) <= 0 for value in full_weights):
            _fail("The mesh has invalid blend-shape frame weights.")
        default_weights = [abs(_number(value)) for _, render_tree in renderer_objects[key]
                           for value in (render_tree.get("m_BlendShapeWeights") or [])]
        # Authored defaults can be negative or greater than 100%. Preserve
        # their envelope too; do not assume that one full endpoint is enough.
        morph_factor = max(1., max(default_weights, default=0.) / min(full_weights, default=100.))
        if not math.isfinite(morph_factor):
            _fail("The authored blend-shape weights exceed the supported range.")
        cursor = 0
        envelope = np.zeros((count, 3))
        old_box = tree.get("m_LocalAABB", {})
        center, extent = np.asarray(_v3(old_box["m_Center"])), np.asarray(_v3(old_box["m_Extent"]))
        corners = np.asarray([[*(center + extent * np.asarray([x, y, z])), 1.]
                              for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)])
        low, high = np.full(3, np.inf), np.full(3, -np.inf)
        for begin in range(0, count, 8192):
            end = min(count, begin + 8192)
            selected, w = indices[begin:end], weights[begin:end, :, None, None]
            base_skin = (base[selected] * w).sum(axis=1)
            desired_skin = (goal[selected] * w).sum(axis=1)
            try:
                delta = np.linalg.solve(base_skin, desired_skin)
            except np.linalg.LinAlgError:
                _fail("A weighted skin frame is singular; this mesh cannot be baked safely.")
            if not np.isfinite(delta).all() or np.max(np.abs(delta)) > MAX_VALUE:
                _fail("The edited skin transform is invalid or too large.")
            points = np.column_stack((positions[begin:end], np.ones(end-begin)))
            moved[begin:end] = np.einsum("vij,vj->vi", delta, points)[:, :3]
            if (not np.isfinite(moved[begin:end]).all() or
                    np.max(np.abs(moved[begin:end])) > np.finfo(np.float32).max):
                _fail("Baking produced invalid mesh positions.")
            linear = delta[:, :3, :3]
            try:
                normal_matrix = np.linalg.inv(linear).transpose(0, 2, 1)
            except np.linalg.LinAlgError:
                _fail("The edited normal frame is singular.")
            normal_lengths, tangent_lengths = np.ones(end-begin), np.ones(end-begin)
            if normals is not None:
                values = np.einsum("vij,vj->vi", normal_matrix, normals[begin:end])
                normal_lengths = np.linalg.norm(values, axis=1)
                if (normal_lengths < 1e-12).any():
                    _fail("The mesh has zero or invalid transformed normals.")
                new_normals[begin:end] = values / normal_lengths[:, None]
            if tangents is not None:
                values = np.einsum("vij,vj->vi", linear, tangents[begin:end, :3])
                tangent_lengths = np.linalg.norm(values, axis=1)
                if (tangent_lengths < 1e-12).any():
                    _fail("The mesh has zero or invalid transformed tangents.")
                new_tangents[begin:end, :3] = values / tangent_lengths[:, None]
                new_tangents[begin:end, 3] *= np.where(np.linalg.det(linear) < 0, -1., 1.)
            while cursor < len(ordered_morphs) and ordered_morphs[cursor]["index"] < end:
                entry = ordered_morphs[cursor]; vertex = entry["index"]; offset = vertex-begin
                for field, matrix, norm in (("vertex", linear, None), ("normal", normal_matrix, normal_lengths),
                                             ("tangent", linear, tangent_lengths)):
                    if field not in entry:
                        continue
                    value = matrix[offset] @ np.asarray(_v3(entry[field]))
                    if norm is not None:
                        value /= norm[offset]
                    if not np.isfinite(value).all() or np.max(np.abs(value)) > np.finfo(np.float32).max:
                        _fail("The edited blend shape contains invalid values.")
                    entry[field] = _d3(value)
                    if field == "vertex":
                        envelope[vertex] += np.abs(value) * morph_factor
                cursor += 1
            # Preserve every transformed source-bound corner as well as the
            # combined morph envelope: do not shrink authored animation bounds.
            boxes = np.einsum("vij,kj->vki", delta, corners)[:, :, :3]
            low = np.minimum(low, boxes.min(axis=(0, 1)))
            high = np.maximum(high, boxes.max(axis=(0, 1)))
        write_attr(buf, moved, ATTR_POS, channels, stride, start, count)
        if new_normals is not None:
            write_attr(buf, new_normals, ATTR_NORMAL, channels, stride, start, count)
        if new_tangents is not None:
            write_attr(buf, new_tangents, ATTR_TANGENT, channels, stride, start, count)
        tree["m_VertexData"]["m_DataSize"] = bytes(raw)
        # Sum absolute deltas across all frames/channels. This is conservative
        # for simultaneous full positive/negative morphs, unlike bounding each
        # individual shape in isolation.
        low = np.minimum(low, (moved-envelope).min(axis=0))
        high = np.maximum(high, (moved+envelope).max(axis=0))
        if not np.isfinite([low, high]).all() or np.max(np.abs([low, high])) > np.finfo(np.float32).max:
            _fail("The edited morph bounds exceed the serialized mesh range.")
        tree["m_LocalAABB"] = {"m_Center": _d3((low+high)/2), "m_Extent": _d3((high-low)/2)}
        obj.save_typetree(tree)
        for renderer, render_tree in renderer_objects[key]:
            box = render_tree.get("m_AABB") or render_tree.get("m_LocalAABB")
            field = "m_AABB" if render_tree.get("m_AABB") is not None else "m_LocalAABB"
            if box is not None:
                rc, re = np.asarray(_v3(box["m_Center"])), np.abs(np.asarray(_v3(box["m_Extent"])))
                rlow, rhigh = np.minimum(low, rc-re), np.maximum(high, rc+re)
                render_tree[field] = {"m_Center": _d3((rlow+rhigh)/2), "m_Extent": _d3((rhigh-rlow)/2)}
                renderer.save_typetree(render_tree)
        changed.append({"mesh": tree.get("m_Name", "Mesh"), "vertices": count,
                        "morphVertices": len(morphs)})
    if not changed:
        _fail("The selected mesh changes do not influence any writable skinned vertices.")
    return changed


def _edit_frames(info, edits, targets, reference):
    import numpy as np
    if info["conflicts"]:
        _fail("Resolve conflicting saved NodeScaling records before exporting this model.")
    desired_values = copy.deepcopy(info["effective"])
    runtime_values = copy.deepcopy(info["effective"])
    reference_values = copy.deepcopy(info["effective"])
    for row in reference:
        target = targets[row["node"]]
        for kind in _KINDS:
            reference_values[target["key"]][kind] = _unity_values(kind, row[kind])
    mesh_edits = []
    for edit in edits:
        target = targets[edit["node"]]; key = target["key"]
        for kind in _KINDS:
            if kind not in edit:
                continue
            value = _unity_values(kind, edit[kind])
            desired_values[key][kind] = value
            if edit["method"] == "node":
                runtime_values[key][kind] = value
                _apply_node_record(info, key, kind, value)
            else:
                runtime_values[key][kind] = list(info["authored"][key][kind])
                # No component is required for pure mesh edits, but existing
                # overrides of the migrated property must become explicit noops.
                if (key, kind) in info["records"]:
                    _apply_node_record(info, key, kind, info["authored"][key][kind])
        if edit["method"] == "mesh":
            mesh_edits.append(edit)
    local_desired = {key: _matrix(v) for key, v in desired_values.items()}
    local_runtime = {key: _matrix(v) for key, v in runtime_values.items()}
    ref_local = {key: _matrix(v) for key, v in reference_values.items()}
    ref_world = _worlds(ref_local, info["parents"])
    corrections = {}
    def depth(edit):
        node = targets[edit["node"]]["key"]; n = 0
        while info["parents"].get(node) is not None:
            n += 1; node = info["parents"][node]
            if n > 256:
                _fail("The compensation hierarchy is circular.")
        return n
    for edit in sorted(mesh_edits, key=depth):
        if not edit.get("compensate"):
            continue
        key = targets[edit["node"]]["key"]
        ratio = np.asarray(desired_values[key]["scale"]) / np.asarray(reference_values[key]["scale"])
        if not np.isfinite(ratio).all() or (np.abs(ratio) < 1e-8).any():
            _fail("The edited child compensation cannot be inverted.")
        inverse = np.diag([*(1/ratio), 1.])
        for node in edit["compensationTargets"]:
            child = targets[node]["key"]
            if not _descendant(info["parents"], child, key):
                _fail("A compensation target is not a descendant of its edited bone.")
            relative = np.linalg.solve(ref_world[key], ref_world[child])
            correction = np.linalg.solve(relative, inverse @ relative)
            corrections[child] = correction @ corrections.get(child, np.eye(4))
    for child, correction in corrections.items():
        baseline = ref_local[child]
        local_desired[child] = baseline @ correction @ np.linalg.solve(baseline, local_desired[child])
    return runtime_values, local_runtime, local_desired, desired_values, mesh_edits


def _accessory_plan(info, edits, targets, frames, settings, read_only_keys=()):
    from .model_accessory_unclip import plan, AccessoryUnclipError
    _, runtime, desired, values, _ = frames
    writable = {target["key"] for target in targets.values()} - set(read_only_keys)
    try:
        result = plan(info, runtime, desired, values, settings, writable_keys=writable)
    except AccessoryUnclipError as error:
        _fail(str(error))
    except ModelEditError:
        raise
    except (ValueError, KeyError, IndexError, TypeError, OverflowError) as error:
        _fail("The accessory skin cannot be analyzed safely: " + str(error))
    if any(targets[edit["node"]]["key"] in result["corrections"] and "position" in edit for edit in edits):
        _fail("Reset explicit accessory-anchor position edits before applying automatic unclipping.")
    return result


def _edit_source(raw, edits, targets, reference, read_only_keys=(), *, accessory_unclip=None, accessory_original_raw=None):
    import numpy as np
    info = _inspect(raw)
    frames = _edit_frames(info, edits, targets, reference)
    runtime_values, local_runtime, local_desired, _, mesh_edits = frames
    runtime_world, desired_world = _worlds(local_runtime, info["parents"]), _worlds(local_desired, info["parents"])
    for key in read_only_keys:
        if not np.allclose(runtime_world[key], desired_world[key], atol=1e-9, rtol=1e-9):
            _fail("This mesh edit would omit automatically attached model parts. Use saved node settings or open those parts as explicit source files.")
    # Manual vertex/weight changes are inputs to the body bake, while this
    # optional correction follows the immutable source used by its live preview.
    accessory_info = _inspect(accessory_original_raw) if accessory_unclip is not None and accessory_original_raw is not None else info
    accessory = (_accessory_plan(accessory_info, edits, targets, frames, accessory_unclip, read_only_keys)
                 if accessory_unclip is not None else {"corrections": {}})
    if accessory.get("summary", {}).get("status") == "no_skin":
        _fail("This model's skinning cannot be checked safely. Turn accessory correction off before saving.")
    if not edits and not accessory["corrections"]:
        return raw, []
    meshes = _mesh_delta(info, runtime_world, desired_world) if mesh_edits else []
    for key, correction in accessory["corrections"].items():
        value = np.asarray(info["authored"][key]["position"]) + correction["export"]
        info["transforms"][key]["m_LocalPosition"] = _d3(value)
        info["objects"][key].save_typetree(info["transforms"][key])
    for obj, tree in info["components"]:
        obj.save_typetree(tree)
    result = info["env"].file.save(packer="original")
    # Re-read the real serialized bundle before exposing any completed output.
    checked = _inspect(result)
    for key, correction in accessory["corrections"].items():
        expected = np.asarray(info["authored"][key]["position"]) + correction["export"]
        if not np.allclose(checked["authored"][key]["position"], expected, atol=1e-5):
            _fail("The accessory anchor failed its saved-position reload check.")
    for edit in edits:
        target = targets[edit["node"]]; key = target["key"]
        for kind in _KINDS:
            if kind not in edit:
                continue
            expected = runtime_values[key][kind]
            actual = checked["effective"][key][kind]
            if kind == "rotation":
                if not np.allclose(_euler_matrix(expected), _euler_matrix(actual), atol=1e-5):
                    _fail("The saved rotation did not match its requested endpoint.")
            elif not np.allclose(expected, actual, atol=1e-5):
                _fail("The saved body endpoint failed reload validation.")
    return result, meshes


def accessory_preview(token, state):
    """Derive an overlay from immutable originals, never from an earlier overlay."""
    with _LOCK:
        session = _session(token)
        if not session["busy"].acquire(blocking=False):
            _fail("This model is busy. Wait for its current edit to finish.")
    if not _EXPORT_SLOT.acquire(blocking=False):
        session["busy"].release()
        _fail("Another model is being processed. Wait for it to finish.")
    try:
        state = validate_state(token, state, allow_empty=True)
        if "accessoryUnclip" not in state:
            return {"corrections": [], "summary": {"status": "disabled", "changed": 0}}
        output, summaries = [], []
        for index, source in enumerate(session["sources"]):
            targets = {node: row for node, row in session["targets"].items() if row["sourceIndex"] == index}
            selected = [row for row in state["edits"] if row["node"] in targets]
            reference = [row for row in state.get("compensationReference", []) if row["node"] in targets]
            info = _inspect(source["raw"])
            frames = _edit_frames(info, selected, targets, reference)
            read_only = [targets[node]["key"] for node in session["readOnlySkinJoints"] if node in targets]
            result = _accessory_plan(info, selected, targets, frames, state["accessoryUnclip"], read_only)
            inverse = {row["key"]: node for node, row in targets.items()}
            for key, correction in result["corrections"].items():
                delta = correction["preview"]
                output.append({"node": inverse[key], "delta": [-delta[0], *delta[1:]]})
            summaries.append({"source": index, **result["summary"]})
        statuses = {row["status"] for row in summaries}
        status = ("applied" if output else "nothing" if "nothing" in statuses else
                  "no_skin" if "no_skin" in statuses else "no_scaling")
        return {"corrections": output, "summary": {"status": status, "changed": len(output), "sources": summaries}}
    finally:
        _EXPORT_SLOT.release()
        session["busy"].release()


def _source_signature(session):
    return [{"name": s["name"], "sha256": s["sha256"], "container": s["container"], "member": s["member"]}
            for s in session["sources"]]


def _recipe(session, state):
    recipe = {"format": "elichika-viewer-body-edit", "version": VERSION,
              "sources": _source_signature(session),
              "originals": [{"name": c["name"], "sha256": c["sha256"]} for c in session["containers"]],
              "state": copy.deepcopy(state), "nodeIdentities": []}
    wanted = {e["node"] for e in state["edits"]} | {r["node"] for r in state.get("compensationReference", [])}
    for edit in state["edits"]:
        wanted.update(edit.get("compensationTargets", []))
    for node in sorted(wanted):
        t = session["targets"][node]
        recipe["nodeIdentities"].append({"node": node, "sourceIndex": t["sourceIndex"],
              "transformId": t["transformId"], "serializedFile": t["serializedFile"]})
    return recipe


def restore(token, recipe):
    session = _session(token)
    if not isinstance(recipe, dict) or set(recipe) - {"format", "version", "sources", "originals", "state", "nodeIdentities"}:
        _fail("Choose an original viewer body-edit recipe.")
    if recipe.get("format") != "elichika-viewer-body-edit" or recipe.get("version") != VERSION:
        _fail("The body-edit recipe format is unsupported.")
    source_values = recipe.get("sources")
    original_values = recipe.get("originals")
    def fingerprints(rows, keys):
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return None
        return [{key: row.get(key) for key in keys} for row in rows]
    if (fingerprints(source_values, ("sha256", "container", "member")) !=
            fingerprints(_source_signature(session), ("sha256", "container", "member")) or
            fingerprints(original_values, ("sha256",)) != [{"sha256": c["sha256"]} for c in session["containers"]]):
        _fail("This recipe belongs to different original model bytes. Open its preserved originals first.")
    identities = recipe.get("nodeIdentities")
    if not isinstance(identities, list) or len(identities) > MAX_EDITS:
        _fail("The recipe's node identities are invalid.")
    reverse = {(t["sourceIndex"], t["transformId"], t["serializedFile"]): node for node, t in session["targets"].items()}
    mapping = {}
    for row in identities:
        if not isinstance(row, dict) or set(row) != {"node", "sourceIndex", "transformId", "serializedFile"}:
            _fail("The recipe's node identity is unsupported.")
        key = (row["sourceIndex"], row["transformId"], row["serializedFile"])
        if key not in reverse or row["node"] in mapping:
            _fail("A recipe node no longer belongs to the original model.")
        mapping[row["node"]] = reverse[key]
    state = copy.deepcopy(recipe.get("state"))
    if not isinstance(state, dict):
        _fail("The recipe has no valid body edit state.")
    try:
        for edit in state.get("edits", []):
            edit["node"] = mapping[edit["node"]]
            if edit.get("compensationTargets"):
                edit["compensationTargets"] = [mapping[node] for node in edit["compensationTargets"]]
        for row in state.get("compensationReference", []):
            row["node"] = mapping[row["node"]]
    except (TypeError, KeyError):
        _fail("The recipe contains an unbound body node.")
    return validate_state(token, state)


def _safe_root(directory):
    root = Path(os.path.abspath(directory))
    for parent in (root, *root.parents):
        if parent.is_symlink():
            _fail("The body-edit output folder must not use symbolic links.")
    root.mkdir(parents=True, exist_ok=True)
    return root


def edit_source_state(session, index, state):
    """Apply validated node, accessory, physics and outline edits to one source."""
    source = session["sources"][index]
    selected = [edit for edit in state["edits"] if session["targets"][edit["node"]]["sourceIndex"] == index]
    blob, meshes = source["raw"], 0
    if selected or "accessoryUnclip" in state:
        reference = [row for row in state.get("compensationReference", []) if session["targets"][row["node"]]["sourceIndex"] == index]
        read_only = [session["targets"][node]["key"] for node in session["readOnlySkinJoints"]
                     if session["targets"][node]["sourceIndex"] == index]
        targets = {node: target for node, target in session["targets"].items() if target["sourceIndex"] == index}
        settings = {}
        if "accessoryUnclip" in state:
            settings["accessory_unclip"] = state["accessoryUnclip"]
            if "_accessory_original_raw" in source:
                settings["accessory_original_raw"] = source["_accessory_original_raw"]
        blob, meshes = _edit_source(blob, selected, targets, reference, read_only, **settings)
    if state.get("physics"):
        from . import viewer_physics
        blob = viewer_physics.apply_edits(blob, index, state["physics"], session["physics"])
    if state.get("outlines"):
        from . import model_outlines
        blob = model_outlines.apply_edits(blob, index, state["outlines"], session["outlines"], original_raw=source["raw"])
    return blob, meshes


def export(token, state, output_dir, *, log=lambda message: None, allow_empty=False):
    """Create new edited copies, preserved originals and a source-bound recipe.

    The HTTP caller owns authorization of output_dir. No request filename/path
    enters the recipe or export destination. Temporary results are exposed only
    after all bundle/ZIP reload and source-hash checks succeed.
    """
    with _LOCK:
        session = _session(token)
        if not session["busy"].acquire(blocking=False):
            _fail("This model is already being saved. Wait for it to finish.")
    if not _EXPORT_SLOT.acquire(blocking=False):
        session["busy"].release()
        _fail("Another model is being saved. Wait for it to finish.")
    temporary = None
    try:
        state = validate_state(token, state, allow_empty=allow_empty)
        for original in session["containers"]:
            if _sha(_read(original["path"])) != original["sha256"]:
                _fail("An original model changed after opening. Reopen it before saving.")
        replacements, summaries = {}, []
        for index, source in enumerate(session["sources"]):
            selected = [edit for edit in state["edits"] if session["targets"][edit["node"]]["sourceIndex"] == index]
            physics = [row for row in state.get("physics", []) if row["id"].split(":", 1)[0] == str(index)]
            outlines = [row for row in state.get("outlines", []) if row["id"].split(":", 1)[0] == str(index)]
            if not selected and not physics and not outlines and "accessoryUnclip" not in state:
                continue
            log("Saving body edits: " + source["name"])
            blob, meshes = edit_source_state(session, index, state)
            replacements[(source["container"], source["member"])] = blob
            summaries.append({"source": index, "nodes": len(selected), "meshes": meshes, "physics": len(physics), "outlines": len(outlines)})
        recipe = _recipe(session, state)
        root = _safe_root(output_dir)
        temporary = Path(tempfile.mkdtemp(prefix=".viewer-edit-", dir=root))
        originals_dir, models_dir = temporary / "originals", temporary / "models"
        originals_dir.mkdir(); models_dir.mkdir()
        output_names, preview_names, original_names = [], [], []
        used = set()
        for index, container in enumerate(session["containers"]):
            original_name = container["name"]
            name, ordinal = original_name, 1
            while name.casefold() in used:
                name = f"{index+1}-{ordinal}-" + original_name
                ordinal += 1
            used.add(name.casefold())
            original_path = originals_dir / name
            original_path.write_bytes(container["raw"])
            original_names.append(name)
            changed = [(member, blob) for (ci, member), blob in replacements.items() if ci == index]
            output = models_dir / name
            if any(member is None for member, _ in changed):
                if len(changed) != 1:
                    _fail("The source model has conflicting export identities.")
                output.write_bytes(changed[0][1])
            elif changed:
                updates = dict(changed)
                with zipfile.ZipFile(io.BytesIO(container["raw"])) as incoming, zipfile.ZipFile(output, "w") as outgoing:
                    outgoing.comment = incoming.comment
                    for entry in incoming.infolist():
                        value = updates.pop(entry.filename, None)
                        outgoing.writestr(copy.copy(entry), incoming.read(entry) if value is None else value)
                    if updates:
                        _fail("An edited model is missing from its original costume archive.")
                with zipfile.ZipFile(io.BytesIO(container["raw"])) as incoming, zipfile.ZipFile(output) as reloaded:
                    if incoming.namelist() != reloaded.namelist() or incoming.comment != reloaded.comment:
                        _fail("The edited costume archive failed reload validation.")
                    for entry in incoming.infolist():
                        key = (index, entry.filename)
                        expected = replacements[key] if key in replacements else incoming.read(entry)
                        if reloaded.read(entry.filename) != expected:
                            _fail("A costume archive member changed unexpectedly.")
            else:
                output.write_bytes(container["raw"])
            preview_names.append(name)
            if changed:
                output_names.append(name)
        (temporary / "recipe.json").write_text(json.dumps(recipe, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        # Detect another process changing the originals during a long save too.
        for original in session["containers"]:
            if _sha(_read(original["path"])) != original["sha256"]:
                _fail("An original model changed during saving. No output was published.")
        final = root / ("body-edit-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4))
        if final.exists():
            _fail("The output folder already exists. Save again to create a new copy.")
        temporary.rename(final); temporary = None
        recipe_path = str(final / "recipe.json")
        return {"recipe": recipe, "recipe_path": recipe_path,
                "output_paths": [str(final / "models" / name) for name in output_names] + [recipe_path],
                "preview_paths": [str(final / "models" / name) for name in preview_names],
                "original_paths": [str(final / "originals" / name) for name in original_names],
                "preview_variants": dict(session["variants"]), "original_variants": dict(session["variants"]),
                "summary": summaries, "originals_preserved": True}
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        session["busy"].release()
        _EXPORT_SLOT.release()
