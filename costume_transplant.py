#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFAS Costume Transplant — cross-character outfit swap
======================================================
Takes the *outfit* (body mesh + body textures + costume-specific bones) from a
DONOR character model bundle and grafts it onto a TARGET character model bundle,
while keeping the TARGET's identity (face mesh, hair mesh, head texture, body
skeleton/proportions). The result is "the target character wearing the donor's
costume".

Why this works for SIFAS models
-------------------------------
Every SIFAS `chXXXX_coYYYY_member` model packs the whole character in one bundle:

    Body  SkinnedMeshRenderer : body + clothing geometry  -> ch_co_body texture
    Hair  SkinnedMeshRenderer : hairstyle                 -> identity
    Face  SkinnedMeshRenderer : face                      -> ch_co_head texture

The costume IS the Body mesh + the `*_body` material/textures. The body skeleton
is a shared base rig (Hips...Skirt) that is byte-for-byte the same bone names and
order across characters, except a costume may add a few *appendage* dynamic bones
(a sailor collar `SailorA_*`, a cape, ribbons...). Those extra bones do not exist
in the target rig.

Instead of creating brand-new bone GameObjects in the target (fragile), every
costume-specific donor bone is re-bound to the nearest ancestor bone that DOES
exist in the target (its dynamic-bone parent, e.g. `Spine2`), and its bind pose
is replaced with that ancestor's bind pose. Geometrically:

    at rest:  bone.localToWorld * bindpose == renderer.localToWorld   (identity map)

so copying the ancestor's bind pose into the appendage slots keeps every costume
vertex exactly where it was modelled; the appendage just moves rigidly with that
ancestor instead of having its own jiggle physics. Nothing in the file dangles.

What is transplanted
--------------------
    * Body mesh (geometry, skin weights, bind poses, index buffer)  donor -> target
    * Body SkinnedMeshRenderer bone list + bounds                    donor -> target
    * `*_body` and `*_body_rim` textures (raw, lossless byte copy)   donor -> target

What is kept (target identity)
------------------------------
    * Face mesh, Hair mesh and their bones
    * `*_head` / `*_head_rim` textures and head material
    * AssetBundle name + container path (so it still installs as the TARGET costume)

Limitations
-----------
    * Costume appendage bones lose independent physics (they follow their anchor
      bone rigidly). Placement is exact; only the sway is gone.
    * Body proportions stay the target's; a wildly different donor silhouette may
      clip. SIFAS base bodies are close enough that this is rarely visible.
    * Verified on Unity 2018.4 uncompressed SIFAS model bundles. Compressed meshes
      are not handled.

Masked / board-face models (e.g. Tennoji Rina's "Rina-chan board", ch9999_co0035)
---------------------------------------------------------------------------------
A few members do not use the standard "Body + Hair + Face" 3-renderer layout: the
face is a screen made of dozens of *static* MeshRenderer parts (eye_*/mouth_*/Mask/
HeadSet_*) hung off an accessory head hierarchy (Head -> Head_All -> Head_Face) and
driven by MemberFace / BodyPartManager. The whole mask is parented under the body
`Head` bone, and the body-shape bones ship already at their LiveCoreMemberNodeScaling
`scaledValue` (Head localScale ~1.077). Realigning `Head` to the donor and re-anchoring
node-scaling against the usual `bone == originValue` invariant would warp the mask and
double-apply the body shape, which makes the model fail to load in-game. When such a
target is detected (or `--mask-handling on`), the head accessory-anchor bone is left
out of the realign and its node-scaling is kept intact. Use `--mask-handling off` to
force the plain behaviour.

Usage
-----
    # graphical interface (run with no arguments, or --gui):
    python3 costume_transplant.py

    # command line:
    python3 costume_transplant.py --donor YOU.unity --target MAKI.unity --out OUT.unity \
            [--physics] [--no-collision] [--no-realign]

On a desktop with tkinter the GUI opens automatically; on Termux/headless it
falls back to the CLI. The output replaces the target's model file 1:1 (same
bundle/container name), so you can either swap it in directly or feed it to
unity_costumemod_packer.py to build an installable mod package.
"""

import os
import re
import sys
import copy
import argparse
import importlib
import subprocess


# --------------------------------------------------------------------------
# dependency bootstrap (mirrors sifas_mesh_baker.py so Termux works too)
# --------------------------------------------------------------------------
def is_termux():
    if "com.termux" in (os.environ.get("PREFIX", "") + os.environ.get("HOME", "")):
        return True
    return os.path.isdir("/data/data/com.termux")


def _run(cmd):
    try:
        subprocess.run(cmd, check=True)
        return True
    except Exception:
        return False


def _pip_install(pip_name):
    cmd = [sys.executable, "-m", "pip", "install", pip_name]
    return _run(cmd + ["--break-system-packages", "-q"]) or _run(cmd + ["-q"])


def _pkg_install_termux(pkg):
    if _run(["pkg", "install", "-y", pkg]) or _run(["apt", "install", "-y", pkg]):
        return True
    _run(["apt", "update", "-y"])
    return _run(["pkg", "install", "-y", pkg]) or _run(["apt", "install", "-y", pkg])


_TERMUX_PKG = {"PIL": "python-pillow", "Pillow": "python-pillow"}


def ensure_module(import_name, pip_name=None):
    try:
        return importlib.import_module(import_name)
    except ImportError:
        pass
    pip_name = pip_name or import_name
    print(f"[setup] installing '{pip_name}' ...")
    if is_termux():
        pkg = _TERMUX_PKG.get(pip_name) or _TERMUX_PKG.get(import_name)
        if pkg:
            _pkg_install_termux(pkg)
            try:
                return importlib.import_module(import_name)
            except ImportError:
                pass
    _pip_install(pip_name)
    try:
        return importlib.import_module(import_name)
    except ImportError:
        print(f"[setup] could not install '{pip_name}'. Install it manually and re-run.")
        if is_termux():
            print("    pkg install -y python-pillow")
            print("    pip install UnityPy --break-system-packages")
        else:
            print(f"    pip install {pip_name}")
        sys.exit(1)


if is_termux():
    ensure_module("PIL", "Pillow")
UnityPy = ensure_module("UnityPy")
np = ensure_module("numpy")


# --------------------------------------------------------------------------
# world-space normalization (so SwingBone physics — ribbon/skirt — renders
# correctly; a costume mesh left in the donor's local space makes the *swinging*
# verts shift by the mesh-root offset at runtime). Same baking as
# fix_sifas_bundle_export.py, run on the written output (re-read avoids the
# save_typetree staleness from the graft).
# --------------------------------------------------------------------------
_FMT_BYTES = {0: 4, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2, 6: 1, 7: 1, 8: 2, 9: 2, 10: 4, 11: 4}


def _stream_layout(tree):
    vd = tree["m_VertexData"]; vc = vd["m_VertexCount"]; chans = vd["m_Channels"]
    by = {}
    for ch in chans:
        if ch.get("dimension", 0):
            by.setdefault(ch["stream"], []).append(ch)
    stride, start, cur = {}, {}, 0
    for s in sorted(by):
        stride[s] = max(c["offset"] + c["dimension"] * _FMT_BYTES[c["format"]] for c in by[s])
    for s in sorted(by):
        start[s] = cur
        cur = (cur + vc * stride[s] + 15) & ~15
    return vc, chans, stride, start


def _read_f(u8, chans, attr, stride, start, vc):
    ch = chans[attr]
    if ch.get("dimension", 0) == 0 or ch["format"] != 0:
        return None
    s, off, dim = ch["stream"], ch["offset"], ch["dimension"]
    blk = u8[start[s]:start[s] + vc * stride[s]].reshape(vc, stride[s])
    return blk[:, off:off + dim * 4].copy().view("<f4").reshape(vc, dim).astype(np.float64)


def _write_f(u8, arr, chans, attr, stride, start, vc):
    ch = chans[attr]; s, off, dim = ch["stream"], ch["offset"], ch["dimension"]
    blk = u8[start[s]:start[s] + vc * stride[s]].reshape(vc, stride[s])
    blk[:, off:off + dim * 4] = np.ascontiguousarray(arr[:, :dim], "<f4").view(np.uint8).reshape(vc, dim * 4)


def _qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y), 0],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x), 0],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y), 0],
                     [0, 0, 0, 1]], float)


def _trsmat(t, q, s):
    M = _qmat(q); M[:3, 0] *= s[0]; M[:3, 1] *= s[1]; M[:3, 2] *= s[2]
    M[0, 3], M[1, 3], M[2, 3] = t
    return M


def _bp_mat(b):
    return np.array([[b['e00'], b['e01'], b['e02'], b['e03']], [b['e10'], b['e11'], b['e12'], b['e13']],
                     [b['e20'], b['e21'], b['e22'], b['e23']], [b['e30'], b['e31'], b['e32'], b['e33']]], float)


def _mat_bp(M, dst):
    for r in range(4):
        for c in range(4):
            dst["e%d%d" % (r, c)] = float(M[r, c])


def worldspace_normalize(path, verbose=True):
    """Bake each skinned mesh's mesh-root transform into its vertices and fold the
    inverse into the bind poses, so meshRoot == I (world space). In-game render is
    unchanged, but SwingBone-driven pieces (ribbon/skirt) no longer shift."""
    def log(*a):
        if verbose:
            print(*a)
    env = UnityPy.load(path)
    uid = {o.path_id: o for o in env.objects}
    tf = {}
    for o in env.objects:
        if o.type.name == "Transform":
            t = o.read_typetree(); g = uid.get(t.get("m_GameObject", {}).get("m_PathID"))
            n = g.read().m_Name if g else None
            lp, lr, ls = t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"]
            tf[o.path_id] = (n, ([lp['x'], lp['y'], lp['z']], [lr['x'], lr['y'], lr['z'], lr['w']],
                                 [ls['x'], ls['y'], ls['z']]), t.get('m_Father', {}).get('m_PathID'),
                            [c['m_PathID'] for c in t.get('m_Children', [])])
    world = {}

    def cw(pid, P):
        n, (lp, lr, ls), fa, ch = tf[pid]; M = P @ _trsmat(lp, lr, ls); world[n] = M
        for c in ch:
            if c in tf:
                cw(c, M)
    for pid, (n, _, fa, ch) in tf.items():
        if fa not in tf:
            cw(pid, np.eye(4))

    n_fixed = 0
    for o in env.objects:
        if o.type.name != "SkinnedMeshRenderer":
            continue
        smr = o.read_typetree()
        if not smr.get("m_Bones"):
            continue
        mobj = uid.get(smr["m_Mesh"]["m_PathID"])
        if not mobj:
            continue
        tree = mobj.read_typetree()

        def bname(pid):
            x = uid.get(pid)
            if not x:
                return None
            g = uid.get(x.read_typetree().get("m_GameObject", {}).get("m_PathID"))
            return g.read().m_Name if g else None
        bnames = [bname(b["m_PathID"]) for b in smr["m_Bones"]]
        BP = tree.get("m_BindPose")
        if not BP or len(BP) != len(bnames):
            continue
        cand = [world[bnames[i]] @ _bp_mat(BP[i]) for i in range(len(bnames))
                if bnames[i] in world][:4]
        if not cand:
            continue
        mr = cand[0]
        if max(np.abs(c - mr).max() for c in cand) > 1e-3 or np.abs(mr - np.eye(4)).max() < 1e-5:
            continue
        R, inv = mr[:3, :3], np.linalg.inv(mr)
        vc, chans, stride, start = _stream_layout(tree)
        buf = bytearray(tree["m_VertexData"]["m_DataSize"]); u8 = np.frombuffer(buf, np.uint8)
        pos = _read_f(u8, chans, 0, stride, start, vc)
        if pos is None:
            continue
        _write_f(u8, (np.c_[pos, np.ones(len(pos))] @ mr.T)[:, :3], chans, 0, stride, start, vc)
        if np.abs(R - np.eye(3)).max() > 1e-6:
            for attr in (1, 2):
                a = _read_f(u8, chans, attr, stride, start, vc)
                if a is not None:
                    a2 = a.copy(); a2[:, :3] = a[:, :3] @ R.T
                    _write_f(u8, a2, chans, attr, stride, start, vc)
        tree["m_VertexData"]["m_DataSize"] = bytes(buf)
        for i in range(len(BP)):
            _mat_bp(_bp_mat(BP[i]) @ inv, BP[i])
        ab = tree.get("m_LocalAABB")
        if ab:
            c = ab["m_Center"]; nc = (mr @ np.array([c['x'], c['y'], c['z'], 1.0]))[:3]
            c['x'], c['y'], c['z'] = float(nc[0]), float(nc[1]), float(nc[2])
        mobj.save_typetree(tree)
        n_fixed += 1
        log(f"[ok] world-spaced mesh {tree.get('m_Name')!r} (mesh root {np.round(mr[:3,3],3)})")
    if n_fixed:
        bf = list(env.files.values())[0]; bf.mark_changed()
        with open(path, "wb") as f:
            f.write(bf.save(packer="original"))




# --------------------------------------------------------------------------
# LiveCoreMemberNodeScaling consistency
# --------------------------------------------------------------------------
# `LiveCoreMemberNodeScaling` (LLAS.Scene.Live.Components) overrides selected
# bones' local position / scale with a per-character body-shape `scaledValue`
# when the member spawns in a live, and stores `originValue` = the bone's
# *shipped* (unscaled) local value. The healthy invariant is therefore
#
#       bone.localPosition == positionValue.originValue
#       bone.localScale    == scaleValue.originValue
#
# Realigning the shared body bones to the donor's rest pose (apply_bone_edits)
# moves some of those bones, which breaks the invariant: at runtime the
# component then forces `scaledValue` and *teleports* the bone — e.g. it drags
# `Breast_Offset` (parent of the ribbon bones) down to the chest.
#
# We must NOT just zero the override — that throws away the character's body
# shaping. Instead we *re-anchor* it: keep the correction the entry encoded
# (the position delta `scaled - origin`, or the scale ratio `scaled / origin`)
# and rebuild it around the bone's new local value, so the same body-shape
# adjustment is reapplied on top of the costume's rest pose.
# --------------------------------------------------------------------------
def _is_node_scaling(mb):
    return "targetName" in mb and "scaleValues" in mb and "positionValues" in mb


def rebase_node_scaling(path, eps=1e-4, verbose=True):
    """Re-anchor every NodeScaling entry whose originValue drifted from its bone
    after a realign, preserving the body-shape correction. Runs on the written
    output (re-read avoids save_typetree staleness)."""
    def log(*a):
        if verbose:
            print(*a)

    env = UnityPy.load(path)
    objs = list(env.objects)
    uid = {o.path_id: o for o in objs}
    go = {o.path_id: o.read_typetree().get("m_Name") for o in objs if o.type.name == "GameObject"}

    def bone(pid):
        o = uid.get(pid)
        if not o or o.type.name != "Transform":
            return None, None
        t = o.read_typetree()
        return t, go.get(t.get("m_GameObject", {}).get("m_PathID"))

    total = 0
    skipped_total = 0
    for o in objs:
        if o.type.name != "MonoBehaviour":
            continue
        mb = o.read_typetree()
        if not _is_node_scaling(mb):
            continue
        changed = 0
        for pv in mb.get("positionValues", []):
            t, bn = bone(pv["target"]["m_PathID"])
            if t is None:
                continue
            lp = t["m_LocalPosition"]; ov = pv["originValue"]; sv = pv["scaledValue"]
            d_origin = max(abs(lp[k] - ov[k]) for k in "xyz")
            if d_origin <= eps:
                continue                       # healthy: bone already at originValue
            if max(abs(lp[k] - sv[k]) for k in "xyz") <= eps:
                # bone already AT scaledValue: this model SHIPS with the body shape
                # baked into the rest pose (e.g. the Rina-chan board), so the entry is
                # already consistent. Re-anchoring here would double-apply the offset.
                skipped_total += 1
                continue
            # additive body-shape offset, re-anchored to the new rest pose
            delta = {k: sv[k] - ov[k] for k in "xyz"}
            pv["originValue"] = {k: lp[k] for k in "xyz"}
            pv["scaledValue"] = {k: lp[k] + delta[k] for k in "xyz"}
            changed += 1
            log(f"   [rebase] POS  {bn}: origin -> {tuple(round(lp[k],4) for k in 'xyz')} "
                f"(kept offset {tuple(round(delta[k],4) for k in 'xyz')})")
        for sv in mb.get("scaleValues", []):
            t, bn = bone(sv["target"]["m_PathID"])
            if t is None:
                continue
            ls = t["m_LocalScale"]; ov = sv["originValue"]; sd = sv["scaledValue"]
            d_origin = max(abs(ls[k] - ov[k]) for k in "xyz")
            if d_origin <= eps:
                continue                       # healthy: bone already at originValue
            if max(abs(ls[k] - sd[k]) for k in "xyz") <= eps:
                # bone already AT scaledValue (model ships body-shape-applied): the
                # entry is already consistent, so re-anchoring would double the scale.
                skipped_total += 1
                continue
            # multiplicative body-shape ratio, re-anchored to the new scale
            ratio = {k: (sd[k] / ov[k] if abs(ov[k]) > 1e-9 else 1.0) for k in "xyz"}
            sv["originValue"] = {k: ls[k] for k in "xyz"}
            sv["scaledValue"] = {k: ls[k] * ratio[k] for k in "xyz"}
            changed += 1
            log(f"   [rebase] SCALE {bn}: origin -> {tuple(round(ls[k],4) for k in 'xyz')} "
                f"(kept ratio {tuple(round(ratio[k],3) for k in 'xyz')})")
        if changed:
            o.save_typetree(mb)
            total += changed
    if total:
        bf = list(env.files.values())[0]; bf.mark_changed()
        with open(path, "wb") as f:
            f.write(bf.save(packer="original"))
        log(f"[ok] re-anchored {total} NodeScaling entr{'y' if total == 1 else 'ies'} to the costume rest pose")
    if skipped_total:
        log(f"[mask] kept {skipped_total} NodeScaling entr{'y' if skipped_total == 1 else 'ies'} "
            f"intact (bone already at scaledValue — model ships body-shape-applied)")
    return total


# --------------------------------------------------------------------------
# bundle helpers
# --------------------------------------------------------------------------
def _index(env):
    objs = list(env.objects)
    return objs, {o.path_id: o for o in objs}


def _go_name(id2, go_pid):
    o = id2.get(go_pid)
    return o.read().m_Name if o else None


def _transform_goname(id2, tpid):
    o = id2.get(tpid)
    if not o:
        return None
    t = o.read_typetree()
    return _go_name(id2, t.get("m_GameObject", {}).get("m_PathID"))


def _name2transform(id2):
    m = {}
    for pid, o in id2.items():
        if o.type.name == "Transform":
            n = _transform_goname(id2, pid)
            if n is not None:
                m[n] = pid
    return m


def _transform_parent_byname(id2):
    """child GO name -> parent GO name (via Transform.m_Father)."""
    out = {}
    for pid, o in id2.items():
        if o.type.name != "Transform":
            continue
        t = o.read_typetree()
        cn = _go_name(id2, t.get("m_GameObject", {}).get("m_PathID"))
        fp = t.get("m_Father", {}).get("m_PathID")
        pn = _transform_goname(id2, fp) if fp else None
        if cn is not None:
            out[cn] = pn
    return out


def _local_trs_byname(id2):
    """GO name -> (m_LocalPosition, m_LocalRotation, m_LocalScale) dicts."""
    out = {}
    for pid, o in id2.items():
        if o.type.name != "Transform":
            continue
        t = o.read_typetree()
        n = _go_name(id2, t.get("m_GameObject", {}).get("m_PathID"))
        if n is not None:
            out[n] = (t["m_LocalPosition"], t["m_LocalRotation"], t["m_LocalScale"])
    return out


def apply_bone_edits(donor_id2, target_id2, bone_names, child_adds=None,
                     log=lambda *a: None):
    """Apply both kinds of per-bone edit in ONE save_typetree per object.

    1. realign: copy the donor's rest (local) transform onto each bone in
       `bone_names`. A costume's body mesh is authored against the donor's
       skeleton rest pose, so binding it to the wearer's slightly different bone
       positions shifts attached pieces (e.g. the chest ribbon floats high).
       Snapping the shared body bones to the donor's rest pose makes mesh + bind
       poses + bones self-consistent and the costume sits exactly as designed.
       Head/hair/face bones are not in this list, so identity is preserved.
    2. child_adds: append injected appendage roots to their parent bone's
       m_Children. Merged here because read_typetree() does not reflect a prior
       save on the same object, so a parent that is also realigned would lose one
       edit if the two were saved separately.
    """
    child_adds = child_adds or {}
    d_local = _local_trs_byname(donor_id2) if bone_names else {}
    realign_set = set(bone_names)
    # target name -> Transform ObjectReader
    t_tf = {}
    for pid, o in target_id2.items():
        if o.type.name == "Transform":
            n = _go_name(target_id2, o.read_typetree().get("m_GameObject", {}).get("m_PathID"))
            if n is not None:
                t_tf[n] = o
    n_re = 0
    for name in (realign_set | set(child_adds)):
        o = t_tf.get(name)
        if o is None:
            continue
        tt = o.read_typetree()
        if name in realign_set and name in d_local:
            lp, lr, ls = d_local[name]
            tt["m_LocalPosition"] = copy.deepcopy(lp)
            tt["m_LocalRotation"] = copy.deepcopy(lr)
            tt["m_LocalScale"] = copy.deepcopy(ls)
            n_re += 1
        existing = {c["m_PathID"] for c in tt.get("m_Children", [])}
        for cpid in child_adds.get(name, []):
            if cpid not in existing:   # never list a child twice (AssetStudio dup-key)
                tt.setdefault("m_Children", []).append({"m_FileID": 0, "m_PathID": cpid})
                existing.add(cpid)
        o.save_typetree(tt)
    if bone_names:
        log(f"[ok] realigned {n_re} body bone(s) to the costume's rest pose")
    return n_re


def _body_smr(objs):
    """The body SkinnedMeshRenderer: the skinned renderer with the most bones."""
    best = None
    best_n = -1
    for o in objs:
        if o.type.name == "SkinnedMeshRenderer":
            n = len(o.read_typetree().get("m_Bones", []))
            if n > best_n:
                best_n, best = n, o
    return best


def _mesh_by_pid(id2, pid):
    o = id2.get(pid)
    return o, (o.read_typetree() if o else None)


def _mesh_name_pid(objs, name):
    for o in objs:
        if o.type.name == "Mesh" and o.read_typetree().get("m_Name") == name:
            return o
    return None


def _material_textures(id2, mat_pid):
    """body material -> {'main': tex_pid, 'rim': tex_pid} from its _MainTex/_RimlightTex."""
    o = id2.get(mat_pid)
    out = {}
    if not o:
        return out
    sp = o.read_typetree().get("m_SavedProperties", {})
    for name, env in sp.get("m_TexEnvs", []):
        pid = env.get("m_Texture", {}).get("m_PathID", 0)
        if name == "_MainTex" and pid:
            out["main"] = pid
        elif name == "_RimlightTex" and pid:
            out["rim"] = pid
    return out


def _texname(id2, pid):
    o = id2.get(pid)
    return o.read().m_Name if o else None


def _raw_tex(id2, pid):
    o = id2.get(pid)
    return o.read().get_image_data() if o else None


def _chara_costume_id(env):
    """Pull chXXXX_coYYYY from the AssetBundle name."""
    for o in env.objects:
        if o.type.name == "AssetBundle":
            m = re.search(r"(ch\d{4})_(co\d{4})", o.read_typetree().get("m_Name", ""))
            if m:
                return m.group(1), m.group(2)
    return None, None


# --------------------------------------------------------------------------
# special-case detection: masked / "board-face" models (e.g. Rina-chan board)
# --------------------------------------------------------------------------
# A few SIFAS members are not the standard "Body + Hair + Face" 3-renderer model.
# Tennoji Rina's "Rina-chan board" (ch9999_co0035) renders her face as a screen:
# dozens of *static* MeshRenderer parts (eye_*/mouth_*/Mask/HeadSet_*) hang off an
# accessory head hierarchy (Head -> Head_All -> Head_Face) driven by MemberFace /
# BodyPartManager and a second Animator. Two things about such a model break the
# realign / node-scaling passes:
#   1. the whole mask is parented under a *body-skeleton* bone (Head), so realigning
#      that bone to the donor's rest pose drags/rescales the entire mask, and
#   2. the body-shape bones ship already at their LiveCoreMemberNodeScaling
#      `scaledValue` (Head localScale ~1.077, Move 0.927, ...), the opposite of the
#      `bone.local == originValue` invariant rebase_node_scaling expects, so the
#      re-anchor pass would double-apply the body shape.
# detect_board_face_model() spots these so transplant() can take the exceptional path.
def detect_board_face_model(objs, id2):
    """Return None for a standard model, else a dict describing the masked/board model:

        {"kind": "board-face",
         "face_parts": int,          # static face/mask MeshRenderers
         "anchor_bones": set[str],   # body bones carrying the mask subtree (e.g. {"Head"})
         "markers": list[str]}       # which signatures matched
    """
    body = _body_smr(objs)
    if body is None:
        return None

    # skeleton bone names = union of every skinned renderer's bone list, plus the
    # body renderer's bones on their own (so we can tell a real bone child from an
    # accessory child).
    skeleton, body_bones = set(), set()
    for o in objs:
        if o.type.name == "SkinnedMeshRenderer":
            for b in o.read_typetree().get("m_Bones", []):
                n = _transform_goname(id2, b["m_PathID"])
                if n:
                    skeleton.add(n)
    for b in body.read_typetree().get("m_Bones", []):
        n = _transform_goname(id2, b["m_PathID"])
        if n:
            body_bones.add(n)

    # which GameObjects own a MeshRenderer, and the transform graph
    go_with_mr = {o.read_typetree().get("m_GameObject", {}).get("m_PathID")
                  for o in objs if o.type.name == "MeshRenderer"}
    tf_children, tf_goname, tf_gopid, name2tfpid = {}, {}, {}, {}
    for o in objs:
        if o.type.name == "Transform":
            t = o.read_typetree()
            gp = t.get("m_GameObject", {}).get("m_PathID")
            tf_gopid[o.path_id] = gp
            nm = _go_name(id2, gp)
            tf_goname[o.path_id] = nm
            tf_children[o.path_id] = [c["m_PathID"] for c in t.get("m_Children", [])]
            if nm and nm not in name2tfpid:
                name2tfpid[nm] = o.path_id

    def subtree_has_mr(tpid):
        stack, seen = [tpid], set()
        while stack:
            p = stack.pop()
            if p in seen:
                continue
            seen.add(p)
            if tf_gopid.get(p) in go_with_mr:
                return True
            stack.extend(tf_children.get(p, []))
        return False

    # a body bone is an accessory anchor if it has a NON-skeletal child whose subtree
    # contains static mesh parts (the mask / face board)
    anchor_bones = set()
    for bn in body_bones:
        tpid = name2tfpid.get(bn)
        if tpid is None:
            continue
        for cpid in tf_children.get(tpid, []):
            if tf_goname.get(cpid) in skeleton:
                continue
            if subtree_has_mr(cpid):
                anchor_bones.add(bn)
                break

    have = set(_scriptname_map(objs).values())
    face_parts = sum(1 for gp in go_with_mr
                     if not (_go_name(id2, gp) or "").startswith("Shadow"))

    # a board-face model has a body bone carrying mesh accessories AND either the
    # dedicated face component or a meaningful number of static face parts.
    if not anchor_bones or not ("MemberFace" in have or face_parts >= 4):
        return None
    markers = [m for m in ("MemberFace", "BodyPartManager") if m in have]
    markers.append("anchor:" + ",".join(sorted(anchor_bones)))
    return {"kind": "board-face", "face_parts": face_parts,
            "anchor_bones": anchor_bones, "markers": markers}


def detect_board_face_model_path(path):
    """Convenience wrapper: load a bundle and run detect_board_face_model on it."""
    objs, id2 = _index(UnityPy.load(path))
    return detect_board_face_model(objs, id2)


# --------------------------------------------------------------------------
# object injection (used to preserve costume jiggle physics)
# --------------------------------------------------------------------------
def _serialized_file(env):
    bf = list(env.files.values())[0]
    sf = [v for v in bf.files.values() if type(v).__name__ == "SerializedFile"][0]
    return bf, sf


def _scriptname_map(objs):
    return {o.path_id: o.read_typetree().get("m_ClassName")
            for o in objs if o.type.name == "MonoScript"}


def _find_swingbone_manager(objs, scriptnames):
    for o in objs:
        if o.type.name == "MonoBehaviour" and \
                scriptnames.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) == "SwingBoneManager":
            return o
    return None


def _manager_colliders(objs, id2, scriptnames):
    """Ordered manager collider list as [(collider_path_id, owning_bone_name), ...].

    A SwingBone references colliders both by PPtr (`colliders`) and by 1-based
    index into this list (`colliderIds`, where 0 means none)."""
    mgr = _find_swingbone_manager(objs, scriptnames)
    out = []
    if not mgr:
        return out
    for c in mgr.read_typetree().get("colliders", []):
        pid = c.get("m_PathID")
        co = id2.get(pid)
        bone = None
        if co:
            bone = _go_name(id2, co.read_typetree().get("m_GameObject", {}).get("m_PathID"))
        out.append((pid, bone))
    return out


def _swingbone_script_pid(objs, scriptnames):
    for pid, n in scriptnames.items():
        if n == "SwingBone":
            return pid
    return None


def _template(objs, cls, scriptnames=None, script_class=None):
    for o in objs:
        if o.type.name != cls:
            continue
        if script_class is None:
            return o
        if scriptnames.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) == script_class:
            return o
    return None


def _make_object(sf, template, new_pid, tree):
    """Append a brand-new object to a SerializedFile, reusing template's type info."""
    from UnityPy.files.ObjectReader import ObjectReader
    o = ObjectReader(
        assets_file=sf, reader=template.reader, path_id=new_pid,
        type_id=template.type_id, serialized_type=template.serialized_type,
        class_id=template.class_id, type=template.type,
        byte_start=template.byte_start, byte_size=template.byte_size,
        is_destroyed=getattr(template, "is_destroyed", 0),
        is_stripped=getattr(template, "is_stripped", 0),
    )
    sf.objects[new_pid] = o
    o.save_typetree(tree)
    return o


def _rand_pids(n, used):
    import random
    out = []
    while len(out) < n:
        p = random.randint(10 ** 17, 9 * 10 ** 17)
        if p not in used and p not in out:
            out.append(p)
    return out


def inject_appendage_bones(donor, target, inject_names, name2tf_target,
                           restore_collision=True, log=lambda *a: None):
    """Recreate donor costume-appendage bone chains (GameObject + Transform + their
    SwingBone components) inside the target bundle so the jiggle physics survives.

    With restore_collision, each injected SwingBone's body-collision references are
    remapped from the donor's SwingColliders to the target's equivalent colliders
    (matched by the bone they sit on), so the appendage still collides with the body
    instead of clipping through it.

    Returns ({donor_bone_name: new_target_transform_path_id}, child_adds).
    """
    do, did = _index(donor)
    to, tid = _index(target)
    _, t_sf = _serialized_file(target)

    d_scripts = _scriptname_map(do)
    t_scripts = _scriptname_map(to)

    # collider remap tables (donor collider pid -> bone; target bone -> pid/index) --
    d_cols = _manager_colliders(do, did, d_scripts)
    t_cols = _manager_colliders(to, tid, t_scripts)
    d_colpid_to_bone = {pid: bone for pid, bone in d_cols}
    t_bone_to_colpid = {bone: pid for pid, bone in t_cols if bone}
    t_bone_to_colidx = {bone: i for i, (pid, bone) in enumerate(t_cols) if bone}

    # donor lookups -----------------------------------------------------------
    d_go_by_name, d_tf_by_go, d_tfpid_to_goname = {}, {}, {}
    for o in do:
        if o.type.name == "GameObject":
            d_go_by_name[o.read().m_Name] = o
    for o in do:
        if o.type.name == "Transform":
            t = o.read_typetree()
            gp = t.get("m_GameObject", {}).get("m_PathID")
            d_tf_by_go[gp] = o
            d_tfpid_to_goname[o.path_id] = _go_name(did, gp)
    d_goname_to_pid = {n: g.path_id for n, g in d_go_by_name.items()}
    # SwingBone component(s) keyed by owning GameObject name
    d_swing_by_goname = {}
    for o in do:
        if o.type.name == "MonoBehaviour" and \
                d_scripts.get(o.read_typetree().get("m_Script", {}).get("m_PathID")) == "SwingBone":
            t = o.read_typetree()
            gn = _go_name(did, t.get("m_GameObject", {}).get("m_PathID"))
            if gn:
                d_swing_by_goname[gn] = t

    # target infrastructure ---------------------------------------------------
    t_sb_script = _swingbone_script_pid(to, t_scripts)
    t_mgr = _find_swingbone_manager(to, t_scripts)
    go_tmpl = _template(to, "GameObject")
    tf_tmpl = _template(to, "Transform")
    mb_tmpl = _template(to, "MonoBehaviour", t_scripts, "SwingBone")
    if not (t_mgr and go_tmpl and tf_tmpl and mb_tmpl and t_sb_script):
        raise RuntimeError("target lacks SwingBone infrastructure; cannot preserve physics")

    used = set(t_sf.objects.keys())
    # allocate new path ids: GO + TF per bone, MB per swingbone
    inject_names = [n for n in inject_names if n in d_go_by_name]
    go_pid = dict(zip(inject_names, _rand_pids(len(inject_names), used)))
    used |= set(go_pid.values())
    tf_pid = dict(zip(inject_names, _rand_pids(len(inject_names), used)))
    used |= set(tf_pid.values())
    swing_owners = [n for n in inject_names if n in d_swing_by_goname]
    mb_pid = dict(zip(swing_owners, _rand_pids(len(swing_owners), used)))
    used |= set(mb_pid.values())

    def tf_of(name):
        """target transform pid for a bone name: injected -> new, else existing rig."""
        if name in tf_pid:
            return tf_pid[name]
        return name2tf_target.get(name)

    new_swing_pids = []
    d_parent = _transform_parent_byname(did)

    for name in inject_names:
        d_go = d_go_by_name[name]
        d_tf = d_tf_by_go[d_go.path_id]
        d_go_tt = d_go.read_typetree()
        d_tf_tt = d_tf.read_typetree()

        # ---- GameObject ----
        go_tt = copy.deepcopy(d_go_tt)
        comps = [{"component": {"m_FileID": 0, "m_PathID": tf_pid[name]}}]
        if name in mb_pid:
            comps.append({"component": {"m_FileID": 0, "m_PathID": mb_pid[name]}})
        go_tt["m_Component"] = comps
        _make_object(t_sf, go_tmpl, go_pid[name], go_tt)

        # ---- Transform ----
        tf_tt = copy.deepcopy(d_tf_tt)
        tf_tt["m_GameObject"] = {"m_FileID": 0, "m_PathID": go_pid[name]}
        father_name = d_parent.get(name)
        tf_tt["m_Father"] = {"m_FileID": 0, "m_PathID": tf_of(father_name) or 0}
        # children: ONLY other injected appendage bones. Never list a native
        # target bone here — that bone already has its own parent, and claiming
        # it would give it two parents, which makes AssetStudio's model export
        # throw "An item with the same key has already been added".
        children, seen_ch = [], set()
        for c in d_tf_tt.get("m_Children", []):
            cn = d_tfpid_to_goname.get(c["m_PathID"])
            cp = tf_pid.get(cn)
            if cp and cp not in seen_ch:
                children.append({"m_FileID": 0, "m_PathID": cp})
                seen_ch.add(cp)
        tf_tt["m_Children"] = children
        _make_object(t_sf, tf_tmpl, tf_pid[name], tf_tt)

    # ---- SwingBone components ----
    # SwingBones in a chain (e.g. a 4-bone necktie) reference each other by
    # *integer index* into SwingBoneManager.bones (parent/child/siblingIndex,
    # -1 = none). Those indices are donor-relative, so they must be rewritten to
    # the injected bones' new positions in the target manager (appended after the
    # target's existing bones, in swing_owners order). References to a shared bone
    # already present in the target keep that bone's index; anything unresolved
    # becomes -1.
    d_mgr_tt = _find_swingbone_manager(do, d_scripts).read_typetree()
    donor_idx_name = []
    for b in d_mgr_tt.get("bones", []):
        co = did.get(b["m_PathID"])
        donor_idx_name.append(_go_name(did, co.read_typetree().get("m_GameObject", {}).get("m_PathID")) if co else None)
    t_existing_bones = t_mgr.read_typetree().get("bones", [])
    base = len(t_existing_bones)
    target_name_idx = {}
    for i, b in enumerate(t_existing_bones):
        co = tid.get(b["m_PathID"])
        nm = _go_name(tid, co.read_typetree().get("m_GameObject", {}).get("m_PathID")) if co else None
        if nm:
            target_name_idx[nm] = i
    inj_owner_newidx = {nm: base + k for k, nm in enumerate(swing_owners)}

    def remap_idx(idx):
        if idx is None or idx < 0 or idx >= len(donor_idx_name):
            return -1
        nm = donor_idx_name[idx]
        if nm in inj_owner_newidx:
            return inj_owner_newidx[nm]
        return target_name_idx.get(nm, -1)

    # Base the injected components on a REAL target SwingBone typetree, then
    # overlay the donor's values for shared fields. The donor and target bundles
    # can carry different SwingBone script schemas (e.g. the target adds
    # kneeSpaceOffsetMax); writing the donor tree against the target type would
    # KeyError on the missing field. Starting from the target's own instance
    # guarantees every field the target schema expects is present.
    base_sb_tt = mb_tmpl.read_typetree()
    _skip = ("m_GameObject", "m_Script", "m_Name", "m_Enabled")
    for name in swing_owners:
        donor_sb = d_swing_by_goname[name]
        sb = copy.deepcopy(base_sb_tt)
        for k in sb:
            if k in donor_sb and k not in _skip:
                sb[k] = copy.deepcopy(donor_sb[k])
        sb["m_GameObject"] = {"m_FileID": 0, "m_PathID": go_pid[name]}
        sb["m_Script"] = {"m_FileID": 0, "m_PathID": t_sb_script}
        child_goname = d_tfpid_to_goname.get(sb.get("child", {}).get("m_PathID"))
        sb["child"] = {"m_FileID": 0, "m_PathID": tf_of(child_goname) or 0}
        sib_goname = d_tfpid_to_goname.get(sb.get("sibling", {}).get("m_PathID"))
        sb["sibling"] = {"m_FileID": 0, "m_PathID": tf_of(sib_goname) or 0}
        # rewrite the chain indices to the target manager's numbering
        for key in ("parentIndex", "childIndex", "siblingIndex"):
            if key in sb:
                sb[key] = remap_idx(sb[key])
        # body colliders are bundle-specific objects: remap them to the target's
        # collider on the same bone (colliderIds are 1-based indices into the
        # manager's collider list, 0 = none). Drop refs whose bone is absent.
        new_cols, new_ids = [], []
        if restore_collision:
            for c in donor_sb.get("colliders", []):
                bone = d_colpid_to_bone.get(c.get("m_PathID"))
                if bone in t_bone_to_colpid:
                    new_cols.append({"m_FileID": 0, "m_PathID": t_bone_to_colpid[bone]})
                    new_ids.append(t_bone_to_colidx[bone] + 1)
        if "colliders" in sb:
            sb["colliders"] = new_cols
        if "colliderIds" in sb:
            sb["colliderIds"] = new_ids
        _make_object(t_sf, mb_tmpl, mb_pid[name], sb)
        new_swing_pids.append(mb_pid[name])

    # ---- roots to attach to an existing target bone's child list ----
    # Returned (not saved here) so it can be merged with the bone-realign pass:
    # read_typetree does not see a prior save_typetree on the same object, so a
    # parent bone that is ALSO realigned must receive both edits in one save.
    child_adds = {}   # target parent bone name -> [new child transform pids]
    for name in inject_names:
        father_name = d_parent.get(name)
        if father_name in tf_pid:          # parent is itself injected; already wired
            continue
        if name2tf_target.get(father_name) is None:
            continue
        child_adds.setdefault(father_name, []).append(tf_pid[name])

    # ---- register new swing bones with the manager ----
    if new_swing_pids:
        mtt = t_mgr.read_typetree()
        mtt.setdefault("bones", []).extend(
            {"m_FileID": 0, "m_PathID": p} for p in new_swing_pids)
        t_mgr.save_typetree(mtt)

    log(f"[ok] injected {len(inject_names)} bone(s) with {len(new_swing_pids)} swing "
        f"component(s): {', '.join(inject_names)}")
    return {n: tf_pid[n] for n in inject_names}, child_adds


def sync_body_material(donor, target, d_mat_pid, t_mat_pid, log=lambda *a: None):
    """Replace the wearer's body material properties + textures with the costume's.

    Overwriting only the _MainTex/_RimlightTex pixel bytes (the old approach)
    breaks when the costume's textures differ in size/format (the body header and
    payload disagree -> garbled) and silently drops costume-only effects such as a
    matcap (the donor sets _MATCAP=1 with _MatcapTex/_MatcapMaskTex the wearer
    lacks). This copies the donor body material's saved properties (floats/colors)
    and, for every texture slot, writes the donor texture's FULL metadata + pixels:
    reusing the wearer's same-slot texture object where it has one, or injecting a
    brand-new Texture2D (matcap/emissive) where it does not. The wearer's body
    shader is kept (SIFAS bodies share one shader); head textures stay untouched.
    """
    do, did = _index(donor)
    to, tid = _index(target)
    _, t_sf = _serialized_file(target)
    d_mat, t_mat = did.get(d_mat_pid), tid.get(t_mat_pid)
    if not d_mat or not t_mat:
        return
    d_mat_tt, t_mat_tt = d_mat.read_typetree(), t_mat.read_typetree()
    d_tex = {o.path_id: o for o in do if o.type.name == "Texture2D"}
    tex_tmpl = next((o for o in to if o.type.name == "Texture2D"), None)
    used = set(t_sf.objects.keys())
    # texture metadata fields to carry over (everything but name + payload)
    META = ("m_ForcedFallbackFormat", "m_DownscaleFallback", "m_Width", "m_Height",
            "m_CompleteImageSize", "m_TextureFormat", "m_MipCount", "m_IsReadable",
            "m_StreamingMipmaps", "m_StreamingMipmapsPriority", "m_ImageCount",
            "m_TextureDimension", "m_TextureSettings", "m_LightmapFormat", "m_ColorSpace")

    def overwrite_tex(t_obj, d_obj):
        dtt = d_obj.read_typetree()
        ttt = t_obj.read_typetree()
        for k in META:
            if k in dtt:
                ttt[k] = copy.deepcopy(dtt[k])
        ttt["image data"] = d_obj.read().get_image_data()
        ttt["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
        t_obj.save_typetree(ttt)

    def inject_tex(d_obj):
        dtt = copy.deepcopy(d_obj.read_typetree())
        dtt["image data"] = d_obj.read().get_image_data()
        dtt["m_StreamData"] = {"offset": 0, "size": 0, "path": ""}
        npid = _rand_pids(1, used)[0]
        used.add(npid)
        _make_object(t_sf, tex_tmpl, npid, dtt)
        return npid

    # wearer's current texture per material slot (so we reuse its texture objects)
    t_slot_pid = {}
    for pair in t_mat_tt.get("m_SavedProperties", {}).get("m_TexEnvs", []):
        t_slot_pid[pair[0]] = pair[1].get("m_Texture", {}).get("m_PathID", 0)

    sp = copy.deepcopy(d_mat_tt.get("m_SavedProperties", {}))
    injected_by_name = {}
    n_over = n_inj = 0
    for pair in sp.get("m_TexEnvs", []):
        slot, env = pair[0], pair[1]
        tex = env.get("m_Texture", {})
        dpid = tex.get("m_PathID", 0)
        if not dpid or dpid not in d_tex:
            tex["m_PathID"], tex["m_FileID"] = 0, 0   # never leak a donor path id
            continue
        d_obj = d_tex[dpid]
        existing = t_slot_pid.get(slot, 0)
        if existing and existing in tid:
            overwrite_tex(tid[existing], d_obj)
            tpid = existing
            n_over += 1
        else:
            dname = d_obj.read_typetree()["m_Name"]
            if dname in injected_by_name:
                tpid = injected_by_name[dname]
            else:
                tpid = inject_tex(d_obj)
                injected_by_name[dname] = tpid
                n_inj += 1
        tex["m_PathID"], tex["m_FileID"] = tpid, 0
    # keep wearer's shader + material name; swap in the costume's properties
    t_mat_tt["m_SavedProperties"] = sp
    t_mat.save_typetree(t_mat_tt)
    log(f"[ok] body material synced: {n_over} texture(s) overwritten, "
        f"{n_inj} injected (matcap/emissive), properties copied")


# --------------------------------------------------------------------------
# core
# --------------------------------------------------------------------------
def transplant(donor_path, target_path, out_path, verbose=True,
               preserve_physics=False, realign=True, restore_collision=True,
               worldspace=True, fix_nodescaling=True, mask_handling="auto"):
    def log(*a):
        if verbose:
            print(*a)

    donor = UnityPy.load(donor_path)
    target = UnityPy.load(target_path)
    do, did = _index(donor)
    to, tid = _index(target)

    dch, dco = _chara_costume_id(donor)
    tch, tco = _chara_costume_id(target)
    log(f"[info] donor (costume) : {dch}_{dco}")
    log(f"[info] target (wearer) : {tch}_{tco}")

    # ---- special-case masked / board-face targets (e.g. Rina-chan board) ----
    # mask_handling: "auto" detect, "on" force, "off" disable. When active, the head
    # accessory-anchor bone is kept out of the realign so the mask is not warped; its
    # node-scaling is preserved by rebase_node_scaling's scaledValue guard.
    board = detect_board_face_model(to, tid) if mask_handling != "off" else None
    if mask_handling == "on" and board is None:
        board = {"kind": "board-face(forced)", "face_parts": 0,
                 "anchor_bones": {"Head"}, "markers": ["forced"]}
    if board:
        log(f"[mask] masked / board-face target detected: {board['face_parts']} face "
            f"part(s); markers: {', '.join(board['markers'])}. Exceptional handling ON — "
            f"keeping accessory-anchor bone(s) {sorted(board['anchor_bones'])} out of the "
            f"realign and preserving their node-scaling.")

    # ---- donor body renderer / mesh ----
    d_smr = _body_smr(do)
    d_smr_tt = d_smr.read_typetree()
    d_bone_names = [_transform_goname(did, b["m_PathID"]) for b in d_smr_tt["m_Bones"]]
    d_mesh_obj, d_mesh_tt = _mesh_by_pid(did, d_smr_tt["m_Mesh"]["m_PathID"])
    d_mesh_name = d_mesh_tt.get("m_Name")

    # ---- target body renderer / mesh ----
    t_smr = _body_smr(to)
    t_smr_tt = t_smr.read_typetree()
    t_mesh_obj = _mesh_name_pid(to, d_mesh_name) or _mesh_by_pid(tid, t_smr_tt["m_Mesh"]["m_PathID"])[0]

    name2tf = _name2transform(tid)
    native_target_bones = set(name2tf)   # before any appendage injection
    d_parent = _transform_parent_byname(did)
    d_name_to_idx = {n: i for i, n in enumerate(d_bone_names)}

    # ---- optionally recreate costume-appendage bones (with their jiggle physics) ----
    # When enabled, the donor's costume-only bones are injected into the target as
    # real GameObjects/Transforms + SwingBone components, so they keep their sway.
    # The injected transforms then resolve via name2tf like any native bone and use
    # the donor mesh's original bind poses (no rigid override).
    child_adds = {}
    if preserve_physics:
        inject_names = [n for n in dict.fromkeys(d_bone_names)
                        if n is not None and n not in name2tf]
        if inject_names:
            new_map, child_adds = inject_appendage_bones(
                donor, target, inject_names, name2tf,
                restore_collision=restore_collision, log=log)
            name2tf.update(new_map)

    # ---- resolve every donor body bone to a target transform ----
    # costume-specific bones still absent in target re-bind to the nearest ancestor
    # that exists in the target AND in the donor bone list (for its bind pose).
    bone_pids = []
    bindpose_override = {}   # donor bone index -> donor bone index whose bindpose to copy
    rebinds = []
    for i, n in enumerate(d_bone_names):
        if n in name2tf:
            bone_pids.append(name2tf[n])
            continue
        anc = d_parent.get(n)
        while anc is not None and not (anc in name2tf and anc in d_name_to_idx):
            anc = d_parent.get(anc)
        if anc is None:
            anc = "Hips"  # last-resort anchor
        bone_pids.append(name2tf[anc])
        if anc in d_name_to_idx:
            bindpose_override[i] = d_name_to_idx[anc]
        rebinds.append((n, anc))
    if rebinds:
        log(f"[info] costume bones rigidly re-bound to wearer rig: "
            + ", ".join(f"{n}->{a}" for n, a in rebinds))

    missing = [n for n, _ in rebinds if n is None]
    if missing:
        raise RuntimeError("unnamed donor bones; unexpected rig")

    # ---- 1) graft donor body mesh into target mesh object (keep target pid/name) ----
    new_mesh_tt = copy.deepcopy(d_mesh_tt)
    bp = new_mesh_tt.get("m_BindPose", [])
    for slot, src_idx in bindpose_override.items():
        bp[slot] = copy.deepcopy(bp[src_idx])
    new_mesh_tt["m_Name"] = t_mesh_obj.read_typetree().get("m_Name", new_mesh_tt.get("m_Name"))
    t_mesh_obj.save_typetree(new_mesh_tt)
    log(f"[ok] body mesh grafted: {new_mesh_tt['m_VertexData']['m_VertexCount']} verts, "
        f"{len(bp)} bind poses")

    # ---- 2) rewrite target body SMR bone list + bounds ----
    t_smr_tt["m_Bones"] = [{"m_FileID": 0, "m_PathID": pid} for pid in bone_pids]
    t_smr_tt["m_AABB"] = copy.deepcopy(d_smr_tt["m_AABB"])
    # match submesh/material count (SIFAS body = single submesh; guard anyway)
    n_sub = len(new_mesh_tt.get("m_SubMeshes", [])) or 1
    mats = t_smr_tt.get("m_Materials", [])
    if mats:
        body_mat = mats[0]
        t_smr_tt["m_Materials"] = [copy.deepcopy(body_mat) for _ in range(n_sub)]
    t_smr.save_typetree(t_smr_tt)
    log(f"[ok] body renderer rewired: {len(bone_pids)} bones, {n_sub} submesh(es)")

    # ---- 3) sync body material: properties + every texture slot (incl. matcap) ----
    d_body_mat = d_smr_tt.get("m_Materials", [{}])[0].get("m_PathID")
    t_body_mat = t_smr_tt.get("m_Materials", [{}])[0].get("m_PathID")
    sync_body_material(donor, target, d_body_mat, t_body_mat, log)

    # ---- 4) snap the wearer's body bones to the costume's rest pose, and wire
    #         any injected appendage roots into their parent (one save per bone) ----
    align_names = ([n for n in dict.fromkeys(d_bone_names) if n in native_target_bones]
                   if realign else [])
    if board and align_names:
        # never snap an accessory-anchor bone (e.g. Head, which carries the whole
        # mask) to the donor's rest pose — that would drag/rescale the mask.
        protected = [n for n in align_names if n in board["anchor_bones"]]
        align_names = [n for n in align_names if n not in board["anchor_bones"]]
        if protected:
            log(f"[mask] excluded {protected} from realign (mask anchor)")
    if align_names or child_adds:
        apply_bone_edits(did, tid, align_names, child_adds, log)

    # ---- write ----
    bf, _ = _serialized_file(target)
    bf.mark_changed()
    with open(out_path, "wb") as f:
        f.write(bf.save(packer="original"))

    # ---- 6) bake the grafted body mesh into world space (re-read the file so it
    #         reflects the graft; needed so swinging pieces like the ribbon render
    #         in the right place in-game) ----
    if worldspace:
        worldspace_normalize(out_path, verbose=verbose)

    # ---- 7) keep LiveCoreMemberNodeScaling consistent with the realigned bones
    #         so the runtime body-shape pass doesn't teleport ribbon/skirt pieces
    #         (the correction is preserved, only re-anchored to the new rest) ----
    if fix_nodescaling and realign:
        rebase_node_scaling(out_path, verbose=verbose)

    log(f"[done] wrote {out_path}")
    return out_path


def validate(out_path, verbose=True):
    """Re-load the output and assert no dangling references remain in the bits we
    touched: SkinnedMeshRenderer bones/mesh, SwingBoneManager bones and the
    SwingBone child/sibling pointers of any injected appendage bones."""
    env = UnityPy.load(out_path)
    objs, id2 = _index(env)
    scripts = _scriptname_map(objs)
    dangling = 0
    # hierarchy must stay a clean tree: every Transform listed under exactly one
    # parent, once. Otherwise AssetStudio's export throws a duplicate-key error.
    child_parents = {}
    hier_problems = 0
    for o in objs:
        if o.type.name == "Transform":
            seen = set()
            for c in o.read_typetree().get("m_Children", []):
                cp = c["m_PathID"]
                if cp in seen:
                    hier_problems += 1
                seen.add(cp)
                child_parents.setdefault(cp, 0)
                child_parents[cp] += 1
    hier_problems += sum(1 for n in child_parents.values() if n > 1)
    if hier_problems and verbose:
        print(f"[validate] WARNING: {hier_problems} transform(s) with multiple/duplicate "
              f"parents — run fix_unity_hierarchy.py before exporting in AssetStudio")
    for o in objs:
        if o.type.name == "SkinnedMeshRenderer":
            t = o.read_typetree()
            for b in t.get("m_Bones", []):
                if b["m_PathID"] not in id2:
                    dangling += 1
            mp = t.get("m_Mesh", {}).get("m_PathID")
            if mp and mp not in id2:
                dangling += 1
        elif o.type.name == "MonoBehaviour":
            cls = scripts.get(o.read_typetree().get("m_Script", {}).get("m_PathID"))
            t = o.read_typetree()
            if cls == "SwingBoneManager":
                for b in t.get("bones", []):
                    if b["m_PathID"] not in id2:
                        dangling += 1
            elif cls == "SwingBone":
                for key in ("child", "sibling"):
                    pid = t.get(key, {}).get("m_PathID", 0)
                    if pid and pid not in id2:
                        dangling += 1
    if verbose:
        print(f"[validate] dangling references: {dangling}")
    return dangling == 0


def build_parser():
    p = argparse.ArgumentParser(
        description="Transplant a SIFAS costume from a donor model bundle onto a target "
                    "character's model bundle (target keeps its face/hair/identity).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--donor", help="bundle whose COSTUME you want (second character)")
    p.add_argument("--target",
                   help="bundle of the character that should WEAR it (first character)")
    p.add_argument("--out", help="output bundle path")
    p.add_argument("--physics", action="store_true",
                   help="recreate costume-appendage bones (collar/cape/ribbon) as real "
                        "bones with their SwingBone jiggle physics, instead of rigidly "
                        "anchoring them. Body collision is remapped to the wearer's "
                        "colliders (use --no-collision to drop it instead)")
    p.add_argument("--no-collision", action="store_true",
                   help="with --physics, do not remap body collision for injected bones")
    p.add_argument("--no-realign", action="store_true",
                   help="do NOT snap the wearer's body bones to the costume's rest pose "
                        "(keeps the wearer's exact body proportions, but costume pieces "
                        "such as the chest ribbon may sit offset)")
    p.add_argument("--no-worldspace", action="store_true",
                   help="do NOT bake the body mesh into world space (leave it in the "
                        "donor's local space; swinging pieces like the ribbon may shift)")
    p.add_argument("--no-nodescaling-fix", action="store_true",
                   help="do NOT re-anchor LiveCoreMemberNodeScaling to the realigned bones "
                        "(the runtime body-shape pass may then teleport ribbon/skirt pieces "
                        "to the chest). The character's body shaping is preserved either way)")
    p.add_argument("--mask-handling", choices=["auto", "on", "off"], default="auto",
                   help="special handling for masked / board-face targets (e.g. Tennoji "
                        "Rina's Rina-chan board): keep the head accessory-anchor bone out of "
                        "the realign and never double-apply node-scaling. 'auto' (default) "
                        "detects the model, 'on' forces it, 'off' uses the plain behaviour.")
    p.add_argument("--gui", action="store_true", help="force the graphical interface")
    p.add_argument("-q", "--quiet", action="store_true", help="less logging")
    return p


def run_cli(args):
    if not (args.donor and args.target and args.out):
        build_parser().error("--donor, --target and --out are required "
                             "(or run with no arguments for the GUI)")
    transplant(args.donor, args.target, args.out,
               verbose=not args.quiet, preserve_physics=args.physics,
               realign=not args.no_realign, restore_collision=not args.no_collision,
               worldspace=not args.no_worldspace,
               fix_nodescaling=not args.no_nodescaling_fix,
               mask_handling=args.mask_handling)
    ok = validate(args.out, verbose=not args.quiet)
    if not ok:
        print("[error] output has dangling references; aborting", file=sys.stderr)
        sys.exit(2)
    print("[success] costume transplant complete and verified")


# --------------------------------------------------------------------------
# GUI (optional; falls back to the CLI where tkinter/$DISPLAY is unavailable)
# --------------------------------------------------------------------------
def gui_available():
    if is_termux():
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

    root = tk.Tk()
    root.title("SIFAS Costume Transplant")
    root.geometry("760x560")

    donor_v = tk.StringVar()
    target_v = tk.StringVar()
    out_v = tk.StringVar()
    physics_v = tk.BooleanVar(value=True)
    collision_v = tk.BooleanVar(value=True)
    realign_v = tk.BooleanVar(value=True)
    _auto = {"val": ""}   # last auto-suggested output; lets us tell auto from manual

    def suggest_out(*_):
        # keep the output name following the target until the user edits it by hand
        cur = out_v.get()
        if target_v.get() and (cur == "" or cur == _auto["val"]):
            base, ext = os.path.splitext(target_v.get())
            nv = base + "_modded" + (ext or ".unity")
            _auto["val"] = nv
            out_v.set(nv)

    target_v.trace_add("write", suggest_out)

    def pick(var, save=False):
        if save:
            path = filedialog.asksaveasfilename(
                title="Save output bundle", defaultextension=".unity",
                filetypes=[("Unity bundle", "*.unity *.unity3d"), ("All files", "*.*")])
        else:
            path = filedialog.askopenfilename(
                title="Select bundle",
                filetypes=[("Unity bundle", "*.unity *.unity3d"), ("All files", "*.*")])
        if path:
            var.set(path)

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="x")
    frm.columnconfigure(1, weight=1)
    rows = [
        ("Donor  (costume source)", donor_v, False),
        ("Target (wearer / identity)", target_v, False),
        ("Output bundle", out_v, True),
    ]
    for i, (label, var, save) in enumerate(rows):
        ttk.Label(frm, text=label, width=24).grid(row=i, column=0, sticky="w", pady=3)
        ent = ttk.Entry(frm, textvariable=var, width=62)
        ent.grid(row=i, column=1, padx=4, sticky="we")

        # show the END of the path (the filename) when it's longer than the box
        def _show_end(*_, e=ent):
            e.after_idle(lambda: e.xview_moveto(1.0))
        var.trace_add("write", _show_end)

        ttk.Button(frm, text="Browse…",
                   command=lambda v=var, s=save: pick(v, s)).grid(row=i, column=2)

    opts = ttk.LabelFrame(root, text="Options", padding=10)
    opts.pack(fill="x", padx=10, pady=(4, 0))
    cb_phys = ttk.Checkbutton(opts, variable=physics_v,
                              text="Preserve appendage jiggle physics (collar / tie / wings)")
    cb_phys.grid(row=0, column=0, sticky="w", columnspan=2)
    cb_col = ttk.Checkbutton(opts, variable=collision_v,
                             text="Restore body collision for those bones")
    cb_col.grid(row=1, column=0, sticky="w", padx=(22, 0))
    ttk.Checkbutton(opts, variable=realign_v,
                    text="Realign body bones to the costume's rest pose (fixes offset ribbon/skirt)"
                    ).grid(row=2, column=0, sticky="w", columnspan=2)
    worldspace_v = tk.BooleanVar(value=True)
    ttk.Checkbutton(opts, variable=worldspace_v,
                    text="World-space the body mesh (so swinging ribbon/skirt render correctly)"
                    ).grid(row=3, column=0, sticky="w", columnspan=2)
    nodescale_v = tk.BooleanVar(value=True)
    ttk.Checkbutton(opts, variable=nodescale_v,
                    text="Re-anchor NodeScaling to realigned bones (keeps body shaping; "
                         "stops the in-game ribbon dropping to the chest)"
                    ).grid(row=4, column=0, sticky="w", columnspan=2)
    mask_v = tk.BooleanVar(value=True)
    ttk.Checkbutton(opts, variable=mask_v,
                    text="Special handling for masked / board-face models (Rina-chan board): "
                         "auto-detect, protect head + body-shape scaling"
                    ).grid(row=5, column=0, sticky="w", columnspan=2)
    mask_status = ttk.Label(opts, text="", foreground="#207a3c")
    mask_status.grid(row=6, column=0, sticky="w", columnspan=2, padx=(22, 0))

    def sync_collision_state(*_):
        cb_col.configure(state=("normal" if physics_v.get() else "disabled"))
    physics_v.trace_add("write", sync_collision_state)
    sync_collision_state()

    log_box = scrolledtext.ScrolledText(root, height=18, wrap="word",
                                        font=("TkFixedFont", 9))
    log_box.pack(fill="both", expand=True, padx=10, pady=8)

    msgq = queue.Queue()

    def drain():
        try:
            while True:
                item = msgq.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__mask_status__":
                    mask_status.configure(text=item[1])
                else:
                    log_box.insert("end", item)
                    log_box.see("end")
        except queue.Empty:
            pass
        root.after(80, drain)

    # auto-detect a masked / board-face target and report it in the status label
    def detect_target_model(*_):
        path = target_v.get().strip()
        if not path or not os.path.isfile(path):
            msgq.put(("__mask_status__", ""))
            return

        def _probe():
            try:
                info = detect_board_face_model_path(path)
            except Exception:
                info = None
            if info:
                msgq.put(("__mask_status__",
                          f"detected masked / board-face model "
                          f"({info['face_parts']} face parts, anchor "
                          f"{sorted(info['anchor_bones'])}) — special handling applies when checked"))
            else:
                msgq.put(("__mask_status__", "standard model — no special handling needed"))
        threading.Thread(target=_probe, daemon=True).start()
    target_v.trace_add("write", detect_target_model)

    class _QWriter:
        def write(self, s):
            if s:
                msgq.put(s)
        def flush(self):
            pass

    run_btn = ttk.Button(frm, text="Transplant")

    def worker(d, t, o, phys, col, realign, wspace, nscale, maskh):
        old = sys.stdout
        sys.stdout = _QWriter()
        try:
            transplant(d, t, o, verbose=True, preserve_physics=phys,
                       realign=realign, restore_collision=col, worldspace=wspace,
                       fix_nodescaling=nscale, mask_handling=maskh)
            ok = validate(o, verbose=True)
            print("\n[success] done — verified ✓\n" if ok
                  else "\n[error] output has dangling references!\n")
        except Exception as ex:
            import traceback
            print("\n[error] " + "".join(traceback.format_exception(ex)))
        finally:
            sys.stdout = old
            root.after(0, lambda: run_btn.configure(state="normal"))

    def go():
        d, t, o = donor_v.get().strip(), target_v.get().strip(), out_v.get().strip()
        if not (d and t and o):
            msgq.put("[error] choose donor, target and output first.\n")
            return
        log_box.delete("1.0", "end")
        run_btn.configure(state="disabled")
        threading.Thread(target=worker, daemon=True,
                         args=(d, t, o, physics_v.get(), collision_v.get(),
                               realign_v.get(), worldspace_v.get(),
                               nodescale_v.get(),
                               "auto" if mask_v.get() else "off")).start()

    run_btn.configure(command=go)
    run_btn.grid(row=len(rows), column=1, sticky="e", pady=8)

    drain()
    root.mainloop()


def main(argv=None):
    args = build_parser().parse_args(argv)
    want_gui = args.gui or not (args.donor or args.target or args.out)
    if want_gui and gui_available():
        run_gui()
        return
    if args.gui and not gui_available():
        print("[info] no graphical display available; falling back to CLI.")
    run_cli(args)


if __name__ == "__main__":
    main()
