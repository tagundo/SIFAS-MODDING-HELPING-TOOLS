"""Build a glTF 2.0 binary (GLB) rest-pose preview of a SIFAS model bundle.

The heavy lifting already exists in the repo and is reused here:

  * mesh extraction (vertex streams, indices) -> ``sifas_fbx`` (``stream_layout``,
    ``read_attr``, ``read_indices``), the same functions the FBX exporter uses.
  * rest-pose world-space skinning -> ``fix_sifas_bundle_export`` (``_bone_worlds``,
    ``_bindpose_to_mat``): a skinned vertex at rest sits at ``meshRoot @ v`` where
    ``meshRoot = boneWorld[bone0] @ bindPose[bone0]`` (identical math to that
    module's ``normalize`` / ``validate``), so the model shows in its natural pose
    instead of raw local space.
  * body texture decode -> ``webtools.core.decode.thumbnail`` (the SIGILL-isolated
    subprocess decoder, already cached), embedded as the body mesh's baseColor.

We emit the GLB by hand with ``struct`` + ``json`` (no new dependency), mirroring
how ``sifas_fbx.py`` hand-writes binary FBX. Coordinate handedness: Unity is
left-handed, glTF is right-handed, so X is negated (the same axis the FBX path
mirrors); materials are double-sided so winding never hides a face in the viewer.

``preview(path)`` is the entry point the server calls; it caches on (path, mtime)
exactly like ``decode.thumbnail`` and returns ``None`` on any failure so the
endpoint can fall back to the flat texture thumbnail.
"""
import json
import struct

from . import decode
from .repo import ensure_repo_on_path

# numpy / UnityPy are imported lazily (inside build_glb, after _load_repo_mods
# triggers the repo's on-demand install) so merely importing this module — and
# thus starting the server — never requires the mesh-processing stack.

# (path, mtime) -> GLB bytes; b"" marks a known-failed build so we don't retry.
_CACHE: dict = {}

# glTF component / target constants
_FLOAT = 5126
_UINT = 5125
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963


def _load_repo_mods():
    """Import the repo-root modules whose extraction/skinning code we reuse.
    Importing ``sifas_fbx`` runs its ``_ensure('numpy')`` / ``_ensure('UnityPy')``,
    so numpy and UnityPy are guaranteed importable after this returns."""
    ensure_repo_on_path()
    import fix_sifas_bundle_export as fx
    import sifas_fbx as fbx
    return fbx, fx


def _bone_name_map(uid):
    """path_id (of a Transform) -> its GameObject m_Name, for resolving m_Bones."""
    def bone_name(pid):
        x = uid.get(pid)
        if not x:
            return None
        tt = x.read_typetree()
        g = uid.get(tt.get("m_GameObject", {}).get("m_PathID"))
        return g.read().m_Name if g else None
    return bone_name


def _mesh_rest_geometry(np, fbx, fx, tree, bnames, world):
    """Return (positions Nx3, normals Nx3, uv0 Nx2, faces Mx3) in glTF space, or
    None if the mesh has no usable float positions. Positions/normals are baked to
    the rest world pose and X-negated for glTF's right-handed frame."""
    vc, chans, stride, start, _ = fbx.stream_layout(tree)
    u8 = np.frombuffer(bytearray(tree["m_VertexData"]["m_DataSize"]), np.uint8)
    try:
        pos = fbx.read_attr(u8, chans, fbx.CH_POS, stride, start, vc)
    except NotImplementedError:
        return None  # unsupported vertex format (e.g. half-float) -> preview unavailable
    if pos is None:
        return None
    try:
        nrm = fbx.read_attr(u8, chans, fbx.CH_NORMAL, stride, start, vc)
    except Exception:
        nrm = None
    try:
        uv0 = fbx.read_attr(u8, chans, fbx.CH_UV0, stride, start, vc)
    except Exception:
        uv0 = None

    # rest-pose world transform (constant per mesh): meshRoot = boneWorld @ bindPose
    BP = tree.get("m_BindPose")
    meshRoot = np.eye(4)
    if BP and bnames and bnames[0] in world and len(BP) == len(bnames):
        meshRoot = world[bnames[0]] @ fx._bindpose_to_mat(BP[0])

    pos_h = np.c_[pos, np.ones(len(pos))]
    wpos = (pos_h @ meshRoot.T)[:, :3]
    R = meshRoot[:3, :3]
    if nrm is not None:
        wn = nrm[:, :3] @ R.T
        n = np.linalg.norm(wn, axis=1, keepdims=True)
        n[n == 0] = 1.0
        wn = wn / n
    else:
        wn = np.tile([0.0, 0.0, 1.0], (len(wpos), 1))

    # Unity (left-handed) -> glTF (right-handed): negate X on both position and
    # normal so lighting stays consistent. Materials are double-sided, so the
    # winding flip the mirror causes never hides a triangle.
    wpos = wpos.copy(); wpos[:, 0] *= -1.0
    wn = wn.copy(); wn[:, 0] *= -1.0

    if uv0 is None:
        uv0 = np.zeros((len(wpos), 2))
    uv0 = uv0[:, :2].astype(np.float64)

    faces = fbx.read_indices(tree).reshape(-1, 3)
    return wpos, wn, uv0, faces


def _pad4(buf: bytearray):
    while len(buf) % 4:
        buf.append(0)


def build_glb(bundle_path):
    """Build GLB bytes for ``bundle_path``. Returns bytes, or raises on hard
    failure (no meshes, unreadable bundle)."""
    fbx, fx = _load_repo_mods()
    import numpy as np
    import UnityPy

    env = UnityPy.load(str(bundle_path))
    world, uid = fx._bone_worlds(env)
    bone_name = _bone_name_map(uid)

    smrs = [o for o in env.objects if o.type.name == "SkinnedMeshRenderer"]
    if not smrs:
        raise RuntimeError("no SkinnedMeshRenderer in bundle")

    # the body mesh (most bones) gets the decoded body texture; everything else
    # (hair / face) is drawn with a neutral material — its UVs index other atlases.
    body_smr = fbx.body_smr(env)
    body_mesh_pid = None
    if body_smr is not None:
        body_mesh_pid = body_smr.read_typetree().get("m_Mesh", {}).get("m_PathID")

    prims = []  # (positions, normals, uv0, faces, is_body)
    for smr in smrs:
        tt = smr.read_typetree()
        mesh_ref = tt.get("m_Mesh", {})
        mesh_obj = uid.get(mesh_ref.get("m_PathID"))
        if not mesh_obj:
            continue
        tree = mesh_obj.read_typetree()
        if not tree.get("m_VertexData", {}).get("m_VertexCount"):
            continue
        bnames = [bone_name(b["m_PathID"]) for b in tt.get("m_Bones", [])]
        geo = _mesh_rest_geometry(np, fbx, fx, tree, bnames, world)
        if geo is None:
            continue
        is_body = mesh_ref.get("m_PathID") == body_mesh_pid
        prims.append((*geo, is_body))

    if not prims:
        raise RuntimeError("no renderable mesh (unsupported vertex formats?)")

    # decoded body atlas (SIGILL-isolated, cached); None -> body drawn untextured
    png = decode.thumbnail(bundle_path)
    return _serialize_glb(np, prims, png)


def _serialize_glb(np, prims, png):
    """Serialize ``prims`` (list of (pos Nx3, nrm Nx3, uv0 Nx2, faces Mx3, is_body))
    plus an optional body PNG into GLB bytes. Pure packing — no UnityPy — so it is
    unit-testable from synthetic geometry."""
    # ---- assemble the single GLB binary buffer + glTF accessors ----
    bin_buf = bytearray()
    bufferViews = []
    accessors = []
    meshes = []
    nodes = []

    def add_view(data: bytes, target=None):
        _pad4(bin_buf)
        offset = len(bin_buf)
        bin_buf.extend(data)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        bufferViews.append(view)
        return len(bufferViews) - 1

    def add_accessor(view, comp_type, count, atype, minv=None, maxv=None):
        acc = {"bufferView": view, "componentType": comp_type,
               "count": count, "type": atype}
        if minv is not None:
            acc["min"] = minv
            acc["max"] = maxv
        accessors.append(acc)
        return len(accessors) - 1

    for pos, nrm, uv0, faces, is_body in prims:
        pos32 = np.ascontiguousarray(pos, "<f4")
        nrm32 = np.ascontiguousarray(nrm, "<f4")
        uv32 = np.ascontiguousarray(uv0, "<f4")
        idx32 = np.ascontiguousarray(faces.reshape(-1), "<u4")

        v_pos = add_view(pos32.tobytes(), _ARRAY_BUFFER)
        a_pos = add_accessor(v_pos, _FLOAT, len(pos32), "VEC3",
                             pos32.min(axis=0).tolist(), pos32.max(axis=0).tolist())
        v_nrm = add_view(nrm32.tobytes(), _ARRAY_BUFFER)
        a_nrm = add_accessor(v_nrm, _FLOAT, len(nrm32), "VEC3")
        v_uv = add_view(uv32.tobytes(), _ARRAY_BUFFER)
        a_uv = add_accessor(v_uv, _FLOAT, len(uv32), "VEC2")
        v_idx = add_view(idx32.tobytes(), _ELEMENT_ARRAY_BUFFER)
        a_idx = add_accessor(v_idx, _UINT, len(idx32), "SCALAR")

        material = 0 if (is_body and png) else 1
        meshes.append({"primitives": [{
            "attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "TEXCOORD_0": a_uv},
            "indices": a_idx, "material": material}]})
        nodes.append({"mesh": len(meshes) - 1})

    # ---- materials / texture ----
    materials = [
        # 0: body (textured when a PNG was decoded)
        {"pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1],
                                  "metallicFactor": 0.0, "roughnessFactor": 1.0},
         "doubleSided": True, "name": "body"},
        # 1: neutral (hair / face / untextured body)
        {"pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.82, 1],
                                  "metallicFactor": 0.0, "roughnessFactor": 1.0},
         "doubleSided": True, "name": "neutral"},
    ]
    images = []
    textures = []
    samplers = []
    if png:
        img_view = add_view(png)
        images.append({"bufferView": img_view, "mimeType": "image/png"})
        samplers.append({"wrapS": 10497, "wrapT": 10497})  # REPEAT
        textures.append({"source": 0, "sampler": 0})
        materials[0]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}

    gltf = {
        "asset": {"version": "2.0", "generator": "webtools.core.glb"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": bufferViews,
        "buffers": [{"byteLength": len(bin_buf)}],
    }
    if images:
        gltf["images"] = images
        gltf["textures"] = textures
        gltf["samplers"] = samplers

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(json_bytes) % 4:
        json_bytes += b" "
    _pad4(bin_buf)

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_buf)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)          # "glTF", version 2
    out += struct.pack("<II", len(json_bytes), 0x4E4F534A)      # JSON chunk header
    out += json_bytes
    out += struct.pack("<II", len(bin_buf), 0x004E4942)         # BIN chunk header
    out += bin_buf
    return bytes(out)


def preview(bundle_path, timeout: int = 180):
    """Return GLB bytes for ``bundle_path``, or None on any failure. Cached on
    (path, mtime) so repeat views of the same bundle are instant."""
    import os
    try:
        bundle_path = os.path.realpath(os.path.expanduser(str(bundle_path)))
    except Exception:
        return None
    if not os.path.isfile(bundle_path):
        return None
    try:
        mtime = os.path.getmtime(bundle_path)
    except OSError:
        return None

    key = (bundle_path, mtime)
    if key in _CACHE:
        return _CACHE[key] or None
    try:
        data = build_glb(bundle_path)
        _CACHE[key] = data
        return data
    except Exception:
        _CACHE[key] = b""
        return None
