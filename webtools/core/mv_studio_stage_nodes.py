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
