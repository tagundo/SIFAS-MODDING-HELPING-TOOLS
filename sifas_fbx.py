#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFAS FBX round-trip — export a model bundle to FBX (+textures) and re-import an
edited FBX back into the bundle.
================================================================================
Workflow:
    1. export : .unity bundle  ->  .fbx (skeleton + skinned mesh) + textures (.png)
    2. edit the .fbx in Blender (move vertices, retopo, add geometry...) keeping
       the armature, then export it from Blender as FBX (binary, with the armature)
    3. import : edited .fbx  ->  new .unity bundle (the skinned mesh is rebuilt
       from the FBX: positions / normals / tangents / UV0 / bone weights / indices)

Because export and import share one convention, a bundle exported and re-imported
without any edit reproduces the original mesh (verified by --selftest). The mesh
is rebuilt entirely from the FBX, so topology changes (added/removed vertices,
retopology) are supported as long as the FBX carries the armature + skin weights.

What is exported
    * Every skinned mesh (Body, Hair, Face...) as its own Geometry, sharing one
      skeleton (all bones + ancestors as LimbNodes) with a BindPose.
    * A Material + Texture (the _MainTex of each mesh's material) per mesh, so the
      model shows up textured in Blender. Textures are also written as PNG files to
      --texdir, which the Material nodes reference.
    * The mesh objects and the armature are separate objects bound by the skin
      deformer — that is the normal Blender representation of a rigged model.

Conventions / limits
    * Unity is left-handed; the FBX mirrors X (and flips winding) like AssetStudio,
      so the model looks correct in Blender. Import undoes it.
    * On import each FBX mesh is matched back to a bundle mesh by name; rebuilt
      channels: position, normal, tangent, UV0, vertex color, BlendWeights/Indices
      (<=4), triangle list. Vertex colors round-trip when the FBX carries them (else
      default white); extra UV sets (SIFAS has several) are filled from UV0. Blend
      shapes are not round-tripped (a warning is shown).
    * Import also reads FBX written by AssetStudio (per-vertex "ByVertice" layers and
      vertex colors) and by Blender ("ByPolygonVertex"); export writes per-vertex
      "ByVertice" layers (the form Blender accepts — it rejects "ByControlPoint") with
      vertex colors and zlib-compressed arrays.
    * Verified on Unity 2018.4 uncompressed SIFAS member bundles (float streams).

Usage
    python3 sifas_fbx.py                          # no command -> opens the browser UI
    python3 sifas_fbx.py export --in model.unity --out model.fbx [--texdir tex]
    python3 sifas_fbx.py import --fbx model.fbx --bundle model.unity --out new.unity
    python3 sifas_fbx.py selftest --in model.unity
"""

import os
import sys
import json
import struct
import zlib
import argparse
import importlib
import subprocess


def _pip(p):
    for extra in (["--break-system-packages", "-q"], ["-q"]):
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", p] + extra, check=True)
            return True
        except Exception:
            pass
    return False


def _ensure(mod, pip=None):
    try:
        return importlib.import_module(mod)
    except ImportError:
        _pip(pip or mod)
        return importlib.import_module(mod)


np = _ensure("numpy")
UnityPy = _ensure("UnityPy")

FMT_BYTES = {0: 4, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2, 6: 1, 7: 1, 8: 2, 9: 2, 10: 4, 11: 4}
# Unity 2018 vertex channel order
CH_POS, CH_NORMAL, CH_TANGENT, CH_COLOR, CH_UV0 = 0, 1, 2, 3, 4
CH_BLENDWEIGHT, CH_BLENDINDICES = 12, 13
MIRROR = np.diag([-1.0, 1.0, 1.0, 1.0])   # Unity <-> FBX (mirror X)


# ==========================================================================
# vertex stream IO
# ==========================================================================
def _align16(x):
    return (x + 15) & ~15


def stream_layout(tree):
    vd = tree["m_VertexData"]
    vc = vd["m_VertexCount"]
    chans = vd["m_Channels"]
    by_stream = {}
    for ch in chans:
        if ch.get("dimension", 0):
            by_stream.setdefault(ch["stream"], []).append(ch)
    stride, start, cur = {}, {}, 0
    for s in sorted(by_stream):
        stride[s] = max(c["offset"] + c["dimension"] * FMT_BYTES[c["format"]] for c in by_stream[s])
    for s in sorted(by_stream):
        start[s] = cur
        cur = _align16(cur + vc * stride[s])
    return vc, chans, stride, start, cur


def _block(u8, s, stride, start, vc):
    return u8[start[s]:start[s] + vc * stride[s]].reshape(vc, stride[s])


def read_attr(u8, chans, attr, stride, start, vc):
    ch = chans[attr]
    if ch.get("dimension", 0) == 0:
        return None
    s, off, dim, fmt = ch["stream"], ch["offset"], ch["dimension"], ch["format"]
    raw = _block(u8, s, stride, start, vc)[:, off:off + dim * FMT_BYTES[fmt]]
    if fmt == 0:
        return raw.copy().view("<f4").reshape(vc, dim).astype(np.float64)
    if fmt == 11:
        return raw.copy().view("<i4").reshape(vc, dim).astype(np.int64)
    if fmt == 10:
        return raw.copy().view("<u4").reshape(vc, dim).astype(np.int64)
    if fmt == 2:                       # unorm8 (e.g. vertex color) -> 0..1 float
        return raw.copy().reshape(vc, dim).astype(np.float64) / 255.0
    raise NotImplementedError(f"vertex format {fmt}")


def write_attr(u8, arr, chans, attr, stride, start, vc):
    ch = chans[attr]
    s, off, dim, fmt = ch["stream"], ch["offset"], ch["dimension"], ch["format"]
    block = _block(u8, s, stride, start, vc)
    if fmt == 0:
        packed = np.ascontiguousarray(arr[:, :dim], "<f4").view(np.uint8)
        block[:, off:off + dim * 4] = packed.reshape(vc, dim * 4)
    elif fmt == 11:
        packed = np.ascontiguousarray(arr[:, :dim], "<i4").view(np.uint8)
        block[:, off:off + dim * 4] = packed.reshape(vc, dim * 4)
    elif fmt == 2:   # unorm8 (e.g. vertex color)
        u = np.clip(arr[:, :dim] * 255.0 + 0.5, 0, 255).astype(np.uint8)
        block[:, off:off + dim] = u
    else:
        raise NotImplementedError(f"write vertex format {fmt}")


def read_indices(tree):
    fmt = tree.get("m_IndexFormat", 0)
    buf = bytes(tree["m_IndexBuffer"])
    return np.frombuffer(buf, "<u2" if fmt == 0 else "<u4").astype(np.int64)


# ==========================================================================
# bone transforms
# ==========================================================================
def _quat_mat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y), 0],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x), 0],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y), 0],
                     [0, 0, 0, 1]], float)


def _trs(t, q, s):
    M = _quat_mat(q)
    M[:3, 0] *= s[0]; M[:3, 1] *= s[1]; M[:3, 2] *= s[2]
    M[0, 3], M[1, 3], M[2, 3] = t
    return M


def _mat_to_euler_xyz(R):
    sy = (R[0, 0] ** 2 + R[1, 0] ** 2) ** 0.5
    if sy > 1e-7:
        x = np.arctan2(R[2, 1], R[2, 2]); y = np.arctan2(-R[2, 0], sy); z = np.arctan2(R[1, 0], R[0, 0])
    else:
        x = np.arctan2(-R[1, 2], R[1, 1]); y = np.arctan2(-R[2, 0], sy); z = 0.0
    return np.degrees([x, y, z])


def bundle_skeleton(env):
    """Return dicts keyed by GO name: local matrix, world matrix, parent name,
    plus a Transform-pathid map and the GO names of every transform."""
    uid = {o.path_id: o for o in env.objects}
    tf = {}
    for o in env.objects:
        if o.type.name == "Transform":
            t = o.read_typetree()
            g = uid.get(t.get("m_GameObject", {}).get("m_PathID"))
            n = g.read().m_Name if g else None
            lp, lr, ls = t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"]
            tf[o.path_id] = (n,
                             _trs([lp['x'], lp['y'], lp['z']],
                                  [lr['x'], lr['y'], lr['z'], lr['w']],
                                  [ls['x'], ls['y'], ls['z']]),
                             t.get('m_Father', {}).get('m_PathID'),
                             [c['m_PathID'] for c in t.get('m_Children', [])])
    local, world, parent, name2pid = {}, {}, {}, {}
    for pid, (n, M, fa, ch) in tf.items():
        if n is not None:
            local[n] = M
            name2pid[n] = pid

    def cw(pid, P, pname):
        n, M, fa, ch = tf[pid]
        W = P @ M
        if n is not None:
            world[n] = W
            parent[n] = pname
        for c in ch:
            if c in tf:
                cw(c, W, n)
    for pid, (n, M, fa, ch) in tf.items():
        if fa not in tf:
            cw(pid, np.eye(4), None)
    return local, world, parent, name2pid, uid


def _bindpose_to_mat(b):
    return np.array([[b['e00'], b['e01'], b['e02'], b['e03']],
                     [b['e10'], b['e11'], b['e12'], b['e13']],
                     [b['e20'], b['e21'], b['e22'], b['e23']],
                     [b['e30'], b['e31'], b['e32'], b['e33']]], float)


def _mat_to_bindpose(M):
    return {"e%d%d" % (r, c): float(M[r, c]) for r in range(4) for c in range(4)}


def body_smr(env):
    best, best_n = None, -1
    for o in env.objects:
        if o.type.name == "SkinnedMeshRenderer":
            n = len(o.read_typetree().get("m_Bones", []))
            if n > best_n:
                best_n, best = n, o
    return best


# ==========================================================================
# binary FBX writer
# ==========================================================================
class FNode:
    __slots__ = ("name", "props", "children")

    def __init__(self, name, props=None, children=None):
        self.name = name; self.props = props or []; self.children = children or []

    def add(self, *c):
        self.children.extend(c); return self


def _prop_bytes(t, v):
    if t == 'I': return b'I' + struct.pack('<i', v)
    if t == 'L': return b'L' + struct.pack('<q', v)
    if t == 'D': return b'D' + struct.pack('<d', v)
    if t == 'C': return b'C' + struct.pack('<?', bool(v))
    if t == 'S':
        b = v.encode('utf-8') if isinstance(v, str) else v
        return b'S' + struct.pack('<I', len(b)) + b
    if t in 'dilf':
        fmt = {'d': 'd', 'i': 'i', 'l': 'q', 'f': 'f'}[t]
        arr = np.ascontiguousarray(v, fmt if fmt != 'q' else '<i8')
        raw = arr.tobytes()
        enc, payload = 0, raw                       # zlib-compress big arrays (like AssetStudio)
        if len(raw) >= 256:
            comp = zlib.compress(raw)
            if len(comp) < len(raw):
                enc, payload = 1, comp
        return t.encode() + struct.pack('<III', len(arr), enc, len(payload)) + payload
    raise ValueError(t)


def fbx_serialize(roots, version=7500):
    out = bytearray()
    out += b'Kaydara FBX Binary  \x00' + b'\x1a\x00' + struct.pack('<I', version)

    def write(n):
        start = len(out)
        name = n.name.encode('utf-8')
        props = b''.join(_prop_bytes(t, v) for t, v in n.props)
        out.extend(struct.pack('<QQQ', 0, len(n.props), len(props)))
        out.append(len(name)); out.extend(name); out.extend(props)
        for c in n.children:
            write(c)
        if n.children:
            out.extend(b'\x00' * 25)
        struct.pack_into('<Q', out, start, len(out))
    for r in roots:
        write(r)
    out.extend(b'\x00' * 25)
    out.extend(b'\x00' * ((16 - (len(out) % 16)) % 16))
    out.extend(b'\xfa\xbc\xab\x09\xd0\xc8\xd4\x66\xb1\x76\xfb\x83\x1c\xf7\x26\x7e')
    out.extend(b'\x00' * 4)
    out.extend(struct.pack('<I', version))
    out.extend(b'\x00' * 120)
    out.extend(b'\xf8\x5a\x8c\x6a\xde\xf5\xd9\x7e\xec\xe9\x0c\xe3\x75\x05\xa0\x47')
    return bytes(out)


def _name_class(name, cls):
    return name + "\x00\x01" + cls


_uid = [1000000]


def _nid():
    _uid[0] += 1
    return _uid[0]


# ==========================================================================
# EXPORT  (bundle -> FBX + textures)
# ==========================================================================
def _geo_and_skin(mesh, smr_tt, bones, world, bone_model_id, geo_id, name):
    """Build the Geometry node (+ optional Skin/Cluster nodes) for one mesh.
    Returns (geo_node, skin_node_or_None, cluster_nodes, cluster_ids_by_bone)."""
    vc, chans, stride, start, _ = stream_layout(mesh)
    u8 = np.frombuffer(bytearray(mesh["m_VertexData"]["m_DataSize"]), np.uint8)
    pos = read_attr(u8, chans, CH_POS, stride, start, vc)
    nrm = read_attr(u8, chans, CH_NORMAL, stride, start, vc)
    tan = read_attr(u8, chans, CH_TANGENT, stride, start, vc)
    uv0 = read_attr(u8, chans, CH_UV0, stride, start, vc)
    try:
        col = read_attr(u8, chans, CH_COLOR, stride, start, vc)   # vertex color (may be None)
    except Exception:
        col = None
    has_skin = chans[CH_BLENDWEIGHT].get("dimension", 0) and chans[CH_BLENDINDICES].get("dimension", 0)
    bw = read_attr(u8, chans, CH_BLENDWEIGHT, stride, start, vc) if has_skin else None
    bi = read_attr(u8, chans, CH_BLENDINDICES, stride, start, vc) if has_skin else None
    tris = read_indices(mesh).reshape(-1, 3)

    posF = pos.copy(); posF[:, 0] *= -1
    nrmF = (nrm.copy() if nrm is not None else None)
    if nrmF is not None:
        nrmF[:, 0] *= -1
    tanF = (tan.copy() if tan is not None else None)
    if tanF is not None:
        tanF[:, 0] *= -1
    trisF = tris[:, ::-1]

    pvi = []
    for a, b, c in trisF:
        pvi += [int(a), int(b), int(c) ^ -1]
    # per-control-point ("ByVertice") layers — the exact convention AssetStudio uses
    # and the one Blender's FBX importer accepts (it rejects "ByControlPoint"). Smaller
    # files than per-corner; the importer reads it back. Unity already splits seam verts.
    geo = FNode("Geometry", [('L', geo_id), ('S', _name_class(name, "Geometry")), ('S', "Mesh")]).add(
        FNode("GeometryVersion", [('I', 124)]),
        FNode("Vertices", [('d', posF.reshape(-1))]),
        FNode("PolygonVertexIndex", [('i', pvi)]))
    if nrmF is not None:
        geo.add(FNode("LayerElementNormal", [('I', 0)]).add(
            FNode("Version", [('I', 101)]), FNode("Name", [('S', "")]),
            FNode("MappingInformationType", [('S', "ByVertice")]),
            FNode("ReferenceInformationType", [('S', "Direct")]),
            FNode("Normals", [('d', nrmF.reshape(-1))])))
    if tanF is not None:
        geo.add(FNode("LayerElementTangent", [('I', 0)]).add(
            FNode("Version", [('I', 101)]), FNode("Name", [('S', "tangent")]),
            FNode("MappingInformationType", [('S', "ByVertice")]),
            FNode("ReferenceInformationType", [('S', "Direct")]),
            FNode("Tangents", [('d', tanF[:, :3].reshape(-1))])))
    if uv0 is not None:
        geo.add(FNode("LayerElementUV", [('I', 0)]).add(
            FNode("Version", [('I', 101)]), FNode("Name", [('S', "UVMap")]),
            FNode("MappingInformationType", [('S', "ByVertice")]),
            FNode("ReferenceInformationType", [('S', "Direct")]),
            FNode("UV", [('d', uv0.reshape(-1))])))
    if col is not None and col.ndim == 2 and col.shape[1] >= 3:
        rgba = col[:, :4].reshape(-1) if col.shape[1] >= 4 else \
            np.concatenate([col[:, :3], np.ones((vc, 1))], axis=1).reshape(-1)
        geo.add(FNode("LayerElementColor", [('I', 0)]).add(
            FNode("Version", [('I', 101)]), FNode("Name", [('S', "")]),
            FNode("MappingInformationType", [('S', "ByVertice")]),
            FNode("ReferenceInformationType", [('S', "Direct")]),
            FNode("Colors", [('d', rgba)])))
    geo.add(FNode("LayerElementMaterial", [('I', 0)]).add(
        FNode("Version", [('I', 101)]), FNode("Name", [('S', "")]),
        FNode("MappingInformationType", [('S', "AllSame")]),
        FNode("ReferenceInformationType", [('S', "IndexToDirect")]),
        FNode("Materials", [('i', [0])])))
    layer = FNode("Layer", [('I', 0)]).add(FNode("Version", [('I', 100)]))
    for et in ("LayerElementNormal", "LayerElementTangent", "LayerElementUV",
               "LayerElementColor", "LayerElementMaterial"):
        if any(c.name == et for c in geo.children):
            layer.add(FNode("LayerElement").add(FNode("Type", [('S', et)]), FNode("TypedIndex", [('I', 0)])))
    geo.add(layer)

    skin = None
    clusters = []
    cl_ids = {}
    if has_skin:
        skin = FNode("Deformer", [('L', _nid()), ('S', _name_class("", "Deformer")), ('S', "Skin")]).add(
            FNode("Version", [('I', 101)]))
        smr_bones = [b for b in bones]
        for bone_idx, n in enumerate(smr_bones):
            if n is None or n not in bone_model_id:
                continue
            sel = bi == bone_idx
            vids = np.where(sel.any(axis=1))[0]
            if len(vids) == 0:
                continue
            wlist = [float(bw[v][bi[v] == bone_idx].sum()) for v in vids]
            ilist = [int(v) for v in vids]
            cid = _nid(); cl_ids[n] = cid
            TL = MIRROR @ world.get(n, np.eye(4)) @ MIRROR
            clusters.append(FNode("Deformer", [('L', cid), ('S', _name_class(n, "SubDeformer")), ('S', "Cluster")]).add(
                FNode("Version", [('I', 100)]),
                FNode("Indexes", [('i', ilist)]),
                FNode("Weights", [('d', wlist)]),
                FNode("Transform", [('d', np.eye(4).T.reshape(-1))]),
                FNode("TransformLink", [('d', TL.T.reshape(-1))])))
    return geo, skin, clusters, cl_ids, has_skin


def _material_nodes(mat_name, tex_name, texdir):
    """Return (material_node, texture_node_or_None, video_node_or_None, ids)."""
    mat_id, tex_id, vid_id = _nid(), _nid(), _nid()
    mat = FNode("Material", [('L', mat_id), ('S', _name_class(mat_name or "mat", "Material")), ('S', "")]).add(
        FNode("Version", [('I', 102)]), FNode("ShadingModel", [('S', "phong")]),
        FNode("Properties70").add(
            FNode("P", [('S', "DiffuseColor"), ('S', "Color"), ('S', ""), ('S', "A"),
                        ('D', 0.8), ('D', 0.8), ('D', 0.8)])))
    tex = vid = None
    if tex_name:
        rel = tex_name + ".png"
        absn = os.path.join(texdir, rel) if texdir else rel
        vid = FNode("Video", [('L', vid_id), ('S', _name_class(tex_name, "Video")), ('S', "Clip")]).add(
            FNode("Type", [('S', "Clip")]),
            FNode("FileName", [('S', absn)]), FNode("RelativeFilename", [('S', rel)]))
        tex = FNode("Texture", [('L', tex_id), ('S', _name_class(tex_name, "Texture")), ('S', "")]).add(
            FNode("Type", [('S', "TextureVideoClip")]), FNode("Version", [('I', 202)]),
            FNode("TextureName", [('S', tex_name)]),
            FNode("Media", [('S', "Video::" + tex_name)]),
            FNode("FileName", [('S', absn)]), FNode("RelativeFilename", [('S', rel)]),
            FNode("Properties70"))
    return mat, tex, vid, (mat_id, tex_id, vid_id)


def export(in_path, out_path, texdir=None, verbose=True):
    def log(*a):
        if verbose:
            print(*a)
    env = UnityPy.load(in_path)
    local, world, parent, name2pid, uid = bundle_skeleton(env)

    # all skinned-mesh renderers
    smrs = [o for o in env.objects if o.type.name == "SkinnedMeshRenderer"]
    if not smrs:
        raise RuntimeError("no SkinnedMeshRenderer found")

    def bone_name(pid):
        o = uid.get(pid)
        if not o:
            return None
        t = o.read_typetree()
        g = uid.get(t.get("m_GameObject", {}).get("m_PathID"))
        return g.read().m_Name if g else None

    # ---- skeleton: every bone used by any mesh + all ancestors ----
    bone_set = set()
    for smr in smrs:
        for b in smr.read_typetree().get("m_Bones", []):
            n = bone_name(b["m_PathID"])
            if n:
                bone_set.add(n)
    changed = True
    while changed:
        changed = False
        for n in list(bone_set):
            p = parent.get(n)
            if p and p not in bone_set:
                bone_set.add(p); changed = True
    bone_model_id = {n: _nid() for n in bone_set}

    objects = FNode("Objects")
    conns = FNode("Connections")
    pose = FNode("Pose", [('L', _nid()), ('S', _name_class("BindPose", "Pose")), ('S', "BindPose")]).add(
        FNode("Type", [('S', "BindPose")]), FNode("Version", [('I', 100)]),
        FNode("NbPoseNodes", [('I', len(bone_model_id))]))

    for n, mid in bone_model_id.items():
        Ln = local.get(n, np.eye(4))
        t = Ln[:3, 3].copy(); t[0] *= -1
        Rm = MIRROR[:3, :3] @ Ln[:3, :3] @ MIRROR[:3, :3]
        eul = _mat_to_euler_xyz(Rm)
        objects.add(FNode("Model", [('L', mid), ('S', _name_class(n, "Model")), ('S', "LimbNode")]).add(
            FNode("Version", [('I', 232)]),
            FNode("Properties70").add(
                FNode("P", [('S', "Lcl Translation"), ('S', "Lcl Translation"), ('S', ""), ('S', "A"),
                            ('D', float(t[0])), ('D', float(t[1])), ('D', float(t[2]))]),
                FNode("P", [('S', "Lcl Rotation"), ('S', "Lcl Rotation"), ('S', ""), ('S', "A"),
                            ('D', float(eul[0])), ('D', float(eul[1])), ('D', float(eul[2]))]))))
        p = parent.get(n)
        conns.add(FNode("C", [('S', "OO"), ('L', mid), ('L', bone_model_id.get(p, 0))]))
        TL = MIRROR @ world.get(n, np.eye(4)) @ MIRROR
        pose.add(FNode("PoseNode").add(FNode("Node", [('L', mid)]), FNode("Matrix", [('d', TL.T.reshape(-1))])))

    n_models = len(bone_model_id)
    n_def = 0
    tex_done = {}
    total_v = total_t = 0
    for smr in smrs:
        smr_tt = smr.read_typetree()
        mesh_obj = uid[smr_tt["m_Mesh"]["m_PathID"]]
        mesh = mesh_obj.read_typetree()
        mname = mesh.get("m_Name", "mesh")
        mbones = [bone_name(b["m_PathID"]) for b in smr_tt.get("m_Bones", [])]
        if mesh.get("m_Shapes", {}).get("shapes"):
            log(f"[warn] {mname}: blend shapes not round-tripped")
        geo_id = _nid()
        geo, skin, clusters, cl_ids, has_skin = _geo_and_skin(
            mesh, smr_tt, mbones, world, bone_model_id, geo_id, mname)
        mesh_model_id = _nid()
        objects.add(FNode("Model", [('L', mesh_model_id), ('S', _name_class(mname, "Model")), ('S', "Mesh")]).add(
            FNode("Version", [('I', 232)]),
            FNode("Properties70").add(
                FNode("P", [('S', "Lcl Scaling"), ('S', "Lcl Scaling"), ('S', ""), ('S', "A"),
                            ('D', 1.0), ('D', 1.0), ('D', 1.0)]))))
        objects.add(geo)
        conns.add(FNode("C", [('S', "OO"), ('L', mesh_model_id), ('L', 0)]))
        conns.add(FNode("C", [('S', "OO"), ('L', geo_id), ('L', mesh_model_id)]))
        n_models += 1
        if has_skin and skin is not None:
            objects.add(skin)
            conns.add(FNode("C", [('S', "OO"), ('L', skin.props[0][1]), ('L', geo_id)]))
            for c in clusters:
                objects.add(c)
            for n, cid in cl_ids.items():
                conns.add(FNode("C", [('S', "OO"), ('L', cid), ('L', skin.props[0][1])]))
                conns.add(FNode("C", [('S', "OO"), ('L', bone_model_id[n]), ('L', cid)]))
            n_def += 1 + len(clusters)
        # material + texture
        matname = maintex = None
        mats = smr_tt.get("m_Materials", [])
        if mats:
            mt = uid.get(mats[0]["m_PathID"])
            if mt:
                mtt = mt.read_typetree(); matname = mtt.get("m_Name")
                for nm, envp in mtt.get("m_SavedProperties", {}).get("m_TexEnvs", []):
                    if nm == "_MainTex" and envp.get("m_Texture", {}).get("m_PathID"):
                        tx = uid.get(envp["m_Texture"]["m_PathID"])
                        maintex = tx.read().m_Name if tx else None
        mat, tex, vid, (mat_id, tex_id, vid_id) = _material_nodes(matname, maintex, texdir)
        objects.add(mat)
        conns.add(FNode("C", [('S', "OO"), ('L', mat_id), ('L', mesh_model_id)]))
        if tex is not None and maintex not in tex_done:
            objects.add(vid); objects.add(tex)
            conns.add(FNode("C", [('S', "OP"), ('L', tex_id), ('L', mat_id), ('S', "DiffuseColor")]))
            conns.add(FNode("C", [('S', "OO"), ('L', vid_id), ('L', tex_id)]))
            tex_done[maintex] = tex_id
        elif tex is not None:
            conns.add(FNode("C", [('S', "OP"), ('L', tex_done[maintex]), ('L', mat_id), ('S', "DiffuseColor")]))
        vc = mesh["m_VertexData"]["m_VertexCount"]
        nt = read_indices(mesh).size // 3
        total_v += vc; total_t += nt
        log(f"[ok] mesh '{mname}': {vc} verts, {nt} tris, {'skinned' if has_skin else 'static'}")

    objects.add(pose)

    header = FNode("FBXHeaderExtension").add(
        FNode("FBXHeaderVersion", [('I', 1003)]), FNode("FBXVersion", [('I', 7500)]),
        FNode("Creator", [('S', "sifas_fbx.py")]))
    gs = FNode("GlobalSettings").add(FNode("Version", [('I', 1000)]), FNode("Properties70").add(
        FNode("P", [('S', "UpAxis"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 1)]),
        FNode("P", [('S', "UpAxisSign"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 1)]),
        FNode("P", [('S', "FrontAxis"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 2)]),
        FNode("P", [('S', "FrontAxisSign"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 1)]),
        FNode("P", [('S', "CoordAxis"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 0)]),
        FNode("P", [('S', "CoordAxisSign"), ('S', "int"), ('S', "Integer"), ('S', ""), ('I', 1)]),
        FNode("P", [('S', "UnitScaleFactor"), ('S', "double"), ('S', "Number"), ('S', ""), ('D', 1.0)])))
    documents = FNode("Documents").add(
        FNode("Count", [('I', 1)]),
        FNode("Document", [('L', _nid()), ('S', "Scene"), ('S', "Scene")]).add(FNode("RootNode", [('I', 0)])))
    definitions = FNode("Definitions").add(
        FNode("Version", [('I', 100)]), FNode("Count", [('I', n_models + n_def + len(tex_done) * 2 + 5)]),
        FNode("ObjectType", [('S', "Model")]).add(FNode("Count", [('I', n_models)])),
        FNode("ObjectType", [('S', "Geometry")]).add(FNode("Count", [('I', len(smrs))])),
        FNode("ObjectType", [('S', "Material")]).add(FNode("Count", [('I', len(smrs))])),
        FNode("ObjectType", [('S', "Texture")]).add(FNode("Count", [('I', len(tex_done))])),
        FNode("ObjectType", [('S', "Video")]).add(FNode("Count", [('I', len(tex_done))])),
        FNode("ObjectType", [('S', "Deformer")]).add(FNode("Count", [('I', n_def)])),
        FNode("ObjectType", [('S', "Pose")]).add(FNode("Count", [('I', 1)])))
    takes = FNode("Takes").add(FNode("Current", [('S', "")]))

    with open(out_path, "wb") as f:
        f.write(fbx_serialize([header, gs, documents, definitions, objects, conns, takes]))
    log(f"[ok] exported {len(smrs)} mesh(es), {total_v} verts, {total_t} tris, "
        f"{len(bone_model_id)} bones -> {out_path}")

    if texdir:
        export_textures_isolated(in_path, texdir, log)
    return out_path


def _decode_one_texture(bundle_path, name, out_png):
    """Decode a single Texture2D to PNG (run in a child process)."""
    env = UnityPy.load(bundle_path)
    for o in env.objects:
        if o.type.name == "Texture2D" and o.read().m_Name == name:
            o.read().image.save(out_png)
            return 0
    return 2


def export_textures_isolated(bundle_path, texdir, log=lambda *a: None):
    """Export every texture to PNG, decoding each in a CHILD process so a native
    decoder crash (e.g. a Crunch-compressed texture segfaulting texture2ddecoder
    on macOS) only loses that one texture instead of killing the whole program."""
    os.makedirs(texdir, exist_ok=True)
    env = UnityPy.load(bundle_path)
    names = [o.read().m_Name for o in env.objects if o.type.name == "Texture2D"]
    ok = 0
    for nm in names:
        out = os.path.join(texdir, nm + ".png")
        try:
            r = subprocess.run([sys.executable, os.path.abspath(__file__),
                                "__decode_tex", bundle_path, nm, out],
                               capture_output=True, timeout=180)
            if r.returncode == 0 and os.path.exists(out):
                ok += 1
            else:
                log(f"[warn] texture '{nm}': decode failed (crunched/native crash?) — skipped")
        except Exception as ex:
            log(f"[warn] texture '{nm}': {ex}")
    log(f"[ok] exported {ok}/{len(names)} textures -> {texdir}")
    return ok


# ==========================================================================
# IMPORT  (edited FBX -> bundle)
# ==========================================================================
class _FbxNode:
    __slots__ = ("name", "props", "parr", "children")

    def __init__(self, name):
        self.name = name
        self.props = []
        self.parr = {}
        self.children = []

    def first(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None

    def findall(self, name):
        return [c for c in self.children if c.name == name]


class _FbxReader:
    """Minimal binary-FBX reader (versions 7.4 / 7.5), self-contained."""

    def __init__(self, path):
        self.buf = bytearray(open(path, "rb").read())
        if self.buf[:20] != b'Kaydara FBX Binary  ':
            raise ValueError("not a binary FBX (it looks like an ASCII FBX, or isn't an FBX). "
                             "Re-export from Blender as BINARY FBX (untick the 'ASCII' option).")
        self.version = struct.unpack("<I", self.buf[23:27])[0]
        primary = 8 if self.version >= 7500 else 4
        last = None
        for W in (primary, 12 - primary):      # auto-detect 32- vs 64-bit node records (4<->8)
            self.W = W
            try:
                root = self._parse()
            except Exception as ex:
                last = ex
                continue
            if root.first("Objects") is not None:   # sanity: a real FBX has an Objects section
                self.root = root
                return
            last = last or ValueError("parsed but no Objects section")
        raise ValueError("could not parse this FBX (version %d) — it may be corrupt or an "
                         "unsupported variant. Last error: %s" % (self.version, last))

    def _parse(self):
        d, W = self.buf, self.W
        NULL = 3 * W + 1

        def ru(p):
            return int.from_bytes(d[p:p + W], "little")

        def read_prop(p, node, idx):
            t = chr(d[p]); p += 1
            if t == 'Y': v = struct.unpack_from("<h", d, p)[0]; p += 2
            elif t == 'C': v = bool(d[p]); p += 1
            elif t == 'I': v = struct.unpack_from("<i", d, p)[0]; p += 4
            elif t == 'F': v = struct.unpack_from("<f", d, p)[0]; p += 4
            elif t == 'D': v = struct.unpack_from("<d", d, p)[0]; p += 8
            elif t == 'L': v = struct.unpack_from("<q", d, p)[0]; p += 8
            elif t in ('R', 'S'):
                ln = struct.unpack_from("<I", d, p)[0]; p += 4
                v = bytes(d[p:p + ln]); p += ln
                if t == 'S':
                    v = v.decode("utf-8", "replace")
            elif t in ('f', 'd', 'l', 'i', 'b'):
                al, enc, cl = struct.unpack_from("<III", d, p); p += 12
                node.parr[idx] = (t, enc, al, p)
                raw = bytes(d[p:p + cl]); p += cl
                if enc == 1:
                    raw = zlib.decompress(raw)
                fmt = {'f': 'f', 'd': 'd', 'l': 'q', 'i': 'i', 'b': 'b'}[t]
                v = list(struct.unpack("<%d%s" % (al, fmt), raw))
            else:
                raise ValueError("bad FBX property type %r" % t)
            node.props.append(v)
            return p

        def read_node(p):
            end = ru(p); nprops = ru(p + W); plen = ru(p + 2 * W); nl = d[p + 3 * W]
            if end == 0 and nprops == 0 and plen == 0 and nl == 0:
                return None, p + NULL
            p2 = p + 3 * W + 1
            name = bytes(d[p2:p2 + nl]).decode("utf-8", "replace"); p2 += nl
            ps = p2
            node = _FbxNode(name)
            for i in range(nprops):
                p2 = read_prop(p2, node, i)
            p2 = ps + plen
            while p2 < end:
                child, p2 = read_node(p2)
                if child is None:
                    break
                node.children.append(child)
            return node, end

        root = _FbxNode("__root__")
        pos = 27
        while pos < len(d) - NULL:
            if ru(pos) == 0:
                break
            n, pos = read_node(pos)
            if n is None:
                break
            root.children.append(n)
        return root


def _fbx_reader():
    return _FbxReader


def _RX(a): c, s = np.cos(a), np.sin(a); return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
def _RY(a): c, s = np.cos(a), np.sin(a); return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
def _RZ(a): c, s = np.cos(a), np.sin(a); return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _fbx_world_matrices(fbx):
    """World 4x4 matrix of every FBX Model, composed from Lcl transforms (incl.
    PreRotation and Lcl Scaling) down the Connections hierarchy. Returns
    (world_by_id, name_by_id, models)."""
    objs = fbx.root.first("Objects")
    conns = fbx.root.first("Connections")
    models = {m.props[0]: m for m in objs.findall("Model")}
    name = {i: m.props[1].split("\x00\x01")[0] for i, m in models.items()}
    parent = {}
    for c in conns.findall("C"):
        if c.props[0] == "OO" and c.props[1] in models and c.props[2] in models:
            parent[c.props[1]] = c.props[2]

    def lcl(m):
        pp = {}
        p70 = m.first("Properties70")
        if p70:
            for P in p70.findall("P"):
                pp[P.props[0]] = [float(x) for x in P.props[4:]]
        T = pp.get("Lcl Translation", [0, 0, 0])
        R = pp.get("Lcl Rotation", [0, 0, 0])
        Sc = pp.get("Lcl Scaling", [1, 1, 1])
        pre = pp.get("PreRotation", [0, 0, 0])
        rx, ry, rz = np.radians(R); px, py, pz = np.radians(pre)
        M = np.eye(4)
        M[:3, :3] = (_RZ(pz) @ _RY(py) @ _RX(px)) @ (_RZ(rz) @ _RY(ry) @ _RX(rx)) @ np.diag(Sc)
        M[:3, 3] = T
        return M

    world = {}

    def gw(i):
        if i in world:
            return world[i]
        p = parent.get(i)
        world[i] = (gw(p) if p in models else np.eye(4)) @ lcl(models[i])
        return world[i]
    for i in models:
        gw(i)
    return world, name, models


def _fbx_bone_worlds(fbx):
    """World translation of every Model node (bone) keyed by name (first wins)."""
    world, name, models = _fbx_world_matrices(fbx)
    out = {}
    for i in models:
        out.setdefault(name[i], world[i][:3, 3])
    return out


def _fit_transform(src, dst):
    """Least-squares similarity transform: dst ≈ M @ src + t where M = scale*Rotation
    (uniform scale + rotation + reflection allowed). Handles exporters that use a
    different unit scale (e.g. Blender FBX is often 100x the Unity bundle: cm vs m).
    Returns (M 3x3, t 3, rms residual)."""
    src = np.asarray(src, float); dst = np.asarray(dst, float)
    mu_s, mu_d = src.mean(0), dst.mean(0)
    S, D = src - mu_s, dst - mu_d
    H = D.T @ S
    U, _, Vt = np.linalg.svd(H)
    R = U @ Vt                      # rotation/reflection (reflection NOT corrected)
    denom = float((S ** 2).sum())
    scale = float(np.sum(D * (S @ R.T)) / denom) if denom > 1e-12 else 1.0
    M = scale * R
    t = mu_d - M @ mu_s
    res = dst - (src @ M.T + t)
    rms = float(np.sqrt((res ** 2).sum(1).mean()))
    return M, t, rms


def apply_textures(env, texdir, log=lambda *a: None):
    """Re-encode edited images (PNG/TGA/JPG named like the texture) back into the
    bundle's matching Texture2D objects, keeping each texture's original format."""
    from PIL import Image
    imgs = {}
    for fn in os.listdir(texdir):
        stem, ext = os.path.splitext(fn)
        if ext.lower() in (".png", ".tga", ".jpg", ".jpeg", ".bmp"):
            imgs.setdefault(stem, os.path.join(texdir, fn))
    n = 0
    for o in env.objects:
        if o.type.name != "Texture2D":
            continue
        d = o.read()
        p = imgs.get(d.m_Name)
        if not p:
            continue
        img = Image.open(p).convert("RGBA")
        try:
            d.set_image(img, target_format=d.m_TextureFormat)
            d.save()
            n += 1
            log(f"[ok] texture imported: {d.m_Name} <- {os.path.basename(p)} "
                f"({img.size[0]}x{img.size[1]})")
        except Exception as ex:
            log(f"[warn] texture {d.m_Name}: {ex}")
    return n


def import_textures_only(texdir, bundle_path, out_path, verbose=True):
    def log(*a):
        if verbose:
            print(*a)
    env = UnityPy.load(bundle_path)
    n = apply_textures(env, texdir, log)
    bf = list(env.files.values())[0]
    bf.mark_changed()
    with open(out_path, "wb") as f:
        f.write(bf.save(packer="original"))
    log(f"[done] imported {n} texture(s) -> {out_path}")
    return out_path


def _compute_tangents(pos, nrm, uv, tris):
    """Per-vertex tangent (xyz) + handedness (w) from positions, normals and UV0
    (Lengyel's method). Used when the FBX carries no tangents (e.g. a Blender export
    without 'Tangent Space') so SIFAS normal-map shaders still get real tangents."""
    pos = np.asarray(pos, float); nrm = np.asarray(nrm, float); uv = np.asarray(uv, float)
    tan = np.zeros((len(pos), 3)); bit = np.zeros((len(pos), 3))
    p0, p1, p2 = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    w0, w1, w2 = uv[tris[:, 0]], uv[tris[:, 1]], uv[tris[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = w1 - w0, w2 - w0
    denom = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(denom) > 1e-12, 1.0 / np.where(denom == 0, 1.0, denom), 0.0)[:, None]
    sdir = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r
    tdir = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r
    for i in range(3):
        np.add.at(tan, tris[:, i], sdir)
        np.add.at(bit, tris[:, i], tdir)
    t = tan - nrm * np.sum(nrm * tan, axis=1, keepdims=True)    # orthonormalize vs normal
    tl = np.linalg.norm(t, axis=1, keepdims=True); tl[tl == 0] = 1.0
    t = t / tl
    w = np.where(np.sum(np.cross(nrm, tan) * bit, axis=1) < 0.0, -1.0, 1.0)
    return t, w


def _rebuild_mesh(geo, oo, id2name, clusters, mesh, bones, R, t):
    """Rebuild one bundle mesh tree (in place) from one FBX Geometry. Returns
    (new_vertex_count, triangle_count)."""
    verts = np.array(geo.first("Vertices").props[0], float).reshape(-1, 3)
    pvi = np.array(geo.first("PolygonVertexIndex").props[0], np.int64)
    faces, pvfaces, cur = [], [], []
    for pvpos, raw in enumerate(pvi):
        idx = int(raw)
        if idx < 0:
            cur.append((~idx, pvpos))
            for k in range(1, len(cur) - 1):
                faces.append((cur[0][0], cur[k][0], cur[k + 1][0]))
                pvfaces.append((cur[0][1], cur[k][1], cur[k + 1][1]))
            cur = []
        else:
            cur.append((idx, pvpos))
    corners = np.array([c for f in faces for c in f], np.int64)        # control-point idx / tri-corner
    pv_corners = np.array([c for f in pvfaces for c in f], np.int64)   # polygon-vertex pos / tri-corner

    def layer(name, sub):
        le = geo.first(name)
        if not le:
            return None, None
        arr = le.first(sub)
        if not arr:
            return None, None
        return (np.array(arr.props[0], float),
                (le.first("MappingInformationType").props[0],
                 le.first("ReferenceInformationType").props[0], le))

    def corner_values(data, meta, dim):
        if data is None:
            return None
        mapping, ref, le = meta
        data = data.reshape(-1, dim)
        idxmap = {"LayerElementUV": "UVIndex", "LayerElementNormal": "NormalsIndex",
                  "LayerElementColor": "ColorIndex"}
        if mapping == "ByPolygonVertex":
            if ref.startswith("IndexToDirect"):
                per_pv = data[np.array(le.first(idxmap.get(le.name)).props[0], np.int64)]
            else:
                per_pv = data
            return per_pv[pv_corners]          # polygon-vertex data -> per triangulated corner
        # per-vertex: AssetStudio writes 'ByVertice', other tools 'ByVertex'/'ByControlPoint'
        if mapping in ("ByVertex", "ByVertice", "ByVertices", "ByControlPoint"):
            if ref.startswith("IndexToDirect"):
                idxname = idxmap.get(le.name)
                ix = np.array(le.first(idxname).props[0], np.int64)
                return data[ix[corners]] if idxname else data[corners]
            return data[corners]
        return data

    c_nrm = corner_values(*layer("LayerElementNormal", "Normals"), 3)
    c_uv = corner_values(*layer("LayerElementUV", "UV"), 2)
    c_tan = corner_values(*layer("LayerElementTangent", "Tangents"), 3)
    # vertex colors (RGBA or RGB) — round-tripped instead of being forced white
    c_col = None
    cle = geo.first("LayerElementColor")
    if cle is not None and cle.first("Colors") is not None:
        nco = len(cle.first("Colors").props[0])
        for cdim in (4, 3):
            if nco % cdim == 0:
                try:
                    c_col = corner_values(*layer("LayerElementColor", "Colors"), cdim)
                except Exception:
                    c_col = None
                if c_col is not None:
                    if cdim == 3:
                        c_col = np.concatenate([c_col, np.ones((len(c_col), 1))], axis=1)
                    break

    cp_weights = [dict() for _ in range(len(verts))]
    for cid, cl in clusters.items():
        bone = None
        for a, b in oo:
            if b == cid and a in id2name:
                bone = id2name[a]
            if a == cid and b in id2name:
                bone = id2name[b]
        idxn, wn = cl.first("Indexes"), cl.first("Weights")
        if not idxn or not wn or bone is None:
            continue
        for vi, w in zip(idxn.props[0], wn.props[0]):
            if w and int(vi) < len(cp_weights):
                cp_weights[int(vi)][bone] = cp_weights[int(vi)].get(bone, 0.0) + float(w)

    # map FBX space -> Unity space using the auto-detected transform (handles any
    # exporter: AssetStudio's X-mirror, Blender's axis conversion, etc.)
    verts = verts @ R.T + t
    if c_nrm is not None:
        c_nrm = c_nrm @ R.T
        _n = np.linalg.norm(c_nrm, axis=1, keepdims=True); _n[_n == 0] = 1.0
        c_nrm = c_nrm / _n                   # M carries scale -> renormalize directions
    if c_tan is not None:
        c_tan = c_tan @ R.T
        _n = np.linalg.norm(c_tan, axis=1, keepdims=True); _n[_n == 0] = 1.0
        c_tan = c_tan / _n
    if np.linalg.det(R) < 0:                 # reflection -> triangle winding flips
        corners = corners.reshape(-1, 3)[:, ::-1].reshape(-1)

        def flip_corner(a):
            return None if a is None else a.reshape(-1, 3, a.shape[-1])[:, ::-1, :].reshape(-1, a.shape[-1])
        c_nrm, c_uv, c_tan, c_col = (flip_corner(c_nrm), flip_corner(c_uv),
                                     flip_corner(c_tan), flip_corner(c_col))

    key_cols = [corners.reshape(-1, 1)]
    if c_nrm is not None: key_cols.append(np.round(c_nrm, 5))
    if c_uv is not None: key_cols.append(np.round(c_uv, 5))
    keys = np.concatenate(key_cols, axis=1)
    _, first_idx, inv = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    new_vc = len(first_idx)
    cp_of = corners[first_idx]
    out_pos = verts[cp_of]
    out_nrm = c_nrm[first_idx] if c_nrm is not None else np.tile([0.0, 0, 1.0], (new_vc, 1))
    out_uv = c_uv[first_idx] if c_uv is not None else np.zeros((new_vc, 2))
    out_tan = c_tan[first_idx] if c_tan is not None else np.tile([1.0, 0, 0], (new_vc, 1))
    out_col = c_col[first_idx] if c_col is not None else None
    new_tris = inv.reshape(-1, 3)

    bone_idx = {n: i for i, n in enumerate(bones)}
    BW = np.zeros((new_vc, 4)); BI = np.zeros((new_vc, 4), np.int64)
    if bone_idx:
        for v in range(new_vc):
            items = sorted(((w, bone_idx[b]) for b, w in cp_weights[cp_of[v]].items()
                            if b in bone_idx), reverse=True)[:4]
            s = sum(w for w, _ in items) or 1.0
            for k, (w, bidx) in enumerate(items):
                BW[v, k] = w / s; BI[v, k] = bidx

    if c_tan is not None:
        tan4 = np.zeros((new_vc, 4)); tan4[:, :3] = out_tan[:, :3]; tan4[:, 3] = -1.0
    else:                                    # FBX had no tangents -> compute from UV + normal
        _td, _tw = _compute_tangents(out_pos, out_nrm, out_uv, new_tris)
        tan4 = np.zeros((new_vc, 4)); tan4[:, :3] = _td; tan4[:, 3] = _tw

    mesh["m_VertexData"]["m_VertexCount"] = new_vc
    nvc, nchans, nstride, nstart, ntotal = stream_layout(mesh)
    buf = bytearray(ntotal)
    u8 = np.frombuffer(buf, np.uint8)

    def put(arr, idx):
        if idx < len(nchans) and nchans[idx].get("dimension", 0):
            write_attr(u8, arr, nchans, idx, nstride, nstart, nvc)
    put(out_pos, CH_POS)
    put(out_nrm, CH_NORMAL)
    put(tan4, CH_TANGENT)
    if nchans[CH_COLOR].get("dimension", 0):
        put(out_col if out_col is not None else np.ones((nvc, 4)), CH_COLOR)
    uvstream = nchans[CH_UV0]["stream"] if nchans[CH_UV0].get("dimension", 0) else None
    for ci, ch in enumerate(nchans):
        if ch.get("dimension", 0) == 2 and ch["stream"] == uvstream:
            put(out_uv, ci)
    if nchans[CH_BLENDWEIGHT].get("dimension", 0):
        put(BW, CH_BLENDWEIGHT)
        put(BI.astype(np.float64), CH_BLENDINDICES)
    mesh["m_VertexData"]["m_DataSize"] = bytes(buf)

    idx_fmt = mesh.get("m_IndexFormat", 0)
    if new_vc > 65535 and idx_fmt == 0:
        idx_fmt = 1; mesh["m_IndexFormat"] = 1
    flat = new_tris.reshape(-1).astype("<u2" if idx_fmt == 0 else "<u4")
    mesh["m_IndexBuffer"] = flat.tobytes()
    sm = mesh["m_SubMeshes"][0]
    sm["firstByte"] = 0; sm["indexCount"] = int(flat.size)
    sm["firstVertex"] = 0; sm["vertexCount"] = new_vc; sm["baseVertex"] = 0
    mn, mx = out_pos.min(0), out_pos.max(0)
    ctr = (mn + mx) / 2; ext = (mx - mn) / 2
    for box in (sm.get("localAABB"), mesh.get("m_LocalAABB")):
        if box:
            box["m_Center"] = {"x": float(ctr[0]), "y": float(ctr[1]), "z": float(ctr[2])}
            box["m_Extent"] = {"x": float(ext[0]), "y": float(ext[1]), "z": float(ext[2])}
    mesh["m_SubMeshes"] = [sm]
    n_weighted = int((BW.sum(1) > 1e-9).sum())
    return new_vc, len(new_tris), n_weighted


def inspect_fbx_meshes(fbx_path, bundle_path):
    """List what an import would do, per bundle skinned-mesh: which FBX geometry maps
    to it, its vertex count, and whether the FBX carries skin weights for it. Returns
    [{'mesh','fbx','verts','skin','match'}]. Lets the caller pick a subset to import."""
    FBX = _fbx_reader(); fbx = FBX(fbx_path)
    objs = fbx.root.first("Objects"); conns = fbx.root.first("Connections")
    oo = [(c.props[1], c.props[2]) for c in conns.findall("C") if c.props[0] == "OO"]
    id2name = {m.props[0]: m.props[1].split("\x00\x01")[0] for m in objs.findall("Model")}
    defs = {d.props[0]: d for d in objs.findall("Deformer")}

    def subtype(d):
        return d.props[2].split("\x00\x01")[0] if len(d.props) > 2 and isinstance(d.props[2], str) else ""

    def vcount(g):
        v = g.first("Vertices"); return len(v.props[0]) // 3 if v else 0
    geos = [g for g in objs.findall("Geometry") if vcount(g) > 0]
    geo_set = {g.props[0] for g in geos}
    geo_model_name = {}
    for a, b in oo:
        if a in geo_set and b in id2name:
            geo_model_name[a] = id2name[b]
    geo_by_name = {}
    for g in geos:
        nm = geo_model_name.get(g.props[0]) or g.props[1].split("\x00\x01")[0]
        geo_by_name.setdefault(nm, g)

    def has_skin(gid):
        skins = {s for (s, d) in oo if d == gid and s in defs and subtype(defs[s]) == "Skin"}
        return any(b in skins and a in defs and subtype(defs[a]) == "Cluster" for (a, b) in oo)

    env = UnityPy.load(bundle_path); uid = {o.path_id: o for o in env.objects}
    out = []
    for o in env.objects:
        if o.type.name == "SkinnedMeshRenderer":
            tt = o.read_typetree(); m = uid[tt["m_Mesh"]["m_PathID"]].read_typetree()
            nm = m.get("m_Name", "")
            try:
                _, mchans, _, _, _ = stream_layout(m)
                needs = bool(mchans[CH_BLENDWEIGHT].get("dimension", 0))
            except Exception:
                needs = False
            g = geo_by_name.get(nm)
            out.append({"mesh": nm,
                        "fbx": (geo_model_name.get(g.props[0]) or g.props[1].split("\x00\x01")[0]) if g else None,
                        "verts": vcount(g) if g else 0,
                        "skin": bool(g is not None and has_skin(g.props[0])),
                        "needs_skin": needs,
                        "match": g is not None})
    return out


def import_fbx(fbx_path, bundle_path, out_path, texdir=None, verbose=True, only_meshes=None):
    def log(*a):
        if verbose:
            print(*a)
    FBX = _fbx_reader()
    fbx = FBX(fbx_path)
    objs = fbx.root.first("Objects")
    conns = fbx.root.first("Connections")
    oo = [(c.props[1], c.props[2]) for c in conns.findall("C") if c.props[0] == "OO"]
    id2model = {m.props[0]: m for m in objs.findall("Model")}
    id2name = {i: m.props[1].split("\x00\x01")[0] for i, m in id2model.items()}
    clusters = {d.props[0]: d for d in objs.findall("Deformer")
                if len(d.props) > 2 and d.props[2] == "Cluster"}

    def vcount(g):
        v = g.first("Vertices")
        return len(v.props[0]) // 3 if v else 0
    geos = [g for g in objs.findall("Geometry") if vcount(g) > 0]
    if not geos:
        raise RuntimeError("FBX has no geometry with vertices")
    # geometry -> the name of the Model it is connected to (robust against renames)
    geo_model_name = {}
    for a, b in oo:
        if a in {g.props[0] for g in geos} and b in id2name:
            geo_model_name[a] = id2name[b]
    geo_by_name = {}
    for g in geos:
        nm = geo_model_name.get(g.props[0]) or g.props[1].split("\x00\x01")[0]
        geo_by_name.setdefault(nm, g)
    geo_set = {g.props[0] for g in geos}
    geo_model_id = {}                    # geometry id -> its mesh Model id
    for a, b in oo:
        if a in geo_set and b in id2model:
            geo_model_id[a] = b

    env = UnityPy.load(bundle_path)
    uid = {o.path_id: o for o in env.objects}
    local, world, parent, name2pid, _uid = bundle_skeleton(env)

    def bone_name(pid):
        o = uid.get(pid)
        if not o:
            return None
        t = o.read_typetree()
        g = uid.get(t.get("m_GameObject", {}).get("m_PathID"))
        return g.read().m_Name if g else None

    # ---- auto-detect the FBX->Unity coordinate transform from shared bones ----
    fbx_wmats, fbx_wnames, fbx_models = _fbx_world_matrices(fbx)
    fbx_bw = {}
    for _i in fbx_models:
        fbx_bw.setdefault(fbx_wnames[_i], fbx_wmats[_i][:3, 3])
    shared = [n for n in fbx_bw if n in world]
    if len(shared) >= 4:
        src = np.array([fbx_bw[n] for n in shared])
        dst = np.array([world[n][:3, 3] for n in shared])
        R, t, rms = _fit_transform(src, dst)
        det = np.linalg.det(R)
        log(f"[info] coordinate fit from {len(shared)} bones: "
            f"{'mirror' if det < 0 else 'rotation'}, residual {rms*1000:.2f} mm")
        if rms > 0.02:
            log("[warn] large fit residual — the FBX rest pose may differ from the "
                "bundle (e.g. armature was re-posed in Blender); result may be off")
    else:
        R, t = np.diag([-1.0, 1, 1]), np.zeros(3)   # fall back to AssetStudio X-mirror
        log("[warn] not enough shared bones to auto-detect coordinates; assuming X-mirror")

    def mesh_RT(geo):
        """Combined FBX-local -> Unity transform for one mesh: the bone-fit (R, t)
        composed with the mesh's own FBX world transform, so per-object scale (e.g.
        Blender's 100x cm->m), rotation and translation are all accounted for."""
        mid = geo_model_id.get(geo.props[0])
        Wm = fbx_wmats.get(mid, np.eye(4)) if mid is not None else np.eye(4)
        return R @ Wm[:3, :3], R @ Wm[:3, 3] + t

    smrs = [o for o in env.objects if o.type.name == "SkinnedMeshRenderer"]
    matched = 0
    for smr in smrs:
        smr_tt = smr.read_typetree()
        mesh_obj = uid[smr_tt["m_Mesh"]["m_PathID"]]
        mesh = mesh_obj.read_typetree()
        mname = mesh.get("m_Name", "")
        if only_meshes is not None and mname not in only_meshes:
            continue                          # user chose a subset of meshes to import
        geo = geo_by_name.get(mname)
        if geo is None:
            continue
        bones = [bone_name(b["m_PathID"]) for b in smr_tt.get("m_Bones", [])]
        Rm, tm = mesh_RT(geo)
        nv, nt, nw = _rebuild_mesh(geo, oo, id2name, clusters, mesh, bones, Rm, tm)
        mesh_obj.save_typetree(mesh)
        matched += 1
        log(f"[ok] rebuilt '{mname}': {nv} verts, {nt} tris")
        if bones and nw == 0:
            log(f"[WARN] '{mname}': the FBX carried NO skin weights for this mesh, so it "
                f"will collapse/be invisible in-game. Re-export from Blender WITH the "
                f"armature (keep the Armature modifier + vertex groups).")

    if matched == 0 and only_meshes is None:
        # fallback: largest FBX geometry -> the body (most-bones) SMR
        smr = body_smr(env); smr_tt = smr.read_typetree()
        mesh_obj = uid[smr_tt["m_Mesh"]["m_PathID"]]; mesh = mesh_obj.read_typetree()
        bones = [bone_name(b["m_PathID"]) for b in smr_tt.get("m_Bones", [])]
        geo = max(geos, key=vcount)
        Rm, tm = mesh_RT(geo)
        nv, nt, nw = _rebuild_mesh(geo, oo, id2name, clusters, mesh, bones, Rm, tm)
        mesh_obj.save_typetree(mesh)
        log(f"[warn] no name match; rebuilt body mesh from largest geometry: {nv} verts, {nt} tris")
        if bones and nw == 0:
            log(f"[WARN] this mesh has NO skin weights from the FBX — it will be invisible "
                f"in-game. Re-export from Blender with the armature + vertex groups.")

    if texdir and os.path.isdir(texdir):
        apply_textures(env, texdir, log)
    bf = list(env.files.values())[0]; bf.mark_changed()
    with open(out_path, "wb") as f:
        f.write(bf.save(packer="original"))
    log(f"[done] -> {out_path}")
    return out_path


# ==========================================================================
# self-test (export -> import -> compare to original)
# ==========================================================================
def selftest(in_path, verbose=True):
    tmp_fbx = in_path + ".__selftest.fbx"
    tmp_out = in_path + ".__selftest.unity"
    export(in_path, tmp_fbx, texdir=None, verbose=False)
    import_fbx(tmp_fbx, in_path, tmp_out, verbose=False)

    def body_geo(path):
        e = UnityPy.load(path); smr = body_smr(e)
        uid = {o.path_id: o for o in e.objects}
        m = uid[smr.read_typetree()["m_Mesh"]["m_PathID"]].read_typetree()
        vc, chans, stride, start, _ = stream_layout(m)
        u8 = np.frombuffer(bytearray(m["m_VertexData"]["m_DataSize"]), np.uint8)
        return (read_attr(u8, chans, CH_POS, stride, start, vc),
                read_indices(m).size, vc)

    p0, ni0, vc0 = body_geo(in_path)
    p1, ni1, vc1 = body_geo(tmp_out)
    # compare as point sets (order/topology may legitimately differ)
    def bbox(p):
        return np.round(np.concatenate([p.min(0), p.max(0)]), 4)
    ok = np.allclose(bbox(p0), bbox(p1), atol=1e-3) and ni0 == ni1
    if verbose:
        print(f"[selftest] orig verts={vc0} idx={ni0} bbox={bbox(p0)}")
        print(f"[selftest] round verts={vc1} idx={ni1} bbox={bbox(p1)}")
        print(f"[selftest] {'PASS — geometry preserved' if ok else 'FAIL — geometry differs'}")
    for f in (tmp_fbx, tmp_out):
        try:
            os.remove(f)
        except OSError:
            pass
    return ok


def info(in_path):
    """Print the bundle's skinned-mesh names and bone names as one line of JSON.
    Used by the Blender add-on to validate a scene before exporting (so it can
    warn when a mesh object name won't match, or too few bones share names)."""
    env = UnityPy.load(in_path)
    _, world, _, _, uid = bundle_skeleton(env)

    def bone_name(pid):
        o = uid.get(pid)
        if not o:
            return None
        t = o.read_typetree()
        g = uid.get(t.get("m_GameObject", {}).get("m_PathID"))
        return g.read().m_Name if g else None

    meshes, bones = [], set()
    for o in env.objects:
        if o.type.name == "SkinnedMeshRenderer":
            tt = o.read_typetree()
            m = uid.get(tt["m_Mesh"]["m_PathID"])
            if m:
                meshes.append(m.read_typetree().get("m_Name", ""))
            for b in tt.get("m_Bones", []):
                n = bone_name(b["m_PathID"])
                if n:
                    bones.add(n)
    print(json.dumps({"meshes": meshes, "bones": sorted(bones)}))


def build_parser():
    p = argparse.ArgumentParser(description="SIFAS bundle <-> FBX round-trip (mesh + skin + textures).")
    p.add_argument("--gui", action="store_true", help="force the graphical interface")
    p.add_argument("--web", action="store_true", help="launch the browser-based interface")
    sub = p.add_subparsers(dest="cmd")
    e = sub.add_parser("export"); e.add_argument("--in", dest="infile", required=True)
    e.add_argument("--out", required=True); e.add_argument("--texdir", default=None)
    e.add_argument("-q", "--quiet", action="store_true")
    i = sub.add_parser("import"); i.add_argument("--fbx", required=True)
    i.add_argument("--bundle", required=True); i.add_argument("--out", required=True)
    i.add_argument("--texdir", default=None, help="also re-import edited textures from this folder")
    i.add_argument("--meshes", default=None,
                   help="comma-separated mesh names to import (default: all that match)")
    i.add_argument("-q", "--quiet", action="store_true")
    ms = sub.add_parser("meshes", help="list the meshes an import would touch (name/verts/skin)")
    ms.add_argument("--fbx", required=True); ms.add_argument("--bundle", required=True)
    t = sub.add_parser("texture"); t.add_argument("--texdir", required=True)
    t.add_argument("--bundle", required=True); t.add_argument("--out", required=True)
    t.add_argument("-q", "--quiet", action="store_true")
    s = sub.add_parser("selftest"); s.add_argument("--in", dest="infile", required=True)
    inf = sub.add_parser("info"); inf.add_argument("--in", dest="infile", required=True)
    return p


# --------------------------------------------------------------------------
# GUI (optional; falls back to CLI on Termux/headless)
# --------------------------------------------------------------------------
def gui_available():
    if os.path.isdir("/data/data/com.termux"):
        return False
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") \
            and not os.environ.get("WAYLAND_DISPLAY"):
        return False
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False


def run_gui():
    import threading
    import queue
    import tkinter as tk
    from tkinter import ttk, filedialog, scrolledtext

    # Drag & drop via tkinterdnd2 if available (auto-installed like the other deps).
    # If it can't load, fall back cleanly to a plain Tk root (Browse buttons still work).
    dnd_files = None
    TkinterDnD = None
    root = None
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
    except Exception:
        try:
            _pip("tkinterdnd2")
            from tkinterdnd2 import TkinterDnD, DND_FILES
        except Exception:
            TkinterDnD = None
    if TkinterDnD is not None:
        try:
            root = TkinterDnD.Tk()
            dnd_files = DND_FILES
        except Exception as ex:
            # TkinterDnD.Tk() creates its window *before* loading tkdnd, so if tkdnd
            # fails (common with Apple's system Tk 8.5) it leaves an orphan empty
            # window. Destroy it so we don't end up showing two windows.
            if tk._default_root is not None:
                try:
                    tk._default_root.destroy()
                except Exception:
                    pass
                tk._default_root = None
            print("[gui] drag & drop disabled (%s). Using Browse buttons. On macOS use "
                  "python.org Python (Tk 8.6); the system Tk 8.5 can't load tkdnd." % ex)
    if root is None:
        root = tk.Tk()
    try:
        if float(root.tk.call("info", "patchlevel").rsplit(".", 1)[0]) < 8.6:
            print("[gui] note: Tk %s — Apple's system Tk 8.5 is buggy on macOS (focus, "
                  "shortcuts, drag&drop). Prefer python.org Python (Tk 8.6)."
                  % root.tk.call("info", "patchlevel"))
    except Exception:
        pass
    root.title("SIFAS FBX Round-Trip")
    root.geometry("780x620")

    msgq = queue.Queue()
    buttons = []

    class _W:
        def write(self, s):
            if s:
                msgq.put(s)
        def flush(self):
            pass

    def run_thread(fn):
        for b in buttons:
            b.configure(state="disabled")

        def wrap():
            old = sys.stdout
            sys.stdout = _W()
            try:
                fn()
            except Exception as ex:
                import traceback
                print("\n[error] " + "".join(traceback.format_exception(ex)))
            finally:
                sys.stdout = old
                root.after(0, lambda: [b.configure(state="normal") for b in buttons])
        threading.Thread(target=wrap, daemon=True).start()

    def _register_drop(widget, var, folder=False):
        """Make a widget accept a dropped file/folder, setting `var` to its path."""
        if dnd_files is None:
            return
        try:
            widget.drop_target_register(dnd_files)
        except Exception:
            return

        def _on_drop(event, v=var, fo=folder):
            try:
                paths = root.tk.splitlist(event.data)   # handles {paths with spaces}
            except Exception:
                paths = [event.data.strip("{}")]
            if paths:
                p = paths[0]
                if fo and not os.path.isdir(p):         # folder field: use the parent dir
                    p = os.path.dirname(p)
                v.set(p)
            return event.action
        widget.dnd_bind('<<Drop>>', _on_drop)

    def row(parent, r, label, var, save=False, kind="bundle", folder=False):
        ttk.Label(parent, text=label, width=20).grid(row=r, column=0, sticky="w", pady=3)
        entry = ttk.Entry(parent, textvariable=var, width=54)
        entry.grid(row=r, column=1, padx=4)
        _register_drop(entry, var, folder=folder)

        def pick():
            ft = {"bundle": [("Unity bundle", "*.unity *.unity3d"), ("All files", "*.*")],
                  "fbx": [("FBX", "*.fbx"), ("All files", "*.*")]}.get(kind, [("All files", "*.*")])
            if folder:
                pth = filedialog.askdirectory(title=label)
            elif save:
                ext = ".fbx" if kind == "fbx" else ".unity"
                pth = filedialog.asksaveasfilename(title=label, defaultextension=ext, filetypes=ft)
            else:
                pth = filedialog.askopenfilename(title=label, filetypes=ft)
            if pth:
                var.set(pth)
        ttk.Button(parent, text="Browse…", command=pick).grid(row=r, column=2)

    nb = ttk.Notebook(root)
    nb.pack(fill="x", padx=10, pady=(10, 4))

    # ---- Export tab ----
    ex = ttk.Frame(nb, padding=8); nb.add(ex, text="Export (bundle → FBX)")
    ex_in, ex_out, ex_tex = tk.StringVar(), tk.StringVar(), tk.StringVar()
    row(ex, 0, "Input bundle", ex_in, kind="bundle")
    row(ex, 1, "Output FBX", ex_out, save=True, kind="fbx")
    row(ex, 2, "Texture folder", ex_tex, folder=True)

    def do_export():
        i, o = ex_in.get().strip(), ex_out.get().strip()
        if not (i and o):
            msgq.put("[error] choose input bundle and output FBX.\n"); return
        log_box.delete("1.0", "end")
        run_thread(lambda: export(i, o, ex_tex.get().strip() or None, verbose=True))
    b = ttk.Button(ex, text="Export", command=do_export); b.grid(row=3, column=1, sticky="e", pady=6)
    buttons.append(b)

    # ---- Import tab ----
    im = ttk.Frame(nb, padding=8); nb.add(im, text="Import (FBX → bundle)")
    im_fbx, im_bundle, im_out, im_tex = (tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar())
    row(im, 0, "Edited FBX", im_fbx, kind="fbx")
    row(im, 1, "Source bundle", im_bundle, kind="bundle")
    row(im, 2, "Output bundle", im_out, save=True, kind="bundle")
    row(im, 3, "Texture folder", im_tex, folder=True)

    def do_import():
        f, s, o = im_fbx.get().strip(), im_bundle.get().strip(), im_out.get().strip()
        if not (f and s and o):
            msgq.put("[error] choose FBX, source bundle and output bundle.\n"); return
        log_box.delete("1.0", "end")
        run_thread(lambda: import_fbx(f, s, o, texdir=im_tex.get().strip() or None, verbose=True))
    b = ttk.Button(im, text="Import", command=do_import); b.grid(row=4, column=1, sticky="e", pady=6)
    buttons.append(b)

    # ---- Texture-only tab ----
    tx = ttk.Frame(nb, padding=8); nb.add(tx, text="Textures only")
    tx_dir, tx_bundle, tx_out = tk.StringVar(), tk.StringVar(), tk.StringVar()
    row(tx, 0, "Texture folder", tx_dir, folder=True)
    row(tx, 1, "Source bundle", tx_bundle, kind="bundle")
    row(tx, 2, "Output bundle", tx_out, save=True, kind="bundle")

    def do_tex():
        d, s, o = tx_dir.get().strip(), tx_bundle.get().strip(), tx_out.get().strip()
        if not (d and s and o):
            msgq.put("[error] choose texture folder, source bundle and output bundle.\n"); return
        log_box.delete("1.0", "end")
        run_thread(lambda: import_textures_only(d, s, o, verbose=True))
    b = ttk.Button(tx, text="Import textures", command=do_tex); b.grid(row=3, column=1, sticky="e", pady=6)
    buttons.append(b)

    # ---- Self-test tab ----
    st = ttk.Frame(nb, padding=8); nb.add(st, text="Self-test")
    st_in = tk.StringVar()
    row(st, 0, "Bundle", st_in, kind="bundle")

    def do_selftest():
        i = st_in.get().strip()
        if not i:
            msgq.put("[error] choose a bundle.\n"); return
        log_box.delete("1.0", "end")
        run_thread(lambda: selftest(i, verbose=True))
    b = ttk.Button(st, text="Run self-test", command=do_selftest); b.grid(row=1, column=1, sticky="e", pady=6)
    buttons.append(b)

    _hint = ("Export a bundle to FBX (+textures), edit in Blender (keep the armature), "
             "then import back.")
    if dnd_files is not None:
        _hint += "   •  Tip: drag & drop files onto any field."
    ttk.Label(root, padding=(10, 0), foreground="#555", text=_hint).pack(anchor="w")
    log_box = scrolledtext.ScrolledText(root, height=18, wrap="word", font=("TkFixedFont", 9))
    log_box.pack(fill="both", expand=True, padx=10, pady=8)

    def drain():
        try:
            while True:
                log_box.insert("end", msgq.get_nowait()); log_box.see("end")
        except queue.Empty:
            pass
        root.after(80, drain)
    drain()
    root.mainloop()


_WEB_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>SIFAS FBX</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#1e1f22;color:#ddd;font-size:14px}
.app{max-width:600px;margin:0 auto;padding:16px}
h1{font-size:18px;margin:2px 2px 14px}
.tabs{display:flex;gap:5px;margin-bottom:12px}
.tab{flex:1;background:#2b2d31;border:0;color:#bbb;padding:9px 2px;border-radius:7px;cursor:pointer;font-size:13px;font-weight:600}
.tab.active{background:#5865f2;color:#fff}
.panel{background:#2b2d31;border-radius:10px;padding:15px}
.panel.hidden{display:none}
label{display:block;font-size:12px;color:#9aa6b2;margin:11px 0 3px}
label.first{margin-top:0}
label.chk{display:flex;align-items:center;gap:8px;font-size:13px;color:#cfd6de;margin-top:11px;cursor:pointer}
label.chk input{width:auto;margin:0}
input[type=text]{width:100%;background:#1e1f22;border:1px solid #3a3d44;color:#ddd;border-radius:6px;padding:8px;font-size:13px}
.drop{margin-top:5px;border:1.5px dashed #4a4d55;border-radius:7px;padding:9px;text-align:center;font-size:12px;color:#888;cursor:pointer}
.drop.hover{border-color:#57b97f;color:#57b97f;background:#23351f}
button.go{width:100%;margin-top:14px;background:#5865f2;color:#fff;border:0;border-radius:7px;padding:11px;cursor:pointer;font-weight:600;font-size:14px}
#out{margin-top:11px}#out a{display:inline-block;margin:3px 11px 0 0;color:#7bdfff;font-weight:600;font-size:13px}
#log{white-space:pre-wrap;background:#111;border-radius:8px;padding:11px;margin-top:10px;height:160px;overflow:auto;font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:#cdd;-webkit-user-select:text;user-select:text;cursor:text}
.minibtn{background:#4a4d55;color:#fff;border:0;border-radius:6px;padding:5px 12px;cursor:pointer;font-size:12px;margin-top:6px}
.note{color:#7c8590;font-size:11.5px;margin:9px 3px 0}
</style></head><body>
<div class="app">
<h1>SIFAS FBX Round-Trip</h1>
<div class="tabs">
 <button class="tab active" data-t="export">Export</button>
 <button class="tab" data-t="import">Import</button>
 <button class="tab" data-t="texture">Textures</button>
 <button class="tab" data-t="selftest">Self-test</button>
</div>
<div class="panel" id="p_export">
 <label class="first">Input .unity bundle</label><input type="text" id="ex_bundle"><div class="drop" data-for="ex_bundle">drop .unity</div>
 <label class="chk"><input type="checkbox" id="ex_tex" checked> Export textures too (FBX + textures together)</label>
 <label>Save to (optional &mdash; folder; empty = next to bundle, else Downloads)</label><input type="text" id="ex_out">
 <div class="note">The FBX (and a _tex folder) are written to disk and also offered as a download.</div>
 <button class="go" onclick="runExport()">Export to FBX</button>
</div>
<div class="panel hidden" id="p_import">
 <label class="first">Edited .fbx</label><input type="text" id="im_fbx"><div class="drop" data-for="im_fbx">drop .fbx</div>
 <label>Source .unity bundle</label><input type="text" id="im_bundle"><div class="drop" data-for="im_bundle">drop .unity</div>
 <label>Textures (optional)</label><input type="text" id="im_tex"><div class="drop" data-for="im_tex" data-dir="1">drop PNG files</div>
 <label>Save to (optional &mdash; folder or .unity path; empty = next to source, else Downloads)</label><input type="text" id="im_out">
 <button class="go" style="background:#4a4d55" onclick="inspectMeshes()">1 &middot; Inspect meshes</button>
 <div id="im_meshes"></div>
 <button class="go" onclick="runImport()">2 &middot; Import selected (or all)</button>
</div>
<div class="panel hidden" id="p_texture">
 <label class="first">Textures (drop PNGs)</label><input type="text" id="tx_tex"><div class="drop" data-for="tx_tex" data-dir="1">drop PNG files</div>
 <label>Source .unity bundle</label><input type="text" id="tx_bundle"><div class="drop" data-for="tx_bundle">drop .unity</div>
 <label>Save to (optional &mdash; folder or .unity path; empty = next to source, else Downloads)</label><input type="text" id="tx_out">
 <button class="go" onclick="run('texture',{texdir:val('tx_tex'),bundle:val('tx_bundle'),outdir:val('tx_out')})">Import textures</button>
</div>
<div class="panel hidden" id="p_selftest">
 <label class="first">.unity bundle</label><input type="text" id="st_bundle"><div class="drop" data-for="st_bundle">drop .unity</div>
 <button class="go" onclick="run('selftest',{bundle:val('st_bundle')})">Run self-test</button>
</div>
<div id="out"></div>
<pre id="log"></pre>
<div style="display:flex;gap:8px;justify-content:flex-end">
 <button class="minibtn" onclick="copyLog()">Copy log</button>
 <button class="minibtn" onclick="document.getElementById('log').textContent=''">Clear</button>
</div>
<div class="note">Drag a file onto a box (uploads to this local app) or type an absolute path.</div>
</div>
<script>
function val(id){return document.getElementById(id).value.trim()}
function copyLog(){
  const txt=document.getElementById('log').textContent||'';
  let ok=false;
  try{ const ta=document.createElement('textarea'); ta.value=txt; ta.style.position='fixed'; ta.style.opacity='0';
       document.body.appendChild(ta); ta.focus(); ta.select(); ok=document.execCommand('copy'); document.body.removeChild(ta); }catch(e){}
  if(navigator.clipboard){ navigator.clipboard.writeText(txt).then(()=>{},()=>{}); ok=true; }
  const b=event&&event.target; if(b){ const o=b.textContent; b.textContent=ok?'Copied!':'Select & ⌘C'; setTimeout(()=>b.textContent=o,1200); }
}
function runExport(){
  run('export',{bundle:val('ex_bundle'),
                textures:document.getElementById('ex_tex').checked,
                outdir:val('ex_out')});
}
let imMeshRows=null;
async function inspectMeshes(){
  const box=document.getElementById('im_meshes'); box.innerHTML='<div class="note">inspecting...</div>';
  try{
    const r=await fetch('/inspect',{method:'POST',body:JSON.stringify({fbx:val('im_fbx'),bundle:val('im_bundle')})});
    const j=await r.json();
    if(j.error){ box.innerHTML='<div class="note">inspect failed: '+j.error+'</div>'; imMeshRows=null; return; }
    imMeshRows=j.meshes;
    box.innerHTML=j.meshes.map(function(m){
      const tag=!m.match?'no FBX match':m.skin?'skinned':m.needs_skin?'⚠ NO SKIN → invisible':'static';
      return '<label class="chk"><input type="checkbox" class="im_msel" data-name="'+encodeURIComponent(m.mesh)+'" '+(m.match?'checked':'')+'> '+m.mesh+' <span class="note" style="margin:0">['+m.verts+'v · '+tag+']</span></label>';
    }).join('') || '<div class="note">no skinned meshes found</div>';
  }catch(e){ box.innerHTML='<div class="note">inspect error: '+e+'</div>'; imMeshRows=null; }
}
function runImport(){
  let meshes=null;
  if(imMeshRows){ meshes=Array.from(document.querySelectorAll('.im_msel:checked')).map(c=>decodeURIComponent(c.dataset.name)); }
  run('import',{fbx:val('im_fbx'),bundle:val('im_bundle'),texdir:val('im_tex'),outdir:val('im_out'),meshes:meshes});
}
document.querySelectorAll('.tab').forEach(function(t){t.onclick=function(){
  document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===t));
  document.querySelectorAll('.panel').forEach(p=>p.classList.add('hidden'));
  document.getElementById('p_'+t.dataset.t).classList.remove('hidden');
};});
async function upload(file,dir){
  const r=await fetch('/upload',{method:'POST',headers:{'X-Filename':file.name,'X-Subdir':dir||''},body:file});
  return await r.json();
}
document.querySelectorAll('.drop').forEach(function(d){
  const fld=document.getElementById(d.dataset.for), isdir=d.dataset.dir==='1';
  const fi=document.createElement('input'); fi.type='file'; if(isdir)fi.multiple=true; fi.style.display='none'; d.appendChild(fi);
  d.onclick=()=>fi.click();
  fi.onchange=()=>handle(fi.files,fld,isdir,d);
  d.ondragover=e=>{e.preventDefault();d.classList.add('hover')};
  d.ondragleave=()=>d.classList.remove('hover');
  d.ondrop=e=>{e.preventDefault();d.classList.remove('hover');handle(e.dataTransfer.files,fld,isdir,d)};
});
async function handle(files,fld,isdir,d){
  if(!files.length)return; const base=d.textContent; d.textContent='uploading...';
  try{
    if(isdir){ let dir=''; for(const f of files){const j=await upload(f,'texset'); dir=j.dir;} fld.value=dir; d.textContent=files.length+' file(s)'; }
    else{ const j=await upload(files[0]); fld.value=j.path; d.textContent=files[0].name; }
  }catch(e){ d.textContent=base; alert('upload failed: '+e); }
}
const log=document.getElementById('log'), out=document.getElementById('out');
async function run(cmd,args){
  out.innerHTML=''; log.textContent=''; args.cmd=cmd;
  const r=await fetch('/run',{method:'POST',body:JSON.stringify(args)});
  poll((await r.json()).id,0);
}
async function poll(id,from){
  const r=await fetch('/status?id='+id+'&from='+from);
  const j=await r.json();
  if(j.log){log.textContent+=j.log; log.scrollTop=log.scrollHeight;}
  if(j.done){ out.innerHTML=j.outputs.map(n=>'<a href="/download?id='+id+'&name='+encodeURIComponent(n)+'">&#11015; '+n+'</a>').join(''); return; }
  setTimeout(()=>poll(id,j.len),400);
}
</script></body></html>"""


def _try_app_window(url, server):
    """Show the UI in a standalone native app window (pywebview: WKWebView on macOS,
    WebView2 on Windows, GTK/Qt on Linux) — its own app, not a Safari tab. Serves in a
    background thread while the window is open. Returns True if it ran the window (and
    stopped the server on close), False if pywebview isn't available."""
    import threading
    import time
    try:
        import webview
    except Exception:
        print("[web] setting up the standalone app window (one-time install)...")
        try:
            _pip("pywebview")
            import webview
        except Exception:
            print("[web] (pywebview unavailable; opening a browser window instead)")
            return False
    try:
        webview.create_window("SIFAS FBX Round-Trip", url, width=650, height=700)
    except Exception:
        return False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        webview.start()                          # blocks on the main thread until closed
    except Exception as ex:                       # no display / runtime failure -> browser
        print("[web] couldn't open the app window (%s); opening a browser at %s" % (ex, url))
        _open_browser_window(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("\n[web] stopped")
    try:
        server.shutdown()
    except Exception:
        pass
    return True


def _open_browser_window(url, width=650, height=700):
    """Open `url` in a separate, sized window: a Chromium '--app' window if such a
    browser exists; else on macOS a new Safari *window* (not a tab) via AppleScript;
    else the default browser in a new window."""
    import shutil
    import subprocess
    import webbrowser
    cands = []
    if sys.platform == "darwin":
        cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                 "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    elif sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                cands += [os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                          os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "BraveSoftware", "Brave-Browser", "Application", "brave.exe")]
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                     "microsoft-edge", "brave-browser"):
            p = shutil.which(name)
            if p:
                cands.append(p)
    exe = next((c for c in cands if c and os.path.isfile(c)), None)
    if exe:
        try:
            subprocess.Popen([exe, "--app=" + url, "--window-size=%d,%d" % (width, height)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    if sys.platform == "darwin":
        # A real new Safari window (not a tab), sized. Needs the one-time
        # "<app> wants to control Safari" permission the first time it runs.
        x, y = 130, 70
        script = ('tell application "Safari"\n'
                  '  activate\n'
                  '  make new document with properties {URL:"%s"}\n'
                  '  delay 0.3\n'
                  '  try\n'
                  '    set bounds of front window to {%d, %d, %d, %d}\n'
                  '  end try\n'
                  'end tell') % (url, x, y, x + width, y + height)
        try:
            r = subprocess.run(["osascript", "-e", script], timeout=90,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if r.returncode == 0:
                return True
        except Exception:
            pass
    try:
        webbrowser.open(url, new=1)
    except Exception:
        pass
    return False


def run_web(open_browser=True, host="127.0.0.1", port=0, serve=True):
    """Browser-based UI (stdlib only). Drag files onto the page (HTML5 DnD, works on
    any OS/browser regardless of the Tk version), or type absolute local paths."""
    import http.server
    import json
    import threading
    import tempfile
    import urllib.parse
    import zipfile
    import webbrowser
    import traceback

    work = tempfile.mkdtemp(prefix="sifas_web_")
    jobs = {}
    counter = [0]
    job_lock = threading.Lock()

    class _Buf:
        def __init__(self, jid):
            self.jid = jid

        def write(self, s):
            if s:
                jobs[self.jid]["log"].append(s)

        def flush(self):
            pass

    def start_job(fn, outputs_after):
        counter[0] += 1
        jid = str(counter[0])
        jobs[jid] = {"log": [], "done": False, "ok": False, "outputs": []}

        def worker():
            with job_lock:                       # serialize (stdout is captured globally)
                old = sys.stdout
                sys.stdout = _Buf(jid)
                ok = True
                try:
                    fn()
                except Exception:
                    jobs[jid]["log"].append("\n[error] " + traceback.format_exc())
                    ok = False
                finally:
                    sys.stdout = old
                try:
                    jobs[jid]["outputs"] = outputs_after() if ok else []
                except Exception:
                    jobs[jid]["outputs"] = []
                jobs[jid]["ok"] = ok
                jobs[jid]["done"] = True
        threading.Thread(target=worker, daemon=True).start()
        return jid

    def _need(p, what):
        if not p or not os.path.isfile(p):
            raise ValueError("%s not found: %r" % (what, p))

    def _resolve_out(explicit, src, default_name):
        """Where to write an output bundle. Explicit folder/file path wins; else next
        to the source bundle if it's a real local path (not an uploaded temp file);
        else ~/Downloads. This keeps results on disk so they don't depend on the
        browser/app-window download mechanism (WKWebView doesn't trigger downloads)."""
        explicit = (explicit or "").strip()
        if explicit:
            explicit = os.path.abspath(os.path.expanduser(explicit))
            return os.path.join(explicit, default_name) if os.path.isdir(explicit) else explicit
        if src and not os.path.abspath(src).startswith(os.path.abspath(work)):
            return os.path.join(os.path.dirname(os.path.abspath(src)), default_name)
        dl = os.path.join(os.path.expanduser("~"), "Downloads")
        return os.path.join(dl if os.path.isdir(dl) else os.path.expanduser("~"), default_name)

    def dispatch(req):
        cmd = req.get("cmd")
        if cmd == "export":
            inp = req.get("bundle", "")
            want_tex = bool(req.get("textures", True))
            outdir = (req.get("outdir") or "").strip()
            stem = os.path.splitext(os.path.basename(inp))[0] or "model"
            if outdir:
                dest = os.path.abspath(os.path.expanduser(outdir))
            else:
                dest = os.path.dirname(_resolve_out(None, inp, stem + ".fbx"))
            out = os.path.join(dest, stem + ".fbx")
            tex = os.path.join(dest, stem + "_tex") if want_tex else None

            def fn():
                _need(inp, "input bundle")
                if not os.path.isdir(dest):
                    raise ValueError("output folder not found: %r" % dest)
                export(inp, out, texdir=tex, verbose=True)
                print("[saved] " + out)
                if tex:
                    print("[saved] textures -> " + tex + os.sep)

            def outs():
                # files are on disk at `dest`; also offer a download (works in browsers)
                if want_tex and tex and os.path.isdir(tex) and os.listdir(tex):
                    zp = os.path.join(work, stem + ".zip")   # FBX + textures in one file
                    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
                        if os.path.isfile(out):
                            z.write(out, os.path.basename(out))
                        for f in sorted(os.listdir(tex)):
                            z.write(os.path.join(tex, f), "textures/" + f)
                    return [(stem + ".zip", zp)]
                return [(os.path.basename(out), out)] if os.path.isfile(out) else []
            return start_job(fn, outs)
        if cmd == "import":
            fbx = req.get("fbx", ""); bundle = req.get("bundle", "")
            tex = req.get("texdir") or None
            only = req.get("meshes") if isinstance(req.get("meshes"), list) else None
            stem = os.path.splitext(os.path.basename(bundle))[0] or "model"
            out = _resolve_out(req.get("outdir"), bundle, stem + "_new.unity")

            def fn():
                _need(fbx, "FBX"); _need(bundle, "source bundle")
                d = os.path.dirname(out)
                if d and not os.path.isdir(d):
                    raise ValueError("output folder not found: %r" % d)
                import_fbx(fbx, bundle, out, texdir=tex, verbose=True, only_meshes=only)
                print("[saved] " + out)
            return start_job(fn, lambda: [(os.path.basename(out), out)] if os.path.isfile(out) else [])
        if cmd == "texture":
            tex = req.get("texdir", ""); bundle = req.get("bundle", "")
            stem = os.path.splitext(os.path.basename(bundle))[0] or "model"
            out = _resolve_out(req.get("outdir"), bundle, stem + "_tex.unity")

            def fn():
                if not tex or not os.path.isdir(tex):
                    raise ValueError("texture folder not found: %r" % tex)
                _need(bundle, "source bundle")
                d = os.path.dirname(out)
                if d and not os.path.isdir(d):
                    raise ValueError("output folder not found: %r" % d)
                import_textures_only(tex, bundle, out, verbose=True)
                print("[saved] " + out)
            return start_job(fn, lambda: [(os.path.basename(out), out)] if os.path.isfile(out) else [])
        if cmd == "selftest":
            inp = req.get("bundle", "")

            def fn():
                _need(inp, "bundle"); selftest(inp, verbose=True)
            return start_job(fn, lambda: [])

        def _bad():
            raise ValueError("unknown command: %r" % cmd)
        return start_job(_bad, lambda: [])

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            if u.path == "/":
                return self._send(200, _WEB_PAGE, "text/html; charset=utf-8")
            if u.path == "/status":
                j = jobs.get(q.get("id", [""])[0])
                if not j:
                    return self._send(404, "{}")
                frm = int(q.get("from", ["0"])[0])
                text = "".join(j["log"])
                return self._send(200, json.dumps(
                    {"log": text[frm:], "len": len(text), "done": j["done"],
                     "ok": j["ok"], "outputs": [n for n, _ in j["outputs"]]}))
            if u.path == "/download":
                j = jobs.get(q.get("id", [""])[0]); name = q.get("name", [""])[0]
                path = None
                for n, p in (j["outputs"] if j else []):
                    if n == name:
                        path = p
                if not path or not os.path.isfile(path):
                    return self._send(404, "not found", "text/plain")
                data = open(path, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except Exception:
                    pass
                return
            return self._send(404, "{}")

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            ln = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(ln) if ln else b""
            if u.path == "/upload":
                name = os.path.basename(self.headers.get("X-Filename", "file.bin")) or "file.bin"
                sub = os.path.basename(self.headers.get("X-Subdir", "") or "")
                d = os.path.join(work, sub) if sub else work
                os.makedirs(d, exist_ok=True)
                p = os.path.join(d, name)
                with open(p, "wb") as f:
                    f.write(body)
                return self._send(200, json.dumps({"path": p, "name": name, "dir": d}))
            if u.path == "/run":
                try:
                    req = json.loads(body.decode("utf-8") or "{}")
                except Exception:
                    return self._send(400, "{}")
                return self._send(200, json.dumps({"id": dispatch(req)}))
            if u.path == "/inspect":
                try:
                    req = json.loads(body.decode("utf-8") or "{}")
                    rows = inspect_fbx_meshes(req.get("fbx", ""), req.get("bundle", ""))
                    return self._send(200, json.dumps({"meshes": rows}))
                except Exception as ex:
                    return self._send(200, json.dumps({"error": str(ex)}))
            return self._send(404, "{}")

    server = http.server.ThreadingHTTPServer((host, port), H)
    if not serve:
        return server, work
    url = "http://%s:%d/" % (host, server.server_address[1])
    print("[web] SIFAS FBX UI at", url, "  (Ctrl-C to stop)")
    # Prefer a standalone native app window (not a Safari tab); fall back to a browser.
    if open_browser and _try_app_window(url, server):
        return
    if open_browser:
        # in a thread: opening a sized Safari window may block on a one-time
        # permission prompt, and the server must already be serving by then.
        threading.Thread(target=_open_browser_window, args=(url,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[web] stopped")
    finally:
        server.server_close()


def main(argv=None):
    # hidden child-process entrypoint: decode one texture in isolation
    av = sys.argv if argv is None else argv
    if len(av) >= 5 and av[1] == "__decode_tex":
        sys.exit(_decode_one_texture(av[2], av[3], av[4]))
    a = build_parser().parse_args(argv)
    if a.gui:                         # explicitly force the tkinter desktop GUI
        if gui_available():
            run_gui()
            return
        print("[gui] tkinter unavailable; opening the web UI instead.")
        run_web()
        return
    if a.web or a.cmd is None:        # just run it (no command) -> open the web UI
        run_web()
        return
    if a.cmd == "export":
        export(a.infile, a.out, a.texdir, verbose=not a.quiet)
    elif a.cmd == "import":
        only = [x.strip() for x in a.meshes.split(",") if x.strip()] if a.meshes else None
        import_fbx(a.fbx, a.bundle, a.out, texdir=a.texdir, verbose=not a.quiet, only_meshes=only)
    elif a.cmd == "meshes":
        for r in inspect_fbx_meshes(a.fbx, a.bundle):
            if not r["match"]:
                status = "no FBX match (would be skipped)"
            elif r["skin"]:
                status = "skinned (ok)"
            elif r["needs_skin"]:
                status = "NO SKIN -> would be INVISIBLE in-game"
            else:
                status = "static (ok)"
            mark = "ok" if r["match"] else "--"
            print(f"  [{mark}] {r['mesh']:<28} fbx={str(r['fbx']):<28} verts={r['verts']:<6} {status}")
    elif a.cmd == "texture":
        import_textures_only(a.texdir, a.bundle, a.out, verbose=not a.quiet)
    elif a.cmd == "selftest":
        sys.exit(0 if selftest(a.infile) else 1)
    elif a.cmd == "info":
        info(a.infile)


if __name__ == "__main__":
    main()
