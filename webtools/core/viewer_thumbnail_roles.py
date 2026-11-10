"""Headless thumbnail roles proved by original component pointers.

Mesh/game-object names are display labels only. A costume may legitimately use
names such as Face_Print or Hair_Ribbon; neither makes it facial geometry.
"""
from collections import defaultdict
import ntpath
from pathlib import Path

from . import model_viewer

_NAMESPACE = "LLAS.Components.Members"
_ASSEMBLY = "Assembly-CSharp.dll"
_COMPONENTS = {"MemberFace": "face", "MemberHair": "hair", "BodyPartManager": "head"}


def excluded_renderers(scene, paths):
    """Return source mesh/renderer identities within verified native head roots.

    ``scene`` is an already loaded immutable model_viewer._Scene. ``paths`` has
    the same source order used by prepare/GLB export. Unknown/ambiguous pointers
    preserve geometry. No filename, mesh label, shader label or skin influence
    alone can authorize removal of a costume renderer.
    """
    objects = tuple(scene.env.objects)
    files = {}
    source_files = defaultdict(dict)
    source_indices = {str(Path(path).resolve()): index for index, path in enumerate(paths)}
    for obj in objects:
        model_viewer._remaining(scene.deadline)
        files[id(obj.assets_file)] = obj.assets_file
        source = model_viewer._source_path(obj)
        source_files[source].setdefault(id(obj.assets_file), len(source_files[source]))
    by_name = defaultdict(list)
    for file in files.values():
        by_name[ntpath.basename(file.name).casefold()].append(file)

    def tree(obj):
        if obj is None:
            return None
        try:
            return scene.tree(obj)
        except Exception:
            # Unrelated custom scripts need not have a supported type tree.
            # Keep their geometry, but never hide deadline exhaustion.
            model_viewer._remaining(scene.deadline)
            return None

    def resolve(owner, pointer, expected=None):
        if (not isinstance(pointer, dict) or type(pointer.get("m_PathID")) is not int
                or not pointer["m_PathID"] or type(pointer.get("m_FileID", 0)) is not int):
            return None
        file_id = pointer.get("m_FileID", 0)
        if file_id == 0:
            target = owner.assets_file
        elif 1 <= file_id <= len(owner.assets_file.externals):
            name = ntpath.basename(owner.assets_file.externals[file_id - 1].path).casefold()
            matches = by_name.get(name, ())
            if len(matches) != 1:
                return None
            target = matches[0]
        else:
            return None
        obj = target.objects.get(pointer["m_PathID"])
        return obj if obj is not None and (expected is None or obj.type.name == expected) else None

    def script_class(component, value=None):
        if component is None or component.type.name != "MonoBehaviour":
            return None
        value = value if value is not None else tree(component)
        if not isinstance(value, dict):
            return None
        script = resolve(component, value.get("m_Script"), "MonoScript")
        metadata = tree(script)
        if (not isinstance(metadata, dict) or metadata.get("m_Namespace") != _NAMESPACE
                or metadata.get("m_AssemblyName") != _ASSEMBLY):
            return None
        name = metadata.get("m_ClassName")
        return name if isinstance(name, str) else None

    transforms = defaultdict(list)
    filters = defaultdict(list)
    for obj in objects:
        if obj.type.name not in ("Transform", "MeshFilter"):
            continue
        value = tree(obj)
        game = resolve(obj, value.get("m_GameObject"), "GameObject") if isinstance(value, dict) else None
        if game is not None:
            (transforms if obj.type.name == "Transform" else filters)[model_viewer._key(game)].append(obj)

    def transform(game):
        found = transforms.get(model_viewer._key(game), ())
        return found[0] if len(found) == 1 else None

    def identity(obj):
        source = model_viewer._source_path(obj)
        index = source_indices.get(source)
        file = source_files.get(source, {}).get(id(obj.assets_file))
        return {"source": index, "file": file, "id": str(obj.path_id)} if index is not None and file is not None else None

    scopes = []

    def scope(component, game, role, field):
        if game is None or game.type.name != "GameObject":
            return
        root = transform(game)
        component_id, root_id = identity(component), identity(game)
        if root is None or component_id is None or root_id is None:
            return
        scopes.append((model_viewer._key(root), role, {"component": component_id,
            "class": script_class(component), "namespace": _NAMESPACE, "assembly": _ASSEMBLY,
            "field": field, "root": root_id}))

    for component in objects:
        if component.type.name != "MonoBehaviour":
            continue
        value = tree(component)
        kind = script_class(component, value)
        if kind not in _COMPONENTS:
            continue
        if kind in ("MemberFace", "MemberHair"):
            scope(component, resolve(component, value.get("m_GameObject"), "GameObject"),
                  _COMPONENTS[kind], "m_GameObject")
            continue
        # Native body head renderers live below the exact original headAll
        # GameObject. The body renderer can use Head as a skin joint and still
        # belongs outside this subtree, so skin weights are not a role test.
        head = resolve(component, value.get("headAll"), "GameObject")
        field = "headAll"
        if head is None:
            head, field = resolve(component, value.get("head"), "GameObject"), "head"
        scope(component, head, "head", field)
        # The face can live in another serialized CAB. Recheck its exact script
        # identity rather than accepting a path-ID collision or a label.
        for field, expected, role in (("face", "MemberFace", "face"), ("hair", "MemberHair", "hair")):
            target = resolve(component, value.get(field), "MonoBehaviour")
            if script_class(target) == expected:
                target_tree = tree(target)
                scope(target, resolve(target, target_tree.get("m_GameObject"), "GameObject"), role, "m_GameObject")

    def ancestors(game):
        result, seen = set(), set()
        node = transform(game)
        while node is not None:
            model_viewer._remaining(scene.deadline)
            key = model_viewer._key(node)
            if key in seen or len(seen) >= 256:
                return set()
            seen.add(key)
            result.add(key)
            value = tree(node)
            if not isinstance(value, dict):
                return set()
            parent = resolve(node, value.get("m_Father"), "Transform")
            if parent is None:
                break
            parent_tree = tree(parent)
            parent_game = resolve(parent, parent_tree.get("m_GameObject"), "GameObject") if isinstance(parent_tree, dict) else None
            if parent_game is None or transform(parent_game) is not parent:
                return set()
            node = parent
        return result

    rows = defaultdict(list)
    for renderer, value, game in scene.renderers:
        if renderer.type.name not in ("SkinnedMeshRenderer", "MeshRenderer") or game.type.name != "GameObject":
            continue
        if renderer.type.name == "SkinnedMeshRenderer":
            mesh = resolve(renderer, value.get("m_Mesh"), "Mesh")
        else:
            matches = filters.get(model_viewer._key(game), ())
            mesh = (resolve(matches[0], tree(matches[0]).get("m_Mesh"), "Mesh")
                    if len(matches) == 1 and isinstance(tree(matches[0]), dict) else None)
        mesh_id = identity(mesh) if mesh is not None else None
        if mesh_id is None:
            continue
        lineage = ancestors(game)
        proofs = [(role, proof) for root, role, proof in scopes if root in lineage]
        key = (mesh_id["source"], mesh_id["file"], mesh_id["id"], str(renderer.path_id))
        rows[key].append((mesh_id, renderer, mesh, proofs))

    output = []
    rank = {"face": 0, "hair": 1, "head": 2}
    for key, uses in rows.items():
        # The GLB identity format has no separate renderer-file field. If an
        # otherwise identical numeric identity also denotes costume geometry,
        # preserve it rather than removing both renderers through that alias.
        if any(not proof for _, _, _, proof in uses):
            continue
        mesh_id, renderer, mesh, _ = uses[0]
        proofs = [entry for _, _, _, found in uses for entry in found]
        proofs.sort(key=lambda entry: rank[entry[0]])
        unique = []
        for _, proof in proofs:
            if proof not in unique:
                unique.append(proof)
        output.append({"mesh": mesh_id, "renderer": str(renderer.path_id),
                       "rendererIdentity": identity(renderer), "role": proofs[0][0],
                       "name": scene.name(mesh), "proofs": unique})
    return output
