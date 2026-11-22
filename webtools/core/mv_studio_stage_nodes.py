"""Retain the prefab hierarchy for exact stage animation bindings."""

from . import model_animation, model_viewer as viewer
from .model_rig import _authored_trs
from .mv_studio_stage_coloring import _path

_PREFIX = "/EntryPoint/Live/Stages/MainStage/Effect/"


class StageNodes:
    def __init__(self, scene, glb, bindings):
        self.scene, self.glb = scene, glb
        self.roots, self.nodes = {}, {}
        self.paths = {}
        if not bindings:
            return
        wanted = {tuple(binding[len(_PREFIX):].split("/")): binding
                  for binding in bindings if isinstance(binding, str) and binding.startswith(_PREFIX)}
        candidates = {}
        for key, transform in scene.transforms.items():
            game = viewer._ref(transform, scene.tree(transform).get("m_GameObject"))
            path = _path(scene, game)
            if not path:
                continue
            self.paths[key] = path
            if path[1:] in wanted:
                candidates.setdefault(wanted[path[1:]], []).append(path)
        roots = {paths[0]: name for name, paths in candidates.items() if len(paths) == 1}
        # A single animated transform cannot belong to two independent graphs.
        self.roots = {path: name for path, name in roots.items()
                      if not any(other != path and (path[:len(other)] == other or other[:len(path)] == path)
                                 for other in roots)}

    def binding(self, game):
        path = self.paths.get(viewer._key(game), ())
        for root, name in self.roots.items():
            if path[:len(root)] == root:
                return name, model_animation.path_hash("/".join(path[len(root):]))
        return None

    def attach(self, game, mesh):
        parent = self._ensure(game)
        self.glb.doc["nodes"][parent].setdefault("children", []).append(mesh)

    def export_skinned(self, renderer, tree, game_object, raw):
        """Add a local rigid skin to the original animated stage hierarchy."""
        import numpy as np

        from .model_skinning import MAX_BONES, MAX_VERTICES, SkinningError, _matrix, _rows

        binding = self.binding(game_object)
        if binding is None or renderer.type.name != "SkinnedMeshRenderer" or tree.get("m_BlendShapeWeights"):
            return None

        def local_object(pointer, object_type):
            if not isinstance(pointer, dict) or pointer.get("m_FileID") != 0:
                return None
            item = viewer._ref(renderer, pointer)
            return item if (item is not None and item.type.name == object_type
                            and item.assets_file is renderer.assets_file) else None

        def bone_game(pointer):
            transform = local_object(pointer, "Transform")
            if transform is None:
                return None
            game = viewer._ref(transform, self.scene.tree(transform).get("m_GameObject"))
            if game is None or game.assets_file is not renderer.assets_file:
                return None
            registered = self.scene.transforms.get(viewer._key(game))
            return game if registered is not None and viewer._key(registered) == viewer._key(transform) else None

        mesh = raw.get("mesh")
        refs, poses = tree.get("m_Bones"), getattr(mesh, "m_BindPose", None)
        if (not refs or not poses or not 0 < len(refs) == len(poses) <= MAX_BONES
                or local_object(tree.get("m_Mesh"), "Mesh") is None):
            return None
        root_game = bone_game(tree.get("m_RootBone"))
        root_path = self.paths.get(viewer._key(root_game), ()) if root_game is not None else ()
        if not root_path:
            return None
        joints, paths, inverse = [], set(), []
        mirror = np.diag([-1., 1., 1., 1.])
        try:
            for ref, pose in zip(refs, poses, strict=True):
                game = bone_game(ref)
                if game is None:
                    return None
                path = self.paths.get(viewer._key(game), ())
                owner = self.binding(game)
                if path[:len(root_path)] != root_path or path in paths or owner is None or owner[0] != binding[0]:
                    return None
                paths.add(path)
                joints.append(game)
                inverse.append(mirror @ _matrix(pose, np) @ mirror)
            if root_path not in paths:
                return None
            count = len(raw["positions"])
            if not 0 < count <= MAX_VERTICES:
                return None
            indices = _rows(raw.get("indices"), count, (1, 2, 3, 4), np, "bone indices", dtype=None)
            weights = _rows(raw.get("weights"), count, (1, 2, 3, 4), np, "vertex weights")
        except (KeyError, TypeError, SkinningError):
            return None
        if indices.shape != weights.shape or indices.dtype.kind not in "iuf":
            return None
        weighted = weights == 1
        if not ((weights == 0) | weighted).all() or not (weighted.sum(axis=1) == 1).all():
            return None
        selected = indices[weighted]
        if not np.isfinite(selected).all() or (selected < 0).any() or (selected >= len(joints)).any() \
                or not np.equal(selected, np.trunc(selected)).all():
            return None
        attributes = {
            "JOINTS_0": self.glb.attribute(np.column_stack((selected, np.zeros((count, 3)))), "VEC4", 5123),
            "WEIGHTS_0": self.glb.attribute(np.column_stack((np.ones(count), np.zeros((count, 3)))), "VEC4"),
        }
        matrices = np.asarray(inverse, dtype=np.float32).transpose(0, 2, 1).reshape(len(joints), 16)
        skins = self.glb.doc.setdefault("skins", [])
        skin = len(skins)
        skins.append({"joints": [self._ensure(game) for game in joints],
                      "inverseBindMatrices": self.glb.attribute(matrices, "MAT4", target=None),
                      "skeleton": self._ensure(root_game)})
        return attributes, skin

    def _ensure(self, game):
        key = viewer._key(game)
        if key in self.nodes:
            return self.nodes[key]
        transform = self.scene.transforms[key]
        tree = self.scene.local_tree(transform)
        father = viewer._ref(transform, tree.get("m_Father"))
        parent = viewer._ref(father, self.scene.tree(father).get("m_GameObject")) if father is not None else None
        index = len(self.glb.doc["nodes"])
        extras = {"active": bool(self.scene.tree(game).get("m_IsActive", True))}
        binding = self.binding(game)
        if binding is not None:
            extras.update(binding=binding[0], path=binding[1])
        self.glb.doc["nodes"].append({**_authored_trs(tree, allow_zero_scale=True), "name": self.scene.name(game),
                                      "extras": {"mvStageNode": extras}})
        self.nodes[key] = index
        if parent is None:
            self.glb.doc["scenes"][0]["nodes"].append(index)
        else:
            self.glb.doc["nodes"][self._ensure(parent)].setdefault("children", []).append(index)
        return index
