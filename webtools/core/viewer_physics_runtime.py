"""Bind costume-dependent original game physics settings to verified sources.

The manager's serialized booleans are not the game's Initialize arguments.
Home/member and Live profiles are recovered from the original 3.12 code; the
Live costume exception is obtained only from a validated game import receipt.
An arbitrary filename or display name never establishes a costume identity.
"""
from pathlib import Path
from collections import OrderedDict
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import threading
import zipfile


_DERIVED_SCHEMA = 1
_MAX_DERIVED_BYTES = 256 * 1024
_MAX_DERIVED_DEPTH = 16
_FACTS = OrderedDict()
_FACTS_LOCK = threading.RLock()


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _proof(entry, containers):
    container = containers[entry["container"]]
    return {"path": str(Path(container["path"]).resolve()),
            "containerSha256": container["sha256"], "member": entry["member"],
            "sha256": entry["sha256"]}


def _entry_context(proof):
    """Read a bounded, immutable parent; receipt fields never authorize a file."""
    from . import viewer_mod_sources
    if (not isinstance(proof, dict) or set(proof) != {"path", "containerSha256", "member", "sha256"}
            or not isinstance(proof["path"], str) or len(proof["path"]) > 4096):
        raise ValueError("Invalid derived physics source proof.")
    raw = viewer_mod_sources._read(proof["path"])
    if _digest(raw) != proof["containerSha256"]:
        raise ValueError("The original physics source changed after transplanting.")
    model = raw
    member = proof["member"]
    if member is not None:
        if not isinstance(member, str) or len(member) > 4096:
            raise ValueError("Invalid derived physics archive member.")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            info = archive.getinfo(member)
            if not 0 < info.file_size <= viewer_mod_sources.MAX_BYTES:
                raise ValueError("Derived physics source is too large.")
            model = archive.read(info)
    if _digest(model) != proof["sha256"]:
        raise ValueError("The original physics model changed after transplanting.")
    container = {"path": proof["path"], "raw": raw, "sha256": proof["containerSha256"]}
    source = {"container": 0, "member": member, "raw": model, "sha256": proof["sha256"]}
    return {"containers": [container], "sources": [source]}


def _receipt_path(cache_root, path):
    # This folder is chosen by the server, never by a model or HTTP payload.
    root = Path(cache_root).resolve() / "viewer-derived-physics"
    if root.is_symlink():
        raise ValueError("The derived physics cache must use a real folder.")
    return root / (_digest(str(Path(path).resolve()).encode("utf-8")) + ".json")


def _read_receipt(cache_root, proof):
    path = _receipt_path(cache_root, proof["path"])
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_DERIVED_BYTES:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema") != _DERIVED_SCHEMA or data.get("path") != proof["path"]
            or data.get("sha256") != proof["containerSha256"] or not isinstance(data.get("sources"), list)
            or len(data["sources"]) > 8 or any(not isinstance(row, dict) for row in data["sources"])):
        return None
    rows = [row for row in data["sources"] if row.get("member") == proof["member"]
            and row.get("sha256") == proof["sha256"]]
    return rows[0] if len(rows) == 1 else None


def _write_receipts(cache_root, path, rows):
    from . import viewer_mod_sources
    path = str(Path(path).resolve())
    raw = viewer_mod_sources._read(path)
    target = _receipt_path(cache_root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema": _DERIVED_SCHEMA, "path": path, "sha256": _digest(raw), "sources": rows}
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > _MAX_DERIVED_BYTES:
        raise ValueError("The derived physics receipt is too large.")
    descriptor, temporary = tempfile.mkstemp(prefix=".physics-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _source_settings(record, repo_root):
    from . import game_models
    database = game_models._readonly(Path(repo_root) / "assets/db" / record["region"] / "masterdata.db")
    try:
        row = database.execute("SELECT skirtsafe_disable FROM m_suit_custom3d WHERE suit_master_id=?",
                               (record["suit_id"],)).fetchone()
    finally:
        database.close()
    flag = row[0] if row is not None and row[0] is not None else 0
    if type(flag) is not int or flag not in (0, 1):
        return None
    owner = record.get("owner")
    return {"default": bool(flag), "components": {}, "derived": False, "operations": [],
            "owner": {"character_id": owner, "suit_id": record["suit_id"], "region": record["region"]}
                     if type(owner) is int and owner > 0 else None}


def _resolve(proof, *, repo_root, cache_root, active=None, memo=None):
    """Resolve receipts recursively, rechecking originals instead of trusting flags."""
    from . import viewer_mod_flow, viewer_mod_sources
    active = set() if active is None else active
    memo = {} if memo is None else memo
    identity = (proof["path"], proof["containerSha256"], proof["member"], proof["sha256"])
    if identity in active or len(active) >= _MAX_DERIVED_DEPTH:
        return None
    if identity in memo:
        return memo[identity]
    if len(memo) >= 64:
        return None
    memo[identity] = None
    context = _entry_context(proof)
    bindings = viewer_mod_sources.game_context(context, repo_root,
        receipts=viewer_mod_flow.cached_receipts(context, cache_root))
    if bindings:
        result = _source_settings(bindings[0]["record"], repo_root)
        if result is not None:
            result["ids"] = _physics_ids(context["sources"][0]["raw"])
        memo[identity] = result
        return result
    row = _read_receipt(cache_root, proof)
    if row is None:
        return None
    active = active | {identity}
    parents = row.get("parents")
    if not isinstance(parents, list) or not 1 <= len(parents) <= 2:
        return None
    resolved = [_resolve(parent, repo_root=repo_root, cache_root=cache_root, active=active, memo=memo) for parent in parents]
    origins = row.get("components")
    if not isinstance(origins, list) or len(origins) > 512:
        return None
    flags, seen = {}, set()
    identities = _physics_ids(context["sources"][0]["raw"])
    for origin in origins:
        if not isinstance(origin, dict) or set(origin) != {"id", "parent", "sourceId"}:
            return None
        index = origin["parent"]
        if (type(index) is not int or not 0 <= index < len(resolved) or not isinstance(origin["id"], str)
                or origin["id"] in seen):
            return None
        seen.add(origin["id"])
        parent = resolved[index]
        if parent is None or origin["id"] not in identities or origin["sourceId"] not in parent["ids"]:
            continue
        flag = parent["components"].get(origin["sourceId"], parent["default"])
        if type(flag) is bool:
            flags[origin["id"]] = flag
    owner = resolved[0]["owner"] if resolved[0] else None
    operation = row.get("operation")
    operations = row.get("operations", [operation])
    if (operation not in ("costume", "part", "lower", "edit") or not isinstance(operations, list)
            or not 1 <= len(operations) <= 4
            or any(value not in ("costume", "part", "lower", "edit") for value in operations)):
        return None
    operations = list(dict.fromkeys([value for parent in resolved if parent for value in parent["operations"]]
                                    + operations))
    result = {"default": None, "components": flags, "derived": True, "owner": owner,
              "operations": operations, "ids": identities}
    memo[identity] = result
    return result


def _source_proofs(context):
    from . import viewer_mod_sources
    containers, entries = viewer_mod_sources._snapshots(context)
    return [_proof(entry, containers) for entry in entries]


def _physics_ids(raw):
    from . import model_edits, viewer_physics
    digest = _digest(raw)
    with _FACTS_LOCK:
        if digest in _FACTS:
            _FACTS.move_to_end(digest)
            return _FACTS[digest]
    info = model_edits._inspect(raw)
    bones = [{"sourceIndex": 0, "serializedFile": key[0], "transformId": str(key[1]), "node": index}
             for index, key in enumerate(info["transforms"])]
    result = frozenset(f"{row['serializedFile']}:{row['componentId']}" for row in viewer_physics.inspect_info(info, 0, bones)
                       if row["kind"] == "bone")
    with _FACTS_LOCK:
        _FACTS[digest] = result
        while len(_FACTS) > 8:
            _FACTS.popitem(last=False)
    return result


def record_transplant(output_path, *, wearer_context, wearer_source, donor_path, donor_member, donor_sha256,
                      operation, component_origins, repo_root, cache_root):
    """Persist only source-bound runtime provenance; never an original-game identity."""
    from . import viewer_mod_sources
    if operation not in ("costume", "part", "lower") or type(wearer_source) is not int:
        raise ValueError("Invalid derived physics operation.")
    proofs = _source_proofs(wearer_context)
    if not 0 <= wearer_source < len(proofs) or not isinstance(component_origins, list) or len(component_origins) > 512:
        raise ValueError("Invalid derived physics source mapping.")
    wearer = proofs[wearer_source]
    donor_raw = viewer_mod_sources._read(donor_path)
    if _digest(donor_raw) != donor_sha256:
        raise ValueError("The donor changed after the transplanted model was prepared.")
    donor_model = donor_raw
    if donor_member is not None:
        with zipfile.ZipFile(io.BytesIO(donor_raw)) as archive:
            info = archive.getinfo(donor_member)
            if not 0 < info.file_size <= viewer_mod_sources.MAX_BYTES:
                raise ValueError("The donor physics source is too large.")
            donor_model = archive.read(info)
    donor = {"path": str(Path(donor_path).resolve()), "containerSha256": _digest(donor_raw),
             "member": donor_member, "sha256": _digest(donor_model)}
    raw = viewer_mod_sources._read(output_path)
    member = wearer["member"]
    output_model = raw
    if member is not None:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            output_model = archive.read(member)
    output_ids = _physics_ids(output_model)
    source_ids = [_physics_ids(_entry_context(wearer)["sources"][0]["raw"]), _physics_ids(donor_model)]
    mapped, seen = [], set()
    for origin in component_origins:
        if not isinstance(origin, dict):
            raise ValueError("Invalid transplanted physics component mapping.")
        source = {"wearer": 0, "donor": 1}.get(origin.get("source"))
        key = f"{origin.get('serializedFile')}:{origin.get('componentId')}"
        original = f"{origin.get('sourceSerializedFile')}:{origin.get('sourceComponentId')}"
        if source is None or key not in output_ids or original not in source_ids[source] or key in seen:
            raise ValueError("The transplanted physics component no longer matches its source.")
        seen.add(key)
        mapped.append({"id": key, "parent": source, "sourceId": original})
    row = {"member": member, "sha256": _digest(output_model), "operation": operation,
           "parents": [wearer, donor], "components": mapped}
    _write_receipts(cache_root, output_path, [row])
    return {"derived": True, "mappedComponents": len(mapped)}


def inherit_export(context, preview_paths, *, repo_root, cache_root):
    """Carry source-bound component identities through a normal edit/save copy."""
    from . import viewer_mod_sources
    proofs = _source_proofs(context)
    if not isinstance(preview_paths, (list, tuple)) or len(preview_paths) != len(context["containers"]):
        raise ValueError("Saved physics sources do not match their original containers.")
    grouped = {}
    for index, proof in enumerate(proofs):
        source = context["sources"][index]
        try:
            result = _resolve(proof, repo_root=repo_root, cache_root=cache_root)
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, zipfile.BadZipFile):
            # Invalid provenance never turns an otherwise valid edited copy
            # into an original game asset or blocks saving that copy.
            continue
        if result is None:
            continue
        destination = preview_paths[source["container"]]
        raw = viewer_mod_sources._read(destination)
        if proof["member"] is not None:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                raw = archive.read(proof["member"])
        original = _physics_ids(_entry_context(proof)["sources"][0]["raw"])
        current = _physics_ids(raw)
        previous = _read_receipt(cache_root, proof) if result["derived"] else None
        if previous is not None:
            # Ordinary saves preserve component identities. Reuse their
            # verified original parents instead of adding one receipt layer
            # per click on Save and eventually exhausting the recursion bound.
            parents = previous["parents"]
            components = [dict(row) for row in previous["components"] if row["id"] in current and row["id"] in original]
        else:
            parents = [proof]
            components = [{"id": key, "parent": 0, "sourceId": key} for key in current if key in original]
        grouped.setdefault(str(destination), []).append({"member": proof["member"], "sha256": _digest(raw),
            "operation": "edit", "operations": list(dict.fromkeys(result["operations"] + ["edit"])),
            "parents": parents, "components": components})
    for destination, rows in grouped.items():
        _write_receipts(cache_root, destination, rows)
    return {"derivedOutputs": len(grouped)}


def owner_for_context(context, *, repo_root, cache_root):
    """A target hint only; this must never enable native counterpart auto-pairing."""
    owners = []
    memo = {}
    try:
        proofs = _source_proofs(context)
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile):
        return None
    for proof in proofs:
        try:
            value = _resolve(proof, repo_root=repo_root, cache_root=cache_root, memo=memo)
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, zipfile.BadZipFile):
            continue
        if value and value["owner"]:
            owners.append({**value["owner"], "derived": value["derived"], "operations": value["operations"]})
    if not owners or len({row["character_id"] for row in owners}) != 1:
        return None
    return owners[0]


def motion_settings(*, repo_root, record):
    """The original song-specific LateUpdate switch, independent of costume."""
    if record.get("category") != "mv":
        return {"profile": "navi", "safeSwingBoneKnown": True, "safeSwingBone": False}
    result = {"profile": "live", "liveId": record.get("live_id"),
              "safeSwingBoneKnown": False, "safeSwingBone": None}
    if (record.get("region") not in ("gl", "jp") or type(record.get("live_id")) is not int or
            not 0 < record["live_id"] < 10 ** 12):
        return result
    from . import game_models
    try:
        database = game_models._readonly(Path(repo_root) / "assets/db" / record["region"] / "masterdata.db")
        try:
            row = database.execute("SELECT safe_swing_bone FROM m_live_visible_definition WHERE live_m_id=?",
                                   (record["live_id"],)).fetchone()
        finally:
            database.close()
        value = row[0] if row is not None and row[0] is not None else 0
        if type(value) is int and value in (0, 1):
            result.update(safeSwingBoneKnown=True, safeSwingBone=bool(value))
    except (OSError, ValueError, TypeError, sqlite3.Error):
        pass
    return result


def describe(context, physics, *, repo_root, cache_root):
    indices = sorted({row["sourceIndex"] for row in physics.get("managers", [])})
    result = {"profile": "sifas-3.12.0", "sources": [
        {"sourceIndex": index, "known": False, "suitId": None, "skirtsafeDisable": None}
        for index in indices]}
    if not indices:
        return result
    from . import game_models, viewer_mod_flow, viewer_mod_sources
    try:
        bindings = viewer_mod_sources.game_context(context, repo_root,
            receipts=viewer_mod_flow.cached_receipts(context, cache_root))
    except (ImportError, OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        bindings = []
    indexed = {row["sourceIndex"]: row for row in result["sources"]}
    seen = set()
    for binding in bindings:
        index, record = binding["source"], binding["record"]
        if index not in indexed or index in seen:
            continue
        seen.add(index)
        try:
            database = game_models._readonly(Path(repo_root) / "assets/db" / record["region"] / "masterdata.db")
            try:
                row = database.execute("SELECT skirtsafe_disable FROM m_suit_custom3d WHERE suit_master_id=?",
                                       (record["suit_id"],)).fetchone()
            finally:
                database.close()
            # The original nullable lookup defaults an absent/NULL value to
            # false. Invalid data remains unknown, not a guessed false value.
            value = row[0] if row is not None and row[0] is not None else 0
            if type(value) is not int or value not in (0, 1):
                continue
            indexed[index].update(known=True, suitId=record["suit_id"], region=record["region"],
                                  skirtsafeDisable=bool(value))
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
            continue
    # A modified costume is not an original game import. Its separately stored
    # derivation can nevertheless retain the caller's physics flags, including
    # different source settings within one mixed wearer/donor manager.
    try:
        proofs = _source_proofs(context)
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile):
        return result
    flags, owners, memo = {}, [], {}
    for index, source in indexed.items():
        if source["known"] or index >= len(proofs):
            continue
        try:
            resolved = _resolve(proofs[index], repo_root=repo_root, cache_root=cache_root, memo=memo)
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, zipfile.BadZipFile):
            continue
        if resolved is None or not resolved["derived"]:
            continue
        component_flags = {f"{index}:{ident}": value for ident, value in resolved["components"].items()}
        flags.update(component_flags)
        managed = {ident for manager in physics.get("managers", []) if manager["sourceIndex"] == index
                   for ident in (manager.get("bones") or []) + (manager.get("lodBones") or [])}
        complete = bool(managed) and all(type(component_flags.get(ident)) is bool for ident in managed)
        unique = {component_flags[ident] for ident in managed if ident in component_flags}
        source.update(derived=True, known=complete, skirtsafeDisable=next(iter(unique)) if complete and len(unique) == 1 else None,
                      operations=resolved["operations"], componentFlags=component_flags)
        if resolved["owner"]:
            owners.append({**resolved["owner"], "derived": True, "operations": resolved["operations"]})
    if flags:
        result["skirtsafeDisableByComponent"] = flags
    if owners and len({row["character_id"] for row in owners}) == 1:
        result["derivedOwner"] = owners[0]
    return result
