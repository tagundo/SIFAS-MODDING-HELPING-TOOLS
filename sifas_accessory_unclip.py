#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SIFAS accessory un-clip — stop transplanted ornaments sinking into a resized body
=================================================================================
When you transplant a costume onto a character whose body is a different size
(``costume_transplant.py``), accessories worn over a resized region — a brooch on
the bust, a charm on the hips — can end up buried in it. The costume's own *cloth*
over that region is skinned to the region's bones, so it follows the wearer; the
accessory is anchored to the spine/hips **outside** that subtree, so it does not.
The more the wearer's region inflates, the further the cloth pushes out and the
deeper the (stationary) accessory sinks.

How a SIFAS body region gets its size
-------------------------------------
Region size is **not** baked into the mesh. A ``LiveCoreMemberNodeScaling``
component scales named nodes (``BreastSize``, ``HipsSize``, …) at runtime::

    Reference/Move/.../Spine2/BreastSize/LeftBreast_Dyna   <- bust cloth rides here
    Reference/Move/.../Spine2/PartsA_Offset/...            <- accessory rides here

``LeftBreast_Dyna`` / ``RightBreast_Dyna`` are children of ``BreastSize`` so the
bust cloth inflates with it; ``PartsA_Offset`` is a sibling of ``BreastSize`` so
the accessory does not move at all. The same holds for ``HipsSize`` and any other
scaled node. This tool walks **every** scaled node and lifts the accessories that
clip into it; nodes whose accessories already ride inside them (e.g. ``Move``,
which is the root of everything, or ``Head`` over the hair ornaments) self-exclude
because the accessory is a *descendant* of the node, not a sibling.

The fix
-------
For each chest accessory we compute the displacement it *would* receive if it
rode the ``BreastSize`` scaling, and bake that as a rigid translation of the
accessory's anchor bone::

    d   = (BreastSize_world)^-1 · anchor_world           (anchor in BreastSize space)
    Δ   = linear(BreastSize_world) · ((scale - 1) ⊙ d)   (matches how the cloth moves)
    anchor.m_LocalPosition += linear(parent_world)^-1 · Δ

This is computed entirely in the bundle's static (authored) frame, so any extra
runtime scaling above ``BreastSize`` (e.g. the body-wide ``Move`` node) is
applied to the accessory and the bust *equally* at runtime — exactly as it is
for the breast cloth. The whole accessory subtree moves as a rigid body, so its
shape and size are untouched; only its resting position rides out onto the
inflated bust. Its own jiggle physics keeps working relative to the new anchor.

Compared with re-parenting the accessory under ``BreastSize`` (which also fixes
the clipping) this keeps the ornament's authored size — re-parenting scales the
ornament by the bust factor (~1.16x in testing), visibly enlarging it.

This does NOT change the wearer's body shape or the costume; it only nudges the
accessory anchor. Run it on the *output* of a transplant.

Runs three ways:
  * a window (run with no arguments on a desktop),
  * a text menu (no arguments on a phone/Termux or a screenless server),
  * the command line:
        python3 sifas_accessory_unclip.py --in modded.unity --out fixed.unity
        python3 sifas_accessory_unclip.py --in modded.unity --report      # detect only
        python3 sifas_accessory_unclip.py --in m.unity --out f.unity --strength 1.2
        python3 sifas_accessory_unclip.py --in m.unity --out f.unity --anchors PartsA_Offset

Verified on Unity 2018.4 uncompressed SIFAS model bundles (float vertex streams).
"""

import os
import sys
import argparse
import importlib
import subprocess
import json as _json


# --------------------------------------------------------------------------
# self-contained multi-language support (English default; 한국어 / 日本語).
# Translations are embedded so this single file works on its own; the chosen
# language is remembered (and shared with the other SIFAS tools) via a small
# JSON config. Same scheme as fix_sifas_bundle_export.py / sifas_breast_tuner.py.
# --------------------------------------------------------------------------
class _LangStore:
    @staticmethod
    def _path():
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        return os.path.join(base, "sifas_modding_tools", "config.json")

    def get_language(self):
        try:
            with open(self._path(), encoding="utf-8") as f:
                return _json.load(f).get("language")
        except Exception:
            return None

    def set_language(self, code):
        try:
            p = self._path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            data = {}
            try:
                with open(p, encoding="utf-8") as f:
                    data = _json.load(f)
            except Exception:
                pass
            data["language"] = code
            with open(p, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


_shared_i18n = _LangStore()
_LANG_NAMES = (("en", "English"), ("ko", "한국어"), ("ja", "日本語"))
_TRANSLATIONS = {
    "ko": {
        "Language": "언어",
        "SIFAS Chest-Accessory Un-clip": "SIFAS 가슴 장식 언클립",
        "Lifts chest accessories that sank into a larger bust after a transplant, back onto it. Keeps the ornament's size and the body shape.":
            "이식 후 더 큰 가슴에 파묻힌 가슴 장식을 다시 가슴 위로 들어올립니다. 장식 크기와 체형은 그대로 둡니다.",
        "Lifts chest accessories that sank into a larger bust after a transplant.":
            "이식 후 더 큰 가슴에 파묻힌 가슴 장식을 다시 들어올립니다.",
        "Input bundle (transplant output)": "입력 번들 (이식 결과물)",
        "Output bundle": "출력 번들",
        "Browse…": "찾아보기…",
        "Report only (detect, don't write)": "탐지만 (저장 안 함)",
        "Also close gaps (shrunk regions)": "틈도 메우기 (작아진 부위)",
        "Lift strength": "리프트 강도",
        "Min bust overlap": "최소 가슴 겹침",
        "Anchors (optional, comma-separated)": "앵커 (선택, 쉼표 구분)",
        "Run": "실행",
        "Select bundle": "번들 선택",
        "Save fixed bundle": "수정된 번들 저장",
        "[error] choose an input bundle.\n": "[오류] 입력 번들을 선택하세요.\n",
        "[error] choose an output path (or tick Report only).\n": "[오류] 출력 경로를 선택하세요 (또는 '탐지만'을 체크).\n",
        "[error] strength and overlap must be numbers.\n": "[오류] 강도와 겹침은 숫자여야 합니다.\n",
        "Input bundle path: ": "입력 번들 경로: ",
        "Report only (just detect)? [y/N]: ": "탐지만 할까요? [y/N]: ",
        "Output bundle path (blank = <input>_unclip): ": "출력 번들 경로 (비우면 <입력>_unclip): ",
        "Lift strength [1.0]: ": "리프트 강도 [1.0]: ",
        "[error] no input given.": "[오류] 입력이 없습니다.",
    },
    "ja": {
        "Language": "言語",
        "SIFAS Chest-Accessory Un-clip": "SIFAS 胸アクセサリ クリップ解消",
        "Lifts chest accessories that sank into a larger bust after a transplant, back onto it. Keeps the ornament's size and the body shape.":
            "移植後に大きなバストへ埋もれた胸アクセサリを元の表面へ持ち上げます。装飾のサイズと体型はそのままです。",
        "Lifts chest accessories that sank into a larger bust after a transplant.":
            "移植後に大きなバストへ埋もれた胸アクセサリを持ち上げます。",
        "Input bundle (transplant output)": "入力バンドル（移植の出力）",
        "Output bundle": "出力バンドル",
        "Browse…": "参照…",
        "Report only (detect, don't write)": "検出のみ（書き込まない）",
        "Also close gaps (shrunk regions)": "隙間も詰める（縮小した部位）",
        "Lift strength": "リフト強度",
        "Min bust overlap": "最小バスト重なり",
        "Anchors (optional, comma-separated)": "アンカー（任意、カンマ区切り）",
        "Run": "実行",
        "Select bundle": "バンドルを選択",
        "Save fixed bundle": "修正済みバンドルを保存",
        "[error] choose an input bundle.\n": "[エラー] 入力バンドルを選んでください。\n",
        "[error] choose an output path (or tick Report only).\n": "[エラー] 出力先を選んでください（または「検出のみ」をチェック）。\n",
        "[error] strength and overlap must be numbers.\n": "[エラー] 強度と重なりは数値で指定してください。\n",
        "Input bundle path: ": "入力バンドルのパス: ",
        "Report only (just detect)? [y/N]: ": "検出のみにしますか？ [y/N]: ",
        "Output bundle path (blank = <input>_unclip): ": "出力バンドルのパス（空欄なら <入力>_unclip）: ",
        "Lift strength [1.0]: ": "リフト強度 [1.0]: ",
        "[error] no input given.": "[エラー] 入力がありません。",
    },
}


def _normalize_lang(code):
    c = str(code or "").strip().lower().replace("-", "_").split("_")[0].split(".")[0]
    if c in ("ko", "kr", "kor"):
        return "ko"
    if c in ("ja", "jp", "jpn"):
        return "ja"
    return "en"


_LANG = _normalize_lang(
    (_shared_i18n.get_language() if _shared_i18n is not None else None)
    or os.environ.get("SIFAS_LANG", "en")
)


def _get_lang():
    return _LANG


def _set_lang(code, **_kw):
    global _LANG
    _LANG = _normalize_lang(code)
    _shared_i18n.set_language(_LANG)
    return _LANG


def _lang_opts():
    return list(_LANG_NAMES)


def _tr(text, **kw):
    s = _TRANSLATIONS.get(_LANG, {}).get(text, text)
    if not kw:
        return s
    try:
        return s.format(**kw)
    except Exception:
        return s


def ensure_module(import_name, pip_name=None):
    try:
        return importlib.import_module(import_name)
    except ImportError:
        pip_name = pip_name or import_name
        print(f"[setup] installing {pip_name} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])
        return importlib.import_module(import_name)


UnityPy = ensure_module("UnityPy")
np = ensure_module("numpy")


# --------------------------------------------------------------------------
# Standard body bones — never treated as an accessory. Everything else hanging
# off the skeleton (Skirt*, Sleeve*, Ribbon*, Parts*, *_Offset, *_Dyna chains,
# capes, collars) is costume. The breast bones are body identity and excluded.
# --------------------------------------------------------------------------
_BODY_EXACT = {
    "Reference", "Move", "Position", "Center", "Hips_Position", "Hips",
    "Spine", "Spine1", "Spine2", "Neck", "Neck1", "Head", "BreastSize",
}
_BODY_PREFIX = (
    "Head_",                       # Head_All / Head_Face / Head_Hair scaffold
)
_BODY_LIMB_SUFFIX = (
    "Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase", "Toe",
    "HandThumb", "HandIndex", "HandMiddle", "HandRing", "HandPinky",
    "HandThumb1", "HandThumb2", "HandThumb3",
)


def is_body_bone(name):
    if name is None:
        return True
    if name in _BODY_EXACT:
        return True
    if "Breast" in name:                       # body identity, not costume
        return True
    for p in _BODY_PREFIX:
        if name.startswith(p):
            return True
    for side in ("Left", "Right"):
        if name.startswith(side):
            rest = name[len(side):]
            if rest in _BODY_LIMB_SUFFIX:
                return True
    return False


# --------------------------------------------------------------------------
# vertex-stream decode (same layout maths as the other SIFAS mesh tools)
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


def _read_chan(u8, chans, attr, stride, start, vc, dtype):
    if attr >= len(chans):
        return None
    ch = chans[attr]
    if ch.get("dimension", 0) == 0:
        return None
    s, off, dim = ch["stream"], ch["offset"], ch["dimension"]
    blk = u8[start[s]:start[s] + vc * stride[s]].reshape(vc, stride[s])
    return blk[:, off:off + dim * 4].copy().view(dtype).reshape(vc, dim)


def _qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]], float)


def _trs(t, q, s):
    L = np.eye(4); L[:3, :3] = _qmat(q) @ np.diag(s); L[:3, 3] = t
    return L


def _bp_mat(b):
    return np.array([[b['e00'], b['e01'], b['e02'], b['e03']], [b['e10'], b['e11'], b['e12'], b['e13']],
                     [b['e20'], b['e21'], b['e22'], b['e23']], [b['e30'], b['e31'], b['e32'], b['e33']]], float)


# --------------------------------------------------------------------------
# model graph
# --------------------------------------------------------------------------
class Model:
    def __init__(self, path):
        self.env = UnityPy.load(path)
        self.objs = list(self.env.objects)
        self.uid = {o.path_id: o for o in self.objs}
        self.go_name = {}
        self.tf = {}            # tf path_id -> typetree
        self.tf_obj = {}        # tf path_id -> object (for save)
        self.go_of_tf = {}
        self.tf_of_go = {}
        self.mb, self.smr, self.mesh = [], [], {}
        for o in self.objs:
            n = o.type.name
            if n == "GameObject":
                self.go_name[o.path_id] = o.read_typetree().get("m_Name", "?")
            elif n == "Transform":
                d = o.read_typetree(); self.tf[o.path_id] = d; self.tf_obj[o.path_id] = o
                gp = d.get("m_GameObject", {}).get("m_PathID")
                self.go_of_tf[o.path_id] = gp; self.tf_of_go[gp] = o.path_id
            elif n == "MonoBehaviour":
                self.mb.append(o)
            elif n == "SkinnedMeshRenderer":
                self.smr.append(o)
            elif n == "Mesh":
                self.mesh[o.path_id] = o
        self.children = {}
        for t, d in self.tf.items():
            fa = d.get("m_Father", {}).get("m_PathID")
            self.children.setdefault(fa, []).append(t)
        self._world = None

    def name(self, tfpid):
        return self.go_name.get(self.go_of_tf.get(tfpid), None)

    def tfpid_of(self, name):
        for t in self.tf:
            if self.name(t) == name:
                return t
        return None

    def father(self, tfpid):
        fa = self.tf.get(tfpid, {}).get("m_Father", {}).get("m_PathID")
        return fa if fa else None

    def world(self):
        """static world matrices (file-stored local TRS)."""
        if self._world is not None:
            return self._world
        W = {}

        def rec(t, P):
            d = self.tf[t]; p = d["m_LocalPosition"]; q = d["m_LocalRotation"]; s = d["m_LocalScale"]
            M = P @ _trs((p["x"], p["y"], p["z"]), (q["x"], q["y"], q["z"], q["w"]), (s["x"], s["y"], s["z"]))
            W[t] = M
            for c in self.children.get(t, []):
                if c in self.tf:
                    rec(c, M)
        for t, d in self.tf.items():
            if self.father(t) not in self.tf:
                rec(t, np.eye(4))
        self._world = W
        return W

    def node_scalings(self):
        """{node_name: (sx,sy,sz)} from LiveCoreMemberNodeScaling."""
        out = {}
        for o in self.mb:
            try:
                d = o.read_typetree()
            except Exception:
                continue                  # MonoBehaviour with no readable type tree
            if isinstance(d.get("scaleValues"), list):
                for e in d["scaleValues"]:
                    tgt = e.get("target", {}).get("m_PathID")
                    sv = e.get("scaledValue", {})
                    nm = self.name(tgt)
                    if nm:
                        out[nm] = (sv.get("x", 1.0), sv.get("y", 1.0), sv.get("z", 1.0))
        return out

    def costume_smr(self):
        if not self.smr:
            return None
        return max(self.smr, key=lambda o: len(o.read_typetree().get("m_Bones", [])))


def is_descendant(model, tfpid, ancestor):
    cur = tfpid
    seen = set()
    while cur is not None and cur not in seen:
        if cur == ancestor:
            return True
        seen.add(cur)
        cur = model.father(cur)
    return False


def subtree_tfpids(model, tfpid):
    """All transform path_ids at or below tfpid (inclusive)."""
    out = set()
    stack = [tfpid]
    while stack:
        c = stack.pop()
        if c in out:
            continue
        out.add(c)
        stack.extend(model.children.get(c, []))
    return out


# --------------------------------------------------------------------------
# detection: which accessory anchors sit over the bust
# --------------------------------------------------------------------------
def analyze(model):
    """Generic node-scaling analysis. Returns a dict::

        {
          "world":  {tfpid: 4x4},
          "nodes":  [{name, tf, scale, region(3D bbox or None), subtree(set of tfpid)}],
          "anchors":[{name, tfpid, n_verts, centroid, overlaps:{node_name: frac}}],
        }

    A "node" is any transform driven by a ``LiveCoreMemberNodeScaling`` entry
    (BreastSize, HipsSize, Move, Head, …). Its *region* is the xy bounding box of
    the costume cloth skinned to bones inside that node — the surface an accessory
    must clear. An "anchor" is a costume bone hanging directly off a body bone; for
    each scaled node it is NOT a descendant of, we record how much of its mesh
    overlaps that node's region. The caller picks, per anchor, the best-overlapping
    eligible node and lifts by that node's scale."""
    W = model.world()
    scal = model.node_scalings()

    smr = model.costume_smr()
    if smr is None:
        return {"world": W, "nodes": [], "anchors": [], "skin_ok": False}
    sd = smr.read_typetree()
    bones = [b["m_PathID"] for b in sd.get("m_Bones", [])]
    bnames = [model.name(b) for b in bones]
    mobj = model.mesh.get(sd.get("m_Mesh", {}).get("m_PathID"))
    if mobj is None:
        return {"world": W, "nodes": [], "anchors": [], "skin_ok": False}
    mt = mobj.read_typetree()
    BP = [_bp_mat(b) for b in mt["m_BindPose"]]
    vc, chans, stride, start = _stream_layout(mt)
    u8 = np.frombuffer(mt["m_VertexData"]["m_DataSize"], np.uint8)
    pos = _read_chan(u8, chans, 0, stride, start, vc, "<f4")
    wgt = _read_chan(u8, chans, 12, stride, start, vc, "<f4")
    idx = _read_chan(u8, chans, 13, stride, start, vc, "<u4")
    if pos is None or wgt is None or idx is None or len(BP) != len(bones):
        # compressed mesh / m_VariableBoneCountWeights / stripped bindpose: can't skin
        return {"world": W, "nodes": [], "anchors": [], "skin_ok": False}
    pos = pos.astype(np.float64); wgt = wgt.astype(np.float64)
    idx = np.clip(idx.astype(np.int64), 0, len(bones) - 1)   # zero-weight slots may hold stale indices

    # static skin == authored vertices (bundle is world-space baked), but skin
    # explicitly so this also works on un-baked bundles. Missing bone transforms
    # (null/external m_Bones) fall back to identity rather than crashing.
    BW = np.array([(W[b] if b in W else np.eye(4)) @ BP[i] for i, b in enumerate(bones)])
    ph = np.c_[pos, np.ones(vc)]
    wp = np.zeros((vc, 3))
    for k in range(4):
        wp += wgt[:, k:k + 1] * np.einsum('vij,vj->vi', BW[idx[:, k]], ph)[:, :3]

    dom = idx[np.arange(vc), np.argmax(wgt, axis=1)]
    domname = np.array([bnames[i] for i in dom])

    # every scaled node -> its subtree + the cloth region that inflates with it
    nodes = []
    for nm, scale in scal.items():
        tf = model.tfpid_of(nm)
        if tf is None:
            continue
        sub = subtree_tfpids(model, tf)
        sub_names = {model.name(x) for x in sub}
        rmask = np.isin(domname, list(sub_names))
        if rmask.sum() >= 8:
            rv = wp[rmask]
            region = (rv[:, 0].min(), rv[:, 0].max(), rv[:, 1].min(), rv[:, 1].max(),
                      rv[:, 2].min(), rv[:, 2].max())   # 3D bbox (x, y, z=depth)
        else:
            region = None
        nodes.append(dict(name=nm, tf=tf, scale=scale, region=region, subtree=sub))

    # accessory anchors: a costume bone whose parent is a body bone
    anchors = []
    for t in model.tf:
        nm = model.name(t)
        if nm is None or is_body_bone(nm):
            continue
        pn = model.name(model.father(t))
        if pn is None or not is_body_bone(pn):
            continue                      # anchor must hang directly off a body bone
            # (skips the mesh-root node and accessory bones nested under other costume bones)
        sub_names = {model.name(x) for x in subtree_tfpids(model, t)}
        vmask = np.isin(domname, list(sub_names))
        n = int(vmask.sum())
        if n == 0:
            continue
        av = wp[vmask]
        overlaps = {}
        for nd in nodes:
            if nd["region"] is None:
                continue
            if t in nd["subtree"]:
                continue                  # already rides this node — nothing to fix
            bb = nd["region"]
            zm = bb[5] - bb[4]            # allow an accessory to sit in front of the cloth,
            inx = ((av[:, 0] >= bb[0]) & (av[:, 0] <= bb[1]) &      # but reject one clearly
                   (av[:, 1] >= bb[2]) & (av[:, 1] <= bb[3]) &      # behind/elsewhere in depth
                   (av[:, 2] >= bb[4] - zm) & (av[:, 2] <= bb[5] + zm))
            overlaps[nd["name"]] = float(inx.mean())
        anchors.append(dict(name=nm, tfpid=t, n_verts=n, centroid=av.mean(0), overlaps=overlaps))
    return {"world": W, "nodes": nodes, "anchors": anchors, "skin_ok": True}


# --------------------------------------------------------------------------
# the lift
# --------------------------------------------------------------------------
def lift_vector(W, node_tf, point_world, scale, strength):
    """world-space displacement of a point under `node_tf`'s runtime scaling. The
    cloth's motion is a position-dependent field (grows with distance from the node
    pivot), so we evaluate it at the accessory's own geometry, not just its anchor
    origin. Works for any scaled node (BreastSize, HipsSize, …) and for scale<1 (a
    negative lift that closes the gap to a *smaller* surface)."""
    Mn = W[node_tf]
    p = np.asarray(point_world, float)
    d = np.linalg.inv(Mn) @ np.array([p[0], p[1], p[2], 1.0])       # point in node space
    s = np.array(scale, float)
    disp_local = (s - 1.0) * strength * d[:3]
    return Mn[:3, :3] @ disp_local                                  # -> world


def apply(model, jobs, strength, report_only):
    """jobs: list of (anchor_dict, node_tf, scale). Each anchor's whole subtree is
    rigidly translated by lifting its anchor's m_LocalPosition. The lift is the cloth
    displacement evaluated at the accessory's vertex centroid."""
    W = model.world()
    changes = []
    for a, node_tf, scale in jobs:
        t = a["tfpid"]
        eval_pt = a.get("centroid")
        if eval_pt is None:
            eval_pt = W[t][:3, 3]
        try:
            delta_world = lift_vector(W, node_tf, eval_pt, scale, strength)
            fa = model.father(t)
            Rp = W[fa][:3, :3] if fa in W else np.eye(3)
            delta_local = np.linalg.inv(Rp) @ delta_world
        except np.linalg.LinAlgError:
            print(f"[warn] skipping {a['name']}: singular transform on its lift chain.")
            continue
        changes.append((a, delta_world, delta_local))
        if not report_only:
            d = model.tf[t]
            lp = d["m_LocalPosition"]
            lp["x"] = float(lp["x"] + delta_local[0])
            lp["y"] = float(lp["y"] + delta_local[1])
            lp["z"] = float(lp["z"] + delta_local[2])
            model.tf_obj[t].save_typetree(d)
    return changes


def save_bundle(model, out_path):
    bf = list(model.env.files.values())[0]
    data = bf.save(packer="original")          # serialize first — UnityPy may still
    with open(out_path, "wb") as f:            # read lazily from the source until now
        f.write(data)


# --------------------------------------------------------------------------
# high-level routine shared by the window, the menu and the command line
# --------------------------------------------------------------------------
def _node_eligible(scale, close_gaps, eps=1e-3):
    """A scaled node is worth acting on when it enlarges its region (accessories
    sink) or — with close_gaps — when it shrinks it (accessories float in a gap)."""
    mx, mn = max(scale), min(scale)
    if mx > 1.0 + eps:
        return True
    if close_gaps and mn < 1.0 - eps:
        return True
    return False


def process(inp, out=None, report=False, strength=1.0, overlap=0.15, anchors=None,
            close_gaps=False, verbose=True):
    """Detect accessories that clip into any runtime-scaled body region (bust, hips,
    …) and (unless report) lift each onto its region. Prints a technical log; returns
    a small summary dict. Writes a new bundle when an output path is given and report
    is False."""
    def log(*a):
        if verbose:
            print(*a)

    will_write = bool(out) and not report
    if will_write and os.path.abspath(out) == os.path.abspath(inp):
        log("[error] output path equals input path — pick a different output.")
        return {"status": "bad_output"}

    model = Model(inp)
    info = analyze(model)
    nodes = info["nodes"]
    found = info["anchors"]
    node_by_name = {nd["name"]: nd for nd in nodes}

    if not info.get("skin_ok", True):
        log("[skip] couldn't read the costume mesh skinning (no SkinnedMeshRenderer, or "
            "compressed / variable-bone-count weights) — cannot detect accessories.")
        return {"status": "no_skin"}
    if not nodes:
        log("[skip] no LiveCoreMemberNodeScaling nodes found — nothing to do.")
        return {"status": "no_scaling"}

    eligible = {nd["name"] for nd in nodes if _node_eligible(nd["scale"], close_gaps)}
    log("[scan] runtime node scalings:")
    for nd in sorted(nodes, key=lambda n: n["name"]):
        sx, sy, sz = nd["scale"]
        tag = "act " if nd["name"] in eligible else ("skip" if nd["region"] else "----")
        log(f"   [{tag}] {nd['name']:16s} scale=({sx:.3f},{sy:.3f},{sz:.3f})"
            + ("" if nd["region"] is not None else "  (no cloth region)"))

    # assign each anchor to the eligible node it overlaps most
    for a in found:
        best, frac = None, 0.0
        for nm, f in a["overlaps"].items():
            if nm in eligible and f > frac:
                best, frac = nm, f
        a["_node"], a["_overlap"] = best, frac

    log("[scan] candidate accessories (best scaled-region overlap):")
    for a in sorted(found, key=lambda x: -x["_overlap"]):
        will = a["_node"] is not None and a["_overlap"] >= overlap
        flag = "FIX " if will else "    "
        tgt = f"-> {a['_node']}" if a["_node"] else ""
        log(f"   [{flag}] {a['name']:22s} verts={a['n_verts']:4d}  overlap={a['_overlap']*100:5.1f}% {tgt}")

    if anchors:
        if isinstance(anchors, str):
            anchors = anchors.split(",")
        wanted = {x.strip() for x in anchors if str(x).strip()}
        chosen = [a for a in found if a["name"] in wanted]
        missing = wanted - {a["name"] for a in chosen}
        if missing:
            log(f"[warn] requested anchors not found / not liftable: {sorted(missing)}")
        chosen = [a for a in chosen if a["_node"] is not None]
    else:
        chosen = [a for a in found if a["_node"] is not None and a["_overlap"] >= overlap]

    if not chosen:
        log("[done] no accessory met the overlap threshold on an eligible node; nothing to lift.")
        return {"status": "nothing", "nodes": {nd["name"]: nd["scale"] for nd in nodes}}

    jobs = [(a, node_by_name[a["_node"]]["tf"], node_by_name[a["_node"]]["scale"]) for a in chosen]
    changes = apply(model, jobs, strength, report_only=(report or not out))
    log(f"\n[lift] {len(changes)} accessory anchor(s):")
    for (a, dw, dl), (_, _, _scale) in zip(changes, jobs):
        log(f"   {a['name']:22s} via {a['_node']:12s} |Δ|={np.linalg.norm(dw) * 1000:5.1f} mm  "
            f"world Δ=({dw[0] * 1000:+.1f},{dw[1] * 1000:+.1f},{dw[2] * 1000:+.1f}) mm")

    if report or not out:
        log("\n[report] no file written (use an output path to save).")
        return {"status": "report", "lifted": [c[0]["name"] for c in changes]}

    save_bundle(model, out)
    log(f"\n[ok] wrote {out}")
    return {"status": "written", "out": out, "lifted": [c[0]["name"] for c in changes]}


# --------------------------------------------------------------------------
# window (tkinter) — falls back to the text menu when no display is available
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

    root = tk.Tk()
    root.geometry("800x620")

    _i18n_widgets = []

    def _reg(widget, key, kind="text"):
        _i18n_widgets.append((widget, key, kind))
        return widget

    def _apply_i18n():
        root.title(_tr("SIFAS Chest-Accessory Un-clip"))
        for w, key, kind in _i18n_widgets:
            try:
                w.configure(**{kind: _tr(key)})
            except Exception:
                pass

    # language picker (top-right)
    topbar = ttk.Frame(root)
    topbar.pack(fill="x", padx=10, pady=(8, 0))
    _names = [n for _c, n in _lang_opts()]
    _code_by_name = {n: c for c, n in _lang_opts()}
    _name_by_code = {c: n for c, n in _lang_opts()}
    _lang_var = tk.StringVar(value=_name_by_code.get(_get_lang(), _names[0]))
    _reg(ttk.Label(topbar, text=_tr("Language")), "Language").pack(side="left")
    _lang_cb = ttk.Combobox(topbar, textvariable=_lang_var, values=_names, state="readonly", width=10)
    _lang_cb.pack(side="left", padx=(6, 0))
    _lang_cb.bind("<<ComboboxSelected>>",
                  lambda e: (_set_lang(_code_by_name[_lang_var.get()]), _apply_i18n()))

    _desc = ("Lifts chest accessories that sank into a larger bust after a transplant, "
             "back onto it. Keeps the ornament's size and the body shape.")
    _reg(ttk.Label(root, padding=(10, 4), foreground="#555", wraplength=760, text=_tr(_desc)),
         _desc).pack(anchor="w")

    frm = ttk.Frame(root, padding=8)
    frm.pack(fill="x")
    in_v, out_v = tk.StringVar(), tk.StringVar()
    report_v = tk.BooleanVar(value=False)
    closegaps_v = tk.BooleanVar(value=False)
    strength_v = tk.StringVar(value="1.0")
    overlap_v = tk.StringVar(value="0.15")
    anchors_v = tk.StringVar(value="")

    def suggest_out(*_):
        if not out_v.get() and in_v.get():
            base, ext = os.path.splitext(in_v.get())
            out_v.set(base + "_unclip" + (ext or ".unity"))

    def pick(var, save=False):
        ft = [("Unity bundle", "*.unity *.unity3d"), ("All files", "*.*")]
        path = (filedialog.asksaveasfilename(title=_tr("Save fixed bundle"),
                                             defaultextension=".unity", filetypes=ft) if save
                else filedialog.askopenfilename(title=_tr("Select bundle"), filetypes=ft))
        if path:
            var.set(path); suggest_out()

    for i, (label, var, save) in enumerate(
            [("Input bundle (transplant output)", in_v, False), ("Output bundle", out_v, True)]):
        _reg(ttk.Label(frm, text=_tr(label), width=28), label).grid(row=i, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=var, width=54).grid(row=i, column=1, padx=4)
        _reg(ttk.Button(frm, text=_tr("Browse…"),
                        command=lambda v=var, s=save: pick(v, s)), "Browse…").grid(row=i, column=2)

    opt = ttk.Frame(root, padding=(10, 2))
    opt.pack(fill="x")
    _reg(ttk.Checkbutton(opt, text=_tr("Report only (detect, don't write)"), variable=report_v),
         "Report only (detect, don't write)").grid(row=0, column=0, columnspan=2, sticky="w", pady=2)
    _reg(ttk.Checkbutton(opt, text=_tr("Also close gaps (shrunk regions)"), variable=closegaps_v),
         "Also close gaps (shrunk regions)").grid(row=0, column=2, columnspan=2, sticky="w", pady=2)
    _reg(ttk.Label(opt, text=_tr("Lift strength")), "Lift strength").grid(row=1, column=0, sticky="w", pady=2)
    ttk.Entry(opt, textvariable=strength_v, width=8).grid(row=1, column=1, sticky="w")
    _reg(ttk.Label(opt, text=_tr("Min bust overlap")), "Min bust overlap").grid(row=2, column=0, sticky="w", pady=2)
    ttk.Entry(opt, textvariable=overlap_v, width=8).grid(row=2, column=1, sticky="w")
    _reg(ttk.Label(opt, text=_tr("Anchors (optional, comma-separated)")),
         "Anchors (optional, comma-separated)").grid(row=3, column=0, sticky="w", pady=2)
    ttk.Entry(opt, textvariable=anchors_v, width=40).grid(row=3, column=1, sticky="w")

    msgq = queue.Queue()
    busy = {"n": 0}

    class _W:
        def write(self, s):
            if s:
                msgq.put(s)

        def flush(self):
            pass

    def run_thread(fn):
        busy["n"] += 1
        run_btn.configure(state="disabled")

        def wrap():
            old = sys.stdout
            sys.stdout = _W()
            try:
                fn()
            except Exception as ex:
                import traceback
                print("\n[error] " + "".join(
                    traceback.format_exception(type(ex), ex, ex.__traceback__)))
            finally:
                sys.stdout = old

                def done():
                    busy["n"] -= 1
                    if busy["n"] == 0:
                        run_btn.configure(state="normal")
                root.after(0, done)
        threading.Thread(target=wrap, daemon=True).start()

    def go():
        s = in_v.get().strip()
        o = out_v.get().strip()
        rep = report_v.get()
        log_box.delete("1.0", "end")
        if not s:
            msgq.put(_tr("[error] choose an input bundle.\n")); return
        if not rep and not o:
            msgq.put(_tr("[error] choose an output path (or tick Report only).\n")); return
        try:
            strength = float(strength_v.get() or "1.0")
            ov = float(overlap_v.get() or "0.15")
        except ValueError:
            msgq.put(_tr("[error] strength and overlap must be numbers.\n")); return
        anchors = anchors_v.get().strip() or None
        cg = closegaps_v.get()
        run_thread(lambda: process(s, None if rep else o, report=rep,
                                   strength=strength, overlap=ov, anchors=anchors, close_gaps=cg))

    run_btn = _reg(ttk.Button(root, text=_tr("Run"), command=go), "Run")
    run_btn.pack(pady=6)

    log_box = scrolledtext.ScrolledText(root, height=16, wrap="word", font=("TkFixedFont", 9))
    log_box.pack(fill="both", expand=True, padx=10, pady=8)

    def drain():
        try:
            while True:
                log_box.insert("end", msgq.get_nowait()); log_box.see("end")
        except queue.Empty:
            pass
        root.after(80, drain)

    _apply_i18n()
    drain()
    root.mainloop()


# --------------------------------------------------------------------------
# text menu (phone / Termux / screenless server)
# --------------------------------------------------------------------------
def _ask(prompt):
    try:
        return input(_tr(prompt))
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def run_menu():
    print("== " + _tr("SIFAS Chest-Accessory Un-clip") + " ==")
    print(_tr("Lifts chest accessories that sank into a larger bust after a transplant."))
    inp = _ask("Input bundle path: ")
    if inp is None:
        return 0
    inp = inp.strip().strip('"').strip("'")
    if not inp:
        print(_tr("[error] no input given."))
        return 1
    rep_ans = _ask("Report only (just detect)? [y/N]: ")
    rep = bool(rep_ans) and rep_ans.strip().lower().startswith("y")
    out = None
    if not rep:
        out = (_ask("Output bundle path (blank = <input>_unclip): ") or "").strip().strip('"').strip("'")
        if not out:
            base, ext = os.path.splitext(inp)
            out = base + "_unclip" + (ext or ".unity")
    s = (_ask("Lift strength [1.0]: ") or "").strip()
    try:
        strength = float(s) if s else 1.0
    except ValueError:
        strength = 1.0
    cg_ans = _ask("Also close gaps on shrunk regions? [y/N]: ")
    cg = bool(cg_ans) and cg_ans.strip().lower().startswith("y")
    process(inp, out, report=rep, strength=strength, close_gaps=cg)
    return 0


# --------------------------------------------------------------------------
# CLI / dispatch
# --------------------------------------------------------------------------
def build_parser():
    ap = argparse.ArgumentParser(
        description="Lift chest accessories so they ride the wearer's bust instead of sinking into it. "
                    "Run with no arguments for the window / text menu.")
    ap.add_argument("--in", dest="inp", help="input bundle (a transplant output)")
    ap.add_argument("--out", dest="out", help="output bundle (omit with --report)")
    ap.add_argument("--report", action="store_true", help="only detect/print chest accessories, write nothing")
    ap.add_argument("--strength", type=float, default=1.0, help="lift multiplier (1.0 = match the bust exactly)")
    ap.add_argument("--overlap", type=float, default=0.15, help="min bust-overlap fraction to treat a part as a chest accessory")
    ap.add_argument("--anchors", default=None, help="comma-separated anchor bone names to force (skip auto-detect)")
    ap.add_argument("--close-gaps", dest="close_gaps", action="store_true",
                    help="also pull accessories IN when a region was shrunk (scale < 1), not just push out when enlarged")
    ap.add_argument("--gui", action="store_true", help="force the graphical window")
    ap.add_argument("--menu", action="store_true", help="force the text menu")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.menu:
        if args.inp or args.out:
            print("[info] --menu ignores --in/--out; enter the paths at the prompts.")
        return run_menu()

    want_gui = args.gui or not (args.inp or args.out or args.report)
    if want_gui and gui_available():
        run_gui()
        return 0
    if args.gui:
        print("[info] no graphical display available; falling back.")

    if not args.inp:
        # partial CLI intent without --in: fail loudly instead of silently dropping to the menu
        if args.out or args.report or args.anchors or args.close_gaps:
            build_parser().error("--in is required when using --out/--report/--anchors/--close-gaps")
        if sys.stdin and sys.stdin.isatty():
            return run_menu()
        build_parser().error("--in is required (or run with no arguments for the window / menu)")

    process(args.inp, args.out, report=args.report, strength=args.strength,
            overlap=args.overlap, anchors=args.anchors, close_gaps=args.close_gaps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
