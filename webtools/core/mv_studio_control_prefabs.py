"""Instance the non-particle content of CustomControl prefabs (one common rule).

Client behaviour, shared with mv_studio_particle_systems (whose docstring has
the evidence) and read from the same cue extraction (``control_clips``):

* ``CustomControlClip.CreatePlayable`` (0x26e7cb0) instantiates
  ``prefabGameObject`` through a PrefabControlPlayable with no parent, at the
  world root; ``ConnectPlayablesToMixer`` adds the clip ``offset`` to the clone
  position. OnBehaviourPlay activates the clone at the clip start and
  OnBehaviourPause deactivates it at the clip end.
* While active, every enabled MeshRenderer (its MeshFilter's mesh, Unity's
  built-in Quad/Plane included) and SkinnedMeshRenderer on an active
  GameObject draws with its materials through the MainCamera when its layer
  is in the level35 culling mask 0x0C0BC013. Layer 20 belongs to the
  orthographic overlay camera and is reported here.
* An enabled Animator on a GameObject active at the clone's activation plays
  its controller's default state from that activation on the player clock
  (mv_studio_prefab_animator): Transform,
  GameObject activation, renderer enable and the renderer's _TintColor and
  _MainTex_ST (its MaterialPropertyBlock), wrapped by m_LoopTime.
* A CustomControl track is gated by its quality category like the particle
  systems (Control: stage_control, Display: stage_display).

Only AS/General/Transparent materials are read (identified by the shader's
ShaderLab name, so an embedded copy counts); meshes keep their authored
vertices, UVs, colors and bone weights, and textures their authored pixels and
mip levels. Anything else is reported per renderer, never approximated.

``read`` also returns a coverage ledger with one row for every
CustomControlClip: drawn by a per-effect stage reader, drawn in full or in
part by the particle and prefab rules, drawing nothing in the original, or not
previewed with the reasons. mv_studio_import_coverage reports it.
"""

import base64
import math
import time

from . import model_viewer as viewer, mv_studio_particle_systems as particles
from . import mv_studio_prefab_animator as animator, mv_studio_stage_title as title
from . import transient_failures, unity_builtin_meshes


SCHEMA = 1
_MAX_TEMPLATES = 64
_MAX_CUES = 512  # MVStudioControlPrefabs.validDescriptor refuses a longer cue list.
_MAX_RENDERERS = 64
_MAX_VERTICES = 120_000
_MAX_BYTES = 12 * 1024 * 1024
_MAX_BONES = 256
_RESERVE_SECONDS = 3
_MAIN_CAMERA_MASK = 0x0C0BC013
_OVERLAY_LAYER = 20
_RENDERER_KINDS = ("MeshRenderer", "SkinnedMeshRenderer")

RENDERED, PARTIAL, NOT_RENDERED, NO_EFFECT, MUTED = "rendered", "partial", "not rendered", "no effect", "muted"
# Particle importer reasons that describe what the original never draws.
_NO_EFFECT = {"playOnAwake is off (the clone never starts it)",
              "kept inactive by the prefab Animator (the game never draws it)",
              "renderer material is empty (nothing is drawn)"}


def _b64(array, dtype):
    import numpy as np

    return base64.b64encode(np.ascontiguousarray(array, dtype=dtype).tobytes()).decode("ascii")


class _Builder:
    """Shared textures and meshes of every template, within the preview budget."""

    def __init__(self, deadline, textures=None):
        # The particle reader's table when given: a texture both use is exported once.
        self.textures = particles._Textures(deadline) if textures is None else textures
        self.meshes, self.index, self.vertices, self.bytes = [], {}, 0, 0

    def mesh(self, renderer, kind, node, need_colors, skin_quality=0):
        import numpy as np

        if kind == "MeshRenderer":
            mesh_filter = node["components"].get("MeshFilter")
            if mesh_filter is None:
                raise animator.Unsupported("MeshRenderer without a MeshFilter (nothing is drawn)")
            pointer = mesh_filter.read_typetree().get("m_Mesh") or {}
            owner = mesh_filter
        else:
            pointer, owner = renderer.read_typetree().get("m_Mesh") or {}, renderer
        if not pointer.get("m_PathID"):
            raise animator.Unsupported("renderer has no mesh (nothing is drawn)")
        builtin = unity_builtin_meshes.pointer_id(owner, pointer)
        source = None if builtin else viewer._ref(owner, pointer)
        if not builtin and (source is None or source.type.name != "Mesh"):
            raise animator.Unsupported("the mesh is not in the timeline bundle")
        key = ("builtin", builtin) if builtin else viewer._key(source)
        if key in self.index:
            row = self.index[key]
            if need_colors and self.meshes[row]["colors"] is None and not self.meshes[row]["colorAbsent"]:
                raise animator.Unsupported("vertex colors the preview cannot decode")
            return row, self.meshes[row]
        raw, inputs = {}, {}
        if builtin:
            name, positions, _, uv, submeshes = unity_builtin_meshes.geometry(builtin)
            inputs["colorAbsent"] = True  # Plane and Quad have no COLOR stream.
        else:
            name, positions, _, uv, submeshes = viewer._geometry(source, np.eye(4), rig_data=raw, stage_data=inputs)
        count = len(positions)
        if self.vertices + count > _MAX_VERTICES:
            raise animator.Unsupported("preview mesh budget")
        if uv is not None:
            uv = np.asarray(uv, dtype=np.float32).copy()
            uv[:, 1] = 1 - uv[:, 1]  # Back to Unity's UV; the runtime flips after _MainTex_ST.
        colors = inputs.get("color")
        row = {"name": str(name)[:128], "vertexCount": count, "positions": _b64(positions, "<f4"),
               "uv": _b64(uv, "<f4") if uv is not None else None,
               "colors": _b64(colors, "<f4") if colors is not None else None,
               "colorAbsent": bool(inputs.get("colorAbsent")),
               "submeshes": [_b64(np.asarray(indices).reshape(-1), "<u4") for indices in submeshes]}
        if kind == "SkinnedMeshRenderer":
            from .model_skinning import SkinningError, _rows

            try:
                joints = _rows(raw.get("indices"), count, (1, 2, 3, 4), np, "bone indices", dtype=None)
                weights = _rows(raw.get("weights"), count, (1, 2, 3, 4), np, "vertex weights")
            except (SkinningError, KeyError, TypeError, ValueError):
                raise animator.Unsupported("skin weights the preview cannot read") from None
            if (joints.shape != weights.shape or not np.isfinite(weights).all() or (weights < 0).any()
                    or not np.equal(joints, np.trunc(joints)).all() or (joints < 0).any()):
                raise animator.Unsupported("skin weights the preview cannot read")
            # Auto skin quality follows the device's QualitySettings: accept it only when
            # every vertex is rigid, where the setting cannot change the result.
            limit = skin_quality if skin_quality in (1, 2, 4) else 1
            if ((weights > 0).sum(axis=1) > limit).any():
                raise animator.Unsupported("skin with more bone influences than its quality setting fixes")
            padding = ((0, 0), (0, 4 - joints.shape[1]))
            row["joints"] = _b64(np.pad(joints, padding), "<u2")
            row["weights"] = _b64(np.pad(weights, padding), "<f4")
            row["bindPoses"] = raw["mesh"].m_BindPose
        size = sum(len(value) for field, value in row.items() if isinstance(value, str) and field != "name")
        size += sum(len(value) for value in row["submeshes"])
        if self.bytes + size > _MAX_BYTES:
            raise animator.Unsupported("preview mesh budget")
        self.vertices += count
        self.bytes += size
        bind_poses = row.pop("bindPoses", None)
        if not builtin:
            center = getattr(getattr(raw.get("mesh"), "m_LocalAABB", None), "m_Center", None)
            values = [getattr(center, axis, None) for axis in "xyz"]
            if all(type(value) in (int, float) and math.isfinite(value) for value in values):
                row["_center"] = [-values[0], values[1], values[2]]
        self.index[key] = len(self.meshes)
        self.meshes.append(row)
        if bind_poses is not None:
            row["_bindPoses"] = bind_poses
        if need_colors and colors is None and not row["colorAbsent"]:
            raise animator.Unsupported("vertex colors the preview cannot decode")
        return self.index[key], row


def _mirrored(matrix):
    """A Unity 4x4 matrix in the editor's X-mirrored basis, column-major for three.js."""
    import numpy as np

    from .model_skinning import _matrix

    mirror = np.diag([-1., 1., 1., 1.])
    return [float(value) for value in (mirror @ _matrix(matrix, np) @ mirror).T.reshape(-1)]


def _reachable(walked, own, activated):
    """Whether the node can be active in the clone: every inactive GameObject on its chain
    below the root (which PrefabControl activates) has an Animator activation curve."""
    index = own
    while index is not None and walked[index]["parent"] is not None:
        if not walked[index]["self"] and index not in activated:
            return False
        index = walked[index]["parent"]
    return True


def _animators(objects, walked, deadline):
    """Every playing Animator's channels, and the reasons nodes are not previewed under them."""
    rows, subtree, own_unsupported = [], {}, {}
    for own, node in enumerate(walked):
        legacy = node["components"].get("Animation")
        if legacy is not None and node["authored"] and legacy.read_typetree().get("m_Enabled", True):
            subtree[own] = "under prefab animation that is not previewed (legacy Animation component)"
        component = node["components"].get("Animator")
        if component is None:
            continue
        fields = component.read_typetree()
        if not fields.get("m_Enabled", True):
            continue
        if not node["authored"]:
            # Inactive when PrefabControl activates the clone: Unity starts this
            # Animator's default state when a curve activates its GameObject, not
            # at the clone's activation. That start time is not reproduced, so
            # what it animates is reported (an unreachable node draws nothing).
            subtree[own] = ("under prefab animation that is not previewed "
                            "(Animator activated after the clone; its state time is not reproduced)")
            continue
        try:
            clip = animator.default_clip(objects, component, fields)
            if clip is None:
                continue
            timing = animator.timing(clip)
            channels, unsupported = animator.channels(walked, own, animator.bindings(clip, deadline))
            channels = [{**row, "curves": [animator.json_curve(curve) for curve in row["curves"]]} for row in channels]
        except (animator.Unsupported, *title._UNSUPPORTED) as error:
            subtree[own] = f"under prefab animation that is not previewed ({str(error)[:120] or type(error).__name__})"
            continue
        for target, reason in unsupported.items():
            own_unsupported.setdefault(target, reason)
        rows.append({"node": own, "clip": timing, "channels": channels})
    return rows, subtree, own_unsupported


def _template(objects, walked, builder, deadline):
    """Return (template or None, drawn renderer count, gaps, no-effect notes) for one prefab."""
    present = [(own, kind) for own, node in enumerate(walked) for kind in _RENDERER_KINDS
               if kind in node["components"]]
    if not present:
        return None, 0, [], []
    animators, subtree, own_unsupported = _animators(objects, walked, deadline)
    activated = {row["node"] for item in animators for row in item["channels"] if row["kind"] == "active"}
    blocked = []
    for own, node in enumerate(walked):
        parent = node["parent"]
        blocked.append(subtree.get(own) or (blocked[parent] if parent is not None else None))
    transforms = {viewer._key(node["components"]["Transform"]): own for own, node in enumerate(walked)
                  if node["components"].get("Transform") is not None}
    renderers, gaps, no_effect, materials_seen = [], [], [], {}
    for own, kind in present:
        node = walked[own]
        renderer = node["components"][kind]
        path = node["path"]
        try:
            tree = renderer.read_typetree()
            switched = any(row["kind"] == "enabled" and row["node"] == own and row["renderer"] == kind
                           for item in animators for row in item["channels"])
            if not tree.get("m_Enabled", True) and not switched:
                no_effect.append(f"{kind} disabled")
                continue
            if not _reachable(walked, own, activated):
                no_effect.append("inactive GameObject")
                continue
            layer = node["tree"].get("m_Layer", 0)
            if layer == _OVERLAY_LAYER:
                raise animator.Unsupported("on the overlay camera layer 20 (not previewed)")
            if type(layer) is not int or not 0 <= layer < 32 or not (_MAIN_CAMERA_MASK >> layer) & 1:
                no_effect.append(f"layer {layer} is not drawn by the main camera")
                continue
            if blocked[own]:
                raise animator.Unsupported(blocked[own])
            if own in own_unsupported:
                raise animator.Unsupported(own_unsupported[own])
            if any(tree.get(field) for field in ("m_SortingLayerID", "m_SortingOrder", "m_RendererPriority")):
                raise animator.Unsupported("renderer sorting layer, order or priority")
            if kind == "SkinnedMeshRenderer" and any(tree.get("m_BlendShapeWeights") or ()):
                raise animator.Unsupported("blend shape weights")
            if len(renderers) >= _MAX_RENDERERS:
                raise animator.Unsupported("too many renderers in one prefab")
            pointers = tree.get("m_Materials") or []
            surfaces, textures = [], []
            for pointer in pointers:
                identity = (pointer or {}).get("m_FileID"), (pointer or {}).get("m_PathID")
                if identity not in materials_seen:
                    try:
                        materials_seen[identity] = particles.surface(objects, renderer, pointer)
                    except (animator.Unsupported, *title._UNSUPPORTED) as error:
                        materials_seen[identity] = str(error)[:160] or type(error).__name__
                found = materials_seen[identity]
                if isinstance(found, str):
                    raise animator.Unsupported(found)
                surfaces.append(dict(found[0]))
                textures.append(found[1])
            if not surfaces:
                no_effect.append(f"{kind} without materials")
                continue
            mesh_index, mesh = builder.mesh(renderer, kind, node, any(item["vertexColor"] for item in surfaces),
                                            tree.get("m_Quality", 0))
            submeshes = len(mesh["submeshes"])
            # Unity draws submesh i with material i; extra materials draw the last submesh again.
            draws = [[min(index, submeshes - 1), index] for index in range(len(surfaces))] if submeshes else []
            for surface, texture in zip(surfaces, textures):
                surface["texture"] = builder.textures.add(texture)
            row = {"node": own, "kind": kind, "mesh": mesh_index, "materials": surfaces, "draws": draws,
                   "enabled": bool(tree.get("m_Enabled", True)), "path": path}
            if kind == "MeshRenderer":
                # Unity sorts a transparent renderer by its bounds center (the mesh AABB center).
                row["sortCenter"] = mesh.get("_center") or [0., 0., 0.]
            else:
                bones = []
                for pointer in tree.get("m_Bones") or []:
                    transform = title._local(objects, renderer, pointer, "Transform")
                    index = transforms.get(viewer._key(transform)) if transform is not None else None
                    if index is None:
                        raise animator.Unsupported("a skin bone is outside the prefab")
                    bones.append(index)
                poses = mesh.get("_bindPoses") or []
                if not bones or len(bones) != len(poses) or len(bones) > _MAX_BONES:
                    raise animator.Unsupported("skin bones do not match the mesh bind poses")
                root = title._local(objects, renderer, tree.get("m_RootBone"), "Transform")
                center = ((tree.get("m_AABB") or {}).get("m_Center") or {})
                values = [center.get(axis) for axis in "xyz"]
                row["skin"] = {"bones": bones, "bindPoses": [_mirrored(pose) for pose in poses],
                               # Unity recomputes the bounds from the skinned pose every frame.
                               "updateWhenOffscreen": bool(tree.get("m_UpdateWhenOffscreen", 0)),
                               "root": transforms.get(viewer._key(root)) if root is not None else None,
                               "rootCenter": [-values[0], values[1], values[2]]
                               if all(type(value) in (int, float) and math.isfinite(value) for value in values) else None}
            renderers.append(row)
        except (animator.Unsupported, *title._UNSUPPORTED, viewer.ModelViewerError) as error:
            gaps.append({"path": path, "reason": str(error)[:160] or type(error).__name__})
    if not renderers:
        return None, 0, gaps, no_effect
    nodes = []
    for node in walked:
        if any(node[field] is None for field in ("position", "rotation", "scale")):
            raise animator.Unsupported("non-finite or out-of-range transform")
        nodes.append({"parent": node["parent"], "path": node["path"], "layer": node["tree"].get("m_Layer", 0),
                      # PrefabControl activates the clone root itself.
                      "active": node["parent"] is None or node["self"],
                      "position": node["position"], "rotation": node["rotation"], "scale": node["scale"]})
    by_renderer = {(row["node"], row["kind"]): index for index, row in enumerate(renderers)}
    played = []
    for item in animators:
        channels = []
        for row in item["channels"]:
            if "renderer" in row:
                index = by_renderer.get((row["node"], row["renderer"]))
                if index is None:
                    continue  # Particle renderers are played by the particle runtime.
                row = {key: value for key, value in row.items() if key not in ("node", "renderer")}
                row["target"] = index
            else:
                row = {key: value for key, value in row.items() if key != "node"} | {"target": row["node"]}
            channels.append(row)
        if channels:
            played.append({"node": item["node"], "clip": item["clip"], "channels": channels})
    name = str(walked[0]["tree"].get("m_Name", ""))[:128]
    return ({"name": name, "nodes": nodes, "renderers": renderers, "animators": played},
            len(renderers), gaps, no_effect)


def _counted(reasons):
    found = {}
    for reason in reasons:
        found[reason] = found.get(reason, 0) + 1
    return ", ".join(f"{reason} x{count}" if count > 1 else reason
                     for reason, count in sorted(found.items(), key=lambda item: (-item[1], item[0])))


def _particle_summary(outcome):
    """(drawn systems, gap reasons, no-effect reasons) from the particle importer's outcome."""
    if outcome is None:
        return 0, [], []
    gaps, quiet = [], []
    if outcome.get("error"):
        gaps.append(f"particle prefab: {outcome['error']}")
    drawn = 0
    for layer in outcome.get("systems") or ():
        if layer == _OVERLAY_LAYER:
            gaps.append("particles on the overlay camera layer 20")
        elif type(layer) is int and 0 <= layer < 32 and (_MAIN_CAMERA_MASK >> layer) & 1:
            drawn += 1
        else:
            quiet.append(f"particles on layer {layer}, which the main camera does not draw")
    for row in outcome.get("rejected") or ():
        (quiet if row["reason"] in _NO_EFFECT else gaps).append(row["reason"])
    return drawn, gaps, quiet


def read(objects, mono, tracks, deadline, *, claimed=None, outcomes=None, textures=None, shared=0):
    """Return (descriptor or None, coverage ledger) for every CustomControlClip.

    ``claimed`` maps (trackId, eventId) to the per-effect stage reader that draws
    the cue; those cues are left to it. ``outcomes`` is what
    mv_studio_particle_systems.read did with each prefab (None: no particles).
    ``textures`` is the particle reader's texture table; its first ``shared``
    entries are carried by the stageParticleSystems descriptor, so this
    descriptor lists only the entries after them ("sharedTextures": shared) and
    a material index below ``shared`` names that descriptor's texture.
    """
    claimed = claimed or {}
    builder = _Builder(deadline, textures)
    if not 0 <= shared <= len(builder.textures.levels):
        raise ValueError("shared texture count outside the texture table")
    templates, cues, ledger, prefabs, mesh_reasons = [], [], [], {}, {}
    for row in particles.control_clips(objects, mono, tracks):
        track, event = row["track"], row["event"]
        identity = (track["id"], event["id"])
        entry = {"trackId": track["id"], "eventId": event["id"]}
        if "reason" in row:
            reason = row["reason"]
            # CreatePlayable returns Playable.Null for a clip without a prefab.
            status = (MUTED if reason == particles.MUTED else
                      NO_EFFECT if reason in (particles.DISABLED, particles.NO_PREFAB) else NOT_RENDERED)
            ledger.append({**entry, "status": status, "note": f"The clip is not played here: {reason}."})
            continue
        if identity in claimed:
            ledger.append({**entry, "status": RENDERED,
                           "note": f"Drawn by the per-effect stage reader {claimed[identity]}."})
            continue
        key = viewer._key(row["prefab"])
        if key not in prefabs:
            outcome = (outcomes or {}).get(key)
            drawn, gaps, quiet = _particle_summary(outcome)
            index, meshes = None, 0
            try:
                if time.monotonic() > deadline - _RESERVE_SECONDS:
                    transient_failures.note()  # a faster run would read this template
                    raise animator.Unsupported("import time budget")
                if len(templates) >= _MAX_TEMPLATES:
                    raise animator.Unsupported("import time budget")
                walked = (outcome or {}).get("walked")
                if walked is None:
                    walked = particles._walk(objects, row["prefab"], deadline)
                template, meshes, mesh_gaps, mesh_quiet = _template(objects, walked, builder, deadline)
                gaps += [item["reason"] for item in mesh_gaps]
                mesh_reasons[key] = [item["reason"] for item in mesh_gaps]
                quiet += mesh_quiet
                if template is not None:
                    index = len(templates)
                    templates.append(template)
            except (animator.Unsupported, *title._UNSUPPORTED, viewer.ModelViewerError) as error:
                gaps.append(f"prefab meshes: {str(error)[:120] or type(error).__name__}")
            if outcomes is None:
                gaps.append("particle systems are not read by this import")
            prefabs[key] = index, drawn, meshes, gaps, quiet
        index, systems, meshes, gaps, quiet = prefabs[key]
        cue_gaps = list(gaps)
        if identity in ((outcomes or {}).get(key) or {}).get("dropped", ()):
            # The particle reader left this cue out of its own budget: its systems are not drawn.
            cue_gaps.append("particle cue budget of the preview")
            systems = 0
        if index is not None:
            if len(cues) < _MAX_CUES:
                cues.append({**entry, "template": index, "offset": row["offset"], "quality": row["quality"]})
            else:
                cue_gaps.append("prefab cue budget of the preview")
                meshes = 0
        drawn = systems + meshes
        if drawn and not cue_gaps:
            status, note = RENDERED, "The effect prefab is drawn by the common CustomControl rule."
        elif drawn:
            status, note = PARTIAL, f"The effect prefab is drawn in part; not previewed: {_counted(cue_gaps)}."
        elif cue_gaps:
            status, note = NOT_RENDERED, f"The effect prefab is not previewed: {_counted(cue_gaps)}."
        else:
            status = NO_EFFECT
            note = (f"The original prefab draws nothing here: {_counted(quiet)}." if quiet
                    else "The original prefab has no renderer.")
        row = {**entry, "status": status, "note": note}
        if mesh_reasons.get(key):
            # Once per prefab, for the project warning.
            row["meshGaps"] = mesh_reasons.pop(key)
        ledger.append(row)
    for mesh in builder.meshes:
        mesh.pop("_bindPoses", None)
        mesh.pop("_center", None)
    descriptor = None
    if cues:
        descriptor = {"schema": SCHEMA, "textures": builder.textures.levels[shared:], "meshes": builder.meshes,
                      "templates": templates, "cues": cues}
        if shared:
            descriptor["sharedTextures"] = shared
    return descriptor, ledger


def warning(ledger):
    """One project warning naming the prefab mesh content the preview leaves out (per prefab)."""
    reasons = [reason for row in ledger or () for reason in row.get("meshGaps") or ()]
    if not reasons:
        return None
    return f"{len(reasons)} original effect prefab meshes are not previewed: {_counted(reasons)}."


def claims(result):
    """(trackId, eventId) -> per-effect stage reader key, for the cues those readers draw."""
    found = {}
    for key, value in result.items():
        if not key.startswith("stage") or key in ("stageParticleSystems", "stageControlPrefabs"):
            continue
        for identity in particles.claimed_cues({key: value}):
            found.setdefault(identity, key)
    return found
