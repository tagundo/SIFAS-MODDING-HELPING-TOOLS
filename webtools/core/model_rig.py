"""Bounded standard glTF rigs, with read-only Unity rest-pose equivalence."""
from collections import defaultdict
import math
import zlib

MAX_NODES = 1024
MAX_MORPHS = 64
MAX_MORPH_VALUES = 8_000_000
MAX_NAME_BYTES = 1024
MAX_PATH_BYTES = 4096


class RigError(ValueError):
    pass


def apply_default_morphs(mesh, positions, normals, weights, deadline=None):
    """Evaluate supported authored default shape weights without editing inputs."""
    import numpy as np
    from .model_viewer import _remaining
    shapes = mesh.m_Shapes
    channels = getattr(shapes, "channels", [])
    if not weights or not channels:
        return positions, normals
    if len(channels) > MAX_MORPHS or len(weights) > MAX_MORPHS:
        raise RigError("The mesh has too many default morph weights.")
    positions, normals = positions.copy(), normals.copy()
    for index, channel in enumerate(channels):
        if deadline is not None:
            _remaining(deadline)
        weight = float(weights[index]) if index < len(weights) else 0.
        if not math.isfinite(weight) or abs(weight) > 10000:
            raise RigError("An authored morph weight is invalid.")
        if not weight:
            continue
        if channel.frameCount != 1:
            raise RigError("Nonzero multi-frame morph defaults are not supported.")
        frame = int(channel.frameIndex)
        if not 0 <= frame < len(shapes.shapes):
            raise RigError("An authored morph frame is invalid.")
        shape = shapes.shapes[frame]
        full = float(shapes.fullWeights[frame])
        if not math.isfinite(full) or full <= 0:
            raise RigError("An authored morph full weight is invalid.")
        start, count = int(shape.firstVertex), int(shape.vertexCount)
        if start < 0 or count < 0 or start + count > len(shapes.vertices):
            raise RigError("An authored morph vertex range is invalid.")
        for ordinal, value in enumerate(shapes.vertices[start:start + count]):
            if deadline is not None and ordinal % 4096 == 0:
                _remaining(deadline)
            vertex = int(value.index)
            if not 0 <= vertex < len(positions):
                raise RigError("An authored morph points outside its mesh.")
            positions[vertex] += np.asarray([value.vertex.x, value.vertex.y, value.vertex.z]) * (weight / full)
            if shape.hasNormals:
                normals[vertex] += np.asarray([value.normal.x, value.normal.y, value.normal.z]) * (weight / full)
    return positions, normals


def _quat(matrix, np):
    trace = float(np.trace(matrix))
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        q = [(matrix[2, 1] - matrix[1, 2]) / s, (matrix[0, 2] - matrix[2, 0]) / s,
             (matrix[1, 0] - matrix[0, 1]) / s, .25 * s]
    else:
        i = int(np.argmax(np.diag(matrix)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = math.sqrt(max(0, 1 + matrix[i, i] - matrix[j, j] - matrix[k, k])) * 2
        if s < 1e-12:
            raise RigError("A rig rotation cannot be represented safely.")
        q = [0., 0., 0., 0.]
        q[i], q[j], q[k], q[3] = .25 * s, (matrix[j, i] + matrix[i, j]) / s, (matrix[k, i] + matrix[i, k]) / s, (matrix[k, j] - matrix[j, k]) / s
    q = np.asarray(q, float)
    return (q / np.linalg.norm(q)).tolist()


def _trs(matrix):
    import numpy as np
    mirror = np.diag([-1., 1., 1., 1.])
    value = mirror @ matrix @ mirror
    scale = np.linalg.norm(value[:3, :3], axis=0)
    if not np.isfinite(value).all() or (scale < 1e-9).any():
        raise RigError("A rig contains an invalid transform.")
    if np.linalg.det(value[:3, :3]) < 0:
        scale[0] *= -1
    rotation = value[:3, :3] / scale
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-4, rtol=0):
        raise RigError("A facial attachment contains unsupported transform shear.")
    return {"translation": value[:3, 3].tolist(), "rotation": _quat(rotation, np), "scale": scale.tolist()}


def _authored_trs(tree):
    """Keep the authored local basis so absolute scale/animation keys stay valid."""
    position = [float(tree.get("m_LocalPosition", {}).get(axis, 0)) for axis in "xyz"]
    scale = [float(tree.get("m_LocalScale", {}).get(axis, 1)) for axis in "xyz"]
    rotation = [float(tree.get("m_LocalRotation", {}).get(axis, 1 if axis == "w" else 0)) for axis in "xyzw"]
    if not all(math.isfinite(value) for value in position + scale + rotation) or any(abs(value) < 1e-9 for value in scale):
        raise RigError("A rig contains invalid authored TRS values.")
    length = math.sqrt(sum(value * value for value in rotation))
    if length < 1e-12:
        raise RigError("A rig contains an invalid authored quaternion.")
    x, y, z, w = [value / length for value in rotation]
    return {"translation": [-position[0], position[1], position[2]], "rotation": [x, -y, -z, w], "scale": scale}


class RigBuilder:
    def __init__(self, scene, glb, faces, selected_paths, deadline):
        from .model_viewer import _source_path
        from .model_faces import _names
        self.glb, self.scene, self.faces, self.deadline = glb, scene, faces, deadline
        self.selected = set(selected_paths)
        owners, self.facial_sources = _names(scene)
        self.owner = next(iter(owners)) if len(owners) == 1 else None
        self.nodes, self.worlds, self.names = {}, {}, defaultdict(list)
        self.bones, self.morphs, self.node_bindings, self.morph_bindings = [], [], {}, {}
        self.visibility_bindings = {"renderer": {}, "gameObject": {}}
        self.warnings, self.skinned, self.morph_values = [], 0, 0
        self.bounds = None
        self.clips, self.animation_warnings, self.scaling = [], [], {}
        self.root = self._node("Character", {"translation": [0, 0, 0]}, "root")
        glb.doc["scenes"][0]["nodes"].append(self.root)
        for transform in scene.transforms.values():
            if _source_path(transform) in self.selected - self.facial_sources:
                self.ensure(transform)

    def _node(self, name, values, role):
        if len(name.encode("utf-8")) > MAX_NAME_BYTES:
            raise RigError("A rig node name exceeds the preview byte limit.")
        if len(self.glb.doc["nodes"]) >= MAX_NODES:
            raise RigError("The rig has too many nodes for the mobile viewer.")
        index = len(self.glb.doc["nodes"])
        self.glb.doc["nodes"].append(dict(values, name=f"{name}__{index}", extras={"elichika_node": index, "originalName": name, "role": role}))
        return index

    def _path(self, transform):
        from .model_viewer import _key, _ref
        names, seen, path_bytes = [], set(), 0
        while transform is not None:
            key = _key(transform)
            if key in seen or len(seen) >= 256:
                raise RigError("The rig contains a circular transform hierarchy.")
            seen.add(key)
            obj = _ref(transform, self.scene.tree(transform).get("m_GameObject"))
            name = self.scene.name(obj) if obj is not None else ""
            length = len(name.encode("utf-8"))
            path_bytes += length + 1
            if length > MAX_NAME_BYTES or path_bytes > MAX_PATH_BYTES:
                raise RigError("A rig hierarchy path exceeds the preview byte limit.")
            names.append(name)
            transform = _ref(transform, self.scene.tree(transform).get("m_Father"))
        return "/".join(reversed(names[:-1]))

    def _binding(self, path, node):
        for key in (path, zlib.crc32(path.encode())):
            previous = self.node_bindings.get(key)
            if previous is None:
                self.node_bindings[key] = node
            elif previous != node:
                self.node_bindings[key] = list(dict.fromkeys(([previous] if isinstance(previous, int) else previous) + [node]))

    def ensure(self, transform, renderer=None):
        import numpy as np
        from .model_viewer import _key, _ref, _source_path, _remaining
        _remaining(self.deadline)
        key = _key(transform)
        if key in self.nodes:
            return self.nodes[key]
        tree = self.scene.tree(transform)
        obj = _ref(transform, tree.get("m_GameObject"))
        name = self.scene.name(obj) if obj is not None else "Bone"
        world = self.scene.world(transform)
        source = _source_path(transform)
        primary = source in self.selected and source not in self.facial_sources
        if not primary and renderer is not None:
            world = self.faces.world(self.scene, renderer, world)
            matching = self.names.get(name, [])
            if len(matching) == 1 and name not in ("Face", "Hair", "Body", "Reference", "Move"):
                node = matching[0]
                if np.allclose(self.worlds[node], world, atol=5e-4, rtol=0):
                    self.nodes[key] = node
                    self._binding(self._path(transform), node)
                    return node
        parent = _ref(transform, tree.get("m_Father"))
        parent_index = self.ensure(parent, renderer) if parent is not None else self.root
        parent_world = self.worlds.get(parent_index, np.eye(4))
        local = np.linalg.inv(parent_world) @ world
        node = self._node(name, _authored_trs(tree) if primary else _trs(local), "bone")
        self.nodes[key], self.worlds[node] = node, world
        self.glb.doc["nodes"][parent_index].setdefault("children", []).append(node)
        path = self._path(transform)
        self.bones.append({"node": node, "name": name, "parent": parent_index, "path": path})
        if primary:
            self.names[name].append(node)
        self._binding(path, node)
        return node

    def update(self, scene, faces, deadline):
        self.scene, self.faces, self.deadline = scene, faces, deadline

    def record_bounds(self, positions):
        import numpy as np
        low, high = positions.min(axis=0), positions.max(axis=0)
        self.bounds = [low, high] if self.bounds is None else [np.minimum(self.bounds[0], low), np.maximum(self.bounds[1], high)]

    def _anchor(self, renderer, game_object):
        from .model_viewer import _key, _source_path
        source = _source_path(renderer)
        # Zero-bind Face surfaces and facial morph meshes are authored in whole
        # character space. Bind them rigidly to the verified head frame.
        for name in ("Head_Face", "Head"):
            matches = [t for t in self.scene.transforms.values()
                       if _source_path(t) == source and self.scene.name(self._game(t)) == name]
            if len(matches) == 1:
                return self.ensure(matches[0], renderer)
        return None

    def _game(self, transform):
        from .model_viewer import _ref
        return _ref(transform, self.scene.tree(transform).get("m_GameObject"))

    def attributes(self, renderer, tree, game_object, raw, rest_positions):
        import numpy as np
        from .model_viewer import _key, _ref
        from .model_skinning import _matrix
        mirror = np.diag([-1., 1., 1., 1.])
        positions, normals = raw["positions"], raw["normals"]
        mesh = raw["mesh"]
        joints, inverse = [], []
        refs, poses = tree.get("m_Bones", []), mesh.m_BindPose
        indices, weights = raw["indices"], raw["weights"]
        if poses and refs and indices is not None and weights is not None:
            indices, weights = np.asarray(indices, dtype=np.int64).copy(), np.asarray(weights, float).copy()
            if indices.shape != weights.shape or indices.ndim != 2 or indices.shape[0] != len(positions) or not 1 <= indices.shape[1] <= 4:
                raise RigError("A rig has unsupported skin influences.")
            if indices.shape[1] < 4:
                indices = np.pad(indices, ((0, 0), (0, 4 - indices.shape[1])))
                weights = np.pad(weights, ((0, 0), (0, 4 - weights.shape[1])))
            active = weights > 0
            if (active & ((indices < 0) | (indices >= min(len(refs), len(poses))))).any():
                raise RigError("A rig references missing bone weights.")
            indices[~active] = 0
            totals = weights.sum(axis=1)
            if (totals <= 0).any():
                raise RigError("Zero-weight vertices retain their static preview.")
            weights /= totals[:, None]
            for index, pose in enumerate(poses):
                bone = _ref(renderer, refs[index]) if index < len(refs) else None
                if bone is None:
                    if (active & (indices == index)).any():
                        raise RigError("A rig contains an unresolved active bone.")
                    joints.append(self.root)
                else:
                    joints.append(self.ensure(bone, renderer))
                inverse.append(mirror @ _matrix(pose, np) @ mirror)
        else:
            joint = self._anchor(renderer, game_object)
            if joint is None:
                raise RigError("This mesh has no usable rig anchor.")
            # Bake ordinary renderer placement into this one inverse bind so
            # zero-bind face pieces follow the selected costume's head bones.
            world = self.scene.world(self.scene.transforms.get(_key(game_object)))
            world = self.faces.world(self.scene, renderer, world)
            joints = [joint]
            inverse = [mirror @ (np.linalg.inv(self.worlds[joint]) @ world) @ mirror]
            indices = np.zeros((len(positions), 4), dtype=np.int64)
            weights = np.zeros((len(positions), 4), float)
            weights[:, 0] = 1
        if len(joints) > 1024:
            raise RigError("A skin has too many joints.")
        normalized = normals.copy()
        lengths = np.linalg.norm(normalized, axis=1)
        normalized[lengths < 1e-12] = [0, 1, 0]
        lengths[lengths < 1e-12] = 1
        normalized /= lengths[:, None]
        attributes = {"POSITION": self.glb.attribute(positions * [-1, 1, 1], "VEC3", bounds=True),
                      "NORMAL": self.glb.attribute(normalized * [-1, 1, 1], "VEC3"),
                      "JOINTS_0": self.glb.attribute(indices, "VEC4", 5123),
                      "WEIGHTS_0": self.glb.attribute(weights, "VEC4")}
        matrices = np.asarray(inverse, dtype=float).transpose(0, 2, 1).reshape(len(joints), 16)
        skin_index = len(self.glb.doc.setdefault("skins", []))
        self.glb.doc["skins"].append({"joints": joints, "inverseBindMatrices": self.glb.attribute(matrices, "MAT4", target=None), "skeleton": self.root})
        colors = raw.get("colors")
        if colors is not None:
            colors = np.asarray(colors, float)
            if colors.shape == (len(positions), 4) and np.isfinite(colors).all():
                if colors.max() > 1:
                    colors = colors / 255
                attributes["_SIFAS_COLOR"] = self.glb.attribute(colors, "VEC4")
        return attributes, skin_index

    def morph_targets(self, raw, renderer, game_object):
        import numpy as np
        from .model_viewer import _remaining
        shapes = raw["mesh"].m_Shapes
        channels = getattr(shapes, "channels", [])
        if len(channels) > MAX_MORPHS:
            raise RigError("The mesh has too many facial morph targets.")
        targets, names, hashes, defaults = [], [], [], []
        saved_weights = self.scene.tree(renderer).get("m_BlendShapeWeights", [])
        count = len(raw["positions"])
        for channel_index, channel in enumerate(channels):
            _remaining(self.deadline)
            if channel.frameCount != 1:
                self.warnings.append("Multi-frame blend shapes are not exported.")
                continue
            index = int(channel.frameIndex)
            if not 0 <= index < len(shapes.shapes):
                raise RigError("A facial morph frame is invalid.")
            shape = shapes.shapes[index]
            full_weight = float(shapes.fullWeights[index]) if index < len(shapes.fullWeights) else 100.
            if not math.isfinite(full_weight) or full_weight <= 0:
                raise RigError("A facial morph has an invalid full weight.")
            first, size = int(shape.firstVertex), int(shape.vertexCount)
            if first < 0 or size < 0 or first + size > len(shapes.vertices):
                raise RigError("A facial morph contains invalid vertices.")
            self.morph_values += count * 6
            if self.morph_values > MAX_MORPH_VALUES:
                raise RigError("Facial morph data exceeds the preview memory limit.")
            delta, normal = np.zeros((count, 3)), np.zeros((count, 3))
            for ordinal in range(first, first + size, 4096):
                _remaining(self.deadline)
                chunk = shapes.vertices[ordinal:min(ordinal + 4096, first + size)]
                indices = np.asarray([value.index for value in chunk], dtype=np.int64)
                if (indices < 0).any() or (indices >= count).any():
                    raise RigError("A facial morph points outside its mesh.")
                delta[indices] = [[value.vertex.x, value.vertex.y, value.vertex.z] for value in chunk]
                if shape.hasNormals:
                    normal[indices] = [[value.normal.x, value.normal.y, value.normal.z] for value in chunk]
            targets.append({"POSITION": self.glb.attribute(delta * [-1, 1, 1] * (100 / full_weight), "VEC3"),
                            "NORMAL": self.glb.attribute(normal * [-1, 1, 1] * (100 / full_weight), "VEC3")})
            names.append(str(channel.name))
            hashes.append(int(channel.nameHash))
            default = float(saved_weights[channel_index]) / 100. if channel_index < len(saved_weights) else 0.
            if not math.isfinite(default) or abs(default) > 100:
                raise RigError("An authored facial morph weight is invalid.")
            defaults.append(default)
        return targets, names, hashes, defaults

    def place(self, node, renderer, game_object, skin, morph_names, morph_hashes, morph_weights):
        from .model_viewer import _key
        value = self.glb.doc["nodes"][node]
        self.skinned += 1
        value["skin"] = skin
        value.setdefault("extras", {}).update(elichika_node=node, role="mesh")
        self.glb.doc["scenes"][0]["nodes"].remove(node)
        self.glb.doc["nodes"][self.root].setdefault("children", []).append(node)
        path = self._path(self.scene.transforms[_key(game_object)])
        for visibility_type, paths in (("renderer", [path]), ("gameObject", ["/"] + ["/".join(path.split("/")[:index]) for index in range(1, len(path.split("/")) + 1)])):
            for target_path in paths:
                if target_path == "/":
                    target_path = ""
                for key in (target_path, zlib.crc32(target_path.encode())):
                    values = self.visibility_bindings[visibility_type].setdefault(key, [])
                    if node not in values:
                        values.append(node)
        if morph_names:
            record = {"node": node, "names": morph_names, "hashes": dict(zip(morph_names, morph_hashes)), "weights": list(morph_weights)}
            self.morphs.append(record)
            for key in (path, zlib.crc32(path.encode())):
                self.morph_bindings[key] = record

    def metadata(self):
        import copy
        bounds = {"min": self.bounds[0].tolist(), "max": self.bounds[1].tolist()} if self.bounds is not None else None
        return copy.deepcopy({"enabled": True, "available": self.skinned > 0, "root": self.root,
                "bones": self.bones, "bounds": bounds, "morphs": self.morphs,
                "clips": self.clips, "animationWarnings": self.animation_warnings,
                "scaling": self.scaling, "warnings": list(dict.fromkeys(self.warnings))})

    def finalize(self, animations=True):
        from .model_animation import append_animations
        from .model_scaling import describe_scaling
        # Rebind after optional facial nodes arrive. Older animation accessors
        # remain bounded unused buffers; the playable animation list is replaced.
        self.scaling = describe_scaling(self.scene, self.glb, self.nodes, sources=self.selected)
        if animations:
            self.glb.doc.pop("animations", None)
            result = append_animations(self.scene, self.glb, self.node_bindings, self.morph_bindings,
                                       deadline=self.deadline, visibility_bindings=self.visibility_bindings)
            self.clips, self.animation_warnings = result["clips"], result["warnings"]
