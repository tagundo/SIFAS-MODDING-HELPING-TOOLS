"""Portable identity-only UnityFS isolation shared by scene and clone tools.

The isolation implementation is copied without semantic changes from the
reviewed parent helper; no geometry or NodeScaling operation belongs here.
"""
import hashlib
import copy
import re

_CAB = re.compile(r"^CAB-[0-9a-f]{32}$", re.IGNORECASE)


def _bundle(data):
    import UnityPy
    if not data.startswith(b"UnityFS\0"):
        raise ValueError("costume model is not a UnityFS bundle")
    env = UnityPy.load(data)
    files = list(env.files.values())
    if len(files) != 1 or type(files[0]).__name__ != "BundleFile":
        raise ValueError("costume model must contain one UnityFS bundle")
    bundle = files[0]
    serialized = [f for f in bundle.files.values() if hasattr(f, "objects")]
    if not serialized or any(not _CAB.fullmatch(f.name) for f in serialized):
        raise ValueError("costume model has an unsupported serialized-file identity")
    return env, bundle, serialized


def _cab_names(data):
    _, _, files = _bundle(data)
    return [f.name for f in files]


def _cab_mapping(names, namespace):
    return {name.lower(): "CAB-" + hashlib.sha256(
        (namespace + ":" + name.lower()).encode()).hexdigest()[:32] for name in names}


def _runtime_name(namespace, serialized_name, original_name):
    return "clone_" + hashlib.sha256((namespace + ":" + serialized_name + ":" +
        str(original_name)).encode()).hexdigest() + ".unity3d"


def _runtime_names(data, namespace):
    _, _, files = _bundle(data)
    result = {}
    for sf in files:
        for obj in sf.objects.values():
            if obj.type.name == "AssetBundle":
                tree = obj.read_typetree()
                if tree.get("m_AssetBundleName"):
                    original = tree["m_AssetBundleName"]
                    result[original] = _runtime_name(namespace, sf.name, original)
    return result


def isolate_bundle(data, namespace, _identities=None, _bundle_names=None):
    """Copy a model without sharing its serialized assets or streamed resources.

    Only CAB identities and AssetBundle runtime names change. Object/path ids,
    prefab load paths, meshes, materials and animation data are preserved. CABs
    have a fixed width, so resource paths can be replaced without deserializing
    unknown MonoBehaviours or changing any binary field sizes/offsets.
    """
    _, bundle, serialized = _bundle(data)
    identities = dict(_identities or {})
    identities.update(_cab_mapping([f.name for f in serialized], namespace))

    def rename(value):
        # Archive paths can use lower-case CAB names while the directory uses
        # upper-case CAB. Do not rename external shared dependencies.
        for old, new in identities.items():
            value = re.sub(re.escape(old), lambda match: (
                new.lower() if match.group().startswith("cab-") else new), value,
                flags=re.IGNORECASE)
        return value

    found_bundle = False
    for sf in serialized:
        for external in sf.externals:
            external.path = rename(external.path)
        for obj in sf.objects.values():
            raw = obj.get_raw_data()
            updated = raw
            for old, new in identities.items():
                updated = re.sub(re.escape(old.encode()), lambda match: (
                    new.lower().encode() if match.group().startswith(b"cab-") else new.encode()),
                    updated, flags=re.IGNORECASE)
            if updated != raw:
                obj.set_raw_data(updated)
            if obj.type.name == "AssetBundle":
                tree = obj.read_typetree()
                for field in ("m_Name", "m_AssetBundleName"):
                    if field in tree:
                        tree[field] = _runtime_name(namespace, sf.name, tree[field])
                if _bundle_names:
                    tree["m_Dependencies"] = [_bundle_names.get(name, name)
                                               for name in tree.get("m_Dependencies", [])]
                obj.save_typetree(tree)
                found_bundle = True
        sf.name = rename(sf.name)
        sf.mark_changed()
    if not found_bundle:
        raise ValueError("costume model has no AssetBundle metadata")
    bundle.files = {rename(name): value for name, value in bundle.files.items()}
    result = bundle.save(packer="lz4")
    # Parse again before registering anything; malformed outputs must never
    # become downloadable models. No texture decoding/recompression is needed.
    _, _, copied = _bundle(result)
    if sorted(len(f.objects) for f in copied) != sorted(len(f.objects) for f in serialized):
        raise ValueError("costume bundle object count changed while isolating it")
    return result


def verify_identity_only(original, isolated, namespace, _identities=None, _bundle_names=None):
    """Reject any change outside the reviewed CAB/stream/runtime-name contract.

    Raw object payloads are compared after replacing only fixed-width CAB
    strings. AssetBundle metadata is compared as a full tree, with only its two
    runtime identity fields excepted. Stream bytes, IDs, native targets and
    external references are checked independently; no image decoding is used.
    """
    _, source_bundle, sources = _bundle(original)
    _, target_bundle, targets = _bundle(isolated)
    if len(sources) != len(targets):
        raise ValueError("Identity isolation changed serialized file count.")
    identities = dict(_identities or {})
    identities.update(_cab_mapping([file.name for file in sources], namespace))

    def rename(raw):
        for old, new in identities.items():
            raw = re.sub(re.escape(old.encode()), lambda match: (
                new.lower().encode() if match.group().startswith(b"cab-") else new.encode()),
                raw, flags=re.IGNORECASE)
        return raw

    def named(name):
        return rename(name.encode()).decode()

    if set(target_bundle.files) != {named(name) for name in source_bundle.files}:
        raise ValueError("Identity isolation changed the bundle file set.")
    streams = 0
    for name, resource in source_bundle.files.items():
        if hasattr(resource, "objects"):
            continue
        if bytes(resource.bytes) != bytes(target_bundle.files[named(name)].bytes):
            raise ValueError("Identity isolation changed streamed resource bytes.")
        streams += 1
    objects = 0
    for source in sources:
        target = target_bundle.files[named(source.name)]
        if int(source.target_platform) != int(target.target_platform) or set(source.objects) != set(target.objects):
            raise ValueError("Identity isolation changed the native platform or object identities.")
        if [(str(row.guid), row.type, named(row.path)) for row in source.externals] != [
                (str(row.guid), row.type, row.path) for row in target.externals]:
            raise ValueError("Identity isolation changed an external dependency.")
        for path_id, obj in source.objects.items():
            other = target.objects[path_id]
            if obj.type.name != other.type.name:
                raise ValueError("Identity isolation changed an object type.")
            if obj.type.name == "AssetBundle":
                expected = copy.deepcopy(obj.read_typetree())
                # The known helper's only tree writes are these two fields.
                for field in ("m_Name", "m_AssetBundleName"):
                    if field in expected:
                        expected[field] = _runtime_name(namespace, source.name, expected[field])
                if _bundle_names:
                    expected["m_Dependencies"] = [_bundle_names.get(name, name)
                                                   for name in expected.get("m_Dependencies", [])]
                if expected != other.read_typetree():
                    raise ValueError("Identity isolation changed non-identity AssetBundle metadata.")
            elif rename(obj.get_raw_data()) != other.get_raw_data():
                raise ValueError("Identity isolation changed non-identity object data.")
            objects += 1
    return {"source_sha256": hashlib.sha256(original).hexdigest(),
            "execution_sha256": hashlib.sha256(isolated).hexdigest(),
            "source_cabs": [file.name for file in sources],
            "execution_cabs": [file.name for file in targets],
            "verified_objects": objects, "verified_streams": streams,
            "all_nonidentity_data_preserved": True}


def isolate_verified_bundle(original, namespace):
    isolated = isolate_bundle(original, namespace)
    return isolated, verify_identity_only(original, isolated, namespace)
